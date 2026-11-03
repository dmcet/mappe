"""One search: query the sources in parallel, merge, rank, store."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx
from sqlmodel import Session, col, delete, select

from application_crew.config import Settings
from application_crew.db import JobHitRecord, SavedSearch, Search, SearchResult
from application_crew.domain.models import ParsedCV, Requirement
from application_crew.fetch.listing import USER_AGENT
from application_crew.runner import activity
from application_crew.search.dedupe import dedupe
from application_crew.search.models import JobHit, SearchQuery
from application_crew.search.queries import places_from, remote_only
from application_crew.search.rank import rank
from application_crew.search.sources import SOURCES, missing_env
from application_crew.search.sources.base import Source, SourceOptions

log = logging.getLogger(__name__)


@dataclass
class SourceStatus:
    label: str
    count: int = 0
    error: str | None = None
    seconds: float = 0.0
    hits: list[JobHit] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "count": self.count,
            "error": self.error,
            "seconds": self.seconds,
        }


def make_client(timeout: float) -> httpx.AsyncClient:
    """Separate so tests can swap in a mock transport."""
    return httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )


def available_sources(settings: Settings) -> list[dict]:
    return [
        {
            "key": s.key,
            "label": s.label,
            "home": s.home,
            "remote_only": s.remote_only,
            "default": s.key in settings.search.sources,
            "missing_env": [] if settings.demo else missing_env(s),
        }
        for s in SOURCES.values()
    ]


def build_query(settings: Settings, titles: list[str], reqs: list[Requirement]) -> SearchQuery:
    cfg = settings.search
    return SearchQuery(
        titles=[t.strip() for t in titles if t.strip()],
        places=places_from(reqs),
        remote_only=remote_only(reqs),
        radius_km=cfg.radius_km,
        max_age_days=cfg.max_age_days,
        limit=cfg.max_results_per_source,
    )


def _as_of_today(hits: list[JobHit]) -> list[JobHit]:
    """Demo samples were recorded once; shift their dates so the newest one is today."""
    dates = [h.posted_at for h in hits if h.posted_at]
    if not dates:
        return hits
    shift = date.today() - max(dates)
    return [
        h.model_copy(update={"posted_at": h.posted_at + shift}) if h.posted_at else h for h in hits
    ]


async def _run_source(
    source: Source, client: httpx.AsyncClient, query: SearchQuery, settings: Settings
) -> SourceStatus:
    status = SourceStatus(source.label)
    started = time.monotonic()
    opts = SourceOptions(settings.search.cache_minutes, settings.search.list_pages)
    try:
        if settings.demo:
            payloads = [source.sample()]
        else:
            payloads = await asyncio.wait_for(
                source.fetch(client, query, opts), settings.search.timeout_seconds
            )
        for payload in payloads:
            status.hits += source.parse(payload)
        if settings.demo:
            status.hits = _as_of_today(status.hits)
        status.count = len({h.external_id for h in status.hits})
    except TimeoutError:
        status.error = "timed out"
    except httpx.HTTPStatusError as exc:
        status.error = f"HTTP {exc.response.status_code}"
    except Exception as exc:  # a broken source must never fail the whole search
        log.warning("Job source %s failed", source.key, exc_info=True)
        status.error = f"{type(exc).__name__}: {exc}"[:200]
    status.seconds = round(time.monotonic() - started, 1)
    return status


async def collect(
    settings: Settings, query: SearchQuery, keys: list[str]
) -> tuple[list[JobHit], dict[str, SourceStatus]]:
    statuses: dict[str, SourceStatus] = {}
    runnable = []
    for source in (SOURCES[k] for k in keys if k in SOURCES):
        missing = [] if settings.demo else missing_env(source)
        if missing:
            statuses[source.key] = SourceStatus(source.label, error=f"needs {', '.join(missing)}")
        else:
            runnable.append(source)
    progress = {
        k: {"label": SOURCES[k].label, "state": "running", "count": 0, "error": None}
        for k in keys
        if k in SOURCES
    }
    for key, status in statuses.items():
        progress[key] |= {"state": "failed", "error": status.error}

    def report() -> None:
        done = sum(p["state"] != "running" for p in progress.values())
        found = sum(p["count"] for p in progress.values())
        detail = f"Searching jobs · {done}/{len(progress)} sources · {found} listings"
        activity.update(detail, progress={k: dict(v) for k, v in progress.items()})

    async def run(source: Source, client: httpx.AsyncClient) -> SourceStatus:
        status = await _run_source(source, client, query, settings)
        progress[source.key] |= {
            "state": "failed" if status.error else "done",
            "count": status.count,
            "error": status.error,
        }
        report()
        return status

    report()
    async with make_client(settings.search.timeout_seconds) as client:
        results = await asyncio.gather(*(run(s, client) for s in runnable))
    statuses |= {s.key: r for s, r in zip(runnable, results, strict=True)}
    hits = [h for r in results for h in r.hits]
    return hits, {k: statuses[k] for k in keys if k in statuses}


def _now() -> datetime:
    return datetime.now(UTC)


def save_search(
    session: Session,
    *,
    cv_id: int,
    cv: ParsedCV,
    query: SearchQuery,
    requirements: list[Requirement],
    hits: list[JobHit],
    statuses: dict[str, SourceStatus],
    settings: Settings,
    saved_id: int | None = None,
) -> Search:
    """Store a search. "New" means first seen ever, or, for a saved search, not found by
    any of its earlier runs."""
    hits = dedupe(hits)
    seen_before: set[int] | None = None
    if saved_id is not None:
        earlier = select(Search.id).where(Search.saved_id == saved_id)
        seen_before = set(
            session.exec(
                select(SearchResult.hit_id).where(col(SearchResult.search_id).in_(earlier))
            ).all()
        )
    ids = {h.external_id for h in hits}
    records = (
        {
            (r.source, r.external_id): r
            for r in session.exec(
                select(JobHitRecord).where(col(JobHitRecord.external_id).in_(ids))
            )
        }
        if ids
        else {}
    )
    dismissed = {f"{s}:{e}" for (s, e), r in records.items() if r.status == "dismissed"}
    ranked = rank(
        hits,
        cv,
        requirements,
        max_age_days=settings.search.max_age_days,
        min_score=settings.search.min_score,
        dismissed=dismissed,
        places=query.places,
        located={k for k, s in SOURCES.items() if s.searches_places},
    )

    search = Search(
        cv_id=cv_id,
        saved_id=saved_id,
        titles=query.titles,
        places=query.places,
        remote_only=query.remote_only,
        requirements=[r.model_dump(mode="json") for r in requirements],
        sources={k: s.to_dict() for k, s in statuses.items()},
    )
    session.add(search)
    session.flush()
    for item in ranked:
        hit = item.hit
        record = records.get((hit.source, hit.external_id))
        if record is None:
            record = JobHitRecord(source=hit.source, external_id=hit.external_id)
        is_new = record.id is None if seen_before is None else record.id not in seen_before
        record.data = hit.model_dump(mode="json")
        record.last_seen_at = _now()
        session.add(record)
        session.flush()
        session.add(
            SearchResult(
                search_id=search.id,  # type: ignore[arg-type]
                hit_id=record.id,  # type: ignore[arg-type]
                score=item.score,
                reasons=item.reasons(),
                hidden=item.hidden,
                is_new=is_new,
            )
        )
    session.commit()
    session.refresh(search)
    return search


def search_summary(session: Session, search: Search) -> dict:
    results = session.exec(select(SearchResult).where(SearchResult.search_id == search.id)).all()
    return {
        "id": search.id,
        "cv_id": search.cv_id,
        "saved_id": search.saved_id,
        "titles": search.titles,
        "places": search.places,
        "remote_only": search.remote_only,
        "created_at": search.created_at,
        "total": len(results),
        "shown": sum(r.hidden is None for r in results),
        "new": sum(r.is_new and r.hidden is None for r in results),
    }


def hit_view(record: JobHitRecord) -> dict:
    hit = JobHit.model_validate(record.data)
    source = SOURCES.get(hit.source)
    return {
        "id": record.id,
        "status": record.status,
        "run_id": record.run_id,
        "source_label": source.label if source else hit.source,
        "source_home": source.home if source else None,
        "full_text": bool(source and source.full_text and hit.description),
        "first_seen_at": record.first_seen_at,
        **hit.model_dump(mode="json", exclude={"description"}),
        "excerpt": hit.description[:400],
    }


def search_detail(session: Session, search: Search) -> dict:
    rows = session.exec(
        select(SearchResult, JobHitRecord)
        .join(JobHitRecord, col(JobHitRecord.id) == SearchResult.hit_id)
        .where(SearchResult.search_id == search.id)
        .order_by(col(SearchResult.score).desc())
    ).all()
    results = []
    for result, record in rows:
        hidden = result.hidden
        # Dismissing or restoring after the search changes what is shown now.
        if record.status == "dismissed":
            hidden = "dismissed"
        elif hidden == "dismissed":
            hidden = None
        results.append(
            {
                "score": result.score,
                "reasons": result.reasons,
                "hidden": hidden,
                "is_new": result.is_new,
                "hit": hit_view(record),
            }
        )
    return search_summary(session, search) | {
        "requirements": search.requirements,
        "sources": search.sources,
        "results": results,
    }


def saved_view(session: Session, saved: SavedSearch) -> dict:
    last = session.exec(
        select(Search).where(Search.saved_id == saved.id).order_by(col(Search.id).desc()).limit(1)
    ).first()
    return {
        "id": saved.id,
        "cv_id": saved.cv_id,
        "name": saved.name,
        "titles": saved.titles,
        "requirements": saved.requirements,
        "sources": saved.sources,
        "created_at": saved.created_at,
        "last_run": search_summary(session, last) if last else None,
    }


def delete_saved(session: Session, saved: SavedSearch) -> None:
    """Delete a saved search; its runs stay as ordinary searches (the caller commits)."""
    for search in session.exec(select(Search).where(Search.saved_id == saved.id)).all():
        search.saved_id = None
        session.add(search)
    session.delete(saved)


def delete_search(session: Session, search: Search) -> None:
    """Delete a search and its scores (the caller commits). Listings stay for later searches."""
    session.exec(delete(SearchResult).where(col(SearchResult.search_id) == search.id))
    session.delete(search)
