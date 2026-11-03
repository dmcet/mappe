"""Arbeitnow job board API: newest jobs in Germany, no search, updated hourly."""

from __future__ import annotations

from typing import Any

import httpx

from application_crew.search.models import JobHit, SearchQuery
from application_crew.search.sources.base import Source, SourceOptions, cached, get_json
from application_crew.search.text import html_to_text, parse_date

API = "https://www.arbeitnow.com/api/job-board-api"


async def fetch(client: httpx.AsyncClient, query: SearchQuery, opts: SourceOptions) -> list[Any]:
    async def load() -> list[Any]:
        pages = []
        for page in range(1, opts.pages + 1):
            payload = await get_json(client, API, page=page)
            pages.append(payload)
            if not (payload.get("links") or {}).get("next"):
                break
        return pages

    return await cached(f"arbeitnow:{opts.pages}", opts.cache_minutes, load)


def parse(payload: Any) -> list[JobHit]:
    hits = []
    for job in payload.get("data") or []:
        if not job.get("slug") or not job.get("title") or not job.get("url"):
            continue
        hits.append(
            JobHit(
                source="arbeitnow",
                external_id=job["slug"],
                url=job["url"],
                view_url=job["url"],
                title=job["title"].strip(),
                company=job.get("company_name"),
                location=job.get("location"),
                remote="remote" if job.get("remote") else None,
                description=html_to_text(job.get("description")),
                tags=[*(job.get("tags") or []), *(job.get("job_types") or [])],
                posted_at=parse_date(job.get("created_at")),
            )
        )
    return hits


SOURCE = Source(
    key="arbeitnow",
    label="Arbeitnow",
    home="https://www.arbeitnow.com/",
    fetch=fetch,
    parse=parse,
)
