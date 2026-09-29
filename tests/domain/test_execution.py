"""Focused tests for P-02.06 execution recovery, idempotency, retry, and reconciliation."""

from __future__ import annotations

import sys
import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from stilldone.domain.action import (
    ActionId,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.desired_state import PredicateId
from stilldone.domain.execution import (
    MAX_RETRY_ATTEMPTS_CEILING,
    AttemptId,
    ExecutionAttempt,
    IdempotencyKey,
    PredicateScope,
    ReconciliationReason,
    ReconciliationRequest,
    ResourceBinding,
    RetryPolicy,
    RetryStrategy,
)
from stilldone.domain.mission import MissionId


def test_idempotency_key_valid_and_generation() -> None:
    """A1. IdempotencyKey valid UUID parsing, canonical string, and generation."""
    key = IdempotencyKey.generate()
    assert isinstance(key.value, str)
    parsed = uuid.UUID(key.value)
    assert parsed.version == 4
    assert str(key) == key.value

    # Parse valid UUID object
    raw = uuid.uuid4()
    assert IdempotencyKey(raw).value == str(raw)  # type: ignore[arg-type]
    assert IdempotencyKey(str(raw)).value == str(raw)


def test_idempotency_key_invalid_formats_rejected() -> None:
    """A2. IdempotencyKey rejects malformed strings, non-UUIDs, and invalid types."""
    for bad in ["", "   ", "not-a-uuid", "12345", "g" * 36]:
        with pytest.raises(ValueError, match="Invalid IdempotencyKey format"):
            IdempotencyKey(bad)

    bad_types: list[object] = [None, 12345, [], {}]
    for bad_type in bad_types:
        with pytest.raises(
            TypeError, match="IdempotencyKey value must be a string or UUID instance"
        ):
            IdempotencyKey(bad_type)  # type: ignore[arg-type]


def test_idempotency_key_lineage_reuse() -> None:
    """A3. Multiple attempts of the same logical mutation lineage must reuse the same key."""
    action_id = ActionId.generate()
    shared_key = IdempotencyKey.generate()
    t0 = datetime.now(UTC)

    attempt_1 = ExecutionAttempt.create(
        action_id=action_id,
        idempotency_key=shared_key,
        attempt_number=1,
        started_at=t0,
    )
    attempt_2 = ExecutionAttempt.create(
        action_id=action_id,
        idempotency_key=shared_key,
        attempt_number=2,
        started_at=t0 + timedelta(seconds=2),
    )

    assert attempt_1.idempotency_key == attempt_2.idempotency_key == shared_key
    assert attempt_1.action_id == attempt_2.action_id == action_id
    assert attempt_1.attempt_number == 1
    assert attempt_2.attempt_number == 2
    assert attempt_1.attempt_id != attempt_2.attempt_id


def test_idempotency_key_immutability() -> None:
    """A4. IdempotencyKey is frozen and immutable."""
    key = IdempotencyKey.generate()
    with pytest.raises(FrozenInstanceError):
        key.value = "new-value"  # type: ignore[misc]


def test_retry_strategy_vocabulary() -> None:
    """B1. RetryStrategy defines exact three-value vocabulary without blind retry."""
    assert len(RetryStrategy) == 3
    assert set(RetryStrategy) == {
        RetryStrategy.NO_RETRY,
        RetryStrategy.IDEMPOTENT_RETRY,
        RetryStrategy.READ_BEFORE_RETRY,
    }
    assert RetryStrategy.NO_RETRY.value == "NO_RETRY"
    assert RetryStrategy.IDEMPOTENT_RETRY.value == "IDEMPOTENT_RETRY"
    assert RetryStrategy.READ_BEFORE_RETRY.value == "READ_BEFORE_RETRY"

    # Unsupported strategy rejected
    for bad in ["BLIND_RETRY", "EXPONENTIAL", "INFINITE"]:
        with pytest.raises(ValueError, match="is not a valid RetryStrategy"):
            RetryStrategy(bad)


def test_retry_policy_no_retry_enforces_max_attempts_one() -> None:
    """B2. NO_RETRY must strictly enforce max_attempts == 1."""
    policy = RetryPolicy.no_retry()
    assert policy.strategy == RetryStrategy.NO_RETRY
    assert policy.max_attempts == 1

    # Attempting max_attempts != 1 with NO_RETRY must fail
    for attempts in [2, 3, 5]:
        with pytest.raises(ValueError, match="NO_RETRY strategy requires max_attempts == 1"):
            RetryPolicy(strategy=RetryStrategy.NO_RETRY, max_attempts=attempts)


def test_retry_policy_ceiling_and_bounds() -> None:
    """B3. RetryPolicy enforces bounded finite max_attempts and ceiling."""
    assert MAX_RETRY_ATTEMPTS_CEILING == 5

    # Valid within ceiling
    p_idemp = RetryPolicy.idempotent(max_attempts=3)
    assert p_idemp.strategy == RetryStrategy.IDEMPOTENT_RETRY
    assert p_idemp.max_attempts == 3

    p_read = RetryPolicy.read_before_retry(max_attempts=5)
    assert p_read.strategy == RetryStrategy.READ_BEFORE_RETRY
    assert p_read.max_attempts == 5

    # Exceeding ceiling rejected
    with pytest.raises(
        ValueError, match=f"exceeds maximum ceiling of {MAX_RETRY_ATTEMPTS_CEILING}"
    ):
        RetryPolicy(strategy=RetryStrategy.IDEMPOTENT_RETRY, max_attempts=6)

    # Less than 1 rejected
    for bad_count in [0, -1, -5]:
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            RetryPolicy(strategy=RetryStrategy.IDEMPOTENT_RETRY, max_attempts=bad_count)

    # Non-integer rejected (including bool)
    for bad_val in [True, False, 1.5, "3", None]:
        with pytest.raises(TypeError, match="max_attempts must be an integer"):
            RetryPolicy(strategy=RetryStrategy.IDEMPOTENT_RETRY, max_attempts=bad_val)  # type: ignore[arg-type]


def test_retry_policy_immutability() -> None:
    """B4. RetryPolicy is frozen."""
    policy = RetryPolicy.idempotent(2)
    with pytest.raises(FrozenInstanceError):
        policy.max_attempts = 4  # type: ignore[misc]


def test_attempt_id_semantics() -> None:
    """C1. AttemptId generation, validation, and immutability."""
    aid = AttemptId.generate()
    assert isinstance(aid.value, str)
    parsed = uuid.UUID(aid.value)
    assert parsed.version == 4
    assert str(aid) == aid.value

    # Parse UUID object
    raw = uuid.uuid4()
    assert AttemptId(raw).value == str(raw)  # type: ignore[arg-type]

    # Malformed rejected
    with pytest.raises(ValueError, match="Invalid AttemptId format"):
        AttemptId("invalid-attempt-id")

    with pytest.raises(TypeError, match="AttemptId value must be a string or UUID instance"):
        AttemptId(123)  # type: ignore[arg-type]


def test_execution_attempt_validation_and_normalization() -> None:
    """C2. ExecutionAttempt validation, 1-based attempt number, and UTC timestamp normalization."""
    act_id = ActionId.generate()
    idem_key = IdempotencyKey.generate()

    # Timezone conversion from non-UTC
    tz_plus_3 = timezone(timedelta(hours=3))
    t_local = datetime(2026, 9, 29, 15, 0, 0, tzinfo=tz_plus_3)
    attempt = ExecutionAttempt.create(
        action_id=act_id,
        idempotency_key=idem_key,
        attempt_number=1,
        started_at=t_local,
    )
    assert attempt.started_at.tzinfo == UTC
    assert attempt.started_at == datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)

    # Naive timestamp rejected
    with pytest.raises(ValueError, match="started_at must be timezone-aware"):
        ExecutionAttempt.create(
            action_id=act_id,
            idempotency_key=idem_key,
            attempt_number=1,
            started_at=datetime(2026, 9, 29, 12, 0, 0),
        )

    # 0 or negative attempt number rejected
    for bad_num in [0, -1, -10]:
        with pytest.raises(ValueError, match="attempt_number must be >= 1"):
            ExecutionAttempt.create(
                action_id=act_id,
                idempotency_key=idem_key,
                attempt_number=bad_num,
            )

    # Bool and non-integer attempt numbers rejected
    for bad_val in [True, False, 1.0, "1"]:
        with pytest.raises(TypeError, match="attempt_number must be an integer"):
            ExecutionAttempt(
                action_id=act_id,
                idempotency_key=idem_key,
                attempt_number=bad_val,  # type: ignore[arg-type]
                started_at=datetime.now(UTC),
            )

    # Type validation of IDs
    with pytest.raises(TypeError, match="action_id must be an ActionId"):
        ExecutionAttempt(
            action_id="bad",  # type: ignore[arg-type]
            idempotency_key=idem_key,
            attempt_number=1,
            started_at=datetime.now(UTC),
        )

    with pytest.raises(TypeError, match="idempotency_key must be an IdempotencyKey"):
        ExecutionAttempt(
            action_id=act_id,
            idempotency_key="bad",  # type: ignore[arg-type]
            attempt_number=1,
            started_at=datetime.now(UTC),
        )


