import pytest

from application_crew.domain.extraction import (
    ExtractedCertification,
    ExtractedCV,
    ExtractedEducation,
    ExtractedLanguage,
    ExtractedPosition,
)
from application_crew.llm.client import Usage


def make_extracted(**overrides) -> ExtractedCV:
    data = dict(
        name="Jane Doe",
        city="Berlin",
        address=None,
        email="jane@example.com",
        phone="+49 30 1234567",
        links=["https://github.com/janedoe"],
        languages=[
            ExtractedLanguage(name="German", level="native"),
            ExtractedLanguage(name="English", level="C1"),
        ],
        skills=["Python", "Kubernetes", "python", "PostgreSQL"],
        soft_skills=[],
        certifications=[
            ExtractedCertification(
                name="Certified Kubernetes Administrator",
                abbreviation="CKA",
                issuer="CNCF",
                year=2023,
            )
        ],
        education=[
            ExtractedEducation(
                qualification="M.Sc. Computer Science",
                institution="TU Berlin",
                location="Berlin",
                start="2014-10",
                end="2017-03",
            )
        ],
        positions=[
            ExtractedPosition(
                company="Acme GmbH",
                role="Senior Backend Engineer",
                location="Berlin",
                start="2021-04",
                end="2099-01",
                is_current=True,
                responsibilities=["Own the payments API", " "],
                achievements=["Cut p99 latency by 40%"],
                technologies=["Python", "FastAPI", "Python"],
            ),
            ExtractedPosition(
                company="Beta AG",
                role="Backend Engineer",
                location="Hamburg",
                start="2017-04",
                end="2021-03",
                is_current=False,
                responsibilities=["Built data pipelines"],
                achievements=[],
                technologies=["Java"],
            ),
        ],
        projects=["Open-source contributor to httpx (2022)"],
        publications=[],
        volunteering=[],
        notice_period="3 months",
        earliest_start=None,
        salary_expectation=None,
        work_permit=None,
    )
    data.update(overrides)
    return ExtractedCV(**data)


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
            self.calls.append({"step": step, "context": stable_context})
            if self.error:
                raise self.error
            return self.result, USAGE

    fake = Fake()
    fake.calls = []
    monkeypatch.setattr("application_crew.llm.client.structured", fake.structured)
    return fake
