"""Shared helpers for the API routers."""

from __future__ import annotations

import shutil
from typing import Annotated

from fastapi import Depends, Request
from sqlmodel import Session, delete

from mappe.config import get_settings
from mappe.db import Event, Run, get_session
from mappe.runner.engine import Engine

SessionDep = Annotated[Session, Depends(get_session)]


def engine_of(request: Request) -> Engine:
    return request.app.state.engine


def remove_run(session: Session, run: Run) -> None:
    """Delete a run with its events and files (the caller commits)."""
    session.exec(delete(Event).where(Event.run_id == run.id))  # type: ignore[call-overload]
    run_dir = get_settings().runs_dir / str(run.id)
    if run_dir.is_dir():
        shutil.rmtree(run_dir)
    session.delete(run)
