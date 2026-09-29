"""Focused tests for P-02.03 action contracts, target identity, and parameter normalization."""

from __future__ import annotations

import math
import sys
import uuid
from dataclasses import FrozenInstanceError

import pytest

from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.mission import MissionId


def test_action_id_generation_and_validation() -> None:
    """Verify runtime-generated action IDs are valid opaque UUIDs."""
    aid = ActionId.generate()
    assert isinstance(aid.value, str)
    parsed = uuid.UUID(aid.value)
    assert parsed.version == 4
    assert str(aid) == aid.value

    # Parse from string and UUID
    raw = uuid.uuid4()
    aid_str = ActionId(str(raw))
    aid_uuid = ActionId(raw)  # type: ignore[arg-type]
    assert aid_str == aid_uuid


def test_action_id_rejects_invalid_values() -> None:
    """Verify invalid format strings and non-UUID values are rejected."""
    with pytest.raises(ValueError, match="Invalid ActionId format"):
        ActionId("invalid-action-id")

    with pytest.raises(TypeError, match="ActionId value must be a string or UUID instance"):
        ActionId(42)  # type: ignore[arg-type]


def test_supported_action_vocabulary_frozen() -> None:
    """Verify supported action vocabulary covers exactly the five required capabilities."""
    expected_actions = {
        "calendar.read": ActionType.CALENDAR_READ,
        "calendar.update": ActionType.CALENDAR_UPDATE,
        "task.read": ActionType.TASK_READ,
        "task.create": ActionType.TASK_CREATE,
        "weather.read": ActionType.WEATHER_READ,
    }
    for val, enum_member in expected_actions.items():
        assert ActionType(val) == enum_member

    assert len(ActionType) == 5


def test_unsupported_action_types_rejected() -> None:
    """Verify arbitrary shell, HTTP, delete, or model actions cannot be constructed."""
    mid = MissionId.generate()
    target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="demo-list",
    )
    unsupported_actions = [
        "shell.execute",
        "http.request",
        "filesystem.delete",
        "email.send",
        "call_tool",
        "generic.execute",
        "delete_task",
    ]
    for unsupported in unsupported_actions:
        with pytest.raises(ValueError, match="Unsupported action type"):
            ActionContract.create(
                mission_id=mid,
                action_type=unsupported,
                target=target,
                parameters={},
            )


def test_target_identity_immutable_and_valid() -> None:
    """Verify TargetIdentity holds system, kind, resource, and optional parent."""
    target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="event-789",
        parent_id="calendar-123",
    )
    assert target.system == "google_calendar"
    assert target.resource_kind == ResourceKind.CALENDAR_EVENT
    assert target.resource_id == "event-789"
    assert target.parent_id == "calendar-123"

    with pytest.raises(FrozenInstanceError):
        target.resource_id = "new-id"  # type: ignore[misc]


def test_target_identity_rejects_empty_fields() -> None:
    """Verify TargetIdentity validates required fields."""
    with pytest.raises(ValueError, match="system must be a non-empty string"):
        TargetIdentity(
            system="",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-1",
        )

    with pytest.raises(ValueError, match="resource_id must be a non-empty string"):
        TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="   ",
        )

    with pytest.raises(ValueError, match="Unsupported resource kind"):
        TargetIdentity(
            system="google_calendar",
            resource_kind="unknown_kind",  # type: ignore[arg-type]
            resource_id="evt-1",
        )


def test_creation_action_targets_parent_without_fabricating_child_id() -> None:
    """Verify creation action targets parent container directly without fabricating child ID."""
    mid = MissionId.generate()
    parent_target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="StillDone Demo",
    )
    action = ActionContract.create(
        mission_id=mid,
        action_type=ActionType.TASK_CREATE,
        target=parent_target,
        parameters={"title": "Pack umbrella"},
    )
    assert action.target.resource_kind == ResourceKind.TASK_LIST
    assert action.target.resource_id == "StillDone Demo"
    assert action.target.parent_id is None
    # No child task ID was fabricated
    assert "task_id" not in action.parameters


