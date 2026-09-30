"""Focused tests for P-04.03 closed-world action allowlist and parameter validation."""

from __future__ import annotations

import ast
import pathlib
from typing import Any

import pytest

from stilldone.action_policy import (
    ACTION_POLICIES,
    MAX_PARAM_STRING_LENGTH,
    ActionParameterPolicyError,
    ActionPolicy,
    ActionPolicyError,
    ActionPolicyTypeError,
    ActionTargetCompatibilityError,
    EmptyParameterSetError,
    InvalidParameterTypeError,
    InvalidParameterValueError,
    MissingRequiredParameterError,
    OversizedParameterError,
    UnknownParameterError,
    UnsupportedActionTypeError,
    ValidatedActionContract,
    validate_action_contract,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.mission import MissionId

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    action_type: ActionType,
    system: str,
    resource_kind: ResourceKind,
    resource_id: str = "res-1",
    parent_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> ActionContract:
    """Helper to create an ActionContract with explicit parameters."""
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=action_type,
        target=TargetIdentity(
            system=system,
            resource_kind=resource_kind,
            resource_id=resource_id,
            parent_id=parent_id,
        ),
        parameters=parameters or {},
    )


# ---------------------------------------------------------------------------
# 1 & 2: Policy Table Cardinality & Exact Closed-World Mapping
# ---------------------------------------------------------------------------


def test_action_policy_table_exact_cardinality_and_coverage() -> None:
    """Requirement 1 & 2: All 5 canonical actions have exactly one policy entry; no extras."""
    assert len(ACTION_POLICIES) == 5
    assert set(ACTION_POLICIES.keys()) == set(ActionType)

    canonical_members = {
        ActionType.CALENDAR_READ,
        ActionType.CALENDAR_UPDATE,
        ActionType.TASK_READ,
        ActionType.TASK_CREATE,
        ActionType.WEATHER_READ,
    }
    assert set(ACTION_POLICIES.keys()) == canonical_members

    for at in ActionType:
        entry = ACTION_POLICIES[at]
        assert isinstance(entry, ActionPolicy)
        assert entry.action_type == at


def test_action_policy_model_rejects_inconsistent_definitions() -> None:
    """ActionPolicy model self-validates consistency upon construction."""
    with pytest.raises(TypeError, match="action_type must be an ActionType instance"):
        ActionPolicy(
            action_type="calendar.read",  # type: ignore[arg-type]
            allowed_system="google_calendar",
            allowed_resource_kind=ResourceKind.CALENDAR_EVENT,
            supported_parameters=frozenset(),
            required_parameters=frozenset(),
        )

    with pytest.raises(ValueError, match="allowed_system must be a non-empty string"):
        ActionPolicy(
            action_type=ActionType.CALENDAR_READ,
            allowed_system="   ",
            allowed_resource_kind=ResourceKind.CALENDAR_EVENT,
            supported_parameters=frozenset(),
            required_parameters=frozenset(),
        )

    with pytest.raises(TypeError, match="allowed_resource_kind must be a ResourceKind instance"):
        ActionPolicy(
            action_type=ActionType.CALENDAR_READ,
            allowed_system="google_calendar",
            allowed_resource_kind="calendar_event",  # type: ignore[arg-type]
            supported_parameters=frozenset(),
            required_parameters=frozenset(),
        )

    with pytest.raises(ValueError, match="required_parameters must be a subset"):
        ActionPolicy(
            action_type=ActionType.TASK_CREATE,
            allowed_system="google_tasks",
            allowed_resource_kind=ResourceKind.TASK_LIST,
            supported_parameters=frozenset({"title"}),
            required_parameters=frozenset({"title", "nonexistent"}),
        )


# ---------------------------------------------------------------------------
# 3: Every Valid Action/Target Pair Passes
# ---------------------------------------------------------------------------


