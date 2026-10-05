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

__all__ = [
    "FROZEN_IDEMPOTENCY_STRATEGIES",
    "BlindRetryForbiddenError",
    "DuplicateRiskClass",
    "IdempotencyError",
    "IdempotencyStrategyType",
    "MutationIdempotencyStrategy",
    "PlannerRecoveryAuthorityError",
    "RecoveryError",
    "UnsupportedRecoveryActionError",
    "assert_not_planner_for_recovery",
    "derive_idempotency_key",
    "get_idempotency_strategy",
]
