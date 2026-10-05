"""Deterministic mission readiness computation for StillDone.

Phase P-09.04:
Computes MissionState.READY from deterministic verification facts and freshness.

Core Architectural Laws:
- Execution success is NOT verification.
- Provider / tool success is NOT predicate truth.
- Predicate truth is NOT automatically mission READY.
- Recorded historical evidence is NOT current external truth.
- Planner / model output is irrelevant to readiness truth (ZERO verification authority).
- No provider prose may directly create VERIFIED or READY.
- Deterministic runtime owns verifier dispatch, read-back facts, predicate evaluation,
  freshness, and mission readiness.
- P-09.04 computes readiness from supplied current verified facts, and must NOT:
    * re-read previously READY missions;
    * detect drift;
    * transition READY -> DRIFTED;
    * run reconciliation loops.
  (Drift and reconciliation belong strictly to P-09.05 / P-09.06).
"""

from __future__ import annotations

import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from stilldone.domain.action import ActionId
from stilldone.domain.desired_state import DesiredStatePredicate, PredicateId
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.execution.state import (
    ActionExecutionStatus,
    MissionExecutionRecord,
    ProviderExecutionResult,
)
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
# Readiness Exceptions
# ===========================================================================


class ReadinessError(VerifierError):
    """Base exception for deterministic readiness computation failures."""


class PlannerReadinessAuthorityError(ReadinessError, TypeError):
    """Raised when a model/planner proposal object is passed as authority for readiness."""


class ReadinessContractTypeError(ReadinessError, TypeError):
    """Raised when inputs to readiness computation have invalid types."""


class ReadinessContractValueError(ReadinessError, ValueError):
    """Raised when inputs to readiness computation have invalid values."""


# ===========================================================================
# Model / Execution Payload Rejection Helper
# ===========================================================================


def assert_not_planner_or_execution_payload(obj: Any, *, parameter_name: str = "argument") -> None:
    """Reject planner/model proposals and execution payloads fail-closed.

    Enforces StillDone core laws:
    - Model/planner output has ZERO verification authority.
    - Execution results / attempts cannot substitute for verification facts.
    """
    if isinstance(obj, (ProviderExecutionResult, ExecutionAttempt)):
        raise ExecutionPayloadSubstitutionError(
            f"Execution payload {type(obj).__name__} cannot substitute for verification "
            f"facts in readiness computation ({parameter_name})"
        )

    for pt in _PLANNER_TYPES:
        if isinstance(obj, pt):
            raise PlannerReadinessAuthorityError(
                f"Model/planner proposal {type(obj).__name__} has ZERO verification authority "
                f"and cannot be used for readiness computation ({parameter_name})"
            )

    # Reject string proposals pretending to be readiness authority
    if isinstance(obj, str) and parameter_name not in ("current_state",):
        msg = (
            "String prose cannot substitute for structured verification "
            f"contracts ({parameter_name})"
        )
        raise ReadinessContractTypeError(msg)


# ===========================================================================
# Mission Readiness Determination Record
# ===========================================================================


