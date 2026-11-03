"""Search API end to end, with the job APIs replaced by their recorded responses."""

import json
from datetime import date

import httpx
import pytest

from application_crew.search.sources.base import SAMPLES_DIR, clear_cache
from tests.test_web import confirmed_cv, status_is, wait_for

HOSTS = {
    "rest.arbeitsagentur.de": "ba",
    "www.arbeitnow.com": "arbeitnow",
    "remotive.com": "remotive",
    "jobicy.com": "jobicy",
    "remoteok.com": "remoteok",
    "api.adzuna.com": "adzuna",
}


@pytest.fixture
def job_apis(monkeypatch):
    """Serve the samples; ``job_apis.fail`` makes a source return HTTP 503."""

    class Apis:
        fail: set[str] = set()
        requests: list[httpx.Request] = []

    apis = Apis()
    apis.fail, apis.requests = set(), []

    def handler(request: httpx.Request) -> httpx.Response:
        apis.requests.append(request)
        key = HOSTS[request.url.host]
        if key in apis.fail:
            return httpx.Response(503)
        payload = json.loads((SAMPLES_DIR / f"{key}.json").read_text(encoding="utf-8"))
        if key == "arbeitnow":
            payload["links"] = {"next": None}
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        "application_crew.search.service.make_client",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    clear_cache()
    yield apis
    clear_cache()


def search(client, cv_id, **body):
    resp = client.post("/api/searches", json={"cv_id": cv_id, **body})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_suggestions(client):
    cv_id = confirmed_cv(client)
    data = client.get(f"/api/search/suggestions?cv_id={cv_id}").json()
    assert data["titles"] == ["Backend Engineer", "Backend-Entwickler"]
    sources = {s["key"]: s for s in data["sources"]}
    assert sources["ba"]["default"] and not sources["remoteok"]["default"]
    assert sources["adzuna"]["missing_env"] == ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"]


def test_search_ranks_reports_sources_and_survives_a_failing_one(client, job_apis):
    cv_id = confirmed_cv(client)
    job_apis.fail = {"jobicy"}
    data = search(
        client,
        cv_id,
        titles=["Softwareentwickler"],
        requirements=[{"kind": "location", "value": "Berlin"}],
    )

    assert data["places"] == ["Berlin"]
    sources = data["sources"]
    assert sources["ba"]["count"] > 0 and sources["ba"]["error"] is None
    assert sources["jobicy"]["error"] == "HTTP 503"
    assert sources["adzuna"]["error"] == "needs ADZUNA_APP_ID, ADZUNA_APP_KEY"
    assert "remoteok" not in sources  # not a default source

    results = data["results"]
    assert results and [r["score"] for r in results] == sorted(
        (r["score"] for r in results), reverse=True
    )
    assert all(r["is_new"] for r in results)
    first = results[0]["hit"]
    assert first["source_label"] and first["view_url"] and "description" not in first

    # The same search again: nothing is new, nothing is queried for Arbeitnow (cached).
    before = sum(r.url.host == "www.arbeitnow.com" for r in job_apis.requests)
    again = search(client, cv_id, titles=["Softwareentwickler"])
    assert not any(r["is_new"] for r in again["results"])
    assert sum(r.url.host == "www.arbeitnow.com" for r in job_apis.requests) == before
    assert [s["id"] for s in client.get("/api/searches").json()] == [again["id"], data["id"]]


def test_dismissed_hits_stay_hidden(client, job_apis):
    cv_id = confirmed_cv(client)
    data = search(client, cv_id, sources=["ba"])
    hit_id = data["results"][0]["hit"]["id"]
    client.post(f"/api/job-hits/{hit_id}/dismiss")

    shown = client.get(f"/api/searches/{data['id']}").json()
    assert next(r for r in shown["results"] if r["hit"]["id"] == hit_id)["hidden"] == "dismissed"
    later = search(client, cv_id, sources=["ba"])
    assert next(r for r in later["results"] if r["hit"]["id"] == hit_id)["hidden"] == "dismissed"

    client.post(f"/api/job-hits/{hit_id}/restore")
    shown = client.get(f"/api/searches/{later['id']}").json()
    assert next(r for r in shown["results"] if r["hit"]["id"] == hit_id)["hidden"] is None


def test_apply_starts_runs_with_text_when_the_source_has_it(client, job_apis):
    cv_id = confirmed_cv(client)
    data = search(
        client,
        cv_id,
        sources=["ba", "arbeitnow"],
        requirements=[{"kind": "salary_min", "value": "50000"}],
    )
    by_source = {}
    for r in data["results"]:
        by_source.setdefault(r["hit"]["source"], r["hit"])
    chosen = [by_source["ba"]["id"], by_source["arbeitnow"]["id"]]

    resp = client.post(f"/api/searches/{data['id']}/apply", json={"hit_ids": chosen})
    assert resp.status_code == 201, resp.text
    runs = resp.json()
    assert [r["listing_url"] for r in runs] == [
        by_source["ba"]["url"],
        by_source["arbeitnow"]["url"],
    ]

    # Arbeitnow has the full text: no fetch, the run goes straight to parsing and matching.
    text_run = wait_for(
        client, f"/api/runs/{runs[1]['id']}", status_is("waiting_for_apply_decision")
    )
    assert text_run["requirements"] == [
        {"kind": "salary_min", "value": "50000", "must_have": False}
    ]

    shown = client.get(f"/api/searches/{data['id']}").json()
    statuses = {r["hit"]["id"]: (r["hit"]["status"], r["hit"]["run_id"]) for r in shown["results"]}
    assert statuses[chosen[1]] == ("applied", runs[1]["id"])

    other = search(client, cv_id, sources=["ba"])
    resp = client.post(f"/api/searches/{other['id']}/apply", json={"hit_ids": [chosen[1]]})
    assert resp.status_code == 400  # not part of that search


def test_search_needs_titles_and_known_sources(client, job_apis):
    cv_id = confirmed_cv(client)
    assert (
        client.post("/api/searches", json={"cv_id": cv_id, "sources": ["nope"]}).status_code == 400
    )
    assert client.post("/api/searches", json={"cv_id": cv_id, "sources": []}).status_code == 400


def test_deleting_the_cv_deletes_its_searches(client, job_apis):
    cv_id = confirmed_cv(client)
    data = search(client, cv_id, sources=["ba"])
    assert client.delete(f"/api/cvs/{cv_id}").status_code == 204
    assert client.get(f"/api/searches/{data['id']}").status_code == 404


def test_demo_mode_uses_samples_dated_as_of_today(client, monkeypatch):
    from application_crew.config import get_settings

    cv_id = confirmed_cv(client)
    monkeypatch.setenv("APP_DEMO", "1")
    get_settings.cache_clear()
    requests = []

    def no_network(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    monkeypatch.setattr(
        "application_crew.search.service.make_client",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(no_network)),
    )
    data = search(client, cv_id, sources=["ba", "adzuna"])
    assert data["sources"]["ba"]["count"] > 0 and data["sources"]["adzuna"]["error"] is None
    newest = max(r["hit"]["posted_at"] for r in data["results"])
    assert newest == date.today().isoformat()
    assert requests == []  # demo mode never calls the job APIs
