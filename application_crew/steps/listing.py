"""Listing steps: fetch, parse (Claude + JSON-LD), check user requirements."""

from __future__ import annotations

from application_crew.checks.requirements import (
    FUZZY_KINDS,
    check_requirements,
    failed_must_haves,
)
from application_crew.domain.listing import ExtractedListing, FuzzyCheck, merge_listing
from application_crew.domain.models import ParsedListing, Requirement
from application_crew.fetch.listing import detect_language, fetch_listing
from application_crew.llm import client
from application_crew.llm.pricing import cost_usd
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
        stable_context=f"<listing>\n{text}\n</listing>",
        task=task,
    )
    listing = merge_listing(extracted, job_posting, language=detect_language(text))

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
