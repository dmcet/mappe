"""CV parsing flow: Claude extraction -> fact IDs -> completeness checks -> confirmation gate."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlmodel import Session

from application_crew.checks.completeness import check_cv
from application_crew.config import Settings
from application_crew.db import CV, get_engine
from application_crew.domain.extraction import ExtractedCV, to_parsed_cv
from application_crew.llm import client
from application_crew.llm.pricing import cost_usd
from application_crew.runner import activity
from application_crew.runner.engine import cv_job
from application_crew.runner.states import CVStatus

log = logging.getLogger(__name__)


@cv_job
async def parse_cv(cv_id: int, settings: Settings) -> None:
    with Session(get_engine()) as session:
        cv = session.get(CV, cv_id)
        if cv is None or cv.status != CVStatus.PARSING:
            return
        activity.update("Reading your CV", phase="parsing", title=f"CV · {cv.label}")
        try:
            extracted, usage = await client.structured(
                settings,
                step="parse_cv",
                output=ExtractedCV,
                stable_context=f"<cv>\n{cv.markdown}\n</cv>",
                task="Extract the CV above.",
            )
        except Exception as exc:  # noqa: BLE001 - shown to the user, who can retry
            log.exception("CV %s: parsing failed", cv_id)
            cv.status = CVStatus.FAILED
            cv.error = str(exc)
        else:
            parsed = to_parsed_cv(extracted)
            cv.parsed = parsed.model_dump(mode="json")
            activity.update("Checking completeness (Python)")
            cv.warnings = check_cv(parsed)
            cv.cost_usd += cost_usd(settings.llm_for("parse_cv").model, usage)
            cv.status = CVStatus.WAITING_FOR_CONFIRMATION
            cv.error = None
        cv.updated_at = datetime.now(UTC)
        session.add(cv)
        session.commit()
