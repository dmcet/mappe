"""Live updates: change detection for the SSE stream, and queueing jobs from other threads."""

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from mappe.config import DEFAULT_CONFIG_PATH, load_settings
from mappe.db import CV, Event, Run, init_engine
from mappe.runner.engine import Engine
from mappe.runner.states import CVStatus
from mappe.web.live import ChangeTracker


def setup(tmp_path):
    db = init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(db) as session:
        cv = CV(label="t", markdown="#", status=CVStatus.CONFIRMED)
        session.add(cv)
        session.commit()
        run = Run(cv_id=cv.id)
        session.add(run)
        session.commit()
        return db, cv.id, run.id


def test_nothing_changed_at_start(tmp_path):
    db, _, _ = setup(tmp_path)
    with Session(db) as session:
        tracker = ChangeTracker(session)
        assert tracker.changes(session) == (set(), set())


def test_every_new_event_is_reported_once(tmp_path):
    db, _, run_id = setup(tmp_path)
    with Session(db) as session:
        tracker = ChangeTracker(session)
        session.add(Event(run_id=run_id, kind="status", message="delivering"))
        session.commit()
        assert tracker.changes(session) == ({run_id}, set())
        assert tracker.changes(session) == (set(), set())


def test_late_commit_with_an_older_timestamp_is_still_seen(tmp_path):
    """updated_at is set before the commit: the row can show up after a check that ran
    later than its timestamp (this lost the update after approving or saving edits)."""
    db, cv_id, run_id = setup(tmp_path)
    with Session(db) as session:
        tracker = ChangeTracker(session)
        stamp = datetime.now(UTC) - timedelta(seconds=2)  # "before the previous check"
        assert tracker.changes(session) == (set(), set())

        run, cv = session.get(Run, run_id), session.get(CV, cv_id)
        run.updated_at = stamp
        cv.updated_at = stamp
        session.add_all([run, cv])
        session.commit()
        assert tracker.changes(session) == ({run_id}, {cv_id})
        assert tracker.changes(session) == (set(), set())  # reported once


async def test_jobs_queued_from_a_thread_wake_the_worker(tmp_path):
    """Sync API routes run in a thread pool and call enqueue() from there."""
    engine = Engine(load_settings(DEFAULT_CONFIG_PATH))
    engine._loop = asyncio.get_running_loop()
    got = asyncio.create_task(engine.queue.get())
    await asyncio.sleep(0)  # the getter is waiting

    loop = asyncio.get_running_loop()
    start = loop.time()

    def request_handler():  # like approve: runs while the event loop sleeps
        time.sleep(0.1)
        engine.enqueue(42)

    threading.Thread(target=request_handler).start()
    # A put that doesn't wake the loop is only noticed when the 3 s timeout fires.
    assert await asyncio.wait_for(got, timeout=3.0) == ("run", 42)
    assert loop.time() - start < 1.0
    assert engine.is_busy("run", 42)
