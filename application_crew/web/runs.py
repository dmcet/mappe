"""Run (application) routes: create, inspect, gate actions, edit, downloads, delete."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from application_crew.config import get_settings
from application_crew.db import CV, Event, Run, Usage
from application_crew.domain.models import ParsedCV, Requirement
from application_crew.runner.engine import InvalidTransition, run_title, set_status
from application_crew.runner.states import WORKING, CVStatus, RunStatus
from application_crew.steps.final import DocumentEdit, bundle, final_draft, save_user_draft
from application_crew.web.deps import SessionDep, engine_of, remove_run
from application_crew.web.live import MODEL_NAMES
from application_crew.web.pipeline import pipeline

router = APIRouter(prefix="/api/runs")


class RunCreate(BaseModel):
    cv_id: int
    urls: list[str] = Field(default_factory=list)
    listing_text: str = ""
    requirements: list[Requirement] = Field(default_factory=list)


class ListingText(BaseModel):
    listing_text: str


class ApplyDecision(BaseModel):
    cover_letter: bool = False


def _get(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Application not found")
    return run


def _resume(request: Request, session: Session, run: Run, target: RunStatus) -> dict:
    """Move a run out of a user gate and hand it back to the engine."""
    try:
        set_status(session, run, target)
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    if target in WORKING:
        engine_of(request).enqueue(run.id)  # type: ignore[arg-type]
    return run_detail(session, run)


def run_summary(run: Run) -> dict:
    state = run.state or {}
    listing = state.get("listing") or {}
    match = state.get("match") or {}
    return {
        "id": run.id,
        "cv_id": run.cv_id,
        "title": run_title(run),
        "company": listing.get("company"),
        "listing_url": run.listing_url,
        "status": str(run.status),
        "error": run.error,
        "verdict": match.get("verdict"),
        "score": match.get("score"),
        "cost_usd": run.cost_usd,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "pipeline": pipeline(
            run.status, state.get("previous_status"), len(state.get("drafts", []))
        ),
    }


def _facts(cv_data: dict | None) -> dict[str, str]:
    """Fact ID -> short label, so the UI can show what a fact ID refers to."""
    if not cv_data:
        return {}
    cv = ParsedCV.model_validate(cv_data)
    texts = {}
    for p in cv.positions:
        texts[p.id] = f"{p.role} · {p.company}"
        for f in p.responsibilities + p.achievements:
            texts[f.id] = f"{p.role} · {p.company}: {f.text}"
    for e in cv.education:
        texts[e.id] = f"{e.qualification}, {e.institution}"
    for c in cv.certifications:
        texts[c.id] = c.name
    for f in cv.projects + cv.publications + cv.volunteering:
        texts[f.id] = f.text
    return texts


def _drafts(drafts: list[dict] | None) -> list[dict] | None:
    """Drafts in the current shape (older drafts named title IDs "position_id")."""
    if drafts is None:
        return None
    out = []
    for d in drafts:
        cv = d.get("cv") or {}
        titles = [
            {"id": t.get("id") or t.get("position_id"), "title": t.get("title", "")}
            for t in cv.get("titles", [])
        ]
        out.append(d | {"cv": cv | {"titles": titles}})
    return out


def run_detail(session: Session, run: Run) -> dict:
    state = run.state or {}
    events = session.exec(
        select(Event).where(Event.run_id == run.id).order_by(Event.id.desc()).limit(300)  # type: ignore[union-attr]
    ).all()
    usage = session.exec(select(Usage).where(Usage.run_id == run.id).order_by(Usage.id)).all()
    keys = [
        "listing", "requirement_results", "analysis", "match", "match_warnings",
        "cover_letter_suggested", "decision", "drafts", "final_draft", "review_stop_reason",
        "delivery", "cv", "fetch",
    ]  # fmt: skip
    return run_summary(run) | {
        "requirements": run.requirements,
        "has_listing_text": bool(run.listing_text),
        "previous_status": state.get("previous_status"),
        "state": {k: state.get(k) for k in keys} | {"drafts": _drafts(state.get("drafts"))},
        "facts": _facts(state.get("cv")),
        "events": [
            {"id": e.id, "kind": e.kind, "message": e.message, "at": e.created_at}
            for e in reversed(events)
        ],
        "usage": [
            {
                "step": u.step,
                "model": MODEL_NAMES.get(u.model, u.model),
                "cost_usd": u.cost_usd,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "cache_read_tokens": u.cache_read_tokens,
                "at": u.created_at,
            }
            for u in usage
        ],
    }


@router.get("")
def list_runs(session: SessionDep) -> list[dict]:
    runs = session.exec(select(Run).order_by(Run.created_at.desc())).all()  # type: ignore[attr-defined]
    return [run_summary(r) for r in runs]


@router.get("/requirements/last")
def last_requirements(session: SessionDep) -> list[dict]:
    """The requirements of the most recent application, to pre-fill the form."""
    run = session.exec(select(Run).order_by(Run.created_at.desc()).limit(1)).first()  # type: ignore[attr-defined]
    return run.requirements if run else []


@router.post("", status_code=201)
def create_runs(body: RunCreate, request: Request, session: SessionDep) -> list[dict]:
    cv = session.get(CV, body.cv_id)
    if cv is None:
        raise HTTPException(404, "CV not found")
    if cv.status != CVStatus.CONFIRMED:
        raise HTTPException(409, "Confirm the CV before starting an application")
    reqs = [r.model_dump(mode="json") for r in body.requirements]
    runs = [
        Run(cv_id=cv.id, listing_url=u.strip(), requirements=reqs) for u in body.urls if u.strip()
    ]
    if body.listing_text.strip():
        runs.append(Run(cv_id=cv.id, listing_text=body.listing_text.strip(), requirements=reqs))
    if not runs:
        raise HTTPException(400, "Provide at least one URL or a pasted listing")
    session.add_all(runs)
    session.commit()
    for run in runs:
        engine_of(request).enqueue(run.id)  # type: ignore[arg-type]
    return [run_summary(r) for r in runs]


@router.get("/{run_id}")
def get_run(run_id: int, session: SessionDep) -> dict:
    return run_detail(session, _get(session, run_id))


@router.post("/{run_id}/listing-text")
def submit_listing_text(
    run_id: int, body: ListingText, request: Request, session: SessionDep
) -> dict:
    run = _get(session, run_id)
    if not body.listing_text.strip():
        raise HTTPException(400, "Paste the listing text")
    run.listing_text = body.listing_text.strip()
    return _resume(request, session, run, RunStatus.PARSING_LISTING)


@router.post("/{run_id}/continue")
def continue_run(run_id: int, request: Request, session: SessionDep) -> dict:
    """Override failed must-have requirements and continue with matching."""
    return _resume(request, session, _get(session, run_id), RunStatus.MATCHING)


@router.post("/{run_id}/decline")
def decline_run(run_id: int, request: Request, session: SessionDep) -> dict:
    return _resume(request, session, _get(session, run_id), RunStatus.DECLINED)


@router.post("/{run_id}/apply")
def apply_run(run_id: int, body: ApplyDecision, request: Request, session: SessionDep) -> dict:
    run = _get(session, run_id)
    if run.status != RunStatus.WAITING_FOR_APPLY_DECISION:
        raise HTTPException(409, "The application is not waiting for an apply decision")
    run.state = run.state | {"decision": {"cover_letter": body.cover_letter}}
    return _resume(request, session, run, RunStatus.AUTHORING)


@router.put("/{run_id}/documents")
def save_documents(run_id: int, body: DocumentEdit, session: SessionDep) -> dict:
    """Save the user's edits as a new draft (rendered and checked, no AI calls)."""
    run = _get(session, run_id)
    if run.status != RunStatus.WAITING_FOR_FINAL_REVIEW:
        raise HTTPException(409, "The application is not waiting for the final review")
    try:
        save_user_draft(get_settings(), run, body)
    except RuntimeError as exc:  # rendering failed: keep the previous draft
        raise HTTPException(422, str(exc)) from exc
    run.updated_at = datetime.now(UTC)
    session.add(run)
    session.commit()
    return run_detail(session, run)


