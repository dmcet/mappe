import pytest

from application_crew.domain.extraction import ExtractedCV
from application_crew.llm.client import Usage
from application_crew.llm.demo import demo_listing, sample_cv

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

        async def structured(self, settings, step, output, stable_context, task, **kw):
            self.calls.append({"step": step, "context": stable_context, "task": task})
            if self.error:
                raise self.error
            if step == "parse_cv":
                return self.result, USAGE
            return self.results[step], USAGE

    fake = Fake()
    fake.calls = []
    fake.results = {"parse_listing": demo_listing()}
    monkeypatch.setattr("application_crew.llm.client.structured", fake.structured)
    return fake
