"""Pipeline view of a run: one entry per stage with its state, for the status stepper."""

from __future__ import annotations

from application_crew.runner.states import RunStatus as S

# (key, label, working statuses, gate status)
STAGES: list[tuple[str, str, set[S], S | None]] = [
    ("fetch", "Fetch listing", {S.CREATED, S.FETCHING_LISTING}, S.WAITING_FOR_LISTING_TEXT),
    ("parse", "Read listing", {S.PARSING_LISTING}, None),
    ("requirements", "Your requirements", {S.CHECKING_REQUIREMENTS}, S.STOPPED_BY_REQUIREMENTS),
    ("match", "Assess fit", {S.MATCHING}, S.WAITING_FOR_APPLY_DECISION),
    ("author", "Write", {S.AUTHORING}, None),
    ("review", "Review loop", {S.REVIEWING}, None),
    ("final", "Your review", set(), S.WAITING_FOR_FINAL_REVIEW),
    ("deliver", "Deliver", {S.DELIVERING}, None),
]

GATE_PROMPTS = {
    S.WAITING_FOR_LISTING_TEXT: "Paste the listing text",
    S.STOPPED_BY_REQUIREMENTS: "A must-have isn't met: decide",
    S.WAITING_FOR_APPLY_DECISION: "Decide whether to apply",
    S.WAITING_FOR_FINAL_REVIEW: "Review and approve the documents",
}


def _stage_of(status: S) -> int:
    for i, (_, _, working, gate) in enumerate(STAGES):
        if status in working or status == gate:
            return i
    return len(STAGES) - 1


def pipeline(status: S, previous: str | None, drafts: int = 0) -> list[dict]:
    """Stage states: done | active | waiting | failed | declined | pending."""
    if status == S.DONE:
        return [
            {"key": k, "label": label, "state": "done", "hint": ""} for k, label, _, _ in STAGES
        ]
    if status in (S.FAILED, S.DECLINED):
        at = _stage_of(S(previous)) if previous in S._value2member_map_ else 0
        state = "failed" if status == S.FAILED else "declined"
    else:
        at = _stage_of(status)
        state = "waiting" if status in GATE_PROMPTS else "active"

    out = []
    for i, (key, label, _, _) in enumerate(STAGES):
        if i < at:
            s, hint = "done", ""
        elif i == at:
            s, hint = state, GATE_PROMPTS.get(status, "")
        else:
            s, hint = "pending", ""
        if key in ("author", "review") and drafts and s != "pending":
            hint = hint or f"draft {drafts}"
        out.append({"key": key, "label": label, "state": s, "hint": hint})
    return out