def test_parameter_normalization_stable_ordering_and_determinism() -> None:
    """Verify key ordering is lexicographically sorted and equivalent maps normalize identically."""
    map1 = {"zebra": "last", "alpha": 1, "middle": True}
    map2 = {"alpha": 1, "middle": True, "zebra": "last"}
    map3 = {"middle": True, "zebra": "last", "alpha": 1}

    norm1 = NormalizedParameters.from_dict(map1)
    norm2 = NormalizedParameters.from_dict(map2)
    norm3 = NormalizedParameters.from_dict(map3)

    assert norm1 == norm2 == norm3
    assert norm1.items() == (("alpha", 1), ("middle", True), ("zebra", "last"))
    assert list(norm1) == ["alpha", "middle", "zebra"]
    assert len(norm1) == 3
    assert norm1["alpha"] == 1
    assert norm1.get("zebra") == "last"
    assert norm1.get("missing", "default") == "default"


def test_parameter_normalization_preserves_string_semantics() -> None:
    """Verify strings are preserved verbatim without normalization or trimming."""
    raw_title = "  Pack Umbrella For 7:30 AM!  \n"
    norm = NormalizedParameters.from_dict({"title": raw_title})
    assert norm["title"] == raw_title


def test_parameter_normalization_rejects_nested_and_arbitrary_objects() -> None:
    """Verify complex nested collections or arbitrary objects fail closed."""
    for bad_val in [
        {"nested": "dict"},
        [1, 2, 3],
        {1, 2},
        object(),
        lambda: None,
    ]:
        with pytest.raises(TypeError, match="Unsupported parameter value type"):
            NormalizedParameters.from_dict({"key": bad_val})


def test_parameter_normalization_rejects_nan_and_infinity() -> None:
    """Verify non-finite numeric floats fail closed."""
    with pytest.raises(ValueError, match="Non-finite float value"):
        NormalizedParameters.from_dict({"lat": float("nan")})

    with pytest.raises(ValueError, match="Non-finite float value"):
        NormalizedParameters.from_dict({"lon": math.inf})

    with pytest.raises(ValueError, match="Non-finite float value"):
        NormalizedParameters.from_dict({"lon": -math.inf})


def test_action_contract_immutability() -> None:
    """Verify action contract and parameters cannot be mutated."""
    mid = MissionId.generate()
    target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-123",
    )
    action = ActionContract.create(
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=target,
        parameters={"start_time": "07:30"},
    )
    with pytest.raises(FrozenInstanceError):
        action.action_type = ActionType.CALENDAR_READ  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        action.parameters = NormalizedParameters.from_dict({})  # type: ignore[misc]


def test_no_provider_dependencies_imported() -> None:
    """Verify domain action module does not import cloud or provider SDKs."""
    forbidden_modules = [
        "boto3",
        "botocore",
        "strands",
        "agentcore",
        "google",
        "mcp",
        "requests",
        "httpx",
        "urllib3",
    ]
    for mod in forbidden_modules:
        assert mod not in sys.modules, f"Forbidden module {mod} was imported!"


def test_direct_construction_canonicalizes_order_and_matches_from_dict() -> None:
    """A. Direct construction canonicalizes unsorted inputs to match from_dict identically."""
    direct_unsorted = NormalizedParameters(
        _items=(("zebra", "last"), ("alpha", 1), ("middle", True))
    )
    from_dict_inst = NormalizedParameters.from_dict({"zebra": "last", "alpha": 1, "middle": True})

    assert direct_unsorted == from_dict_inst
    assert direct_unsorted.items() == (("alpha", 1), ("middle", True), ("zebra", "last"))
    assert from_dict_inst.items() == (("alpha", 1), ("middle", True), ("zebra", "last"))


def test_direct_construction_rejects_duplicate_keys() -> None:
    """B. Direct construction rejects duplicate keys."""
    with pytest.raises(ValueError, match="Duplicate parameter key"):
        NormalizedParameters(_items=(("key", 1), ("key", 2)))

    with pytest.raises(ValueError, match="Duplicate parameter key"):
        NormalizedParameters(_items=(("alpha", 1), ("beta", 2), ("alpha", 3)))