def test_every_valid_action_target_pair_passes() -> None:
    """Requirement 3: Each canonical action passes with supported target & valid params."""
    valid_cases = [
        # calendar.read: google_calendar / CALENDAR_EVENT / no params
        _make_action(
            ActionType.CALENDAR_READ,
            "google_calendar",
            ResourceKind.CALENDAR_EVENT,
            "evt-101",
        ),
        # calendar.update: google_calendar / CALENDAR_EVENT / summary
        _make_action(
            ActionType.CALENDAR_UPDATE,
            "google_calendar",
            ResourceKind.CALENDAR_EVENT,
            "evt-102",
            parameters={"summary": "Team Sync"},
        ),
        # task.read: google_tasks / TASK / no params
        _make_action(
            ActionType.TASK_READ,
            "google_tasks",
            ResourceKind.TASK,
            "task-201",
        ),
        # task.create: google_tasks / TASK_LIST / title
        _make_action(
            ActionType.TASK_CREATE,
            "google_tasks",
            ResourceKind.TASK_LIST,
            "StillDone Demo",
            parameters={"title": "Pack umbrella"},
        ),
        # weather.read: open_meteo / WEATHER_LOCATION / no params
        _make_action(
            ActionType.WEATHER_READ,
            "open_meteo",
            ResourceKind.WEATHER_LOCATION,
            "loc-301",
        ),
    ]

    for action in valid_cases:
        validated = validate_action_contract(action)
        assert isinstance(validated, ValidatedActionContract)
        assert validated.action == action
        assert validated.action_type == action.action_type
        assert validated.target == action.target
        assert validated.parameters == action.parameters
        assert validated.action_id == action.action_id
        assert validated.mission_id == action.mission_id


# ---------------------------------------------------------------------------
# 4 & 5: Target Compatibility Matrix (Wrong ResourceKind & Wrong System)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action_type", "correct_system", "wrong_kind"),
    [
        (ActionType.CALENDAR_READ, "google_calendar", ResourceKind.TASK),
        (ActionType.CALENDAR_READ, "google_calendar", ResourceKind.TASK_LIST),
        (ActionType.CALENDAR_READ, "google_calendar", ResourceKind.WEATHER_LOCATION),
        (ActionType.CALENDAR_UPDATE, "google_calendar", ResourceKind.TASK),
        (ActionType.CALENDAR_UPDATE, "google_calendar", ResourceKind.TASK_LIST),
        (ActionType.CALENDAR_UPDATE, "google_calendar", ResourceKind.WEATHER_LOCATION),
        (ActionType.TASK_READ, "google_tasks", ResourceKind.CALENDAR_EVENT),
        (ActionType.TASK_READ, "google_tasks", ResourceKind.TASK_LIST),
        (ActionType.TASK_READ, "google_tasks", ResourceKind.WEATHER_LOCATION),
        (ActionType.TASK_CREATE, "google_tasks", ResourceKind.CALENDAR_EVENT),
        (ActionType.TASK_CREATE, "google_tasks", ResourceKind.TASK),
        (ActionType.TASK_CREATE, "google_tasks", ResourceKind.WEATHER_LOCATION),
        (ActionType.WEATHER_READ, "open_meteo", ResourceKind.CALENDAR_EVENT),
        (ActionType.WEATHER_READ, "open_meteo", ResourceKind.TASK),
        (ActionType.WEATHER_READ, "open_meteo", ResourceKind.TASK_LIST),
    ],
)
def test_wrong_resource_kind_for_action_fails(
    action_type: ActionType, correct_system: str, wrong_kind: ResourceKind
) -> None:
    """Requirement 4: Incompatible ResourceKind fails closed."""
    params: dict[str, Any] = {}
    if action_type == ActionType.CALENDAR_UPDATE:
        params = {"summary": "Sample"}
    elif action_type == ActionType.TASK_CREATE:
        params = {"title": "Sample"}

    act = _make_action(action_type, correct_system, wrong_kind, parameters=params)
    with pytest.raises(ActionTargetCompatibilityError, match="requires target resource kind"):
        validate_action_contract(act)


