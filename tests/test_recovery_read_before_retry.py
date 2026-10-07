"""Tests for read-before-retry and verify-after-timeout orchestration (Phase P-10.03).

Enforces StillDone core architectural laws:
- A retry is not allowed to create a second effect merely because the first response was lost.
- Ambiguous timeout on mutation never blindly retries; requires verification.
- CALENDAR_UPDATE:
  * timeout requires read-back;
  * effect already exists -> no redundant execution (EFFECT_ALREADY_EXISTS);
  * effect absent -> retry permitted within bounded ceiling;
  * inconclusive verification fails closed (DO_NOT_RETRY).
- TASK_CREATE:
  * high duplicate risk requires read-before-retry;
  * intended task creation proven -> do not create second task (EFFECT_ALREADY_EXISTS);
  * effect absent -> retry permitted within bounded ceiling;
  * inconclusive verification fails closed (DO_NOT_RETRY).
- Read-only actions preserve safer retry semantics.
- Model / planner output has ZERO authority over recovery decisions.
- Pure deterministic calculations with zero network calls and zero sleeps.
"""

from __future__ import annotations

import pytest

from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.mission import MissionId
from stilldone.planning.contracts import PlannerInput
from stilldone.recovery.idempotency import (
    PlannerRecoveryAuthorityError,
    derive_idempotency_key,
    get_idempotency_strategy,
)
from stilldone.recovery.orchestrator import (
    ReadbackOutcome,
    ReadbackVerificationResult,
    RecoveryActionType,
    RecoveryLineageError,
    RecoveryOrchestrator,
    evaluate_post_execution_recovery,
    evaluate_readback_recovery,
)
from stilldone.recovery.retry import (
    RetryClassification,
    RetryPolicy,
)

CAL_TARGET = TargetIdentity(
    system="google_calendar",
    resource_kind=ResourceKind.CALENDAR_EVENT,
    resource_id="event_123",
    parent_id="primary",
)

TASKS_TARGET = TargetIdentity(
    system="google_tasks",
    resource_kind=ResourceKind.TASK_LIST,
    resource_id="default",
    parent_id=None,
)

WEATHER_TARGET = TargetIdentity(
    system="open_meteo",
    resource_kind=ResourceKind.WEATHER_LOCATION,
    resource_id="loc_123",
    parent_id=None,
)


def _make_action(action_type: ActionType, target: TargetIdentity) -> ActionContract:
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=action_type,
        target=target,
        parameters={"title": "Pack bags"} if action_type == ActionType.TASK_CREATE else {},
    )


class TestCalendarUpdateRecovery:
    """Verifies recovery orchestration for CALENDAR_UPDATE mutations."""

    def test_ambiguous_timeout_requires_verification_before_retry(self) -> None:
        action = _make_action(ActionType.CALENDAR_UPDATE, CAL_TARGET)
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=TimeoutError("Calendar gateway timed out"),
        )
        assert decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION
        assert decision.attempt_number == 1
        assert decision.delay_seconds == 0.0
        assert decision.retry_classification == RetryClassification.AMBIGUOUS_TIMEOUT
        assert decision.idempotency_key == derive_idempotency_key(action, 1)

    def test_calendar_update_transient_failure_requires_verification_not_blind_retry(
        self,
    ) -> None:
        """Regression test for Defect 1:

        CALENDAR_UPDATE + retryable transient + allows_blind_retry=False
        => MUST NOT produce direct RETRY
        => MUST require independent verification/read-back.
        """
        action = _make_action(ActionType.CALENDAR_UPDATE, CAL_TARGET)
        strategy = get_idempotency_strategy(action)
        assert strategy.allows_blind_retry is False

        # Transient 503 error
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error="Calendar backend unavailable (status 503)",
        )
        # Must require verification, NOT blind retry
        assert decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION
        assert decision.attempt_number == 1
        assert decision.delay_seconds == 0.0
        assert decision.retry_classification == RetryClassification.RETRYABLE_TRANSIENT
        assert "allows_blind_retry=False" in decision.reason
        assert decision.idempotency_key == derive_idempotency_key(action, 1)

    def test_readback_intended_effect_exists_prevents_second_execution(self) -> None:
        action = _make_action(ActionType.CALENDAR_UPDATE, CAL_TARGET)
        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.INTENDED_EFFECT_EXISTS,
            action_id=action.action_id,
            match_count=1,
        )
        decision = evaluate_readback_recovery(
            action=action,
            attempt_number=1,
            readback_result=readback,
        )
        assert decision.action_type == RecoveryActionType.EFFECT_ALREADY_EXISTS
        assert decision.attempt_number == 1
        assert decision.delay_seconds == 0.0
        assert decision.readback_outcome == ReadbackOutcome.INTENDED_EFFECT_EXISTS
        assert "intended effect already exists" in decision.reason

    def test_readback_effect_absent_allows_bounded_retry(self) -> None:
        action = _make_action(ActionType.CALENDAR_UPDATE, CAL_TARGET)
        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.EFFECT_ABSENT,
            action_id=action.action_id,
            match_count=0,
        )
        decision = evaluate_readback_recovery(
            action=action,
            attempt_number=1,
            readback_result=readback,
            policy=RetryPolicy(max_attempts=3, base_delay_seconds=2.0),
        )
        assert decision.action_type == RecoveryActionType.RETRY
        assert decision.attempt_number == 1
        assert decision.delay_seconds == 2.0
        assert decision.readback_outcome == ReadbackOutcome.EFFECT_ABSENT

    def test_readback_effect_absent_at_ceiling_prohibits_retry(self) -> None:
        action = _make_action(ActionType.CALENDAR_UPDATE, CAL_TARGET)
        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.EFFECT_ABSENT,
            action_id=action.action_id,
            match_count=0,
        )
        # Attempt 3 reaches ceiling
        decision = evaluate_readback_recovery(
            action=action,
            attempt_number=3,
            readback_result=readback,
            policy=RetryPolicy(max_attempts=3),
        )
        assert decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert "ceiling reached" in decision.reason.lower()

    def test_readback_inconclusive_fails_closed(self) -> None:
        action = _make_action(ActionType.CALENDAR_UPDATE, CAL_TARGET)
        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.INCONCLUSIVE,
            action_id=action.action_id,
            error_message="Calendar read failed with 500 internal server error",
        )
        decision = evaluate_readback_recovery(
            action=action,
            attempt_number=1,
            readback_result=readback,
        )
        assert decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert decision.readback_outcome == ReadbackOutcome.INCONCLUSIVE
        assert "inconclusive" in decision.reason.lower()


