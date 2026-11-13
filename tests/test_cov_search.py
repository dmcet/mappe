"""Job search edge cases: helpers, ranking corners, source fetches and failure handling."""

import asyncio
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np

from mappe.config import ReviewConfig, SearchConfig, Settings, StepLLMConfig
from mappe.domain.extraction import to_parsed_cv
from mappe.domain.models import Skill
from mappe.fetch.listing import USER_AGENT
from mappe.search import semantic, service
from mappe.search.dedupe import dedupe
from mappe.search.models import JobHit, SearchQuery
from mappe.search.queries import title_variants
from mappe.search.rank import _freshness, cv_skills, rank, title_fit
from mappe.search.sources import SOURCES, ba
from mappe.search.sources.base import Source, SourceOptions, clear_cache
from mappe.search.text import html_to_text, parse_date, parse_salary_text
from tests.conftest import make_extracted

TODAY = date(2026, 11, 3)
CV = to_parsed_cv(make_extracted())


def hit(title="Backend Engineer", **kw):
    data = dict(
        source="arbeitnow",
        external_id=title,
        url=f"https://example.com/{title.replace(' ', '-')}",
        view_url="https://example.com",
        title=title,
        posted_at=TODAY,
    )
    return JobHit(**(data | kw))


def settings(**search) -> Settings:
    return Settings(
        data_dir=Path("/tmp/unused"),
        max_concurrent_runs=1,
        review=ReviewConfig(),
        llm_default=StepLLMConfig("m", "low", 100),
        search=SearchConfig(**search),
    )


# --- models, text, queries, dedupe ------------------------------------------------------


def test_listing_text_shows_salary_range_or_single_amount():
    ranged = hit(salary_min=60000, salary_max=80000, salary_currency="EUR", description="Text")
    assert "Salary: 60,000 - 80,000 EUR/year" in ranged.listing_text()
    assert ranged.listing_text().endswith("\n\nText")
    single = hit(salary_max=5000, salary_period="month", remote="remote", location="Berlin")
    assert single.listing_text().startswith(
        "Backend Engineer\nLocation: Berlin\nRemote\nSalary: 5,000 /month"
    )


def test_text_helpers_handle_empty_values():
    assert html_to_text("") == "" and html_to_text(None) == ""
    # Digits, but only noise below 10: currency and period are kept, amounts unknown.
    assert parse_salary_text("5 € / month") == (None, None, "EUR", "month")
    assert parse_date(None) is None and parse_date("") is None


def test_single_word_titles_without_a_known_form_have_no_variant():
    assert title_variants("Kubernetes") == []


def test_dedupe_merges_hits_with_the_same_url_from_different_sources():
    a = hit(source="ba", external_id="1", url="https://jobs.example/42?utm=x")
    b = hit(source="arbeitnow", external_id="2", url="https://jobs.example/42/", description="x")
    merged = dedupe([a, b])
    assert len(merged) == 1
    assert merged[0].source == "arbeitnow" and merged[0].also_on == ["ba"]


# --- ranking ----------------------------------------------------------------------------


def test_short_skills_match_case_sensitively_and_duplicates_count_once():
    cv = CV.model_copy(
        update={
            "skills": [Skill(name="Go", level="advanced"), Skill(name="go", level="basic")]
            + CV.skills
        }
    )
    skills = {s.name: s for s in cv_skills(cv, TODAY)}
    assert "go" not in skills  # the duplicate is dropped
    pattern = skills["Go"].pattern
    assert pattern.search("We use Go and Python") and not pattern.search("let's go")


def test_title_fit_without_title_or_candidates_is_zero():
    assert title_fit("", ["Backend Engineer"]) == 0.0
    assert title_fit("Backend Engineer", []) == 0.0


def test_unknown_posting_date_counts_as_half_fresh():
    assert _freshness(hit(posted_at=None), TODAY, 30) == 0.5


def test_onsite_location_that_mentions_remote_is_not_hidden_as_elsewhere():
    h = hit(location="Amsterdam (Remote)", description="Python Kubernetes PostgreSQL")
    [ranked] = rank([h], CV, [], today=TODAY)
    assert ranked.hidden != "elsewhere"
    [abroad] = rank([hit(location="Amsterdam", description="Python")], CV, [], today=TODAY)
    assert abroad.hidden == "elsewhere"


# --- semantic model loading -------------------------------------------------------------


def test_semantic_turned_off_loads_nothing():
    cfg = SearchConfig(semantic=False)
    assert semantic.get_embedder(cfg) is None
    assert semantic.unavailable_reason(cfg) == "turned off in config.toml"


