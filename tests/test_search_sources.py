"""Job source adapters against recorded API responses (no network)."""

import json
from datetime import date

import httpx
import pytest

from mappe.search.models import SearchQuery
from mappe.search.sources import SOURCES, hn
from mappe.search.sources.base import SAMPLES_DIR, SourceOptions, clear_cache
from mappe.search.text import fix_mojibake, html_to_text, parse_date, parse_salary_text


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


def test_himalayas_keeps_jobs_open_to_germany():
    hits = parse("himalayas")
    assert len(hits) == len(sample("himalayas")["jobs"]) - 1  # the US-only job is dropped
    assert all(h.remote == "remote" and "<" not in h.description for h in hits)
    assert "Staff Engineer (US only)" not in {h.title for h in hits}
    assert {h.location for h in hits} == {"Germany", "Germany + 51 more countries", "Anywhere"}
    assert all(h.external_id.count("/jobs/") == 1 and isinstance(h.posted_at, date) for h in hits)
    paid = {(h.salary_min, h.salary_currency, h.salary_period) for h in hits if h.salary_min}
    assert paid == {(2400, "EUR", "month"), (60000, "EUR", "year")}


def test_hn_reads_the_first_line_of_each_post():
    hits = {h.company: h for h in parse("hn")}
    assert len(hits) == 15  # job seeker, US-only remote, onsite abroad and deleted are dropped
    assert not {"GovStar", "Curiosity", "Sparcle"} & set(hits)

    mesmer = hits["Mesmer"]
    assert (mesmer.title, mesmer.location, mesmer.remote) == (
        "Founding Engineer",
        "Berlin | ONSITE",
        "onsite",
    )
    assert (mesmer.salary_min, mesmer.salary_max, mesmer.salary_currency) == (100000, 140000, "EUR")
    assert mesmer.url == mesmer.view_url == "https://news.ycombinator.com/item?id=50340449"
    assert "\n\n" in mesmer.description and "<p>" not in mesmer.description

    assert hits["ICEYE"].remote == "hybrid"
    assert hits["Baserow"].remote == "remote"
    assert hits["Better Stack"].title == "Open roles at Better Stack"  # no role in the line
    assert all(h.posted_at == date(2026, 11, 2) for h in [mesmer, hits["River"]])


@pytest.mark.parametrize(
    ("head", "kept", "mode"),
    [
        ("Acme | Backend Engineer | REMOTE", True, "remote"),  # no restriction stated
        ("Acme | Backend Engineer | REMOTE (US)", False, None),
        ("Acme | Backend Engineer | Remote (U.S. only)", False, None),
        ("Acme | Backend Engineer | Hamburg | ONSITE (part remote)", True, "hybrid"),
        ("Acme | Backend Engineer | Paris | ONSITE", False, None),
        ("Acme | Backend Engineer | Hamburg", True, None),
        ("Acme | Backend Engineer", False, None),  # not the header format
        ("Location: Berlin | Remote: yes | Willing to relocate", False, None),  # a job seeker
    ],
)
def test_hn_location_rules(head, kept, mode):
    hit = hn.parse_post({"id": 7, "text": f"{head}<p>We build things.", "created_at": "2026-11-02"})
    assert (hit is not None) == kept
    if hit:
        assert hit.remote == mode and hit.title == "Backend Engineer" and hit.company == "Acme"


def test_hn_ignores_numbers_that_are_not_salaries():
    hit = hn.parse_post(
        {"id": 7, "text": "Acme | Engineer | REMOTE (EU) | 30k users | 0.5% equity"}
    )
    assert hit and hit.salary_min is None and hit.salary_currency is None


def test_remoteok_text_is_repaired():
    [hit] = SOURCES["remoteok"].parse(
        [
            {
                "id": 1,
                "url": "https://remoteok.com/1",
                "position": "Engineer \u00e2\u0080\u0094 Core",
                "location": "M\u00c3\u00bcnchen, Germany",
                "company": "Acme",
            }
        ]
    )
    assert (hit.title, hit.location) == ("Engineer \u2014 Core", "München, Germany")
    assert fix_mojibake("Zürich €") == "Zürich €" and fix_mojibake(None) == ""
    assert fix_mojibake("â\x80 €") == "â\x80 €"  # not repairable: left as it is


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
        titles=["Softwareentwickler", "Backend Developer"],
        places=["Berlin", "Hamburg"],
        radii={"Berlin": 10},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payloads = await SOURCES["ba"].fetch(client, query, SourceOptions())
    assert len(payloads) == 4
    assert all(r.headers["X-API-Key"] == "jobboerse-jobsuche" for r in seen)
    assert seen[0].url.params["was"] == "Softwareentwickler"
    assert seen[0].url.params["umkreis"] == "10"
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
        ("€100–140k + 0.5–1% equity", (100000, 140000, "EUR", "year")),
        ("$23-34/hr", (23, 34, "USD", "hour")),
        ("", (None, None, None, None)),
        ("competitive", (None, None, None, None)),
    ],
)
def test_salary_text(text, expected):
    assert parse_salary_text(text) == expected


def test_dates():
    assert parse_date("2026-11-02T09:42:28.340") == date(2026, 11, 2)
    assert parse_date(1793742325) == date(2026, 11, 3)
    assert parse_date("1793742325") == date(2026, 11, 3)
    assert parse_date("soon") is None


def test_ba_titles_that_say_remote_are_remote():
    payload = sample("ba")
    job = dict(payload["ergebnisliste"][0], stellenangebotsTitel="Software Architect (Remote)")
    job.pop("homeofficemoeglich", None)
    (parsed,) = SOURCES["ba"].parse({"ergebnisliste": [job]})
    assert parsed.remote == "remote"


async def test_himalayas_searches_germany_one_title_at_a_time():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"jobs": []})

    titles = [f"Title {i}" for i in range(8)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await SOURCES["himalayas"].fetch(client, SearchQuery(titles=titles), SourceOptions())
    assert [r.url.params["q"] for r in seen] == titles[:5]
    assert all(r.url.params["country"] == "DE" for r in seen)


async def test_hn_fetches_the_newest_hiring_thread_once():
    clear_cache()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/search_by_date"):
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "objectID": "2",
                            "title": "Ask HN: Who wants to be hired? (November 2026)",
                        },
                        {"objectID": "1", "title": "Ask HN: Who is hiring? (November 2026)"},
                    ]
                },
            )
        return httpx.Response(200, json={"id": 1, "children": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for _ in range(2):
            payloads = await SOURCES["hn"].fetch(client, SearchQuery(titles=["x"]), SourceOptions())
    assert payloads == [{"id": 1, "children": []}]
    assert seen == ["/api/v1/search_by_date", "/api/v1/items/1"]

    clear_cache()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"hits": []}))
    ) as client:
        assert await SOURCES["hn"].fetch(client, SearchQuery(titles=["x"]), SourceOptions()) == []
    clear_cache()
