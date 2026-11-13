"""Bundesagentur für Arbeit, Jobsuche API (the largest German job database).

Unofficial but public (documented on bund.dev); the key is the same for everyone. Search
results have no description, so the pipeline fetches the listing (the employer's page when
the hit names one).
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from mappe.search.models import JobHit, SearchQuery
from mappe.search.sources.base import Source, SourceOptions, positive
from mappe.search.text import parse_date

API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
DETAIL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}"
MAX_REQUESTS = 8


async def fetch(client: httpx.AsyncClient, query: SearchQuery, opts: SourceOptions) -> list[Any]:
    places: list[str | None] = list(query.places[:3]) or [None]
    payloads = []
    for title in query.titles:
        for place in places:
            if len(payloads) >= MAX_REQUESTS:
                return payloads
            params = {
                "was": title,
                "wo": place,
                "umkreis": query.radius(place) if place else None,
                "angebotsart": 1,  # jobs (not apprenticeships or self-employment)
                "veroeffentlichtseit": query.max_age_days,
                "size": min(query.limit, 100),
                "page": 1,
            }
            params = {k: v for k, v in params.items() if v is not None}
            resp = await client.get(API, params=params, headers=HEADERS)
            resp.raise_for_status()
            payloads.append(resp.json())
    return payloads


_REMOTE_TITLE = re.compile(r"\b(remote|home[- ]?office|100\s*%\s*mobil)\b", re.I)


def _remote(job: dict) -> tuple[str | None, int | None]:
    if _REMOTE_TITLE.search(job.get("stellenangebotsTitel") or ""):
        return "remote", None
    # "No home office" is often just an unticked box, so it stays unknown (never fails).
    if not job.get("homeofficemoeglich"):
        return None, None
    percent = positive(job.get("homeofficeprozent"))
    if percent is not None and percent >= 100:
        return "remote", None
    if percent is not None:
        return "hybrid", round(5 * (100 - percent) / 100)
    return "hybrid", None


def _salary(job: dict) -> tuple[int | None, int | None, str | None]:
    period = {"JAHRESGEHALT": "year", "MONATSGEHALT": "month", "STUNDENLOHN": "hour"}.get(
        job.get("verguetungsangabe", "")
    )
    fixed = positive(job.get("festgehalt"))
    low = positive(job.get("gehaltsspanneVon")) or fixed
    high = positive(job.get("gehaltsspanneBis")) or fixed
    return (low, high, period or "year") if low or high else (None, None, None)


def parse(payload: Any) -> list[JobHit]:
    hits = []
    for job in payload.get("ergebnisliste") or []:
        ref = job.get("referenznummer")
        title = job.get("stellenangebotsTitel")
        if not ref or not title:
            continue
        places = job.get("stellenlokationen") or []
        address = places[0].get("adresse", {}) if places else {}
        remote, onsite_days = _remote(job)
        low, high, period = _salary(job)
        occupations = [job.get("hauptberuf"), *(job.get("alleBerufe") or [])]
        view = DETAIL.format(ref=ref)
        hits.append(
            JobHit(
                source="ba",
                external_id=ref,
                url=job.get("externeURL") or view,
                view_url=view,
                title=title.strip(),
                company=(job.get("firma") or "").strip() or None,
                location=address.get("ort"),
                remote=remote,
                onsite_days_per_week=onsite_days,
                salary_min=low,
                salary_max=high,
                salary_currency="EUR" if low or high else None,
                salary_period=period,
                tags=list(dict.fromkeys(o for o in occupations if o)),
                posted_at=parse_date(
                    (job.get("veroeffentlichungszeitraum") or {}).get("von")
                    or job.get("aenderungsdatum")
                ),
            )
        )
    return hits


SOURCE = Source(
    key="ba",
    label="Bundesagentur für Arbeit",
    home="https://www.arbeitsagentur.de/jobsuche/",
    fetch=fetch,
    parse=parse,
    searches_places=True,
    full_text=False,
)
