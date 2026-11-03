from sqlmodel import Session, select

import application_crew.steps  # noqa: F401 - registers steps
from application_crew.config import DEFAULT_CONFIG_PATH, load_settings
from application_crew.db import CV, Event, Run, init_engine
from application_crew.runner.engine import Engine
from application_crew.runner.states import RunStatus


async def test_pasted_listing_runs_until_first_unimplemented_step(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    db = init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with Session(db) as session:
        cv = CV(label="test", markdown="# Jane Doe")
        session.add(cv)
        session.commit()
        run = Run(cv_id=cv.id, listing_text="We are hiring a Python developer.")
        session.add(run)
        session.commit()
        run_id = run.id

    await Engine(load_settings(DEFAULT_CONFIG_PATH)).drive(run_id)

    with Session(db) as session:
        run = session.get(Run, run_id)
        # CREATED -> PARSING_LISTING works; parsing is not implemented yet.
        assert run.status == RunStatus.FAILED
        assert "parsing_listing" in run.error
        kinds = [e.kind for e in session.exec(select(Event).where(Event.run_id == run_id))]
        assert kinds[:3] == ["step_started", "step_finished", "status"]
