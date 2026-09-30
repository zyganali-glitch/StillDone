"""Focused tests for P-04.05 demo-resource isolation checks."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from stilldone.action_policy import (
    ValidatedActionContract,
    validate_action_contract,
)
from stilldone.demo_isolation import (
    CalendarOutOfScopeError,
    DemoIsolationError,
    DemoIsolationResult,
    DemoIsolationStatus,
    DemoIsolationTypeError,
    DemoResourceOutOfScopeError,
    DemoResourceScope,
    DemoScopeError,
    DemoScopeTypeError,
    DemoScopeValueError,
    MissingParentContainerError,
    TaskOutOfScopeError,
    UnexpectedParentContainerError,
    check_demo_resource_isolation,
    verify_demo_resource_isolation,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.lifecycle import MissionState, StepEvidenceState
from stilldone.domain.mission import MissionId


def test_exception_hierarchy() -> None:
    """Verify that all specific demo isolation errors inherit properly."""
    assert issubclass(DemoIsolationTypeError, (DemoIsolationError, TypeError))
    assert issubclass(DemoScopeError, DemoIsolationError)
    assert issubclass(DemoScopeTypeError, (DemoScopeError, TypeError))
    assert issubclass(DemoScopeValueError, (DemoScopeError, ValueError))
    assert issubclass(MissingParentContainerError, (DemoIsolationError, ValueError))
    assert issubclass(UnexpectedParentContainerError, (DemoIsolationError, ValueError))
    assert issubclass(DemoResourceOutOfScopeError, (DemoIsolationError, ValueError))
    assert issubclass(CalendarOutOfScopeError, DemoResourceOutOfScopeError)
    assert issubclass(TaskOutOfScopeError, DemoResourceOutOfScopeError)


# ===========================================================================
# Sentinels and Test Helpers
# ===========================================================================

_SENTINEL_CONFIG_CAL_ID = "sentinel-config-cal-primary-99999"
_SENTINEL_CANDIDATE_CAL_ID = "sentinel-candidate-cal-other-11111"
_SENTINEL_CONFIG_TASK_LIST_ID = "sentinel-config-tasklist-primary-88888"
_SENTINEL_CANDIDATE_TASK_LIST_ID = "sentinel-candidate-tasklist-other-22222"
_SENTINEL_EVENT_ID = "sentinel-event-res-44444"
_SENTINEL_TASK_ID = "sentinel-task-res-55555"


def _make_scope(
    calendar_id: str = _SENTINEL_CONFIG_CAL_ID,
    task_list_id: str = _SENTINEL_CONFIG_TASK_LIST_ID,
) -> DemoResourceScope:
    """Helper to construct a valid DemoResourceScope with sentinels."""
    return DemoResourceScope(calendar_id=calendar_id, task_list_id=task_list_id)


def _make_action(
    action_type: ActionType,
    *,
    resource_id: str = "res-default",
    parent_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> ValidatedActionContract:
    """Construct a ValidatedActionContract conforming to P-04.03 schemas."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    pid: str | None = None

    if action_type == ActionType.CALENDAR_READ:
        system = "google_calendar"
        rk = ResourceKind.CALENDAR_EVENT
        params: dict[str, Any] = {}
        pid = parent_id if parent_id is not None else _SENTINEL_CONFIG_CAL_ID
    elif action_type == ActionType.CALENDAR_UPDATE:
        system = "google_calendar"
        rk = ResourceKind.CALENDAR_EVENT
        params = parameters if parameters is not None else {"summary": "Updated Title"}
        pid = parent_id if parent_id is not None else _SENTINEL_CONFIG_CAL_ID
    elif action_type == ActionType.TASK_READ:
        system = "google_tasks"
        rk = ResourceKind.TASK
        params = {}
        pid = parent_id if parent_id is not None else _SENTINEL_CONFIG_TASK_LIST_ID
    elif action_type == ActionType.TASK_CREATE:
        system = "google_tasks"
        rk = ResourceKind.TASK_LIST
        params = parameters if parameters is not None else {"title": "New Task"}
        pid = parent_id  # Expected None by default
    elif action_type == ActionType.WEATHER_READ:
        system = "open_meteo"
        rk = ResourceKind.WEATHER_LOCATION
        params = {}
        pid = parent_id
    else:
        raise ValueError(f"Unsupported action_type in test helper: {action_type}")

    raw_action = ActionContract.create(
        mission_id=mid,
        action_id=aid,
        action_type=action_type,
        target=TargetIdentity(
            system=system,
            resource_kind=rk,
            resource_id=resource_id,
            parent_id=pid,
        ),
        parameters=params,
    )
    return validate_action_contract(raw_action)


