"""Job search routes: suggestions, search, history, dismiss, start applications."""

from __future__ import annotations

import itertools

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from mappe.config import get_settings
from mappe.db import CV, JobHitRecord, SavedSearch, Search, SearchResult
from mappe.domain.models import ParsedCV, Requirement
from mappe.runner import activity
from mappe.search.models import JobHit
from mappe.search.queries import suggest_titles
from mappe.search.service import (
    available_sources,
    build_query,
    collect,
    delete_saved,
    delete_search,
    save_search,
    saved_view,
    search_detail,
    search_summary,
)
from mappe.search.sources import SOURCES
from mappe.web.deps import SessionDep
from mappe.web.runs import confirmed_cv, run_summary, start_runs

router = APIRouter(prefix="/api")
_search_ids = itertools.count(1)  # live status IDs for running searches


class SearchCreate(BaseModel):
    cv_id: int
    titles: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    sources: list[str] | None = None  # None = the configured defaults


class SearchPrefs(BaseModel):
    """The search form of one CV, kept between visits."""

    titles: list[str] = Field(default_factory=list)  # searched
    titles_off: list[str] = Field(default_factory=list)  # shown as chips, not searched
    requirements: list[Requirement] = Field(default_factory=list)
    requirements_off: list[Requirement] = Field(default_factory=list)  # parked chips
    sources: list[str] | None = None


class SavedCreate(BaseModel):
    search_id: int  # save the parameters of this search; it becomes the first run
    name: str = ""


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
    """Titles from the CV (searched by default), Claude's alternative roles (opt-in) and
    the form as the user last left it for this CV (``prefs``, None before the first save)."""
    cv = confirmed_cv(session, cv_id)
    return {
        "prefs": cv.search_prefs,
        "titles": suggest_titles(_parsed(cv)),
        "roles": [{k: r[k] for k in ("title", "title_alt", "reason")} for r in cv.roles or []],
        "roles_status": cv.roles_status,
        "sources": available_sources(get_settings()),
    }


@router.put("/search/prefs/{cv_id}")
def save_prefs(cv_id: int, body: SearchPrefs, session: SessionDep) -> dict:
    cv = confirmed_cv(session, cv_id)
    cv.search_prefs = body.model_dump(mode="json")
    session.add(cv)
    session.commit()
    return cv.search_prefs


async def _run(
    session: Session,
    cv_id: int,
    titles: list[str],
    requirements: list[Requirement],
    sources: list[str] | None,
    saved_id: int | None = None,
) -> Search:
    settings = get_settings()
    cv = confirmed_cv(session, cv_id)
    parsed = _parsed(cv)
    query = build_query(settings, titles or suggest_titles(parsed), requirements)
    if not query.titles:
        raise HTTPException(400, "Enter at least one job title to search for")
    keys = sources if sources is not None else list(settings.search.sources)
    unknown = [k for k in keys if k not in SOURCES]
    if unknown or not keys:
        raise HTTPException(400, f"Unknown sources: {unknown}" if unknown else "Choose a source")
    activity.begin("search", next(_search_ids), f"Job search: {', '.join(query.titles[:2])}")
    try:
        hits, statuses = await collect(settings, query, keys)
        return await save_search(
            session,
            cv_id=cv_id,
            cv=parsed,
            query=query,
            requirements=requirements,
            hits=hits,
            statuses=statuses,
            settings=settings,
            saved_id=saved_id,
        )
    finally:
        activity.end()


@router.post("/searches", status_code=201)
async def create_search(body: SearchCreate, session: SessionDep) -> dict:
    search = await _run(session, body.cv_id, body.titles, body.requirements, body.sources)
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


# --- saved searches ---------------------------------------------------------------------


def _saved(session: Session, saved_id: int) -> SavedSearch:
    saved = session.get(SavedSearch, saved_id)
    if saved is None:
        raise HTTPException(404, "Saved search not found")
    return saved


@router.get("/saved-searches")
def list_saved(session: SessionDep) -> list[dict]:
    rows = session.exec(select(SavedSearch).order_by(col(SavedSearch.name))).all()
    return [saved_view(session, s) for s in rows]


@router.post("/saved-searches", status_code=201)
def create_saved(body: SavedCreate, session: SessionDep) -> dict:
    search = _search(session, body.search_id)
    if search.saved_id is not None:
        raise HTTPException(409, "This search is already saved")
    name = body.name.strip() or ", ".join(search.titles[:2])
    if search.places:
        name = body.name.strip() or f"{name} · {', '.join(search.places)}"
    saved = SavedSearch(
        cv_id=search.cv_id,
        name=name,
        titles=search.titles,
        requirements=search.requirements,
        sources=list(search.sources),
    )
    session.add(saved)
    session.flush()
    search.saved_id = saved.id
    session.add(search)
    session.commit()
    return saved_view(session, saved)


@router.post("/saved-searches/{saved_id}/run", status_code=201)
async def run_saved(saved_id: int, session: SessionDep) -> dict:
    """Run a saved search again; "new" marks listings none of its earlier runs found."""
    saved = _saved(session, saved_id)
    requirements = [Requirement.model_validate(r) for r in saved.requirements]
    search = await _run(
        session, saved.cv_id, saved.titles, requirements, saved.sources, saved_id=saved.id
    )
    return search_detail(session, search)


@router.delete("/saved-searches/{saved_id}", status_code=204)
def remove_saved(saved_id: int, session: SessionDep) -> None:
    delete_saved(session, _saved(session, saved_id))
    session.commit()
