"""Focused tests for P-02.02 desired-state predicates and freshness contracts."""

from __future__ import annotations

import math
import sys
import uuid
from dataclasses import FrozenInstanceError

import pytest

from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    FreshnessMode,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.mission import MissionId


def test_predicate_id_generation_and_validation() -> None:
    """Verify runtime-generated predicate IDs are valid opaque UUIDs."""
    pid = PredicateId.generate()
    assert isinstance(pid.value, str)
    parsed = uuid.UUID(pid.value)
    assert parsed.version == 4
    assert str(pid) == pid.value

    # From string or UUID
    raw = uuid.uuid4()
    pid_str = PredicateId(str(raw).upper())
    pid_uuid = PredicateId(raw)  # type: ignore[arg-type]
    assert pid_str == pid_uuid
    assert pid_str.value == str(raw)


def test_predicate_id_rejects_invalid_values() -> None:
    """Verify invalid format strings and non-UUID values are rejected."""
    with pytest.raises(ValueError, match="Invalid PredicateId format"):
        PredicateId("invalid-id")

    with pytest.raises(TypeError, match="PredicateId value must be a string or UUID instance"):
        PredicateId(12345)  # type: ignore[arg-type]


def test_operator_vocabulary_allows_deterministic_operators() -> None:
    """Verify supported deterministic comparison operators."""
    expected_ops = {
        "==": PredicateOperator.EQUALS,
        "!=": PredicateOperator.NOT_EQUALS,
        "exists": PredicateOperator.EXISTS,
        "does_not_exist": PredicateOperator.DOES_NOT_EXIST,
        "<": PredicateOperator.LESS_THAN,
        "<=": PredicateOperator.LESS_THAN_OR_EQUAL,
        ">": PredicateOperator.GREATER_THAN,
        ">=": PredicateOperator.GREATER_THAN_OR_EQUAL,
    }
    for symbol, op_enum in expected_ops.items():
        assert PredicateOperator(symbol) == op_enum


def test_operator_vocabulary_rejects_arbitrary_operators() -> None:
    """Verify arbitrary code/expressions/operators are rejected."""
    for unsupported in ["eval", "lambda x: True", "in", "regex", "like", "contains"]:
        with pytest.raises(ValueError, match="Unsupported predicate operator"):
            DesiredStatePredicate.create(
                mission_id=MissionId.generate(),
                subject="calendar_event.summary",
                operator=unsupported,
                expected_value="test",
            )


def test_freshness_contract_current() -> None:
    """Verify FreshnessContract.current() semantics."""
    fc = FreshnessContract.current()
    assert fc.mode == FreshnessMode.CURRENT
    assert fc.max_age_seconds is None


def test_freshness_contract_max_age() -> None:
    """Verify FreshnessContract.max_age() semantics with bounded positive duration."""
    fc = FreshnessContract.max_age(3600)
    assert fc.mode == FreshnessMode.MAX_AGE
    assert fc.max_age_seconds == 3600


def test_freshness_contract_rejects_contradictory_combinations() -> None:
    """Verify contradictory combinations (e.g. CURRENT with max_age) are rejected."""
    with pytest.raises(ValueError, match="FreshnessMode.CURRENT does not allow max_age_seconds"):
        FreshnessContract(mode=FreshnessMode.CURRENT, max_age_seconds=60)

    with pytest.raises(ValueError, match="FreshnessMode.MAX_AGE requires max_age_seconds"):
        FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=None)


def test_freshness_contract_rejects_non_positive_max_age() -> None:
    """Verify non-positive (zero and negative) max-age durations are rejected."""
    with pytest.raises(ValueError, match="max_age_seconds must be strictly positive"):
        FreshnessContract.max_age(0)

    with pytest.raises(ValueError, match="max_age_seconds must be strictly positive"):
        FreshnessContract.max_age(-120)

    with pytest.raises(TypeError, match="max_age_seconds must be an integer"):
        FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=True)

    with pytest.raises(TypeError, match="max_age_seconds must be an integer"):
        FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds="60")  # type: ignore[arg-type]


def test_desired_state_predicate_creation_required_and_optional() -> None:
    """Verify required vs optional semantics and explicit predicate definition."""
    mid = MissionId.generate()

    # Required predicate
    pred_req = DesiredStatePredicate.create(
        mission_id=mid,
        subject="calendar_event.start_time",
        operator=PredicateOperator.EQUALS,
        expected_value="07:30",
        required=True,
        freshness=FreshnessContract.current(),
    )
    assert pred_req.required is True
    assert pred_req.mission_id == mid
    assert pred_req.subject == "calendar_event.start_time"
    assert pred_req.operator == PredicateOperator.EQUALS
    assert pred_req.expected_value == "07:30"
    assert pred_req.freshness.mode == FreshnessMode.CURRENT

    # Optional predicate
    pred_opt = DesiredStatePredicate.create(
        mission_id=mid,
        subject="weather_observation.condition",
        operator="!=",
        expected_value="rain",
        required=False,
        freshness=FreshnessContract.max_age(1800),
    )
    assert pred_opt.required is False
    assert pred_opt.operator == PredicateOperator.NOT_EQUALS
    assert pred_opt.freshness.mode == FreshnessMode.MAX_AGE
    assert pred_opt.freshness.max_age_seconds == 1800


def test_desired_state_predicate_rejects_blank_subject() -> None:
    """Verify subject path cannot be empty or whitespace-only."""
    mid = MissionId.generate()
    with pytest.raises(ValueError, match="subject cannot be blank or whitespace-only"):
        DesiredStatePredicate.create(
            mission_id=mid,
            subject="   ",
            operator=PredicateOperator.EXISTS,
            expected_value=True,
        )


def test_desired_state_predicate_rejects_non_scalar_expected_value() -> None:
    """Verify arbitrary complex/mutable objects as expected_value are rejected."""
    mid = MissionId.generate()
    with pytest.raises(TypeError, match="expected_value must be a JSON-like scalar"):
        DesiredStatePredicate.create(
            mission_id=mid,
            subject="task.details",
            operator=PredicateOperator.EQUALS,
            expected_value={"nested": "dict"},  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="expected_value must be a JSON-like scalar"):
        DesiredStatePredicate.create(
            mission_id=mid,
            subject="task.details",
            operator=PredicateOperator.EQUALS,
            expected_value=[1, 2, 3],  # type: ignore[arg-type]
        )


def test_desired_state_predicate_rejects_nan_and_inf() -> None:
    """Verify non-finite float values are rejected."""
    mid = MissionId.generate()
    with pytest.raises(ValueError, match="NaN and Infinity forbidden"):
        DesiredStatePredicate.create(
            mission_id=mid,
            subject="temperature",
            operator=PredicateOperator.LESS_THAN,
            expected_value=float("nan"),
        )

    with pytest.raises(ValueError, match="NaN and Infinity forbidden"):
        DesiredStatePredicate.create(
            mission_id=mid,
            subject="temperature",
            operator=PredicateOperator.LESS_THAN,
            expected_value=math.inf,
        )


def test_desired_state_predicate_immutability() -> None:
    """Verify frozen instances cannot be modified."""
    pred = DesiredStatePredicate.create(
        mission_id=MissionId.generate(),
        subject="calendar_event.exists",
        operator=PredicateOperator.EXISTS,
        expected_value=True,
    )
    with pytest.raises(FrozenInstanceError):
        pred.required = False  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        pred.expected_value = False  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        pred.freshness = FreshnessContract.max_age(60)  # type: ignore[misc]


def test_no_provider_dependencies_imported() -> None:
    """Verify domain package does not import cloud or provider SDKs."""
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