# ===========================================================================
# 1-5. Scope Validation and Representation
# ===========================================================================


def test_scope_rejects_blank_calendar_id() -> None:
    """1. DemoResourceScope rejects empty calendar_id."""
    with pytest.raises(DemoScopeValueError, match="calendar_id must not be empty"):
        DemoResourceScope(calendar_id="", task_list_id=_SENTINEL_CONFIG_TASK_LIST_ID)


def test_scope_rejects_whitespace_only_calendar_id() -> None:
    """2. DemoResourceScope rejects whitespace-only calendar_id."""
    with pytest.raises(DemoScopeValueError, match="calendar_id must not be empty"):
        DemoResourceScope(calendar_id="   \t\n  ", task_list_id=_SENTINEL_CONFIG_TASK_LIST_ID)


def test_scope_rejects_blank_task_list_id() -> None:
    """3. DemoResourceScope rejects empty task_list_id."""
    with pytest.raises(DemoScopeValueError, match="task_list_id must not be empty"):
        DemoResourceScope(calendar_id=_SENTINEL_CONFIG_CAL_ID, task_list_id="")


def test_scope_rejects_whitespace_only_task_list_id() -> None:
    """4. DemoResourceScope rejects whitespace-only task_list_id."""
    with pytest.raises(DemoScopeValueError, match="task_list_id must not be empty"):
        DemoResourceScope(calendar_id=_SENTINEL_CONFIG_CAL_ID, task_list_id="   ")


def test_scope_repr_and_str_do_not_expose_raw_identifiers() -> None:
    """5. Scope repr/str do not expose either raw identifier."""
    scope = _make_scope()
    s_repr = repr(scope)
    s_str = str(scope)

    assert _SENTINEL_CONFIG_CAL_ID not in s_repr
    assert _SENTINEL_CONFIG_TASK_LIST_ID not in s_repr
    assert _SENTINEL_CONFIG_CAL_ID not in s_str
    assert _SENTINEL_CONFIG_TASK_LIST_ID not in s_str
    assert "***" in s_repr
    assert "***" in s_str


def test_scope_type_validation() -> None:
    """DemoResourceScope rejects non-string calendar_id and task_list_id."""
    with pytest.raises(DemoScopeTypeError, match="calendar_id must be a string"):
        DemoResourceScope(calendar_id=12345, task_list_id=_SENTINEL_CONFIG_TASK_LIST_ID)  # type: ignore[arg-type]

    with pytest.raises(DemoScopeTypeError, match="task_list_id must be a string"):
        DemoResourceScope(calendar_id=_SENTINEL_CONFIG_CAL_ID, task_list_id=None)  # type: ignore[arg-type]


# ===========================================================================
# 6. Rejection of Raw ActionContract and Non-Scope Types
# ===========================================================================


def test_isolation_api_rejects_raw_action_contract() -> None:
    """6. Isolation API rejects raw unvalidated ActionContract."""
    scope = _make_scope()
    raw_action = ActionContract.create(
        mission_id=MissionId.generate(),
        action_id=ActionId.generate(),
        action_type=ActionType.CALENDAR_READ,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-123",
            parent_id=_SENTINEL_CONFIG_CAL_ID,
        ),
        parameters={},
    )
    with pytest.raises(DemoIsolationTypeError, match="ValidatedActionContract instance"):
        verify_demo_resource_isolation(raw_action, scope)  # type: ignore[arg-type]


