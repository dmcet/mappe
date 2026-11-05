"""API edge cases: refusals (404/400/409), failure paths, the SPA fallback and the SSE stream.

Rows are inserted directly into the database, so the tests don't wait for the pipeline.
"""

import json
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from mappe.config import get_settings, load_settings
from mappe.db import CV, Event, JobHitRecord, Run, Search, SearchResult, get_engine, init_engine
from mappe.domain.extraction import to_parsed_cv
from mappe.export.pdf import ExportError
from mappe.runner import activity
from mappe.runner.states import CVStatus, RunStatus
from mappe.web import live
from mappe.web.pipeline import pipeline
from tests.conftest import make_extracted

PARSED = to_parsed_cv(make_extracted()).model_dump(mode="json")


def add(row):
    with Session(get_engine()) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def make_cv(status=CVStatus.CONFIRMED, parsed=PARSED, **kw) -> int:
    return add(CV(label="CV", markdown="# Jane", status=status, parsed=parsed, **kw)).id


def make_run(cv_id, status=RunStatus.WAITING_FOR_APPLY_DECISION, state=None) -> int:
    return add(Run(cv_id=cv_id, status=status, state=state or {})).id


def detail(resp):
    return resp.json()["detail"]


# --- frontend fallback ------------------------------------------------------------------


def test_spa_serves_build_files_and_index_for_app_routes(client, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "robots.txt").write_text("User-agent: *")
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setattr("mappe.web.app.FRONTEND_DIR", dist)

    assert client.get("/robots.txt").text == "User-agent: *"
    assert client.get("/runs/5").text == "<html>app</html>"
    assert client.get("/").text == "<html>app</html>"
    # Files outside the build are never served, even when they exist.
    assert client.get("/%2E%2E/secret.txt").text == "<html>app</html>"

    (dist / "index.html").unlink()
    resp = client.get("/runs/5")
    assert resp.status_code == 404 and "Frontend not built" in detail(resp)


# --- CVs --------------------------------------------------------------------------------


def test_cv_refusals(client):
    assert client.get("/api/cvs/999").status_code == 404
    resp = client.post("/api/cvs", json={"label": "  ", "markdown": "# Jane"})
    assert resp.status_code == 400 and detail(resp) == "Label and CV text are required"

    confirmed = make_cv()
    resp = client.patch(f"/api/cvs/{confirmed}/fields", json={"notice_period": "1 month"})
    assert resp.status_code == 409
    assert client.post(f"/api/cvs/{confirmed}/confirm").status_code == 409

    parsing = make_cv(status=CVStatus.PARSING, parsed=None)
    resp = client.put(f"/api/cvs/{parsing}/markdown", json={"markdown": "# new"})
    assert resp.status_code == 409 and detail(resp) == "CV is being parsed"
    resp = client.delete(f"/api/cvs/{parsing}")
    assert resp.status_code == 409 and "being processed" in detail(resp)

    suggesting = make_cv(roles_status="suggesting")
    resp = client.post(f"/api/cvs/{suggesting}/roles")
    assert resp.status_code == 409 and detail(resp) == "Roles are being suggested"


def test_quick_fields_outside_contact_are_saved(client):
    cv_id = make_cv(status=CVStatus.WAITING_FOR_CONFIRMATION)
    data = client.patch(
        f"/api/cvs/{cv_id}/fields", json={"notice_period": " 3 months ", "work_permit": ""}
    ).json()
    assert data["parsed"]["notice_period"] == "3 months"
    assert data["quick_values"]["notice_period"] == "3 months"
    assert data["quick_values"]["work_permit"] == ""


def test_cv_with_working_applications_cannot_be_deleted(client):
    cv_id = make_cv()
    working = make_run(cv_id, status=RunStatus.MATCHING)
    make_run(cv_id)
    resp = client.delete(f"/api/cvs/{cv_id}?cascade=true")
    assert resp.status_code == 409 and detail(resp) == (
        f"Applications [{working}] are still working; wait until they pause"
    )
    assert client.get(f"/api/cvs/{cv_id}").status_code == 200


def test_failure_after_an_unknown_stage_marks_the_last_stage_failed():
    stages = pipeline(RunStatus.FAILED, "done")
    assert [s["state"] for s in stages] == ["done"] * (len(stages) - 1) + ["failed"]
    assert pipeline(RunStatus.FAILED, "nonsense")[0]["state"] == "failed"


