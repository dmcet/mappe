from application_crew.runner.states import (
    TRANSITIONS,
    USER_GATES,
    WORKING,
    RunStatus,
    can_transition,
)


def test_happy_path_is_allowed():
    path = [
        RunStatus.CREATED,
        RunStatus.FETCHING_LISTING,
        RunStatus.PARSING_LISTING,
        RunStatus.CHECKING_REQUIREMENTS,
        RunStatus.MATCHING,
        RunStatus.WAITING_FOR_APPLY_DECISION,
        RunStatus.AUTHORING,
        RunStatus.REVIEWING,
        RunStatus.AUTHORING,
        RunStatus.REVIEWING,
        RunStatus.WAITING_FOR_FINAL_REVIEW,
        RunStatus.DELIVERING,
        RunStatus.DONE,
    ]
    for current, target in zip(path, path[1:], strict=False):
        assert can_transition(current, target), f"{current} -> {target}"


def test_skipping_user_gates_is_forbidden():
    assert not can_transition(RunStatus.MATCHING, RunStatus.AUTHORING)
    assert not can_transition(RunStatus.REVIEWING, RunStatus.DELIVERING)


def test_failed_reachable_from_non_terminal_only():
    assert can_transition(RunStatus.REVIEWING, RunStatus.FAILED)
    assert not can_transition(RunStatus.DONE, RunStatus.FAILED)


def test_every_non_terminal_status_has_transitions():
    for status in WORKING | USER_GATES:
        assert TRANSITIONS.get(status), status
