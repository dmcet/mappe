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
    fake_llm.result.phone = None
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