# --- runs -------------------------------------------------------------------------------


def test_run_creation_refusals(client):
    resp = client.post("/api/runs", json={"cv_id": 999, "listing_text": "x"})
    assert resp.status_code == 404 and detail(resp) == "CV not found"
    cv_id = make_cv()
    resp = client.post("/api/runs", json={"cv_id": cv_id, "urls": [" "], "listing_text": " "})
    assert (
        resp.status_code == 400 and detail(resp) == "Provide at least one URL or a pasted listing"
    )


def test_run_without_a_parsed_cv_has_no_facts(client):
    run_id = make_run(make_cv(), status=RunStatus.WAITING_FOR_LISTING_TEXT)
    data = client.get(f"/api/runs/{run_id}").json()
    assert data["facts"] == {} and data["status"] == "waiting_for_listing_text"
    resp = client.post(f"/api/runs/{run_id}/listing-text", json={"listing_text": "  "})
    assert resp.status_code == 400 and detail(resp) == "Paste the listing text"


def test_gate_actions_in_the_wrong_status_are_refused(client):
    run_id = make_run(make_cv(), status=RunStatus.WAITING_FOR_LISTING_TEXT)
    assert client.post(f"/api/runs/{run_id}/apply", json={}).status_code == 409
    resp = client.put(f"/api/runs/{run_id}/documents", json={"profile": "x"})
    assert resp.status_code == 409
    resp = client.get(f"/api/runs/{run_id}/edit-data")
    assert resp.status_code == 409
    assert detail(resp) == "The application is not waiting for the final review"


def test_failed_render_keeps_the_previous_draft(client, monkeypatch):
    def broken(settings, run, body):
        raise RuntimeError("Typst failed: bad markup")

    monkeypatch.setattr("mappe.web.runs.save_user_draft", broken)
    run_id = make_run(make_cv(), status=RunStatus.WAITING_FOR_FINAL_REVIEW)
    resp = client.put(f"/api/runs/{run_id}/documents", json={"profile": "x"})
    assert resp.status_code == 422 and detail(resp) == "Typst failed: bad markup"


def test_working_run_cannot_be_deleted(client):
    run_id = make_run(make_cv(), status=RunStatus.AUTHORING)
    resp = client.delete(f"/api/runs/{run_id}")
    assert resp.status_code == 409
    assert client.get(f"/api/runs/{run_id}").status_code == 200


def test_files_recorded_but_missing_on_disk_are_404(client):
    state = {
        "drafts": [{"iteration": 1, "files": {"cv.pdf": "cv.pdf"}}],
        "delivery": {"files": {"Jane_CV.pdf": "cv.pdf"}},
    }
    run_id = make_run(make_cv(), status=RunStatus.DONE, state=state)
    assert client.get(f"/api/runs/{run_id}/drafts/1/cv.pdf").status_code == 404
    assert client.get(f"/api/runs/{run_id}/final/Jane_CV.pdf").status_code == 404

    run_dir = get_settings().runs_dir / str(run_id)
    (run_dir / "draft-1").mkdir(parents=True)
    (run_dir / "draft-1" / "cv.pdf").write_bytes(b"%PDF-draft")
    (run_dir / "final").mkdir()
    (run_dir / "final" / "Jane_CV.pdf").write_bytes(b"%PDF-final")
    assert client.get(f"/api/runs/{run_id}/drafts/1/cv.pdf").content == b"%PDF-draft"
    assert client.get(f"/api/runs/{run_id}/final/Jane_CV.pdf").content == b"%PDF-final"


def test_email_draft_of_an_unfinished_run(client):
    run_id = make_run(make_cv())
    data = client.get(f"/api/runs/{run_id}/email").json()
    assert data == {"available": False, "reason": "The application isn't finished yet."}
    resp = client.get(f"/api/runs/{run_id}/email.eml")
    assert resp.status_code == 409 and detail(resp) == "The application isn't finished yet."


# --- job search -------------------------------------------------------------------------


def make_search(cv_id) -> int:
    return add(Search(cv_id=cv_id, titles=["Backend Engineer"])).id