@router.post("/{run_id}/approve")
def approve_run(run_id: int, request: Request, session: SessionDep) -> dict:
    return _resume(request, session, _get(session, run_id), RunStatus.DELIVERING)


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: int, request: Request, session: SessionDep) -> None:
    """Delete an application with its events and files. Cost history is kept."""
    run = _get(session, run_id)
    if run.status in WORKING or engine_of(request).is_busy("run", run_id):
        raise HTTPException(409, "The application is still working; wait until it pauses")
    remove_run(session, run)
    session.commit()


@router.get("/{run_id}/drafts/{iteration}/{name}")
def download_draft_file(run_id: int, iteration: int, name: str, session: SessionDep):
    """Serve a file of a draft. Only names recorded in the run state are served."""
    run = _get(session, run_id)
    drafts = (run.state or {}).get("drafts", [])
    draft = next((d for d in drafts if d["iteration"] == iteration), None)
    if draft is None or name not in draft.get("files", {}):
        raise HTTPException(404, "File not found")
    path = get_settings().runs_dir / str(run_id) / f"draft-{iteration}" / draft["files"][name]
    if not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=f"run-{run_id}-draft-{iteration}-{name}")


@router.get("/{run_id}/final/{name}")
def download_final(run_id: int, name: str, session: SessionDep):
    run = _get(session, run_id)
    if name not in (run.state or {}).get("delivery", {}).get("files", {}):
        raise HTTPException(404, "File not found")
    path = get_settings().runs_dir / str(run_id) / "final" / name
    if not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=name)


@router.get("/{run_id}/bundle.zip")
def download_bundle(run_id: int, session: SessionDep) -> Response:
    run = _get(session, run_id)
    headers = {"Content-Disposition": f'attachment; filename="application-{run_id}.zip"'}
    return Response(bundle(get_settings(), run), media_type="application/zip", headers=headers)


@router.get("/{run_id}/edit-data")
def edit_data(run_id: int, session: SessionDep) -> dict:
    """The final draft and the CV, prepared for the editor."""
    run = _get(session, run_id)
    if run.status != RunStatus.WAITING_FOR_FINAL_REVIEW:
        raise HTTPException(409, "The application is not waiting for the final review")
    draft = final_draft(run.state)
    return {"draft": draft, "cv": run.state["cv"], "title": run_title(run)}
