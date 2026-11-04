"""Review step: Claude-facing models for the claims check and the recruiter review."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mappe.domain.author import AuthorCV, AuthorLetter
from mappe.domain.models import ParsedCV

# --- claims check ---------------------------------------------------------------------


class ClaimProblem(BaseModel):
    item: str = Field(description="The item label as given, e.g. 'B3', 'P2', 'S1'")
    kind: Literal["embellished", "unsupported", "misleading"]
    explanation: str = Field(description="What is wrong and what the facts actually say")


class ClaimsResult(BaseModel):
    problems: list[ClaimProblem]


def render_claims(
    cv: ParsedCV,
    doc: AuthorCV,
    letter: AuthorLetter | None,
    unverified_terms: list[str] | None = None,
) -> str:
    """Every claim with the full text of the facts it cites."""
    from mappe.checks.skills import skill_variants

    texts: dict[str, str] = {}
    techs: dict[str, str] = {}
    for p in cv.positions:
        client = f", client {p.client}" if p.client else ""
        texts[p.id] = f"Position: {p.role} at {p.company}{client}"
        techs[p.id] = ", ".join(p.technologies)
        for f in p.responsibilities + p.achievements:
            texts[f.id] = f.text
    for f in cv.projects + cv.publications + cv.volunteering:
        texts[f.id] = f.text

    def cited(ids: list[str]) -> str:
        lines = []
        for i in ids:
            lines.append(f"    [{i}] {texts.get(i, '(unknown)')}")
            if i in techs and techs[i]:
                lines.append(f"    [{i} technologies] {techs[i]}")
        return "\n".join(lines) or "    (no facts cited)"

    skills_list = ", ".join(
        f"{s.name} ({s.level or s.level_text or 'no level'})" for s in cv.skills
    )
    out = [
        "The CV's own skills section (also facts; skills named here are supported anywhere):",
        f"    {skills_list}",
    ]
    if unverified_terms:
        out += [
            "Listing requirements the CV doesn't show by name (a mention is unsupported unless "
            "the cited facts describe the same thing, possibly in other words or in German):",
            f"    {', '.join(unverified_terms)}",
        ]
    out += ["", f"P0 (profile): {doc.profile}", cited(doc.profile_fact_ids)]
    for n, b in enumerate(doc.bullets, 1):
        out += [f"B{n} ({b.position_id}): {b.text}", cited(b.fact_ids)]
    for n, b in enumerate(doc.extra, 1):
        out += [f"E{n}: {b.text}", cited(b.fact_ids)]

    listed: dict[str, str] = {}
    for s in cv.skills:
        for form in skill_variants(s.name):
            listed.setdefault(form, s.level or s.level_text or "no level stated")
    used_in: dict[str, list[str]] = {}
    for p in cv.positions:
        for t in p.technologies:
            for form in skill_variants(t):
                used_in.setdefault(form, []).append(f"{p.id} ({p.role})")
    for n, g in enumerate(doc.skill_groups, 1):
        details = []
        for s in g.skills:
            forms = skill_variants(s)
            level = next((listed[f] for f in forms if f in listed), None)
            where = sorted({w for f in forms for w in used_in.get(f, [])})
            in_list = (
                f"in the CV skills section, level {level}"
                if level
                else "not in the CV skills section"
            )
            details.append(f"{s} [{in_list}; technologies of: {', '.join(where) or '—'}]")
        out.append(f"S{n} (skills, {g.category}): " + "; ".join(details))
    if letter:
        out.append(f"L0 (cover letter subject): {letter.subject}")
        for n, p in enumerate(letter.paragraphs, 1):
            out += [f"L{n} (cover letter paragraph): {p.text}", cited(p.fact_ids)]
    return "\n".join(out)


# --- recruiter --------------------------------------------------------------------------

CRITERIA = ["relevance", "keywords", "evidence", "clarity", "seniority"]


class RecruiterResult(BaseModel):
    relevance: int = Field(
        description="1-5: the most relevant experience for this role comes first"
    )
    keywords: int = Field(
        description="1-5: the listing's requirements are visibly covered where true"
    )
    evidence: int = Field(description="1-5: bullets show concrete application and impact")
    clarity: int = Field(description="1-5: concise, readable, no clichés or repetition")
    seniority: int = Field(description="1-5: level and leadership signals fit the role")
    cover_letter: int = Field(description="1-5 for the cover letter; 0 if there is none")
    invite: bool = Field(description="Would you invite the candidate to a first interview?")
    summary: str = Field(description="2-3 sentences: your overall impression as a recruiter")
    feedback: list[str] = Field(
        description="Concrete changes to the documents, most important first. Only changes "
        "that are possible with facts from the CV. Empty if nothing important is left."
    )

    def average(self, has_letter: bool) -> float:
        scores = [getattr(self, c) for c in CRITERIA]
        if has_letter and self.cover_letter:
            scores.append(self.cover_letter)
        return round(sum(max(1, min(5, s)) for s in scores) / len(scores), 2)
