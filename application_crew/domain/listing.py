"""Claude-facing listing extraction, JSON-LD mapping, and the merge into ParsedListing.

Precedence: schema.org ``JobPosting`` data from the page is structured and authoritative,
so it wins for title, company, location, remote and salary. Claude fills everything else
and every gap the JSON-LD leaves.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from application_crew.domain.models import ParsedListing, RemoteMode, SalaryPeriod


class FuzzyCheck(BaseModel):
    """Claude's judgement of one benefit/other requirement against the listing."""

    index: int = Field(description="Index of the requirement in the given list")
    outcome: Literal["met", "not_met", "not_mentioned"]
    evidence: str | None = Field(
        description="Verbatim quote from the listing supporting the outcome; null if not mentioned"
    )


class ExtractedListing(BaseModel):
    title: str | None
    company: str | None
    domain: str | None = Field(
        description="Industry of the company (automotive, banking, ...) if stated or obvious"
    )
    responsibilities: list[str]
    required_skills: list[str]
    nice_to_have_skills: list[str]
    location: str | None = Field(description="City or cities of the workplace")
    remote: RemoteMode | None
    onsite_days_per_week: int | None = Field(
        description="For hybrid: maximum onsite days per week stated; null if not stated"
    )
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None = Field(description="ISO code, e.g. EUR")
    salary_period: SalaryPeriod | None
    benefits: list[str]
    cover_letter_requested: bool = Field(
        description="True only if the listing explicitly asks for a cover letter / Anschreiben"
    )
    requirement_checks: list[FuzzyCheck]


_SALARY_UNITS: dict[str, SalaryPeriod] = {"YEAR": "year", "MONTH": "month", "HOUR": "hour"}


def from_job_posting(posting: dict[str, Any] | None) -> dict[str, Any]:
    """Map the reliable fields of a schema.org JobPosting to ParsedListing fields."""
    if not posting:
        return {}
    out: dict[str, Any] = {}

    if isinstance(title := posting.get("title"), str) and title.strip():
        out["title"] = title.strip()

    org = posting.get("hiringOrganization")
    if isinstance(org, dict) and isinstance(org.get("name"), str):
        out["company"] = org["name"].strip()
    elif isinstance(org, str) and org.strip():
        out["company"] = org.strip()

    cities = []
    locations = posting.get("jobLocation")
    for loc in locations if isinstance(locations, list) else [locations]:
        address = loc.get("address") if isinstance(loc, dict) else None
        city = address.get("addressLocality") if isinstance(address, dict) else None
        if isinstance(city, str) and city.strip() and city.strip() not in cities:
            cities.append(city.strip())
    if cities:
        out["location"] = ", ".join(cities)

    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        out["remote"] = "remote"

    salary = posting.get("baseSalary")
    if isinstance(salary, dict):
        value = salary.get("value")
        if isinstance(value, dict):
            low = _to_int(value.get("minValue") or value.get("value"))
            high = _to_int(value.get("maxValue") or value.get("value"))
            unit = _SALARY_UNITS.get(str(value.get("unitText", "")).upper())
        else:
            low = high = _to_int(value)
            unit = None
        if low or high:
            out["salary_min"], out["salary_max"] = low, high
            out["salary_currency"] = salary.get("currency")
            if unit:
                out["salary_period"] = unit
    return out


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def merge_listing(extracted: ExtractedListing, job_posting: dict[str, Any] | None, language: str):
    data = extracted.model_dump(exclude={"requirement_checks"})
    for key, value in from_job_posting(job_posting).items():
        if value is not None:
            data[key] = value
    data["language"] = language
    return ParsedListing(**data)
