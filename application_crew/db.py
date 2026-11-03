"""SQLite persistence (SQLModel)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, LargeBinary, UniqueConstraint, inspect
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


class Usage(SQLModel, table=True):
    """One Claude call. Kept when a run or CV is deleted, so the total spend stays right."""

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_now, index=True)
    run_id: int | None = Field(default=None, index=True)
    cv_id: int | None = None
    step: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


class SavedSearch(SQLModel, table=True):
    """A search to run again later; its runs mark what is new since the previous run."""

    __tablename__ = "saved_search"

    id: int | None = Field(default=None, primary_key=True)
    cv_id: int = Field(foreign_key="cv.id", index=True)
    name: str
    titles: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    requirements: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    sources: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class Search(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    cv_id: int = Field(foreign_key="cv.id", index=True)
    saved_id: int | None = Field(default=None, index=True)  # plain ID, see SavedSearch
    titles: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    places: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    remote_only: bool = False
    requirements: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    # Per source: {"label", "count", "error", "seconds"}.
    sources: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # How results were ranked: {"semantic": bool, "model", "embedded", "reused", "note"}.
    ranking: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now, index=True)


class JobHitRecord(SQLModel, table=True):
    """A listing seen in a search; stored once per source listing, across searches."""

    __tablename__ = "job_hit"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str
    external_id: str
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))  # JobHit
    status: str = "new"  # new | dismissed | applied
    run_id: int | None = None  # plain ID: the run may be deleted
    # Semantic ranking: the listing's vector (float16) and what it was computed from.
    embedding: bytes | None = Field(default=None, sa_column=Column(LargeBinary))
    embedding_key: str | None = None  # "<model>:<hash of the embedded text>"
    first_seen_at: datetime = Field(default_factory=_now)
    last_seen_at: datetime = Field(default_factory=_now)


class SearchResult(SQLModel, table=True):
    __tablename__ = "search_result"

    id: int | None = Field(default=None, primary_key=True)
    search_id: int = Field(foreign_key="search.id", index=True)
    hit_id: int = Field(foreign_key="job_hit.id", index=True)
    score: float = 0.0
    reasons: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    hidden: str | None = None  # dismissed | requirements | elsewhere | low_score
    is_new: bool = False  # first seen in this search


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE_REVISION = "0001"  # the schema SQLModel created before migrations existed

_engine: Engine | None = None


def run_migrations(engine: Engine) -> None:
    """Bring the database to the latest schema.

    A database created before migrations existed (tables, but no ``alembic_version``) is
    stamped at the baseline revision first, so only the newer migrations run on it.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        if "cv" in tables and "alembic_version" not in tables:
            command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, "head")


def init_engine(url: str) -> Engine:
    global _engine
    _engine = create_engine(url, connect_args={"check_same_thread": False})
    run_migrations(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialised; call init_engine() first")
    return _engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
