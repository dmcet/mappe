"""Search queries from a parsed CV and the user's requirements."""

from __future__ import annotations

import re

from application_crew.checks.skills import STUDENT_ROLES
from application_crew.domain.models import ParsedCV, Requirement

MAX_TITLES = 6

_GENDER = re.compile(r"\(\s*[mwfdxi](?:\s*[/|,]\s*[mwfdxi]+)+\s*\)|\b[mwf]/[mwf]/[dx]\b", re.I)
_SENIORITY = re.compile(
    r"\b(senior|junior|sr\.?|jr\.?|principal|head of|staff|expert|mid[- ]level)\b"
    r"|^\s*lead\b(?=\s+\w)",  # "Lead Developer", but keep "Tech Lead"
    re.I,
)
# German <-> English role nouns (applied to the last word of a title).
_DE_FOR_EN = {
    "developer": "Entwickler",
    "engineer": "Entwickler",
    "architect": "Architekt",
    "consultant": "Berater",
    "manager": "Manager",
    "administrator": "Administrator",
}
_EN_FOR_DE = {
    "entwickler": "Developer",
    "entwicklerin": "Developer",
    "architekt": "Architect",
    "architektin": "Architect",
    "berater": "Consultant",
    "beraterin": "Consultant",
}
# Whole titles that don't follow the "<field> <role>" pattern.
_WHOLE = {
    "software engineer": ["Softwareentwickler"],
    "software developer": ["Softwareentwickler"],
    "softwareentwickler": ["Software Engineer", "Software Developer"],
    "softwareentwicklerin": ["Software Engineer"],
    "softwarearchitekt": ["Software Architect"],
    "software architect": ["Softwarearchitekt"],
    "fullstack developer": ["Fullstack-Entwickler"],
    "full stack developer": ["Fullstack-Entwickler"],
}


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
        if key.endswith(tuple(_EN_FOR_DE)):  # "Androidentwickler"
            for de, en in _EN_FOR_DE.items():
                if key.endswith(de) and len(key) > len(de):
                    return [f"{title[: -len(de)].rstrip('-').capitalize()} {en}"]
        return []
    field, role = " ".join(words[:-1]), words[-1].casefold()
    if role in _DE_FOR_EN:
        return [f"{field}-{_DE_FOR_EN[role]}"]
    if role in _EN_FOR_DE:
        return [f"{field} {_EN_FOR_DE[role]}"]
    return []


def suggest_titles(cv: ParsedCV) -> list[str]:
    """Headline and the two most recent roles (no student jobs), plus DE/EN variants."""
    raw = [cv.headline] if cv.headline else []
    recent = sorted(cv.positions, key=lambda p: (p.end is None, p.end or "", p.start), reverse=True)
    raw += [p.role for p in recent if not STUDENT_ROLES.search(p.role)][:2]

    titles: list[str] = []
    seen: set[str] = set()

    def add(title: str) -> None:
        if title and title.casefold() not in seen and len(titles) < MAX_TITLES:
            seen.add(title.casefold())
            titles.append(title)

    cleaned = [clean_title(t) for t in raw]
    for title in cleaned:
        add(title)
    for title in cleaned:
        for variant in title_variants(title):
            add(variant)
    return titles


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
