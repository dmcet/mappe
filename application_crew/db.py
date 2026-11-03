"""SQLite persistence (SQLModel)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine

from application_crew.runner.states import CVStatus, RunStatus


def _now() -> datetime:
    return datetime.now(UTC)


class CV(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    label: str
    markdown: str
    status: CVStatus = CVStatus.PARSING
    parsed: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    warnings: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    error: str | None = None
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Run(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    cv_id: int = Field(foreign_key="cv.id", index=True)
    listing_url: str | None = None
    listing_text: str | None = None
    status: RunStatus = Field(default=RunStatus.CREATED, index=True)
    # Step outputs (parsed listing, match report, drafts, ...) keyed by step name.
    state: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    requirements: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    error: str | None = None
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    kind: str  # step_started | step_progress | iteration_result | step_finished | usage | error
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


_engine: Engine | None = None


def init_engine(url: str) -> Engine:
    global _engine
    _engine = create_engine(url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialised; call init_engine() first")
    return _engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
