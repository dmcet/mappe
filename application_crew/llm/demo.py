"""Demo mode: canned Claude responses so the UI can be explored without an API key.

The sample data never depends on the input (CV or listing).
The UI shows a banner while demo mode is on.
"""

from __future__ import annotations

from pydantic import BaseModel

from application_crew.domain.extraction import (
    ExtractedCertification,
    ExtractedCV,
    ExtractedEducation,
    ExtractedLanguage,
    ExtractedPosition,
    ExtractedSkill,
)
from application_crew.domain.listing import ExtractedListing


def sample_cv(**overrides) -> ExtractedCV:
    """A complete sample CV (produces no completeness warnings)."""
    data = dict(
        name="Jane Doe",
        city="Berlin",
        address="",
        email="jane@example.com",
        phone="+49 30 1234567",
        links=["https://github.com/janedoe"],
        languages=[
            ExtractedLanguage(name="German", level="native"),
            ExtractedLanguage(name="English", level="C1"),
        ],
        headline="Senior Backend Engineer | Python & Cloud",
        skills=[
            ExtractedSkill(name="Python", level="Fortgeschritten"),
            ExtractedSkill(name="Kubernetes", level="Grundlagen"),
            ExtractedSkill(name="python", level=""),
            ExtractedSkill(name="PostgreSQL", level=""),
        ],
        soft_skills=[],
        certifications=[
            ExtractedCertification(
                name="Certified Kubernetes Administrator",
                abbreviation="CKA",
                issuer="CNCF",
                year="2023",
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
                client="",
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
                client="Gamma Bank",
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
        earliest_start="",
        salary_expectation="",
        work_permit="",
    )
    data.update(overrides)
    return ExtractedCV(**data)


def demo_cv() -> ExtractedCV:
    """The sample CV with a few gaps, so the demo shows warnings and quick fixes."""
    cv = sample_cv(
        phone="",
        languages=[
            ExtractedLanguage(name="German", level="native"),
            ExtractedLanguage(name="English", level="fluent"),
        ],
    )
    cv.positions[1].location = ""
    return cv


def demo_listing() -> ExtractedListing:
    """A German hybrid backend role. Requirement checks are left empty ("not mentioned")."""
    return ExtractedListing(
        title="Senior Python Developer (m/w/d)",
        company="Beispiel Mobility GmbH",
        domain="automotive",
        responsibilities=[
            "Weiterentwicklung unserer Flottenmanagement-Plattform",
            "Design und Betrieb von Microservices auf Kubernetes",
        ],
        required_skills=["Python", "FastAPI", "PostgreSQL", "Kubernetes"],
        nice_to_have_skills=["Kafka", "Terraform"],
        qualifications=["5+ Jahre Erfahrung in der Backend-Entwicklung", "Sehr gutes Deutsch"],
        location="München",
        remote="hybrid",
        onsite_days_per_week=2,
        salary_min=70000,
        salary_max=85000,
        salary_currency="EUR",
        salary_period="year",
        benefits=["30 Urlaubstage", "Jobrad", "Weiterbildungsbudget"],
        cover_letter_requested=False,
        requirement_checks=[],
    )


def demo_response(step: str, output: type[BaseModel]) -> BaseModel:
    if step == "parse_cv" and output is ExtractedCV:
        return demo_cv()
    if step == "parse_listing" and output is ExtractedListing:
        return demo_listing()
    raise NotImplementedError(f"demo mode has no sample response for step '{step}'")
