"""API tests: the flows the frontend drives, end to end with a fake Claude."""

import time

from fastapi.testclient import TestClient

from application_crew.config import get_settings


def wait_for(client, url, predicate, timeout=10.0):
    """Poll a JSON endpoint until ``predicate(data)`` is true."""
    deadline = time.monotonic() + timeout
    data = None
    while time.monotonic() < deadline:
        data = client.get(url).json()
        if predicate(data):
            return data
        time.sleep(0.05)
    raise AssertionError(f"condition not met on {url}: {data}")


def status_is(*statuses):
    return lambda d: d.get("status") in statuses


def confirmed_cv(client) -> int:
    cv = client.post("/api/cvs", json={"label": "Main CV", "markdown": "# Jane Doe"}).json()
    wait_for(client, f"/api/cvs/{cv['id']}", status_is("waiting_for_confirmation"))
    client.post(f"/api/cvs/{cv['id']}/confirm")
    return cv["id"]


def start_run(client, cv_id, **body) -> int:
    body = {"cv_id": cv_id, "listing_text": "Wir suchen ...", **body}
    resp = client.post("/api/runs", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()[0]["id"]


def test_health_and_unknown_api_path(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/does-not-exist").status_code == 404


def test_cv_parse_fix_and_confirm_flow(client, fake_llm):
    fake_llm.result.phone = ""
    cv = client.post("/api/cvs", json={"label": "Main CV", "markdown": "# Jane Doe"}).json()
    data = wait_for(client, f"/api/cvs/{cv['id']}", status_is("waiting_for_confirmation"))
    assert data["parsed"]["positions"][0]["role"] == "Senior Backend Engineer"
    assert "Contact: no phone number found." in data["warnings"]
    assert data["summary"]["current_role"] == "Senior Backend Engineer at Acme GmbH"

    # Starting an application with an unconfirmed CV is refused.
    resp = client.post("/api/runs", json={"cv_id": cv["id"], "listing_text": "x"})
    assert resp.status_code == 409

    data = client.patch(f"/api/cvs/{cv['id']}/fields", json={"contact.phone": "+49 40 999"}).json()
    assert "Contact: no phone number found." not in data["warnings"]
    assert data["quick_values"]["contact.phone"] == "+49 40 999"

    assert client.post(f"/api/cvs/{cv['id']}/confirm").json()["status"] == "confirmed"
    assert [c["label"] for c in client.get("/api/cvs").json()] == ["Main CV"]


def test_failed_parse_can_be_retried(client, fake_llm):
    fake_llm.error = RuntimeError("API unavailable")
    cv = client.post("/api/cvs", json={"label": "Main CV", "markdown": "# Jane Doe"}).json()
    data = wait_for(client, f"/api/cvs/{cv['id']}", status_is("failed"))
    assert data["error"] == "API unavailable"

    fake_llm.error = None
    client.put(f"/api/cvs/{cv['id']}/markdown", json={"markdown": "# Jane Doe\nfixed"})
    wait_for(client, f"/api/cvs/{cv['id']}", status_is("waiting_for_confirmation"))


def test_run_stops_on_must_have_then_continues_to_documents(client):
    cv_id = confirmed_cv(client)
    requirements = [
        {"kind": "salary_min", "value": "100000", "must_have": True},
        {"kind": "other", "value": "Jobrad", "must_have": False},
    ]
    run_id = start_run(client, cv_id, requirements=requirements)
    data = wait_for(client, f"/api/runs/{run_id}", status_is("stopped_by_requirements"))
    assert data["title"] == "Senior Python Developer (m/w/d) · Beispiel Mobility GmbH"
    results = data["state"]["requirement_results"]
    assert results[0]["note"] == "Band 70,000–85,000 EUR/year is below 100,000 EUR/year"
    stages = {s["key"]: s["state"] for s in data["pipeline"]}
    assert stages["parse"] == "done" and stages["requirements"] == "waiting"

    data = client.post(f"/api/runs/{run_id}/decline").json()
    assert data["status"] == "declined"
    assert {s["key"]: s["state"] for s in data["pipeline"]}["requirements"] == "declined"
    assert client.post(f"/api/runs/{run_id}/continue").status_code == 409  # declined is final

    # The requirements of the last run pre-fill the form.
    assert client.get("/api/runs/requirements/last").json() == requirements

    run_id = start_run(client, cv_id, requirements=requirements)
    wait_for(client, f"/api/runs/{run_id}", status_is("stopped_by_requirements"))
    client.post(f"/api/runs/{run_id}/continue")
    data = wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_apply_decision"))
    assert data["state"]["match"]["score"] == 78
    assert (
        data["facts"]["pos1.resp1"] == "Senior Backend Engineer · Acme GmbH: Own the payments API"
    )
    assert data["state"]["cover_letter_suggested"] is True  # German listing

    client.post(f"/api/runs/{run_id}/apply", json={"cover_letter": False})
    data = wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_final_review"), 20)
    draft = data["state"]["drafts"][-1]
    assert draft["accepted"] and draft["letter"] is None
    assert data["state"]["review_stop_reason"] == "all checks passed"
    assert draft["recruiter"]["average"] == 4.2  # no cover letter: its score is ignored
    pdf = client.get(f"/api/runs/{run_id}/drafts/1/cv.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(f"/api/runs/{run_id}/drafts/1/cover-letter.pdf").status_code == 404
    assert client.get(f"/api/runs/{run_id}/drafts/1/..%2F..%2Fapp.db").status_code == 404


def test_failed_fetch_waits_for_pasted_text(client, monkeypatch):
    from application_crew.fetch.listing import FetchResult

    async def blocked(url):
        return FetchResult(ok=False, error="403 Forbidden")

    monkeypatch.setattr("application_crew.steps.listing.fetch_listing", blocked)
    cv_id = confirmed_cv(client)
    resp = client.post("/api/runs", json={"cv_id": cv_id, "urls": ["https://x.test/job"]})
    run_id = resp.json()[0]["id"]
    data = wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_listing_text"))
    assert any("403 Forbidden" in e["message"] for e in data["events"])

    client.post(f"/api/runs/{run_id}/listing-text", json={"listing_text": "Wir suchen ..."})
    wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_apply_decision"))


def test_delete_run_and_cv(client):
    cv_id = confirmed_cv(client)
    run_id = start_run(client, cv_id)
    wait_for(client, f"/api/runs/{run_id}", status_is("waiting_for_apply_decision"))
    run_dir = get_settings().runs_dir / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "x.pdf").write_bytes(b"%PDF")

    # A CV with applications needs an explicit cascade.
    assert client.delete(f"/api/cvs/{cv_id}").status_code == 409
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert not run_dir.exists()

    other = start_run(client, cv_id)
    wait_for(client, f"/api/runs/{other}", status_is("waiting_for_apply_decision"))
    assert client.delete(f"/api/cvs/{cv_id}?cascade=true").status_code == 204
    assert client.get("/api/cvs").json() == [] and client.get("/api/runs").json() == []


def test_demo_mode_parses_sample_cv_without_api(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DEMO", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    from application_crew.web.app import app

    try:
        with TestClient(app) as client:
            assert client.get("/health").json()["demo"] is True
            assert client.get("/api/status").json()["demo"] is True
            cv = client.post("/api/cvs", json={"label": "Mine", "markdown": "# Somebody"}).json()
            data = wait_for(client, f"/api/cvs/{cv['id']}", status_is("waiting_for_confirmation"))
            assert data["parsed"]["contact"]["name"] == "Jane Doe"
            assert "Contact: no phone number found." in data["warnings"]
    finally:
        get_settings.cache_clear()
