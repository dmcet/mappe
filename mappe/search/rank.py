"""Filter and rank job hits against a CV, in Python only (no Claude).

Score 0-100. Keywords only: skill overlap (60) + title fit (30) + freshness (10). With
semantic similarity from the local embedding model: skills (40) + title (20) + meaning (30)
+ freshness (10). Hits without a description (Bundesagentur) use the same weights with
their skills counted as average (0.4), and are marked as "title only".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from rapidfuzz import fuzz

from mappe.checks.completeness import parse_month
from mappe.checks.requirements import (
    check_requirements,
    failed_must_haves,
    normalize_place,
)
from mappe.checks.skills import SYNONYMS, normalize_skill, skill_variants
from mappe.domain.models import ParsedCV, Requirement
from mappe.search.models import JobHit
from mappe.search.places import abroad, open_to_germany
from mappe.search.queries import clean_title, suggest_titles, title_variants

LEVEL_WEIGHT = {"advanced": 1.0, "intermediate": 0.7, "basic": 0.4, None: 0.7}
TOP_SKILLS = 20  # the CV skills that count
FULL_SKILL_WEIGHT = 6.0  # matched weight that earns the whole skill share ...
FULL_SKILL_SHARE = 0.6  # ... or this share of the CV's total, for CVs with few skills
RECENT_YEARS = 3
UNKNOWN_SKILL_FIT = 0.4  # listings without a description: skills can't be checked
# Short or everyday words: matched only as written in the CV ("Go", not "go").
_CASE_SENSITIVE = {"go", "r", "c", "d", "rest", "swift", "spring", "flow", "compose", "dart"}
CHECKED_KINDS = {"salary_min", "max_onsite_days", "remote", "location"}


@dataclass
class CVSkill:
    name: str  # as in the CV
    weight: float
    pattern: re.Pattern[str]


@dataclass
class Ranked:
    hit: JobHit
    score: float
    matched_skills: list[str] = field(default_factory=list)
    title_fit: float = 0.0
    semantic_fit: float | None = None  # 0..1, None without the embedding model
    basis: str = "description"  # or "title only"
    hidden: str | None = None  # "dismissed" | "requirements" | "elsewhere" | "low_score"
    notes: list[str] = field(default_factory=list)  # failed must-haves

    def reasons(self) -> dict:
        data = asdict(self)
        data.pop("hit")
        return data


def _recent(cv: ParsedCV, name: str, today: date) -> bool:
    wanted = set(skill_variants(name))
    for p in cv.positions:
        if not any(wanted & set(skill_variants(t)) for t in p.technologies):
            continue
        end = parse_month(p.end) or today
        if (today - end).days <= RECENT_YEARS * 365:
            return True
    return False


def _pattern(name: str) -> re.Pattern[str]:
    forms = {name.strip()}
    for variant in skill_variants(name):
        forms.add(variant)
        # Synonym targets aren't singularised ("kubernetes"), CV variants are ("kubernete").
        forms.update(k for k, v in SYNONYMS.items() if variant in (v, normalize_skill(v)))
    alternatives = "|".join(sorted((re.escape(f) for f in forms if f), key=len, reverse=True))
    sensitive = normalize_skill(name) in _CASE_SENSITIVE or len(name.strip()) <= 2
    flags = 0 if sensitive else re.I
    body = rf"(?<![\w#+.])(?:{alternatives})(?:s|es)?(?![\w#+])"
    if sensitive:  # match the CV's spelling only
        body = rf"(?<![\w#+.]){re.escape(name.strip())}(?![\w#+])"
    return re.compile(body, flags)


def cv_skills(cv: ParsedCV, today: date | None = None) -> list[CVSkill]:
    """The CV's top skills, weighted by level and recent use; technologies fill up the list."""
    today = today or date.today()
    seen: set[str] = set()
    skills = []
    for s in cv.skills:
        key = normalize_skill(s.name)
        if key in seen:
            continue
        seen.add(key)
        recency = 1.0 if _recent(cv, s.name, today) else 0.8
        skills.append(CVSkill(s.name, LEVEL_WEIGHT[s.level] * recency, _pattern(s.name)))
    for p in cv.positions:
        for tech in p.technologies:
            key = normalize_skill(tech)
            if key not in seen:
                seen.add(key)
                weight = 0.6 if _recent(cv, tech, today) else 0.4
                skills.append(CVSkill(tech, weight, _pattern(tech)))
    skills.sort(key=lambda s: s.weight, reverse=True)
    return skills[:TOP_SKILLS]


