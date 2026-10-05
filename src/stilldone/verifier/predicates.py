"""Exact deterministic predicate evaluation for Calendar and Tasks.

Phase P-09.02:
Evaluates machine-checkable DesiredStatePredicates against independent
VerificationObservations.

Strict Laws:
- Predicates are deterministic facts; zero fuzzy matching or model judgment.
- Provider status "SUCCESS" is NEVER treated as predicate TRUE.
- Execution payload (ProviderExecutionResult) cannot substitute for read-back observation.
- Mismatched target identity produces deterministic FALSE / fail-closed.
- Bounded result vocabulary: TRUE, FALSE, NOT_EVALUABLE.
- Sensitive provider payloads are redacted in mismatch explanations.
- Zero mutations, zero network calls.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.domain.action import TargetIdentity
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    ExpectedValueType,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.execution import ExecutionAttempt
from stilldone.execution.state import ProviderExecutionResult
from stilldone.redaction import redact_text
from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    MalformedObservationError,
    VerificationObservation,
)

# ===========================================================================
# Predicate Evaluation Vocabulary
# ===========================================================================


class PredicateTruth(StrEnum):
    """Bounded deterministic truth values for predicate evaluation.

    Strictly binary-first:
    - TRUE: Observation independently satisfies the predicate.
    - FALSE: Observation contradicts the predicate or target mismatch.
    - NOT_EVALUABLE: Observation is missing required subject and cannot be compared.
    """

    TRUE = "TRUE"
    FALSE = "FALSE"
    NOT_EVALUABLE = "NOT_EVALUABLE"


# ===========================================================================
# Predicate Evaluation Result Contract
# ===========================================================================


@dataclass(frozen=True)
class PredicateEvaluationResult:
    """Immutable outcome of evaluating a DesiredStatePredicate against an observation."""

    predicate_id: PredicateId
    truth: PredicateTruth
    subject: str
    operator: PredicateOperator
    expected_value: ExpectedValueType
    observed_value: Any = None
    reason: str | None = None
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.predicate_id, PredicateId):
            raise TypeError("predicate_id must be a PredicateId instance")
        if not isinstance(self.truth, PredicateTruth):
            raise TypeError("truth must be a PredicateTruth instance")
        if not isinstance(self.subject, str):
            raise TypeError("subject must be a str")
        if not isinstance(self.operator, PredicateOperator):
            raise TypeError("operator must be a PredicateOperator")
        if not isinstance(self.evaluated_at, datetime):
            raise TypeError("evaluated_at must be a datetime")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise MalformedObservationError("evaluated_at must be timezone-aware")
        if self.evaluated_at.tzinfo != UTC:
            object.__setattr__(self, "evaluated_at", self.evaluated_at.astimezone(UTC))

        if self.reason is not None:
            if not isinstance(self.reason, str):
                raise TypeError("reason must be a str or None")
            object.__setattr__(self, "reason", redact_text(self.reason))

    @property
    def is_true(self) -> bool:
        """Return True if and only if predicate evaluated to TRUE."""
        return self.truth == PredicateTruth.TRUE

    @property
    def is_false(self) -> bool:
        """Return True if predicate evaluated to FALSE."""
        return self.truth == PredicateTruth.FALSE


# ===========================================================================
# Exact Subject Extraction Helper
# ===========================================================================


def _normalize_subject_key(subject: str) -> str:
    """Normalize subject path to extract property field name.

    Handles dot-separated paths (e.g. 'calendar.event.status' -> 'status',
    'task.title' -> 'title', 'status' -> 'status').
    """
    raw = subject.strip().lower()
    if not raw:
        return ""
    parts = raw.split(".")
    return parts[-1]


def _extract_observed_value(
    observation: VerificationObservation,
    subject: str,
) -> tuple[bool, Any]:
    """Extract subject value from observation target or properties.

    Returns:
        (found, value) tuple.
    """
    norm_key = _normalize_subject_key(subject)

    # 1. Special existence subject
    if norm_key == "exists":
        return True, observation.exists

    # 2. Target identity fields
    if norm_key in ("resource_id", "id", "event_id", "task_id", "location_id"):
        return True, observation.target.resource_id
    if norm_key in ("parent_id", "calendar_id", "task_list_id"):
        return True, observation.target.parent_id
    if norm_key == "system":
        return True, observation.target.system
    if norm_key == "resource_kind":
        return True, observation.target.resource_kind.value

    # 3. Observed properties
    if norm_key in observation.properties:
        return True, observation.properties[norm_key]

    return False, None


# ===========================================================================
# Strict Comparison Evaluator
# ===========================================================================


def _evaluate_operator(
    operator: PredicateOperator,
    observed_value: Any,
    expected_value: ExpectedValueType,
) -> bool:
    """Strictly evaluate a PredicateOperator without type coercion."""
    if operator == PredicateOperator.EXISTS:
        if isinstance(observed_value, bool):
            return observed_value is True
        return observed_value is not None

    if operator == PredicateOperator.DOES_NOT_EXIST:
        if isinstance(observed_value, bool):
            return observed_value is False
        return observed_value is None

    # Strict type equality to prevent Python bool/int collisions (e.g. True == 1)
    if isinstance(expected_value, bool) and not isinstance(observed_value, bool):
        return False
    if isinstance(observed_value, bool) and not isinstance(expected_value, bool):
        return False

    # Reject non-finite floats fail-closed for all comparisons
    if isinstance(observed_value, float) and not math.isfinite(observed_value):
        return False
    if isinstance(expected_value, float) and not math.isfinite(expected_value):
        return False

    if operator == PredicateOperator.EQUALS:
        return bool(observed_value == expected_value)

    if operator == PredicateOperator.NOT_EQUALS:
        return bool(observed_value != expected_value)

    # Ordered comparisons require comparable types and non-None non-bool operands
    if operator in (
        PredicateOperator.LESS_THAN,
        PredicateOperator.LESS_THAN_OR_EQUAL,
        PredicateOperator.GREATER_THAN,
        PredicateOperator.GREATER_THAN_OR_EQUAL,
    ):
        if expected_value is None or observed_value is None:
            return False
        if isinstance(expected_value, bool) or isinstance(observed_value, bool):
            return False

        if isinstance(observed_value, (int, float)) and isinstance(expected_value, (int, float)):
            # Exact native numeric comparison:
            # - int vs int: exact native integer comparison (arbitrary precision)
            # - int vs float / float vs int: Python compares exact without int coercion
            # - float vs float: exact finite IEEE 754 float comparison
            if operator == PredicateOperator.LESS_THAN:
                return observed_value < expected_value
            if operator == PredicateOperator.LESS_THAN_OR_EQUAL:
                return observed_value <= expected_value
            if operator == PredicateOperator.GREATER_THAN:
                return observed_value > expected_value
            if operator == PredicateOperator.GREATER_THAN_OR_EQUAL:
                return observed_value >= expected_value

        elif isinstance(observed_value, str) and isinstance(expected_value, str):
            if operator == PredicateOperator.LESS_THAN:
                return observed_value < expected_value
            if operator == PredicateOperator.LESS_THAN_OR_EQUAL:
                return observed_value <= expected_value
            if operator == PredicateOperator.GREATER_THAN:
                return observed_value > expected_value
            if operator == PredicateOperator.GREATER_THAN_OR_EQUAL:
                return observed_value >= expected_value

    return False


# ===========================================================================
# Exact Predicate Evaluator
# ===========================================================================


def evaluate_predicate(
    predicate: DesiredStatePredicate,
    observation: VerificationObservation,
    *,
    expected_target: TargetIdentity | None = None,
    at: datetime | None = None,
) -> PredicateEvaluationResult:
    """Evaluate an exact machine-checkable DesiredStatePredicate against an observation.

    Strict Laws:
    - Rejects ProviderExecutionResult / ExecutionAttempt payloads with
      ExecutionPayloadSubstitutionError.
    - Checks target identity: if expected_target is provided and mismatches observation.target,
      returns FALSE with target mismatch explanation.
    - If object does not exist (observation.exists == False) and operator is not DOES_NOT_EXIST:
      returns FALSE.
    - Evaluates exact equality, numeric bounds, and status fields without fuzzy matching.
    - Redacts sensitive payloads in error text.

    Args:
        predicate: Canonical DesiredStatePredicate.
        observation: Independent VerificationObservation.
        expected_target: Optional expected TargetIdentity for closed-world verification.
        at: Optional evaluation timestamp (defaults to UTC now).

    Returns:
        PredicateEvaluationResult.
    """
    # Strict independence law enforcement
    if isinstance(observation, (ProviderExecutionResult, ExecutionAttempt)):
        raise ExecutionPayloadSubstitutionError(
            f"Execution payload {type(observation).__name__} cannot substitute "
            "for VerificationObservation in predicate evaluation"
        )
    if not isinstance(observation, VerificationObservation):
        raise TypeError(
            f"observation must be a VerificationObservation, got {type(observation).__name__}"
        )
    if not isinstance(predicate, DesiredStatePredicate):
        raise TypeError(
            f"predicate must be a DesiredStatePredicate, got {type(predicate).__name__}"
        )

    eval_time = at or datetime.now(UTC)

    # 1. Closed-world Target Identity Assertion
    if expected_target is not None:
        if not isinstance(expected_target, TargetIdentity):
            raise TypeError("expected_target must be a TargetIdentity instance")
        if observation.target != expected_target:
            return PredicateEvaluationResult(
                predicate_id=predicate.predicate_id,
                truth=PredicateTruth.FALSE,
                subject=predicate.subject,
                operator=predicate.operator,
                expected_value=predicate.expected_value,
                observed_value=None,
                reason="Target identity mismatch",
                evaluated_at=eval_time,
            )

    # 2. Missing object handling
    if not observation.exists:
        if predicate.operator == PredicateOperator.DOES_NOT_EXIST:
            return PredicateEvaluationResult(
                predicate_id=predicate.predicate_id,
                truth=PredicateTruth.TRUE,
                subject=predicate.subject,
                operator=predicate.operator,
                expected_value=predicate.expected_value,
                observed_value=None,
                reason="Object independently observed as non-existent (matches DOES_NOT_EXIST)",
                evaluated_at=eval_time,
            )
        return PredicateEvaluationResult(
            predicate_id=predicate.predicate_id,
            truth=PredicateTruth.FALSE,
            subject=predicate.subject,
            operator=predicate.operator,
            expected_value=predicate.expected_value,
            observed_value=None,
            reason="External object does not exist in target system",
            evaluated_at=eval_time,
        )

    # 3. Subject extraction
    found, observed_value = _extract_observed_value(observation, predicate.subject)
    if not found:
        # Subject property is missing from the observation
        if predicate.operator == PredicateOperator.DOES_NOT_EXIST:
            return PredicateEvaluationResult(
                predicate_id=predicate.predicate_id,
                truth=PredicateTruth.TRUE,
                subject=predicate.subject,
                operator=predicate.operator,
                expected_value=predicate.expected_value,
                observed_value=None,
                reason=f"Required observation property absent for subject '{predicate.subject}'",
                evaluated_at=eval_time,
            )
        return PredicateEvaluationResult(
            predicate_id=predicate.predicate_id,
            truth=PredicateTruth.NOT_EVALUABLE,
            subject=predicate.subject,
            operator=predicate.operator,
            expected_value=predicate.expected_value,
            observed_value=None,
            reason=f"Required observation property absent for subject '{predicate.subject}'",
            evaluated_at=eval_time,
        )

    # 4. Strict operator evaluation
    passed = _evaluate_operator(predicate.operator, observed_value, predicate.expected_value)
    truth = PredicateTruth.TRUE if passed else PredicateTruth.FALSE
    if passed:
        reason = f"Exact predicate match for subject '{predicate.subject}'"
    else:
        reason = f"Exact predicate mismatch for subject '{predicate.subject}'"

    return PredicateEvaluationResult(
        predicate_id=predicate.predicate_id,
        truth=truth,
        subject=predicate.subject,
        operator=predicate.operator,
        expected_value=predicate.expected_value,
        observed_value=None,
        reason=reason,
        evaluated_at=eval_time,
    )


def evaluate_predicates(
    predicates: Iterable[DesiredStatePredicate],
    observation: VerificationObservation,
    *,
    expected_target: TargetIdentity | None = None,
    at: datetime | None = None,
) -> tuple[PredicateEvaluationResult, ...]:
    """Batch-evaluate multiple DesiredStatePredicates against a single observation."""
    return tuple(
        evaluate_predicate(p, observation, expected_target=expected_target, at=at)
        for p in predicates
    )
