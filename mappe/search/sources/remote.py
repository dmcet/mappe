"""Remote-only job APIs: Remotive, Jobicy and Remote OK.

Each one asks to be credited with a link to the original listing; the app shows the source
and links every hit to it.
"""

from __future__ import annotations

from typing import Any

import httpx

from mappe.search.models import JobHit, SearchQuery
from mappe.search.sources.base import (
    Source,
    SourceOptions,
    cached,
    get_json,
    open_to_germany,
    positive,
)
from mappe.search.text import html_to_text, parse_date, parse_salary_text

MAX_REQUESTS = 3

# --- Remotive ---------------------------------------------------------------------------

REMOTIVE = "https://remotive.com/api/remote-jobs"


async def fetch_remotive(
    client: httpx.AsyncClient, query: SearchQuery, opts: SourceOptions
) -> list[Any]:
    return [
        await get_json(client, REMOTIVE, search=title, limit=query.limit)
        for title in query.titles[:MAX_REQUESTS]
    ]


def parse_remotive(payload: Any) -> list[JobHit]:
    hits = []
    for job in payload.get("jobs") or []:
        where = job.get("candidate_required_location")
        if not job.get("id") or not job.get("url") or not open_to_germany(where):
            continue
        low, high, currency, period = parse_salary_text(job.get("salary"))
        hits.append(
            JobHit(
                source="remotive",
                external_id=str(job["id"]),
                url=job["url"],
                view_url=job["url"],
                title=(job.get("title") or "").strip(),
                company=job.get("company_name"),
                location=where or "Remote",
                remote="remote",
                salary_min=low,
                salary_max=high,
                salary_currency=currency,
                salary_period=period,
                description=html_to_text(job.get("description")),
                tags=[
                    *(job.get("tags") or []),
                    *([job["category"]] if job.get("category") else []),
                ],
                posted_at=parse_date(job.get("publication_date")),
            )
        )
    return hits


# --- Jobicy -----------------------------------------------------------------------------

JOBICY = "https://jobicy.com/api/v2/remote-jobs"


async def fetch_jobicy(
    client: httpx.AsyncClient, query: SearchQuery, opts: SourceOptions
) -> list[Any]:
    count = min(query.limit, 100)
    return [
        await get_json(client, JOBICY, count=count, geo="germany", tag=title)
        for title in query.titles[:MAX_REQUESTS]
    ]


def parse_jobicy(payload: Any) -> list[JobHit]:
    hits = []
    for job in payload.get("jobs") or []:
        if not job.get("id") or not job.get("url"):
            continue
        low, high = positive(job.get("annualSalaryMin")), positive(job.get("annualSalaryMax"))
        hits.append(
            JobHit(
                source="jobicy",
                external_id=str(job["id"]),
                url=job["url"],
                view_url=job["url"],
                title=(job.get("jobTitle") or "").strip(),
                company=job.get("companyName"),
                location=job.get("jobGeo") or "Remote",
                remote="remote",
                salary_min=low,
                salary_max=high,
                salary_currency=job.get("salaryCurrency") if low or high else None,
                salary_period="year" if low or high else None,
                description=html_to_text(job.get("jobDescription")),
                tags=[*(job.get("jobIndustry") or []), *(job.get("jobType") or [])],
                posted_at=parse_date(job.get("pubDate")),
            )
        )
    return hits


# --- Remote OK --------------------------------------------------------------------------

REMOTEOK = "https://remoteok.com/api"


async def fetch_remoteok(
    client: httpx.AsyncClient, query: SearchQuery, opts: SourceOptions
) -> list[Any]:
    payload = await cached("remoteok", opts.cache_minutes, lambda: get_json(client, REMOTEOK))
    return [payload]


def parse_remoteok(payload: Any) -> list[JobHit]:
    hits = []
    for job in payload or []:
        # The first element is the API's legal notice, not a job.
        if not isinstance(job, dict) or not job.get("id") or not job.get("url"):
            continue
        if not open_to_germany(job.get("location")):
            continue
        low, high = positive(job.get("salary_min")), positive(job.get("salary_max"))
        hits.append(
            JobHit(
                source="remoteok",
                external_id=str(job["id"]),
                url=job.get("apply_url") or job["url"],
                view_url=job["url"],
                title=(job.get("position") or "").strip(),
                company=job.get("company"),
                location=job.get("location") or "Remote",
                remote="remote",
                salary_min=low,
                salary_max=high,
                salary_currency="USD" if low or high else None,
                salary_period="year" if low or high else None,
                description=html_to_text(job.get("description")),
                tags=job.get("tags") or [],
                posted_at=parse_date(job.get("date") or job.get("epoch")),
            )
        )
    return hits


REMOTIVE_SOURCE = Source(
    key="remotive",
    label="Remotive",
    home="https://remotive.com/",
    fetch=fetch_remotive,
    parse=parse_remotive,
    remote_only=True,
)
JOBICY_SOURCE = Source(
    key="jobicy",
    label="Jobicy",
    home="https://jobicy.com/",
    fetch=fetch_jobicy,
    parse=parse_jobicy,
    remote_only=True,
)
REMOTEOK_SOURCE = Source(
    key="remoteok",
    label="Remote OK",
    home="https://remoteok.com/",
    fetch=fetch_remoteok,
    parse=parse_remoteok,
    remote_only=True,
)