def cv_titles(cv: ParsedCV) -> list[str]:
    return suggest_titles(cv)


def _title_key(title: str) -> str:
    return re.sub(r"[-/]", " ", clean_title(title)).casefold()


def title_fit(title: str, cv_titles: list[str]) -> float:
    key = _title_key(title)
    candidates = {_title_key(t) for t in cv_titles}
    candidates |= {_title_key(v) for t in cv_titles for v in title_variants(clean_title(t))}
    if not key or not candidates:
        return 0.0
    return (
        max(
            fuzz.token_sort_ratio(key, c) * 0.5 + fuzz.partial_ratio(key, c) * 0.5
            for c in candidates
        )
        / 100
    )


def _freshness(hit: JobHit, today: date, max_age_days: int) -> float:
    if hit.posted_at is None:
        return 0.5
    age = max(0, (today - hit.posted_at).days)
    return max(0.0, 1 - age / max(max_age_days, 1))


def _elsewhere(hit: JobHit, places: list[str]) -> bool:
    """An onsite or hybrid job outside the searched cities (or abroad, without cities), or a
    remote job tied to another country ("Zürich", not "Europe")."""
    if not hit.location:
        return False
    if hit.remote == "remote":
        return abroad(hit.location) and not open_to_germany(hit.location)
    where = normalize_place(hit.location)
    if re.search(r"\b(remote|homeoffice|home office)\b", where):
        return False
    if places:
        return not any(re.search(rf"\b{re.escape(normalize_place(p))}\b", where) for p in places)
    return abroad(hit.location)


def rank(
    hits: list[JobHit],
    cv: ParsedCV,
    requirements: list[Requirement],
    *,
    max_age_days: int = 30,
    min_score: float = 30,
    dismissed: set[str] | None = None,
    places: list[str] | None = None,
    located: set[str] | None = None,
    semantic: dict[str, float] | None = None,
    titles: list[str] | None = None,
    today: date | None = None,
) -> list[Ranked]:
    """Rank ``hits``. ``places`` are the search's cities; sources in ``located`` already
    searched around them (Bundesagentur's radius), so only the others are checked.
    ``semantic`` maps hit keys to their semantic fit (0..1); hits without one are scored on
    keywords only. ``titles`` are the searched titles: they count for title fit next to the
    CV's own, so a role the user chose to search for isn't ranked down."""
    today = today or date.today()
    skills = cv_skills(cv, today)
    full = max(1.0, min(FULL_SKILL_WEIGHT, FULL_SKILL_SHARE * sum(s.weight for s in skills)))
    titles = list(dict.fromkeys(cv_titles(cv) + (titles or [])))
    checked = [r for r in requirements if r.kind in CHECKED_KINDS]
    dismissed = dismissed or set()
    ranked = []
    for hit in hits:
        if hit.posted_at and (today - hit.posted_at).days > max_age_days:
            continue
        text = " ".join([hit.title, hit.description, " ".join(hit.tags)])
        matched = [s for s in skills if s.pattern.search(text)]
        skill_fit = min(1.0, sum(s.weight for s in matched) / full)
        tfit = title_fit(hit.title, titles)
        fresh = _freshness(hit, today, max_age_days)
        meaning = (semantic or {}).get(hit.key)
        basis = "description" if hit.description else "title only"
        if not hit.description:
            # Skills unknown (no text): count them as average, not as missing, and use the
            # same weights, so an identical title doesn't outrank a listing that was read.
            skill_fit = max(skill_fit, UNKNOWN_SKILL_FIT)
        weights = (60, 30, 0, 10) if meaning is None else (40, 20, 30, 10)
        parts = (skill_fit, tfit, meaning or 0.0, fresh)
        score = sum(w * p for w, p in zip(weights, parts, strict=True))
        item = Ranked(
            hit,
            round(score, 1),
            [s.name for s in matched],
            round(tfit, 2),
            basis=basis,
            semantic_fit=None if meaning is None else round(meaning, 2),
        )

        failed = failed_must_haves(check_requirements(checked, hit.as_listing(), "", []))
        if hit.key in dismissed:
            item.hidden = "dismissed"
        elif failed:
            item.hidden = "requirements"
            item.notes = [f"{r.requirement.kind}: {r.note}" for r in failed]
        # Radius searches (Bundesagentur) found their hits around the cities themselves;
        # without cities, every source is checked for jobs abroad.
        elif (not places or hit.source not in (located or set())) and _elsewhere(hit, places or []):
            item.hidden = "elsewhere"
        elif item.score < min_score:
            item.hidden = "low_score"
        ranked.append(item)
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked
