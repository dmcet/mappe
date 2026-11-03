"""Search API end to end, with the job APIs replaced by their recorded responses."""

from datetime import date

import httpx
from sqlmodel import Session

from application_crew.db import SavedSearch, get_engine
from tests.test_web import confirmed_cv, status_is, wait_for


def search(client, cv_id, **body):
    resp = client.post("/api/searches", json={"cv_id": cv_id, **body})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_suggestions(client):
    cv_id = confirmed_cv(client)
    data = client.get(f"/api/search/suggestions?cv_id={cv_id}").json()
    assert data["titles"] == [
        "Backend Engineer",
        "Python Developer",
        "Backend-Entwickler",
        "Python-Entwickler",
    ]
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


def test_live_status_shows_per_source_progress(client, job_apis, monkeypatch):
    from application_crew.runner import activity

    seen = []
    handler = job_apis.handler

    def watching(request):
        seen.append([j for j in activity.snapshot() if j["kind"] == "search"])
        return handler(request)

    monkeypatch.setattr(job_apis, "handler", watching)
    cv_id = confirmed_cv(client)
    search(client, cv_id, sources=["ba", "jobicy"], titles=["Backend Engineer"])

    jobs = [j for snapshot in seen for j in snapshot]
    assert jobs and all(j["title"] == "Job search: Backend Engineer" for j in jobs)
    assert set(jobs[0]["progress"]) == {"ba", "jobicy"}
    assert jobs[0]["detail"].startswith("Searching jobs · ")
    states = {k: v["state"] for j in jobs for k, v in j["progress"].items()}
    assert set(states.values()) <= {"running", "done"}
    assert not [j for j in activity.snapshot() if j["kind"] == "search"]  # ended


def test_saved_search_marks_what_is_new_since_its_last_run(client, job_apis):
    cv_id = confirmed_cv(client)
    first = search(
        client,
        cv_id,
        sources=["ba"],
        titles=["Softwareentwickler"],
        requirements=[{"kind": "location", "value": "Berlin"}],
    )
    saved = client.post("/api/saved-searches", json={"search_id": first["id"]}).json()
    assert saved["name"] == "Softwareentwickler · Berlin"
    assert saved["sources"] == ["ba"] and saved["last_run"]["id"] == first["id"]
    assert client.post("/api/saved-searches", json={"search_id": first["id"]}).status_code == 409

    # Another, unsaved search sees the same listings: they're not new for it ...
    other = search(client, cv_id, sources=["ba"], titles=["Softwareentwickler"])
    assert not any(r["is_new"] for r in other["results"])

    # ... and not new for the saved search either: its first run found them.
    run = client.post(f"/api/saved-searches/{saved['id']}/run").json()
    assert run["saved_id"] == saved["id"] and run["places"] == ["Berlin"]
    assert run["results"] and not any(r["is_new"] for r in run["results"])
    listed = client.get("/api/saved-searches").json()
    assert [s["last_run"]["id"] for s in listed] == [run["id"]]

    # Deleting the saved search keeps its runs as ordinary searches.
    assert client.delete(f"/api/saved-searches/{saved['id']}").status_code == 204
    assert client.get(f"/api/searches/{run['id']}").json()["saved_id"] is None


def test_saved_search_reports_listings_its_earlier_runs_missed(client, job_apis):
    cv_id = confirmed_cv(client)
    # Seen by an unsaved search first: globally old, but new for the saved search.
    search(client, cv_id, sources=["remotive"])
    first = search(client, cv_id, sources=["ba"])
    saved = client.post("/api/saved-searches", json={"search_id": first["id"], "name": "Mine"})
    saved_id = saved.json()["id"]
    with Session(get_engine()) as session:  # widen the saved search to a second source
        row = session.get(SavedSearch, saved_id)
        row.sources = ["ba", "remotive"]
        session.add(row)
        session.commit()
    run = client.post(f"/api/saved-searches/{saved_id}/run").json()
    new = {r["hit"]["source"] for r in run["results"] if r["is_new"]}
    assert new == {"remotive"}


def test_deleting_the_cv_deletes_its_saved_searches(client, job_apis):
    cv_id = confirmed_cv(client)
    first = search(client, cv_id, sources=["ba"])
    client.post("/api/saved-searches", json={"search_id": first["id"]})
    assert client.delete(f"/api/cvs/{cv_id}").status_code == 204
    assert client.get("/api/saved-searches").json() == []
