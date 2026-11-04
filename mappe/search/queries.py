"""Search queries from a parsed CV and the user's requirements."""

from __future__ import annotations

import re

from mappe.checks.skills import STUDENT_ROLES
from mappe.domain.models import ParsedCV, Requirement
from mappe.domain.roles import SuggestedRole

MAX_TITLES = 8
MAX_ROLES = 6

_GENDER = re.compile(r"\(\s*[mwfdxi](?:\s*[/|,]\s*[mwfdxi]+)+\s*\)|\b[mwf]/[mwf]/[dx]\b", re.I)
_SENIORITY = re.compile(
    r"\b(senior|junior|sr\.?|jr\.?|principal|head of|staff|expert|mid[- ]level)\b"
    r"|^\s*lead\b(?=\s+\w)",  # "Lead Developer", but keep "Tech Lead"
    re.I,
)
# "<field> Engineer/Developer" -> "<field>-Entwickler" only for these fields: a "System
# Engineer" is a "Systemingenieur", not a developer.
_DEV_FIELDS = {
    "rust",
    "swift",
    "flutter",
    "scala",
    "ruby",
    "angular",
    "vue",
    "node.js",
    "backend",
    "frontend",
    "fullstack",
    "full stack",
    "android",
    "ios",
    "mobile",
    "app",
    "web",
    "java",
    "kotlin",
    "python",
    "go",
    "golang",
    ".net",
    "c#",
    "c++",
    "php",
    "javascript",
    "typescript",
    "react",
    "embedded",
    "game",
    "unity",
    "salesforce",
    "sap",
}
_EN_FOR_DE = {
    "entwickler": "Developer",
    "entwicklerin": "Developer",
}
# Titles with an established form in the other language; [] = none (keep the original).
_WHOLE = {
    "software engineer": ["Softwareentwickler"],
    "software developer": ["Softwareentwickler"],
    "softwareentwickler": ["Software Engineer", "Software Developer"],
    "softwareentwicklerin": ["Software Engineer"],
    "softwarearchitekt": ["Software Architect"],
    "software architect": ["Softwarearchitekt"],
    "fullstack developer": ["Fullstack-Entwickler"],
    "full stack developer": ["Fullstack-Entwickler"],
    "system engineer": ["Systemingenieur"],
    "systems engineer": ["Systemingenieur"],
    "systemingenieur": ["System Engineer"],
    "solution architect": ["Lösungsarchitekt"],
    "solutions architect": ["Lösungsarchitekt"],
    "lösungsarchitekt": ["Solution Architect"],
    "it architect": ["IT-Architekt"],
    "it-architekt": ["IT Architect"],
    "cloud architect": ["Cloud-Architekt"],
    "cloud-architekt": ["Cloud Architect"],
    "it consultant": ["IT-Berater"],
    "it-berater": ["IT Consultant"],
    "technical architect": [],
}
# A headline segment counts as a job title only if it ends with one of these.
_ROLE_NOUN = re.compile(
    r"(engineer|developer|architect|consultant|manager|lead|administrator|scientist|analyst|"
    r"designer|tester|owner|master|cto|entwickler(in)?|ingenieur(in)?|architekt(in)?|"
    r"berater(in)?|leiter(in)?)$",
    re.I,
)


def clean_title(title: str) -> str:
    """'Senior Backend Engineer (m/w/d)' -> 'Backend Engineer'."""
    title = _GENDER.sub(" ", title)
    title = re.split(r"\s+(?:@|at|bei)\s+|[|·•]", title)[0]
    title = _SENIORITY.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip(" -,/")
    return title


def title_variants(title: str) -> list[str]:
    """The other language's form: 'Backend Developer' <-> 'Backend-Entwickler'."""
    key = title.casefold()
    if key in _WHOLE:
        return list(_WHOLE[key])
    words = title.replace("-", " ").split()
    if len(words) < 2:
        for de, en in _EN_FOR_DE.items():  # "Androidentwickler"
            if key.endswith(de) and len(key) > len(de):
                return [f"{title[: -len(de)].rstrip('-').capitalize()} {en}"]
        return []
    field, role = " ".join(words[:-1]), words[-1].casefold()
    if role in ("engineer", "developer") and field.casefold() in _DEV_FIELDS:
        return [f"{field}-Entwickler"]
    if role in _EN_FOR_DE:
        return [f"{field} {_EN_FOR_DE[role]}"]
    return []


