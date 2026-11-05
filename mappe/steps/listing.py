"""Listing steps: fetch, parse (Claude + JSON-LD), check user requirements."""

from __future__ import annotations

from mappe.checks.requirements import (
    FUZZY_KINDS,
    check_requirements,
    failed_must_haves,
)
from mappe.domain.listing import ExtractedListing, FuzzyCheck, merge_listing
from mappe.domain.models import ParsedListing, Requirement
from mappe.fetch.listing import detect_language, fetch_listing
from mappe.llm import client
from mappe.llm.client import Block, instructions
from mappe.llm.pricing import cost_usd
from mappe.runner import aborts, activity
from mappe.runner.engine import StepContext, step
from mappe.runner.states import RunStatus
from mappe.steps.common import run_cv


@step(RunStatus.CREATED)
async def start(ctx: StepContext) -> RunStatus:
    # Snapshot the parsed CV: re-parsing the CV later must not change this run's fact IDs.
    run_cv(ctx)
    if ctx.run.listing_text:
        return RunStatus.PARSING_LISTING
    return RunStatus.FETCHING_LISTING


@step(RunStatus.FETCHING_LISTING)
async def fetch(ctx: StepContext) -> RunStatus:
    run = ctx.run
    if not run.listing_url:
        ctx.emit("step_progress", "no URL given, waiting for pasted text")
        return RunStatus.WAITING_FOR_LISTING_TEXT

    activity.update(f"Downloading {run.listing_url}")
    cfg = ctx.settings.fetch
    work = fetch_listing(
        run.listing_url, timeout=cfg.timeout_seconds, max_bytes=int(cfg.max_mb * 1_000_000)
    )
    result, aborted = await aborts.abortable(run.id, work)  # type: ignore[arg-type]
    if aborted or result is None:
        ctx.emit("step_progress", "download aborted by you")
        return RunStatus.WAITING_FOR_LISTING_TEXT
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


MAX_LISTING_CHARS = 60_000


@step(RunStatus.PARSING_LISTING)
async def parse(ctx: StepContext) -> RunStatus:
    run = ctx.run
    text = run.listing_text or ""
    if len(text) > MAX_LISTING_CHARS:
        ctx.emit(
            "step_progress",
            f"listing is {len(text):,} characters; only the first {MAX_LISTING_CHARS:,} are used",
        )
        text = text[:MAX_LISTING_CHARS]

    requirements = [Requirement.model_validate(r) for r in run.requirements]
    fuzzy = [(i, r) for i, r in enumerate(requirements) if r.kind in FUZZY_KINDS]
    if fuzzy:
        lines = "\n".join(f"{i}. {r.value}" for i, r in fuzzy)
        task = f"Extract the listing above. Candidate requirements to check:\n{lines}"
    else:
        task = "Extract the listing above. There are no candidate requirements to check."

    fetch_state = run.state.get("fetch", {})
    job_posting = fetch_state.get("job_posting")
    extracted, usage = await client.structured(
        ctx.settings,
        step="parse_listing",
        output=ExtractedListing,
        # One call per listing: nothing is read again, so no cache markers.
        blocks=[Block(f"<listing>\n{text}\n</listing>"), instructions("parse_listing")],
        task=task,
    )
    contact_text = text
    if ctx.settings.demo:
        from mappe.llm.demo import DEMO_CONTACT_LINE

        contact_text = f"{text}\n{DEMO_CONTACT_LINE}"
    listing = merge_listing(
        extracted, job_posting, language=detect_language(text), text=contact_text
    )

    cost = cost_usd(ctx.settings.llm_for("parse_listing").model, usage)
    run.cost_usd += cost
    run.state = run.state | {
        "listing": listing.model_dump(mode="json"),
        "fuzzy_checks": [c.model_dump(mode="json") for c in extracted.requirement_checks],
    }
    ctx.session.add(run)
    ctx.session.commit()
    ctx.emit("usage", f"parse_listing ≈ ${cost:.4f}", **usage.__dict__)
    if not listing.responsibilities and not listing.required_skills:
        ctx.emit(
            "step_progress",
            "the text contains no responsibilities or skills, so it's probably not the listing "
            "(cookie banner, job index or login page); waiting for pasted text",
        )
        return RunStatus.WAITING_FOR_LISTING_TEXT
    title = " · ".join(x for x in (listing.title, listing.company) if x) or "listing"
    ctx.emit("step_progress", f"parsed {title} ({listing.language})")
    return RunStatus.CHECKING_REQUIREMENTS


@step(RunStatus.CHECKING_REQUIREMENTS)
async def check(ctx: StepContext) -> RunStatus:
    run = ctx.run
    requirements = [Requirement.model_validate(r) for r in run.requirements]
    listing = ParsedListing.model_validate(run.state["listing"])
    fuzzy_checks = [FuzzyCheck.model_validate(c) for c in run.state.get("fuzzy_checks", [])]
    activity.update(f"Checking {len(requirements)} requirement(s) (Python)")
    results = check_requirements(requirements, listing, run.listing_text or "", fuzzy_checks)

    run.state = run.state | {"requirement_results": [r.model_dump(mode="json") for r in results]}
    ctx.session.add(run)
    ctx.session.commit()

    failed = failed_must_haves(results)
    counts = {o: sum(r.outcome == o for r in results) for o in ("passed", "failed", "unknown")}
    ctx.emit("step_progress", ", ".join(f"{n} {o}" for o, n in counts.items()))
    if failed:
        names = "; ".join(f"{r.requirement.kind}: {r.note}" for r in failed)
        ctx.emit("step_progress", f"must-have requirement failed: {names}")
        return RunStatus.STOPPED_BY_REQUIREMENTS
    return RunStatus.MATCHING
