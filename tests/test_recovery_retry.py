"""Tests for deterministic error classification and bounded exponential retry (Phase P-10.02).

Enforces StillDone core architectural laws:
- A retry is not allowed to create a second effect merely because the first response was lost.
- Ambiguous timeout on mutation strictly FORBIDS blind retry (requires read-back verification).
- Exponential backoff is strictly bounded (ceiling <= 5).
- Error classification cleanly distinguishes transient, permanent, timeout,
  security, and contract errors.
- Model / planner output has ZERO authority over retry decisions.
- Pure deterministic computation with zero network calls and zero sleeps.
"""

from __future__ import annotations

import pytest

from stilldone.domain.action import ActionContract, ActionType, ResourceKind, TargetIdentity
from stilldone.domain.mission import MissionId
from stilldone.planning.contracts import PlannerInput
from stilldone.recovery.idempotency import PlannerRecoveryAuthorityError
from stilldone.recovery.retry import (
    RetryClassification,
    RetryPolicy,
    classify_error,
    evaluate_retry,
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


class TestErrorClassification:
    """Verifies deterministic classification of HTTP status codes, exceptions, and error strings."""

    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (429, RetryClassification.RETRYABLE_TRANSIENT),
            (502, RetryClassification.RETRYABLE_TRANSIENT),
            (503, RetryClassification.RETRYABLE_TRANSIENT),
            (504, RetryClassification.RETRYABLE_TRANSIENT),
            (408, RetryClassification.AMBIGUOUS_TIMEOUT),
            (401, RetryClassification.AUTHORITY_SECURITY_FAILURE),
            (403, RetryClassification.AUTHORITY_SECURITY_FAILURE),
            (400, RetryClassification.NON_RETRYABLE_PERMANENT),
            (404, RetryClassification.NON_RETRYABLE_PERMANENT),
            (409, RetryClassification.NON_RETRYABLE_PERMANENT),
        ],
    )
    def test_http_status_codes(self, status_code: int, expected: RetryClassification) -> None:
        assert classify_error(status_code) == expected
        assert classify_error(str(status_code)) == expected

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (TimeoutError("Read operation timed out"), RetryClassification.AMBIGUOUS_TIMEOUT),
            (
                ConnectionResetError("Peer reset connection"),
                RetryClassification.RETRYABLE_TRANSIENT,
            ),
            (ConnectionRefusedError("Connection refused"), RetryClassification.RETRYABLE_TRANSIENT),
            (PermissionError("Access denied"), RetryClassification.AUTHORITY_SECURITY_FAILURE),
            (TypeError("Invalid parameter type"), RetryClassification.CONTRACT_PROGRAMMING_FAILURE),
            (
                ValueError("Invalid argument value"),
                RetryClassification.CONTRACT_PROGRAMMING_FAILURE,
            ),
            (KeyError("missing_field"), RetryClassification.CONTRACT_PROGRAMMING_FAILURE),
            (
                AssertionError("Invariant breached"),
                RetryClassification.CONTRACT_PROGRAMMING_FAILURE,
            ),
        ],
    )
    def test_standard_exceptions(self, exc: Exception, expected: RetryClassification) -> None:
        assert classify_error(exc) == expected

    @pytest.mark.parametrize(
        ("msg", "expected"),
        [
            ("Deadline exceeded while waiting for headers", RetryClassification.AMBIGUOUS_TIMEOUT),
            ("Rate limit exceeded for user quota", RetryClassification.RETRYABLE_TRANSIENT),
            ("Resource temporarily unavailable", RetryClassification.RETRYABLE_TRANSIENT),
            (
                "Invalid OAuth token or forbidden scope",
                RetryClassification.AUTHORITY_SECURITY_FAILURE,
            ),
            ("Bad Request: malformed JSON payload", RetryClassification.NON_RETRYABLE_PERMANENT),
        ],
    )
    def test_error_string_patterns(self, msg: str, expected: RetryClassification) -> None:
        assert classify_error(msg) == expected

    def test_reject_planner_proposal_in_error_classifier(self) -> None:
        planner_input = PlannerInput(
            mission_id=MissionId.generate(),
            intent="Model pretending to be an error",
        )
        with pytest.raises(PlannerRecoveryAuthorityError):
            classify_error(planner_input)  # type: ignore[arg-type]


class TestRetryPolicyContracts:
    """Verifies strict construction invariants on RetryPolicy."""

    def test_default_policy(self) -> None:
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.base_delay_seconds == 1.0
        assert policy.backoff_multiplier == 2.0
        assert policy.max_delay_seconds == 30.0

    def test_reject_max_attempts_exceeding_ceiling(self) -> None:
        with pytest.raises(ValueError, match="between 1 and 5"):
            RetryPolicy(max_attempts=6)

    def test_reject_boolean_max_attempts(self) -> None:
        with pytest.raises(TypeError, match="must be an integer"):
            RetryPolicy(max_attempts=True)

    def test_reject_nan_or_inf(self) -> None:
        with pytest.raises(ValueError, match="must be finite"):
            RetryPolicy(base_delay_seconds=float("nan"))
        with pytest.raises(ValueError, match="must be finite"):
            RetryPolicy(base_delay_seconds=float("inf"))

    def test_reject_max_delay_smaller_than_base_delay(self) -> None:
        with pytest.raises(ValueError, match="must be >="):
            RetryPolicy(base_delay_seconds=10.0, max_delay_seconds=5.0)