def test_isolation_api_rejects_non_scope_object() -> None:
    """Isolation API rejects non-DemoResourceScope objects."""
    action = _make_action(ActionType.CALENDAR_READ)
    with pytest.raises(DemoIsolationTypeError, match="DemoResourceScope instance"):
        verify_demo_resource_isolation(action, {"calendar_id": "cal-1"})  # type: ignore[arg-type]


# ===========================================================================
# 7-12. Calendar Actions (calendar.read, calendar.update)
# ===========================================================================


def test_calendar_read_with_exact_demo_parent_passes() -> None:
    """7. calendar.read with exact configured demo parent calendar passes."""
    scope = _make_scope()
    action = _make_action(
        ActionType.CALENDAR_READ,
        resource_id=_SENTINEL_EVENT_ID,
        parent_id=_SENTINEL_CONFIG_CAL_ID,
    )
    res = verify_demo_resource_isolation(action, scope)
    assert isinstance(res, DemoIsolationResult)
    assert res.status == DemoIsolationStatus.ISOLATED
    assert res.action_type == ActionType.CALENDAR_READ


def test_calendar_read_allows_varying_event_ids() -> None:
    """calendar.read allows different event IDs within the same demo calendar."""
    scope = _make_scope()
    for eid in ("evt-001", "evt-002", "evt-random-uuid"):
        action = _make_action(
            ActionType.CALENDAR_READ,
            resource_id=eid,
            parent_id=_SENTINEL_CONFIG_CAL_ID,
        )
        res = verify_demo_resource_isolation(action, scope)
        assert res.status == DemoIsolationStatus.ISOLATED


def test_calendar_read_with_missing_parent_id_fails() -> None:
    """8. calendar.read with missing parent_id fails closed."""
    scope = _make_scope()
    raw = ActionContract.create(
        mission_id=MissionId.generate(),
        action_id=ActionId.generate(),
        action_type=ActionType.CALENDAR_READ,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=_SENTINEL_EVENT_ID,
            parent_id=None,
        ),
        parameters={},
    )
    action = validate_action_contract(raw)
    with pytest.raises(MissingParentContainerError, match="requires a non-null target.parent_id"):
        verify_demo_resource_isolation(action, scope)


def test_calendar_read_with_wrong_parent_id_fails() -> None:
    """9. calendar.read with wrong parent_id fails closed."""
    scope = _make_scope()
    action = _make_action(
        ActionType.CALENDAR_READ,
        resource_id=_SENTINEL_EVENT_ID,
        parent_id=_SENTINEL_CANDIDATE_CAL_ID,
    )
    with pytest.raises(CalendarOutOfScopeError, match="target parent_id does not match"):
        verify_demo_resource_isolation(action, scope)


def test_calendar_update_with_exact_demo_parent_passes() -> None:
    """10. calendar.update with exact demo parent passes."""
    scope = _make_scope()
    action = _make_action(
        ActionType.CALENDAR_UPDATE,
        resource_id=_SENTINEL_EVENT_ID,
        parent_id=_SENTINEL_CONFIG_CAL_ID,
        parameters={"summary": "New Title"},
    )
    res = verify_demo_resource_isolation(action, scope)
    assert res.status == DemoIsolationStatus.ISOLATED
    assert res.action_type == ActionType.CALENDAR_UPDATE


def test_calendar_update_with_missing_parent_id_fails() -> None:
    """11. calendar.update with missing parent_id fails closed."""
    scope = _make_scope()
    raw = ActionContract.create(
        mission_id=MissionId.generate(),
        action_id=ActionId.generate(),
        action_type=ActionType.CALENDAR_UPDATE,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=_SENTINEL_EVENT_ID,
            parent_id=None,
        ),
        parameters={"summary": "New Title"},
    )
    action = validate_action_contract(raw)
    with pytest.raises(MissingParentContainerError, match="requires a non-null target.parent_id"):
        verify_demo_resource_isolation(action, scope)


