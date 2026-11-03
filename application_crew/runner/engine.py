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
from application_crew.db import Event, Run, get_engine
from application_crew.runner.states import WORKING, RunStatus, can_transition

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


class Engine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._queued: set[int] = set()
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
        if run_id not in self._queued:
            self._queued.add(run_id)
            self.queue.put_nowait(run_id)

    def _requeue_interrupted(self) -> None:
        with Session(get_engine()) as session:
            stmt = select(Run.id).where(Run.status.in_([s.value for s in WORKING]))  # type: ignore[attr-defined]
            for run_id in session.exec(stmt):
                self.enqueue(run_id)

    async def _worker(self, index: int) -> None:
        while True:
            run_id = await self.queue.get()
            self._queued.discard(run_id)
            try:
                await self.drive(run_id)
            except Exception:  # noqa: BLE001 - a worker must never die
                log.exception("worker %s: run %s crashed", index, run_id)
            finally:
                self.queue.task_done()

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