class TestTaskCreateRecovery:
    """Verifies recovery orchestration for TASK_CREATE high-duplicate-risk mutations."""

    def test_ambiguous_timeout_requires_read_before_retry(self) -> None:
        action = _make_action(ActionType.TASK_CREATE, TASKS_TARGET)
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=TimeoutError("Tasks connection timed out after write"),
        )
        assert decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION
        assert decision.retry_classification == RetryClassification.AMBIGUOUS_TIMEOUT

    def test_transient_error_on_task_create_requires_read_before_retry(self) -> None:
        action = _make_action(ActionType.TASK_CREATE, TASKS_TARGET)
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=503,  # Service Unavailable
        )
        # Because TASK_CREATE has requires_read_before_retry=True, must verify before retry!
        assert decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION
        assert "read-before-retry" in decision.reason

    def test_read_before_retry_finds_intended_task_prevents_duplicate_create(self) -> None:
        action = _make_action(ActionType.TASK_CREATE, TASKS_TARGET)
        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.INTENDED_EFFECT_EXISTS,
            action_id=action.action_id,
            match_count=1,
        )
        decision = evaluate_readback_recovery(
            action=action,
            attempt_number=1,
            readback_result=readback,
        )
        assert decision.action_type == RecoveryActionType.EFFECT_ALREADY_EXISTS
        assert decision.delay_seconds == 0.0

    def test_read_before_retry_finds_duplicate_prevents_further_mutation(self) -> None:
        action = _make_action(ActionType.TASK_CREATE, TASKS_TARGET)
        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.DUPLICATE_DETECTED,
            action_id=action.action_id,
            match_count=2,
        )
        decision = evaluate_readback_recovery(
            action=action,
            attempt_number=1,
            readback_result=readback,
        )
        assert decision.action_type == RecoveryActionType.DUPLICATE_PREVENTED
        assert decision.readback_outcome == ReadbackOutcome.DUPLICATE_DETECTED
        assert "duplicate effect detected" in decision.reason.lower()

    def test_read_before_retry_effect_absent_allows_bounded_retry(self) -> None:
        action = _make_action(ActionType.TASK_CREATE, TASKS_TARGET)
        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.EFFECT_ABSENT,
            action_id=action.action_id,
            match_count=0,
        )
        decision = evaluate_readback_recovery(
            action=action,
            attempt_number=1,
            readback_result=readback,
            policy=RetryPolicy(max_attempts=3, base_delay_seconds=1.5, backoff_multiplier=2.0),
        )
        assert decision.action_type == RecoveryActionType.RETRY
        assert decision.delay_seconds == 1.5

    def test_inconclusive_scan_fails_closed(self) -> None:
        action = _make_action(ActionType.TASK_CREATE, TASKS_TARGET)
        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.INCONCLUSIVE,
            action_id=action.action_id,
            error_message="Tasks scan pagination limit exceeded",
        )
        decision = evaluate_readback_recovery(
            action=action,
            attempt_number=1,
            readback_result=readback,
        )
        assert decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert "failing closed" in decision.reason.lower()