@pytest.mark.parametrize(
    ("action_type", "wrong_system", "correct_kind"),
    [
        (ActionType.CALENDAR_READ, "google_tasks", ResourceKind.CALENDAR_EVENT),
        (ActionType.CALENDAR_READ, "open_meteo", ResourceKind.CALENDAR_EVENT),
        (ActionType.CALENDAR_READ, "other_calendar", ResourceKind.CALENDAR_EVENT),
        (ActionType.CALENDAR_UPDATE, "google_tasks", ResourceKind.CALENDAR_EVENT),
        (ActionType.CALENDAR_UPDATE, "aws_eventbridge", ResourceKind.CALENDAR_EVENT),
        (ActionType.TASK_READ, "google_calendar", ResourceKind.TASK),
        (ActionType.TASK_READ, "todoist", ResourceKind.TASK),
        (ActionType.TASK_CREATE, "google_calendar", ResourceKind.TASK_LIST),
        (ActionType.TASK_CREATE, "jira", ResourceKind.TASK_LIST),
        (ActionType.WEATHER_READ, "google_weather", ResourceKind.WEATHER_LOCATION),
        (ActionType.WEATHER_READ, "accuweather", ResourceKind.WEATHER_LOCATION),
    ],
)
def test_unsupported_system_namespace_fails(
    action_type: ActionType, wrong_system: str, correct_kind: ResourceKind
) -> None:
    """Requirement 5: Unsupported system namespace fails closed."""
    params: dict[str, Any] = {}
    if action_type == ActionType.CALENDAR_UPDATE:
        params = {"summary": "Sample"}
    elif action_type == ActionType.TASK_CREATE:
        params = {"title": "Sample"}

    act = _make_action(action_type, wrong_system, correct_kind, parameters=params)
    with pytest.raises(ActionTargetCompatibilityError, match="requires target system"):
        validate_action_contract(act)


# ---------------------------------------------------------------------------
# 6: calendar.read rejects all parameters
# ---------------------------------------------------------------------------


def test_calendar_read_rejects_all_parameters() -> None:
    """Requirement 6: calendar.read fails closed if any parameter is supplied."""
    act = _make_action(
        ActionType.CALENDAR_READ,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"extra": "param"},
    )
    with pytest.raises(UnknownParameterError, match="does not accept parameters"):
        validate_action_contract(act)


# ---------------------------------------------------------------------------
# 7, 8, 9, 10, 11, 12, 13, 14: calendar.update Parameter Validation
# ---------------------------------------------------------------------------


def test_calendar_update_accepts_each_supported_parameter_independently() -> None:
    """Requirement 7: calendar.update accepts summary, start_time, and all_day independently."""
    # summary only
    act1 = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"summary": "New Title"},
    )
    assert validate_action_contract(act1).action == act1

    # start_time only
    act2 = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"start_time": "2026-10-01T07:30:00Z"},
    )
    assert validate_action_contract(act2).action == act2

    # all_day True only
    act3 = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"all_day": True},
    )
    assert validate_action_contract(act3).action == act3

    # all_day False only
    act4 = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"all_day": False},
    )
    assert validate_action_contract(act4).action == act4


def test_calendar_update_accepts_valid_supported_combinations() -> None:
    """Requirement 8: calendar.update accepts valid combinations of supported parameters."""
    act1 = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={
            "summary": "Morning Routine",
            "start_time": "2026-10-01T07:30:00Z",
            "all_day": False,
        },
    )
    assert validate_action_contract(act1).action == act1

    act2 = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"summary": "Holiday", "all_day": True},
    )
    assert validate_action_contract(act2).action == act2


def test_calendar_update_with_zero_parameters_fails() -> None:
    """Requirement 9: calendar.update with zero parameters fails closed."""
    act = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={},
    )
    with pytest.raises(
        EmptyParameterSetError, match="requires at least one supported update parameter"
    ):
        validate_action_contract(act)


@pytest.mark.parametrize(
    "bad_key",
    [
        "startTime",  # camelCase alias
        "start-time",  # kebab-case alias
        "start",  # truncated alias
        "end_time",  # speculative field
        "attendees",  # speculative field
        "location",  # speculative field
        "description",  # speculative field
        "SUMMARY",  # uppercase variant
        "notes",  # speculative field
    ],
)
def test_calendar_update_unknown_parameters_fail(bad_key: str) -> None:
    """Requirement 10: Unknown parameter names, case variants, and aliases fail closed."""
    act = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"summary": "Valid Title", bad_key: "some_value"},
    )
    with pytest.raises(UnknownParameterError, match=f"does not accept parameter '{bad_key}'"):
        validate_action_contract(act)


