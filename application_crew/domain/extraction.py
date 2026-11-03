"""Claude-facing extraction model for CVs, and conversion to the internal ParsedCV.

Claude only extracts; Python assigns stable fact IDs, so IDs are deterministic and
never depend on the model. Nesting is kept to two levels (CV -> position -> strings).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from application_crew.domain.models import (
    Certification,
    Contact,
    Education,
    Fact,
    Language,
    ParsedCV,
    Position,
)


class ExtractedLanguage(BaseModel):
    name: str
    level: str | None = Field(description="CEFR level A1-C2 or 'native', as stated; else null")


class ExtractedCertification(BaseModel):
    name: str
    abbreviation: str | None
    issuer: str | None
    year: int | None


class ExtractedEducation(BaseModel):
    qualification: str
    institution: str
    location: str | None
    start: str | None = Field(description="YYYY-MM or YYYY")
    end: str | None = Field(description="YYYY-MM or YYYY; null if ongoing or not stated")


class ExtractedPosition(BaseModel):
    company: str
    role: str
    location: str | None
    start: str | None = Field(description="YYYY-MM or YYYY")
    end: str | None = Field(description="YYYY-MM or YYYY; null if this is the current position")
    is_current: bool
    responsibilities: list[str]
    achievements: list[str]
    technologies: list[str]


class ExtractedCV(BaseModel):
    name: str
    city: str | None
    address: str | None
    email: str | None
    phone: str | None
    links: list[str]
    languages: list[ExtractedLanguage]
    skills: list[str]
    soft_skills: list[str]
    certifications: list[ExtractedCertification]
    education: list[ExtractedEducation]
    positions: list[ExtractedPosition]
    projects: list[str]
    publications: list[str]
    volunteering: list[str]
    notice_period: str | None
    earliest_start: str | None
    salary_expectation: str | None
    work_permit: str | None


def _facts(prefix: str, texts: list[str]) -> list[Fact]:
    return [Fact(id=f"{prefix}{i}", text=t.strip()) for i, t in enumerate(texts, 1) if t.strip()]


def to_parsed_cv(extracted: ExtractedCV) -> ParsedCV:
    """Convert Claude's extraction into the internal model and assign fact IDs.

    ID scheme: ``pos{n}``, ``pos{n}.resp{m}``, ``pos{n}.ach{m}``, ``edu{n}``, ``cert{n}``,
    ``proj{n}``, ``pub{n}``, ``vol{n}``. Positions keep the order of the source CV.
    """
    positions = []
    for n, p in enumerate(extracted.positions, 1):
        pid = f"pos{n}"
        positions.append(
            Position(
                id=pid,
                company=p.company,
                role=p.role,
                location=p.location,
                start=p.start or "",
                end=None if p.is_current else p.end,
                responsibilities=_facts(f"{pid}.resp", p.responsibilities),
                achievements=_facts(f"{pid}.ach", p.achievements),
                technologies=_dedupe(p.technologies),
            )
        )

    return ParsedCV(
        contact=Contact(
            name=extracted.name,
            city=extracted.city,
            address=extracted.address,
            email=extracted.email,
            phone=extracted.phone,
            links=extracted.links,
        ),
        languages=[
            Language(name=lang.name, level=lang.level or "") for lang in extracted.languages
        ],
        skills=_dedupe(extracted.skills),
        soft_skills=_dedupe(extracted.soft_skills),
        certifications=[
            Certification(id=f"cert{n}", **c.model_dump())
            for n, c in enumerate(extracted.certifications, 1)
        ],
        education=[
            Education(id=f"edu{n}", **e.model_dump()) for n, e in enumerate(extracted.education, 1)
        ],
        positions=positions,
        projects=_facts("proj", extracted.projects),
        publications=_facts("pub", extracted.publications),
        volunteering=_facts("vol", extracted.volunteering),
        notice_period=extracted.notice_period,
        earliest_start=extracted.earliest_start,
        salary_expectation=extracted.salary_expectation,
        work_permit=extracted.work_permit,
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = item.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out