def test_calendar_update_with_wrong_parent_id_fails() -> None:
    """12. calendar.update with wrong parent_id fails closed."""
    scope = _make_scope()
    action = _make_action(
        ActionType.CALENDAR_UPDATE,
        resource_id=_SENTINEL_EVENT_ID,
        parent_id=_SENTINEL_CANDIDATE_CAL_ID,
        parameters={"summary": "New Title"},
    )
    with pytest.raises(CalendarOutOfScopeError, match="target parent_id does not match"):
        verify_demo_resource_isolation(action, scope)


# ===========================================================================
# 13-18. Task Actions (task.read, task.create)
# ===========================================================================


def test_task_read_with_exact_demo_parent_passes() -> None:
    """13. task.read with exact configured demo task-list parent passes."""
    scope = _make_scope()
    action = _make_action(
        ActionType.TASK_READ,
        resource_id=_SENTINEL_TASK_ID,
        parent_id=_SENTINEL_CONFIG_TASK_LIST_ID,
    )
    res = verify_demo_resource_isolation(action, scope)
    assert res.status == DemoIsolationStatus.ISOLATED
    assert res.action_type == ActionType.TASK_READ


def test_task_read_allows_varying_task_ids() -> None:
    """task.read allows different task IDs within the demo task list."""
    scope = _make_scope()
    for tid in ("task-001", "task-002", "task-999"):
        action = _make_action(
            ActionType.TASK_READ,
            resource_id=tid,
            parent_id=_SENTINEL_CONFIG_TASK_LIST_ID,
        )
        res = verify_demo_resource_isolation(action, scope)
        assert res.status == DemoIsolationStatus.ISOLATED


def test_task_read_with_missing_parent_id_fails() -> None:
    """14. task.read with missing parent_id fails closed."""
    scope = _make_scope()
    raw = ActionContract.create(
        mission_id=MissionId.generate(),
        action_id=ActionId.generate(),
        action_type=ActionType.TASK_READ,
        target=TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id=_SENTINEL_TASK_ID,
            parent_id=None,
        ),
        parameters={},
    )
    action = validate_action_contract(raw)
    with pytest.raises(MissingParentContainerError, match="requires a non-null target.parent_id"):
        verify_demo_resource_isolation(action, scope)


def test_task_read_with_wrong_parent_id_fails() -> None:
    """15. task.read with wrong parent_id fails closed."""
    scope = _make_scope()
    action = _make_action(
        ActionType.TASK_READ,
        resource_id=_SENTINEL_TASK_ID,
        parent_id=_SENTINEL_CANDIDATE_TASK_LIST_ID,
    )
    with pytest.raises(TaskOutOfScopeError, match="target parent_id does not match"):
        verify_demo_resource_isolation(action, scope)


def test_task_create_targeting_exact_demo_task_list_passes() -> None:
    """16. task.create targeting exact configured demo task list passes."""
    scope = _make_scope()
    action = _make_action(
        ActionType.TASK_CREATE,
        resource_id=_SENTINEL_CONFIG_TASK_LIST_ID,
        parent_id=None,
        parameters={"title": "Pack backpacks"},
    )
    res = verify_demo_resource_isolation(action, scope)
    assert res.status == DemoIsolationStatus.ISOLATED
    assert res.action_type == ActionType.TASK_CREATE


def test_task_create_targeting_another_task_list_fails() -> None:
    """17. task.create targeting another task list fails closed."""
    scope = _make_scope()
    action = _make_action(
        ActionType.TASK_CREATE,
        resource_id=_SENTINEL_CANDIDATE_TASK_LIST_ID,
        parent_id=None,
        parameters={"title": "Pack backpacks"},
    )
    with pytest.raises(TaskOutOfScopeError, match="target resource_id does not match"):
        verify_demo_resource_isolation(action, scope)


