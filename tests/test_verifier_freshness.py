"""Tests for Phase P-09.03: Freshness and Stale Evaluation.

Validates that:
- Temporal validity is strictly and deterministically computed.
- Pure evaluator: zero implicit wall-clock reads (explicit `at` required).
- All datetimes are timezone-aware and normalized to UTC.
- Exact boundary conditions:
  * observed_at <= at < valid_until => FRESH
  * at >= valid_until => STALE (at exact expiry boundary => STALE)
  * observed_at == at => FRESH
- Future-dated impossible observations (observed_at > at) fail closed.
- Naive datetimes fail closed with NaiveDatetimeError.
- Freshness applies to VerificationObservation, NOT execution results.
- ProviderExecutionResult / ExecutionAttempt cannot substitute for observation.
- Zero network calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from stilldone.domain.action import ActionId, ActionType, ResourceKind, TargetIdentity
from stilldone.domain.desired_state import FreshnessContract
from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
from stilldone.execution.state import ProviderExecutionResult
from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    VerificationObservation,
)
from stilldone.verifier.freshness import (
    FreshnessStatus,
    FutureDatedObservationError,
    NaiveDatetimeError,
    evaluate_freshness,
    evaluate_observation_freshness,
)

# ===========================================================================
# Exact Boundary Matrix Tests
# ===========================================================================


class TestFreshnessExactBoundaryMatrix:
    """Exact mathematical boundary tests for evaluate_freshness."""

    def test_observed_at_equals_at_is_fresh(self) -> None:
        """Observation exactly at evaluation time (age 0.0s) is FRESH."""
        t0 = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        res = evaluate_freshness(
            observed_at=t0,
            at=t0,
            max_age_seconds=60,
        )
        assert res.status == FreshnessStatus.FRESH
        assert res.is_fresh is True
        assert res.is_stale is False
        assert res.age_seconds == 0.0

    def test_within_validity_window_is_fresh(self) -> None:
        """observed_at < at < valid_until is FRESH."""
        t_obs = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_eval = datetime(2026, 10, 6, 7, 30, 30, tzinfo=UTC)  # 30 seconds later
        t_exp = datetime(2026, 10, 6, 7, 31, 0, tzinfo=UTC)  # 60 seconds window
        res = evaluate_freshness(
            observed_at=t_obs,
            at=t_eval,
            valid_until=t_exp,
        )
        assert res.status == FreshnessStatus.FRESH
        assert res.is_fresh is True
        assert res.age_seconds == 30.0

    def test_exact_expiry_boundary_is_stale(self) -> None:
        """At exact expiry boundary (at == valid_until), status must be STALE."""
        t_obs = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_exp = datetime(2026, 10, 6, 7, 31, 0, tzinfo=UTC)  # exactly 60s later
        res = evaluate_freshness(
            observed_at=t_obs,
            at=t_exp,  # evaluated exactly at expiry boundary!
            valid_until=t_exp,
        )
        assert res.status == FreshnessStatus.STALE
        assert res.is_stale is True
        assert res.is_fresh is False
        assert res.age_seconds == 60.0

    def test_past_expiry_is_stale(self) -> None:
        """at > valid_until is STALE."""
        t_obs = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_eval = datetime(2026, 10, 6, 7, 31, 1, tzinfo=UTC)  # 61s later
        res = evaluate_freshness(
            observed_at=t_obs,
            at=t_eval,
            max_age_seconds=60,
        )
        assert res.status == FreshnessStatus.STALE
        assert res.is_stale is True
        assert res.age_seconds == 61.0

    def test_one_microsecond_before_expiry_is_fresh(self) -> None:
        """at = valid_until - 1 microsecond is FRESH."""
        t_obs = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_exp = datetime(2026, 10, 6, 7, 31, 0, tzinfo=UTC)
        t_almost_exp = t_exp - timedelta(microseconds=1)
        res = evaluate_freshness(
            observed_at=t_obs,
            at=t_almost_exp,
            valid_until=t_exp,
        )
        assert res.status == FreshnessStatus.FRESH


# ===========================================================================
# Future-Dated and Naive Datetime Rejection Tests
# ===========================================================================


class TestFreshnessFailClosedRejections:
    """Fail-closed on impossible future observations or unzoned timestamps."""

    def test_future_dated_observation_fails_closed(self) -> None:
        """observed_at > at raises FutureDatedObservationError."""
        t_obs = datetime(2026, 10, 6, 7, 35, 0, tzinfo=UTC)
        t_eval = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)  # 5 minutes before observation!
        with pytest.raises(FutureDatedObservationError, match="in the future"):
            evaluate_freshness(
                observed_at=t_obs,
                at=t_eval,
                max_age_seconds=60,
            )

    def test_naive_observed_at_fails_closed(self) -> None:
        """Naive datetime without tzinfo raises NaiveDatetimeError."""
        t_naive = datetime(2026, 10, 6, 7, 30, 0)
        t_utc = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        with pytest.raises(NaiveDatetimeError, match="timezone-aware"):
            evaluate_freshness(
                observed_at=t_naive,
                at=t_utc,
                max_age_seconds=60,
            )

    def test_naive_at_fails_closed(self) -> None:
        """Naive evaluation point raises NaiveDatetimeError."""
        t_utc = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_naive = datetime(2026, 10, 6, 7, 30, 0)
        with pytest.raises(NaiveDatetimeError, match="timezone-aware"):
            evaluate_freshness(
                observed_at=t_utc,
                at=t_naive,
                max_age_seconds=60,
            )

    def test_naive_valid_until_fails_closed(self) -> None:
        """Naive valid_until raises NaiveDatetimeError."""
        t_utc = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_naive = datetime(2026, 10, 6, 7, 31, 0)
        with pytest.raises(NaiveDatetimeError, match="timezone-aware"):
            evaluate_freshness(
                observed_at=t_utc,
                at=t_utc,
                valid_until=t_naive,
            )

    def test_non_utc_timezone_normalized_to_utc(self) -> None:
        """Timezone-aware datetime with non-UTC offset is correctly normalized."""
        # UTC+3 offset
        tz_plus_3 = timezone(timedelta(hours=3))
        # 10:30 at UTC+3 is 07:30 UTC
        t_obs = datetime(2026, 10, 6, 10, 30, 0, tzinfo=tz_plus_3)
        t_eval = datetime(2026, 10, 6, 7, 30, 20, tzinfo=UTC)  # 20 seconds later
        res = evaluate_freshness(
            observed_at=t_obs,
            at=t_eval,
            max_age_seconds=60,
        )
        assert res.status == FreshnessStatus.FRESH
        assert res.observed_at.tzinfo == UTC
        assert res.evaluated_at.tzinfo == UTC
        assert res.age_seconds == 20.0


# ===========================================================================
# FreshnessContract Integration Tests
# ===========================================================================


class TestFreshnessContractIntegration:
    """Evaluates freshness using canonical FreshnessContract modes."""

    def test_max_age_contract_fresh(self) -> None:
        """FreshnessMode.MAX_AGE within window is FRESH."""
        contract = FreshnessContract.max_age(120)  # 2 minutes
        t_obs = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_eval = datetime(2026, 10, 6, 7, 31, 30, tzinfo=UTC)  # 90s later
        res = evaluate_freshness(
            observed_at=t_obs,
            at=t_eval,
            freshness_contract=contract,
        )
        assert res.status == FreshnessStatus.FRESH

    def test_max_age_contract_stale(self) -> None:
        """FreshnessMode.MAX_AGE outside window is STALE."""
        contract = FreshnessContract.max_age(60)  # 1 minute
        t_obs = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_eval = datetime(2026, 10, 6, 7, 31, 30, tzinfo=UTC)  # 90s later
        res = evaluate_freshness(
            observed_at=t_obs,
            at=t_eval,
            freshness_contract=contract,
        )
        assert res.status == FreshnessStatus.STALE

    def test_current_mode_within_bounded_window_is_fresh(self) -> None:
        """FreshnessMode.CURRENT within default window (300s) is FRESH."""
        contract = FreshnessContract.current()
        t_obs = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_eval = datetime(2026, 10, 6, 7, 33, 0, tzinfo=UTC)  # 180s later (< 300s)
        res = evaluate_freshness(
            observed_at=t_obs,
            at=t_eval,
            freshness_contract=contract,
        )
        assert res.status == FreshnessStatus.FRESH

    def test_current_mode_outside_bounded_window_is_stale(self) -> None:
        """FreshnessMode.CURRENT outside bounded window (300s) is STALE."""
        contract = FreshnessContract.current()
        t_obs = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_eval = datetime(2026, 10, 6, 7, 36, 0, tzinfo=UTC)  # 360s later (> 300s)
        res = evaluate_freshness(
            observed_at=t_obs,
            at=t_eval,
            freshness_contract=contract,
        )
        assert res.status == FreshnessStatus.STALE


# ===========================================================================
# Strict Independence: Observation vs Execution Payload
# ===========================================================================


class TestFreshnessObservationIndependence:
    """Proves execution payloads cannot substitute for verification observation."""

    def test_evaluate_observation_freshness_rejects_provider_result(self) -> None:
        """ProviderExecutionResult is rejected by evaluate_observation_freshness."""
        exec_result = ProviderExecutionResult(
            action_type=ActionType.TASK_CREATE,
            success=True,
            status_name="SUCCESS",
        )
        contract = FreshnessContract.max_age(60)
        t_eval = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        with pytest.raises(ExecutionPayloadSubstitutionError):
            evaluate_observation_freshness(
                exec_result,  # type: ignore[arg-type]
                contract,
                at=t_eval,
            )

    def test_evaluate_observation_freshness_rejects_attempt(self) -> None:
        """ExecutionAttempt is rejected by evaluate_observation_freshness."""
        attempt = ExecutionAttempt(
            action_id=ActionId.generate(),
            idempotency_key=IdempotencyKey.generate(),
            attempt_number=1,
            started_at=datetime.now(UTC),
        )
        contract = FreshnessContract.max_age(60)
        t_eval = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        with pytest.raises(ExecutionPayloadSubstitutionError):
            evaluate_observation_freshness(
                attempt,  # type: ignore[arg-type]
                contract,
                at=t_eval,
            )

    def test_observation_freshness_success_with_valid_observation(self) -> None:
        """Valid VerificationObservation evaluates cleanly."""
        target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id="task-123",
            parent_id="list-456",
        )
        t_obs = datetime(2026, 10, 6, 7, 30, 0, tzinfo=UTC)
        t_eval = datetime(2026, 10, 6, 7, 30, 30, tzinfo=UTC)
        obs = VerificationObservation(
            target=target,
            observed_at=t_obs,
            exists=True,
        )
        contract = FreshnessContract.max_age(60)
        res = evaluate_observation_freshness(obs, contract, at=t_eval)
        assert res.is_fresh is True
        assert res.age_seconds == 30.0