def test_missing_model_is_remembered_with_its_reason(monkeypatch):
    monkeypatch.setattr(semantic, "_loaded", {})
    monkeypatch.setattr(semantic, "_errors", {})
    calls = []

    class Broken:
        def __init__(self, name, cache_dir):
            calls.append(name)
            raise FileNotFoundError("no model files")

    monkeypatch.setattr(semantic, "FastEmbedder", Broken)
    cfg = SearchConfig(semantic_model="some/model")
    assert semantic.get_embedder(cfg) is None
    assert semantic.get_embedder(cfg) is None  # not tried again
    assert calls == ["some/model"]
    assert semantic.unavailable_reason(cfg) == "FileNotFoundError: no model files"


# --- service ----------------------------------------------------------------------------


async def test_make_client_sets_timeout_redirects_and_user_agent():
    async with service.make_client(7.0) as client:
        assert client.timeout.read == 7.0
        assert client.follow_redirects is True
        assert client.headers["User-Agent"] == USER_AGENT


def test_demo_dates_are_unchanged_without_dates():
    hits = [hit(posted_at=None)]
    assert service._as_of_today(hits) == hits


def test_demo_dates_shift_so_the_newest_is_today():
    old = date.today() - timedelta(days=10)
    shifted = service._as_of_today([hit(posted_at=old), hit("Other", posted_at=None)])
    assert shifted[0].posted_at == date.today() and shifted[1].posted_at is None


def _source(fetch) -> Source:
    return Source(key="test", label="Test", home="https://x.test", fetch=fetch, parse=lambda p: [])


async def test_slow_source_times_out():
    async def slow(client, query, opts):
        await asyncio.sleep(10)

    status = await service._run_source(
        _source(slow), None, SearchQuery(titles=["x"]), settings(timeout_seconds=0.01)
    )
    assert status.error == "timed out" and status.count == 0


async def test_broken_source_reports_the_error_instead_of_failing():
    async def broken(client, query, opts):
        raise ValueError("unexpected payload")

    status = await service._run_source(_source(broken), None, SearchQuery(titles=["x"]), settings())
    assert status.error == "ValueError: unexpected payload" and status.hits == []


async def test_semantic_ranking_skipped_without_hits_or_when_off():
    assert await service._semantic(CV, [], {}, settings()) == (
        {"semantic": False, "note": None},
        {},
    )
    assert await service._semantic(CV, [hit()], {}, settings(semantic=False)) == (
        {"semantic": False, "note": "turned off in config.toml"},
        {},
    )


async def test_semantic_ranking_failure_falls_back_to_keywords(monkeypatch):
    class Failing:
        name = "fake"

        def embed(self, texts):
            raise RuntimeError("onnx crashed")

    monkeypatch.setattr(semantic, "get_embedder", lambda cfg: Failing())
    ranking, fresh = await service._semantic(CV, [hit()], {}, settings())
    assert ranking == {"semantic": False, "note": "RuntimeError: onnx crashed"} and fresh == {}


async def test_semantic_ranking_with_a_working_model(monkeypatch):
    class Fixed:
        name = "fake"

        def embed(self, texts):
            return np.ones((len(texts), 4), dtype=np.float32)

    monkeypatch.setattr(semantic, "get_embedder", lambda cfg: Fixed())
    ranking, fresh = await service._semantic(CV, [hit()], {}, settings())
    assert ranking["semantic"] and ranking["embedded"] == 1 and ranking["reused"] == 0
    assert list(fresh) == [hit().key]


# --- sources ----------------------------------------------------------------------------


async def test_ba_fetch_stops_at_the_request_limit():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ergebnisliste": []})

    query = SearchQuery(titles=[f"T{i}" for i in range(5)], places=["Berlin", "Hamburg"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payloads = await SOURCES["ba"].fetch(client, query, SourceOptions())
    assert len(payloads) == ba.MAX_REQUESTS == len(seen)


def test_ba_full_home_office_is_remote():
    job = {
        "referenznummer": "R1",
        "stellenangebotsTitel": "Python Entwickler",
        "homeofficemoeglich": True,
        "homeofficeprozent": 100,
    }
    [parsed] = ba.parse({"ergebnisliste": [job]})
    assert parsed.remote == "remote" and parsed.onsite_days_per_week is None


async def test_remoteok_fetch_is_cached():
    clear_cache()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[{"legal": "notice"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for _ in range(2):
            payloads = await SOURCES["remoteok"].fetch(
                client, SearchQuery(titles=["x"]), SourceOptions()
            )
    assert payloads == [[{"legal": "notice"}]]
    assert len(calls) == 1 and calls[0].url.host == "remoteok.com"
    clear_cache()
