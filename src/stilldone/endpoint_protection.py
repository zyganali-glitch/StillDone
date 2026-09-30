"""Deterministic public-endpoint rate and budget protection contract for StillDone.

Enforces provider-neutral admission semantics before any incoming request can
reach a paid-capable live runtime (e.g. AWS Bedrock/Strands/AgentCore):
- Finite rate limits: general request limit and paid-live request limit per window.
- Fail-closed snapshot freshness: window_start <= at < window_end.
- Explicit operator live gate: live_paid_path_enabled (no implicit True default).
- Explicit caller exposure: PUBLIC_UNTRUSTED vs OPERATOR_CONTROLLED.
  PAID_CAPABLE_LIVE + PUBLIC_UNTRUSTED fails closed immediately.
- Fresh trusted budget truth: already-accounted conservative usage, remaining
  promotional credit, confirmed credit coverage, and validity window.
- Exact gross ceiling and credit coverage evaluation using exact Decimal arithmetic;
  floating-point money arithmetic and string coercions are strictly rejected.
- Zero-personal-spend truth boundary: An ALLOW decision certifies that the request
  satisfies StillDone's deterministic admission contract given fresh trusted facts;
  it is not billing proof, spend proof, or a provider hard-spending cap.
- Rate-limit truth boundary: P-04.06 evaluates a supplied immutable snapshot. It
  does not atomically consume a quota slot or guarantee concurrency safety; the
  P-05.05 / deployment layer must provide atomic storage before public exposure.
- Separation of concerns: Admission decisions confer zero authority, create zero
  approval grants, execute zero tools, mutate zero ledgers, and cannot produce
  VERIFIED or READY state.
- Provider purity: Pure evaluator with zero network, zero environment reads,
  zero wall-clock reads, and zero provider SDK imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

# ===========================================================================
# Enums
# ===========================================================================


class RequestExposureClass(StrEnum):
    """Execution exposure class for an endpoint request."""

    NO_PAID_CAPABILITY = "NO_PAID_CAPABILITY"
    PAID_CAPABLE_LIVE = "PAID_CAPABLE_LIVE"


class CallerClass(StrEnum):
    """Caller trust and exposure class."""

    PUBLIC_UNTRUSTED = "PUBLIC_UNTRUSTED"
    OPERATOR_CONTROLLED = "OPERATOR_CONTROLLED"


class AdmissionStatus(StrEnum):
    """Deterministic admission outcome status."""

    ALLOW = "ALLOW"
    DENY = "DENY"


class AdmissionReason(StrEnum):
    """Machine-readable reason for an admission decision."""

    ALLOWED = "ALLOWED"
    LIVE_PATH_DISABLED = "LIVE_PATH_DISABLED"
    PUBLIC_PAID_PATH_FORBIDDEN = "PUBLIC_PAID_PATH_FORBIDDEN"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    PAID_LIVE_RATE_LIMIT_EXCEEDED = "PAID_LIVE_RATE_LIMIT_EXCEEDED"
    RATE_SNAPSHOT_INVALID_OR_STALE = "RATE_SNAPSHOT_INVALID_OR_STALE"
    BUDGET_TRUTH_STALE = "BUDGET_TRUTH_STALE"
    CREDIT_COVERAGE_UNCONFIRMED = "CREDIT_COVERAGE_UNCONFIRMED"
    INSUFFICIENT_OBSERVED_CREDIT = "INSUFFICIENT_OBSERVED_CREDIT"
    INTERNAL_BUDGET_EXCEEDED = "INTERNAL_BUDGET_EXCEEDED"
    COST_ESTIMATE_REQUIRED = "COST_ESTIMATE_REQUIRED"


# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class EndpointProtectionError(Exception):
    """Base exception for all endpoint protection errors."""


class EndpointProtectionTypeError(EndpointProtectionError, TypeError):
    """Raised when an argument or configuration parameter has an invalid type."""


class EndpointProtectionValueError(EndpointProtectionError, ValueError):
    """Raised when an argument or configuration parameter has an invalid value."""


# ===========================================================================
# Contract Models
# ===========================================================================


@dataclass(frozen=True, slots=True)
class EndpointProtectionPolicy:
    """Immutable rate and budget protection policy for endpoint admission.

    Defines explicit finite limits for general requests and paid-capable live
    requests per window, an internal gross-cost ceiling, and an explicit
    operator-controlled live path gate.
    """

    max_requests_per_window: int
    max_paid_live_requests_per_window: int
    internal_gross_ceiling: Decimal
    live_paid_path_enabled: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.max_requests_per_window, bool) or not isinstance(
            self.max_requests_per_window, int
        ):
            raise EndpointProtectionTypeError(
                "max_requests_per_window must be an integer, not bool or other type"
            )
        if self.max_requests_per_window <= 0:
            raise EndpointProtectionValueError(
                "max_requests_per_window must be a strictly positive integer"
            )

        if isinstance(self.max_paid_live_requests_per_window, bool) or not isinstance(
            self.max_paid_live_requests_per_window, int
        ):
            raise EndpointProtectionTypeError(
                "max_paid_live_requests_per_window must be an integer, not bool or other type"
            )
        if self.max_paid_live_requests_per_window <= 0:
            raise EndpointProtectionValueError(
                "max_paid_live_requests_per_window must be a strictly positive integer"
            )

        if self.max_paid_live_requests_per_window > self.max_requests_per_window:
            raise EndpointProtectionValueError(
                "max_paid_live_requests_per_window cannot exceed max_requests_per_window"
            )

        if isinstance(self.internal_gross_ceiling, bool) or not isinstance(
            self.internal_gross_ceiling, Decimal
        ):
            raise EndpointProtectionTypeError("internal_gross_ceiling must be a Decimal instance")
        if not self.internal_gross_ceiling.is_finite():
            raise EndpointProtectionValueError("internal_gross_ceiling must be a finite Decimal")
        if self.internal_gross_ceiling < Decimal(0):
            raise EndpointProtectionValueError("internal_gross_ceiling cannot be negative")

        if not isinstance(self.live_paid_path_enabled, bool):
            raise EndpointProtectionTypeError("live_paid_path_enabled must be a bool")


@dataclass(frozen=True, slots=True)
class RateSnapshot:
    """Immutable snapshot of request counts observed within a time window.

    All counts must be non-negative integers. Timestamps must be timezone-aware.
    """

    window_start: datetime
    window_end: datetime
    total_requests: int
    paid_live_requests: int

    def __post_init__(self) -> None:
        if not isinstance(self.window_start, datetime) or not isinstance(self.window_end, datetime):
            raise EndpointProtectionTypeError(
                "window_start and window_end must be datetime instances"
            )
        if (
            self.window_start.tzinfo is None
            or self.window_start.tzinfo.utcoffset(self.window_start) is None
        ):
            raise EndpointProtectionValueError("window_start must be timezone-aware")
        if (
            self.window_end.tzinfo is None
            or self.window_end.tzinfo.utcoffset(self.window_end) is None
        ):
            raise EndpointProtectionValueError("window_end must be timezone-aware")
        if self.window_end <= self.window_start:
            raise EndpointProtectionValueError(
                "window_end must be strictly greater than window_start"
            )

        if isinstance(self.total_requests, bool) or not isinstance(self.total_requests, int):
            raise EndpointProtectionTypeError(
                "total_requests must be an integer, not bool or other type"
            )
        if self.total_requests < 0:
            raise EndpointProtectionValueError("total_requests cannot be negative")

        if isinstance(self.paid_live_requests, bool) or not isinstance(
            self.paid_live_requests, int
        ):
            raise EndpointProtectionTypeError(
                "paid_live_requests must be an integer, not bool or other type"
            )
        if self.paid_live_requests < 0:
            raise EndpointProtectionValueError("paid_live_requests cannot be negative")

        if self.paid_live_requests > self.total_requests:
            raise EndpointProtectionValueError("paid_live_requests cannot exceed total_requests")

    @property
    def total_count(self) -> int:
        """Alias for total_requests."""
        return self.total_requests

    @property
    def paid_live_count(self) -> int:
        """Alias for paid_live_requests."""
        return self.paid_live_requests


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """Immutable snapshot of billing and promotional-credit truth.

    Contains conservative gross usage observed, remaining promotional credit,
    credit coverage confirmation, and the freshness window of the observation.
    Timestamps must be timezone-aware.
    """

    already_accounted_gross_cost: Decimal
    remaining_promotional_credit: Decimal
    credit_coverage_confirmed: bool
    observed_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if isinstance(self.already_accounted_gross_cost, bool) or not isinstance(
            self.already_accounted_gross_cost, Decimal
        ):
            raise EndpointProtectionTypeError(
                "already_accounted_gross_cost must be a Decimal instance"
            )
        if not self.already_accounted_gross_cost.is_finite():
            raise EndpointProtectionValueError(
                "already_accounted_gross_cost must be a finite Decimal"
            )
        if self.already_accounted_gross_cost < Decimal(0):
            raise EndpointProtectionValueError("already_accounted_gross_cost cannot be negative")

        if isinstance(self.remaining_promotional_credit, bool) or not isinstance(
            self.remaining_promotional_credit, Decimal
        ):
            raise EndpointProtectionTypeError(
                "remaining_promotional_credit must be a Decimal instance"
            )
        if not self.remaining_promotional_credit.is_finite():
            raise EndpointProtectionValueError(
                "remaining_promotional_credit must be a finite Decimal"
            )
        if self.remaining_promotional_credit < Decimal(0):
            raise EndpointProtectionValueError("remaining_promotional_credit cannot be negative")

        if not isinstance(self.credit_coverage_confirmed, bool):
            raise EndpointProtectionTypeError("credit_coverage_confirmed must be a bool")

        if not isinstance(self.observed_at, datetime) or not isinstance(self.valid_until, datetime):
            raise EndpointProtectionTypeError(
                "observed_at and valid_until must be datetime instances"
            )
        if (
            self.observed_at.tzinfo is None
            or self.observed_at.tzinfo.utcoffset(self.observed_at) is None
        ):
            raise EndpointProtectionValueError("observed_at must be timezone-aware")
        if (
            self.valid_until.tzinfo is None
            or self.valid_until.tzinfo.utcoffset(self.valid_until) is None
        ):
            raise EndpointProtectionValueError("valid_until must be timezone-aware")
        if self.valid_until <= self.observed_at:
            raise EndpointProtectionValueError(
                "valid_until must be strictly greater than observed_at"
            )


@dataclass(frozen=True, slots=True)
class EndpointRequestAssessment:
    """Immutable assessment of an incoming endpoint request for admission.

    Binds the request's execution exposure class, caller exposure class, and
    an optional conservative incremental gross-cost estimate.

    - NO_PAID_CAPABILITY requests must not declare a cost estimate.
    - If a cost estimate is declared, it must be a strictly positive finite Decimal.
    """

    exposure_class: RequestExposureClass
    caller_class: CallerClass
    cost_estimate: Decimal | None = None

    def __post_init__(self) -> None:
        if type(self.exposure_class) is not RequestExposureClass:
            raise EndpointProtectionTypeError(
                "exposure_class must be an instance of RequestExposureClass"
            )
        if type(self.caller_class) is not CallerClass:
            raise EndpointProtectionTypeError("caller_class must be an instance of CallerClass")

        if self.cost_estimate is not None:
            if isinstance(self.cost_estimate, bool) or not isinstance(self.cost_estimate, Decimal):
                raise EndpointProtectionTypeError(
                    "cost_estimate must be a Decimal instance or None"
                )
            if not self.cost_estimate.is_finite():
                raise EndpointProtectionValueError("cost_estimate must be a finite Decimal")
            if self.cost_estimate <= Decimal(0):
                raise EndpointProtectionValueError("cost_estimate must be strictly positive")

        if (
            self.exposure_class == RequestExposureClass.NO_PAID_CAPABILITY
            and self.cost_estimate is not None
        ):
            raise EndpointProtectionValueError(
                "NO_PAID_CAPABILITY requests must not declare a cost estimate"
            )


EndpointRequest = EndpointRequestAssessment


@dataclass(frozen=True, slots=True)
class EndpointAdmissionDecision:
    """Immutable outcome of an endpoint admission evaluation.

    Contains machine-readable status, reason, evaluation timestamp, and
    contextual request metadata.

    Carries NO authority classification, approval grants, execution attempt state,
    or mission lifecycle markers. Does not constitute billing or spend proof.
    """

    status: AdmissionStatus
    reason: AdmissionReason
    evaluated_at: datetime
    exposure_class: RequestExposureClass
    caller_class: CallerClass
    cost_estimate: Decimal | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not AdmissionStatus:
            raise EndpointProtectionTypeError("status must be an instance of AdmissionStatus")
        if type(self.reason) is not AdmissionReason:
            raise EndpointProtectionTypeError("reason must be an instance of AdmissionReason")

        if not isinstance(self.evaluated_at, datetime):
            raise EndpointProtectionTypeError("evaluated_at must be a datetime instance")
        if (
            self.evaluated_at.tzinfo is None
            or self.evaluated_at.tzinfo.utcoffset(self.evaluated_at) is None
        ):
            raise EndpointProtectionValueError("evaluated_at must be timezone-aware")

        if type(self.exposure_class) is not RequestExposureClass:
            raise EndpointProtectionTypeError(
                "exposure_class must be an instance of RequestExposureClass"
            )
        if type(self.caller_class) is not CallerClass:
            raise EndpointProtectionTypeError("caller_class must be an instance of CallerClass")

        if self.cost_estimate is not None:
            if isinstance(self.cost_estimate, bool) or not isinstance(self.cost_estimate, Decimal):
                raise EndpointProtectionTypeError(
                    "cost_estimate must be a Decimal instance or None"
                )
            if not self.cost_estimate.is_finite():
                raise EndpointProtectionValueError("cost_estimate must be a finite Decimal")
            if self.cost_estimate <= Decimal(0):
                raise EndpointProtectionValueError("cost_estimate must be strictly positive")

        if (
            self.exposure_class == RequestExposureClass.NO_PAID_CAPABILITY
            and self.cost_estimate is not None
        ):
            raise EndpointProtectionValueError(
                "NO_PAID_CAPABILITY decisions must not declare a cost estimate"
            )

        # Status/reason consistency: status == ALLOW iff reason == ALLOWED
        if self.status == AdmissionStatus.ALLOW and self.reason != AdmissionReason.ALLOWED:
            raise EndpointProtectionValueError("ALLOW status requires ALLOWED reason")
        if self.status == AdmissionStatus.DENY and self.reason == AdmissionReason.ALLOWED:
            raise EndpointProtectionValueError("DENY status cannot have ALLOWED reason")

        # A PAID_CAPABLE_LIVE ALLOW decision must require OPERATOR_CONTROLLED
        # and a non-None cost_estimate
        if (
            self.exposure_class == RequestExposureClass.PAID_CAPABLE_LIVE
            and self.status == AdmissionStatus.ALLOW
        ):
            if self.caller_class != CallerClass.OPERATOR_CONTROLLED:
                raise EndpointProtectionValueError(
                    "PAID_CAPABLE_LIVE ALLOW decision requires OPERATOR_CONTROLLED caller_class"
                )
            if self.cost_estimate is None:
                raise EndpointProtectionValueError(
                    "PAID_CAPABLE_LIVE ALLOW decision requires a cost estimate"
                )

    @property
    def is_allowed(self) -> bool:
        """Return True if the request is admitted."""
        return self.status == AdmissionStatus.ALLOW

    @property
    def is_denied(self) -> bool:
        """Return True if the request is denied."""
        return self.status == AdmissionStatus.DENY


# ===========================================================================
# Pure Admission Evaluator
# ===========================================================================


def evaluate_endpoint_admission(
    request: EndpointRequestAssessment,
    policy: EndpointProtectionPolicy,
    rate_snapshot: RateSnapshot,
    budget_snapshot: BudgetSnapshot | None = None,
    *,
    at: datetime,
) -> EndpointAdmissionDecision:
    """Deterministically evaluate endpoint admission against policy and snapshots.

    Pure function:
    - No clock reads (requires explicit timezone-aware `at`).
    - No environment reads.
    - No network or provider SDK calls.
    - No mutable global state.

    Evaluation law:
    1. Validate explicit input types and require timezone-aware `at`.
    2. Check rate snapshot window: window_start <= at < window_end.
       If out of window -> DENY / RATE_SNAPSHOT_INVALID_OR_STALE.
    3. Check general rate limit: total_requests >= max_requests_per_window
       -> DENY / RATE_LIMIT_EXCEEDED.
    4. If NO_PAID_CAPABILITY:
       -> ALLOW / ALLOWED (budget snapshot not required, paid allowance untouched).
    5. If PAID_CAPABLE_LIVE:
       a. Check paid-live rate limit: paid_live_requests >= max_paid_live_requests_per_window
          -> DENY / PAID_LIVE_RATE_LIMIT_EXCEEDED.
       b. Check operator live gate: not live_paid_path_enabled
          -> DENY / LIVE_PATH_DISABLED.
       c. Check caller class: caller_class != OPERATOR_CONTROLLED
          -> DENY / PUBLIC_PAID_PATH_FORBIDDEN.
       d. Check cost estimate: missing, non-positive, or non-finite
          -> DENY / COST_ESTIMATE_REQUIRED.
       e. Check budget snapshot presence: budget_snapshot is None
          -> DENY / BUDGET_TRUTH_STALE.
       f. Check budget snapshot freshness: not (observed_at <= at < valid_until)
          -> DENY / BUDGET_TRUTH_STALE.
       g. Check credit coverage: not credit_coverage_confirmed
          -> DENY / CREDIT_COVERAGE_UNCONFIRMED.
       h. Check internal gross ceiling: already_accounted + estimate > internal_gross_ceiling
          -> DENY / INTERNAL_BUDGET_EXCEEDED.
       i. Check remaining promotional credit: estimate > remaining_promotional_credit
          -> DENY / INSUFFICIENT_OBSERVED_CREDIT.
       j. All checks pass -> ALLOW / ALLOWED.
    """
    if not isinstance(request, EndpointRequestAssessment):
        raise EndpointProtectionTypeError("request must be an EndpointRequestAssessment instance")
    if not isinstance(policy, EndpointProtectionPolicy):
        raise EndpointProtectionTypeError("policy must be an EndpointProtectionPolicy instance")
    if not isinstance(rate_snapshot, RateSnapshot):
        raise EndpointProtectionTypeError("rate_snapshot must be a RateSnapshot instance")
    if budget_snapshot is not None and not isinstance(budget_snapshot, BudgetSnapshot):
        raise EndpointProtectionTypeError(
            "budget_snapshot must be a BudgetSnapshot instance or None"
        )
    if not isinstance(at, datetime):
        raise EndpointProtectionTypeError("at must be a datetime instance")
    if at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        raise EndpointProtectionValueError(
            "Explicit evaluation timestamp 'at' must be timezone-aware"
        )

    # 1. Rate snapshot freshness boundary: window_start <= at < window_end
    if at < rate_snapshot.window_start or at >= rate_snapshot.window_end:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.RATE_SNAPSHOT_INVALID_OR_STALE,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 2. General request rate limit
    if rate_snapshot.total_requests >= policy.max_requests_per_window:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.RATE_LIMIT_EXCEEDED,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 3. NO_PAID_CAPABILITY requests do not invoke paid runtimes
    if request.exposure_class == RequestExposureClass.NO_PAID_CAPABILITY:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.ALLOW,
            reason=AdmissionReason.ALLOWED,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=None,
        )

    # 4. PAID_CAPABLE_LIVE checks
    # 4a. Paid-live request rate limit
    if rate_snapshot.paid_live_requests >= policy.max_paid_live_requests_per_window:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.PAID_LIVE_RATE_LIMIT_EXCEEDED,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 4b. Operator live gate
    if not policy.live_paid_path_enabled:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.LIVE_PATH_DISABLED,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 4c. Public vs operator-controlled caller exposure
    if request.caller_class != CallerClass.OPERATOR_CONTROLLED:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.PUBLIC_PAID_PATH_FORBIDDEN,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 4d. Cost estimate presence and validity
    if (
        request.cost_estimate is None
        or not request.cost_estimate.is_finite()
        or request.cost_estimate <= Decimal(0)
    ):
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.COST_ESTIMATE_REQUIRED,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 4e. Budget snapshot presence
    if budget_snapshot is None:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.BUDGET_TRUTH_STALE,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 4f. Budget snapshot freshness: observed_at <= at < valid_until
    if at < budget_snapshot.observed_at or at >= budget_snapshot.valid_until:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.BUDGET_TRUTH_STALE,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 4g. Credit coverage confirmation
    if not budget_snapshot.credit_coverage_confirmed:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.CREDIT_COVERAGE_UNCONFIRMED,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 4h. Internal gross-cost ceiling
    if (
        budget_snapshot.already_accounted_gross_cost + request.cost_estimate
        > policy.internal_gross_ceiling
    ):
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.INTERNAL_BUDGET_EXCEEDED,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 4i. Remaining promotional credit
    if request.cost_estimate > budget_snapshot.remaining_promotional_credit:
        return EndpointAdmissionDecision(
            status=AdmissionStatus.DENY,
            reason=AdmissionReason.INSUFFICIENT_OBSERVED_CREDIT,
            evaluated_at=at,
            exposure_class=request.exposure_class,
            caller_class=request.caller_class,
            cost_estimate=request.cost_estimate,
        )

    # 4j. All checks passed
    return EndpointAdmissionDecision(
        status=AdmissionStatus.ALLOW,
        reason=AdmissionReason.ALLOWED,
        evaluated_at=at,
        exposure_class=request.exposure_class,
        caller_class=request.caller_class,
        cost_estimate=request.cost_estimate,
    )
