import pytest

from application_crew.domain.extraction import ExtractedCV
from application_crew.llm.client import Usage
from application_crew.llm.demo import (
    demo_author_cv,
    demo_author_letter,
    demo_claims,
    demo_listing,
    demo_match,
    demo_recruiter,
    sample_cv,
)

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
    }
    monkeypatch.setattr("application_crew.llm.client.structured", fake.structured)
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch, fake_llm):
    from fastapi.testclient import TestClient

    from application_crew.config import get_settings
    from application_crew.web.app import app

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    # Independent of the shell: no demo mode, no optional job source keys.
    for name in ("APP_DEMO", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