def test_task_create_with_non_none_parent_id_fails() -> None:
    """18. task.create with non-None parent_id fails closed."""
    scope = _make_scope()
    raw = ActionContract.create(
        mission_id=MissionId.generate(),
        action_id=ActionId.generate(),
        action_type=ActionType.TASK_CREATE,
        target=TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK_LIST,
            resource_id=_SENTINEL_CONFIG_TASK_LIST_ID,
            parent_id="unexpected-parent-container",
        ),
        parameters={"title": "Pack backpacks"},
    )
    action = validate_action_contract(raw)
    with pytest.raises(
        UnexpectedParentContainerError, match="requires target.parent_id to be None"
    ):
        verify_demo_resource_isolation(action, scope)


# ===========================================================================
# 19. Weather Action (weather.read)
# ===========================================================================


def test_weather_read_returns_not_applicable() -> None:
    """19. weather.read returns explicit NOT_APPLICABLE safe result."""
    scope = _make_scope()
    action = _make_action(ActionType.WEATHER_READ, resource_id="loc-berlin", parent_id=None)
    res = verify_demo_resource_isolation(action, scope)
    assert res.status == DemoIsolationStatus.NOT_APPLICABLE
    assert res.action_type == ActionType.WEATHER_READ


# ===========================================================================
# 20-21. Exact Match Law: Case-Sensitivity and Near-Matches
# ===========================================================================


def test_exact_identifier_matching_is_case_sensitive() -> None:
    """20. Exact identifier matching is case-sensitive."""
    scope = _make_scope(calendar_id="cal-Demo-123", task_list_id="task-List-456")

    # Lowercase calendar fails
    a_cal_lower = _make_action(ActionType.CALENDAR_READ, parent_id="cal-demo-123")
    with pytest.raises(CalendarOutOfScopeError):
        verify_demo_resource_isolation(a_cal_lower, scope)

    # Uppercase calendar fails
    a_cal_upper = _make_action(ActionType.CALENDAR_READ, parent_id="CAL-DEMO-123")
    with pytest.raises(CalendarOutOfScopeError):
        verify_demo_resource_isolation(a_cal_upper, scope)

    # Lowercase task list fails
    a_task_lower = _make_action(ActionType.TASK_READ, parent_id="task-list-456")
    with pytest.raises(TaskOutOfScopeError):
        verify_demo_resource_isolation(a_task_lower, scope)

    # Exact case passes
    a_cal_exact = _make_action(ActionType.CALENDAR_READ, parent_id="cal-Demo-123")
    assert verify_demo_resource_isolation(a_cal_exact, scope).status == DemoIsolationStatus.ISOLATED


def test_prefix_suffix_substring_near_matches_fail() -> None:
    """21. Prefix, suffix, and substring near-matches fail."""
    scope = _make_scope(calendar_id="cal-123", task_list_id="list-456")

    near_matches_cal = [
        "cal-12",  # prefix
        "cal-1234",  # extension
        "al-123",  # suffix
        "-123",  # substring
        " cal-123",  # leading whitespace
        "cal-123 ",  # trailing whitespace
        "cal-123\n",  # newline
    ]
    for candidate in near_matches_cal:
        action = _make_action(ActionType.CALENDAR_READ, parent_id=candidate)
        with pytest.raises(CalendarOutOfScopeError):
            verify_demo_resource_isolation(action, scope)

    near_matches_list = [
        "list-45",  # prefix
        "list-4567",  # extension
        "ist-456",  # suffix
        "list-456 ",  # whitespace
    ]
    for candidate in near_matches_list:
        action = _make_action(ActionType.TASK_CREATE, resource_id=candidate, parent_id=None)
        with pytest.raises(TaskOutOfScopeError):
            verify_demo_resource_isolation(action, scope)


# ===========================================================================
# 22-24. Immutability and Determinism
# ===========================================================================


