"""Check user requirements against a parsed listing.

Structured requirements (salary, onsite days, location) are checked here in Python.
Benefit/other requirements are judged by Claude during listing parsing; their evidence
quote is verified against the listing text, so an invented quote can't pass a check.
Missing information is always ``unknown``, which never fails a must-have.
"""

from __future__ import annotations

import re

from mappe.domain.listing import FuzzyCheck
from mappe.domain.models import ParsedListing, Requirement, RequirementResult

# Annualisation factors (gross). 1720 h/year ~ 40 h/week, 43 weeks.
_PER_YEAR = {"year": 1, "month": 12, "hour": 1720}
FUZZY_KINDS = {"benefit", "other"}


def check_requirements(
    requirements: list[Requirement],
    listing: ParsedListing,
    listing_text: str,
    fuzzy_checks: list[FuzzyCheck],
) -> list[RequirementResult]:
    by_index = {c.index: c for c in fuzzy_checks}
    results = []
    for i, req in enumerate(requirements):
        if req.kind in FUZZY_KINDS:
            results.append(_fuzzy(req, by_index.get(i), listing_text))
        elif req.kind == "salary_min":
            results.append(_salary(req, listing))
        elif req.kind == "max_onsite_days":
            results.append(_onsite(req, listing))
        elif req.kind == "location":
            results.append(_location(req, listing))
    return results


def failed_must_haves(results: list[RequirementResult]) -> list[RequirementResult]:
    return [r for r in results if r.requirement.must_have and r.outcome == "failed"]


def _result(req: Requirement, outcome: str, note: str, evidence: str | None = None):
    return RequirementResult(requirement=req, outcome=outcome, note=note, evidence=evidence)


def _salary(req: Requirement, listing: ParsedListing) -> RequirementResult:
    wanted = _to_int(req.value)
    if wanted is None:
        return _result(req, "unknown", f"'{req.value}' is not a number")
    top = listing.salary_max or listing.salary_min
    if top is None:
        return _result(req, "unknown", "No salary stated")
    currency = (listing.salary_currency or "EUR").upper()
    if currency != "EUR":
        return _result(req, "unknown", f"Salary is in {currency}, not EUR")
    annual = top * _PER_YEAR[listing.salary_period or "year"]
    band = _band(listing)
    if annual >= wanted:
        return _result(req, "passed", f"Band {band} reaches {wanted:,} EUR/year")
    return _result(req, "failed", f"Band {band} is below {wanted:,} EUR/year")


def _band(listing: ParsedListing) -> str:
    low, high = listing.salary_min, listing.salary_max
    amount = f"{low:,}–{high:,}" if low and high and low != high else f"{high or low:,}"
    return f"{amount} {listing.salary_currency or 'EUR'}/{listing.salary_period or 'year'}"


def _onsite(req: Requirement, listing: ParsedListing) -> RequirementResult:
    allowed = _to_int(req.value)
    if allowed is None:
        return _result(req, "unknown", f"'{req.value}' is not a number")
    if listing.remote == "remote":
        return _result(req, "passed", "Fully remote")
    if listing.remote == "onsite":
        if allowed >= 5:
            return _result(req, "passed", "Onsite position")
        return _result(req, "failed", "Onsite position (5 days)")
    if listing.remote == "hybrid":
        days = listing.onsite_days_per_week
        if days is None:
            return _result(req, "unknown", "Hybrid, onsite days not stated")
        if days <= allowed:
            return _result(req, "passed", f"Hybrid, {days} onsite day(s) per week")
        return _result(req, "failed", f"Hybrid, {days} onsite day(s) per week")
    return _result(req, "unknown", "Work mode not stated")


# English and other exonyms of German cities -> the normalised German name.
_CITY_ALIASES = {
    "nuremberg": "nuernberg",
    "munich": "muenchen",
    "cologne": "koeln",
    "brunswick": "braunschweig",
    "hanover": "hannover",
}
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def normalize_place(text: str) -> str:
    """'Nürnberg', 'Nuernberg' and 'Nuremberg' -> 'nuernberg'."""
    text = re.sub(r"\s+", " ", text.casefold().translate(_UMLAUTS)).strip()
    for alias, name in _CITY_ALIASES.items():
        text = re.sub(rf"\b{alias}\b", name, text)
    return text


def _location(req: Requirement, listing: ParsedListing) -> RequirementResult:
    if listing.remote == "remote":
        return _result(req, "passed", "Fully remote")
    if not listing.location:
        return _result(req, "unknown", "No location stated")
    wanted = [normalize_place(c) for c in req.value.split(",") if c.strip()]
    where = normalize_place(listing.location)
    for city in wanted:
        if re.search(rf"\b{re.escape(city)}\b", where):
            return _result(req, "passed", f"Located in {listing.location}")
    return _result(req, "failed", f"Located in {listing.location}")


def _fuzzy(req: Requirement, check: FuzzyCheck | None, listing_text: str) -> RequirementResult:
    if check is None or check.outcome == "not_mentioned":
        return _result(req, "unknown", "Not mentioned in the listing")
    if not check.evidence.strip() or not _quote_in_text(check.evidence, listing_text):
        return _result(req, "unknown", "No verifiable quote in the listing")
    outcome = "passed" if check.outcome == "met" else "failed"
    note = "Mentioned in the listing" if outcome == "passed" else "Contradicted by the listing"
    return _result(req, outcome, note, evidence=check.evidence)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _quote_in_text(quote: str, text: str) -> bool:
    quote = _normalize(quote.strip(" \"'„“”…."))
    return len(quote) >= 3 and quote in _normalize(text)


def _to_int(value: str) -> int | None:
    """'75000', '75.000', '75,000 €' -> 75000; '75k' -> 75000."""
    value = (value or "").strip().lower()
    factor = 1000 if value.endswith("k") else 1
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) * factor if digits else None
