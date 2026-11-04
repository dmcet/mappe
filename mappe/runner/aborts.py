"""Abort requests for running steps (in memory; the app runs in one process).

Set from API handlers on the event loop, awaited by the step. A request made while the
run is still queued is picked up as soon as its step starts.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable

_events: dict[int, asyncio.Event] = {}


def request(run_id: int) -> None:
    _events.setdefault(run_id, asyncio.Event()).set()


async def abortable[T](run_id: int, work: Awaitable[T]) -> tuple[T | None, bool]:
    """Run ``work`` until it finishes or the user aborts. Returns (result, aborted)."""
    event = _events.setdefault(run_id, asyncio.Event())
    task = asyncio.ensure_future(work)
    waiter = asyncio.ensure_future(event.wait())
    try:
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        _events.pop(run_id, None)
        for pending in (task, waiter):
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending
    if task.done() and not task.cancelled():
        return task.result(), False
    return None, True
