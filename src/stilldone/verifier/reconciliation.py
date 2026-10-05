"""Deterministic mission state reconciliation against fresh external state.

Phase P-09.05:
Re-evaluates a previously verified/READY mission against fresh independent read-back.

Core Architectural Laws:
- StillDone thesis: "Done, and still true."
- READY is not permanent merely because it was once true.
- Reconciliation MUST use fresh external read-back observations.
- Historical verification evidence != current truth.
- Recorded-live != current-live.
- Executor success != current desired-state truth.
- Model / planner has ZERO verification or reconciliation authority.
- Deterministic runtime owns all reconciliation determinations.
- Providers are NEVER mutated during reconciliation (read-only verification).
- Distinguishes fresh observations from historical observations fail-closed:
  identical observation objects or older timestamps are rejected as historical replay.
"""

from __future__ import annotations

import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.domain.desired_state import DesiredStatePredicate, PredicateId
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.execution.state import ProviderExecutionResult
from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    VerificationObservation,
    VerificationRequest,
    VerifierError,
)
from stilldone.verifier.dispatch import validate_verification_request_lineage
from stilldone.verifier.freshness import (
    DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
    FreshnessResult,
    FreshnessStatus,
    NaiveDatetimeError,
    evaluate_observation_freshness,
)
from stilldone.verifier.predicates import (
    PredicateEvaluationResult,
    PredicateTruth,
    evaluate_predicate,
)

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
# Reconciliation Exceptions
# ===========================================================================


class ReconciliationError(VerifierError):
    """Base exception for deterministic mission reconciliation failures."""


class HistoricalObservationSubstitutionError(ReconciliationError, ValueError):
    """Raised when an identical or older observation is substituted for fresh read-back."""


class PlannerReconciliationAuthorityError(ReconciliationError, TypeError):
    """Raised when a model/planner proposal object is passed as authority for reconciliation."""


class ReconciliationContractTypeError(ReconciliationError, TypeError):
    """Raised when inputs to reconciliation have invalid types."""


class ReconciliationContractValueError(ReconciliationError, ValueError):
    """Raised when inputs to reconciliation have invalid values."""


class ReconciliationLifecycleError(ReconciliationError, ValueError):
    """Raised when an illegal lifecycle transition is attempted during reconciliation."""


# ===========================================================================
# Model / Execution Payload Rejection Helper
# ===========================================================================


def assert_not_planner_or_execution_payload(obj: Any, *, parameter_name: str = "argument") -> None:
    """Reject planner/model proposals and execution payloads fail-closed."""
    if isinstance(obj, (ProviderExecutionResult, ExecutionAttempt)):
        raise ExecutionPayloadSubstitutionError(
            f"Execution payload {type(obj).__name__} cannot substitute for verification "
            f"facts in reconciliation ({parameter_name})"
        )

    for pt in _PLANNER_TYPES:
        if isinstance(obj, pt):
            raise PlannerReconciliationAuthorityError(
                f"Model/planner proposal {type(obj).__name__} has ZERO verification authority "
                f"and cannot be used for reconciliation ({parameter_name})"
            )

    if isinstance(obj, str) and parameter_name not in ("status", "prior_state"):
        msg = (
            "String prose cannot substitute for structured verification "
            f"contracts ({parameter_name})"
        )
        raise ReconciliationContractTypeError(msg)


# ===========================================================================
# Reconciliation Status & Determination Contract
# ===========================================================================


