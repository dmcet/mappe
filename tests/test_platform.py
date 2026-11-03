"""Migrations, usage ledger, live status and the pipeline view."""

import sqlite3
from datetime import UTC, datetime

from sqlmodel import Session, select

from application_crew.db import Usage, init_engine
from application_crew.llm.client import Usage as TokenUsage
from application_crew.llm.client import record_usage
from application_crew.runner import activity
from application_crew.runner.states import RunStatus
from application_crew.web.pipeline import pipeline

LEGACY_SCHEMA = """
CREATE TABLE cv (id INTEGER NOT NULL, label VARCHAR NOT NULL, markdown VARCHAR NOT NULL,
  status VARCHAR(24) NOT NULL, parsed JSON, warnings JSON, error VARCHAR,
  cost_usd FLOAT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  PRIMARY KEY (id));
CREATE TABLE run (id INTEGER NOT NULL, cv_id INTEGER NOT NULL, listing_url VARCHAR,
  listing_text VARCHAR, status VARCHAR(26) NOT NULL, state JSON, requirements JSON,
  error VARCHAR, cost_usd FLOAT NOT NULL, created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(cv_id) REFERENCES cv (id));
CREATE INDEX ix_run_cv_id ON run (cv_id);
CREATE INDEX ix_run_status ON run (status);
CREATE TABLE event (id INTEGER NOT NULL, run_id INTEGER NOT NULL, kind VARCHAR NOT NULL,
  message VARCHAR NOT NULL, data JSON, created_at DATETIME NOT NULL, PRIMARY KEY (id),
  FOREIGN KEY(run_id) REFERENCES run (id));
CREATE INDEX ix_event_run_id ON event (run_id);
INSERT INTO cv VALUES (1, 'Old', '#', 'CONFIRMED', '{}', '[]', NULL, 0.12,
  '2026-11-01 10:00:00', '2026-11-01 10:00:00');
INSERT INTO run VALUES (7, 1, NULL, 'text', 'DONE', '{}', '[]', NULL, 0.70,
  '2026-11-02 10:00:00', '2026-11-02 10:00:00');
"""


def test_fresh_database_is_migrated_to_head(tmp_path):
    db = tmp_path / "fresh.db"
    init_engine(f"sqlite:///{db}")
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"cv", "run", "event", "usage", "alembic_version"} <= tables
    assert con.execute("select version_num from alembic_version").fetchone()[0] == "0005"


def test_database_from_before_migrations_is_adopted_and_keeps_its_data(tmp_path):
    db = tmp_path / "legacy.db"
    con = sqlite3.connect(db)
    con.executescript(LEGACY_SCHEMA)
    con.commit()
    con.close()

    engine = init_engine(f"sqlite:///{db}")
    con = sqlite3.connect(db)
    assert con.execute("select version_num from alembic_version").fetchone()[0] == "0005"
    assert con.execute("select count(*) from run").fetchone()[0] == 1
    with Session(engine) as session:
        rows = session.exec(select(Usage).order_by(Usage.cost_usd)).all()
    # Existing totals carried over as legacy rows, so the overall spend stays correct.
    assert [(r.step, r.cv_id, r.run_id, r.cost_usd) for r in rows] == [
        ("legacy", 1, None, 0.12),
        ("legacy", None, 7, 0.70),
    ]
    init_engine(f"sqlite:///{db}")  # running again is a no-op


def test_usage_is_recorded_for_the_current_job(tmp_path):
    engine = init_engine(f"sqlite:///{tmp_path / 'u.db'}")
    activity.begin("run", 42, "Speechify")
    try:
        activity.update("Claude · Recruiter review", phase="reviewing", model="claude-opus-5-5")
        jobs = activity.snapshot()
        assert jobs[0]["detail"] == "Claude · Recruiter review" and jobs[0]["model"]
        record_usage("recruiter", "claude-opus-5-5", TokenUsage(10_000, 1_000, 0, 0))
    finally:
        activity.end()
    assert activity.snapshot() == []
    with Session(engine) as session:
        row = session.exec(select(Usage)).one()
    assert (row.run_id, row.step) == (42, "recruiter")
    assert round(row.cost_usd, 4) == 0.06  # 10k in * $4/M + 1k out * $20/M