def test_execution_attempt_result_separation() -> None:
    """C3. ExecutionAttempt does not fabricate outcome or mutate state."""
    attempt = ExecutionAttempt.create(
        action_id=ActionId.generate(),
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
    )
    # ExecutionAttempt has only metadata fields
    field_names = set(attempt.__dataclass_fields__)
    assert field_names == {
        "action_id",
        "idempotency_key",
        "attempt_number",
        "started_at",
        "attempt_id",
    }

    # No outcome, result, state, or verified fields
    assert not hasattr(attempt, "outcome")
    assert not hasattr(attempt, "result")
    assert not hasattr(attempt, "status")
    assert not hasattr(attempt, "state")


def test_resource_binding_unresolved_creation() -> None:
    """D1. Creation actions can exist with resolved_target=None without fabricating IDs."""
    parent_target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="demo-task-list",
    )
    binding = ResourceBinding.unresolved(parent_target)

    assert binding.requested_target == parent_target
    assert binding.resolved_target is None
    assert binding.is_resolved is False


def test_resource_binding_resolution() -> None:
    """D2. ResourceBinding can be resolved later with concrete TargetIdentity."""
    parent_target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="demo-task-list",
    )
    binding = ResourceBinding.unresolved(parent_target)

    concrete_child = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task-generated-by-google-456",
        parent_id="demo-task-list",
    )
    resolved_binding = binding.with_resolved(concrete_child)

    assert resolved_binding.requested_target == parent_target
    assert resolved_binding.resolved_target == concrete_child
    assert resolved_binding.is_resolved is True
    # Original remains unresolved (immutability)
    assert binding.resolved_target is None
    assert binding.is_resolved is False


