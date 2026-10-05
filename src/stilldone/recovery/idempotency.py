"""Deterministic idempotency strategy contracts and resolution for StillDone.

Phase P-10.01:
Freezes idempotency strategy per supported mutation and action type.

Core Architectural Laws:
- StillDone invariant: "A retry is not allowed to create a second effect
  merely because the first response was lost."
- Blind retry is FORBIDDEN on actions with duplicate creation risk.
- Mutation actions must declare:
  * duplicate risk class;
  * retry eligibility;
  * requirement for read-before-retry;
  * requirement for verify-after-timeout;
  * attempt ceiling (strictly bounded <= 5).
- Model / planner has ZERO authority over idempotency strategy.
- Deterministic idempotency key derivation from canonical action properties.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from stilldone.domain.action import ActionContract, ActionType

# Detect planner/model classes if available to reject model authority injections
try:
    from stilldone.planning.contracts import (
        CandidateActionProposal,
        CandidatePlanProposal,
        PlannerInput,
    )

    _PLANNER_TYPES: tuple[type, ...] = (
        CandidatePlanProposal,
        CandidateActionProposal,
        PlannerInput,
    )
except ImportError:
    _PLANNER_TYPES = ()


# ===========================================================================
# Recovery Exception Hierarchy
# ===========================================================================


class RecoveryError(Exception):
    """Base exception for all recovery and idempotency failures."""


class IdempotencyError(RecoveryError):
    """Base exception for idempotency contract violations."""


class UnsupportedRecoveryActionError(IdempotencyError, ValueError):
    """Raised when an unsupported action type is queried for idempotency strategy."""


class PlannerRecoveryAuthorityError(RecoveryError, TypeError):
    """Raised when a model/planner proposal is passed as authority for recovery."""


class BlindRetryForbiddenError(IdempotencyError, RuntimeError):
    """Raised when blind retry is attempted on an action that forbids blind retries."""


# ===========================================================================
# Model / Planner Rejection Helper
# ===========================================================================


def assert_not_planner_for_recovery(obj: Any, *, parameter_name: str = "argument") -> None:
    """Reject planner/model proposals fail-closed in recovery operations."""
    for pt in _PLANNER_TYPES:
        if isinstance(obj, pt):
            raise PlannerRecoveryAuthorityError(
                f"Model/planner proposal {type(obj).__name__} has ZERO recovery authority "
                f"({parameter_name})"
            )


# ===========================================================================
# Risk & Strategy Enums
# ===========================================================================


class DuplicateRiskClass(StrEnum):
    """Risk classification of duplicate effects on repeated execution."""

    NONE = "NONE"
    IDEMPOTENT_UPDATE = "IDEMPOTENT_UPDATE"
    HIGH_DUPLICATE_CREATION = "HIGH_DUPLICATE_CREATION"


class IdempotencyStrategyType(StrEnum):
    """Canonical classification of mutation idempotency strategies."""

    READ_ONLY_SAFE = "READ_ONLY_SAFE"
    NATURAL_IN_PLACE_UPDATE = "NATURAL_IN_PLACE_UPDATE"
    CLIENT_TOKEN_DEDUPLICATION = "CLIENT_TOKEN_DEDUPLICATION"


# ===========================================================================
# Mutation Idempotency Strategy Contract
# ===========================================================================

MAX_ALLOWED_RETRY_CEILING = 5


@dataclass(frozen=True)
class MutationIdempotencyStrategy:
    """Immutable declaration of idempotency and duplicate prevention rules for an action."""

    action_type: ActionType
    strategy_type: IdempotencyStrategyType
    duplicate_risk: DuplicateRiskClass
    allows_blind_retry: bool
    requires_read_before_retry: bool
    requires_verify_after_timeout: bool
    max_attempt_ceiling: int
    deduplication_scope: str

    def __post_init__(self) -> None:
        if not isinstance(self.action_type, ActionType):
            raise TypeError(
                f"action_type must be ActionType, got {type(self.action_type).__name__}"
            )
        if not isinstance(self.strategy_type, IdempotencyStrategyType):
            raise TypeError("strategy_type must be IdempotencyStrategyType")
        if not isinstance(self.duplicate_risk, DuplicateRiskClass):
            raise TypeError("duplicate_risk must be DuplicateRiskClass")
        if not isinstance(self.allows_blind_retry, bool):
            raise TypeError("allows_blind_retry must be bool")
        if not isinstance(self.requires_read_before_retry, bool):
            raise TypeError("requires_read_before_retry must be bool")
        if not isinstance(self.requires_verify_after_timeout, bool):
            raise TypeError("requires_verify_after_timeout must be bool")
        if isinstance(self.max_attempt_ceiling, bool) or not isinstance(
            self.max_attempt_ceiling, int
        ):
            raise TypeError("max_attempt_ceiling must be an integer")
        if not (1 <= self.max_attempt_ceiling <= MAX_ALLOWED_RETRY_CEILING):
            raise ValueError(
                f"max_attempt_ceiling must be between 1 and {MAX_ALLOWED_RETRY_CEILING}, "
                f"got {self.max_attempt_ceiling}"
            )
        if not isinstance(self.deduplication_scope, str) or not self.deduplication_scope.strip():
            raise ValueError("deduplication_scope must be a non-empty string")

        # Architectural law: actions with HIGH_DUPLICATE_CREATION MUST NOT allow blind retry
        if self.duplicate_risk == DuplicateRiskClass.HIGH_DUPLICATE_CREATION:
            if self.allows_blind_retry:
                raise ValueError("Actions with HIGH_DUPLICATE_CREATION cannot allow blind retry")
            if not self.requires_read_before_retry:
                raise ValueError(
                    "Actions with HIGH_DUPLICATE_CREATION must require read before retry"
                )

        # Mutation actions must require verification after ambiguous timeout
        if (
            self.duplicate_risk != DuplicateRiskClass.NONE
            and not self.requires_verify_after_timeout
        ):
            raise ValueError("Mutation actions must require verification after ambiguous timeout")

    def to_dict(self) -> dict[str, Any]:
        """Convert strategy to a serializable dictionary."""
        return {
            "action_type": self.action_type.value,
            "strategy_type": self.strategy_type.value,
            "duplicate_risk": self.duplicate_risk.value,
            "allows_blind_retry": self.allows_blind_retry,
            "requires_read_before_retry": self.requires_read_before_retry,
            "requires_verify_after_timeout": self.requires_verify_after_timeout,
            "max_attempt_ceiling": self.max_attempt_ceiling,
            "deduplication_scope": self.deduplication_scope,
        }


# ===========================================================================
# Frozen Canonical Strategies
# ===========================================================================

FROZEN_IDEMPOTENCY_STRATEGIES: dict[ActionType, MutationIdempotencyStrategy] = {
    # 1. Supported Mutation: CALENDAR_UPDATE
    # In-place update to known target event ID. Idempotent by target event,
    # but requires read-back verification after ambiguous timeout.
    ActionType.CALENDAR_UPDATE: MutationIdempotencyStrategy(
        action_type=ActionType.CALENDAR_UPDATE,
        strategy_type=IdempotencyStrategyType.NATURAL_IN_PLACE_UPDATE,
        duplicate_risk=DuplicateRiskClass.IDEMPOTENT_UPDATE,
        allows_blind_retry=False,
        requires_read_before_retry=False,
        requires_verify_after_timeout=True,
        max_attempt_ceiling=3,
        deduplication_scope="event_id",
    ),
    # 2. Supported Mutation: TASK_CREATE
    # Creation of a new task in a parent task list. High duplicate risk!
    # Blind retry is strictly FORBIDDEN; requires read-before-retry to verify
    # if task was created during lost response.
    ActionType.TASK_CREATE: MutationIdempotencyStrategy(
        action_type=ActionType.TASK_CREATE,
        strategy_type=IdempotencyStrategyType.CLIENT_TOKEN_DEDUPLICATION,
        duplicate_risk=DuplicateRiskClass.HIGH_DUPLICATE_CREATION,
        allows_blind_retry=False,
        requires_read_before_retry=True,
        requires_verify_after_timeout=True,
        max_attempt_ceiling=3,
        deduplication_scope="client_request_token",
    ),
    # 3. Read Actions (Safe / Idempotent)
    ActionType.CALENDAR_READ: MutationIdempotencyStrategy(
        action_type=ActionType.CALENDAR_READ,
        strategy_type=IdempotencyStrategyType.READ_ONLY_SAFE,
        duplicate_risk=DuplicateRiskClass.NONE,
        allows_blind_retry=True,
        requires_read_before_retry=False,
        requires_verify_after_timeout=False,
        max_attempt_ceiling=3,
        deduplication_scope="read_only",
    ),
    ActionType.TASK_READ: MutationIdempotencyStrategy(
        action_type=ActionType.TASK_READ,
        strategy_type=IdempotencyStrategyType.READ_ONLY_SAFE,
        duplicate_risk=DuplicateRiskClass.NONE,
        allows_blind_retry=True,
        requires_read_before_retry=False,
        requires_verify_after_timeout=False,
        max_attempt_ceiling=3,
        deduplication_scope="read_only",
    ),
    ActionType.WEATHER_READ: MutationIdempotencyStrategy(
        action_type=ActionType.WEATHER_READ,
        strategy_type=IdempotencyStrategyType.READ_ONLY_SAFE,
        duplicate_risk=DuplicateRiskClass.NONE,
        allows_blind_retry=True,
        requires_read_before_retry=False,
        requires_verify_after_timeout=False,
        max_attempt_ceiling=3,
        deduplication_scope="read_only",
    ),
}


# ===========================================================================
# Strategy Resolution & Idempotency Key Derivation Helpers
# ===========================================================================


def get_idempotency_strategy(action: ActionContract | ActionType) -> MutationIdempotencyStrategy:
    """Resolve the frozen idempotency strategy for an ActionContract or ActionType.

    Fails closed on unsupported action types or planner proposal injections.
    """
    assert_not_planner_for_recovery(action, parameter_name="action")

    if isinstance(action, ActionContract):
        act_type = action.action_type
    elif isinstance(action, ActionType):
        act_type = action
    else:
        raise TypeError(f"action must be ActionContract or ActionType, got {type(action).__name__}")

    strategy = FROZEN_IDEMPOTENCY_STRATEGIES.get(act_type)
    if strategy is None:
        raise UnsupportedRecoveryActionError(
            f"No frozen idempotency strategy registered for action type: {act_type.value}"
        )

    return strategy


STILLDONE_IDEMPOTENCY_NAMESPACE = uuid.UUID("a7b3c2d1-e5f6-4a1b-8c2d-3e4f5a6b7c8d")


def derive_idempotency_key(action: ActionContract, attempt_number: int = 1) -> str:
    """Deterministically derive an idempotency key for an action attempt.

    Uses UUIDv5 derived from (mission_id, action_id, action_type, target_hash).
    If attempt_number > 1, the key remains STABLE per action to ensure provider-level
    deduplication across retries of the SAME intended mutation.

    Args:
        action: Canonical ActionContract.
        attempt_number: Positive integer attempt number.

    Returns:
        Deterministic UUIDv5 string.
    """
    assert_not_planner_for_recovery(action, parameter_name="action")
    if not isinstance(action, ActionContract):
        raise TypeError(f"action must be ActionContract, got {type(action).__name__}")
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise TypeError("attempt_number must be an integer")
    if attempt_number < 1:
        raise ValueError(f"attempt_number must be >= 1, got {attempt_number}")

    target = action.target
    target_digest = hashlib.sha256(
        f"{target.system}:{target.resource_kind.value}:{target.resource_id}:{target.parent_id}".encode()
    ).hexdigest()

    # Stable per intended mutation action
    canonical_seed = (
        f"{action.mission_id}:{action.action_id}:{action.action_type.value}:{target_digest}"
    )
    return str(uuid.uuid5(STILLDONE_IDEMPOTENCY_NAMESPACE, canonical_seed))