def headline_titles(headline: str | None) -> list[str]:
    """'Software Architect | System Engineer | Python & Cloud' -> the two job titles."""
    segments = re.split(r"\s*[|·•/]\s*|\s+-\s+", headline or "")
    return [seg for seg in segments if _ROLE_NOUN.search(clean_title(seg))]


def suggest_titles(cv: ParsedCV) -> list[str]:
    """Headline titles and the two most recent roles (no student jobs), plus DE/EN variants."""
    raw = headline_titles(cv.headline)
    recent = sorted(cv.positions, key=lambda p: (p.end is None, p.end or "", p.start), reverse=True)
    raw += [p.role for p in recent if not STUDENT_ROLES.search(p.role)][:2]

    titles: list[str] = []
    seen: set[str] = set()

    def add(title: str) -> None:
        if title and title.casefold() not in seen and len(titles) < MAX_TITLES:
            seen.add(title.casefold())
            titles.append(title)

    cleaned = [clean_title(t) for t in raw]
    skill_title = _skill_title(cv)
    if skill_title and not any(skill_title.split()[0].casefold() in t.casefold() for t in cleaned):
        cleaned.append(skill_title)
    for title in cleaned:
        add(title)
    for title in cleaned:
        for variant in title_variants(title):
            add(variant)
    return titles


# Skills that make a common job title ("Kotlin Developer", "Android-Entwickler").
_TITLE_SKILLS = {
    "kotlin",
    "java",
    "android",
    "ios",
    "swift",
    "python",
    "go",
    "golang",
    "rust",
    "c#",
    ".net",
    "c++",
    "php",
    "javascript",
    "typescript",
    "react",
    "angular",
    "vue",
    "node.js",
    "ruby",
    "scala",
    "flutter",
    "salesforce",
    "sap",
    "embedded",
}


def _skill_title(cv: ParsedCV) -> str | None:
    """'<skill> Developer' for the CV's first advanced skill that names a job (else first)."""
    candidates = [s for s in cv.skills if s.name.casefold() in _TITLE_SKILLS]
    best = next((s for s in candidates if s.level == "advanced"), None) or next(
        iter(candidates), None
    )
    return f"{best.name} Developer" if best else None


def fact_ids(cv: ParsedCV) -> set[str]:
    ids = set()
    for p in cv.positions:
        ids.add(p.id)
        ids |= {f.id for f in p.responsibilities + p.achievements}
    ids |= {e.id for e in cv.education} | {c.id for c in cv.certifications}
    ids |= {f.id for f in cv.projects + cv.publications + cv.volunteering}
    return ids


def _tidy(title: str) -> str:
    """Strip gender suffixes and stray punctuation, but keep "Lead" and the like."""
    return re.sub(r"\s+", " ", _GENDER.sub(" ", title)).strip(" -,/")


def filter_roles(cv: ParsedCV, roles: list[SuggestedRole]) -> list[dict]:
    """Keep suggestions that rest on real CV facts and add something new.

    Dropped: unknown fact IDs (and suggestions left without any), titles the CV already
    suggests on its own, duplicates. Alternative titles that repeat a known one are blanked.
    """
    known = fact_ids(cv)
    taken = {clean_title(t).casefold() for t in suggest_titles(cv)}
    kept: list[dict] = []
    for role in roles:
        title, alt = _tidy(role.title), _tidy(role.title_alt)
        ids = [i for i in dict.fromkeys(role.fact_ids) if i in known]
        key = clean_title(title).casefold()
        if not title or not ids or key in taken:
            continue
        taken.add(key)
        if alt and clean_title(alt).casefold() in taken:
            alt = ""
        elif alt:
            taken.add(clean_title(alt).casefold())
        kept.append(
            {"title": title, "title_alt": alt, "reason": role.reason.strip(), "fact_ids": ids}
        )
        if len(kept) == MAX_ROLES:
            break
    return kept


def places_from(requirements: list[Requirement]) -> list[str]:
    places = []
    for req in requirements:
        if req.kind == "location":
            places += [c.strip() for c in req.value.split(",") if c.strip()]
    return list(dict.fromkeys(places))


def remote_only(requirements: list[Requirement]) -> bool:
    """Only when fully remote is a must-have; otherwise onsite jobs are filtered later."""
    return any(
        r.kind == "max_onsite_days" and r.must_have and r.value.strip() == "0" for r in requirements
    )
