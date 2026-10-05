"""Recovery, retry, and idempotency engine for StillDone.

Phase P-10:
Survive ambiguous network failures without duplicate real-world effects.
"""

from __future__ import annotations

from stilldone.recovery.idempotency import (
    FROZEN_IDEMPOTENCY_STRATEGIES,
    BlindRetryForbiddenError,
    DuplicateRiskClass,
    IdempotencyError,
    IdempotencyStrategyType,
    MutationIdempotencyStrategy,
    PlannerRecoveryAuthorityError,
    RecoveryError,
    UnsupportedRecoveryActionError,
    assert_not_planner_for_recovery,
    derive_idempotency_key,
    get_idempotency_strategy,
)
from stilldone.recovery.retry import (
    RetryClassification,
    RetryDecision,
    RetryPolicy,
    classify_error,
    evaluate_retry,
)

__all__ = [
    "FROZEN_IDEMPOTENCY_STRATEGIES",
    "BlindRetryForbiddenError",
    "DuplicateRiskClass",
    "IdempotencyError",
    "IdempotencyStrategyType",
    "MutationIdempotencyStrategy",
    "PlannerRecoveryAuthorityError",
    "RecoveryError",
    "RetryClassification",
    "RetryDecision",
    "RetryPolicy",
    "UnsupportedRecoveryActionError",
    "assert_not_planner_for_recovery",
    "classify_error",
    "derive_idempotency_key",
    "evaluate_retry",
    "get_idempotency_strategy",
]
