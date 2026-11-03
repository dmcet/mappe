"""FastAPI application: JSON API under /api, plus the built React frontend."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import application_crew.steps  # noqa: F401 - registers steps
from application_crew.config import PROJECT_ROOT, get_settings
from application_crew.db import init_engine
from application_crew.render.typst import typst_available
from application_crew.runner.engine import Engine
from application_crew.web import cvs, live, runs

log = logging.getLogger(__name__)
FRONTEND_DIR = Path(os.environ.get("APP_FRONTEND_DIR", PROJECT_ROOT / "frontend" / "dist"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    init_engine(f"sqlite:///{settings.db_path}")  # runs the database migrations
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
app.include_router(cvs.router)
app.include_router(runs.router)
app.include_router(live.router)


@app.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "typst": typst_available(),
        "demo": settings.demo,
        "frontend": (FRONTEND_DIR / "index.html").is_file(),
    }


# --- frontend (single-page app) --------------------------------------------------------

if (FRONTEND_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str) -> FileResponse:
    """Serve static files of the build, and index.html for every app route."""
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    candidate = (FRONTEND_DIR / path).resolve()
    if path and candidate.is_file() and FRONTEND_DIR.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = FRONTEND_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "Frontend not built (run `npm run build` in frontend/)")
    return FileResponse(index)
