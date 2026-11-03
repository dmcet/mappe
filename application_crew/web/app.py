"""FastAPI application: HTMX pages, SSE status stream, downloads."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

import application_crew.steps  # noqa: F401 - registers steps
from application_crew.config import get_settings
from application_crew.db import CV, Event, Run, get_engine, get_session, init_engine
from application_crew.render.typst import typst_available
from application_crew.runner.engine import Engine

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")

SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    init_engine(f"sqlite:///{settings.db_path}")
    engine = Engine(settings)
    await engine.start()
    app.state.engine = engine
    yield
    await engine.stop()


app = FastAPI(title="Application Crew", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "typst": typst_available()}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, session: SessionDep) -> HTMLResponse:
    cvs = session.exec(select(CV).order_by(CV.created_at.desc())).all()  # type: ignore[attr-defined]
    runs = session.exec(select(Run).order_by(Run.created_at.desc())).all()  # type: ignore[attr-defined]
    return templates.TemplateResponse(request, "index.html", {"cvs": cvs, "runs": runs})


@app.post("/cvs")
def create_cv(
    session: SessionDep, label: Annotated[str, Form()], markdown: Annotated[str, Form()]
) -> RedirectResponse:
    # TODO: trigger the CV parsing flow (parse -> confirmation gate).
    session.add(CV(label=label, markdown=markdown))
    session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/runs")
def create_runs(
    request: Request,
    session: SessionDep,
    cv_id: Annotated[int, Form()],
    urls: Annotated[str, Form()] = "",
    listing_text: Annotated[str, Form()] = "",
) -> RedirectResponse:
    if session.get(CV, cv_id) is None:
        raise HTTPException(404, "CV not found")
    # TODO: require a confirmed CV once the parsing flow exists.
    new_runs = [Run(cv_id=cv_id, listing_url=u.strip()) for u in urls.splitlines() if u.strip()]
    if listing_text.strip():
        new_runs.append(Run(cv_id=cv_id, listing_text=listing_text.strip()))
    if not new_runs:
        raise HTTPException(400, "Provide at least one URL or a pasted listing")
    session.add_all(new_runs)
    session.commit()
    engine: Engine = request.app.state.engine
    for run in new_runs:
        engine.enqueue(run.id)  # type: ignore[arg-type]
    return RedirectResponse("/", status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: int, session: SessionDep) -> HTMLResponse:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    events = session.exec(select(Event).where(Event.run_id == run_id).order_by(Event.id)).all()
    return templates.TemplateResponse(request, "run.html", {"run": run, "events": events})


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