@pytest.mark.parametrize(
    ("bad_params", "expected_err", "match_str"),
    [
        ({"summary": 123}, InvalidParameterTypeError, "must be of type str"),
        ({"summary": True}, InvalidParameterTypeError, "must be of type str"),
        ({"summary": None}, InvalidParameterTypeError, "must be of type str"),
        ({"start_time": 456}, InvalidParameterTypeError, "must be of type str"),
        ({"start_time": False}, InvalidParameterTypeError, "must be of type str"),
        ({"all_day": "true"}, InvalidParameterTypeError, "must be of type bool"),
        ({"all_day": 1}, InvalidParameterTypeError, "must be of type bool"),
        ({"all_day": 0}, InvalidParameterTypeError, "must be of type bool"),
        ({"all_day": None}, InvalidParameterTypeError, "must be of type bool"),
    ],
)
def test_calendar_update_wrong_parameter_types_fail(
    bad_params: dict[str, Any],
    expected_err: type[ActionPolicyError],
    match_str: str,
) -> None:
    """Requirement 11: Wrong parameter types fail closed."""
    act = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters=bad_params,
    )
    with pytest.raises(expected_err, match=match_str):
        validate_action_contract(act)


@pytest.mark.parametrize(
    "blank_summary",
    ["", "   ", "\t", "\n", " \t \n "],
)
def test_calendar_update_blank_summary_fails(blank_summary: str) -> None:
    """Requirement 12: Blank or whitespace-only summary fails closed."""
    act = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"summary": blank_summary},
    )
    with pytest.raises(InvalidParameterValueError, match="cannot be empty or whitespace-only"):
        validate_action_contract(act)


@pytest.mark.parametrize(
    "blank_start_time",
    ["", "   ", "\t", "\n"],
)
def test_calendar_update_blank_start_time_fails(blank_start_time: str) -> None:
    """Requirement 12: Blank or whitespace-only start_time fails closed."""
    act = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"start_time": blank_start_time},
    )
    with pytest.raises(InvalidParameterValueError, match="cannot be empty or whitespace-only"):
        validate_action_contract(act)


def test_calendar_update_oversized_string_fails() -> None:
    """Requirement 13: Oversized string parameter values fail closed."""
    oversized = "a" * (MAX_PARAM_STRING_LENGTH + 1)
    act = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"summary": oversized},
    )
    with pytest.raises(OversizedParameterError, match="exceeds maximum allowed length"):
        validate_action_contract(act)

    act_start = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"start_time": oversized},
    )
    with pytest.raises(OversizedParameterError, match="exceeds maximum allowed length"):
        validate_action_contract(act_start)

    # Exactly at boundary succeeds
    at_boundary = "a" * MAX_PARAM_STRING_LENGTH
    act_ok = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"summary": at_boundary},
    )
    assert validate_action_contract(act_ok).action == act_ok


def test_all_day_accepts_bool_only() -> None:
    """Requirement 14: all_day accepts actual bool (True/False) only; no int/str coercions."""
    # True and False succeed
    for valid_bool in (True, False):
        act = _make_action(
            ActionType.CALENDAR_UPDATE,
            "google_calendar",
            ResourceKind.CALENDAR_EVENT,
            parameters={"all_day": valid_bool},
        )
        assert validate_action_contract(act).action == act

    # Int 1, 0, strings "true", "True", "false" all fail
    for invalid_val in (1, 0, "true", "True", "false", "False", 1.0, 0.0):
        act = _make_action(
            ActionType.CALENDAR_UPDATE,
            "google_calendar",
            ResourceKind.CALENDAR_EVENT,
            parameters={"all_day": invalid_val},
        )
        with pytest.raises(InvalidParameterTypeError, match="must be of type bool"):
            validate_action_contract(act)


# ---------------------------------------------------------------------------
# 15: task.read rejects all parameters
# ---------------------------------------------------------------------------


