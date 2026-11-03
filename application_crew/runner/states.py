"""Run and CV status values and the allowed transitions between them."""

from __future__ import annotations

from enum import StrEnum


class CVStatus(StrEnum):
    PARSING = "parsing"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class RunStatus(StrEnum):
    CREATED = "created"
    FETCHING_LISTING = "fetching_listing"
    WAITING_FOR_LISTING_TEXT = "waiting_for_listing_text"
    PARSING_LISTING = "parsing_listing"
    CHECKING_REQUIREMENTS = "checking_requirements"
    STOPPED_BY_REQUIREMENTS = "stopped_by_requirements"
    MATCHING = "matching"
    WAITING_FOR_APPLY_DECISION = "waiting_for_apply_decision"
    DECLINED = "declined"
    AUTHORING = "authoring"
    REVIEWING = "reviewing"
    WAITING_FOR_FINAL_REVIEW = "waiting_for_final_review"
    DELIVERING = "delivering"
    DONE = "done"
    FAILED = "failed"


# Statuses in which the runner does work. On startup, runs in these statuses are re-queued.
WORKING: frozenset[RunStatus] = frozenset(
    {
        RunStatus.CREATED,
        RunStatus.FETCHING_LISTING,
        RunStatus.PARSING_LISTING,
        RunStatus.CHECKING_REQUIREMENTS,
        RunStatus.MATCHING,
        RunStatus.AUTHORING,
        RunStatus.REVIEWING,
        RunStatus.DELIVERING,
    }
)

# Statuses that wait for the user. The UI resumes them via an explicit action.
USER_GATES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.WAITING_FOR_LISTING_TEXT,
        RunStatus.STOPPED_BY_REQUIREMENTS,
        RunStatus.WAITING_FOR_APPLY_DECISION,
        RunStatus.WAITING_FOR_FINAL_REVIEW,
    }
)

TERMINAL: frozenset[RunStatus] = frozenset({RunStatus.DONE, RunStatus.DECLINED, RunStatus.FAILED})

TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.FETCHING_LISTING, RunStatus.PARSING_LISTING}),
    RunStatus.FETCHING_LISTING: frozenset(
        {RunStatus.PARSING_LISTING, RunStatus.WAITING_FOR_LISTING_TEXT}
    ),
    RunStatus.WAITING_FOR_LISTING_TEXT: frozenset({RunStatus.PARSING_LISTING}),
    RunStatus.PARSING_LISTING: frozenset({RunStatus.CHECKING_REQUIREMENTS}),
    RunStatus.CHECKING_REQUIREMENTS: frozenset(
        {RunStatus.MATCHING, RunStatus.STOPPED_BY_REQUIREMENTS}
    ),
    RunStatus.STOPPED_BY_REQUIREMENTS: frozenset({RunStatus.MATCHING, RunStatus.DECLINED}),
    RunStatus.MATCHING: frozenset({RunStatus.WAITING_FOR_APPLY_DECISION}),
    RunStatus.WAITING_FOR_APPLY_DECISION: frozenset({RunStatus.AUTHORING, RunStatus.DECLINED}),
    RunStatus.AUTHORING: frozenset({RunStatus.REVIEWING}),
    RunStatus.REVIEWING: frozenset({RunStatus.AUTHORING, RunStatus.WAITING_FOR_FINAL_REVIEW}),
    RunStatus.WAITING_FOR_FINAL_REVIEW: frozenset({RunStatus.DELIVERING}),
    RunStatus.DELIVERING: frozenset({RunStatus.DONE}),
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    if target is RunStatus.FAILED:
        return current not in TERMINAL
    return target in TRANSITIONS.get(current, frozenset())
