import time

import pytest
from fastapi.testclient import TestClient

from application_crew.config import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    from application_crew.web.app import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def wait_for(client, url, text, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        page = client.get(url)
        if text in page.text:
            return page
        time.sleep(0.05)
    raise AssertionError(f"{text!r} not found on {url}")


def test_health_and_index(client):
    assert client.get("/health").json()["status"] == "ok"
    page = client.get("/")
    assert page.status_code == 200
    assert "Add and confirm a CV first." in page.text


def test_cv_parse_fix_and_confirm_flow(client, fake_llm):
    fake_llm.result.phone = ""
    resp = client.post("/cvs", data={"label": "Main CV", "markdown": "# Jane Doe"})
    assert resp.status_code == 200  # followed redirect to the CV page
    cv_url = str(resp.url.path)

    page = wait_for(client, cv_url, "waiting_for_confirmation")
    assert "Senior Backend Engineer · Acme GmbH" in page.text
    assert "Contact: no phone number found." in page.text

    # Starting a run with an unconfirmed CV is refused.
    cv_id = cv_url.rsplit("/", 1)[1]
    assert client.post("/runs", data={"cv_id": cv_id, "listing_text": "x"}).status_code == 409

    page = client.post(f"{cv_url}/fields", data={"contact.phone": "+49 40 999"})
    assert "Contact: no phone number found." not in page.text
    assert "+49 40 999" in page.text

    client.post(f"{cv_url}/confirm")
    assert "Main CV</option>" in client.get("/").text


def test_failed_parse_can_be_retried(client, fake_llm):
    fake_llm.error = RuntimeError("API unavailable")
    resp = client.post("/cvs", data={"label": "Main CV", "markdown": "# Jane Doe"})
    cv_url = str(resp.url.path)
    wait_for(client, cv_url, "API unavailable")

    fake_llm.error = None
    client.post(f"{cv_url}/markdown", data={"markdown": "# Jane Doe\nfixed"})
    wait_for(client, cv_url, "waiting_for_confirmation")


def test_demo_mode_parses_sample_cv_without_api(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DEMO", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    from application_crew.web.app import app

    try:
        with TestClient(app) as client:
            assert client.get("/health").json()["demo"] is True
            resp = client.post("/cvs", data={"label": "Mine", "markdown": "# Somebody Else"})
            page = wait_for(client, str(resp.url.path), "waiting_for_confirmation")
            assert "Demo mode" in page.text
            assert "Jane Doe" in page.text
            assert "Contact: no phone number found." in page.text
    finally:
        get_settings.cache_clear()


def confirmed_cv(client) -> str:
    resp = client.post("/cvs", data={"label": "Main CV", "markdown": "# Jane Doe"})
    cv_url = str(resp.url.path)
    wait_for(client, cv_url, "waiting_for_confirmation")
    client.post(f"{cv_url}/confirm")
    return cv_url.rsplit("/", 1)[1]


def test_run_stops_on_must_have_and_can_be_declined_or_continued(client):
    cv_id = confirmed_cv(client)
    form = {
        "cv_id": cv_id,
        "listing_text": "Wir suchen ...",
        "salary_min": "100000",
        "salary_min_must": "on",
        "nice_other": "Jobrad",
    }

    resp = client.post("/runs", data=form)
    run_url = str(resp.url.path)
    page = wait_for(client, run_url, "stopped_by_requirements")
    assert "A must-have requirement isn't met" in page.text
    assert "Senior Python Developer (m/w/d)" in page.text
    assert "Band 70,000–85,000 EUR/year is below 100,000 EUR/year" in page.text

    page = client.post(f"{run_url}/decline")
    assert "status-declined" in page.text
    assert client.post(f"{run_url}/continue").status_code == 409  # declined is final

    # The form is pre-filled from the last run.
    index = client.get("/").text
    assert 'value="100000"' in index and ">Jobrad</textarea>" in index

    run_url = str(client.post("/runs", data=form).url.path)
    wait_for(client, run_url, "stopped_by_requirements")
    client.post(f"{run_url}/continue")
    wait_for(client, run_url, "step &#39;matching&#39; not implemented")


def test_failed_fetch_waits_for_pasted_text(client, monkeypatch):
    from application_crew.fetch.listing import FetchResult

    async def blocked(url):
        return FetchResult(ok=False, error="403 Forbidden")

    monkeypatch.setattr("application_crew.steps.listing.fetch_listing", blocked)
    cv_id = confirmed_cv(client)
    run_url = str(
        client.post("/runs", data={"cv_id": cv_id, "urls": "https://x.test/job"}).url.path
    )
    wait_for(client, run_url, "Paste the listing")

    client.post(f"{run_url}/listing-text", data={"listing_text": "Wir suchen ..."})
    wait_for(client, run_url, "Senior Python Developer (m/w/d)")
