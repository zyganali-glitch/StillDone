"""Deterministic recovery orchestration and verify-after-timeout engine.

Phase P-10.03:
Implements deterministic recovery orchestration that consumes the already-frozen
P-10.01 idempotency strategy and P-10.02 retry classification.

Core Architectural Laws:
- StillDone invariant: "A retry is not allowed to create a second effect
  merely because the first response was lost."
- AMBIGUOUS_TIMEOUT on a mutation must never blindly retry.
- Recovery decisions are deterministic runtime facts; model/planner has zero authority.
- Reuses canonical P-10.01 and P-10.02 contracts without duplicating definitions.
- Mutation actions:
  * CALENDAR_UPDATE: ambiguous timeout requires independent verification/read-back
    before any retry decision. If read-back proves effect already exists, do not execute
    again. If effect absent and retry permitted under bounded ceiling, retry may become eligible.
    Inconclusive verification fails closed.
  * TASK_CREATE: high duplicate-creation risk; requires read-before-retry / duplicate check.
    If task already exists, do not create second task. Inconclusive outcome fails closed.
- Read-only actions preserve safer retry semantics.
- No sleeps or uncontrolled network loops inside deterministic policy logic.
- Bounded retry strictly enforced (ceiling <= 5).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.domain.action import ActionContract, ActionId
from stilldone.recovery.idempotency import (
    RecoveryError,
    assert_not_planner_for_recovery,
    derive_idempotency_key,
    get_idempotency_strategy,
)
from stilldone.recovery.retry import (
    RetryClassification,
    RetryPolicy,
    evaluate_retry,
)
from stilldone.redaction import redact_text

# ===========================================================================
# Orchestrator Exception Hierarchy
# ===========================================================================


class RecoveryOrchestratorError(RecoveryError):
    """Base exception for recovery orchestrator errors."""


class RecoveryLineageError(RecoveryOrchestratorError, ValueError):
    """Raised when recovery evaluation encounters a mismatched action identity."""


# ===========================================================================
# Canonical Recovery Enums
# ===========================================================================


class RecoveryActionType(StrEnum):
    """Deterministic recovery decision vocabulary."""

    RETRY = "RETRY"
    DO_NOT_RETRY = "DO_NOT_RETRY"
    EFFECT_ALREADY_EXISTS = "EFFECT_ALREADY_EXISTS"
    DUPLICATE_PREVENTED = "DUPLICATE_PREVENTED"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"


class ReadbackOutcome(StrEnum):
    """Deterministic classification of independent read-back / duplicate inspection."""

    EFFECT_ABSENT = "EFFECT_ABSENT"
    INTENDED_EFFECT_EXISTS = "INTENDED_EFFECT_EXISTS"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


# ===========================================================================
# Read-back Verification Result Contract
# ===========================================================================


@dataclass(frozen=True)
class ReadbackVerificationResult:
    """Immutable outcome of an independent read-back / duplicate scan."""

    outcome: ReadbackOutcome
    action_id: ActionId
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    match_count: int = 0
    details: Mapping[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    def __post_init__(self) -> None:
        assert_not_planner_for_recovery(self.outcome, parameter_name="outcome")
        if not isinstance(self.outcome, ReadbackOutcome):
            raise TypeError(f"outcome must be ReadbackOutcome, got {type(self.outcome).__name__}")
        if not isinstance(self.action_id, ActionId):
            raise TypeError(f"action_id must be ActionId, got {type(self.action_id).__name__}")
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware (UTC required)")
        if self.observed_at.tzinfo != UTC:
            object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        if isinstance(self.match_count, bool) or not isinstance(self.match_count, int):
            raise TypeError("match_count must be an integer")
        if self.match_count < 0:
            raise ValueError("match_count cannot be negative")
        if not isinstance(self.details, Mapping):
            raise TypeError("details must be a Mapping")
        if self.error_message is not None:
            if not isinstance(self.error_message, str):
                raise TypeError("error_message must be a string or None")
            object.__setattr__(self, "error_message", redact_text(self.error_message))

    def to_dict(self) -> dict[str, Any]:
        """Convert result to a serializable dictionary."""
        return {
            "outcome": self.outcome.value,
            "action_id": str(self.action_id),
            "observed_at": self.observed_at.isoformat(),
            "match_count": self.match_count,
            "error_message": self.error_message,
        }


# ===========================================================================
# Recovery Decision Contract
# ===========================================================================


@dataclass(frozen=True)
class RecoveryDecision:
    """Immutable deterministic decision produced by the recovery orchestrator."""

    action_type: RecoveryActionType
    action_id: ActionId
    attempt_number: int
    delay_seconds: float = 0.0
    reason: str = ""
    retry_classification: RetryClassification | None = None
    readback_outcome: ReadbackOutcome | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_type, RecoveryActionType):
            raise TypeError("action_type must be RecoveryActionType")
        if not isinstance(self.action_id, ActionId):
            raise TypeError("action_id must be ActionId")
        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int):
            raise TypeError("attempt_number must be an integer")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be >= 1")
        if not isinstance(self.delay_seconds, (int, float)) or isinstance(self.delay_seconds, bool):
            raise TypeError("delay_seconds must be a float")
        if math.isnan(self.delay_seconds) or math.isinf(self.delay_seconds):
            raise ValueError("delay_seconds must be finite")
        if self.delay_seconds < 0.0:
            raise ValueError("delay_seconds must be >= 0.0")
        if not isinstance(self.reason, str):
            raise TypeError("reason must be a str")
        if self.retry_classification is not None and not isinstance(
            self.retry_classification, RetryClassification
        ):
            raise TypeError("retry_classification must be RetryClassification or None")
        if self.readback_outcome is not None and not isinstance(
            self.readback_outcome, ReadbackOutcome
        ):
            raise TypeError("readback_outcome must be ReadbackOutcome or None")

    def to_dict(self) -> dict[str, Any]:
        """Convert decision to a serializable dictionary."""
        return {
            "action_type": self.action_type.value,
            "action_id": str(self.action_id),
            "attempt_number": self.attempt_number,
            "delay_seconds": self.delay_seconds,
            "reason": self.reason,
            "retry_classification": (
                self.retry_classification.value if self.retry_classification else None
            ),
            "readback_outcome": (self.readback_outcome.value if self.readback_outcome else None),
            "idempotency_key": self.idempotency_key,
        }


# ===========================================================================
# Deterministic Recovery Evaluation Functions
# ===========================================================================


def evaluate_post_execution_recovery(
    *,
    action: ActionContract,
    attempt_number: int,
    error: Exception | str | int | None,
    policy: RetryPolicy | None = None,
) -> RecoveryDecision:
    """Evaluate recovery requirement immediately following an execution attempt.

    Laws:
    - If error is None, execution succeeded; no recovery required.
    - If action has high duplicate risk (TASK_CREATE) and retry is otherwise possible,
      blind retry is FORBIDDEN; requires read-before-retry first.
    - If AMBIGUOUS_TIMEOUT occurs on any mutation, blind retry is FORBIDDEN;
      requires independent verification before retry.
    - If action is read-only, safe bounded retry is permitted.
    - Model/planner proposals have ZERO authority.
    """
    assert_not_planner_for_recovery(action, parameter_name="action")
    if error is not None:
        assert_not_planner_for_recovery(error, parameter_name="error")
    if policy is not None:
        assert_not_planner_for_recovery(policy, parameter_name="policy")

    if not isinstance(action, ActionContract):
        raise TypeError(f"action must be ActionContract, got {type(action).__name__}")
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise TypeError("attempt_number must be an integer")
    if attempt_number < 1:
        raise ValueError(f"attempt_number must be >= 1, got {attempt_number}")

    strategy = get_idempotency_strategy(action)
    stable_key = derive_idempotency_key(action, attempt_number=attempt_number)

    if error is None:
        return RecoveryDecision(
            action_type=RecoveryActionType.DO_NOT_RETRY,
            action_id=action.action_id,
            attempt_number=attempt_number,
            delay_seconds=0.0,
            reason="Execution succeeded; no recovery required",
            idempotency_key=stable_key,
        )

    retry_dec = evaluate_retry(
        action=action,
        attempt_number=attempt_number,
        error=error,
        policy=policy,
    )

    # 1. Ambiguous timeout on mutation requires independent verification
    if retry_dec.requires_verification_before_retry:
        return RecoveryDecision(
            action_type=RecoveryActionType.REQUIRES_VERIFICATION,
            action_id=action.action_id,
            attempt_number=attempt_number,
            delay_seconds=0.0,
            reason=(
                "Ambiguous timeout on mutation requires independent verification "
                "before any retry decision"
            ),
            retry_classification=retry_dec.classification,
            idempotency_key=stable_key,
        )

    # 2. High duplicate creation risk actions (TASK_CREATE) require read-before-retry
    if strategy.requires_read_before_retry and retry_dec.should_retry:
        return RecoveryDecision(
            action_type=RecoveryActionType.REQUIRES_VERIFICATION,
            action_id=action.action_id,
            attempt_number=attempt_number,
            delay_seconds=0.0,
            reason=(
                "Action has duplicate creation risk; requires read-before-retry to "
                "verify whether intended effect already occurred"
            ),
            retry_classification=retry_dec.classification,
            idempotency_key=stable_key,
        )

    # 3. Actions where blind retry is prohibited (allows_blind_retry == False,
    # including CALENDAR_UPDATE) MUST NOT directly retry; must require independent
    # verification before any retry decision.
    if not strategy.allows_blind_retry and retry_dec.should_retry:
        return RecoveryDecision(
            action_type=RecoveryActionType.REQUIRES_VERIFICATION,
            action_id=action.action_id,
            attempt_number=attempt_number,
            delay_seconds=0.0,
            reason=(
                "Mutation strategy prohibits blind retry (allows_blind_retry=False); "
                "requires independent verification before retry decision"
            ),
            retry_classification=retry_dec.classification,
            idempotency_key=stable_key,
        )

    # 4. Safe retry eligible (actions with allows_blind_retry == True, such as read-only actions)
    if retry_dec.should_retry:
        return RecoveryDecision(
            action_type=RecoveryActionType.RETRY,
            action_id=action.action_id,
            attempt_number=attempt_number,
            delay_seconds=retry_dec.delay_seconds,
            reason=retry_dec.reason,
            retry_classification=retry_dec.classification,
            idempotency_key=stable_key,
        )

    # 4. Non-retryable failure (permanent, security, contract, or ceiling exhausted)
    return RecoveryDecision(
        action_type=RecoveryActionType.DO_NOT_RETRY,
        action_id=action.action_id,
        attempt_number=attempt_number,
        delay_seconds=0.0,
        reason=retry_dec.reason,
        retry_classification=retry_dec.classification,
        idempotency_key=stable_key,
    )


def evaluate_readback_recovery(
    *,
    action: ActionContract,
    attempt_number: int,
    readback_result: ReadbackVerificationResult,
    policy: RetryPolicy | None = None,
) -> RecoveryDecision:
    """Evaluate recovery decision following independent read-back / duplicate inspection.

    Laws:
    - INTENDED_EFFECT_EXISTS: Effect already exists! Core StillDone law dictates:
      "A retry is not allowed to create a second effect merely because the first response was lost."
      Decision = EFFECT_ALREADY_EXISTS.
    - DUPLICATE_DETECTED: Duplicate detected! Decision = DUPLICATE_PREVENTED.
    - EFFECT_ABSENT: Intended effect did not happen. If attempt count remains below
      effective ceiling, retry is eligible with bounded backoff. If ceiling reached, DO_NOT_RETRY.
    - INCONCLUSIVE: Verification could not prove reality. Fails closed with DO_NOT_RETRY.
      Blind retry is strictly prohibited.
    - Model/planner proposals have ZERO authority.
    """
    assert_not_planner_for_recovery(action, parameter_name="action")
    assert_not_planner_for_recovery(readback_result, parameter_name="readback_result")
    if policy is not None:
        assert_not_planner_for_recovery(policy, parameter_name="policy")

    if not isinstance(action, ActionContract):
        raise TypeError(f"action must be ActionContract, got {type(action).__name__}")
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise TypeError("attempt_number must be an integer")
    if attempt_number < 1:
        raise ValueError(f"attempt_number must be >= 1, got {attempt_number}")
    if not isinstance(readback_result, ReadbackVerificationResult):
        raise TypeError(
            f"readback_result must be ReadbackVerificationResult, "
            f"got {type(readback_result).__name__}"
        )
    if readback_result.action_id != action.action_id:
        raise RecoveryLineageError(
            f"ReadbackVerificationResult action_id {readback_result.action_id} "
            f"does not match action {action.action_id}"
        )

    strategy = get_idempotency_strategy(action)
    eff_policy = policy if policy is not None else RetryPolicy()
    stable_key = derive_idempotency_key(action, attempt_number=attempt_number)
    effective_ceiling = min(eff_policy.max_attempts, strategy.max_attempt_ceiling)

    # 1. Intended effect already exists
    if readback_result.outcome == ReadbackOutcome.INTENDED_EFFECT_EXISTS:
        return RecoveryDecision(
            action_type=RecoveryActionType.EFFECT_ALREADY_EXISTS,
            action_id=action.action_id,
            attempt_number=attempt_number,
            delay_seconds=0.0,
            reason=(
                "Independent read-back confirmed intended effect already exists in "
                "external system; further mutation prohibited"
            ),
            readback_outcome=ReadbackOutcome.INTENDED_EFFECT_EXISTS,
            idempotency_key=stable_key,
        )

    # 2. Duplicate effect detected
    if readback_result.outcome == ReadbackOutcome.DUPLICATE_DETECTED:
        return RecoveryDecision(
            action_type=RecoveryActionType.DUPLICATE_PREVENTED,
            action_id=action.action_id,
            attempt_number=attempt_number,
            delay_seconds=0.0,
            reason=(
                "Duplicate effect detected during read-back; further mutation halted to "
                "prevent exacerbating duplicate creation"
            ),
            readback_outcome=ReadbackOutcome.DUPLICATE_DETECTED,
            idempotency_key=stable_key,
        )

    # 3. Effect absent -> evaluate retry eligibility against ceiling
    if readback_result.outcome == ReadbackOutcome.EFFECT_ABSENT:
        if attempt_number >= effective_ceiling:
            return RecoveryDecision(
                action_type=RecoveryActionType.DO_NOT_RETRY,
                action_id=action.action_id,
                attempt_number=attempt_number,
                delay_seconds=0.0,
                reason=(
                    f"Attempt ceiling reached ({attempt_number} >= {effective_ceiling}); "
                    "retry budget exhausted"
                ),
                readback_outcome=ReadbackOutcome.EFFECT_ABSENT,
                idempotency_key=stable_key,
            )

        # Exponential backoff delay
        delay = min(
            eff_policy.base_delay_seconds * (eff_policy.backoff_multiplier ** (attempt_number - 1)),
            eff_policy.max_delay_seconds,
        )
        return RecoveryDecision(
            action_type=RecoveryActionType.RETRY,
            action_id=action.action_id,
            attempt_number=attempt_number,
            delay_seconds=delay,
            reason="Independent read-back confirmed effect absent; bounded retry permitted",
            readback_outcome=ReadbackOutcome.EFFECT_ABSENT,
            idempotency_key=stable_key,
        )

    # 4. Inconclusive verification -> fail closed
    return RecoveryDecision(
        action_type=RecoveryActionType.DO_NOT_RETRY,
        action_id=action.action_id,
        attempt_number=attempt_number,
        delay_seconds=0.0,
        reason=(
            "Independent verification was inconclusive; failing closed to prevent "
            "blind duplicate creation"
        ),
        readback_outcome=ReadbackOutcome.INCONCLUSIVE,
        idempotency_key=stable_key,
    )


# ===========================================================================
# Recovery Orchestrator Class
# ===========================================================================


class RecoveryOrchestrator:
    """Deterministic recovery coordinator.

    Encapsulates policy and coordinates post-execution and post-readback
    recovery evaluations.
    """

    def __init__(self, policy: RetryPolicy | None = None) -> None:
        if policy is not None:
            assert_not_planner_for_recovery(policy, parameter_name="policy")
        self._policy = policy or RetryPolicy()

    @property
    def policy(self) -> RetryPolicy:
        return self._policy

    def evaluate_execution_failure(
        self,
        *,
        action: ActionContract,
        attempt_number: int,
        error: Exception | str | int,
    ) -> RecoveryDecision:
        """Evaluate failure outcome and determine next recovery step."""
        return evaluate_post_execution_recovery(
            action=action,
            attempt_number=attempt_number,
            error=error,
            policy=self._policy,
        )

    def evaluate_readback_outcome(
        self,
        *,
        action: ActionContract,
        attempt_number: int,
        readback_result: ReadbackVerificationResult,
    ) -> RecoveryDecision:
        """Evaluate read-back / duplicate inspection result."""
        return evaluate_readback_recovery(
            action=action,
            attempt_number=attempt_number,
            readback_result=readback_result,
            policy=self._policy,
        )
