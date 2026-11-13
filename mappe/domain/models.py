"""Domain models exchanged between pipeline steps (and with Claude).

Keep these flat: lists of strings, at most two levels of nesting. Every CV fact
gets a stable ID (e.g. ``pos2.ach3``) so author output can be traced back to it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Fact(BaseModel):
    id: str
    text: str


class Language(BaseModel):
    name: str
    level: str  # CEFR A1-C2 or "native"


class Certification(BaseModel):
    id: str
    name: str
    abbreviation: str | None = None
    issuer: str | None = None
    year: int | None = None


class Education(BaseModel):
    id: str
    qualification: str
    institution: str
    location: str | None = None
    start: str | None = None  # "YYYY-MM"
    end: str | None = None


SkillLevel = Literal["advanced", "intermediate", "basic"]


class Skill(BaseModel):
    name: str
    level: SkillLevel | None = None  # normalised by Python from level_text
    level_text: str | None = None  # as written in the CV, e.g. "Fortgeschritten"

    @model_validator(mode="before")
    @classmethod
    def _from_plain_name(cls, value: Any) -> Any:
        # CVs parsed before skill levels existed stored skills as plain strings.
        return {"name": value} if isinstance(value, str) else value


class Position(BaseModel):
    id: str
    company: str  # the employer
    client: str | None = None  # client of a consulting assignment, if any
    role: str
    location: str | None = None
    start: str  # "YYYY-MM"
    end: str | None = None  # None = present
    responsibilities: list[Fact] = Field(default_factory=list)
    achievements: list[Fact] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Contact(BaseModel):
    name: str
    city: str | None = None
    address: str | None = None
    email: str | None = None
    phone: str | None = None
    links: list[str] = Field(default_factory=list)


class ParsedCV(BaseModel):
    contact: Contact
    headline: str | None = None  # the CV's own title line, e.g. "Software Architect | ..."
    languages: list[Language] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    positions: list[Position] = Field(default_factory=list)
    projects: list[Fact] = Field(default_factory=list)
    publications: list[Fact] = Field(default_factory=list)
    volunteering: list[Fact] = Field(default_factory=list)
    notice_period: str | None = None
    earliest_start: str | None = None
    salary_expectation: str | None = None
    work_permit: str | None = None


RemoteMode = Literal["remote", "hybrid", "onsite"]
SalaryPeriod = Literal["year", "month", "hour"]


class ParsedListing(BaseModel):
    title: str | None = None
    company: str | None = None
    domain: str | None = None
    language: str = "en"  # set by Python, not Claude
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)  # short names only
    nice_to_have_skills: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)  # experience, soft skills, ...
    location: str | None = None
    remote: RemoteMode | None = None
    onsite_days_per_week: int | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    benefits: list[str] = Field(default_factory=list)
    cover_letter_requested: bool = False
    # Application contact, verified against the listing text (domain/contact.py).
    contact_name: str | None = None
    contact_gender: Literal["female", "male"] | None = None
    contact_academic_title: str | None = None  # "Dr.", "Prof. Dr."
    contact_email: str | None = None
    # Employer's postal address, only if confirmed (domain/address.py): ["street", "PLZ city"].
    company_address: list[str] | None = None


RequirementKind = Literal["salary_min", "max_onsite_days", "remote", "location", "benefit", "other"]


class Requirement(BaseModel):
    """A user requirement checked against a listing.

    - ``salary_min``: minimum gross annual salary in EUR, e.g. "75000"
    - ``max_onsite_days``: maximum onsite days per week, "0" = fully remote
    - ``remote``: "no" = fully remote jobs are not wanted
    - ``location``: acceptable cities, comma-separated, each with an optional search radius,
      e.g. "Berlin (30 km), Hamburg"
    - ``benefit`` / ``other``: free text, judged by Claude against the listing
    """

    kind: RequirementKind
    value: str
    must_have: bool = False


class RequirementResult(BaseModel):
    requirement: Requirement
    outcome: Literal["passed", "failed", "unknown"]
    note: str = ""
    evidence: str | None = None  # quote from the listing (fuzzy checks only)


class Bullet(BaseModel):
    text: str
    source_ids: list[str]


class TailoredPosition(BaseModel):
    position_id: str  # employer, title, dates are taken from the source CV, not from Claude
    bullets: list[Bullet]


class CVContent(BaseModel):
    """Author output for the CV. Markup-free; rendered by Python."""

    profile: str | None = None
    positions: list[TailoredPosition]
    skills: list[str]
    certification_ids: list[str] = Field(default_factory=list)
    education_ids: list[str] = Field(default_factory=list)
    extra: list[Bullet] = Field(default_factory=list)  # projects, publications, volunteering


class CoverLetterContent(BaseModel):
    subject: str
    salutation: str
    paragraphs: list[str]
    closing: str
