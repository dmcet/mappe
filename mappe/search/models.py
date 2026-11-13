"""Job search models: a normalised hit from any source, and one search request."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field

from mappe.domain.models import ParsedListing, RemoteMode, SalaryPeriod


class JobHit(BaseModel):
    """One listing from a job API, in the same shape for every source."""

    source: str  # key in sources.SOURCES
    external_id: str
    url: str  # used for the application (the employer's page when the source names one)
    view_url: str  # where the user reads the listing (the source's page)
    title: str
    company: str | None = None
    location: str | None = None
    remote: RemoteMode | None = None
    onsite_days_per_week: int | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    description: str = ""  # plain text; empty when the source has none (Bundesagentur)
    tags: list[str] = Field(default_factory=list)  # tags, occupations, categories
    posted_at: date | None = None
    also_on: list[str] = Field(default_factory=list)  # other sources with the same listing

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"

    def as_listing(self) -> ParsedListing:
        """The fields the requirement checks need."""
        return ParsedListing(
            title=self.title,
            company=self.company,
            location=self.location,
            remote=self.remote,
            onsite_days_per_week=self.onsite_days_per_week,
            salary_min=self.salary_min,
            salary_max=self.salary_max,
            salary_currency=self.salary_currency,
            salary_period=self.salary_period,
        )

    def listing_text(self) -> str:
        """Text handed to the application pipeline, so it doesn't fetch the page again."""
        head = [self.title]
        if self.company:
            head.append(self.company)
        if self.location:
            head.append(f"Location: {self.location}")
        if self.remote == "remote":
            head.append("Remote")
        if self.salary_min or self.salary_max:
            low, high = self.salary_min or self.salary_max, self.salary_max or self.salary_min
            amount = f"{low:,}" if low == high else f"{low:,} - {high:,}"
            head.append(
                f"Salary: {amount} {self.salary_currency or ''}/{self.salary_period or 'year'}"
            )
        return "\n".join(head) + "\n\n" + self.description


@dataclass
class SearchQuery:
    titles: list[str]
    places: list[str] = field(default_factory=list)  # empty = all of Germany
    remote_only: bool = False
    no_remote: bool = False  # fully remote jobs are excluded: skip remote-only sources
    radius_km: int = 30  # default radius
    radii: dict[str, int] = field(default_factory=dict)  # per place, overrides the default
    max_age_days: int = 30
    limit: int = 100  # per source

    def radius(self, place: str) -> int:
        return self.radii.get(place, self.radius_km)