def test_direct_construction_rejects_malformed_inputs() -> None:
    """C. Direct construction rejects blank/non-string keys, bad values, and non-finite floats."""
    # Blank/whitespace keys
    with pytest.raises(ValueError, match="Parameter key cannot be blank or whitespace-only"):
        NormalizedParameters(_items=(("", "value"),))

    with pytest.raises(ValueError, match="Parameter key cannot be blank or whitespace-only"):
        NormalizedParameters(_items=(("   \t", "value"),))

    # Non-string keys
    with pytest.raises(TypeError, match="Parameter key must be a string"):
        NormalizedParameters(_items=((123, "value"),))  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="Parameter key must be a string"):
        NormalizedParameters(_items=((None, "value"),))  # type: ignore[arg-type]

    # Nested / arbitrary object values
    for bad_val in [{"nested": "dict"}, [1, 2], {1, 2}, (1, 2), object()]:
        with pytest.raises(TypeError, match="Unsupported parameter value type"):
            NormalizedParameters(_items=(("key", bad_val),))  # type: ignore[arg-type]

    # Non-finite float values: NaN, +Inf, -Inf
    with pytest.raises(ValueError, match="Non-finite float value"):
        NormalizedParameters(_items=(("key", float("nan")),))

    with pytest.raises(ValueError, match="Non-finite float value"):
        NormalizedParameters(_items=(("key", math.inf),))

    with pytest.raises(ValueError, match="Non-finite float value"):
        NormalizedParameters(_items=(("key", -math.inf),))

    # Non-tuple container or non-2-tuple items
    with pytest.raises(TypeError, match="_items must be a tuple"):
        NormalizedParameters(_items=[("key", 1)])  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="Each item in _items must be a 2-tuple"):
        NormalizedParameters(_items=(("key", 1, 2),))  # type: ignore[arg-type]


def test_from_dict_rejects_non_string_keys_before_sorting() -> None:
    """D. from_dict rejects mixed or non-string keys intentionally with TypeError before sorting."""
    # Mixed int and str keys
    with pytest.raises(TypeError, match="Parameter key must be a string"):
        NormalizedParameters.from_dict({1: "int_key", "str_key": "val"})  # type: ignore[dict-item]

    # Purely integer keys
    with pytest.raises(TypeError, match="Parameter key must be a string"):
        NormalizedParameters.from_dict({10: "val1", 20: "val2"})  # type: ignore[dict-item]

    # None key
    with pytest.raises(TypeError, match="Parameter key must be a string"):
        NormalizedParameters.from_dict({None: "val"})  # type: ignore[dict-item]

    # Blank string key
    with pytest.raises(ValueError, match="Parameter key cannot be blank or whitespace-only"):
        NormalizedParameters.from_dict({"": "val"})


def test_action_contract_cannot_be_smuggled_malformed_parameters() -> None:
    """E. It is impossible to smuggle malformed parameters into ActionContract."""
    mid = MissionId.generate()
    target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="demo-list",
    )

    # Attempting to construct malformed NormalizedParameters fails at construction
    with pytest.raises(ValueError, match="Duplicate parameter key"):
        malformed = NormalizedParameters(_items=(("dup", 1), ("dup", 2)))
        ActionContract(
            action_id=ActionId.generate(),
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=target,
            parameters=malformed,
        )

    with pytest.raises(ValueError, match="Non-finite float value"):
        malformed = NormalizedParameters(_items=(("val", float("nan")),))
        ActionContract(
            action_id=ActionId.generate(),
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=target,
            parameters=malformed,
        )

    with pytest.raises(TypeError, match="parameters must be a NormalizedParameters instance"):
        ActionContract(
            action_id=ActionId.generate(),
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=target,
            parameters={"not": "normalized"},  # type: ignore[arg-type]
        )