def test_resource_binding_parent_not_treated_as_created_task() -> None:
    """D3. Parent task list cannot be passed as resolved child task resource."""
    parent_target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="demo-task-list",
    )
    with pytest.raises(
        ValueError, match="Parent task list cannot be treated as the resolved child task resource"
    ):
        ResourceBinding(
            requested_target=parent_target,
            resolved_target=parent_target,
        )


def test_resource_binding_system_mismatch_rejected() -> None:
    """D4. Resolved target must match requested target system."""
    req = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="demo-task-list",
    )
    bad_res = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-123",
    )
    with pytest.raises(ValueError, match="does not match requested target system"):
        ResourceBinding(requested_target=req, resolved_target=bad_res)


def test_resource_binding_immutability() -> None:
    """D5. ResourceBinding is frozen."""
    target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-1",
    )
    binding = ResourceBinding.unresolved(target)
    with pytest.raises(FrozenInstanceError):
        binding.resolved_target = target  # type: ignore[misc]


def test_reconciliation_reason_vocabulary() -> None:
    """E1. ReconciliationReason defines exact bounded vocabulary."""
    assert len(ReconciliationReason) == 3
    assert set(ReconciliationReason) == {
        ReconciliationReason.POST_EXECUTION_VERIFY,
        ReconciliationReason.EXPLICIT_USER_CHECK,
        ReconciliationReason.FRESHNESS_REFRESH,
    }
    assert ReconciliationReason.POST_EXECUTION_VERIFY.value == "POST_EXECUTION_VERIFY"
    assert ReconciliationReason.EXPLICIT_USER_CHECK.value == "EXPLICIT_USER_CHECK"
    assert ReconciliationReason.FRESHNESS_REFRESH.value == "FRESHNESS_REFRESH"

    with pytest.raises(ValueError, match="is not a valid ReconciliationReason"):
        ReconciliationReason("PERIODIC_SYNC")


