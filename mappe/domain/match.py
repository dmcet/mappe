"""Matcher: Claude-facing output model, prompt context rendering, fact-ID validation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mappe.checks.skills import SkillAnalysis
from mappe.domain.models import ParsedCV, ParsedListing, RequirementResult

Verdict = Literal["apply", "consider", "dont_apply"]


class Evidence(BaseModel):
    """A statement about the candidate, backed by CV fact IDs."""

    point: str
    fact_ids: list[str] = Field(description="IDs of the CV facts this point is based on")


class TransferableSkill(BaseModel):
    missing: str = Field(description="Skill from the listing the candidate doesn't have")
    related_experience: str = Field(description="Experience from the CV that makes it learnable")
    fact_ids: list[str]


class MatchResult(BaseModel):
    """Claude-facing (no optional fields, see extraction.py)."""

    verdict: Verdict
    score: int = Field(description="Overall fit from 0 to 100")
    rationale: str = Field(description="3-5 sentences addressed to the candidate")
    strengths: list[Evidence]
    gaps: list[str] = Field(description="Requirements the CV doesn't cover, most important first")
    transferable: list[TransferableSkill]
    highlights: list[Evidence] = Field(
        description="What the tailored CV should emphasise for this position, most important first"
    )


# --- context rendering --------------------------------------------------------------------


def render_cv(cv: ParsedCV) -> str:
    """Compact text form of the CV with fact IDs (fewer tokens than JSON)."""
    lines = [f"Name: {cv.contact.name}"]
    if cv.headline:
        lines.append(f"Headline: {cv.headline}")
    lines.append("")
    lines.append("Positions:")
    for p in cv.positions:
        client = f" (client: {p.client})" if p.client else ""
        where = f" | {p.location}" if p.location else ""
        lines.append(
            f"[{p.id}] {p.role} | {p.company}{client}{where} | {p.start}–{p.end or 'present'}"
        )
        for f in p.responsibilities:
            lines.append(f"  [{f.id}] {f.text}")
        for f in p.achievements:
            lines.append(f"  [{f.id}] (achievement) {f.text}")
        if p.technologies:
            lines.append(f"  technologies: {', '.join(p.technologies)}")
    lines.append("")
    lines.append("Skills by stated level:")
    for level in ("advanced", "intermediate", "basic", None):
        names = [s.name for s in cv.skills if s.level == level]
        if names:
            lines.append(f"  {level or 'no level stated'}: {', '.join(names)}")
    if cv.soft_skills:
        lines.append(f"  soft skills: {', '.join(cv.soft_skills)}")
    lines.append("")
    lines.append("Languages: " + ", ".join(f"{lang.name} ({lang.level})" for lang in cv.languages))
    for e in cv.education:
        lines.append(f"[{e.id}] Education: {e.qualification}, {e.institution} ({e.start}–{e.end})")
    for c in cv.certifications:
        lines.append(f"[{c.id}] Certification: {c.name}, {c.issuer or '?'} ({c.year or '?'})")
    for f in cv.projects + cv.publications + cv.volunteering:
        lines.append(f"[{f.id}] {f.text}")
    return "\n".join(lines)


def render_listing(listing: ParsedListing) -> str:
    def block(title: str, items: list[str]) -> list[str]:
        return [f"{title}:"] + [f"  - {i}" for i in items] if items else []

    work = listing.remote or "not stated"
    if listing.onsite_days_per_week:
        work += f", {listing.onsite_days_per_week} onsite day(s)/week"
    lines = [
        f"Title: {listing.title or '?'}",
        f"Company: {listing.company or '?'}" + (f" ({listing.domain})" if listing.domain else ""),
        f"Location: {listing.location or '?'} | Work mode: {work}",
        *block("Responsibilities", listing.responsibilities),
        *block("Required skills", listing.required_skills),
        *block("Nice-to-have skills", listing.nice_to_have_skills),
        *block("Qualifications", listing.qualifications),
    ]
    return "\n".join(lines)


def render_analysis(analysis: SkillAnalysis, results: list[RequirementResult]) -> str:
    years_req = f"{analysis.years_required}+ years" if analysis.years_required else "not stated"
    lines = [
        f"Experience: {analysis.total_years} years, including {analysis.student_years} years "
        f"in working-student/intern roles (these count as full experience). "
        f"Listing asks for: {years_req}.",
        f"Required skills: {analysis.required_matched} matched, {analysis.required_related} "
        f"related, of {analysis.required_total}. Nice-to-have: {analysis.nice_matched} of "
        f"{analysis.nice_total} matched.",
        "",
        "Skill coverage (computed from the CV; years = years in positions using it):",
    ]
    for c in analysis.coverage:
        kind = "required" if c.required else "nice-to-have"
        if c.coverage == "missing":
            lines.append(f"  - {c.skill} ({kind}): missing")
            continue
        via = f" via '{c.cv_skill}'" if c.cv_skill and c.cv_skill != c.skill else ""
        level = f", level {c.level}" if c.level else ""
        student = f" (of which {c.student_years}y as working student)" if c.student_years else ""
        where = f" in {', '.join(c.positions)}" if c.positions else ", not linked to a position"
        note = f" ({c.note})" if c.note else ""
        lines.append(
            f"  - {c.skill} ({kind}): {c.coverage}{via}{level}, {c.years}y{student}{where}{note}"
        )
    if results:
        lines += ["", "Candidate's own requirements (already checked):"]
        for r in results:
            must = "must-have" if r.requirement.must_have else "nice-to-have"
            lines.append(f"  - {r.requirement.value} ({must}): {r.outcome} — {r.note}")
    return "\n".join(lines)


# --- validation ---------------------------------------------------------------------------


def fact_ids(cv: ParsedCV) -> set[str]:
    ids = set()
    for p in cv.positions:
        ids.add(p.id)
        ids.update(f.id for f in p.responsibilities + p.achievements)
    ids.update(e.id for e in cv.education)
    ids.update(c.id for c in cv.certifications)
    ids.update(f.id for f in cv.projects + cv.publications + cv.volunteering)
    return ids


def validate_fact_ids(result: MatchResult, cv: ParsedCV) -> tuple[MatchResult, list[str]]:
    """Drop unknown fact IDs; drop strengths/highlights left without any valid ID.

    Returns the cleaned result and a list of human-readable warnings.
    """
    known = fact_ids(cv)
    warnings: list[str] = []

    def clean(items: list, label: str) -> list:
        kept = []
        for item in items:
            text = getattr(item, "point", None) or getattr(item, "missing", "")
            valid = [i for i in item.fact_ids if i in known]
            unknown = [i for i in item.fact_ids if i not in known]
            if not valid:
                warnings.append(f"{label} '{text[:60]}' dropped: not backed by any CV fact")
                continue
            if unknown:
                warnings.append(f"{label} '{text[:60]}': unknown fact IDs {unknown} removed")
            kept.append(item.model_copy(update={"fact_ids": valid}))
        return kept

    cleaned = result.model_copy(
        update={
            "strengths": clean(result.strengths, "Strength"),
            "highlights": clean(result.highlights, "Highlight"),
            "transferable": clean(result.transferable, "Transferable skill"),
            "score": max(0, min(100, result.score)),
        }
    )
    return cleaned, warnings
