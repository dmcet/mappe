"""Deterministic CV summary for the confirmation page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from application_crew.checks.completeness import parse_month
from application_crew.domain.models import ParsedCV, Position


@dataclass(frozen=True)
class CVSummary:
    name: str
    positions: int
    years_of_experience: float  # overlapping positions are counted once
    current_role: str | None
    skills: int
    languages: list[str]
    certifications: int
    education: int


def experience_months(cv: ParsedCV, today: date | None = None) -> int:
    """Total months covered by the CV's positions, merging overlaps."""
    return merged_months(cv.positions, today)


def merged_months(positions: list[Position], today: date | None = None) -> int:
    """Months covered by ``positions``, counting overlapping periods once."""
    today = today or date.today()
    spans = []
    for p in positions:
        start = parse_month(p.start)
        if start is None:
            continue
        end = parse_month(p.end) or today
        if end >= start:
            spans.append((start, end))
    spans.sort()
    months = 0
    cur_start = cur_end = None
    for start, end in spans:
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                months += _months(cur_start, cur_end)
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        months += _months(cur_start, cur_end)
    return months


def _months(start: date, end: date) -> int:
    # Inclusive of the start month: Jan-Mar = 3 months.
    return (end.year - start.year) * 12 + end.month - start.month + 1


def summarize(cv: ParsedCV, today: date | None = None) -> CVSummary:
    current = next((p for p in cv.positions if p.end is None), None)
    return CVSummary(
        name=cv.contact.name,
        positions=len(cv.positions),
        years_of_experience=round(experience_months(cv, today) / 12, 1),
        current_role=f"{current.role} at {current.company}" if current else None,
        skills=len(cv.skills),
        languages=[
            f"{lang.name} ({lang.level})" if lang.level else lang.name for lang in cv.languages
        ],
        certifications=len(cv.certifications),
        education=len(cv.education),
    )
