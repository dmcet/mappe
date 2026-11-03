from sqlmodel import Session, select

import application_crew.steps  # noqa: F401 - registers steps
from application_crew.config import DEFAULT_CONFIG_PATH, load_settings
from application_crew.db import CV, Event, Run, init_engine
from application_crew.runner.engine import Engine
from application_crew.runner.states import CVStatus, RunStatus

LISTING = "Wir suchen eine Senior Python Developerin. Wir bieten 30 Urlaubstage und ein Jobrad."


def make_run(tmp_path, requirements=()):
    db = init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(db) as session:
        cv = CV(label="test", markdown="# Jane Doe", status=CVStatus.CONFIRMED)
        session.add(cv)
        session.commit()
        run = Run(cv_id=cv.id, listing_text=LISTING, requirements=list(requirements))
        session.add(run)
        session.commit()
        return db, run.id


async def test_listing_is_parsed_and_checked_until_matching(tmp_path, fake_llm):
    db, run_id = make_run(
        tmp_path,
        [{"kind": "other", "value": "30 vacation days", "must_have": True}],
    )
    await Engine(load_settings(DEFAULT_CONFIG_PATH)).drive(run_id)

    with Session(db) as session:
        run = session.get(Run, run_id)
        # Matching isn't implemented yet, so the run stops there.
        assert run.status == RunStatus.FAILED
        assert "matching" in run.error
        assert run.state["listing"]["language"] == "de"
        assert run.state["listing"]["title"] == "Senior Python Developer (m/w/d)"
        assert run.state["requirement_results"][0]["outcome"] == "unknown"
        assert run.cost_usd > 0
        kinds = [e.kind for e in session.exec(select(Event).where(Event.run_id == run_id))]
        assert "usage" in kinds

    task = fake_llm.calls[0]["task"]
    assert "0. 30 vacation days" in task


async def test_failed_must_have_stops_the_run(tmp_path, fake_llm):
    db, run_id = make_run(tmp_path, [{"kind": "salary_min", "value": "100000", "must_have": True}])
    await Engine(load_settings(DEFAULT_CONFIG_PATH)).drive(run_id)

    with Session(db) as session:
        assert session.get(Run, run_id).status == RunStatus.STOPPED_BY_REQUIREMENTS