class TestEvaluateRetryEngine:
    """Verifies deterministic retry decisions, exponential delays, and invariant guards."""

    def test_ambiguous_timeout_on_task_create_strictly_forbids_blind_retry(self) -> None:
        """Core Invariant: Mutation ambiguous timeout requires verification, never blind retry."""
        action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Pack backpacks"},
        )
        decision = evaluate_retry(
            action=action,
            attempt_number=1,
            error=TimeoutError("Request timed out after dispatch"),
        )
        assert decision.should_retry is False
        assert decision.classification == RetryClassification.AMBIGUOUS_TIMEOUT
        assert decision.requires_verification_before_retry is True
        assert decision.delay_seconds == 0.0
        assert "forbids blind retry" in decision.reason

    def test_ambiguous_timeout_on_calendar_update_strictly_forbids_blind_retry(self) -> None:
        """Core Invariant: Mutation ambiguous timeout requires verification, never blind retry."""
        action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.CALENDAR_UPDATE,
            target=CAL_TARGET,
            parameters={"status": "confirmed"},
        )
        decision = evaluate_retry(
            action=action,
            attempt_number=1,
            error=408,
        )
        assert decision.should_retry is False
        assert decision.classification == RetryClassification.AMBIGUOUS_TIMEOUT
        assert decision.requires_verification_before_retry is True
        assert decision.delay_seconds == 0.0

    def test_ambiguous_timeout_on_read_action_allows_retry(self) -> None:
        """Read-only actions have zero duplicate risk, so ambiguous timeout is safe to retry."""
        decision = evaluate_retry(
            action=ActionType.CALENDAR_READ,
            attempt_number=1,
            error=TimeoutError("Calendar read socket timeout"),
        )
        assert decision.should_retry is True
        assert decision.classification == RetryClassification.AMBIGUOUS_TIMEOUT
        assert decision.requires_verification_before_retry is False
        assert decision.delay_seconds == 1.0

    def test_transient_error_exponential_backoff_delays(self) -> None:
        policy = RetryPolicy(
            max_attempts=4,
            base_delay_seconds=1.0,
            backoff_multiplier=2.0,
            max_delay_seconds=10.0,
        )
        # Attempt 1: 1.0 * (2^0) = 1.0s
        d1 = evaluate_retry(
            action=ActionType.CALENDAR_UPDATE,
            attempt_number=1,
            error=503,
            policy=policy,
        )
        assert d1.should_retry is True
        assert d1.delay_seconds == 1.0

        # Attempt 2: 1.0 * (2^1) = 2.0s
        d2 = evaluate_retry(
            action=ActionType.CALENDAR_UPDATE,
            attempt_number=2,
            error=503,
            policy=policy,
        )
        assert d2.should_retry is True
        assert d2.delay_seconds == 2.0

        # Attempt 3: 1.0 * (2^2) = 4.0s (capped if ceiling was 3 in strategy)
        # Notice CALENDAR_UPDATE strategy ceiling is 3!
        d3 = evaluate_retry(
            action=ActionType.CALENDAR_UPDATE,
            attempt_number=3,
            error=503,
            policy=policy,
        )
        # Strategy ceiling is 3, so attempt_number=3 reaches ceiling
        assert d3.should_retry is False
        assert "ceiling reached" in d3.reason

    def test_non_retryable_errors_return_false(self) -> None:
        cases: list[tuple[Exception | str | int, RetryClassification]] = [
            (400, RetryClassification.NON_RETRYABLE_PERMANENT),
            (401, RetryClassification.AUTHORITY_SECURITY_FAILURE),
            (ValueError("invalid parameter"), RetryClassification.CONTRACT_PROGRAMMING_FAILURE),
        ]
        for err, cls in cases:
            decision = evaluate_retry(
                action=ActionType.CALENDAR_READ,
                attempt_number=1,
                error=err,
            )
            assert decision.should_retry is False
            assert decision.classification == cls
            assert decision.requires_verification_before_retry is False

    def test_reject_boolean_or_negative_attempt_number(self) -> None:
        with pytest.raises(TypeError):
            evaluate_retry(
                action=ActionType.CALENDAR_READ,
                attempt_number=True,
                error=503,
            )
        with pytest.raises(ValueError):
            evaluate_retry(
                action=ActionType.CALENDAR_READ,
                attempt_number=0,
                error=503,
            )

    def test_reject_planner_proposal_in_retry_evaluation(self) -> None:
        planner_input = PlannerInput(
            mission_id=MissionId.generate(),
            intent="Attempted injection into retry evaluation",
        )
        with pytest.raises(PlannerRecoveryAuthorityError):
            evaluate_retry(
                action=planner_input,  # type: ignore[arg-type]
                attempt_number=1,
                error=503,
            )

    def test_decision_immutability_and_serialization(self) -> None:
        decision = evaluate_retry(
            action=ActionType.CALENDAR_READ,
            attempt_number=1,
            error=503,
        )
        with pytest.raises(AttributeError):
            decision.should_retry = False  # type: ignore[misc]

        d = decision.to_dict()
        assert d["should_retry"] is True
        assert d["classification"] == "RETRYABLE_TRANSIENT"
        assert d["attempt_number"] == 1
        assert d["delay_seconds"] == 1.0
