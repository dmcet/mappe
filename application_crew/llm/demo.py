"""Demo mode: canned Claude responses so the UI can be explored without an API key.

The sample data never depends on the input. The UI shows a banner while demo mode is on.
"""

from __future__ import annotations

from pydantic import BaseModel

from application_crew.domain.extraction import (
    ExtractedCertification,
    ExtractedCV,
    ExtractedEducation,
    ExtractedLanguage,
    ExtractedPosition,
)


def sample_cv(**overrides) -> ExtractedCV:
    """A complete sample CV (produces no completeness warnings)."""
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


def demo_cv() -> ExtractedCV:
    """The sample CV with a few gaps, so the demo shows warnings and quick fixes."""
    cv = sample_cv(
        phone=None,
        languages=[
            ExtractedLanguage(name="German", level="native"),
            ExtractedLanguage(name="English", level="fluent"),
        ],
    )
    cv.positions[1].location = None
    return cv


def demo_response(step: str, output: type[BaseModel]) -> BaseModel:
    if step == "parse_cv" and output is ExtractedCV:
        return demo_cv()
    raise NotImplementedError(f"demo mode has no sample response for step '{step}'")