def test_caller_action_is_not_mutated() -> None:
    """22. Caller action is not mutated by isolation check."""
    scope = _make_scope()
    action = _make_action(
        ActionType.CALENDAR_UPDATE,
        resource_id=_SENTINEL_EVENT_ID,
        parent_id=_SENTINEL_CONFIG_CAL_ID,
        parameters={"summary": "Title"},
    )
    action_repr_before = repr(action)
    action_dict_before = {
        "mission_id": str(action.mission_id),
        "action_id": str(action.action_id),
        "action_type": action.action_type.value,
        "target": (
            action.target.system,
            action.target.resource_kind.value,
            action.target.resource_id,
            action.target.parent_id,
        ),
        "parameters": action.parameters.to_dict(),
    }

    res = verify_demo_resource_isolation(action, scope)
    assert res.status == DemoIsolationStatus.ISOLATED

    assert repr(action) == action_repr_before
    action_dict_after = {
        "mission_id": str(action.mission_id),
        "action_id": str(action.action_id),
        "action_type": action.action_type.value,
        "target": (
            action.target.system,
            action.target.resource_kind.value,
            action.target.resource_id,
            action.target.parent_id,
        ),
        "parameters": action.parameters.to_dict(),
    }
    assert action_dict_before == action_dict_after


def test_caller_scope_cannot_be_mutated() -> None:
    """23. Caller scope cannot be mutated after construction."""
    scope = _make_scope()
    with pytest.raises((AttributeError, TypeError)):
        scope.calendar_id = "cal-other"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        scope.task_list_id = "list-other"  # type: ignore[misc]


def test_isolation_result_is_deterministic() -> None:
    """24. Result is deterministic across repeated calls."""
    scope = _make_scope()
    action = _make_action(ActionType.CALENDAR_READ, parent_id=_SENTINEL_CONFIG_CAL_ID)

    r1 = verify_demo_resource_isolation(action, scope)
    r2 = verify_demo_resource_isolation(action, scope)
    r3 = check_demo_resource_isolation(action, scope)

    assert r1 == r2 == r3
    assert r1.status == r2.status == r3.status == DemoIsolationStatus.ISOLATED


# ===========================================================================
# 25-27. External Identifier Error Secrecy
# ===========================================================================


def test_mismatch_exceptions_do_not_contain_calendar_ids() -> None:
    """25. Mismatch exceptions do not contain configured or candidate calendar IDs."""
    scope = _make_scope()
    action = _make_action(
        ActionType.CALENDAR_READ,
        resource_id=_SENTINEL_EVENT_ID,
        parent_id=_SENTINEL_CANDIDATE_CAL_ID,
    )
    with pytest.raises(CalendarOutOfScopeError) as exc_info:
        verify_demo_resource_isolation(action, scope)

    exc = exc_info.value
    assert _SENTINEL_CONFIG_CAL_ID not in str(exc)
    assert _SENTINEL_CANDIDATE_CAL_ID not in str(exc)
    assert _SENTINEL_CONFIG_CAL_ID not in repr(exc)
    assert _SENTINEL_CANDIDATE_CAL_ID not in repr(exc)
    assert _SENTINEL_EVENT_ID not in str(exc)