def test_status_and_costs_endpoints(client):
    record_usage("parse_cv", "claude-opus-5-5", TokenUsage(1_000_000, 0, 0, 0))  # $4
    status = client.get("/api/status").json()
    assert status["jobs"] == [] and status["costs"]["total_usd"] == 4.0
    assert status["waiting_for_you"] == []
    costs = client.get("/api/costs").json()
    assert costs["today_usd"] == 4.0 and costs["by_model"][0]["name"] == "Opus 5.5"
    assert costs["last_30_days"][-1] == {
        "date": datetime.now(UTC).date().isoformat(),
        "cost_usd": 4.0,
    }


def test_pipeline_states():
    stages = pipeline(RunStatus.REVIEWING, "authoring", drafts=2)
    states = {s["key"]: (s["state"], s["hint"]) for s in stages}
    assert states["match"] == ("done", "")
    assert states["review"] == ("active", "draft 2")
    assert states["final"] == ("pending", "")

    failed = {s["key"]: s["state"] for s in pipeline(RunStatus.FAILED, "matching")}
    assert failed["parse"] == "done" and failed["match"] == "failed"
    assert failed["author"] == "pending"
    waiting = {s["key"]: s for s in pipeline(RunStatus.WAITING_FOR_FINAL_REVIEW, "reviewing")}
    assert waiting["final"]["state"] == "waiting"
    assert waiting["final"]["hint"] == "Review and approve the documents"


def test_waiting_for_you_lists_runs_at_a_gate(client):
    from tests.test_web import confirmed_cv, start_run, status_is, wait_for

    run_id = start_run(client, confirmed_cv(client))
    wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_apply_decision"))
    waiting = client.get("/api/status").json()["waiting_for_you"]
    assert waiting == [
        {
            "id": run_id,
            "title": "Senior Python Developer (m/w/d) · Beispiel Mobility GmbH",
            "status": "waiting_for_apply_decision",
            "prompt": "Decide whether to apply",
        }
    ]


def test_old_drafts_are_normalised_for_the_frontend():
    from application_crew.web.runs import _drafts

    old = [{"iteration": 1, "cv": {"titles": [{"position_id": "pos1", "title": "Engineer"}]}}]
    assert _drafts(old)[0]["cv"]["titles"] == [{"id": "pos1", "title": "Engineer"}]
    assert _drafts(None) is None


async def test_prompt_layout_and_cache_markers(tmp_path, monkeypatch, fake_llm):
    """CV and listing come first, byte-identical in every step that uses them. Only blocks
    that a later call with the same schema reads again carry a cache marker (the schema
    is part of the cached prefix, so steps can't share entries)."""
    from application_crew.config import DEFAULT_CONFIG_PATH, load_settings
    from application_crew.llm.client import COMMON_SYSTEM, _content
    from tests.test_author import drive_to_documents, make_run

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    db, run_id = make_run(tmp_path, cover_letter=True)
    await drive_to_documents(db, run_id, load_settings(DEFAULT_CONFIG_PATH), cover_letter=True)
    calls = {c["step"]: c["blocks"] for c in fake_llm.calls}

    shared_steps = ["match", "author_cv", "author_letter", "recruiter"]
    first_two = {step: [b.text for b in calls[step][:2]] for step in shared_steps}
    assert all(texts == first_two["match"] for texts in first_two.values())
    assert first_two["match"][0].startswith("<cv>") and first_two["match"][1].startswith(
        "<listing>"
    )
    reused = ["author_cv", "author_letter", "recruiter"]  # reworks / further review rounds
    assert all(calls[step][0].cache and calls[step][1].cache for step in reused)
    # One-off calls carry no markers at all.
    one_off = calls["parse_listing"] + calls["claims_check"] + calls["match"]
    assert not any(b.cache for b in one_off)
    # The cover letter's changing part (the tailored CV) comes after the cached context.
    letter = calls["author_letter"]
    assert letter[-1].text.startswith("<tailored_cv>") and not letter[-1].cache
    assert letter[-2].cache  # assessment and experience, reused by reworks
    # The system prompt is the same for every step.
    assert "Application Crew" in COMMON_SYSTEM
    content = _content(calls["author_cv"], "task")
    assert [("cache_control" in c) for c in content] == [True, True, False, True, False]