def test_task_read_rejects_all_parameters() -> None:
    """Requirement 15: task.read fails closed if any parameter is supplied."""
    act = _make_action(
        ActionType.TASK_READ,
        "google_tasks",
        ResourceKind.TASK,
        parameters={"task_id": "123"},
    )
    with pytest.raises(UnknownParameterError, match="does not accept parameters"):
        validate_action_contract(act)


# ---------------------------------------------------------------------------
# 16, 17, 18, 19, 20, 21, 22: task.create Parameter Validation
# ---------------------------------------------------------------------------


def test_task_create_requires_title() -> None:
    """Requirement 16: task.create requires title parameter."""
    act_empty = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={},
    )
    with pytest.raises(MissingRequiredParameterError, match="missing required parameter 'title'"):
        validate_action_contract(act_empty)

    act_due_only = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"due": "2026-10-01"},
    )
    with pytest.raises(MissingRequiredParameterError, match="missing required parameter 'title'"):
        validate_action_contract(act_due_only)


def test_task_create_valid_title_succeeds() -> None:
    """Requirement 17: task.create with valid title succeeds."""
    act = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": "Pack umbrella"},
    )
    validated = validate_action_contract(act)
    assert validated.action == act
    assert validated.parameters["title"] == "Pack umbrella"


def test_task_create_valid_title_and_due_succeeds() -> None:
    """Requirement 18: task.create with valid title + due succeeds."""
    act = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": "Leave for work", "due": "2026-10-01T07:30:00Z"},
    )
    validated = validate_action_contract(act)
    assert validated.action == act
    assert validated.parameters["title"] == "Leave for work"
    assert validated.parameters["due"] == "2026-10-01T07:30:00Z"


@pytest.mark.parametrize(
    "blank_title",
    ["", "   ", "\t", "\n"],
)
def test_task_create_blank_title_fails(blank_title: str) -> None:
    """Requirement 19: Blank or whitespace-only title fails closed."""
    act = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": blank_title},
    )
    with pytest.raises(InvalidParameterValueError, match="cannot be empty or whitespace-only"):
        validate_action_contract(act)


@pytest.mark.parametrize(
    "bad_title",
    [123, True, False, None, 45.6],
)
def test_task_create_wrong_title_type_fails(bad_title: Any) -> None:
    """Requirement 20: Non-string title type fails closed."""
    act = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": bad_title},
    )
    with pytest.raises(InvalidParameterTypeError, match="must be of type str"):
        validate_action_contract(act)


@pytest.mark.parametrize(
    "unknown_key",
    ["notes", "description", "priority", "status", "assignee", "due_date", "dueDate"],
)
def test_task_create_unknown_parameter_fails(unknown_key: str) -> None:
    """Requirement 21: Unknown parameters for task.create fail closed."""
    act = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": "Valid Title", unknown_key: "val"},
    )
    with pytest.raises(UnknownParameterError, match=f"does not accept parameter '{unknown_key}'"):
        validate_action_contract(act)


@pytest.mark.parametrize(
    "bad_due",
    ["", "   ", "\t", 123, True, None, "a" * (MAX_PARAM_STRING_LENGTH + 1)],
)
def test_task_create_malformed_optional_due_fails(bad_due: Any) -> None:
    """Requirement 22: Malformed, blank, wrong-type, or oversized optional due fails closed."""
    act = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": "Valid Title", "due": bad_due},
    )
    with pytest.raises(ActionParameterPolicyError):
        validate_action_contract(act)


# ---------------------------------------------------------------------------
# 23: weather.read rejects unsupported parameters
# ---------------------------------------------------------------------------


def test_weather_read_rejects_unsupported_parameters() -> None:
    """Requirement 23: weather.read rejects any supplied action parameters."""
    act = _make_action(
        ActionType.WEATHER_READ,
        "open_meteo",
        ResourceKind.WEATHER_LOCATION,
        parameters={"latitude": 52.52},
    )
    with pytest.raises(UnknownParameterError, match="does not accept parameters"):
        validate_action_contract(act)


# ---------------------------------------------------------------------------
# 24: Model-like, shell, HTTP, filesystem actions rejected
# ---------------------------------------------------------------------------


