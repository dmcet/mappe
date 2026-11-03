"""Semantic ranking: vector reuse, calibration, fallback, and the real model (if baked in)."""

from datetime import date

import numpy as np
import pytest

from application_crew.config import SearchConfig
from application_crew.domain.extraction import to_parsed_cv
from application_crew.search import semantic
from application_crew.search.models import JobHit
from application_crew.search.rank import rank
from tests.conftest import FakeEmbedder, make_extracted
from tests.test_search_web import confirmed_cv, search

CV = to_parsed_cv(make_extracted())
TODAY = date(2026, 11, 3)


def hit(title, description, **kw):
    data = dict(
        source="arbeitnow",
        external_id=title,
        url=f"https://x/{title}",
        view_url="x",
        title=title,
        description=description,
        posted_at=TODAY,
    )
    return JobHit(**(data | kw))


def test_fit_is_calibrated_per_model():
    model = "jinaai/jina-embeddings-v2-base-de"
    assert semantic.fit(0.20, model) == 0.0  # unrelated job
    assert semantic.fit(0.70, model) == 1.0  # close match
    assert 0.3 < semantic.fit(0.50, model) < 0.4  # generic tech job


def test_vectors_are_reused_only_for_the_same_model_and_text():
    fake = FakeEmbedder()
    a, b = hit("Backend Engineer", "Python APIs"), hit("Data Engineer", "Spark")
    fits, fresh = semantic.similarities(fake, CV, [a, b], {}, 800)
    assert set(fits) == set(fresh) == {a.key, b.key}
    assert fake.calls == 3  # the CV and two listings

    changed = b.model_copy(update={"description": "Spark and Python now"})
    seen = []
    fits2, fresh2 = semantic.similarities(
        fake, CV, [a, changed], fresh, 800, progress=lambda d, t: seen.append((d, t))
    )
    assert set(fresh2) == {b.key}  # a reused, b re-embedded (text changed)
    assert fits2[a.key] == pytest.approx(fits[a.key], abs=1e-3)  # float16 round trip
    assert seen == [(1, 1)]


def test_vector_bytes_round_trip():
    v = np.array([0.25, -1.5, 3.0], dtype=np.float32)
    assert np.allclose(semantic.from_bytes(semantic.to_bytes(v)), v)


def test_semantic_fit_lifts_a_listing_without_keyword_overlap():
    vague = hit("Platform Engineer", "Run our services and APIs; payments; latency work.")
    without = rank([vague], CV, [], today=TODAY)[0]
    with_meaning = rank([vague], CV, [], semantic={vague.key: 0.9}, today=TODAY)[0]
    assert with_meaning.score > without.score + 15
    assert with_meaning.semantic_fit == 0.9 and without.semantic_fit is None


def test_search_reports_semantic_ranking_and_reuses_vectors(client, job_apis, fake_embedder):
    cv_id = confirmed_cv(client)
    first = search(client, cv_id, sources=["arbeitnow"])
    assert first["ranking"]["semantic"] is True and first["ranking"]["model"] == "fake"
    assert first["ranking"]["embedded"] > 0 and first["ranking"]["reused"] == 0
    assert any(r["reasons"]["semantic_fit"] is not None for r in first["results"])

    again = search(client, cv_id, sources=["arbeitnow"])
    assert again["ranking"]["embedded"] == 0
    assert again["ranking"]["reused"] == first["ranking"]["embedded"]


def test_search_falls_back_to_keywords_without_the_model(client, job_apis, monkeypatch):
    monkeypatch.setattr("application_crew.search.semantic.get_embedder", lambda cfg: None)
    monkeypatch.setitem(semantic._errors, SearchConfig().semantic_model, "model not found")
    cv_id = confirmed_cv(client)
    data = search(client, cv_id, sources=["arbeitnow"])
    assert data["ranking"] == {"semantic": False, "note": "model not found"}
    assert all(r["reasons"]["semantic_fit"] is None for r in data["results"])


def _real_model():
    try:
        return semantic.FastEmbedder(SearchConfig().semantic_model, semantic.model_cache_dir())
    except Exception:
        return None


@pytest.mark.skipif(_real_model() is None, reason="model not baked in (runs in the Docker image)")
def test_real_model_tells_related_from_unrelated_jobs():
    model = _real_model()
    backend = hit(
        "Backend-Entwickler Python (m/w/d)",
        "Du entwickelst unsere APIs mit Python, "
        "FastAPI und PostgreSQL und betreibst sie auf Kubernetes.",
    )
    sales = hit(
        "Vertriebsmitarbeiter Außendienst",
        "Du betreust Kunden im Außendienst und baust Beziehungen zu Autohäusern auf.",
    )
    fits, _ = semantic.similarities(model, CV, [backend, sales], {}, 800)
    assert fits[backend.key] > fits[sales.key] + 0.3
