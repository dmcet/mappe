"""Job source adapters against recorded API responses (no network)."""

import json
from datetime import date

import httpx
import pytest

from application_crew.search.models import SearchQuery
from application_crew.search.sources import SOURCES
from application_crew.search.sources.base import SAMPLES_DIR, SourceOptions, clear_cache
from application_crew.search.text import html_to_text, parse_date, parse_salary_text


def sample(key):
    return json.loads((SAMPLES_DIR / f"{key}.json").read_text(encoding="utf-8"))


def parse(key):
    return SOURCES[key].parse(sample(key))


def test_ba_maps_location_salary_and_home_office():
    hits = parse("ba")
    assert hits and all(h.source == "ba" and h.title and h.external_id for h in hits)
    assert all(h.description == "" for h in hits)  # the search API has no text
    assert all(
        h.view_url.startswith("https://www.arbeitsagentur.de/jobsuche/jobdetail/") for h in hits
    )

    paid = [h for h in hits if h.salary_min]
    assert paid and all(h.salary_currency == "EUR" for h in paid)
    assert any(h.salary_min == h.salary_max == 72600 and h.salary_period == "year" for h in paid)
    assert any(h.salary_period == "hour" for h in paid)  # STUNDENLOHN
    assert any((h.salary_min, h.salary_max) == (60000, 70000) for h in paid)  # Gehaltsspanne

    hybrid = [h for h in hits if h.remote == "hybrid"]
    assert any(h.onsite_days_per_week == 2 for h in hybrid)  # 50 % home office
    assert "onsite" not in {h.remote for h in hits}  # "no home office" stays unknown

    external = [h for h in hits if h.url != h.view_url]
    assert external and all("yourfirm" in h.url or h.url.startswith("http") for h in external)
    assert all(h.location for h in hits)
    assert all(isinstance(h.posted_at, date) for h in hits)


def test_arbeitnow_has_text_and_remote_flag():
    hits = parse("arbeitnow")
    assert len(hits) == len(sample("arbeitnow")["data"])
    assert all("<" not in h.description and len(h.description) > 100 for h in hits)
    assert {h.remote for h in hits} == {"remote", None}  # not remote = unknown, never "onsite"


def test_remote_sources_only_keep_jobs_open_to_germany():
    for key in ("remotive", "jobicy", "remoteok"):
        hits = parse(key)
        assert all(h.remote == "remote" for h in hits), key
    remoteok = parse("remoteok")
    assert "Palo Alto" not in {h.location for h in remoteok}
    assert len(remoteok) == 2  # legal notice and the US-only job are dropped

    remotive = {h.title: h for h in parse("remotive")}
    full_stack = remotive["Full-Stack Developer"]
    assert (full_stack.salary_min, full_stack.salary_max) == (3500, 5000)
    assert (full_stack.salary_currency, full_stack.salary_period) == ("USD", "month")


def test_adzuna_ignores_predicted_salaries_and_strips_markup():
    first, second = parse("adzuna")
    assert first.title == "Backend Developer (m/w/d) Python"
    assert (first.salary_min, first.salary_max, first.salary_currency) == (65000, 80000, "EUR")
    assert second.salary_min is None  # Adzuna's estimate, not the employer's


@pytest.mark.parametrize("key", list(SOURCES))
def test_parsers_survive_empty_and_broken_payloads(key):
    assert SOURCES[key].parse({}) == []
    assert (
        SOURCES[key].parse({"data": [{}], "jobs": [{}], "results": [{}], "ergebnisliste": [{}]})
        == []
    )


async def test_ba_fetch_sends_key_and_combines_titles_and_places():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=sample("ba"))

    query = SearchQuery(
        titles=["Softwareentwickler", "Backend Developer"], places=["Berlin", "Hamburg"]
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payloads = await SOURCES["ba"].fetch(client, query, SourceOptions())
    assert len(payloads) == 4
    assert all(r.headers["X-API-Key"] == "jobboerse-jobsuche" for r in seen)
    assert seen[0].url.params["was"] == "Softwareentwickler"
    assert seen[1].url.params["wo"] == "Hamburg" and seen[1].url.params["umkreis"] == "30"


async def test_list_sources_are_cached_between_searches():
    clear_cache()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"data": [], "links": {"next": None}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for _ in range(2):
            await SOURCES["arbeitnow"].fetch(client, SearchQuery(titles=["x"]), SourceOptions())
    assert len(calls) == 1
    clear_cache()


def test_html_to_text_keeps_structure():
    text = html_to_text(
        "<p>We&nbsp;offer:</p><ul><li>Python</li><li>Remote</li></ul><script>x()</script>"
    )
    assert text == "We offer:\n\n- Python\n- Remote" or text.splitlines()[0] == "We offer:"
    assert "- Python" in text and "x()" not in text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$3.5k–$5k/month", (3500, 5000, "USD", "month")),
        ("60.000 – 75.000 €", (60000, 75000, "EUR", "year")),
        ("€70k", (70000, 70000, "EUR", "year")),
        ("", (None, None, None, None)),
        ("competitive", (None, None, None, None)),
    ],
)
def test_salary_text(text, expected):
    assert parse_salary_text(text) == expected


def test_dates():
    assert parse_date("2026-11-02T09:42:28.340") == date(2026, 11, 2)
    assert parse_date(1793742325) == date(2026, 11, 3)
    assert parse_date("soon") is None