def test_unsupported_action_vocabulary_fails_closed() -> None:
    """Requirement 24: Arbitrary execution, shell, HTTP, filesystem, delete actions rejected."""
    unsupported_actions = [
        "shell.execute",
        "http.request",
        "filesystem.delete",
        "email.send",
        "generic.execute",
        "model.call",
        "custom.action",
    ]
    mid = MissionId.generate()
    target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="demo-list",
    )
    for bad_act in unsupported_actions:
        # Fails at ActionContract.create boundary
        with pytest.raises(ValueError, match="Unsupported action type"):
            ActionContract.create(
                mission_id=mid,
                action_type=bad_act,
                target=target,
                parameters={},
            )

    # Even if an ActionContract instance was constructed via object.__new__ bypass:
    bypassed_action = object.__new__(ActionContract)
    object.__setattr__(bypassed_action, "action_id", ActionId.generate())
    object.__setattr__(bypassed_action, "mission_id", mid)
    object.__setattr__(bypassed_action, "action_type", "shell.execute")
    object.__setattr__(bypassed_action, "target", target)
    object.__setattr__(bypassed_action, "parameters", NormalizedParameters.from_dict({}))

    with pytest.raises(UnsupportedActionTypeError, match="Unsupported action type"):
        validate_action_contract(bypassed_action)


# ---------------------------------------------------------------------------
# 25: Error text does NOT include supplied sentinel sensitive value
# ---------------------------------------------------------------------------


def test_error_text_does_not_leak_sentinel_sensitive_values() -> None:
    """Requirement 25: Sensitive parameter values are never echoed in error messages."""
    sentinel = "SUPER_SECRET_TOKEN_998877665544"

    # Case A: Oversized string parameter containing sentinel
    oversized_with_sentinel = sentinel + ("x" * 2000)
    act_oversized = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": oversized_with_sentinel},
    )
    with pytest.raises(OversizedParameterError) as exc_info1:
        validate_action_contract(act_oversized)
    assert sentinel not in str(exc_info1.value)

    # Case B: Unknown parameter containing sentinel as value
    act_unknown = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": "Safe Title", "unsupported_key": sentinel},
    )
    with pytest.raises(UnknownParameterError) as exc_info2:
        validate_action_contract(act_unknown)
    assert sentinel not in str(exc_info2.value)

    # Case C: Parameter for zero-parameter action containing sentinel
    act_zero_param = _make_action(
        ActionType.CALENDAR_READ,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"secret_param": sentinel},
    )
    with pytest.raises(UnknownParameterError) as exc_info3:
        validate_action_contract(act_zero_param)
    assert sentinel not in str(exc_info3.value)


# ---------------------------------------------------------------------------
# 26 & 27: Determinism & Immutability (No Mutation)
# ---------------------------------------------------------------------------


def test_validation_is_deterministic_and_caller_objects_not_mutated() -> None:
    """Requirement 26 & 27: Validation is pure, repeatable, and never mutates inputs."""
    raw_summary = "  Standup Meeting At 9:00  "
    act = _make_action(
        ActionType.CALENDAR_UPDATE,
        "google_calendar",
        ResourceKind.CALENDAR_EVENT,
        parameters={"summary": raw_summary, "all_day": False},
    )

    # Snapshot state before validation
    orig_params = dict(act.parameters.items())
    orig_target_system = act.target.system
    orig_target_kind = act.target.resource_kind

    res1 = validate_action_contract(act)
    res2 = validate_action_contract(act)

    # Determinism
    assert res1 == res2
    assert res1.action == res2.action

    # Preserves whitespace without stripping or altering
    assert act.parameters["summary"] == raw_summary
    assert res1.parameters["summary"] == raw_summary

    # Caller objects completely unmutated
    assert dict(act.parameters.items()) == orig_params
    assert act.target.system == orig_target_system
    assert act.target.resource_kind == orig_target_kind


# ---------------------------------------------------------------------------
# 28: No Authority or Execution Side Effects
# ---------------------------------------------------------------------------