def test_search_refusals(client):
    unparsed = make_cv(parsed=None)
    resp = client.get(f"/api/search/suggestions?cv_id={unparsed}")
    assert resp.status_code == 409 and detail(resp) == "The CV has no parsed data yet"

    cv_id = make_cv()
    resp = client.post("/api/searches", json={"cv_id": cv_id, "titles": ["  "]})
    assert resp.status_code == 400
    assert detail(resp) == "Enter at least one job title to search for"

    assert client.post("/api/job-hits/999/dismiss").status_code == 404
    assert client.post("/api/saved-searches/999/run").status_code == 404
    assert client.delete("/api/saved-searches/999").status_code == 404

    search_id = make_search(cv_id)
    resp = client.post(f"/api/searches/{search_id}/apply", json={"hit_ids": []})
    assert resp.status_code == 400 and detail(resp) == "Choose at least one listing"


def test_delete_search_keeps_its_listings(client):
    cv_id = make_cv()
    search_id = make_search(cv_id)
    record = add(
        JobHitRecord(
            source="ba",
            external_id="1",
            data={"source": "ba", "external_id": "1", "url": "u", "view_url": "v", "title": "T"},
        )
    )
    add(SearchResult(search_id=search_id, hit_id=record.id, score=50))
    assert client.get(f"/api/searches/{search_id}").json()["total"] == 1

    assert client.delete(f"/api/searches/{search_id}").status_code == 204
    assert client.get(f"/api/searches/{search_id}").status_code == 404
    with Session(get_engine()) as session:
        assert session.get(JobHitRecord, record.id) is not None


# --- exports ----------------------------------------------------------------------------


def test_export_errors_are_reported(client, monkeypatch):
    def broken(*args, **kw):
        raise ExportError("Typst is not installed")

    monkeypatch.setattr("mappe.web.export.render_report", broken)
    monkeypatch.setattr("mappe.web.export.build_zip", broken)
    cv_id = make_cv()
    search_id = make_search(cv_id)

    resp = client.get(f"/api/searches/{search_id}/export.pdf")
    assert resp.status_code == 500 and detail(resp) == "Typst is not installed"
    resp = client.get(f"/api/searches/{search_id}/export.zip")
    assert resp.status_code == 500 and detail(resp) == "Typst is not installed"
    resp = client.get(f"/api/runs/{make_run(cv_id)}/export.zip")
    assert resp.status_code == 500 and detail(resp) == "Typst is not installed"


# --- SSE stream -------------------------------------------------------------------------


@pytest.fixture
def stream_db(tmp_path):
    db = init_engine(f"sqlite:///{tmp_path / 'stream.db'}")
    with Session(db) as session:
        cv = CV(label="t", markdown="#", status=CVStatus.CONFIRMED)
        session.add(cv)
        session.commit()
        run = Run(cv_id=cv.id)
        session.add(run)
        session.commit()
        return db, run.id


async def test_stream_sends_on_change_and_stays_quiet_otherwise(stream_db, monkeypatch):
    db, run_id = stream_db
    connected = iter([True, True, True])  # then the client disconnects
    sleeps = []

    async def is_disconnected():
        return not next(connected, False)

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:  # between the 2nd and 3rd check, the run logs an event
            with Session(db) as session:
                session.add(Event(run_id=run_id, kind="step_started", message="go"))
                session.commit()

    monkeypatch.setattr(live.asyncio, "sleep", fake_sleep)
    monkeypatch.delenv("APP_DEMO", raising=False)
    monkeypatch.setattr(activity, "_jobs", {})  # no jobs running: send on change only
    engine = SimpleNamespace(settings=load_settings(), queued=lambda: [])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))
    request.is_disconnected = is_disconnected

    response = await live.stream(request)
    events = [e async for e in response.body_iterator]

    # 1st check: the first snapshot; 2nd: nothing changed, nothing sent; 3rd: the new event.
    assert sleeps == [1.0, 1.0, 1.0]
    assert [e["event"] for e in events] == ["status", "status"]
    first, second = (json.loads(e["data"]) for e in events)
    assert first["changed"] == {"runs": [], "cvs": []} and first["jobs"] == []
    assert second["changed"] == {"runs": [run_id], "cvs": []}
    assert "costs" in second and second["demo"] is False