class ReconciliationStatus(StrEnum):
    """Deterministic outcome of reconciling mission desired state with fresh reality."""

    STILL_TRUE = "STILL_TRUE"
    NO_LONGER_TRUE = "NO_LONGER_TRUE"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class ReconciliationDetermination:
    """Immutable result of deterministic mission state reconciliation.

    Pure deterministic fact aggregate comparing fresh external read-back
    against canonical desired-state predicates for a previously verified mission.
    """

    mission_id: MissionId
    status: ReconciliationStatus
    reasons: tuple[str, ...]
    satisfied_predicate_ids: tuple[PredicateId, ...]
    drifted_predicate_ids: tuple[PredicateId, ...]
    stale_predicate_ids: tuple[PredicateId, ...]
    incomplete_predicate_ids: tuple[PredicateId, ...]
    evaluated_at: datetime
    predicate_evaluations: Mapping[PredicateId, PredicateEvaluationResult] = field(
        default_factory=dict
    )
    freshness_evaluations: Mapping[PredicateId, FreshnessResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise ReconciliationContractTypeError(
                f"mission_id must be a MissionId, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.status, ReconciliationStatus):
            raise ReconciliationContractTypeError(
                f"status must be a ReconciliationStatus, got {type(self.status).__name__}"
            )
        if not isinstance(self.reasons, tuple):
            raise ReconciliationContractTypeError("reasons must be a tuple")
        if not isinstance(self.satisfied_predicate_ids, tuple):
            raise ReconciliationContractTypeError("satisfied_predicate_ids must be a tuple")
        if not isinstance(self.drifted_predicate_ids, tuple):
            raise ReconciliationContractTypeError("drifted_predicate_ids must be a tuple")
        if not isinstance(self.stale_predicate_ids, tuple):
            raise ReconciliationContractTypeError("stale_predicate_ids must be a tuple")
        if not isinstance(self.incomplete_predicate_ids, tuple):
            raise ReconciliationContractTypeError("incomplete_predicate_ids must be a tuple")
        if not isinstance(self.evaluated_at, datetime):
            raise ReconciliationContractTypeError("evaluated_at must be a datetime")
        if self.evaluated_at.tzinfo is None:
            raise NaiveDatetimeError("evaluated_at must be timezone-aware")

        # Freeze mapping views to guarantee deep immutability
        if isinstance(self.predicate_evaluations, dict):
            object.__setattr__(
                self,
                "predicate_evaluations",
                types.MappingProxyType(dict(self.predicate_evaluations)),
            )
        if isinstance(self.freshness_evaluations, dict):
            object.__setattr__(
                self,
                "freshness_evaluations",
                types.MappingProxyType(dict(self.freshness_evaluations)),
            )

    @property
    def is_still_true(self) -> bool:
        """True if and only if reconciliation status is STILL_TRUE."""
        return self.status == ReconciliationStatus.STILL_TRUE

    def to_dict(self) -> dict[str, Any]:
        """Convert determination to a deterministic serializable dictionary."""
        return {
            "mission_id": str(self.mission_id),
            "status": self.status.value,
            "reasons": list(self.reasons),
            "satisfied_predicate_ids": [str(pid) for pid in self.satisfied_predicate_ids],
            "drifted_predicate_ids": [str(pid) for pid in self.drifted_predicate_ids],
            "stale_predicate_ids": [str(pid) for pid in self.stale_predicate_ids],
            "incomplete_predicate_ids": [str(pid) for pid in self.incomplete_predicate_ids],
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# ===========================================================================
# Deterministic Reconciliation Algorithm
# ===========================================================================


def reconcile_mission_state(
    *,
    mission_id: MissionId,
    predicates: Sequence[DesiredStatePredicate],
    verification_requests: Mapping[PredicateId, VerificationRequest],
    fresh_observations: Mapping[PredicateId, VerificationObservation],
    historical_observations: Mapping[PredicateId, VerificationObservation] | None = None,
    at: datetime,
    current_window_seconds: int = DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
) -> ReconciliationDetermination:
    """Reconcile previously verified mission desired state against fresh external read-back.

    Deterministic invariants:
    - Never trusts historical PredicateEvaluationResult or FreshnessResult.
    - Re-evaluates predicate truth and freshness independently against fresh observations.
    - Historical observation substitution is rejected: identical object or non-advancing timestamp
      raises HistoricalObservationSubstitutionError.
    - Model/planner output has ZERO authority.
    - Execution payloads cannot substitute for verification facts.
    - Provider is NEVER mutated.
    - Validates verification request lineage via validate_verification_request_lineage.
    - Fails closed on:
      * missing required verification request or observation;
      * predicate mismatch;
      * foreign mission/predicate;
      * execution payload substitution;
      * historical observation replay.
    """
    assert_not_planner_or_execution_payload(mission_id, parameter_name="mission_id")
    if not isinstance(mission_id, MissionId):
        raise ReconciliationContractTypeError(
            f"mission_id must be a MissionId, got {type(mission_id).__name__}"
        )

    # Validate evaluation timestamp `at`
    if not isinstance(at, datetime):
        raise ReconciliationContractTypeError(f"at must be a datetime, got {type(at).__name__}")
    if at.tzinfo is None:
        raise NaiveDatetimeError("Evaluation timestamp 'at' must be timezone-aware")
    eval_at = at.astimezone(UTC)

    # Validate predicates sequence
    assert_not_planner_or_execution_payload(predicates, parameter_name="predicates")
    if not isinstance(predicates, Sequence) or isinstance(predicates, (str, bytes)):
        raise ReconciliationContractTypeError(
            f"predicates must be a Sequence[DesiredStatePredicate], got {type(predicates).__name__}"
        )

    valid_pids: set[PredicateId] = set()
    for i, p in enumerate(predicates):
        assert_not_planner_or_execution_payload(p, parameter_name=f"predicates[{i}]")
        if not isinstance(p, DesiredStatePredicate):
            raise ReconciliationContractTypeError(
                f"predicates[{i}] must be a DesiredStatePredicate, got {type(p).__name__}"
            )
        if p.mission_id != mission_id:
            raise ReconciliationContractValueError(
                f"Predicate {p.predicate_id} mission_id {p.mission_id} does not match {mission_id}"
            )
        valid_pids.add(p.predicate_id)

    # Validate verification_requests mapping
    assert_not_planner_or_execution_payload(
        verification_requests, parameter_name="verification_requests"
    )
    if not isinstance(verification_requests, Mapping):
        raise ReconciliationContractTypeError("verification_requests must be a Mapping")

    for pid, req in verification_requests.items():
        assert_not_planner_or_execution_payload(req, parameter_name=f"verification_requests[{pid}]")
        if not isinstance(pid, PredicateId):
            raise ReconciliationContractTypeError("verification_requests key must be PredicateId")
        if not isinstance(req, VerificationRequest):
            raise ReconciliationContractTypeError(
                "verification_requests value must be VerificationRequest"
            )
        if pid not in valid_pids:
            raise ReconciliationContractValueError(
                f"verification_requests contains foreign predicate {pid}"
            )
        if req.mission_id != mission_id:
            raise ReconciliationContractValueError(
                f"VerificationRequest mission_id {req.mission_id} does not match {mission_id}"
            )
        validate_verification_request_lineage(req)
        if req.predicate is None:
            raise ReconciliationContractValueError(
                f"VerificationRequest predicate cannot be None for predicate {pid}"
            )
        if req.predicate.predicate_id != pid:
            raise ReconciliationContractValueError(
                f"VerificationRequest predicate_id does not match predicate {pid}"
            )
        matching_p = next(p for p in predicates if p.predicate_id == pid)
        if req.predicate != matching_p:
            raise ReconciliationContractValueError(
                f"VerificationRequest predicate does not match canonical predicate {pid}"
            )

    # Validate fresh_observations mapping
    assert_not_planner_or_execution_payload(fresh_observations, parameter_name="fresh_observations")
    if not isinstance(fresh_observations, Mapping):
        raise ReconciliationContractTypeError("fresh_observations must be a Mapping")

    for pid, obs in fresh_observations.items():
        assert_not_planner_or_execution_payload(obs, parameter_name=f"fresh_observations[{pid}]")
        if not isinstance(pid, PredicateId):
            raise ReconciliationContractTypeError("fresh_observations key must be PredicateId")
        if not isinstance(obs, VerificationObservation):
            raise ReconciliationContractTypeError(
                "fresh_observations value must be VerificationObservation"
            )
        if pid not in valid_pids:
            raise ReconciliationContractValueError(
                f"fresh_observations contains foreign predicate {pid}"
            )

    # Validate historical_observations if provided & check for illegal historical substitution
    if historical_observations is not None:
        assert_not_planner_or_execution_payload(
            historical_observations, parameter_name="historical_observations"
        )
        if not isinstance(historical_observations, Mapping):
            raise ReconciliationContractTypeError("historical_observations must be a Mapping")

        for pid, hist_obs in historical_observations.items():
            assert_not_planner_or_execution_payload(
                hist_obs, parameter_name=f"historical_observations[{pid}]"
            )
            if not isinstance(pid, PredicateId):
                raise ReconciliationContractTypeError(
                    "historical_observations key must be PredicateId"
                )
            if not isinstance(hist_obs, VerificationObservation):
                raise ReconciliationContractTypeError(
                    "historical_observations value must be VerificationObservation"
                )
            if pid not in valid_pids:
                raise ReconciliationContractValueError(
                    f"historical_observations contains foreign predicate {pid}"
                )

            # Check historical replay / substitution against fresh observation
            if pid in fresh_observations:
                fresh_obs = fresh_observations[pid]
                if fresh_obs is hist_obs:
                    msg = (
                        "Identical historical observation object reused as fresh "
                        f"observation for {pid}"
                    )
                    raise HistoricalObservationSubstitutionError(msg)
                if fresh_obs.observed_at <= hist_obs.observed_at:
                    msg = (
                        f"Fresh observation for {pid} timestamp "
                        f"({fresh_obs.observed_at.isoformat()}) "
                        "is not strictly newer than historical observation "
                        f"({hist_obs.observed_at.isoformat()})"
                    )
                    raise HistoricalObservationSubstitutionError(msg)

    # Re-evaluate all predicates against fresh observations
    final_pred_evals: dict[PredicateId, PredicateEvaluationResult] = {}
    final_fresh_evals: dict[PredicateId, FreshnessResult] = {}

    reasons: list[str] = []
    satisfied_pids: list[PredicateId] = []
    drifted_pids: list[PredicateId] = []
    stale_pids: list[PredicateId] = []
    incomplete_pids: list[PredicateId] = []

    if len(predicates) == 0:
        reasons.append("Mission has zero desired-state predicates to reconcile")

    for p in predicates:
        pid = p.predicate_id

        # 1. Verification request resolution
        if pid not in verification_requests:
            if p.required:
                incomplete_pids.append(pid)
                reasons.append(
                    f"Missing required verification request for predicate {pid} "
                    f"(subject: {p.subject})"
                )
            continue

        req = verification_requests[pid]

        # 2. Fresh observation resolution
        if pid not in fresh_observations:
            if p.required:
                incomplete_pids.append(pid)
                reasons.append(
                    f"Missing required fresh observation for predicate {pid} (subject: {p.subject})"
                )
            continue

        obs = fresh_observations[pid]

        # 3. Deterministic re-computation
        p_eval = evaluate_predicate(p, obs, expected_target=req.target, at=eval_at)
        f_eval = evaluate_observation_freshness(
            obs,
            p.freshness,
            at=eval_at,
            current_window_seconds=current_window_seconds,
        )

        final_pred_evals[pid] = p_eval
        final_fresh_evals[pid] = f_eval

        if p_eval.truth == PredicateTruth.TRUE:
            if f_eval.status == FreshnessStatus.FRESH:
                satisfied_pids.append(pid)
            else:
                if p.required:
                    stale_pids.append(pid)
                    reasons.append(
                        f"Fresh observation for predicate {pid} (subject: {p.subject}) is STALE "
                        f"(valid_until: {f_eval.valid_until.isoformat()})"
                    )
        else:
            if p.required:
                drifted_pids.append(pid)
                reasons.append(
                    f"Required predicate {pid} (subject: {p.subject}) evaluated FALSE on "
                    f"fresh read-back: {p_eval.reason}"
                )

    # Determine status
    if len(predicates) == 0:
        status = ReconciliationStatus.INCOMPLETE
    elif drifted_pids:
        status = ReconciliationStatus.NO_LONGER_TRUE
    elif incomplete_pids:
        status = ReconciliationStatus.INCOMPLETE
    elif stale_pids:
        status = ReconciliationStatus.STALE
    elif all(p.predicate_id in satisfied_pids for p in predicates if p.required):
        status = ReconciliationStatus.STILL_TRUE
    else:
        status = ReconciliationStatus.INCOMPLETE

    return ReconciliationDetermination(
        mission_id=mission_id,
        status=status,
        reasons=tuple(reasons),
        satisfied_predicate_ids=tuple(satisfied_pids),
        drifted_predicate_ids=tuple(drifted_pids),
        stale_predicate_ids=tuple(stale_pids),
        incomplete_predicate_ids=tuple(incomplete_pids),
        evaluated_at=eval_at,
        predicate_evaluations=final_pred_evals,
        freshness_evaluations=final_fresh_evals,
    )


# ===========================================================================
# Lifecycle Transition Contract & Engine
# ===========================================================================


@dataclass(frozen=True)
class ReconciliationTransitionResult:
    """Immutable outcome of applying reconciliation to a mission lifecycle state.

    Enforces that:
    - Transition is allowed ONLY from READY state.
    - If status == STILL_TRUE, remains READY.
    - If status != STILL_TRUE, transitions to DRIFTED.
    - Mismatch explanation is privacy-safe (zero raw IDs or provider payloads).
    """

    mission_id: MissionId
    prior_state: MissionState
    new_state: MissionState
    is_drifted: bool
    explanation: str | None
    reconciliation: ReconciliationDetermination

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise ReconciliationContractTypeError(
                f"mission_id must be a MissionId, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.prior_state, MissionState):
            raise ReconciliationContractTypeError("prior_state must be a MissionState")
        if not isinstance(self.new_state, MissionState):
            raise ReconciliationContractTypeError("new_state must be a MissionState")
        if not isinstance(self.is_drifted, bool):
            raise ReconciliationContractTypeError("is_drifted must be a bool")
        if self.explanation is not None and not isinstance(self.explanation, str):
            raise ReconciliationContractTypeError("explanation must be str or None")
        if not isinstance(self.reconciliation, ReconciliationDetermination):
            raise ReconciliationContractTypeError(
                "reconciliation must be ReconciliationDetermination"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert transition result to a deterministic serializable dictionary."""
        return {
            "mission_id": str(self.mission_id),
            "prior_state": self.prior_state.value,
            "new_state": self.new_state.value,
            "is_drifted": self.is_drifted,
            "explanation": self.explanation,
            "reconciliation": self.reconciliation.to_dict(),
        }


def apply_reconciliation_transition(
    *,
    prior_state: MissionState | str,
    reconciliation: ReconciliationDetermination,
) -> ReconciliationTransitionResult:
    """Apply deterministic lifecycle transition based on reconciliation results.

    Laws:
    - Transition is allowed ONLY from prior_state == READY.
    - If prior_state is not READY, fails closed (raises ReconciliationLifecycleError).
    - If reconciliation status is STILL_TRUE: remains READY (new_state=READY, is_drifted=False).
    - If reconciliation status is NO_LONGER_TRUE, STALE, or INCOMPLETE: transitions to DRIFTED
      (new_state=DRIFTED, is_drifted=True).
    - Explanation is privacy-safe: mentions predicate IDs only, strictly omitting
      external resource IDs, titles, notes, and raw provider payloads.
    - Model prose has ZERO authority.
    """
    assert_not_planner_or_execution_payload(prior_state, parameter_name="prior_state")
    assert_not_planner_or_execution_payload(reconciliation, parameter_name="reconciliation")

    if isinstance(prior_state, str):
        try:
            norm_prior = MissionState(prior_state)
        except ValueError as exc:
            raise ReconciliationContractValueError(
                f"Invalid mission state: {prior_state!r}"
            ) from exc
    elif isinstance(prior_state, MissionState):
        norm_prior = prior_state
    else:
        raise ReconciliationContractTypeError(
            f"prior_state must be MissionState or str, got {type(prior_state).__name__}"
        )

    if not isinstance(reconciliation, ReconciliationDetermination):
        msg = (
            "reconciliation must be ReconciliationDetermination, "
            f"got {type(reconciliation).__name__}"
        )
        raise ReconciliationContractTypeError(msg)

    if norm_prior != MissionState.READY:
        raise ReconciliationLifecycleError(
            "Reconciliation transition is only allowed from READY state, "
            f"but mission is {norm_prior.value}"
        )

    if reconciliation.status == ReconciliationStatus.STILL_TRUE:
        return ReconciliationTransitionResult(
            mission_id=reconciliation.mission_id,
            prior_state=norm_prior,
            new_state=MissionState.READY,
            is_drifted=False,
            explanation=None,
            reconciliation=reconciliation,
        )

    # Status is NO_LONGER_TRUE, STALE, or INCOMPLETE -> DRIFTED
    if reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE:
        drifted_items = [f"predicate {pid}" for pid in reconciliation.drifted_predicate_ids]
        desc = ", ".join(drifted_items) if drifted_items else "desired state contradicted"
        explanation = f"Mission drifted from READY: {desc}"
    elif reconciliation.status == ReconciliationStatus.STALE:
        stale_items = [f"predicate {pid}" for pid in reconciliation.stale_predicate_ids]
        desc = ", ".join(stale_items) if stale_items else "verification expired"
        explanation = f"Mission drifted from READY: observation stale for {desc}"
    else:  # INCOMPLETE
        inc_items = [f"predicate {pid}" for pid in reconciliation.incomplete_predicate_ids]
        desc = ", ".join(inc_items) if inc_items else "missing verification facts"
        explanation = f"Mission drifted from READY: required verification incomplete for {desc}"

    return ReconciliationTransitionResult(
        mission_id=reconciliation.mission_id,
        prior_state=norm_prior,
        new_state=MissionState.DRIFTED,
        is_drifted=True,
        explanation=explanation,
        reconciliation=reconciliation,
    )
