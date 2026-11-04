"""Helpers shared by pipeline steps."""

from __future__ import annotations

from mappe.db import CV
from mappe.domain.match import render_cv, render_listing
from mappe.domain.models import ParsedCV, ParsedListing
from mappe.llm.client import Block
from mappe.runner.engine import StepContext


def run_cv(ctx: StepContext) -> ParsedCV:
    """The CV snapshot this run works with (taken when the run started)."""
    run = ctx.run
    if "cv" not in run.state:
        cv = ctx.session.get(CV, run.cv_id)
        if cv is None or cv.parsed is None:
            raise RuntimeError("the run's CV has no parsed data")
        run.state = run.state | {"cv": cv.parsed}
        ctx.session.add(run)
        ctx.session.commit()
    return ParsedCV.model_validate(run.state["cv"])


def shared_blocks(cv: ParsedCV, listing: ParsedListing, cache: bool = True) -> list[Block]:
    """CV and listing, rendered byte-identically for every step.

    ``cache`` for steps that are called again with the same schema (reworks, further
    review rounds). The CV gets its own breakpoint, so the same step of other runs with
    the same CV (several URLs at once) can read it too.
    """
    return [
        Block(f"<cv>\n{render_cv(cv)}\n</cv>", cache=cache),
        Block(f"<listing>\n{render_listing(listing)}\n</listing>", cache=cache),
    ]
