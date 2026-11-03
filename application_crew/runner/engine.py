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

from application_crew.config import Settings
from application_crew.db import CV, Event, Run, get_engine
from application_crew.runner.states import WORKING, CVStatus, RunStatus, can_transition

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


class InvalidTransition(RuntimeError):
    pass


def set_status(session: Session, run: Run, target: RunStatus, error: str | None = None) -> None:
    if not can_transition(run.status, target):
        raise InvalidTransition(f"run {run.id}: {run.status} -> {target} not allowed")
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
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
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
        if job not in self._queued:
            self._queued.add(job)
            self.queue.put_nowait(job)

    def _requeue_interrupted(self) -> None:
        with Session(get_engine()) as session:
            stmt = select(CV.id).where(CV.status == CVStatus.PARSING)
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
            try:
                if kind == "cv":
                    await self.parse_cv(job_id)
                else:
                    await self.drive(job_id)
            except Exception:  # noqa: BLE001 - a worker must never die
                log.exception("worker %s: %s %s crashed", index, kind, job_id)
            finally:
                self.queue.task_done()

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