def test_predicate_scope_all_and_selective() -> None:
    """E2. PredicateScope distinguishes all-required from selective scopes."""
    # All required
    scope_all = PredicateScope.all()
    assert scope_all.all_required is True
    assert scope_all.selected_predicates == ()

    # Selective non-empty unique
    p1 = PredicateId.generate()
    p2 = PredicateId.generate()
    scope_sel = PredicateScope.selective([p1, p2])
    assert scope_sel.all_required is False
    assert scope_sel.selected_predicates == (p1, p2)


def test_predicate_scope_invalid_configurations_rejected() -> None:
    """E3. PredicateScope rejects empty selective, duplicate predicates, and bad types."""
    # Empty selective rejected
    with pytest.raises(
        ValueError, match="selected_predicates must be non-empty when all_required is False"
    ):
        PredicateScope.selective([])

    # Duplicate predicate in selective rejected
    p1 = PredicateId.generate()
    with pytest.raises(ValueError, match="Duplicate PredicateId in selected_predicates"):
        PredicateScope.selective([p1, p1])

    # Non-empty predicates when all_required is True rejected
    with pytest.raises(
        ValueError, match="selected_predicates must be empty when all_required is True"
    ):
        PredicateScope(all_required=True, selected_predicates=(p1,))

    # Non-PredicateId element rejected
    with pytest.raises(TypeError, match="selected_predicates must contain PredicateId instances"):
        PredicateScope(all_required=False, selected_predicates=("not-a-predicate-id",))  # type: ignore[arg-type]


def test_reconciliation_request_creation_and_normalization() -> None:
    """E4. ReconciliationRequest binds mission, reason, UTC timestamp, and scope."""
    mid = MissionId.generate()
    tz_minus_8 = timezone(timedelta(hours=-8))
    t_local = datetime(2026, 9, 29, 4, 30, 0, tzinfo=tz_minus_8)

    req = ReconciliationRequest.create(
        mission_id=mid,
        reason=ReconciliationReason.EXPLICIT_USER_CHECK,
        requested_at=t_local,
    )
    assert req.mission_id == mid
    assert req.reason == ReconciliationReason.EXPLICIT_USER_CHECK
    assert req.requested_at.tzinfo == UTC
    assert req.requested_at == datetime(2026, 9, 29, 12, 30, 0, tzinfo=UTC)
    assert req.scope.all_required is True

    # Naive timestamp rejected
    with pytest.raises(ValueError, match="requested_at must be timezone-aware"):
        ReconciliationRequest.create(
            mission_id=mid,
            reason=ReconciliationReason.FRESHNESS_REFRESH,
            requested_at=datetime(2026, 9, 29, 12, 0, 0),
        )

    # String reason conversion
    req2 = ReconciliationRequest.create(
        mission_id=mid,
        reason="POST_EXECUTION_VERIFY",
    )
    assert req2.reason == ReconciliationReason.POST_EXECUTION_VERIFY

    # Unsupported reason rejected
    with pytest.raises(ValueError, match="Unsupported reconciliation reason"):
        ReconciliationRequest.create(
            mission_id=mid,
            reason="INVALID_REASON",
        )


def test_reconciliation_request_is_request_contract_only() -> None:
    """E5. ReconciliationRequest has no evaluation, execution, or mutation methods."""
    mid = MissionId.generate()
    req = ReconciliationRequest.create(
        mission_id=mid,
        reason=ReconciliationReason.POST_EXECUTION_VERIFY,
    )
    # Only request fields
    fields = set(req.__dataclass_fields__)
    assert fields == {"mission_id", "reason", "requested_at", "scope"}
    assert not hasattr(req, "evaluate")
    assert not hasattr(req, "execute")
    assert not hasattr(req, "read_providers")
    assert not hasattr(req, "calculate_ready")
    assert not hasattr(req, "calculate_drifted")


def test_provider_purity() -> None:
    """F. Domain execution module does not import external/provider SDKs."""
    forbidden = [
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
    ]
    for mod in forbidden:
        assert mod not in sys.modules, f"Forbidden provider module imported: {mod}"
