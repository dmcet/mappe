"""Deterministic skill analysis: listing skills vs. CV, years of experience.

Everything here is computed in Python and handed to the matcher as ground truth, so
Claude only judges what can't be computed (transferable skills, overall fit).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from rapidfuzz import fuzz

from application_crew.domain.models import ParsedCV, ParsedListing, Position
from application_crew.domain.summary import merged_months

# Alternative spellings -> canonical form (after normalisation).
SYNONYMS = {
    "k8s": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "postgres": "postgresql",
    "kotlin coroutine": "coroutine",
    "kotlin flow": "flow",
    "junit": "unit test",
    "unit testing": "unit test",
    "unittest": "unit test",
    "rest api": "rest",
    "rest json": "rest",
    "restful": "rest",
    "ci cd": "ci/cd",
    "cicd": "ci/cd",
    "compose": "jetpack compose",
    "dagger 2": "dagger",
    "gcp": "google cloud",
    "amazon web services": "aws",
}

Coverage = Literal["match", "related", "missing"]
STUDENT_ROLES = re.compile(
    r"werkstudent|studentisch|student|praktik|intern\b|internship|hilfskraft|trainee|azubi",
    re.I,
)
YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|jahre?n?)\b", re.I)


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


def normalize_skill(name: str) -> str:
    text = name.casefold().strip()
    text = re.sub(r"[()]", " ", text)
    text = re.sub(r"[-_/,.]+(?=\s|$)|\s[-_/,.]+", " ", text)  # separators, keep "c#", "ci/cd"
    text = text.replace("-", " ").replace("_", " ")
    text = " ".join(_singular(w) for w in text.split())
    text = text.replace("ci cd", "ci/cd")
    return SYNONYMS.get(text, text)


def _tokens(text: str) -> set[str]:
    return set(text.split())


@dataclass
class SkillCoverage:
    skill: str  # as named in the listing
    required: bool
    coverage: Coverage
    cv_skill: str | None = None  # best CV match, as named in the CV
    level: str | None = None
    years: float = 0.0  # years in positions that used it (working-student roles count fully)
    student_years: float = 0.0  # share of ``years`` from working-student / intern roles
    positions: list[str] = field(default_factory=list)  # position IDs
    note: str = ""


@dataclass
class SkillAnalysis:
    coverage: list[SkillCoverage]
    total_years: float
    student_years: float  # share of total_years from working-student / intern roles
    years_required: int | None  # highest "N+ years" found in the listing
    required_matched: int
    required_related: int
    required_total: int
    nice_matched: int
    nice_total: int

    def to_dict(self) -> dict:
        return asdict(self)


def skill_variants(name: str) -> list[str]:
    """Normalised forms of a CV skill name; "Protocol Buffers/gRPC" yields both parts too."""
    variants = [normalize_skill(name)]
    if "/" in name and normalize_skill(name) != "ci/cd":
        variants += [normalize_skill(part) for part in name.split("/") if part.strip()]
    return variants


def _cv_skill_names(cv: ParsedCV) -> dict[str, tuple[str, str | None]]:
    """Normalised name -> (name as in CV, level). Skills list first, then technologies."""
    names: dict[str, tuple[str, str | None]] = {}
    for s in cv.skills:
        for variant in skill_variants(s.name):
            names.setdefault(variant, (s.name, s.level))
    for p in cv.positions:
        for tech in p.technologies:
            for variant in skill_variants(tech):
                names.setdefault(variant, (tech, None))
    return names


def _compare(listing_norm: str, cv_norm: str) -> Coverage | None:
    if listing_norm == cv_norm:
        return "match"
    if fuzz.ratio(listing_norm, cv_norm) >= 92 and min(len(listing_norm), len(cv_norm)) > 3:
        return "match"
    lt, ct = _tokens(listing_norm), _tokens(cv_norm)
    if lt and ct and (lt <= ct or ct <= lt):
        return "related"  # e.g. "Android animations" vs "Android"
    return None


def _position_uses(position: Position, skill_raw: str) -> bool:
    """The position lists the skill as a technology or names it in a bullet."""
    wanted = set(skill_variants(skill_raw))
    if any(wanted & set(skill_variants(t)) for t in position.technologies):
        return True
    texts = [f.text.casefold() for f in position.responsibilities + position.achievements]
    for part in [skill_raw, *skill_raw.split("/")]:
        part = part.strip().casefold()
        if len(part) < 2:
            continue
        pattern = rf"(?<![\w#+]){re.escape(part)}(?![\w#+])"
        if any(re.search(pattern, t) for t in texts):
            return True
    return False


def _mentions(position: Position, skill: str) -> bool:
    """The listing skill (or its canonical synonym) is named in one of the position's bullets."""
    wanted = normalize_skill(skill)
    for fact in position.responsibilities + position.achievements:
        text = f" {normalize_skill(fact.text)} "
        if f" {wanted} " in text or re.search(
            rf"(?<![\w#+]){re.escape(skill.casefold())}(?![\w#+])", fact.text.casefold()
        ):
            return True
    return False


def _is_student(position: Position) -> bool:
    return bool(STUDENT_ROLES.search(position.role))


def _cover(
    cv: ParsedCV,
    cv_names: dict[str, tuple[str, str | None]],
    skill: str,
    required: bool,
    today: date,
) -> SkillCoverage:
    norm = normalize_skill(skill)
    best: tuple[Coverage, str, str | None] | None = None
    for cv_norm, (cv_name, level) in cv_names.items():
        result = _compare(norm, cv_norm)
        if result == "match":
            best = ("match", cv_name, level)
            break
        if result == "related" and best is None:
            best = ("related", cv_name, level)

    if best is not None:
        kind, cv_name, level = best
        used = [p for p in cv.positions if _position_uses(p, cv_name)]
        note = ""
    else:
        # Not a named skill, but maybe described in the experience ("Unit-Tests" for JUnit).
        used = [p for p in cv.positions if _mentions(p, skill)]
        if not used:
            return SkillCoverage(skill=skill, required=required, coverage="missing")
        kind, cv_name, level, note = "related", None, None, "mentioned in experience"

    student = [p for p in used if _is_student(p)]
    return SkillCoverage(
        skill=skill,
        required=required,
        coverage=kind,
        cv_skill=cv_name,
        level=level,
        years=_years(used, today),
        student_years=_years(student, today),
        positions=[p.id for p in used],
        note=note,
    )


def _years(positions: list[Position], today: date) -> float:
    return round(merged_months(positions, today) / 12, 1)


def analyze_skills(
    cv: ParsedCV, listing: ParsedListing, today: date | None = None
) -> SkillAnalysis:
    today = today or date.today()
    cv_names = _cv_skill_names(cv)
    coverage = []
    for skill, required in [(s, True) for s in listing.required_skills] + [
        (s, False) for s in listing.nice_to_have_skills
    ]:
        coverage.append(_cover(cv, cv_names, skill, required, today))

    student = [p for p in cv.positions if _is_student(p)]
    texts = listing.qualifications + listing.responsibilities
    years_required = max((int(m) for t in texts for m in YEARS_RE.findall(t)), default=None)
    req = [c for c in coverage if c.required]
    nice = [c for c in coverage if not c.required]
    return SkillAnalysis(
        coverage=coverage,
        total_years=_years(cv.positions, today),
        student_years=_years(student, today),
        years_required=years_required,
        required_matched=sum(c.coverage == "match" for c in req),
        required_related=sum(c.coverage == "related" for c in req),
        required_total=len(req),
        nice_matched=sum(c.coverage == "match" for c in nice),
        nice_total=len(nice),
    )
