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
    Skill,
    SkillLevel,
)

# Claude-facing models have no optional fields: every union in the schema enlarges the
# compiled output grammar, and the API rejects grammars that are too large. "Not stated"
# is an empty string; Python converts it to None.
NOT_STATED = "Empty string if not stated."


class ExtractedLanguage(BaseModel):
    name: str
    level: str = Field(description=f"CEFR level A1-C2 or 'native', as stated. {NOT_STATED}")


class ExtractedSkill(BaseModel):
    name: str
    level: str = Field(
        description="Proficiency exactly as the CV states it for this skill "
        f"(e.g. 'Fortgeschritten', 'Grundlagen'). {NOT_STATED}"
    )


class ExtractedCertification(BaseModel):
    name: str
    abbreviation: str
    issuer: str
    year: str = Field(description=f"YYYY. {NOT_STATED}")


class ExtractedEducation(BaseModel):
    qualification: str
    institution: str
    location: str
    start: str = Field(description=f"YYYY-MM or YYYY. {NOT_STATED}")
    end: str = Field(description=f"YYYY-MM or YYYY. {NOT_STATED}")


class ExtractedPosition(BaseModel):
    company: str = Field(description="The employer")
    client: str = Field(
        description=f"For consulting/contracting assignments: the client company. {NOT_STATED}"
    )
    role: str
    location: str
    start: str = Field(description=f"YYYY-MM or YYYY. {NOT_STATED}")
    end: str = Field(description="YYYY-MM or YYYY. Empty string for the current position.")
    is_current: bool
    responsibilities: list[str]
    achievements: list[str]
    technologies: list[str]


class ExtractedCV(BaseModel):
    """Every string field: empty string if not stated."""

    name: str
    headline: str = Field(description=f"The CV's own title or tagline line, verbatim. {NOT_STATED}")
    city: str
    address: str
    email: str
    phone: str
    links: list[str]
    languages: list[ExtractedLanguage]
    skills: list[ExtractedSkill]
    soft_skills: list[str]
    certifications: list[ExtractedCertification]
    education: list[ExtractedEducation]
    positions: list[ExtractedPosition]
    projects: list[str]
    publications: list[str]
    volunteering: list[str]
    notice_period: str
    earliest_start: str
    salary_expectation: str
    work_permit: str


def opt(value: str) -> str | None:
    """Empty string (Claude's "not stated") -> None."""
    value = value.strip()
    return value or None


# Proficiency wording (German and English) -> normalised level. Anything else stays None,
# with the original wording kept in level_text.
_LEVELS: dict[str, SkillLevel] = {
    **dict.fromkeys(
        [
            "fortgeschritten",
            "sehr gut",
            "sehr gute kenntnisse",
            "experte",
            "expert",
            "advanced",
            "proficient",
            "verhandlungssicher",
        ],
        "advanced",
    ),
    **dict.fromkeys(
        ["mittel", "gut", "gute kenntnisse", "solide", "intermediate", "good"], "intermediate"
    ),
    **dict.fromkeys(
        [
            "grundlagen",
            "grundkenntnisse",
            "basis",
            "basic",
            "basics",
            "beginner",
            "anfänger",
            "erste erfahrungen",
        ],
        "basic",
    ),
}


def normalize_level(text: str) -> SkillLevel | None:
    return _LEVELS.get(text.strip().rstrip(":").casefold())


def _skills(extracted: list[ExtractedSkill]) -> list[Skill]:
    """Deduplicate by name (case-insensitive); keep the first stated level."""
    out: dict[str, Skill] = {}
    for item in extracted:
        name = item.name.strip()
        if not name:
            continue
        key = name.casefold()
        level_text = opt(item.level)
        if key not in out:
            out[key] = Skill(
                name=name, level=normalize_level(level_text or ""), level_text=level_text
            )
        elif out[key].level_text is None and level_text:
            out[key] = out[key].model_copy(
                update={"level": normalize_level(level_text), "level_text": level_text}
            )
    return list(out.values())


def _year(value: str) -> int | None:
    digits = value.strip()[:4]
    return int(digits) if digits.isdigit() else None


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
                company=p.company.strip(),
                client=opt(p.client),
                role=p.role,
                location=opt(p.location),
                start=p.start.strip(),
                end=None if p.is_current else opt(p.end),
                responsibilities=_facts(f"{pid}.resp", p.responsibilities),
                achievements=_facts(f"{pid}.ach", p.achievements),
                technologies=_dedupe(p.technologies),
            )
        )

    return ParsedCV(
        contact=Contact(
            name=extracted.name.strip(),
            city=opt(extracted.city),
            address=opt(extracted.address),
            email=opt(extracted.email),
            phone=opt(extracted.phone),
            links=[link.strip() for link in extracted.links if link.strip()],
        ),
        languages=[
            Language(name=lang.name.strip(), level=lang.level.strip())
            for lang in extracted.languages
        ],
        headline=opt(extracted.headline),
        skills=_skills(extracted.skills),
        soft_skills=_dedupe(extracted.soft_skills),
        certifications=[
            Certification(
                id=f"cert{n}",
                name=c.name.strip(),
                abbreviation=opt(c.abbreviation),
                issuer=opt(c.issuer),
                year=_year(c.year),
            )
            for n, c in enumerate(extracted.certifications, 1)
        ],
        education=[
            Education(
                id=f"edu{n}",
                qualification=e.qualification.strip(),
                institution=e.institution.strip(),
                location=opt(e.location),
                start=opt(e.start),
                end=opt(e.end),
            )
            for n, e in enumerate(extracted.education, 1)
        ],
        positions=positions,
        projects=_facts("proj", extracted.projects),
        publications=_facts("pub", extracted.publications),
        volunteering=_facts("vol", extracted.volunteering),
        notice_period=opt(extracted.notice_period),
        earliest_start=opt(extracted.earliest_start),
        salary_expectation=opt(extracted.salary_expectation),
        work_permit=opt(extracted.work_permit),
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
