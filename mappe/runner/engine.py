"""Run queue and state machine driver.

Each step is an async function ``(ctx) -> RunStatus`` registered for the status it
handles. The engine repeatedly executes the step for the run's current status until
the run reaches a user gate or a terminal status. Steps must be idempotent: after a
restart, a run in a working status is simply executed again from that status.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from mappe.config import Settings
from mappe.db import CV, Event, Run, get_engine
from mappe.runner import activity
from mappe.runner.states import WORKING, CVStatus, RunStatus, can_transition

log = logging.getLogger(__name__)


@dataclass
class StepContext:
    run: Run
    session: Session
    settings: Settings

    def emit(self, kind: str, message: str = "", **data: Any) -> None:
        self.session.add(Event(run_id=self.run.id, kind=kind, message=message, data=data))
        self.session.commit()


Step = Callable[[StepContext], Awaitable[RunStatus]]
_STEPS: dict[RunStatus, Step] = {}


def step(status: RunStatus) -> Callable[[Step], Step]:
    """Register a step function for a working status."""

    def decorator(fn: Step) -> Step:
        if status not in WORKING:
            raise ValueError(f"{status} is not a working status")
        _STEPS[status] = fn
        return fn

    return decorator


STEP_LABELS = {
    RunStatus.CREATED: "Starting",
    RunStatus.FETCHING_LISTING: "Fetching the job listing",
    RunStatus.PARSING_LISTING: "Reading the job listing",
    RunStatus.CHECKING_REQUIREMENTS: "Checking your requirements",
    RunStatus.MATCHING: "Assessing your fit",
    RunStatus.AUTHORING: "Writing your documents",
    RunStatus.REVIEWING: "Reviewing the draft",
    RunStatus.DELIVERING: "Preparing the final documents",
}


def run_title(run: Run) -> str:
    listing = (run.state or {}).get("listing") or {}
    parts = [x for x in (listing.get("title"), listing.get("company")) if x]
    if parts:
        return " · ".join(parts)
    return run.listing_url or "Pasted listing"


class InvalidTransition(RuntimeError):
    pass


def set_status(session: Session, run: Run, target: RunStatus, error: str | None = None) -> None:
    if not can_transition(run.status, target):
        raise InvalidTransition(f"run {run.id}: {run.status} -> {target} not allowed")
    # Remember where the run came from, so the UI can show where it failed or was declined.
    run.state = (run.state or {}) | {"previous_status": str(run.status)}
    run.status = target
    run.error = error
    run.updated_at = datetime.now(UTC)
    session.add(run)
    session.add(Event(run_id=run.id, kind="status", message=str(target)))
    session.commit()


CVJob = Callable[[int, Settings], Awaitable[None]]
_CV_JOB: CVJob | None = None


def cv_job(fn: CVJob) -> CVJob:
    """Register the CV parsing job (runs outside the run state machine)."""
    global _CV_JOB
    _CV_JOB = fn
    return fn


class Engine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._queued: set[tuple[str, int]] = set()
        self._running: set[tuple[str, int]] = set()
        self._workers: list[asyncio.Task[None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._requeue_interrupted()
        self._workers = [
            asyncio.create_task(self._worker(i), name=f"run-worker-{i}")
            for i in range(self.settings.max_concurrent_runs)
        ]

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

    def enqueue(self, run_id: int) -> None:
        self._put(("run", run_id))

    def enqueue_cv(self, cv_id: int) -> None:
        self._put(("cv", cv_id))

    def _put(self, job: tuple[str, int]) -> None:
        """Queue a job. Safe from any thread: sync API routes run in a thread pool, and
        asyncio.Queue isn't thread-safe (a put from another thread doesn't wake the worker
        until something else wakes the event loop)."""
        try:
            on_loop = asyncio.get_running_loop() is self._loop
        except RuntimeError:  # no event loop in this thread
            on_loop = False
        if self._loop is None or on_loop:
            self._put_now(job)
        else:
            self._loop.call_soon_threadsafe(self._put_now, job)

    def _put_now(self, job: tuple[str, int]) -> None:
        if job not in self._queued:
            self._queued.add(job)
            self.queue.put_nowait(job)

    def _requeue_interrupted(self) -> None:
        with Session(get_engine()) as session:
            stmt = select(CV.id).where(
                (CV.status == CVStatus.PARSING) | (CV.roles_status == "suggesting")
            )
            for cv_id in session.exec(stmt):
                self.enqueue_cv(cv_id)
            stmt = select(Run.id).where(Run.status.in_([s.value for s in WORKING]))  # type: ignore[attr-defined]
            for run_id in session.exec(stmt):
                self.enqueue(run_id)

    async def _worker(self, index: int) -> None:
        while True:
            job = await self.queue.get()
            self._queued.discard(job)
            kind, job_id = job
            self._running.add(job)
            activity.begin(kind, job_id, self._title(kind, job_id))
            try:
                if kind == "cv":
                    await self.parse_cv(job_id)
                else:
                    await self.drive(job_id)
            except Exception:  # noqa: BLE001 - a worker must never die
                log.exception("worker %s: %s %s crashed", index, kind, job_id)
            finally:
                activity.end()
                self._running.discard(job)
                self.queue.task_done()

    def _title(self, kind: str, job_id: int) -> str:
        with Session(get_engine()) as session:
            if kind == "cv":
                cv = session.get(CV, job_id)
                return f"CV · {cv.label}" if cv else f"CV {job_id}"
            run = session.get(Run, job_id)
            return run_title(run) if run else f"Run {job_id}"

    def queued(self) -> list[dict]:
        """Jobs waiting for a free worker."""
        return [{"kind": k, "id": i} for k, i in self._queued if (k, i) not in self._running]

    def is_busy(self, kind: str, job_id: int) -> bool:
        return (kind, job_id) in self._queued or (kind, job_id) in self._running

    async def parse_cv(self, cv_id: int) -> None:
        if _CV_JOB is None:
            raise RuntimeError("no CV job registered")
        await _CV_JOB(cv_id, self.settings)

    async def drive(self, run_id: int) -> None:
        """Execute steps until the run waits for the user or is finished."""
        with Session(get_engine()) as session:
            run = session.get(Run, run_id)
            while run is not None and run.status in WORKING:
                handler = _STEPS.get(run.status)
                if handler is None:
                    set_status(
                        session, run, RunStatus.FAILED, f"step '{run.status}' not implemented"
                    )
                    return
                ctx = StepContext(run=run, session=session, settings=self.settings)
                activity.update(
                    STEP_LABELS.get(run.status, str(run.status)),
                    phase=str(run.status),
                    title=run_title(run),
                )
                ctx.emit("step_started", str(run.status))
                try:
                    target = await handler(ctx)
                except Exception as exc:  # noqa: BLE001
                    log.exception("run %s: step %s failed", run_id, run.status)
                    session.rollback()
                    set_status(session, run, RunStatus.FAILED, f"{run.status}: {exc}")
                    return
                ctx.emit("step_finished", str(run.status))
                set_status(session, run, target)
