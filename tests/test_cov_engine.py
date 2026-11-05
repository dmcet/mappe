"""Engine: step registration, requeue after restart, worker resilience, failing steps."""

import asyncio
import logging

import pytest
from sqlmodel import Session, select

import mappe.steps  # noqa: F401 - registers steps
from mappe.config import DEFAULT_CONFIG_PATH, load_settings
from mappe.db import CV, Event, Run, init_engine
from mappe.runner import activity, engine
from mappe.runner.engine import Engine, step
from mappe.runner.states import CVStatus, RunStatus


@pytest.fixture
def db(tmp_path):
    return init_engine(f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def settings():
    return load_settings(DEFAULT_CONFIG_PATH)


def add(db, *rows):
    with Session(db) as session:
        for row in rows:
            session.add(row)
        session.commit()
        return [row.id for row in rows]


def test_steps_can_only_be_registered_for_working_statuses():
    before = dict(engine._STEPS)
    with pytest.raises(ValueError, match="waiting_for_apply_decision is not a working status"):
        step(RunStatus.WAITING_FOR_APPLY_DECISION)(lambda ctx: None)
    assert engine._STEPS == before


def test_interrupted_cvs_and_runs_are_requeued(db, settings):
    cv_parsing, cv_roles, cv_done = add(
        db,
        CV(label="a", markdown="#", status=CVStatus.PARSING),
        CV(label="b", markdown="#", status=CVStatus.CONFIRMED, roles_status="suggesting"),
        CV(label="c", markdown="#", status=CVStatus.CONFIRMED),
    )
    working, waiting = add(
        db,
        Run(cv_id=cv_done, status=RunStatus.REVIEWING),
        Run(cv_id=cv_done, status=RunStatus.WAITING_FOR_FINAL_REVIEW),
    )
    eng = Engine(settings)
    eng._requeue_interrupted()

    jobs = sorted((j["kind"], j["id"]) for j in eng.queued())
    assert jobs == [("cv", cv_parsing), ("cv", cv_roles), ("run", working)]
    assert eng.is_busy("run", working) and not eng.is_busy("run", waiting)
    eng._requeue_interrupted()  # queuing twice doesn't duplicate jobs
    assert eng.queue.qsize() == 3


async def test_enqueue_on_and_off_the_event_loop(settings):
    eng = Engine(settings)
    eng._loop = asyncio.get_running_loop()

    eng.enqueue(1)  # on the loop: queued right away
    assert eng.queue.qsize() == 1

    await asyncio.to_thread(eng.enqueue_cv, 2)  # from a worker thread: via the loop
    await asyncio.sleep(0)
    assert eng.queue.qsize() == 2
    assert [eng.queue.get_nowait(), eng.queue.get_nowait()] == [("run", 1), ("cv", 2)]


async def test_a_crashing_job_does_not_kill_the_worker(db, settings, monkeypatch, caplog):
    eng = Engine(settings)
    done = []

    async def drive(run_id):
        if run_id == 1:
            raise RuntimeError("boom")
        done.append(run_id)

    monkeypatch.setattr(eng, "drive", drive)
    worker = asyncio.create_task(eng._worker(0))
    try:
        with caplog.at_level(logging.ERROR, logger="mappe.runner.engine"):
            eng.enqueue(1)
            eng.enqueue(2)
            await asyncio.wait_for(eng.queue.join(), timeout=5)
        assert done == [2]  # the next job still ran
        assert not worker.done()
        assert "worker 0: run 1 crashed" in caplog.text
        assert eng.queued() == [] and not eng.is_busy("run", 1)
        assert activity.current() is None
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_parse_cv_needs_a_registered_job(settings, monkeypatch):
    monkeypatch.setattr(engine, "_CV_JOB", None)
    with pytest.raises(RuntimeError, match="no CV job registered"):
        await Engine(settings).parse_cv(1)


async def test_a_status_without_a_step_fails_the_run(db, settings, monkeypatch):
    monkeypatch.delitem(engine._STEPS, RunStatus.CREATED)
    (cv_id,) = add(db, CV(label="t", markdown="#"))
    (run_id,) = add(db, Run(cv_id=cv_id, listing_text="x"))

    await Engine(settings).drive(run_id)

    with Session(db) as session:
        run = session.get(Run, run_id)
        assert run.status == RunStatus.FAILED
        assert run.error == "step 'created' not implemented"
        assert run.state["previous_status"] == "created"


async def test_a_failing_step_rolls_back_and_fails_the_run(db, settings, monkeypatch):
    async def broken(ctx):
        ctx.run.listing_text = "half-done change"  # not committed: must be rolled back
        raise ValueError("boom")

    monkeypatch.setitem(engine._STEPS, RunStatus.CREATED, broken)
    (cv_id,) = add(db, CV(label="t", markdown="#"))
    (run_id,) = add(db, Run(cv_id=cv_id, listing_text="original"))

    await Engine(settings).drive(run_id)

    with Session(db) as session:
        run = session.get(Run, run_id)
        assert run.status == RunStatus.FAILED
        assert run.error == "created: boom"
        assert run.listing_text == "original"
        kinds = [e.kind for e in session.exec(select(Event).where(Event.run_id == run_id))]
        assert "step_started" in kinds and "step_finished" not in kinds
