"""Listing steps: decide the source and fetch (deterministic)."""

from __future__ import annotations

from application_crew.fetch.listing import detect_language, fetch_listing
from application_crew.runner.engine import StepContext, step
from application_crew.runner.states import RunStatus


@step(RunStatus.CREATED)
async def start(ctx: StepContext) -> RunStatus:
    if ctx.run.listing_text:
        return RunStatus.PARSING_LISTING
    return RunStatus.FETCHING_LISTING


@step(RunStatus.FETCHING_LISTING)
async def fetch(ctx: StepContext) -> RunStatus:
    run = ctx.run
    if not run.listing_url:
        ctx.emit("step_progress", "no URL given, waiting for pasted text")
        return RunStatus.WAITING_FOR_LISTING_TEXT

    result = await fetch_listing(run.listing_url)
    if not result.ok:
        ctx.emit("step_progress", result.error or "fetch failed")
        return RunStatus.WAITING_FOR_LISTING_TEXT

    run.listing_text = result.text
    run.state = run.state | {
        "fetch": {
            "job_posting": result.job_posting,
            "language": detect_language(result.text),
            **result.meta,
        }
    }
    ctx.session.add(run)
    ctx.session.commit()
    ctx.emit("step_progress", f"fetched {len(result.text)} characters")
    return RunStatus.PARSING_LISTING
