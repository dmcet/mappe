"""What is happening right now: one entry per running job, updated as it works.

The engine registers each job (a run or a CV parse) and binds it to the current task via
a context variable. Steps, checks and the Claude client then update the job's activity
without passing anything around, e.g. "Claude · Checking claims against your CV".
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field

# Human-readable names for steps and Claude calls.
LABELS = {
    "parse_cv": "Reading your CV",
    "suggest_roles": "Suggesting other roles",
    "parse_listing": "Reading the job listing",
    "match": "Assessing your fit",
    "author_cv": "Writing the tailored CV",
    "author_letter": "Writing the cover letter",
    "claims_check": "Checking claims against your CV",
    "recruiter": "Recruiter review",
}


@dataclass
class Activity:
    kind: str  # "run" | "cv" | "search"
    id: int
    title: str
    phase: str = ""  # pipeline status, e.g. "reviewing"
    detail: str = ""  # what exactly happens now
    model: str | None = None  # set while waiting for Claude
    draft: int | None = None
    progress: dict | None = None  # search: per source {"label", "state", "count", "error"}
    started_at: float = field(default_factory=time.time)
    detail_since: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        now = time.time()
        return asdict(self) | {
            "elapsed_s": round(now - self.started_at, 1),
            "detail_elapsed_s": round(now - self.detail_since, 1),
        }


_jobs: dict[tuple[str, int], Activity] = {}
_current: ContextVar[tuple[str, int] | None] = ContextVar("current_job", default=None)


def begin(kind: str, job_id: int, title: str) -> None:
    _jobs[(kind, job_id)] = Activity(kind=kind, id=job_id, title=title)
    _current.set((kind, job_id))


def end() -> None:
    key = _current.get()
    if key is not None:
        _jobs.pop(key, None)
    _current.set(None)


def current() -> tuple[str, int] | None:
    return _current.get()


def update(
    detail: str | None = None,
    *,
    phase: str | None = None,
    model: str | None = None,
    draft: int | None = None,
    title: str | None = None,
    progress: dict | None = None,
) -> None:
    """Update the current job's activity. No-op outside a job (e.g. in tests)."""
    key = _current.get()
    job = _jobs.get(key) if key else None
    if job is None:
        return
    if phase is not None:
        job.phase = phase
    if title is not None:
        job.title = title
    if draft is not None:
        job.draft = draft
    if progress is not None:
        job.progress = progress
    if detail is not None:
        job.detail = detail
        job.model = model
        job.detail_since = time.time()


def snapshot() -> list[dict]:
    return [job.to_dict() for job in sorted(_jobs.values(), key=lambda j: j.started_at)]
