"""Matching: Python skill analysis + Claude assessment -> apply decision gate."""

from __future__ import annotations

from application_crew.checks.skills import analyze_skills
from application_crew.domain.match import (
    MatchResult,
    render_analysis,
    validate_fact_ids,
)
from application_crew.domain.models import ParsedListing, RequirementResult
from application_crew.llm import client
from application_crew.llm.client import Block, instructions
from application_crew.llm.pricing import cost_usd
from application_crew.runner import activity
from application_crew.runner.engine import StepContext, step
from application_crew.runner.states import RunStatus
from application_crew.steps.common import run_cv, shared_blocks


@step(RunStatus.MATCHING)
async def match(ctx: StepContext) -> RunStatus:
    run = ctx.run
    cv = run_cv(ctx)
    listing = ParsedListing.model_validate(run.state["listing"])
    results = [
        RequirementResult.model_validate(r) for r in run.state.get("requirement_results", [])
    ]

    activity.update("Comparing your skills with the listing (Python)")
    analysis = analyze_skills(cv, listing)
    ctx.emit(
        "step_progress",
        f"required skills: {analysis.required_matched} matched, {analysis.required_related} "
        f"related of {analysis.required_total}; {analysis.total_years} years of experience",
    )

    result, usage = await client.structured(
        ctx.settings,
        step="match",
        output=MatchResult,
        blocks=[
            # Called once per run, and no other step shares its schema: no cache markers.
            *shared_blocks(cv, listing, cache=False),
            instructions("match"),
            Block(f"<analysis>\n{render_analysis(analysis, results)}\n</analysis>"),
        ],
        task="Assess whether the candidate should apply for this position.",
    )
    result, warnings = validate_fact_ids(result, cv)
    for warning in warnings:
        ctx.emit("step_progress", warning)

    cost = cost_usd(ctx.settings.llm_for("match").model, usage)
    run.cost_usd += cost
    run.state = run.state | {
        "analysis": analysis.to_dict(),
        "match": result.model_dump(mode="json"),
        "match_warnings": warnings,
        # Preselection for the decision page; the user decides.
        "cover_letter_suggested": listing.cover_letter_requested or listing.language == "de",
    }
    ctx.session.add(run)
    ctx.session.commit()
    ctx.emit("usage", f"match ≈ ${cost:.4f}", **usage.__dict__)
    ctx.emit("step_progress", f"verdict: {result.verdict} ({result.score}/100)")
    return RunStatus.WAITING_FOR_APPLY_DECISION
