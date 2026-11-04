"""CV jobs.

Parsing: Claude extraction -> fact IDs -> completeness checks -> confirmation gate.
After confirmation: one small call suggests alternative roles for the job search.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlmodel import Session

from mappe.checks.completeness import check_cv
from mappe.config import Settings
from mappe.db import CV, get_engine
from mappe.domain.extraction import ExtractedCV, to_parsed_cv
from mappe.domain.match import render_cv
from mappe.domain.models import ParsedCV
from mappe.domain.roles import RoleSuggestions
from mappe.domain.summary import experience_months
from mappe.llm import client
from mappe.llm.client import Block, instructions
from mappe.llm.pricing import cost_usd
from mappe.runner import activity
from mappe.runner.engine import cv_job
from mappe.runner.states import CVStatus
from mappe.search.queries import filter_roles, suggest_titles

log = logging.getLogger(__name__)


@cv_job
async def process_cv(cv_id: int, settings: Settings) -> None:
    """The engine's CV job: parse, or suggest roles once the CV is confirmed."""
    with Session(get_engine()) as session:
        cv = session.get(CV, cv_id)
        if cv is None:
            return
        status, roles_status = cv.status, cv.roles_status
    if status == CVStatus.PARSING:
        await parse_cv(cv_id, settings)
    elif status == CVStatus.CONFIRMED and roles_status == "suggesting":
        await suggest_roles(cv_id, settings)


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
                # One call per CV: nothing is read again, so no cache markers.
                blocks=[Block(f"<cv>\n{cv.markdown}\n</cv>"), instructions("parse_cv")],
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


def roles_task(cv: ParsedCV) -> str:
    years = round(experience_months(cv) / 12, 1)
    titles = "\n".join(f"- {t}" for t in suggest_titles(cv)) or "- (none)"
    return (
        f"Total professional experience (computed): {years} years.\n"
        f"The search already uses these titles; don't repeat them:\n{titles}\n\n"
        "Suggest alternative roles for the CV above."
    )


async def suggest_roles(cv_id: int, settings: Settings) -> None:
    with Session(get_engine()) as session:
        cv = session.get(CV, cv_id)
        if cv is None or cv.parsed is None or cv.roles_status != "suggesting":
            return
        activity.update(
            "Suggesting other roles", phase="suggesting_roles", title=f"CV · {cv.label}"
        )
        parsed = ParsedCV.model_validate(cv.parsed)
        try:
            result, usage = await client.structured(
                settings,
                step="suggest_roles",
                output=RoleSuggestions,
                # One call per confirmed CV: nothing is read again, so no cache markers.
                blocks=[Block(f"<cv>\n{render_cv(parsed)}\n</cv>"), instructions("suggest_roles")],
                task=roles_task(parsed),
            )
        except Exception as exc:  # noqa: BLE001 - shown on the CV page, which can retry
            log.exception("CV %s: role suggestions failed", cv_id)
            cv.roles_status, cv.roles_error = "failed", str(exc)
        else:
            session.refresh(cv)  # the CV may have been parsed again meanwhile
            cv.cost_usd += cost_usd(settings.llm_for("suggest_roles").model, usage)
            if cv.status == CVStatus.CONFIRMED and cv.roles_status == "suggesting":
                activity.update("Checking suggestions against your CV (Python)")
                cv.roles = filter_roles(parsed, result.roles)
                cv.roles_status, cv.roles_error = "done", None
        cv.updated_at = datetime.now(UTC)
        session.add(cv)
        session.commit()
