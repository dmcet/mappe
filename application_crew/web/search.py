"""Job search routes: suggestions, search, history, dismiss, start applications."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from application_crew.config import get_settings
from application_crew.db import CV, JobHitRecord, Search, SearchResult
from application_crew.domain.models import ParsedCV, Requirement
from application_crew.search.models import JobHit
from application_crew.search.queries import suggest_titles
from application_crew.search.service import (
    available_sources,
    build_query,
    collect,
    delete_search,
    save_search,
    search_detail,
    search_summary,
)
from application_crew.search.sources import SOURCES
from application_crew.web.deps import SessionDep
from application_crew.web.runs import confirmed_cv, run_summary, start_runs

router = APIRouter(prefix="/api")


class SearchCreate(BaseModel):
    cv_id: int
    titles: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    sources: list[str] | None = None  # None = the configured defaults


class ApplyHits(BaseModel):
    hit_ids: list[int]


def _parsed(cv: CV) -> ParsedCV:
    if not cv.parsed:
        raise HTTPException(409, "The CV has no parsed data yet")
    return ParsedCV.model_validate(cv.parsed)


def _search(session: Session, search_id: int) -> Search:
    search = session.get(Search, search_id)
    if search is None:
        raise HTTPException(404, "Search not found")
    return search


@router.get("/search/suggestions")
def suggestions(cv_id: int, session: SessionDep) -> dict:
    cv = confirmed_cv(session, cv_id)
    return {"titles": suggest_titles(_parsed(cv)), "sources": available_sources(get_settings())}


@router.post("/searches", status_code=201)
async def create_search(body: SearchCreate, session: SessionDep) -> dict:
    settings = get_settings()
    cv = confirmed_cv(session, body.cv_id)
    parsed = _parsed(cv)
    query = build_query(settings, body.titles or suggest_titles(parsed), body.requirements)
    if not query.titles:
        raise HTTPException(400, "Enter at least one job title to search for")
    keys = body.sources if body.sources is not None else list(settings.search.sources)
    unknown = [k for k in keys if k not in SOURCES]
    if unknown or not keys:
        raise HTTPException(400, f"Unknown sources: {unknown}" if unknown else "Choose a source")
    hits, statuses = await collect(settings, query, keys)
    search = save_search(
        session,
        cv_id=cv.id,  # type: ignore[arg-type]
        cv=parsed,
        query=query,
        requirements=body.requirements,
        hits=hits,
        statuses=statuses,
        settings=settings,
    )
    return search_detail(session, search)


@router.get("/searches")
def list_searches(session: SessionDep) -> list[dict]:
    searches = session.exec(select(Search).order_by(col(Search.created_at).desc()).limit(20)).all()
    return [search_summary(session, s) for s in searches]


@router.get("/searches/{search_id}")
def get_search(search_id: int, session: SessionDep) -> dict:
    return search_detail(session, _search(session, search_id))


@router.delete("/searches/{search_id}", status_code=204)
def remove_search(search_id: int, session: SessionDep) -> None:
    delete_search(session, _search(session, search_id))
    session.commit()


def _hit(session: Session, hit_id: int) -> JobHitRecord:
    record = session.get(JobHitRecord, hit_id)
    if record is None:
        raise HTTPException(404, "Listing not found")
    return record


@router.post("/job-hits/{hit_id}/dismiss")
def dismiss_hit(hit_id: int, session: SessionDep) -> dict:
    record = _hit(session, hit_id)
    record.status = "dismissed"
    session.add(record)
    session.commit()
    return {"id": record.id, "status": record.status}


@router.post("/job-hits/{hit_id}/restore")
def restore_hit(hit_id: int, session: SessionDep) -> dict:
    record = _hit(session, hit_id)
    record.status = "applied" if record.run_id else "new"
    session.add(record)
    session.commit()
    return {"id": record.id, "status": record.status}


@router.post("/searches/{search_id}/apply", status_code=201)
def apply_hits(
    search_id: int, body: ApplyHits, request: Request, session: SessionDep
) -> list[dict]:
    """Start one application per chosen listing, with the search's requirements."""
    search = _search(session, search_id)
    cv = confirmed_cv(session, search.cv_id)
    in_search = set(
        session.exec(select(SearchResult.hit_id).where(SearchResult.search_id == search.id)).all()
    )
    records = [_hit(session, i) for i in dict.fromkeys(body.hit_ids)]
    if not records:
        raise HTTPException(400, "Choose at least one listing")
    if any(r.id not in in_search for r in records):
        raise HTTPException(400, "A listing is not part of this search")

    listings: list[tuple[str | None, str | None]] = []
    for record in records:
        hit = JobHit.model_validate(record.data)
        source = SOURCES.get(hit.source)
        full = bool(source and source.full_text and hit.description)
        listings.append((hit.url, hit.listing_text() if full else None))
    requirements = [Requirement.model_validate(r) for r in search.requirements]
    runs = start_runs(request, session, cv, listings, requirements)
    for record, run in zip(records, runs, strict=True):
        record.status, record.run_id = "applied", run.id
        session.add(record)
    session.commit()
    return [run_summary(r) for r in runs]
