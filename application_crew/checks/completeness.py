"""Deterministic CV completeness and plausibility checks (shown as warnings in the UI)."""

from __future__ import annotations

import re
from datetime import date

from application_crew.domain.models import ParsedCV

DATE_RE = re.compile(r"^(\d{4})(?:-(0[1-9]|1[0-2]))?$")
CEFR = {"a1", "a2", "b1", "b2", "c1", "c2", "native"}


def parse_month(value: str | None) -> date | None:
    """'YYYY-MM' -> first of month; 'YYYY' -> January. Invalid/empty -> None."""
    if not value:
        return None
    m = DATE_RE.match(value.strip())
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2) or 1), 1)


def check_cv(cv: ParsedCV, today: date | None = None) -> list[str]:
    today = today or date.today()
    warnings: list[str] = []
    c = cv.contact

    for label, value in [("email", c.email), ("phone number", c.phone), ("city", c.city)]:
        if not value:
            warnings.append(f"Contact: no {label} found.")
    if not cv.positions:
        warnings.append("Experience: no positions found.")
    if not cv.skills:
        warnings.append("Skills: no skills found.")
    if not cv.languages:
        warnings.append("Languages: no languages found.")
    for lang in cv.languages:
        if lang.level.strip().casefold() not in CEFR:
            level = lang.level or "missing"
            warnings.append(
                f"Languages: level of {lang.name} is '{level}', expected CEFR (A1-C2) or native."
            )

    for p in cv.positions:
        where = f"{p.role} at {p.company}"
        start, end = parse_month(p.start), parse_month(p.end)
        if start is None:
            warnings.append(f"Experience: {where} has no valid start date (YYYY-MM).")
        if p.end and end is None:
            warnings.append(f"Experience: {where} has an invalid end date '{p.end}'.")
        if start and end and end < start:
            warnings.append(f"Experience: {where} ends before it starts.")
        if start and start > today:
            warnings.append(f"Experience: {where} starts in the future.")
        if not p.location:
            warnings.append(f"Experience: {where} has no location.")
        if not p.responsibilities and not p.achievements:
            warnings.append(f"Experience: {where} has no responsibilities or achievements.")

    for e in cv.education:
        if not e.end and not e.start:
            warnings.append(f"Education: {e.qualification} ({e.institution}) has no dates.")
    for cert in cv.certifications:
        missing = [k for k in ("issuer", "year") if not getattr(cert, k)]
        if missing:
            warnings.append(f"Certifications: {cert.name} has no {' or '.join(missing)}.")

    return warnings
