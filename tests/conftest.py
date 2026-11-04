import json

import httpx
import pytest

from mappe.domain.extraction import ExtractedCV
from mappe.llm.client import Usage
from mappe.llm.demo import (
    demo_author_cv,
    demo_author_letter,
    demo_claims,
    demo_listing,
    demo_match,
    demo_recruiter,
    demo_roles,
    sample_cv,
)
from mappe.search.sources.base import SAMPLES_DIR, clear_cache

make_extracted = sample_cv


USAGE = Usage(
    input_tokens=2000, output_tokens=1500, cache_read_input_tokens=0, cache_creation_input_tokens=0
)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace Claude with a canned extraction. Set ``fake_llm.result`` or ``.error``."""

    class Fake:
        result: ExtractedCV = make_extracted()
        error: Exception | None = None
        calls: list[dict] = []

        async def structured(self, settings, step, output, blocks, task, **kw):
            context = "\n".join(b.text for b in blocks)
            self.calls.append({"step": step, "context": context, "task": task, "blocks": blocks})
            if self.error:
                raise self.error
            if step == "parse_cv":
                return self.result, USAGE
            result = self.results[step]
            if isinstance(result, list):  # a sequence of answers, e.g. draft 1, draft 2
                result = result.pop(0)
            return result, USAGE

    fake = Fake()
    fake.calls = []
    fake.results = {
        "parse_listing": demo_listing(),
        "match": demo_match(),
        "author_cv": demo_author_cv(),
        "author_letter": demo_author_letter(),
        "claims_check": demo_claims(),
        "recruiter": demo_recruiter(),
        "suggest_roles": demo_roles(),
    }
    monkeypatch.setattr("mappe.llm.client.structured", fake.structured)
    return fake


class FakeEmbedder:
    """Bag-of-words vectors: deterministic, instant, no model download."""

    name = "fake"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        import re

        import numpy as np

        self.calls += len(texts)
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in re.findall(r"\w+", text.casefold()):
                out[i, hash(word) % 256] += 1.0
        return out


@pytest.fixture
def fake_embedder(monkeypatch):
    fake = FakeEmbedder()
    monkeypatch.setattr("mappe.search.semantic.get_embedder", lambda cfg: fake)
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch, fake_llm, fake_embedder):
    from fastapi.testclient import TestClient

    from mappe.config import get_settings
    from mappe.web.app import app

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    # Independent of the shell: no demo mode, no optional job source keys.
    for name in ("APP_DEMO", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


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

    apis.handler = handler
    monkeypatch.setattr(
        "mappe.search.service.make_client",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: apis.handler(r))),
    )
    clear_cache()
    yield apis
    clear_cache()
