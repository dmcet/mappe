"""FastAPI application: HTMX pages, SSE status stream, downloads."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

import application_crew.steps  # noqa: F401 - registers steps
from application_crew.checks.completeness import check_cv
from application_crew.config import get_settings
from application_crew.db import CV, Event, Run, get_engine, get_session, init_engine
from application_crew.domain.match import MatchResult
from application_crew.domain.models import ParsedCV, ParsedListing, RequirementResult
from application_crew.domain.summary import summarize
from application_crew.render.typst import typst_available
from application_crew.runner.engine import Engine, InvalidTransition, set_status
from application_crew.runner.states import WORKING, CVStatus, RunStatus
from application_crew.web.forms import form_defaults, requirements_from_form

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")

SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    init_engine(f"sqlite:///{settings.db_path}")
    templates.env.globals["demo"] = settings.demo
    if settings.demo:
        log.warning("Demo mode: Claude is replaced by canned sample data")
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY is not set; Claude calls will fail (use APP_DEMO=1)")
    engine = Engine(settings)
    await engine.start()
    app.state.engine = engine
    yield
    await engine.stop()


app = FastAPI(title="Application Crew", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "typst": typst_available(), "demo": get_settings().demo}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, session: SessionDep) -> HTMLResponse:
    cvs = session.exec(select(CV).order_by(CV.created_at.desc())).all()  # type: ignore[attr-defined]
    runs = session.exec(select(Run).order_by(Run.created_at.desc())).all()  # type: ignore[attr-defined]
    defaults = form_defaults(runs[0].requirements) if runs else form_defaults([])
    context = {"cvs": cvs, "runs": runs, "req": defaults}
    return templates.TemplateResponse(request, "index.html", context)


def _engine(request: Request) -> Engine:
    return request.app.state.engine


def _get_cv(session: Session, cv_id: int) -> CV:
    cv = session.get(CV, cv_id)
    if cv is None:
        raise HTTPException(404, "CV not found")
    return cv


def _touch(session: Session, cv: CV) -> None:
    cv.updated_at = datetime.now(UTC)
    session.add(cv)
    session.commit()


@app.post("/cvs")
def create_cv(
    request: Request,
    session: SessionDep,
    label: Annotated[str, Form()],
    markdown: Annotated[str, Form()],
) -> RedirectResponse:
    cv = CV(label=label.strip(), markdown=markdown.strip())
    session.add(cv)
    session.commit()
    _engine(request).enqueue_cv(cv.id)  # type: ignore[arg-type]
    return RedirectResponse(f"/cvs/{cv.id}", status_code=303)


@app.get("/cvs/{cv_id}", response_class=HTMLResponse)
def cv_detail(request: Request, cv_id: int, session: SessionDep) -> HTMLResponse:
    cv = _get_cv(session, cv_id)
    parsed = ParsedCV.model_validate(cv.parsed) if cv.parsed else None
    context = {
        "cv": cv,
        "parsed": parsed,
        "summary": summarize(parsed) if parsed else None,
        "quick_fields": QUICK_FIELDS,
        "quick_values": _quick_values(parsed) if parsed else {},
    }
    return templates.TemplateResponse(request, "cv.html", context)


# Fields the user can fill in directly on the confirmation page. Everything else is
# fixed by editing the Markdown CV and parsing again, so the CV stays the source of truth.
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


def _quick_values(parsed: ParsedCV) -> dict[str, str]:
    values = {}
    for key in QUICK_FIELDS:
        obj: object = parsed
        for part in key.split("."):
            obj = getattr(obj, part)
        values[key] = obj or ""  # type: ignore[assignment]
    return values


@app.post("/cvs/{cv_id}/fields")
async def update_cv_fields(request: Request, cv_id: int, session: SessionDep) -> RedirectResponse:
    cv = _get_cv(session, cv_id)
    if cv.status != CVStatus.WAITING_FOR_CONFIRMATION or not cv.parsed:
        raise HTTPException(409, "CV is not waiting for confirmation")
    form = await request.form()
    data = dict(cv.parsed)
    data["contact"] = dict(data["contact"])
    for key in QUICK_FIELDS:
        value = str(form.get(key, "")).strip() or None
        if key.startswith("contact."):
            data["contact"][key.removeprefix("contact.")] = value
        else:
            data[key] = value
    parsed = ParsedCV.model_validate(data)
    cv.parsed = parsed.model_dump(mode="json")
    cv.warnings = check_cv(parsed)
    _touch(session, cv)
    return RedirectResponse(f"/cvs/{cv_id}", status_code=303)


@app.post("/cvs/{cv_id}/markdown")
def update_cv_markdown(
    request: Request, cv_id: int, session: SessionDep, markdown: Annotated[str, Form()]
) -> RedirectResponse:
    """Save the edited Markdown CV and parse it again (also used to retry a failed parse)."""
    cv = _get_cv(session, cv_id)
    if cv.status == CVStatus.PARSING:
        raise HTTPException(409, "CV is being parsed")
    cv.markdown = markdown.strip()
    cv.status = CVStatus.PARSING
    cv.parsed = None
    cv.warnings = []
    cv.error = None
    _touch(session, cv)
    _engine(request).enqueue_cv(cv_id)
    return RedirectResponse(f"/cvs/{cv_id}", status_code=303)


@app.post("/cvs/{cv_id}/confirm")
def confirm_cv(cv_id: int, session: SessionDep) -> RedirectResponse:
    cv = _get_cv(session, cv_id)
    if cv.status != CVStatus.WAITING_FOR_CONFIRMATION:
        raise HTTPException(409, "CV is not waiting for confirmation")
    cv.status = CVStatus.CONFIRMED
    _touch(session, cv)
    return RedirectResponse("/", status_code=303)


@app.post("/runs")
async def create_runs(
    request: Request,
    session: SessionDep,
    cv_id: Annotated[int, Form()],
    urls: Annotated[str, Form()] = "",
    listing_text: Annotated[str, Form()] = "",
) -> RedirectResponse:
    if _get_cv(session, cv_id).status != CVStatus.CONFIRMED:
        raise HTTPException(409, "Confirm the CV before starting an application")
    reqs = [r.model_dump(mode="json") for r in requirements_from_form(await request.form())]
    new_runs = [
        Run(cv_id=cv_id, listing_url=u.strip(), requirements=reqs)
        for u in urls.splitlines()
        if u.strip()
    ]
    if listing_text.strip():
        new_runs.append(Run(cv_id=cv_id, listing_text=listing_text.strip(), requirements=reqs))
    if not new_runs:
        raise HTTPException(400, "Provide at least one URL or a pasted listing")
    session.add_all(new_runs)
    session.commit()
    for run in new_runs:
        _engine(request).enqueue(run.id)  # type: ignore[arg-type]
    if len(new_runs) == 1:
        return RedirectResponse(f"/runs/{new_runs[0].id}", status_code=303)
    return RedirectResponse("/", status_code=303)


def _fact_texts(cv_data: dict | None) -> dict[str, str]:
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


def _get_run(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


def _resume(request: Request, session: Session, run: Run, target: RunStatus) -> RedirectResponse:
    """Move a run out of a user gate and hand it back to the engine."""
    try:
        set_status(session, run, target)
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    if target in WORKING:
        _engine(request).enqueue(run.id)  # type: ignore[arg-type]
    return RedirectResponse(f"/runs/{run.id}", status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: int, session: SessionDep) -> HTMLResponse:
    run = _get_run(session, run_id)
    listing = run.state.get("listing")
    context = {
        "run": run,
        "working": run.status in WORKING,
        "listing": ParsedListing.model_validate(listing) if listing else None,
        "results": [
            RequirementResult.model_validate(r) for r in run.state.get("requirement_results", [])
        ],
        "match": MatchResult.model_validate(run.state["match"]) if "match" in run.state else None,
        "analysis": run.state.get("analysis"),
        "match_warnings": run.state.get("match_warnings", []),
        "facts": _fact_texts(run.state.get("cv")),
    }
    return templates.TemplateResponse(request, "run.html", context)


@app.post("/runs/{run_id}/listing-text")
def submit_listing_text(
    request: Request, run_id: int, session: SessionDep, listing_text: Annotated[str, Form()]
) -> RedirectResponse:
    run = _get_run(session, run_id)
    if not listing_text.strip():
        raise HTTPException(400, "Paste the listing text")
    run.listing_text = listing_text.strip()
    return _resume(request, session, run, RunStatus.PARSING_LISTING)


@app.post("/runs/{run_id}/continue")
def continue_run(request: Request, run_id: int, session: SessionDep) -> RedirectResponse:
    """Override failed must-have requirements and continue with matching."""
    return _resume(request, session, _get_run(session, run_id), RunStatus.MATCHING)


@app.post("/runs/{run_id}/apply")
async def apply_run(request: Request, run_id: int, session: SessionDep) -> RedirectResponse:
    """The user decided to apply: record the cover-letter choice and start authoring."""
    run = _get_run(session, run_id)
    if run.status != RunStatus.WAITING_FOR_APPLY_DECISION:
        raise HTTPException(409, "Run is not waiting for an apply decision")
    form = await request.form()
    run.state = run.state | {"decision": {"cover_letter": form.get("cover_letter") == "on"}}
    return _resume(request, session, run, RunStatus.AUTHORING)


@app.post("/runs/{run_id}/decline")
def decline_run(request: Request, run_id: int, session: SessionDep) -> RedirectResponse:
    return _resume(request, session, _get_run(session, run_id), RunStatus.DECLINED)


@app.get("/runs/{run_id}/events")
async def run_events(request: Request, run_id: int) -> EventSourceResponse:
    """Stream new events of a run as rendered HTML fragments (HTMX SSE extension)."""

    async def stream() -> AsyncIterator[dict[str, str]]:
        last_id = 0
        while not await request.is_disconnected():
            with Session(get_engine()) as session:
                stmt = select(Event).where(Event.run_id == run_id, Event.id > last_id)
                new = session.exec(stmt.order_by(Event.id)).all()
            for event in new:
                last_id = event.id or last_id
                html = templates.get_template("_event.html").render(event=event)
                yield {"event": "run-event", "data": html}
            await asyncio.sleep(1.0)

    return EventSourceResponse(stream())