class TestReadOnlyActionRecovery:
    """Verifies that read-only actions retain safe direct retry semantics."""

    @pytest.mark.parametrize(
        ("action_type", "target"),
        [
            (ActionType.CALENDAR_READ, CAL_TARGET),
            (ActionType.TASK_READ, TASKS_TARGET),
            (ActionType.WEATHER_READ, WEATHER_TARGET),
        ],
    )
    def test_read_actions_retry_ambiguous_timeout_directly(
        self, action_type: ActionType, target: TargetIdentity
    ) -> None:
        action = _make_action(action_type, target)
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=TimeoutError("Read deadline exceeded"),
        )
        assert decision.action_type == RecoveryActionType.RETRY
        assert decision.delay_seconds > 0.0

    @pytest.mark.parametrize(
        ("action_type", "target"),
        [
            (ActionType.CALENDAR_READ, CAL_TARGET),
            (ActionType.TASK_READ, TASKS_TARGET),
            (ActionType.WEATHER_READ, WEATHER_TARGET),
        ],
    )
    def test_read_actions_retry_transient_failure_directly(
        self, action_type: ActionType, target: TargetIdentity
    ) -> None:
        action = _make_action(action_type, target)
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=429,
        )
        assert decision.action_type == RecoveryActionType.RETRY
        assert decision.delay_seconds > 0.0


class TestPermanentAndSecurityFailures:
    """Verifies fail-closed behavior for non-retryable errors."""

    def test_authority_error_fails_closed(self) -> None:
        action = _make_action(ActionType.CALENDAR_UPDATE, CAL_TARGET)
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=403,
        )
        assert decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert decision.retry_classification == RetryClassification.AUTHORITY_SECURITY_FAILURE

    def test_programming_contract_error_fails_closed(self) -> None:
        action = _make_action(ActionType.TASK_CREATE, TASKS_TARGET)
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=ValueError("Invalid field type"),
        )
        assert decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert decision.retry_classification == RetryClassification.CONTRACT_PROGRAMMING_FAILURE

    def test_successful_execution_requires_no_recovery(self) -> None:
        action = _make_action(ActionType.TASK_CREATE, TASKS_TARGET)
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=None,
        )
        assert decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert "succeeded" in decision.reason.lower()


class TestModelAuthorityRejection:
    """Verifies that model / planner proposals have zero authority over recovery."""

    def test_planner_input_as_action_rejected(self) -> None:
        planner_input = PlannerInput(
            mission_id=MissionId.generate(),
            intent="retry please",
        )
        with pytest.raises(PlannerRecoveryAuthorityError):
            evaluate_post_execution_recovery(
                action=planner_input,  # type: ignore[arg-type]
                attempt_number=1,
                error=TimeoutError("timeout"),
            )

    def test_planner_input_as_readback_rejected(self) -> None:
        action = _make_action(ActionType.CALENDAR_UPDATE, CAL_TARGET)
        planner_input = PlannerInput(
            mission_id=MissionId.generate(),
            intent="readback ok",
        )
        with pytest.raises(PlannerRecoveryAuthorityError):
            evaluate_readback_recovery(
                action=action,
                attempt_number=1,
                readback_result=planner_input,  # type: ignore[arg-type]
            )


class TestLineageAndIntegrity:
    """Verifies lineage enforcement and error sanitization."""

    def test_mismatched_action_id_raises_lineage_error(self) -> None:
        action = _make_action(ActionType.CALENDAR_UPDATE, CAL_TARGET)
        other_action_id = ActionId.generate()
        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.INTENDED_EFFECT_EXISTS,
            action_id=other_action_id,
        )
        with pytest.raises(RecoveryLineageError):
            evaluate_readback_recovery(
                action=action,
                attempt_number=1,
                readback_result=readback,
            )

    def test_recovery_orchestrator_class_coordination(self) -> None:
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0)
        orchestrator = RecoveryOrchestrator(policy=policy)
        assert orchestrator.policy == policy

        action = _make_action(ActionType.TASK_CREATE, TASKS_TARGET)
        d1 = orchestrator.evaluate_execution_failure(
            action=action,
            attempt_number=1,
            error=TimeoutError("timeout"),
        )
        assert d1.action_type == RecoveryActionType.REQUIRES_VERIFICATION

        readback = ReadbackVerificationResult(
            outcome=ReadbackOutcome.EFFECT_ABSENT,
            action_id=action.action_id,
        )
        d2 = orchestrator.evaluate_readback_outcome(
            action=action,
            attempt_number=1,
            readback_result=readback,
        )
        assert d2.action_type == RecoveryActionType.RETRY
        assert d2.delay_seconds == 1.0
