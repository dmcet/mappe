"""Adzuna API (Germany). Free, but needs an app ID and key from developer.adzuna.com.

Descriptions are snippets, so the pipeline fetches the full listing from the URL.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from mappe.search.models import JobHit, SearchQuery
from mappe.search.sources.base import Source, SourceOptions, get_json, positive
from mappe.search.text import html_to_text, parse_date

API = "https://api.adzuna.com/v1/api/jobs/de/search/1"
MAX_REQUESTS = 6


async def fetch(client: httpx.AsyncClient, query: SearchQuery, opts: SourceOptions) -> list[Any]:
    keys = {"app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"]}
    places: list[str | None] = list(query.places[:3]) or [None]
    payloads = []
    for title in query.titles:
        for place in places:
            if len(payloads) >= MAX_REQUESTS:
                return payloads
            payload = await get_json(
                client,
                API,
                **keys,
                what=title,
                where=place,
                distance=query.radius(place) if place else None,
                max_days_old=query.max_age_days,
                results_per_page=min(query.limit, 50),
            )
            payloads.append(payload)
    return payloads


def parse(payload: Any) -> list[JobHit]:
    hits = []
    for job in payload.get("results") or []:
        if not job.get("id") or not job.get("redirect_url"):
            continue
        predicted = str(job.get("salary_is_predicted", "0")) == "1"  # Adzuna's own estimate
        low = None if predicted else positive(job.get("salary_min"))
        high = None if predicted else positive(job.get("salary_max"))
        hits.append(
            JobHit(
                source="adzuna",
                external_id=str(job["id"]),
                url=job["redirect_url"],
                view_url=job["redirect_url"],
                title=html_to_text(job.get("title")),
                company=(job.get("company") or {}).get("display_name"),
                location=(job.get("location") or {}).get("display_name"),
                salary_min=low,
                salary_max=high,
                salary_currency="EUR" if low or high else None,
                salary_period="year" if low or high else None,
                description=html_to_text(job.get("description")),
                tags=[(job.get("category") or {}).get("label")] if job.get("category") else [],
                posted_at=parse_date(job.get("created")),
            )
        )
    return hits


SOURCE = Source(
    key="adzuna",
    label="Adzuna",
    home="https://www.adzuna.de/",
    fetch=fetch,
    parse=parse,
    searches_places=True,
    full_text=False,
    needs=("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
)