def test_validation_does_not_create_authority_or_execution_artifacts() -> None:
    """Requirement 28: ValidatedActionContract confers no authority/approval/execution."""
    act = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": "Pack umbrella"},
    )
    validated = validate_action_contract(act)

    assert not hasattr(validated, "authority_class")
    assert not hasattr(validated, "approval_grant")
    assert not hasattr(validated, "binding_hash")
    assert not hasattr(validated, "execution_attempt")
    assert not hasattr(validated, "is_authorized")
    assert not hasattr(validated, "execute")


# ---------------------------------------------------------------------------
# 29: AST Purity: Zero Provider / Network Imports
# ---------------------------------------------------------------------------


def test_action_policy_ast_purity() -> None:
    """Requirement 29: Static AST inspection proves zero provider/network imports."""
    policy_file = pathlib.Path(__file__).parent.parent / "src" / "stilldone" / "action_policy.py"
    assert policy_file.is_file(), f"File {policy_file} does not exist"

    tree = ast.parse(policy_file.read_text(encoding="utf-8"), filename=str(policy_file))
    forbidden_packages = {
        "boto3",
        "botocore",
        "strands",
        "agentcore",
        "google",
        "googleapiclient",
        "mcp",
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "flask",
        "fastapi",
        "sqlite3",
        "sqlalchemy",
        "tkinter",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_pkg = alias.name.split(".")[0]
                assert top_pkg not in forbidden_packages, f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            top_pkg = node.module.split(".")[0]
            assert top_pkg not in forbidden_packages, f"Forbidden from-import: {node.module}"


# ---------------------------------------------------------------------------
# Direct Construction / Bypass Resistance
# ---------------------------------------------------------------------------


def test_direct_construction_without_create_undergoes_identical_validation() -> None:
    """Directly constructed ActionContract undergoes full validation; bypass fails."""
    # Direct valid construction
    act_direct_valid = ActionContract(
        action_id=ActionId.generate(),
        mission_id=MissionId.generate(),
        action_type=ActionType.TASK_CREATE,
        target=TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK_LIST,
            resource_id="list-1",
        ),
        parameters=NormalizedParameters(_items=(("title", "Direct task"),)),
    )
    validated = validate_action_contract(act_direct_valid)
    assert validated.action == act_direct_valid

    # Direct invalid construction (incompatible target)
    act_direct_invalid = ActionContract(
        action_id=ActionId.generate(),
        mission_id=MissionId.generate(),
        action_type=ActionType.TASK_CREATE,
        target=TargetIdentity(
            system="google_calendar",  # incompatible system
            resource_kind=ResourceKind.TASK_LIST,
            resource_id="list-1",
        ),
        parameters=NormalizedParameters(_items=(("title", "Direct task"),)),
    )
    with pytest.raises(ActionTargetCompatibilityError):
        validate_action_contract(act_direct_invalid)


def test_validated_action_contract_direct_construction_self_validates() -> None:
    """Direct construction of ValidatedActionContract runs validation and fails closed."""
    # Valid action can be wrapped directly
    valid_act = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.TASK_LIST,
        parameters={"title": "Pack umbrella"},
    )
    val_contract = ValidatedActionContract(action=valid_act)
    assert val_contract.action == valid_act

    # Non-ActionContract fails
    with pytest.raises(ActionPolicyTypeError, match="action must be an ActionContract instance"):
        ValidatedActionContract(action="not-an-action")  # type: ignore[arg-type]

    # Incompatible action fails even when caller tries to instantiate
    # ValidatedActionContract directly
    invalid_act = _make_action(
        ActionType.TASK_CREATE,
        "google_tasks",
        ResourceKind.CALENDAR_EVENT,  # wrong kind
        parameters={"title": "Pack umbrella"},
    )
    with pytest.raises(ActionTargetCompatibilityError):
        ValidatedActionContract(action=invalid_act)


def test_validate_action_contract_rejects_non_action_contract_instances() -> None:
    """validate_action_contract rejects non-ActionContract inputs."""
    with pytest.raises(ActionPolicyTypeError, match="action must be an ActionContract instance"):
        validate_action_contract("not_an_action")  # type: ignore[arg-type]

    with pytest.raises(ActionPolicyTypeError, match="action must be an ActionContract instance"):
        validate_action_contract(None)  # type: ignore[arg-type]
