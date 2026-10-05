"""Deterministic freshness and stale evaluation.

Phase P-09.03:
Evaluates the temporal validity of independent verification observations
against explicit FreshnessContracts and timestamps.

Strict Laws:
- Verification evidence must have explicit temporal validity.
- Pure evaluator: zero implicit wall-clock reads; explicit `at` required.
- All datetimes: timezone-aware and normalized to UTC.
- Exact boundary condition: observed_at <= at < valid_until (at expiry boundary: STALE).
- Future-dated impossible observation (observed_at > at): fails closed.
- Naive datetimes (lacking timezone): fail closed.
- Freshness applies to verification observation/evidence, NOT to executor success timestamps.
- Zero network calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from stilldone.domain.desired_state import FreshnessContract, FreshnessMode
from stilldone.domain.execution import ExecutionAttempt
from stilldone.execution.state import ProviderExecutionResult
from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    VerificationObservation,
    VerifierError,
)

# ===========================================================================
# Freshness Exceptions
# ===========================================================================


class FreshnessError(VerifierError):
    """Base exception for temporal evaluation failures."""


class NaiveDatetimeError(FreshnessError, ValueError):
    """Raised when a naive datetime (lacking tzinfo) is passed to evaluator."""


class FutureDatedObservationError(FreshnessError, ValueError):
    """Raised when an observation timestamp is in the future relative to evaluation point."""


# ===========================================================================
# Freshness Vocabulary and Result Contract
# ===========================================================================


class FreshnessStatus(StrEnum):
    """Canonical deterministic temporal validity status.

    - FRESH: Observation is within validity window (observed_at <= at < valid_until).
    - STALE: Validity window has elapsed (at >= valid_until).
    """

    FRESH = "FRESH"
    STALE = "STALE"


@dataclass(frozen=True)
class FreshnessResult:
    """Immutable result of temporal validity evaluation."""

    status: FreshnessStatus
    observed_at: datetime
    evaluated_at: datetime
    valid_until: datetime
    age_seconds: float
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, FreshnessStatus):
            raise TypeError("status must be a FreshnessStatus instance")
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime instance")
        if not isinstance(self.evaluated_at, datetime):
            raise TypeError("evaluated_at must be a datetime instance")
        if not isinstance(self.valid_until, datetime):
            raise TypeError("valid_until must be a datetime instance")

    @property
    def is_fresh(self) -> bool:
        """Return True if observation is fresh."""
        return self.status == FreshnessStatus.FRESH

    @property
    def is_stale(self) -> bool:
        """Return True if observation is stale."""
        return self.status == FreshnessStatus.STALE


# ===========================================================================
# Datetime Validation and Normalization Helper
# ===========================================================================


def _require_utc_datetime(dt: datetime, name: str) -> datetime:
    """Assert datetime is timezone-aware and return normalized UTC datetime."""
    if not isinstance(dt, datetime):
        raise TypeError(f"{name} must be a datetime instance, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NaiveDatetimeError(f"{name} must be timezone-aware (got naive datetime {dt!r})")
    if dt.tzinfo != UTC:
        return dt.astimezone(UTC)
    return dt


# ===========================================================================
# Deterministic Freshness Evaluator
# ===========================================================================


DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS: int = 300  # 5 minutes bounded window for CURRENT mode


def evaluate_freshness(
    observed_at: datetime,
    *,
    at: datetime,
    valid_until: datetime | None = None,
    max_age_seconds: int | float | None = None,
    freshness_contract: FreshnessContract | None = None,
    current_window_seconds: int = DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
) -> FreshnessResult:
    """Evaluate temporal validity of an observation timestamp against an evaluation point.

    Exact boundary law:
    - observed_at <= at < valid_until => FRESH
    - at >= valid_until => STALE (at expiry boundary: STALE)
    - observed_at > at => FutureDatedObservationError (fail closed)
    - naive datetimes => NaiveDatetimeError (fail closed)

    Args:
        observed_at: Timezone-aware observation timestamp.
        at: Explicit evaluation point (zero implicit wall-clock reads).
        valid_until: Optional explicit expiry datetime.
        max_age_seconds: Optional max age in seconds relative to observed_at.
        freshness_contract: Optional canonical FreshnessContract.
        current_window_seconds: Max age in seconds for FreshnessMode.CURRENT.

    Returns:
        FreshnessResult with status FRESH or STALE.

    Raises:
        NaiveDatetimeError: If any datetime is naive.
        FutureDatedObservationError: If observed_at > at.
        ValueError: If no validity bound was provided or max_age_seconds <= 0.
    """
    obs_utc = _require_utc_datetime(observed_at, "observed_at")
    at_utc = _require_utc_datetime(at, "at")

    # Fail closed on future-dated impossible observation
    if obs_utc > at_utc:
        raise FutureDatedObservationError(
            f"Observation timestamp {obs_utc.isoformat()} is in the future "
            f"relative to evaluation timestamp {at_utc.isoformat()}"
        )

    # Determine effective valid_until
    effective_valid_until: datetime

    if valid_until is not None:
        effective_valid_until = _require_utc_datetime(valid_until, "valid_until")

    elif max_age_seconds is not None:
        if not isinstance(max_age_seconds, (int, float)) or isinstance(max_age_seconds, bool):
            raise TypeError("max_age_seconds must be a numeric value")
        if max_age_seconds <= 0:
            raise ValueError(f"max_age_seconds must be positive, got {max_age_seconds}")
        effective_valid_until = obs_utc + timedelta(seconds=float(max_age_seconds))

    elif freshness_contract is not None:
        if not isinstance(freshness_contract, FreshnessContract):
            raise TypeError("freshness_contract must be a FreshnessContract instance")
        if freshness_contract.mode == FreshnessMode.MAX_AGE:
            assert freshness_contract.max_age_seconds is not None
            effective_valid_until = obs_utc + timedelta(seconds=freshness_contract.max_age_seconds)
        elif freshness_contract.mode == FreshnessMode.CURRENT:
            effective_valid_until = obs_utc + timedelta(seconds=current_window_seconds)

    else:
        raise ValueError(
            "Must provide at least one of: valid_until, max_age_seconds, or freshness_contract"
        )

    age_seconds = (at_utc - obs_utc).total_seconds()

    # Exact boundary check: observed_at <= at < valid_until
    if at_utc < effective_valid_until:
        status = FreshnessStatus.FRESH
        reason = (
            f"Observation is fresh: age {age_seconds:.1f}s within validity "
            f"until {effective_valid_until.isoformat()}"
        )
    else:
        status = FreshnessStatus.STALE
        reason = (
            f"Observation is stale: expired at {effective_valid_until.isoformat()}, "
            f"evaluated at {at_utc.isoformat()} (age {age_seconds:.1f}s)"
        )

    return FreshnessResult(
        status=status,
        observed_at=obs_utc,
        evaluated_at=at_utc,
        valid_until=effective_valid_until,
        age_seconds=age_seconds,
        reason=reason,
    )


def evaluate_observation_freshness(
    observation: VerificationObservation,
    freshness_contract: FreshnessContract,
    *,
    at: datetime,
    current_window_seconds: int = DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
) -> FreshnessResult:
    """Evaluate temporal freshness of a VerificationObservation against a FreshnessContract.

    Rejects ProviderExecutionResult / ExecutionAttempt payloads with
    ExecutionPayloadSubstitutionError.
    """
    if isinstance(observation, (ProviderExecutionResult, ExecutionAttempt)):
        raise ExecutionPayloadSubstitutionError(
            f"Execution payload {type(observation).__name__} cannot substitute "
            "for VerificationObservation in freshness evaluation"
        )
    if not isinstance(observation, VerificationObservation):
        raise TypeError(
            f"observation must be a VerificationObservation, got {type(observation).__name__}"
        )
    if not isinstance(freshness_contract, FreshnessContract):
        contract_type = type(freshness_contract).__name__
        raise TypeError(f"freshness_contract must be a FreshnessContract, got {contract_type}")

    return evaluate_freshness(
        observed_at=observation.observed_at,
        freshness_contract=freshness_contract,
        at=at,
        current_window_seconds=current_window_seconds,
    )
