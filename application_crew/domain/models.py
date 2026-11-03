"""Domain models exchanged between pipeline steps (and with Claude).

Keep these flat: lists of strings, at most two levels of nesting. Every CV fact
gets a stable ID (e.g. ``pos2.ach3``) so author output can be traced back to it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class Position(BaseModel):
    id: str
    company: str
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
    languages: list[Language] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
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


class ParsedListing(BaseModel):
    title: str | None = None
    company: str | None = None
    domain: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    location: str | None = None
    remote: Literal["remote", "hybrid", "onsite"] | None = None
    onsite_days_per_week: int | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    benefits: list[str] = Field(default_factory=list)
    cover_letter_requested: bool = False


class Requirement(BaseModel):
    """A user requirement checked against a listing."""

    kind: Literal["salary_min", "max_onsite_days", "remote", "location", "benefit", "other"]
    value: str
    must_have: bool = False


class RequirementResult(BaseModel):
    requirement: Requirement
    outcome: Literal["passed", "failed", "unknown"]
    note: str = ""


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
