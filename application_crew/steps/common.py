"""Helpers shared by pipeline steps."""

from __future__ import annotations

from application_crew.db import CV
from application_crew.domain.models import ParsedCV
from application_crew.runner.engine import StepContext


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
