"""Exports: a search list (PDF), and applications with their documents (ZIP).

The ZIP holds one internal report (the list and the reasoning) plus the deliverables, each
tailored CV and cover letter, as separate files.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlmodel import Session, col, select

from mappe.config import get_settings
from mappe.db import CV, JobHitRecord, Run, Search
from mappe.domain.models import ParsedCV
from mappe.export.data import (
    HIDDEN_LABELS,
    Document,
    application_data,
    export_data,
    place_documents,
    ranking_text,
    run_documents,
    search_data,
)
from mappe.export.pdf import ExportError, build_zip, render_report
from mappe.runner.engine import run_title
from mappe.search.service import search_detail
from mappe.steps.final import file_part
from mappe.web.deps import SessionDep

router = APIRouter(prefix="/api")
ShowParam = Annotated[str, Query(description="Hidden reasons to include, comma-separated")]


def _download(content: bytes, filename: str, media_type: str) -> Response:
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content, media_type=media_type, headers=headers)


def _applications(runs: list[Run]) -> tuple[list[dict], list[Document]]:
    """Report sections and the documents that go next to the report, in the same order."""
    settings = get_settings()
    per_run = [(run, run_documents(settings, run)) for run in runs]
    place_documents(per_run)
    sections = [application_data(run, docs, links=True) for run, docs in per_run]
    return sections, [doc for _, docs in per_run for doc in docs]


def _cv(session: Session, cv_id: int) -> ParsedCV | None:
    cv = session.get(CV, cv_id)
    return ParsedCV.model_validate(cv.parsed) if cv and cv.parsed else None


def _search_export(session: Session, search_id: int, show: str, with_applications: bool):
    """The search, its runs (best score first, each once) and the list data."""
    search = session.get(Search, search_id)
    if search is None:
        raise HTTPException(404, "Search not found")
    shown = {s for s in show.split(",") if s in HIDDEN_LABELS}
    detail = search_detail(session, search)
    run_ids = dict.fromkeys(r["hit"]["run_id"] for r in detail["results"] if r["hit"]["run_id"])
    runs = {i: run for i in run_ids if (run := session.get(Run, i)) is not None}
    hit_ids = [r["hit"]["id"] for r in detail["results"]]
    records = session.exec(select(JobHitRecord).where(col(JobHitRecord.id).in_(hit_ids))).all()
    listing = search_data(
        detail,
        shown,
        runs,
        ranking_text(detail["ranking"]),
        with_applications=with_applications,
        descriptions={r.id: r.data.get("description", "") for r in records},  # type: ignore[misc]
    )
    return search, list(runs.values()), listing


def _stem(search: Search) -> str:
    return file_part(search.titles[0] if search.titles else "search")


@router.get("/searches/{search_id}/export.pdf")
def export_search(search_id: int, session: SessionDep, show: ShowParam = "") -> Response:
    """The search list as shown, with links to the listings."""
    search, _, listing = _search_export(session, search_id, show, with_applications=False)
    data = export_data(
        kind="search",
        title=f"Job search · {', '.join(search.titles[:2])}",
        candidate=_cv(session, search.cv_id),
        today=date.today(),
        search=listing,
    )
    try:
        content = render_report(data)
    except ExportError as exc:
        raise HTTPException(500, str(exc)) from exc
    name = f"Mappe_Jobs_{_stem(search)}_{date.today()}.pdf"
    return _download(content, name, "application/pdf")


def _zip(data: dict, stem: str, documents: list[Document]) -> Response:
    try:
        content = build_zip(data, f"{stem}_Report.pdf", documents)
    except ExportError as exc:
        raise HTTPException(500, str(exc)) from exc
    return _download(content, f"{stem}.zip", "application/zip")


@router.get("/searches/{search_id}/export.zip")
def export_search_applications(
    search_id: int, session: SessionDep, show: ShowParam = ""
) -> Response:
    """The list and every application started from it (report), plus their documents."""
    search, runs, listing = _search_export(session, search_id, show, with_applications=True)
    sections, documents = _applications(runs)
    data = export_data(
        kind="full",
        title=f"Applications · {', '.join(search.titles[:2])}",
        candidate=_cv(session, search.cv_id),
        today=date.today(),
        search=listing,
        applications=sections,
    )
    return _zip(data, f"Mappe_Applications_{_stem(search)}_{date.today()}", documents)


@router.get("/runs/{run_id}/export.zip")
def export_run(run_id: int, session: SessionDep) -> Response:
    """One application: the report with its reasoning, plus the CV and cover letter."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Application not found")
    sections, documents = _applications([run])
    state = run.state or {}
    cv = ParsedCV.model_validate(state["cv"]) if state.get("cv") else _cv(session, run.cv_id)
    data = export_data(
        kind="application",
        title=f"Application · {run_title(run)}",
        candidate=cv,
        today=date.today(),
        applications=sections,
    )
    company = (state.get("listing") or {}).get("company") or run_title(run)
    return _zip(data, f"Mappe_Application_{file_part(company)}_{date.today()}", documents)