@dataclass(frozen=True)
class MissionReadinessDetermination:
    """Immutable result of deterministic mission readiness computation.

    Pure deterministic fact aggregate describing whether a mission is READY
    and the complete predicate, freshness, and action verification audit.
    """

    mission_id: MissionId
    is_ready: bool
    state: MissionState
    reasons: tuple[str, ...]
    satisfied_predicate_ids: tuple[PredicateId, ...]
    failed_predicate_ids: tuple[PredicateId, ...]
    stale_predicate_ids: tuple[PredicateId, ...]
    missing_predicate_ids: tuple[PredicateId, ...]
    unverified_action_ids: tuple[ActionId, ...]
    evaluated_at: datetime
    predicate_evaluations: Mapping[PredicateId, PredicateEvaluationResult] = field(
        default_factory=dict
    )
    freshness_evaluations: Mapping[PredicateId, FreshnessResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise ReadinessContractTypeError(
                f"mission_id must be a MissionId, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.is_ready, bool):
            raise ReadinessContractTypeError("is_ready must be a bool")
        if not isinstance(self.state, MissionState):
            raise ReadinessContractTypeError("state must be a MissionState")
        if not isinstance(self.reasons, tuple):
            raise ReadinessContractTypeError("reasons must be a tuple")
        if not isinstance(self.satisfied_predicate_ids, tuple):
            raise ReadinessContractTypeError("satisfied_predicate_ids must be a tuple")
        if not isinstance(self.failed_predicate_ids, tuple):
            raise ReadinessContractTypeError("failed_predicate_ids must be a tuple")
        if not isinstance(self.stale_predicate_ids, tuple):
            raise ReadinessContractTypeError("stale_predicate_ids must be a tuple")
        if not isinstance(self.missing_predicate_ids, tuple):
            raise ReadinessContractTypeError("missing_predicate_ids must be a tuple")
        if not isinstance(self.unverified_action_ids, tuple):
            raise ReadinessContractTypeError("unverified_action_ids must be a tuple")
        if not isinstance(self.evaluated_at, datetime):
            raise ReadinessContractTypeError("evaluated_at must be a datetime")
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

    def to_dict(self) -> dict[str, Any]:
        """Convert determination to a deterministic serializable dictionary."""
        return {
            "mission_id": str(self.mission_id),
            "is_ready": self.is_ready,
            "state": self.state.value,
            "reasons": list(self.reasons),
            "satisfied_predicate_ids": [str(pid) for pid in self.satisfied_predicate_ids],
            "failed_predicate_ids": [str(pid) for pid in self.failed_predicate_ids],
            "stale_predicate_ids": [str(pid) for pid in self.stale_predicate_ids],
            "missing_predicate_ids": [str(pid) for pid in self.missing_predicate_ids],
            "unverified_action_ids": [str(aid) for aid in self.unverified_action_ids],
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# ===========================================================================
# Deterministic Readiness Evaluator
# ===========================================================================


def compute_mission_readiness(
    *,
    mission_id: MissionId,
    predicates: Sequence[DesiredStatePredicate],
    verification_requests: Mapping[PredicateId, VerificationRequest] | None = None,
    predicate_evaluations: Mapping[PredicateId, PredicateEvaluationResult] | None = None,
    freshness_evaluations: Mapping[PredicateId, FreshnessResult] | None = None,
    observations: Mapping[PredicateId, VerificationObservation] | None = None,
    execution_record: MissionExecutionRecord | None = None,
    current_state: MissionState | str = MissionState.VERIFYING,
    at: datetime,
    current_window_seconds: int = DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
) -> MissionReadinessDetermination:
    """Compute deterministic mission readiness from verified facts.

    READY requirements:
    - current_state must be VERIFYING (READY may only be entered from VERIFYING).
    - at least one predicate must be defined.
    - each required predicate must bind to its canonical verification request and observation.
    - all required predicates must evaluate to PredicateTruth.TRUE against their observations.
    - no required predicate may evaluate to PredicateTruth.FALSE.
    - all required verification observations must be FreshnessStatus.FRESH.
    - no required observation may be STALE.
    - no required predicate may have a missing verifier request or observation.
    - no required action may be NOT_RUN, BLOCKED, FAILED, or IN_PROGRESS.

    Execution success alone is INSUFFICIENT.
    Provider success alone is INSUFFICIENT.
    Model / planner proposals have ZERO authority.
    """
    assert_not_planner_or_execution_payload(mission_id, parameter_name="mission_id")
    if not isinstance(mission_id, MissionId):
        raise ReadinessContractTypeError(
            f"mission_id must be a MissionId, got {type(mission_id).__name__}"
        )

    # Normalize current_state
    if isinstance(current_state, str):
        try:
            cur_state = MissionState(current_state)
        except ValueError as exc:
            raise ReadinessContractValueError(f"Invalid mission state: {current_state!r}") from exc
    elif isinstance(current_state, MissionState):
        cur_state = current_state
    else:
        raise ReadinessContractTypeError(
            f"current_state must be MissionState or str, got {type(current_state).__name__}"
        )

    # Validate evaluation point timestamp `at`
    if not isinstance(at, datetime):
        raise ReadinessContractTypeError(f"at must be a datetime, got {type(at).__name__}")
    if at.tzinfo is None:
        raise NaiveDatetimeError("Evaluation timestamp 'at' must be timezone-aware")
    eval_at = at.astimezone(UTC)

    # Validate predicates sequence
    assert_not_planner_or_execution_payload(predicates, parameter_name="predicates")
    if not isinstance(predicates, Sequence) or isinstance(predicates, (str, bytes)):
        raise ReadinessContractTypeError(
            f"predicates must be a Sequence[DesiredStatePredicate], got {type(predicates).__name__}"
        )

    valid_pids: set[PredicateId] = set()
    for i, p in enumerate(predicates):
        assert_not_planner_or_execution_payload(p, parameter_name=f"predicates[{i}]")
        if not isinstance(p, DesiredStatePredicate):
            raise ReadinessContractTypeError(
                f"predicates[{i}] must be a DesiredStatePredicate, got {type(p).__name__}"
            )
        if p.mission_id != mission_id:
            raise ReadinessContractValueError(
                f"Predicate {p.predicate_id} mission_id {p.mission_id} does not match {mission_id}"
            )
        valid_pids.add(p.predicate_id)

    # Validate verification_requests if provided
    if verification_requests is not None:
        assert_not_planner_or_execution_payload(
            verification_requests, parameter_name="verification_requests"
        )
        if not isinstance(verification_requests, Mapping):
            raise ReadinessContractTypeError("verification_requests must be a Mapping")
        for pid, req in verification_requests.items():
            assert_not_planner_or_execution_payload(
                req, parameter_name=f"verification_requests[{pid}]"
            )
            if not isinstance(pid, PredicateId):
                raise ReadinessContractTypeError("verification_requests key must be PredicateId")
            if not isinstance(req, VerificationRequest):
                raise ReadinessContractTypeError(
                    "verification_requests value must be VerificationRequest"
                )
            if pid not in valid_pids:
                raise ReadinessContractValueError(
                    f"verification_requests contains foreign predicate {pid}"
                )
            if req.mission_id != mission_id:
                raise ReadinessContractValueError(
                    f"VerificationRequest mission_id {req.mission_id} does not match {mission_id}"
                )
            if req.predicate is not None and req.predicate.mission_id != mission_id:
                raise ReadinessContractValueError(
                    f"VerificationRequest predicate mission_id {req.predicate.mission_id} "
                    f"does not match {mission_id}"
                )
            validate_verification_request_lineage(req)

    # Validate observations if provided
    if observations is not None:
        assert_not_planner_or_execution_payload(observations, parameter_name="observations")
        if not isinstance(observations, Mapping):
            raise ReadinessContractTypeError("observations must be a Mapping")
        for pid, obs in observations.items():
            assert_not_planner_or_execution_payload(obs, parameter_name=f"observations[{pid}]")
            if not isinstance(pid, PredicateId):
                raise ReadinessContractTypeError("observations key must be PredicateId")
            if not isinstance(obs, VerificationObservation):
                raise ReadinessContractTypeError(
                    "observations value must be VerificationObservation"
                )
            if pid not in valid_pids:
                raise ReadinessContractValueError(f"observations contains foreign predicate {pid}")

    # Validate caller-supplied predicate_evaluations if provided
    if predicate_evaluations is not None:
        assert_not_planner_or_execution_payload(
            predicate_evaluations, parameter_name="predicate_evaluations"
        )
        if not isinstance(predicate_evaluations, Mapping):
            raise ReadinessContractTypeError("predicate_evaluations must be a Mapping")
        for pid, eval_res in predicate_evaluations.items():
            assert_not_planner_or_execution_payload(
                eval_res, parameter_name=f"predicate_evaluations[{pid}]"
            )
            if not isinstance(pid, PredicateId):
                raise ReadinessContractTypeError("predicate_evaluations key must be PredicateId")
            if not isinstance(eval_res, PredicateEvaluationResult):
                raise ReadinessContractTypeError(
                    "predicate_evaluations value must be PredicateEvaluationResult"
                )
            if pid not in valid_pids:
                raise ReadinessContractValueError(
                    f"predicate_evaluations contains foreign predicate {pid}"
                )

    # Validate caller-supplied freshness_evaluations if provided
    if freshness_evaluations is not None:
        assert_not_planner_or_execution_payload(
            freshness_evaluations, parameter_name="freshness_evaluations"
        )
        if not isinstance(freshness_evaluations, Mapping):
            raise ReadinessContractTypeError("freshness_evaluations must be a Mapping")
        for pid, fresh_res in freshness_evaluations.items():
            assert_not_planner_or_execution_payload(
                fresh_res, parameter_name=f"freshness_evaluations[{pid}]"
            )
            if not isinstance(pid, PredicateId):
                raise ReadinessContractTypeError("freshness_evaluations key must be PredicateId")
            if not isinstance(fresh_res, FreshnessResult):
                raise ReadinessContractTypeError(
                    "freshness_evaluations value must be FreshnessResult"
                )
            if pid not in valid_pids:
                raise ReadinessContractValueError(
                    f"freshness_evaluations contains foreign predicate {pid}"
                )

    # Validate execution_record if provided
    unverified_action_ids: list[ActionId] = []
    action_reasons: list[str] = []
    if execution_record is not None:
        assert_not_planner_or_execution_payload(execution_record, parameter_name="execution_record")
        if not isinstance(execution_record, MissionExecutionRecord):
            rec_type = type(execution_record).__name__
            raise ReadinessContractTypeError(
                f"execution_record must be MissionExecutionRecord, got {rec_type}"
            )
        if execution_record.mission_id != mission_id:
            msg = (
                f"execution_record mission_id {execution_record.mission_id} "
                f"does not match {mission_id}"
            )
            raise ReadinessContractValueError(msg)

        for aid, rec in execution_record.step_records.items():
            if rec.status != ActionExecutionStatus.EXECUTION_SUCCEEDED:
                unverified_action_ids.append(aid)
                if rec.status == ActionExecutionStatus.EXECUTION_FAILED:
                    action_reasons.append(
                        f"Action {aid} failed execution: {rec.error_message or 'unspecified error'}"
                    )
                elif rec.status == ActionExecutionStatus.BLOCKED:
                    action_reasons.append(
                        f"Action {aid} was blocked by prerequisite {rec.blocked_by}"
                    )
                elif rec.status == ActionExecutionStatus.NOT_RUN:
                    action_reasons.append(f"Action {aid} has not been executed (NOT_RUN)")
                elif rec.status == ActionExecutionStatus.IN_PROGRESS:
                    action_reasons.append(f"Action {aid} is still in progress")

    # Evaluate readiness conditions
    final_pred_evals: dict[PredicateId, PredicateEvaluationResult] = {}
    final_fresh_evals: dict[PredicateId, FreshnessResult] = {}

    reasons: list[str] = list(action_reasons)
    satisfied_predicate_ids: list[PredicateId] = []
    failed_predicate_ids: list[PredicateId] = []
    stale_predicate_ids: list[PredicateId] = []
    missing_predicate_ids: list[PredicateId] = []

    if len(predicates) == 0:
        reasons.append(
            "Mission requires at least one desired-state predicate to be verified for READY"
        )

    if cur_state != MissionState.VERIFYING:
        reasons.append(
            f"Mission current_state is {cur_state}; READY may only be entered from VERIFYING"
        )

    for p in predicates:
        pid = p.predicate_id

        # 1. Verification request resolution
        if verification_requests is None or pid not in verification_requests:
            if p.required:
                missing_predicate_ids.append(pid)
                reasons.append(
                    f"Missing required verifier request for predicate {pid} (subject: {p.subject})"
                )
            continue

        req = verification_requests[pid]
        if req.mission_id != mission_id:
            raise ReadinessContractValueError(
                f"VerificationRequest mission_id {req.mission_id} does not match {mission_id}"
            )
        validate_verification_request_lineage(req)
        if req.predicate is None:
            if p.required:
                raise ReadinessContractValueError(
                    f"VerificationRequest predicate cannot be None for required predicate {pid}"
                )
            raise ReadinessContractValueError(
                f"VerificationRequest predicate cannot be None for desired state predicate {pid}"
            )
        if req.predicate.predicate_id != pid:
            raise ReadinessContractValueError(
                f"VerificationRequest predicate_id does not match desired state predicate {pid}"
            )
        if req.predicate != p:
            raise ReadinessContractValueError(
                f"VerificationRequest predicate does not match desired state predicate {pid}"
            )

        # 2. Verification observation resolution
        if observations is None or pid not in observations:
            if p.required:
                missing_predicate_ids.append(pid)
                reasons.append(
                    f"Missing required verifier observation for predicate {pid} "
                    f"(subject: {p.subject})"
                )
            continue

        obs = observations[pid]

        # 3. Deterministic re-computation against observation with expected_target bound to request
        expected_target = req.target
        canonical_p_eval = evaluate_predicate(p, obs, expected_target=expected_target, at=eval_at)
        canonical_f_eval = evaluate_observation_freshness(
            obs,
            p.freshness,
            at=eval_at,
            current_window_seconds=current_window_seconds,
        )

        # 4. Anti-forgery check against caller-supplied evaluations
        if predicate_evaluations is not None and pid in predicate_evaluations:
            supplied_p = predicate_evaluations[pid]
            if supplied_p.predicate_id != pid:
                raise ReadinessContractValueError(
                    f"Supplied predicate evaluation predicate_id mismatch for {pid}"
                )
            if supplied_p.subject != p.subject:
                raise ReadinessContractValueError(
                    f"Supplied predicate evaluation subject mismatch for {pid}"
                )
            if supplied_p.operator != p.operator:
                raise ReadinessContractValueError(
                    f"Supplied predicate evaluation operator mismatch for {pid}"
                )
            if supplied_p.expected_value != p.expected_value:
                raise ReadinessContractValueError(
                    f"Supplied predicate evaluation expected_value mismatch for {pid}"
                )
            if (
                supplied_p.truth == PredicateTruth.TRUE
                and canonical_p_eval.truth != PredicateTruth.TRUE
            ):
                raise ReadinessContractValueError(
                    f"Contradiction: supplied evaluation claims TRUE for {pid}, "
                    f"but canonical observation evaluates {canonical_p_eval.truth}"
                )
            final_p_eval = canonical_p_eval
        else:
            final_p_eval = canonical_p_eval

        if freshness_evaluations is not None and pid in freshness_evaluations:
            supplied_f = freshness_evaluations[pid]
            if getattr(supplied_f, "predicate_id", pid) != pid:
                raise ReadinessContractValueError(
                    f"Supplied freshness evaluation predicate_id mismatch for {pid}"
                )
            if (
                supplied_f.status == FreshnessStatus.FRESH
                and canonical_f_eval.status != FreshnessStatus.FRESH
            ):
                raise ReadinessContractValueError(
                    f"Contradiction: supplied evaluation claims FRESH for {pid}, "
                    f"but canonical observation is {canonical_f_eval.status}"
                )
            final_f_eval = canonical_f_eval
        else:
            final_f_eval = canonical_f_eval

        final_pred_evals[pid] = final_p_eval
        final_fresh_evals[pid] = final_f_eval

        if final_p_eval.truth == PredicateTruth.TRUE:
            if final_f_eval.status == FreshnessStatus.FRESH:
                satisfied_predicate_ids.append(pid)
            else:
                if p.required:
                    stale_predicate_ids.append(pid)
                    reasons.append(
                        f"Predicate {pid} (subject: {p.subject}) observation is STALE "
                        f"(valid_until: {final_f_eval.valid_until.isoformat()})"
                    )
        else:
            if p.required:
                failed_predicate_ids.append(pid)
                reasons.append(
                    f"Required predicate {pid} ({p.subject}) evaluated FALSE: {final_p_eval.reason}"
                )

    # Compute deterministically whether the mission is READY
    is_ready = (
        cur_state == MissionState.VERIFYING
        and len(predicates) > 0
        and len(failed_predicate_ids) == 0
        and len(stale_predicate_ids) == 0
        and len(missing_predicate_ids) == 0
        and len(unverified_action_ids) == 0
        and all(p.predicate_id in satisfied_predicate_ids for p in predicates if p.required)
    )

    if is_ready:
        target_state = MissionState.READY
    elif cur_state != MissionState.VERIFYING:
        target_state = cur_state
    elif failed_predicate_ids or (execution_record and execution_record.has_failures):
        if satisfied_predicate_ids:
            target_state = MissionState.PARTIAL
        else:
            target_state = MissionState.FAILED
    else:
        target_state = MissionState.VERIFYING

    return MissionReadinessDetermination(
        mission_id=mission_id,
        is_ready=is_ready,
        state=target_state,
        reasons=tuple(reasons),
        satisfied_predicate_ids=tuple(satisfied_predicate_ids),
        failed_predicate_ids=tuple(failed_predicate_ids),
        stale_predicate_ids=tuple(stale_predicate_ids),
        missing_predicate_ids=tuple(missing_predicate_ids),
        unverified_action_ids=tuple(unverified_action_ids),
        evaluated_at=eval_at,
        predicate_evaluations=final_pred_evals,
        freshness_evaluations=final_fresh_evals,
    )
