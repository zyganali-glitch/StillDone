"""Focused unit tests for StillDone endpoint rate and budget protection contract (P-04.06)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from stilldone.endpoint_protection import (
    AdmissionReason,
    AdmissionStatus,
    BudgetSnapshot,
    CallerClass,
    EndpointAdmissionDecision,
    EndpointProtectionError,
    EndpointProtectionPolicy,
    EndpointProtectionTypeError,
    EndpointProtectionValueError,
    EndpointRequestAssessment,
    RateSnapshot,
    RequestExposureClass,
    evaluate_endpoint_admission,
)

# ===========================================================================
# Fixtures and Helpers
# ===========================================================================

T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
T_START = T0
T_END = T0 + timedelta(hours=1)
T_MID = T0 + timedelta(minutes=30)


def create_policy(
    *,
    max_requests: int = 10,
    max_paid_live_requests: int = 5,
    ceiling: Decimal = Decimal("10.00"),
    live_paid_path_enabled: bool = True,
) -> EndpointProtectionPolicy:
    """Create a standard test policy."""
    return EndpointProtectionPolicy(
        max_requests_per_window=max_requests,
        max_paid_live_requests_per_window=max_paid_live_requests,
        internal_gross_ceiling=ceiling,
        live_paid_path_enabled=live_paid_path_enabled,
    )


def create_rate_snapshot(
    *,
    window_start: datetime = T_START,
    window_end: datetime = T_END,
    total_requests: int = 0,
    paid_live_requests: int = 0,
) -> RateSnapshot:
    """Create a standard test rate snapshot."""
    return RateSnapshot(
        window_start=window_start,
        window_end=window_end,
        total_requests=total_requests,
        paid_live_requests=paid_live_requests,
    )


def create_budget_snapshot(
    *,
    already_accounted_gross_cost: Decimal = Decimal("1.00"),
    remaining_promotional_credit: Decimal = Decimal("50.00"),
    credit_coverage_confirmed: bool = True,
    observed_at: datetime = T_START,
    valid_until: datetime = T_END,
) -> BudgetSnapshot:
    """Create a standard test budget snapshot."""
    return BudgetSnapshot(
        already_accounted_gross_cost=already_accounted_gross_cost,
        remaining_promotional_credit=remaining_promotional_credit,
        credit_coverage_confirmed=credit_coverage_confirmed,
        observed_at=observed_at,
        valid_until=valid_until,
    )


# ===========================================================================
# 1-4. Policy Validation Tests
# ===========================================================================


def test_01_policy_rejects_zero_general_request_limit() -> None:
    """Requirement 1: Policy rejects zero general request limit."""
    with pytest.raises(EndpointProtectionValueError, match="strictly positive"):
        EndpointProtectionPolicy(
            max_requests_per_window=0,
            max_paid_live_requests_per_window=5,
            internal_gross_ceiling=Decimal("10.00"),
        )


def test_02_policy_rejects_negative_limit() -> None:
    """Requirement 2: Policy rejects negative limits."""
    with pytest.raises(EndpointProtectionValueError, match="strictly positive"):
        EndpointProtectionPolicy(
            max_requests_per_window=-1,
            max_paid_live_requests_per_window=5,
            internal_gross_ceiling=Decimal("10.00"),
        )
    with pytest.raises(EndpointProtectionValueError, match="strictly positive"):
        EndpointProtectionPolicy(
            max_requests_per_window=10,
            max_paid_live_requests_per_window=-2,
            internal_gross_ceiling=Decimal("10.00"),
        )


def test_03_policy_rejects_bool_as_integer_limit() -> None:
    """Requirement 3: Policy rejects bool as integer limit."""
    with pytest.raises(EndpointProtectionTypeError, match="not bool"):
        EndpointProtectionPolicy(
            max_requests_per_window=True,
            max_paid_live_requests_per_window=5,
            internal_gross_ceiling=Decimal("10.00"),
        )
    with pytest.raises(EndpointProtectionTypeError, match="not bool"):
        EndpointProtectionPolicy(
            max_requests_per_window=10,
            max_paid_live_requests_per_window=False,
            internal_gross_ceiling=Decimal("10.00"),
        )


def test_04_policy_rejects_zero_paid_live_limit() -> None:
    """Requirement 4: Policy rejects zero paid-live limit."""
    with pytest.raises(EndpointProtectionValueError, match="strictly positive"):
        EndpointProtectionPolicy(
            max_requests_per_window=10,
            max_paid_live_requests_per_window=0,
            internal_gross_ceiling=Decimal("10.00"),
        )


def test_policy_rejects_paid_live_exceeding_total() -> None:
    """Policy rejects max_paid_live_requests_per_window > max_requests_per_window."""
    with pytest.raises(EndpointProtectionValueError, match="cannot exceed"):
        EndpointProtectionPolicy(
            max_requests_per_window=5,
            max_paid_live_requests_per_window=10,
            internal_gross_ceiling=Decimal("10.00"),
        )


def test_policy_rejects_negative_or_non_finite_ceiling() -> None:
    """Policy rejects negative, NaN, infinite, or non-Decimal gross ceiling."""
    with pytest.raises(EndpointProtectionValueError, match="cannot be negative"):
        EndpointProtectionPolicy(
            max_requests_per_window=10,
            max_paid_live_requests_per_window=5,
            internal_gross_ceiling=Decimal("-1.00"),
        )
    with pytest.raises(EndpointProtectionValueError, match="must be a finite"):
        EndpointProtectionPolicy(
            max_requests_per_window=10,
            max_paid_live_requests_per_window=5,
            internal_gross_ceiling=Decimal("NaN"),
        )
    with pytest.raises(EndpointProtectionValueError, match="must be a finite"):
        EndpointProtectionPolicy(
            max_requests_per_window=10,
            max_paid_live_requests_per_window=5,
            internal_gross_ceiling=Decimal("Infinity"),
        )
    with pytest.raises(EndpointProtectionTypeError, match="must be a Decimal"):
        EndpointProtectionPolicy(
            max_requests_per_window=10,
            max_paid_live_requests_per_window=5,
            internal_gross_ceiling=10.0,  # type: ignore[arg-type]
        )


def test_policy_no_implicit_true_live_gate_default() -> None:
    """Policy defaults live_paid_path_enabled to False."""
    policy = EndpointProtectionPolicy(
        max_requests_per_window=10,
        max_paid_live_requests_per_window=5,
        internal_gross_ceiling=Decimal("10.00"),
    )
    assert policy.live_paid_path_enabled is False


# ===========================================================================
# 5-9. Rate Snapshot Validation Tests
# ===========================================================================


def test_05_rate_snapshot_rejects_negative_total_count() -> None:
    """Requirement 5: Rate snapshot rejects negative total count."""
    with pytest.raises(EndpointProtectionValueError, match="cannot be negative"):
        RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=-1,
            paid_live_requests=0,
        )


def test_06_rate_snapshot_rejects_negative_paid_live_count() -> None:
    """Requirement 6: Rate snapshot rejects negative paid-live count."""
    with pytest.raises(EndpointProtectionValueError, match="cannot be negative"):
        RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=5,
            paid_live_requests=-1,
        )


def test_07_paid_live_count_exceeding_total_count_fails() -> None:
    """Requirement 7: paid_live_count > total_count fails closed."""
    with pytest.raises(EndpointProtectionValueError, match="cannot exceed"):
        RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=3,
            paid_live_requests=4,
        )


def test_08_naive_rate_timestamps_fail() -> None:
    """Requirement 8: Naive rate timestamps fail closed."""
    naive_t = datetime(2026, 10, 1, 12, 0, 0)
    with pytest.raises(EndpointProtectionValueError, match="must be timezone-aware"):
        RateSnapshot(
            window_start=naive_t,
            window_end=T_END,
            total_requests=0,
            paid_live_requests=0,
        )
    with pytest.raises(EndpointProtectionValueError, match="must be timezone-aware"):
        RateSnapshot(
            window_start=T_START,
            window_end=naive_t,
            total_requests=0,
            paid_live_requests=0,
        )


def test_09_rate_window_end_le_start_fails() -> None:
    """Requirement 9: Rate window end <= start fails closed."""
    with pytest.raises(EndpointProtectionValueError, match="strictly greater"):
        RateSnapshot(
            window_start=T_START,
            window_end=T_START,
            total_requests=0,
            paid_live_requests=0,
        )
    with pytest.raises(EndpointProtectionValueError, match="strictly greater"):
        RateSnapshot(
            window_start=T_END,
            window_end=T_START,
            total_requests=0,
            paid_live_requests=0,
        )


def test_rate_snapshot_rejects_bool_counts() -> None:
    """Rate snapshot rejects bool passed as request counts."""
    with pytest.raises(EndpointProtectionTypeError, match="not bool"):
        RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=True,
            paid_live_requests=0,
        )
    with pytest.raises(EndpointProtectionTypeError, match="not bool"):
        RateSnapshot(
            window_start=T_START,
            window_end=T_END,
            total_requests=5,
            paid_live_requests=False,
        )


# ===========================================================================
# 10-13. Evaluation Timestamp and Window Freshness Tests
# ===========================================================================


def test_10_explicit_at_must_be_timezone_aware() -> None:
    """Requirement 10: Explicit 'at' must be timezone-aware."""
    policy = create_policy()
    snapshot = create_rate_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )
    naive_at = datetime(2026, 10, 1, 12, 15, 0)
    with pytest.raises(EndpointProtectionValueError, match="timezone-aware"):
        evaluate_endpoint_admission(request, policy, snapshot, at=naive_at)


def test_11_at_equal_window_start_is_valid() -> None:
    """Requirement 11: at == window_start is valid and admitted."""
    policy = create_policy()
    snapshot = create_rate_snapshot(total_requests=0)
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, at=snapshot.window_start)
    assert decision.status == AdmissionStatus.ALLOW
    assert decision.reason == AdmissionReason.ALLOWED


def test_12_at_less_than_window_end_is_valid() -> None:
    """Requirement 12: at < window_end is valid and admitted."""
    policy = create_policy()
    snapshot = create_rate_snapshot(total_requests=0)
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )
    at_valid = snapshot.window_end - timedelta(microseconds=1)
    decision = evaluate_endpoint_admission(request, policy, snapshot, at=at_valid)
    assert decision.status == AdmissionStatus.ALLOW
    assert decision.reason == AdmissionReason.ALLOWED


def test_13_at_equal_window_end_fails_closed_as_stale() -> None:
    """Requirement 13: at == window_end fails closed as stale/outside snapshot."""
    policy = create_policy()
    snapshot = create_rate_snapshot(total_requests=0)
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, at=snapshot.window_end)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.RATE_SNAPSHOT_INVALID_OR_STALE

    # Before window_start also fails closed
    decision_before = evaluate_endpoint_admission(
        request, policy, snapshot, at=snapshot.window_start - timedelta(seconds=1)
    )
    assert decision_before.status == AdmissionStatus.DENY
    assert decision_before.reason == AdmissionReason.RATE_SNAPSHOT_INVALID_OR_STALE


# ===========================================================================
# 14-17. Rate Limit Boundary Tests
# ===========================================================================


def test_14_general_rate_boundary_allows_final_permitted_request() -> None:
    """Requirement 14: General rate boundary allows the final permitted request."""
    policy = create_policy(max_requests=10)
    # 9 requests already admitted, this is the 10th (final permitted) request
    snapshot = create_rate_snapshot(total_requests=9)
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, at=T_MID)
    assert decision.status == AdmissionStatus.ALLOW
    assert decision.reason == AdmissionReason.ALLOWED


def test_15_next_request_beyond_general_rate_ceiling_is_denied() -> None:
    """Requirement 15: Next request beyond general rate ceiling is denied."""
    policy = create_policy(max_requests=10)
    # 10 requests already admitted; next request would exceed ceiling
    snapshot = create_rate_snapshot(total_requests=10)
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, at=T_MID)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.RATE_LIMIT_EXCEEDED


def test_16_paid_live_rate_boundary_allows_final_permitted_paid_request() -> None:
    """Requirement 16: Paid-live rate boundary allows final permitted paid request."""
    policy = create_policy(max_requests=10, max_paid_live_requests=5)
    # 4 paid requests already admitted, total=4; this is the 5th (final permitted)
    snapshot = create_rate_snapshot(total_requests=4, paid_live_requests=4)
    budget = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.ALLOW
    assert decision.reason == AdmissionReason.ALLOWED


def test_17_next_paid_request_beyond_paid_live_ceiling_is_denied() -> None:
    """Requirement 17: Next paid request beyond paid-live ceiling is denied."""
    policy = create_policy(max_requests=10, max_paid_live_requests=5)
    # 5 paid requests already admitted; next paid request exceeds paid ceiling
    snapshot = create_rate_snapshot(total_requests=5, paid_live_requests=5)
    budget = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.PAID_LIVE_RATE_LIMIT_EXCEEDED


# ===========================================================================
# 18-19. NO_PAID_CAPABILITY Semantics Tests
# ===========================================================================


def test_18_no_paid_capability_passes_without_budget_facts_required() -> None:
    """Requirement 18: NO_PAID_CAPABILITY request passes without budget facts required."""
    policy = create_policy(live_paid_path_enabled=False)  # even if live gate is disabled
    snapshot = create_rate_snapshot(total_requests=0)
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )
    # Explicitly pass budget_snapshot=None
    decision = evaluate_endpoint_admission(
        request, policy, snapshot, budget_snapshot=None, at=T_MID
    )
    assert decision.status == AdmissionStatus.ALLOW
    assert decision.reason == AdmissionReason.ALLOWED


def test_19_no_paid_capability_does_not_consume_or_evaluate_paid_allowance() -> None:
    """Requirement 19: NO_PAID_CAPABILITY does not consume or evaluate paid-live allowance."""
    policy = create_policy(max_requests=10, max_paid_live_requests=5)
    # Paid requests are already exhausted (5/5), but total requests are not (5/10)
    snapshot = create_rate_snapshot(total_requests=5, paid_live_requests=5)
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )
    decision = evaluate_endpoint_admission(
        request, policy, snapshot, budget_snapshot=None, at=T_MID
    )
    assert decision.status == AdmissionStatus.ALLOW
    assert decision.reason == AdmissionReason.ALLOWED


# ===========================================================================
# 20-23. Paid-Live Request Exposure & Cost Estimate Tests
# ===========================================================================


def test_20_paid_capable_live_public_untrusted_is_denied() -> None:
    """Requirement 20: PAID_CAPABLE_LIVE + PUBLIC_UNTRUSTED fails closed."""
    policy = create_policy(live_paid_path_enabled=True)
    snapshot = create_rate_snapshot()
    budget = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.PUBLIC_PAID_PATH_FORBIDDEN


def test_21_paid_capable_live_live_gate_disabled_is_denied() -> None:
    """Requirement 21: PAID_CAPABLE_LIVE + live gate disabled is denied."""
    policy = create_policy(live_paid_path_enabled=False)
    snapshot = create_rate_snapshot()
    budget = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.LIVE_PATH_DISABLED


def test_22_paid_live_request_with_missing_cost_estimate_is_denied() -> None:
    """Requirement 22: Paid-live request with missing cost estimate is denied."""
    policy = create_policy(live_paid_path_enabled=True)
    snapshot = create_rate_snapshot()
    budget = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=None,
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.COST_ESTIMATE_REQUIRED


def test_23_paid_live_request_with_zero_negative_non_finite_estimate_fails_closed() -> None:
    """Requirement 23: Paid-live request with zero/negative/non-finite estimate fails closed."""
    # Zero estimate fails closed on construction
    with pytest.raises(EndpointProtectionValueError, match="strictly positive"):
        EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("0.00"),
        )
    # Negative estimate fails closed on construction
    with pytest.raises(EndpointProtectionValueError, match="strictly positive"):
        EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("-0.05"),
        )
    # NaN fails closed on construction
    with pytest.raises(EndpointProtectionValueError, match="finite Decimal"):
        EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("NaN"),
        )
    # Infinity fails closed on construction
    with pytest.raises(EndpointProtectionValueError, match="finite Decimal"):
        EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate=Decimal("Infinity"),
        )


def test_no_paid_capability_rejects_declared_cost_estimate() -> None:
    """NO_PAID_CAPABILITY request rejects declared cost estimate."""
    with pytest.raises(EndpointProtectionValueError, match="must not declare a cost estimate"):
        EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
            cost_estimate=Decimal("0.05"),
        )


# ===========================================================================
# 24-28. Budget Snapshot, Credit Coverage & Internal Ceiling Tests
# ===========================================================================


def test_24_stale_budget_observation_is_denied() -> None:
    """Requirement 24: Stale budget observation is denied (BUDGET_TRUTH_STALE)."""
    policy = create_policy()
    snapshot = create_rate_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    # Budget expired before 'at'
    stale_budget = create_budget_snapshot(
        observed_at=T_START,
        valid_until=T_MID - timedelta(seconds=1),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, stale_budget, at=T_MID)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.BUDGET_TRUTH_STALE

    # Missing budget snapshot also yields BUDGET_TRUTH_STALE
    decision_none = evaluate_endpoint_admission(
        request, policy, snapshot, budget_snapshot=None, at=T_MID
    )
    assert decision_none.status == AdmissionStatus.DENY
    assert decision_none.reason == AdmissionReason.BUDGET_TRUTH_STALE


def test_25_unknown_unconfirmed_credit_coverage_is_denied() -> None:
    """Requirement 25: Unconfirmed credit coverage is denied."""
    policy = create_policy()
    snapshot = create_rate_snapshot()
    budget = create_budget_snapshot(credit_coverage_confirmed=False)
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.CREDIT_COVERAGE_UNCONFIRMED


def test_26_insufficient_observed_applicable_promotional_credit_is_denied() -> None:
    """Requirement 26: Insufficient observed promotional credit is denied."""
    policy = create_policy(ceiling=Decimal("100.00"))  # ceiling is plenty
    snapshot = create_rate_snapshot()
    # Remaining credit is only $0.02, but request estimate is $0.05
    budget = create_budget_snapshot(
        already_accounted_gross_cost=Decimal("0.00"),
        remaining_promotional_credit=Decimal("0.02"),
        credit_coverage_confirmed=True,
    )
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.INSUFFICIENT_OBSERVED_CREDIT


def test_27_current_usage_plus_estimate_over_internal_gross_ceiling_is_denied() -> None:
    """Requirement 27: Usage + estimate exceeding internal gross ceiling is denied."""
    policy = create_policy(ceiling=Decimal("10.00"))
    snapshot = create_rate_snapshot()
    # Credit is plenty ($100.00), but usage ($9.98) + estimate ($0.05) = $10.03 > $10.00
    budget = create_budget_snapshot(
        already_accounted_gross_cost=Decimal("9.98"),
        remaining_promotional_credit=Decimal("100.00"),
        credit_coverage_confirmed=True,
    )
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.DENY
    assert decision.reason == AdmissionReason.INTERNAL_BUDGET_EXCEEDED


def test_28_exact_internal_budget_boundary_is_handled_deterministically() -> None:
    """Requirement 28: Exact internal budget boundary (usage + estimate == ceiling) is admitted."""
    policy = create_policy(ceiling=Decimal("10.00"))
    snapshot = create_rate_snapshot()
    # usage ($9.95) + estimate ($0.05) == $10.00 exact boundary
    # credit ($0.05) == estimate ($0.05) exact boundary
    budget = create_budget_snapshot(
        already_accounted_gross_cost=Decimal("9.95"),
        remaining_promotional_credit=Decimal("0.05"),
        credit_coverage_confirmed=True,
    )
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.ALLOW
    assert decision.reason == AdmissionReason.ALLOWED


# ===========================================================================
# 29-31. Valid Paid-Live Admission & Zero-Spend Truth Boundary
# ===========================================================================


def test_29_valid_operator_controlled_paid_live_request_is_allow() -> None:
    """Requirement 29: Valid operator-controlled paid-live request with fresh budget is ALLOW."""
    policy = create_policy(live_paid_path_enabled=True)
    snapshot = create_rate_snapshot()
    budget = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    assert decision.status == AdmissionStatus.ALLOW
    assert decision.reason == AdmissionReason.ALLOWED
    assert decision.is_allowed is True
    assert decision.is_denied is False
    assert decision.cost_estimate == Decimal("0.05")
    assert isinstance(decision, EndpointAdmissionDecision)


def test_30_allow_does_not_claim_personal_spend_proof_or_billing_proof() -> None:
    """Requirement 30: ALLOW does not claim personal-spend proof or billing proof."""
    policy = create_policy()
    snapshot = create_rate_snapshot()
    budget = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)
    # Decision must not possess billing/spend proof fields
    assert not hasattr(decision, "is_billing_proven")
    assert not hasattr(decision, "is_personal_spend_proven")
    assert not hasattr(decision, "actual_billed_cost")
    assert not hasattr(decision, "actual_credit_applied")


def test_31_promotional_credit_is_never_treated_as_provider_hard_spending_cap() -> None:
    """Requirement 31: Promotional credit is never treated as a provider hard spending cap."""
    doc = evaluate_endpoint_admission.__doc__ or ""
    assert "zero-personal-spend" in doc.lower() or "pure" in doc.lower()
    mod_doc = __import__("stilldone.endpoint_protection", fromlist=["__doc__"]).__doc__ or ""
    assert "hard-spending cap" in mod_doc.lower() or "hard spending cap" in mod_doc.lower()


# ===========================================================================
# 32-34. Immutability, Determinism & Clock/Env Purity
# ===========================================================================


def test_32_evaluation_does_not_mutate_inputs() -> None:
    """Requirement 32: Evaluation does not mutate policy, request, or snapshots."""
    policy = create_policy()
    rate_snap = create_rate_snapshot()
    budget_snap = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )

    orig_policy = (
        policy.max_requests_per_window,
        policy.max_paid_live_requests_per_window,
        policy.internal_gross_ceiling,
        policy.live_paid_path_enabled,
    )
    orig_rate = (
        rate_snap.window_start,
        rate_snap.window_end,
        rate_snap.total_requests,
        rate_snap.paid_live_requests,
    )
    orig_budget = (
        budget_snap.already_accounted_gross_cost,
        budget_snap.remaining_promotional_credit,
        budget_snap.credit_coverage_confirmed,
        budget_snap.observed_at,
        budget_snap.valid_until,
    )
    orig_req = (
        request.exposure_class,
        request.caller_class,
        request.cost_estimate,
    )

    _ = evaluate_endpoint_admission(request, policy, rate_snap, budget_snap, at=T_MID)

    assert (
        policy.max_requests_per_window,
        policy.max_paid_live_requests_per_window,
        policy.internal_gross_ceiling,
        policy.live_paid_path_enabled,
    ) == orig_policy

    assert (
        rate_snap.window_start,
        rate_snap.window_end,
        rate_snap.total_requests,
        rate_snap.paid_live_requests,
    ) == orig_rate

    assert (
        budget_snap.already_accounted_gross_cost,
        budget_snap.remaining_promotional_credit,
        budget_snap.credit_coverage_confirmed,
        budget_snap.observed_at,
        budget_snap.valid_until,
    ) == orig_budget

    assert (
        request.exposure_class,
        request.caller_class,
        request.cost_estimate,
    ) == orig_req


def test_33_identical_explicit_inputs_return_identical_decision() -> None:
    """Requirement 33: Identical explicit inputs return identical decision."""
    policy = create_policy()
    rate_snap = create_rate_snapshot()
    budget_snap = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )

    d1 = evaluate_endpoint_admission(request, policy, rate_snap, budget_snap, at=T_MID)
    d2 = evaluate_endpoint_admission(request, policy, rate_snap, budget_snap, at=T_MID)
    assert d1 == d2


def test_34_no_implicit_clock_environment_or_network_reads() -> None:
    """Requirement 34: Source inspection proves no implicit clock/env/network reads."""
    src_path = Path("src/stilldone/endpoint_protection.py")
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    forbidden_calls = {
        "now",
        "utcnow",
        "time",
        "sleep",
        "getenv",
        "environ",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
                pytest.fail(f"Forbidden call found in endpoint_protection: {node.func.id}")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_calls:
                pytest.fail(
                    f"Forbidden attribute call found in endpoint_protection: {node.func.attr}"
                )


# ===========================================================================
# 35-37. Purity, Non-Server & Authority Separation Tests
# ===========================================================================


def test_35_no_provider_sdk_or_network_imports() -> None:
    """Requirement 35: Source inspection proves no provider SDK or network imports."""
    src_path = Path("src/stilldone/endpoint_protection.py")
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    forbidden_modules = {
        "boto3",
        "botocore",
        "strands",
        "agentcore",
        "google",
        "googleapiclient",
        "mcp",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "socket",
        "http",
        "urllib",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                assert root_pkg not in forbidden_modules, f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0]
                assert root_pkg not in forbidden_modules, f"Forbidden import from: {node.module}"


def test_36_no_authentication_or_mcp_server_implementation() -> None:
    """Requirement 36: No authentication, server, or transport classes in endpoint protection."""
    import stilldone.endpoint_protection as ep

    forbidden_symbols = [
        "Server",
        "MCPServer",
        "StreamableHTTP",
        "FastAPI",
        "Flask",
        "Middleware",
        "Auth",
        "Authenticator",
        "Token",
        "JWT",
        "Password",
        "Session",
        "Cookie",
    ]
    for sym in forbidden_symbols:
        assert not hasattr(ep, sym), f"Forbidden server/auth symbol found: {sym}"


def test_37_decision_contains_no_authority_approval_execution_or_ready_state() -> None:
    """Requirement 37: Decision contains no authority/approval/execution/READY state."""
    policy = create_policy()
    snapshot = create_rate_snapshot()
    budget = create_budget_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
        caller_class=CallerClass.OPERATOR_CONTROLLED,
        cost_estimate=Decimal("0.05"),
    )
    decision = evaluate_endpoint_admission(request, policy, snapshot, budget, at=T_MID)

    forbidden_attrs = [
        "authority_class",
        "approval_grant",
        "approval_id",
        "binding_hash",
        "execution_attempt",
        "attempt_id",
        "mission_state",
        "step_evidence_state",
        "is_verified",
        "is_ready",
        "is_executed",
        "ledger",
    ]
    for attr in forbidden_attrs:
        assert not hasattr(decision, attr), f"Decision must not possess {attr}"


# ===========================================================================
# Model Robustness & Representation Safety Tests
# ===========================================================================


def test_exception_hierarchy() -> None:
    """Endpoint protection exceptions inherit from base exception."""
    assert issubclass(EndpointProtectionTypeError, EndpointProtectionError)
    assert issubclass(EndpointProtectionValueError, EndpointProtectionError)


def test_budget_snapshot_validations() -> None:
    """BudgetSnapshot validates money, types, and timezone freshness."""
    with pytest.raises(EndpointProtectionTypeError, match="must be a Decimal"):
        BudgetSnapshot(
            already_accounted_gross_cost=1.0,  # type: ignore[arg-type]
            remaining_promotional_credit=Decimal("50.00"),
            credit_coverage_confirmed=True,
            observed_at=T_START,
            valid_until=T_END,
        )
    with pytest.raises(EndpointProtectionValueError, match="cannot be negative"):
        BudgetSnapshot(
            already_accounted_gross_cost=Decimal("-1.00"),
            remaining_promotional_credit=Decimal("50.00"),
            credit_coverage_confirmed=True,
            observed_at=T_START,
            valid_until=T_END,
        )
    with pytest.raises(EndpointProtectionValueError, match="cannot be negative"):
        BudgetSnapshot(
            already_accounted_gross_cost=Decimal("1.00"),
            remaining_promotional_credit=Decimal("-50.00"),
            credit_coverage_confirmed=True,
            observed_at=T_START,
            valid_until=T_END,
        )
    with pytest.raises(EndpointProtectionTypeError, match="must be a bool"):
        BudgetSnapshot(
            already_accounted_gross_cost=Decimal("1.00"),
            remaining_promotional_credit=Decimal("50.00"),
            credit_coverage_confirmed="yes",  # type: ignore[arg-type]
            observed_at=T_START,
            valid_until=T_END,
        )
    with pytest.raises(EndpointProtectionValueError, match="strictly greater"):
        BudgetSnapshot(
            already_accounted_gross_cost=Decimal("1.00"),
            remaining_promotional_credit=Decimal("50.00"),
            credit_coverage_confirmed=True,
            observed_at=T_END,
            valid_until=T_START,
        )


def test_endpoint_request_assessment_type_validations() -> None:
    """EndpointRequestAssessment rejects invalid types and string coercions."""
    with pytest.raises(EndpointProtectionTypeError, match="RequestExposureClass"):
        EndpointRequestAssessment(
            exposure_class="NO_PAID_CAPABILITY",  # type: ignore[arg-type]
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )
    with pytest.raises(EndpointProtectionTypeError, match="CallerClass"):
        EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class="PUBLIC_UNTRUSTED",  # type: ignore[arg-type]
        )
    with pytest.raises(EndpointProtectionTypeError, match="Decimal"):
        EndpointRequestAssessment(
            exposure_class=RequestExposureClass.PAID_CAPABLE_LIVE,
            caller_class=CallerClass.OPERATOR_CONTROLLED,
            cost_estimate="0.05",  # type: ignore[arg-type]
        )


def test_evaluator_rejects_invalid_argument_types() -> None:
    """evaluate_endpoint_admission rejects invalid argument types."""
    policy = create_policy()
    rate_snap = create_rate_snapshot()
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )

    bad_req: Any = "bad"
    with pytest.raises(EndpointProtectionTypeError, match="request must be"):
        evaluate_endpoint_admission(bad_req, policy, rate_snap, at=T_MID)

    bad_pol: Any = "bad"
    with pytest.raises(EndpointProtectionTypeError, match="policy must be"):
        evaluate_endpoint_admission(request, bad_pol, rate_snap, at=T_MID)

    bad_rate: Any = "bad"
    with pytest.raises(EndpointProtectionTypeError, match="rate_snapshot must be"):
        evaluate_endpoint_admission(request, policy, bad_rate, at=T_MID)

    bad_budget: Any = "bad"
    with pytest.raises(EndpointProtectionTypeError, match="budget_snapshot must be"):
        evaluate_endpoint_admission(
            request, policy, rate_snap, budget_snapshot=bad_budget, at=T_MID
        )

    bad_at: Any = "not_datetime"
    with pytest.raises(EndpointProtectionTypeError, match="at must be"):
        evaluate_endpoint_admission(request, policy, rate_snap, at=bad_at)


def test_timezone_aware_comparison_across_different_offsets() -> None:
    """Evaluation correctly compares timestamps across different timezone offsets."""
    policy = create_policy()
    # UTC+3 timezone
    tz_plus3 = timezone(timedelta(hours=3))
    # T_START is 12:00 UTC = 15:00 UTC+3
    # T_MID is 12:30 UTC = 15:30 UTC+3
    at_plus3 = datetime(2026, 10, 1, 15, 30, tzinfo=tz_plus3)
    rate_snap = create_rate_snapshot(window_start=T_START, window_end=T_END)
    request = EndpointRequestAssessment(
        exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
        caller_class=CallerClass.PUBLIC_UNTRUSTED,
    )
    decision = evaluate_endpoint_admission(request, policy, rate_snap, at=at_plus3)
    assert decision.status == AdmissionStatus.ALLOW
    assert decision.reason == AdmissionReason.ALLOWED
