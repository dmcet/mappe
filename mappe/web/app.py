"""FastAPI application: JSON API under /api, plus the built React frontend."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import mappe.steps  # noqa: F401 - registers steps
from mappe.config import PROJECT_ROOT, get_settings
from mappe.db import init_engine
from mappe.render.typst import typst_available
from mappe.runner.engine import Engine
from mappe.search import semantic
from mappe.web import cvs, live, runs, search

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
    # Load the semantic ranking model in the background (~20 s), not on the first search.
    app.state.model_warmup = asyncio.create_task(
        asyncio.to_thread(semantic.get_embedder, settings.search)
    )
    yield
    await engine.stop()


app = FastAPI(title="Mappe", lifespan=lifespan)
app.include_router(cvs.router)
app.include_router(runs.router)
app.include_router(live.router)
app.include_router(search.router)


@app.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "typst": typst_available(),
        "demo": settings.demo,
        "frontend": (FRONTEND_DIR / "index.html").is_file(),
        "semantic_ranking": semantic.unavailable_reason(settings.search) or "ok",
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
