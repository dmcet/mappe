"""Live data: what is running, what it costs, and a stream of changes (SSE)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from sqlalchemy import func
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from application_crew.db import CV, Event, Run, Usage, get_engine
from application_crew.runner import activity
from application_crew.runner.engine import run_title
from application_crew.web.pipeline import GATE_PROMPTS

router = APIRouter(prefix="/api")

MODEL_NAMES = {
    "claude-opus-5-5": "Opus 5.5",
    "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-haiku-5-5": "Haiku 5.5",
    "unknown": "before cost tracking",
}


def _sum(session: Session, since: datetime | None = None) -> float:
    stmt = select(func.coalesce(func.sum(Usage.cost_usd), 0.0))
    if since is not None:
        stmt = stmt.where(Usage.created_at >= since)
    return float(session.exec(stmt).one())


def cost_summary(session: Session) -> dict:
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    by_model = session.exec(
        select(Usage.model, func.sum(Usage.cost_usd), func.count())
        .group_by(Usage.model)
        .order_by(func.sum(Usage.cost_usd).desc())
    ).all()
    by_step = session.exec(
        select(Usage.step, func.sum(Usage.cost_usd), func.count())
        .group_by(Usage.step)
        .order_by(func.sum(Usage.cost_usd).desc())
    ).all()
    days = session.exec(
        select(func.date(Usage.created_at), func.sum(Usage.cost_usd))
        .where(Usage.created_at >= today - timedelta(days=29))
        .group_by(func.date(Usage.created_at))
    ).all()
    per_day = {str(d): float(c) for d, c in days}
    last = session.exec(select(Usage).order_by(Usage.id.desc()).limit(1)).first()  # type: ignore[union-attr]
    return {
        "total_usd": _sum(session),
        "today_usd": _sum(session, today),
        "month_usd": _sum(session, month),
        "by_model": [
            {"model": m, "name": MODEL_NAMES.get(m, m), "cost_usd": float(c), "calls": n}
            for m, c, n in by_model
        ],
        "by_step": [{"step": s, "cost_usd": float(c), "calls": n} for s, c, n in by_step],
        "last_30_days": [
            {
                "date": (today - timedelta(days=i)).date().isoformat(),
                "cost_usd": per_day.get((today - timedelta(days=i)).date().isoformat(), 0.0),
            }
            for i in range(29, -1, -1)
        ],
        "last_call": (
            {
                "step": last.step,
                "model": MODEL_NAMES.get(last.model, last.model),
                "cost_usd": last.cost_usd,
                "at": last.created_at.isoformat(),
            }
            if last
            else None
        ),
    }


def status_snapshot(request: Request, session: Session) -> dict:
    engine = request.app.state.engine
    settings = engine.settings
    gates = session.exec(
        select(Run).where(Run.status.in_([g.name for g in GATE_PROMPTS]))  # type: ignore[attr-defined]
    ).all()
    return {
        "jobs": activity.snapshot(),
        "queued": engine.queued(),
        "waiting_for_you": [
            {
                "id": r.id,
                "title": run_title(r),
                "status": str(r.status),
                "prompt": GATE_PROMPTS[r.status],
            }
            for r in sorted(gates, key=lambda r: r.updated_at)
        ],
        "demo": settings.demo,
        "costs": {
            "total_usd": _sum(session),
            "today_usd": _sum(session, datetime.now(UTC).replace(hour=0, minute=0, second=0)),
            "limit_per_run_usd": settings.review.cost_limit_usd,
        },
    }


@router.get("/status")
def get_status(request: Request) -> dict:
    with Session(get_engine()) as session:
        return status_snapshot(request, session)


@router.get("/costs")
def get_costs() -> dict:
    with Session(get_engine()) as session:
        return cost_summary(session)


@router.get("/stream")
async def stream(request: Request) -> EventSourceResponse:
    """One message per second: the status snapshot plus which runs and CVs changed.

    The frontend refetches only what changed, so pages stay live without polling.
    """

    async def events() -> AsyncIterator[dict[str, str]]:
        with Session(get_engine()) as session:
            last_event = session.exec(select(func.coalesce(func.max(Event.id), 0))).one()
        since = datetime.now(UTC)
        previous = ""
        while not await request.is_disconnected():
            with Session(get_engine()) as session:
                runs = set(session.exec(select(Event.run_id).where(Event.id > last_event)).all())
                last_event = session.exec(select(func.coalesce(func.max(Event.id), 0))).one()
                now = datetime.now(UTC)
                runs |= set(session.exec(select(Run.id).where(Run.updated_at >= since)).all())
                cvs = set(session.exec(select(CV.id).where(CV.updated_at >= since)).all())
                since = now
                snapshot = status_snapshot(request, session)
            payload = {**snapshot, "changed": {"runs": sorted(runs), "cvs": sorted(cvs)}}
            text = json.dumps(payload, default=str)
            # Always send while jobs run (elapsed time ticks); otherwise only on change.
            if snapshot["jobs"] or runs or cvs or text != previous:
                yield {"event": "status", "data": text}
                previous = text
            await asyncio.sleep(1.0)

    return EventSourceResponse(events(), ping=15)
