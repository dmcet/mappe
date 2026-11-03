"""CV routes: create, parse, fix, confirm, delete."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from application_crew.checks.completeness import check_cv
from application_crew.db import CV, Run
from application_crew.domain.models import ParsedCV
from application_crew.domain.summary import summarize
from application_crew.runner.states import WORKING, CVStatus
from application_crew.web.deps import SessionDep, engine_of, remove_run

router = APIRouter(prefix="/api/cvs")

# Fields the user can fill in directly; everything else is fixed by editing the Markdown.
QUICK_FIELDS: dict[str, str] = {
    "contact.email": "Email",
    "contact.phone": "Phone",
    "contact.city": "City",
    "contact.address": "Address",
    "notice_period": "Notice period",
    "earliest_start": "Earliest start",
    "salary_expectation": "Salary expectation",
    "work_permit": "Work permit / visa status",
}


class CVCreate(BaseModel):
    label: str
    markdown: str


class CVMarkdown(BaseModel):
    markdown: str


def _get(session: Session, cv_id: int) -> CV:
    cv = session.get(CV, cv_id)
    if cv is None:
        raise HTTPException(404, "CV not found")
    return cv


def _touch(session: Session, cv: CV) -> None:
    cv.updated_at = datetime.now(UTC)
    session.add(cv)
    session.commit()


def cv_summary(cv: CV, runs: int = 0) -> dict:
    return {
        "id": cv.id,
        "label": cv.label,
        "status": str(cv.status),
        "error": cv.error,
        "cost_usd": cv.cost_usd,
        "warnings": len(cv.warnings or []),
        "runs": runs,
        "created_at": cv.created_at,
        "updated_at": cv.updated_at,
    }


def cv_detail(cv: CV, runs: int) -> dict:
    parsed = ParsedCV.model_validate(cv.parsed) if cv.parsed else None
    quick = {}
    if parsed:
        for key in QUICK_FIELDS:
            obj: object = parsed
            for part in key.split("."):
                obj = getattr(obj, part)
            quick[key] = obj or ""
    return cv_summary(cv, runs) | {
        "markdown": cv.markdown,
        "warnings": cv.warnings or [],
        "parsed": parsed.model_dump(mode="json") if parsed else None,
        "summary": asdict(summarize(parsed)) if parsed else None,
        "quick_fields": QUICK_FIELDS,
        "quick_values": quick,
    }


def _run_count(session: Session, cv_id: int) -> int:
    return len(session.exec(select(Run.id).where(Run.cv_id == cv_id)).all())


@router.get("")
def list_cvs(session: SessionDep) -> list[dict]:
    cvs = session.exec(select(CV).order_by(CV.created_at.desc())).all()  # type: ignore[attr-defined]
    return [cv_summary(cv, _run_count(session, cv.id)) for cv in cvs]


@router.post("", status_code=201)
def create_cv(body: CVCreate, request: Request, session: SessionDep) -> dict:
    if not body.label.strip() or not body.markdown.strip():
        raise HTTPException(400, "Label and CV text are required")
    cv = CV(label=body.label.strip(), markdown=body.markdown.strip())
    session.add(cv)
    session.commit()
    engine_of(request).enqueue_cv(cv.id)  # type: ignore[arg-type]
    return cv_detail(cv, 0)


@router.get("/{cv_id}")
def get_cv(cv_id: int, session: SessionDep) -> dict:
    return cv_detail(_get(session, cv_id), _run_count(session, cv_id))


@router.patch("/{cv_id}/fields")
def update_fields(cv_id: int, values: dict[str, str], session: SessionDep) -> dict:
    cv = _get(session, cv_id)
    if cv.status != CVStatus.WAITING_FOR_CONFIRMATION or not cv.parsed:
        raise HTTPException(409, "CV is not waiting for confirmation")
    data = dict(cv.parsed)
    data["contact"] = dict(data["contact"])
    for key in QUICK_FIELDS:
        if key not in values:
            continue
        value = values[key].strip() or None
        if key.startswith("contact."):
            data["contact"][key.removeprefix("contact.")] = value
        else:
            data[key] = value
    parsed = ParsedCV.model_validate(data)
    cv.parsed = parsed.model_dump(mode="json")
    cv.warnings = check_cv(parsed)
    _touch(session, cv)
    return cv_detail(cv, _run_count(session, cv_id))


@router.put("/{cv_id}/markdown")
def update_markdown(cv_id: int, body: CVMarkdown, request: Request, session: SessionDep) -> dict:
    """Save the edited Markdown and parse again (also retries a failed parse)."""
    cv = _get(session, cv_id)
    if cv.status == CVStatus.PARSING:
        raise HTTPException(409, "CV is being parsed")
    cv.markdown = body.markdown.strip()
    cv.status = CVStatus.PARSING
    cv.parsed = None
    cv.warnings = []
    cv.error = None
    _touch(session, cv)
    engine_of(request).enqueue_cv(cv_id)
    return cv_detail(cv, _run_count(session, cv_id))


@router.post("/{cv_id}/confirm")
def confirm(cv_id: int, session: SessionDep) -> dict:
    cv = _get(session, cv_id)
    if cv.status != CVStatus.WAITING_FOR_CONFIRMATION:
        raise HTTPException(409, "CV is not waiting for confirmation")
    cv.status = CVStatus.CONFIRMED
    _touch(session, cv)
    return cv_detail(cv, _run_count(session, cv_id))


@router.delete("/{cv_id}", status_code=204)
def delete_cv(
    cv_id: int, request: Request, session: SessionDep, cascade: bool = Query(False)
) -> None:
    """Delete a CV. With ``cascade``, its applications are deleted too.

    Cost history (the usage ledger) is kept, so total spend stays correct.
    """
    cv = _get(session, cv_id)
    engine = engine_of(request)
    if cv.status == CVStatus.PARSING or engine.is_busy("cv", cv_id):
        raise HTTPException(409, "The CV is being parsed; delete it when parsing is done")
    runs = session.exec(select(Run).where(Run.cv_id == cv_id)).all()
    if runs and not cascade:
        raise HTTPException(409, f"The CV has {len(runs)} application(s); delete them too?")
    busy = [r.id for r in runs if r.status in WORKING or engine.is_busy("run", r.id)]
    if busy:
        raise HTTPException(409, f"Applications {busy} are still working; wait until they pause")
    for run in runs:
        remove_run(session, run)
    session.delete(cv)
    session.commit()
