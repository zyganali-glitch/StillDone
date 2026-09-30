"""Focused unit tests for StillDone canonical serialization contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from enum import Enum, StrEnum

import pytest

from stilldone.domain.action import ActionId, ActionType, ResourceKind, TargetIdentity
from stilldone.domain.authority import ApprovalId, AuthorityClass, BindingHash
from stilldone.domain.desired_state import PredicateId, PredicateOperator
from stilldone.domain.execution import AttemptId, IdempotencyKey, RetryStrategy
from stilldone.domain.lifecycle import MissionState, StepEvidenceState
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.evidence import EvidenceId
from stilldone.serialization import (
    canonical_json,
    canonical_serialize,
    normalize_datetime,
    to_canonical_primitive,
)


class SampleEnum(StrEnum):
    ALPHA = "ALPHA"
    BETA = "BETA"


class SampleIntEnum(Enum):
    ONE = 1
    TWO = 2


class UnsupportedObject:
    def __init__(self, val: str) -> None:
        self.val = val


def test_repeated_canonical_serialization_stability() -> None:
    """Repeated serialization of complex structures produces bitwise identical bytes."""
    data = {
        "mission_id": MissionId("00000000-0000-0000-0000-000000000001"),
        "timestamp": datetime(2026, 9, 30, 8, 30, 0, tzinfo=UTC),
        "nested": {
            "z": 100,
            "a": "hello",
            "items": [3, 2, 1, {"k2": True, "k1": None}],
        },
        "action_type": ActionType.CALENDAR_READ,
        "state": MissionState.PLANNED,
    }

    serialized_1 = canonical_serialize(data)
    serialized_2 = canonical_serialize(data)
    serialized_3 = canonical_serialize(data)

    assert serialized_1 == serialized_2 == serialized_3
    assert isinstance(serialized_1, bytes)


def test_key_and_order_normalization() -> None:
    """Dictionaries with different insertion order produce identical canonical output."""
    d1 = {"z": 1, "m": 2, "a": 3}
    d2 = {"a": 3, "z": 1, "m": 2}
    d3 = {"m": 2, "a": 3, "z": 1}

    assert canonical_json(d1) == canonical_json(d2) == canonical_json(d3)
    assert canonical_json(d1) == '{"a":3,"m":2,"z":1}'


def test_timestamp_stability_and_normalization() -> None:
    """Timestamps representing the exact same UTC instant normalize identically."""
    t_utc = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
    t_plus3 = datetime(2026, 9, 30, 15, 0, 0, tzinfo=timezone(timedelta(hours=3)))
    t_minus4 = datetime(2026, 9, 30, 8, 0, 0, tzinfo=timezone(timedelta(hours=-4)))

    assert normalize_datetime(t_utc) == normalize_datetime(t_plus3) == normalize_datetime(t_minus4)
    assert normalize_datetime(t_utc) == "2026-09-30T12:00:00+00:00"

    # Naive datetime fails closed
    t_naive = datetime(2026, 9, 30, 12, 0, 0)
    with pytest.raises(ValueError, match="Naive datetime is not permitted"):
        normalize_datetime(t_naive)

    with pytest.raises(ValueError, match="Naive datetime is not permitted"):
        to_canonical_primitive(t_naive)


def test_canonical_enum_and_id_projection() -> None:
    """Enums and strongly typed ID wrappers project to their canonical string values."""
    assert to_canonical_primitive(ActionType.CALENDAR_READ) == "calendar.read"
    assert to_canonical_primitive(ActionType.TASK_CREATE) == "task.create"
    assert to_canonical_primitive(MissionState.DRAFT) == "DRAFT"
    assert to_canonical_primitive(StepEvidenceState.NOT_RUN) == "NOT_RUN"
    assert to_canonical_primitive(AuthorityClass.READ_ONLY) == "READ_ONLY"
    assert to_canonical_primitive(PredicateOperator.EQUALS) == "=="
    assert to_canonical_primitive(ResourceKind.CALENDAR_EVENT) == "calendar_event"
    assert to_canonical_primitive(RetryStrategy.NO_RETRY) == "NO_RETRY"
    assert to_canonical_primitive(EvidenceProvenance.LIVE_GOOGLE) == "LIVE_GOOGLE"

    assert to_canonical_primitive(SampleEnum.ALPHA) == "ALPHA"
    assert to_canonical_primitive(SampleIntEnum.ONE) == 1

    mid = MissionId("11111111-1111-1111-1111-111111111111")
    aid = ActionId("22222222-2222-2222-2222-222222222222")
    pid = PredicateId("33333333-3333-3333-3333-333333333333")
    att_id = AttemptId("44444444-4444-4444-4444-444444444444")
    idem = IdempotencyKey("55555555-5555-5555-5555-555555555555")
    app_id = ApprovalId("66666666-6666-6666-6666-666666666666")
    bhash = BindingHash("a" * 64)
    ev_id = EvidenceId("b" * 64)

    assert to_canonical_primitive(mid) == "11111111-1111-1111-1111-111111111111"
    assert to_canonical_primitive(aid) == "22222222-2222-2222-2222-222222222222"
    assert to_canonical_primitive(pid) == "33333333-3333-3333-3333-333333333333"
    assert to_canonical_primitive(att_id) == "44444444-4444-4444-4444-444444444444"
    assert to_canonical_primitive(idem) == "55555555-5555-5555-5555-555555555555"
    assert to_canonical_primitive(app_id) == "66666666-6666-6666-6666-666666666666"
    assert to_canonical_primitive(bhash) == "a" * 64
    assert to_canonical_primitive(ev_id) == "b" * 64


def test_semantic_distinctions_preserved() -> None:
    """Semantic distinctions between False, 0, None, and empty string are strictly preserved."""
    assert canonical_json(False) == "false"
    assert canonical_json(0) == "0"
    assert canonical_json(None) == "null"
    assert canonical_json("") == '""'
    assert canonical_json([]) == "[]"
    assert canonical_json({}) == "{}"

    # Dict with distinct semantic values
    d = {"bool": False, "int": 0, "none": None, "str": ""}
    assert canonical_json(d) == '{"bool":false,"int":0,"none":null,"str":""}'


def test_dataclass_sorted_fields_projection() -> None:
    """Dataclasses project to dictionaries with sorted field names."""
    target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-123",
        parent_id="cal-456",
    )
    primitive = to_canonical_primitive(target)
    assert primitive == {
        "parent_id": "cal-456",
        "resource_id": "evt-123",
        "resource_kind": "calendar_event",
        "system": "google_calendar",
    }


def test_unsupported_and_malformed_content_fails_closed() -> None:
    """Unsupported types and malformed data fail closed with explicit exceptions."""
    # Non-finite floats
    with pytest.raises(ValueError, match="Non-finite float"):
        to_canonical_primitive(float("nan"))
    with pytest.raises(ValueError, match="Non-finite float"):
        to_canonical_primitive(float("inf"))
    with pytest.raises(ValueError, match="Non-finite float"):
        to_canonical_primitive(float("-inf"))

    # Non-string dict keys
    with pytest.raises(TypeError, match="Dictionary keys must be strings"):
        to_canonical_primitive({1: "invalid_key"})

    # Unsupported arbitrary Python object
    with pytest.raises(TypeError, match="Unsupported type"):
        to_canonical_primitive(UnsupportedObject("bad"))

    # Sets are rejected fail-closed to avoid non-deterministic iteration order
    with pytest.raises(TypeError, match="Unsupported type"):
        to_canonical_primitive({"set_item_1", "set_item_2"})

    # Functions / lambdas are rejected fail-closed
    with pytest.raises(TypeError, match="Unsupported type"):
        to_canonical_primitive(lambda x: x)
