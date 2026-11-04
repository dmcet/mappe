"""Merge the same listing found on several sources."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from mappe.checks.requirements import normalize_place
from mappe.search.models import JobHit
from mappe.search.queries import clean_title

_LEGAL_FORM = re.compile(r"\b(gmbh|ag|se|kg|co|mbh|inc|ltd|llc|ug|e\.?v)\b\.?", re.I)
TITLE_SIMILARITY = 92


def _company(name: str | None) -> str:
    return re.sub(r"[^\w]+", " ", _LEGAL_FORM.sub(" ", (name or "").casefold())).strip()


def _city(location: str | None) -> str:
    return normalize_place(re.split(r"[,(/]", location or "")[0])


def _url(url: str) -> str:
    return re.sub(r"[?#].*$", "", url).rstrip("/").casefold()


def _same(a: JobHit, b: JobHit) -> bool:
    if _url(a.url) == _url(b.url):
        return True
    if not a.company or _company(a.company) != _company(b.company):
        return False
    if _city(a.location) != _city(b.location) and "remote" not in {a.remote, b.remote}:
        return False
    ta, tb = clean_title(a.title).casefold(), clean_title(b.title).casefold()
    return fuzz.token_set_ratio(ta, tb) >= TITLE_SIMILARITY


def dedupe(hits: list[JobHit]) -> list[JobHit]:
    """Keep the hit with the longest description; note the other sources on it."""
    kept: list[JobHit] = []
    for hit in hits:
        for i, other in enumerate(kept):
            if hit.key == other.key or _same(hit, other):
                best, rest = (
                    (hit, other)
                    if len(hit.description) > len(other.description)
                    else (
                        other,
                        hit,
                    )
                )
                sources = {*best.also_on, *rest.also_on, rest.source} - {best.source}
                kept[i] = best.model_copy(update={"also_on": sorted(sources)})
                break
        else:
            kept.append(hit)
    return kept
