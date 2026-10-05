"""Deterministic error classification and bounded exponential retry engine.

Phase P-10.02:
Implements deterministic error classification and bounded exponential retry calculation.

Core Architectural Laws:
- StillDone invariant: "A retry is not allowed to create a second effect
  merely because the first response was lost."
- If an ambiguous timeout occurs on a mutation:
  Blind retry is STRICTLY FORBIDDEN (should_retry = False,
  requires_verification_before_retry = True).
- Retry classification distinguishes:
  * RETRYABLE_TRANSIENT
  * NON_RETRYABLE_PERMANENT
  * AMBIGUOUS_TIMEOUT
  * AUTHORITY_SECURITY_FAILURE
  * CONTRACT_PROGRAMMING_FAILURE
- Strictly bounded attempt ceiling (bounded <= 5).
- Pure deterministic calculation with zero network calls and zero sleeps.
- Model / planner has ZERO authority over retry decisions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from stilldone.domain.action import ActionContract, ActionType
from stilldone.recovery.idempotency import (
    MAX_ALLOWED_RETRY_CEILING,
    DuplicateRiskClass,
    assert_not_planner_for_recovery,
    get_idempotency_strategy,
)

# ===========================================================================
# Retry Classification Enum
# ===========================================================================


class RetryClassification(StrEnum):
    """Canonical classification of execution failures for recovery policy."""

    RETRYABLE_TRANSIENT = "RETRYABLE_TRANSIENT"
    NON_RETRYABLE_PERMANENT = "NON_RETRYABLE_PERMANENT"
    AMBIGUOUS_TIMEOUT = "AMBIGUOUS_TIMEOUT"
    AUTHORITY_SECURITY_FAILURE = "AUTHORITY_SECURITY_FAILURE"
    CONTRACT_PROGRAMMING_FAILURE = "CONTRACT_PROGRAMMING_FAILURE"


# ===========================================================================
# Retry Policy Configuration Contract
# ===========================================================================


@dataclass(frozen=True)
class RetryPolicy:
    """Immutable bounded retry policy parameters."""

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise TypeError("max_attempts must be an integer")
        if not (1 <= self.max_attempts <= MAX_ALLOWED_RETRY_CEILING):
            raise ValueError(
                f"max_attempts must be between 1 and {MAX_ALLOWED_RETRY_CEILING}, "
                f"got {self.max_attempts}"
            )

        for name, val in [
            ("base_delay_seconds", self.base_delay_seconds),
            ("backoff_multiplier", self.backoff_multiplier),
            ("max_delay_seconds", self.max_delay_seconds),
        ]:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be a number, got {type(val).__name__}")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must be finite, got {val}")

        if self.base_delay_seconds <= 0.0:
            raise ValueError(f"base_delay_seconds must be > 0.0, got {self.base_delay_seconds}")
        if self.backoff_multiplier < 1.0:
            raise ValueError(f"backoff_multiplier must be >= 1.0, got {self.backoff_multiplier}")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError(
                f"max_delay_seconds ({self.max_delay_seconds}) must be >= "
                f"base_delay_seconds ({self.base_delay_seconds})"
            )


# ===========================================================================
# Retry Decision Contract
# ===========================================================================


@dataclass(frozen=True)
class RetryDecision:
    """Immutable deterministic outcome of evaluating retry eligibility."""

    should_retry: bool
    classification: RetryClassification
    attempt_number: int
    delay_seconds: float
    requires_verification_before_retry: bool
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.should_retry, bool):
            raise TypeError("should_retry must be a bool")
        if not isinstance(self.classification, RetryClassification):
            raise TypeError("classification must be a RetryClassification")
        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int):
            raise TypeError("attempt_number must be an integer")
        if not isinstance(self.delay_seconds, (int, float)) or isinstance(self.delay_seconds, bool):
            raise TypeError("delay_seconds must be a float")
        if math.isnan(self.delay_seconds) or math.isinf(self.delay_seconds):
            raise ValueError("delay_seconds must be finite")
        if self.delay_seconds < 0.0:
            raise ValueError("delay_seconds must be >= 0.0")
        if not isinstance(self.requires_verification_before_retry, bool):
            raise TypeError("requires_verification_before_retry must be a bool")
        if not isinstance(self.reason, str):
            raise TypeError("reason must be a str")

    def to_dict(self) -> dict[str, Any]:
        """Convert decision to a serializable dictionary."""
        return {
            "should_retry": self.should_retry,
            "classification": self.classification.value,
            "attempt_number": self.attempt_number,
            "delay_seconds": self.delay_seconds,
            "requires_verification_before_retry": self.requires_verification_before_retry,
            "reason": self.reason,
        }


# ===========================================================================
# Deterministic Error Classifier
# ===========================================================================


def classify_error(error: Exception | str | int) -> RetryClassification:
    """Deterministically classify an error into canonical RetryClassification.

    Handles:
    - HTTP status codes (int or numeric str)
    - Python standard and custom exception types
    - Error strings and failure descriptors
    """
    assert_not_planner_for_recovery(error, parameter_name="error")

    # 1. Numeric HTTP status code handling
    if isinstance(error, int):
        status_code = error
        if status_code in (429, 502, 503, 504):
            return RetryClassification.RETRYABLE_TRANSIENT
        if status_code == 408:
            return RetryClassification.AMBIGUOUS_TIMEOUT
        if status_code in (401, 403):
            return RetryClassification.AUTHORITY_SECURITY_FAILURE
        if 400 <= status_code < 500:
            return RetryClassification.NON_RETRYABLE_PERMANENT
        return RetryClassification.NON_RETRYABLE_PERMANENT

    # 2. Exception type inspection
    if isinstance(error, Exception):
        if isinstance(error, (TimeoutError,)):
            return RetryClassification.AMBIGUOUS_TIMEOUT
        if isinstance(
            error,
            (ConnectionResetError, ConnectionRefusedError, ConnectionError),
        ):
            return RetryClassification.RETRYABLE_TRANSIENT
        if isinstance(error, PermissionError):
            return RetryClassification.AUTHORITY_SECURITY_FAILURE
        if isinstance(error, (TypeError, ValueError, KeyError, AssertionError)):
            return RetryClassification.CONTRACT_PROGRAMMING_FAILURE

        # Also inspect exception message
        err_msg = str(error).lower()
        err_type_name = type(error).__name__.lower()
    elif isinstance(error, str):
        # Check if str is integer HTTP code
        if error.isdigit():
            return classify_error(int(error))
        err_msg = error.lower()
        err_type_name = ""
    else:
        raise TypeError(f"error must be Exception, str, or int, got {type(error).__name__}")

    # 3. String content pattern matching
    # Timeout / ambiguous
    if any(
        kw in err_msg or kw in err_type_name for kw in ("timeout", "timed out", "deadline exceeded")
    ):
        return RetryClassification.AMBIGUOUS_TIMEOUT

    # Authority / security
    if any(
        kw in err_msg or kw in err_type_name
        for kw in (
            "unauthorized",
            "forbidden",
            "permission denied",
            "signature mismatch",
            "auth error",
            "401",
            "403",
        )
    ):
        return RetryClassification.AUTHORITY_SECURITY_FAILURE

    # Transient / throttled
    if any(
        kw in err_msg or kw in err_type_name
        for kw in (
            "rate limit",
            "rate_limit",
            "throttled",
            "transient",
            "service unavailable",
            "unavailable",
            "temporarily",
            "connection reset",
            "503",
            "429",
        )
    ):
        return RetryClassification.RETRYABLE_TRANSIENT

    # Programming contract failure
    if any(
        kw in err_msg or kw in err_type_name
        for kw in ("typeerror", "valueerror", "assertion", "programming error", "keyerror")
    ):
        return RetryClassification.CONTRACT_PROGRAMMING_FAILURE

    # Permanent failure by default
    return RetryClassification.NON_RETRYABLE_PERMANENT


# ===========================================================================
# Deterministic Retry Evaluator
# ===========================================================================


def evaluate_retry(
    *,
    action: ActionContract | ActionType,
    attempt_number: int,
    error: Exception | str | int,
    policy: RetryPolicy | None = None,
) -> RetryDecision:
    """Evaluate whether an action failure is eligible for retry and compute delay.

    Laws:
    - Bounded attempt ceiling strictly enforced.
    - If attempt_number >= max_attempts: returns should_retry=False.
    - If error is AMBIGUOUS_TIMEOUT on a mutation action:
      blind retry is FORBIDDEN (should_retry=False, requires_verification_before_retry=True).
    - If error is AMBIGUOUS_TIMEOUT on a read-only action:
      retry is allowed with exponential backoff delay.
    - If error is RETRYABLE_TRANSIENT:
      retry is allowed with exponential backoff delay.
    - Non-retryable permanent, security, and programming failures return should_retry=False.
    - Model/planner proposals have ZERO authority.
    """
    assert_not_planner_for_recovery(action, parameter_name="action")
    assert_not_planner_for_recovery(error, parameter_name="error")
    if policy is not None:
        assert_not_planner_for_recovery(policy, parameter_name="policy")

    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise TypeError("attempt_number must be an integer")
    if attempt_number < 1:
        raise ValueError(f"attempt_number must be >= 1, got {attempt_number}")

    strategy = get_idempotency_strategy(action)
    eff_policy = policy if policy is not None else RetryPolicy()

    # Effective attempt ceiling is bounded by both policy and action strategy ceiling
    effective_ceiling = min(eff_policy.max_attempts, strategy.max_attempt_ceiling)

    classification = classify_error(error)

    # 1. Ceiling check
    if attempt_number >= effective_ceiling:
        return RetryDecision(
            should_retry=False,
            classification=classification,
            attempt_number=attempt_number,
            delay_seconds=0.0,
            requires_verification_before_retry=False,
            reason=f"Attempt ceiling reached ({attempt_number} >= {effective_ceiling})",
        )

    # 2. Ambiguous timeout handling
    if classification == RetryClassification.AMBIGUOUS_TIMEOUT:
        if strategy.duplicate_risk != DuplicateRiskClass.NONE:
            # Core Law: Mutation ambiguous timeout forbids blind retry!
            return RetryDecision(
                should_retry=False,
                classification=classification,
                attempt_number=attempt_number,
                delay_seconds=0.0,
                requires_verification_before_retry=True,
                reason=(
                    "Ambiguous timeout on mutation forbids blind retry; requires "
                    "independent read-back verification before recovery"
                ),
            )
        # Read action ambiguous timeout is safe to retry
        delay = min(
            eff_policy.base_delay_seconds * (eff_policy.backoff_multiplier ** (attempt_number - 1)),
            eff_policy.max_delay_seconds,
        )
        return RetryDecision(
            should_retry=True,
            classification=classification,
            attempt_number=attempt_number,
            delay_seconds=delay,
            requires_verification_before_retry=False,
            reason="Ambiguous timeout on safe read action eligible for retry",
        )

    # 3. Retryable transient handling
    if classification == RetryClassification.RETRYABLE_TRANSIENT:
        delay = min(
            eff_policy.base_delay_seconds * (eff_policy.backoff_multiplier ** (attempt_number - 1)),
            eff_policy.max_delay_seconds,
        )
        return RetryDecision(
            should_retry=True,
            classification=classification,
            attempt_number=attempt_number,
            delay_seconds=delay,
            requires_verification_before_retry=False,
            reason="Transient error eligible for bounded exponential retry",
        )

    # 4. Non-retryable classifications
    return RetryDecision(
        should_retry=False,
        classification=classification,
        attempt_number=attempt_number,
        delay_seconds=0.0,
        requires_verification_before_retry=False,
        reason=f"Non-retryable error classification: {classification.value}",
    )