def test_mismatch_exceptions_do_not_contain_task_list_ids() -> None:
    """26. Mismatch exceptions do not contain configured or candidate task-list IDs."""
    scope = _make_scope()

    # task.read parent mismatch
    a_read = _make_action(
        ActionType.TASK_READ,
        resource_id=_SENTINEL_TASK_ID,
        parent_id=_SENTINEL_CANDIDATE_TASK_LIST_ID,
    )
    with pytest.raises(TaskOutOfScopeError) as exc_info_read:
        verify_demo_resource_isolation(a_read, scope)

    exc_r = exc_info_read.value
    assert _SENTINEL_CONFIG_TASK_LIST_ID not in str(exc_r)
    assert _SENTINEL_CANDIDATE_TASK_LIST_ID not in str(exc_r)
    assert _SENTINEL_CONFIG_TASK_LIST_ID not in repr(exc_r)
    assert _SENTINEL_CANDIDATE_TASK_LIST_ID not in repr(exc_r)

    # task.create resource_id mismatch
    a_create = _make_action(
        ActionType.TASK_CREATE,
        resource_id=_SENTINEL_CANDIDATE_TASK_LIST_ID,
        parent_id=None,
    )
    with pytest.raises(TaskOutOfScopeError) as exc_info_create:
        verify_demo_resource_isolation(a_create, scope)

    exc_c = exc_info_create.value
    assert _SENTINEL_CONFIG_TASK_LIST_ID not in str(exc_c)
    assert _SENTINEL_CANDIDATE_TASK_LIST_ID not in str(exc_c)
    assert _SENTINEL_CONFIG_TASK_LIST_ID not in repr(exc_c)
    assert _SENTINEL_CANDIDATE_TASK_LIST_ID not in repr(exc_c)


def test_result_repr_and_str_do_not_leak_identifiers() -> None:
    """27. Result str and repr do not leak external identifiers."""
    scope = _make_scope()
    action = _make_action(ActionType.CALENDAR_READ, parent_id=_SENTINEL_CONFIG_CAL_ID)
    res = verify_demo_resource_isolation(action, scope)

    r_str = str(res)
    r_repr = repr(res)

    assert _SENTINEL_CONFIG_CAL_ID not in r_str
    assert _SENTINEL_CONFIG_CAL_ID not in r_repr
    assert _SENTINEL_CONFIG_TASK_LIST_ID not in r_str
    assert _SENTINEL_CONFIG_TASK_LIST_ID not in r_repr
    assert _SENTINEL_EVENT_ID not in r_str
    assert _SENTINEL_EVENT_ID not in r_repr


# ===========================================================================
# 28-29. Authority and Execution Separation
# ===========================================================================


def test_isolation_pass_does_not_imply_authority_or_execution() -> None:
    """28. Isolation PASS contains no authority/execution attributes."""
    scope = _make_scope()
    action = _make_action(ActionType.CALENDAR_READ)
    res = verify_demo_resource_isolation(action, scope)

    assert not hasattr(res, "is_authorized")
    assert not hasattr(res, "authority_class")
    assert not hasattr(res, "approval_grant")
    assert not hasattr(res, "execute")
    assert not hasattr(res, "verified")
    assert not hasattr(res, "ready")


def test_isolation_pass_cannot_produce_verified_or_ready() -> None:
    """29. Isolation PASS cannot produce VERIFIED or READY state."""
    scope = _make_scope()
    action = _make_action(ActionType.CALENDAR_READ)
    res = verify_demo_resource_isolation(action, scope)

    # Result type cannot be compared to or equal StepEvidenceState or MissionState
    res_any: Any = res
    assert res_any != StepEvidenceState.VERIFIED
    assert res_any != MissionState.READY
    status_any: Any = res.status
    assert status_any != StepEvidenceState.VERIFIED
    assert status_any != MissionState.READY


# ===========================================================================
# 30. Zero Provider/Network Imports
# ===========================================================================


def test_zero_provider_or_network_imports() -> None:
    """30. Verify no Google SDKs, AWS SDKs, MCP, or network packages are imported."""
    import stilldone.demo_isolation as demo_mod

    assert demo_mod is not None

    # Inspect module globals and imports
    for mod_name in sys.modules:
        assert not mod_name.startswith("google.colab")
        assert not mod_name.startswith("googleapiclient")
        assert not mod_name.startswith("google.auth")
        assert not mod_name.startswith("boto3")
        assert not mod_name.startswith("botocore")
        assert not mod_name.startswith("mcp")
        assert not mod_name.startswith("httpx")
        assert not mod_name.startswith("requests")
        assert not mod_name.startswith("urllib3")
