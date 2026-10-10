"""Deterministic external-change drift detection for StillDone.

Phases P-12.04 & P-12.05:
Detects changes to externally verified resources across Google Calendar and
Google Tasks using existing read adapters and canonical verifier contracts.

Core Architectural Laws:
- StillDone invariant: "Done, and still true."
- Compares fresh independently observed external state against persisted desired state.
- Detects time, summary, status, completion reversal, and missing resource changes.
- Preserves exact entity identity (calendar ID + event ID, task list ID + task ID).
  Never matches events or tasks by title alone.
- A legitimate persisted READY mission may transition to DRIFTED only through
  canonical lifecycle rules and durable evidence.
- Never fabricates a READY predecessor solely to demonstrate drift.
- Errors (transport / API failures) and stale reads must NOT masquerade as confirmed drift.
- Strictly read-only: zero provider writes, zero task creation, zero approval consumption.
- Cross-provider parity: Calendar and Tasks drift logic share the same domain contracts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from stilldone.adapters.calendar import GoogleCalendarReadAdapter
from stilldone.adapters.tasks import GoogleTasksReadAdapter
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.desired_state import DesiredStatePredicate, PredicateId
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.ledger import EvidenceRecord
from stilldone.redaction import redact_text
from stilldone.snapshot import (
    SUPPORTED_SNAPSHOT_VERSIONS,
    DurableSnapshotRepository,
    MissionSnapshot,
    SnapshotIntegrityError,
    create_mission_snapshot,
)
from stilldone.verifier.contracts import (
    VerificationObservation,
    VerificationRequest,
    VerifierReadError,
)
from stilldone.verifier.dispatch import (
    CalendarVerificationPort,
    TasksVerificationPort,
)
from stilldone.verifier.freshness import (
    DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
)
from stilldone.verifier.predicates import (
    PredicateTruth,
    evaluate_predicate,
)
from stilldone.verifier.reconciliation import (
    ReconciliationDetermination,
    ReconciliationLifecycleError,
    ReconciliationStatus,
    ReconciliationTransitionResult,
    apply_reconciliation_transition,
    reconcile_mission_state,
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
# Drift Exceptions
# ===========================================================================


class DriftError(Exception):
    """Base exception for all StillDone drift detection operations."""


class DriftTypeError(DriftError, TypeError):
    """Raised when an argument has an invalid type."""


class DriftValueError(DriftError, ValueError):
    """Raised when an argument has an invalid value."""


class DriftTargetMismatchError(DriftError, ValueError):
    """Raised when an external target does not match the bound identity or lineage."""


class PlannerDriftAuthorityError(DriftError, TypeError):
    """Raised when a planner/model proposal is passed into drift operations."""


def assert_not_planner_for_drift(obj: Any, *, parameter_name: str = "argument") -> None:
    """Reject planner/model proposals fail-closed."""
    for pt in _PLANNER_TYPES:
        if isinstance(obj, pt):
            raise PlannerDriftAuthorityError(
                f"Model/planner proposal {type(obj).__name__} has ZERO authority "
                f"in drift detection ({parameter_name})"
            )


# ===========================================================================
# Drift Evaluation Result Contract
# ===========================================================================


@dataclass(frozen=True)
class MissionDriftEvaluationResult:
    """Immutable result of evaluating external-change drift on a mission."""

    mission_id: MissionId
    prior_state: MissionState
    new_state: MissionState
    is_drifted: bool
    reconciliation: ReconciliationDetermination | None
    transition_result: ReconciliationTransitionResult | None
    evaluated_at: datetime
    is_inconclusive: bool
    error_message: str | None
    fresh_observations: Mapping[PredicateId, VerificationObservation]
    is_whole_mission: bool = True
    is_partial: bool = False
    scope: str = "whole_mission"

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise DriftTypeError("mission_id must be MissionId")
        if not isinstance(self.prior_state, MissionState):
            raise DriftTypeError("prior_state must be MissionState")
        if not isinstance(self.new_state, MissionState):
            raise DriftTypeError("new_state must be MissionState")
        if not isinstance(self.is_drifted, bool):
            raise DriftTypeError("is_drifted must be bool")
        if not isinstance(self.is_inconclusive, bool):
            raise DriftTypeError("is_inconclusive must be bool")
        if not isinstance(self.evaluated_at, datetime):
            raise DriftTypeError("evaluated_at must be datetime")


CALENDAR_SUBJECTS: frozenset[str] = frozenset(
    {
        "summary",
        "start",
        "end",
        "all_day",
        "allday",
        "event_id",
        "calendar_id",
        "description",
        "location",
        "start_time",
        "end_time",
    }
)
TASKS_SUBJECTS: frozenset[str] = frozenset(
    {
        "title",
        "due",
        "completed",
        "deleted",
        "task_id",
        "task_list_id",
        "notes",
        "due_date",
    }
)


def _normalize_subject(subject: str) -> str:
    """Normalize subject path to extract property field name."""
    parts = subject.strip().lower().split(".")
    return parts[-1]


def _resolve_target_for_predicate(
    predicate: DesiredStatePredicate,
    snapshot: MissionSnapshot,
    explicit_target: TargetIdentity | None = None,
    expected_system: str | None = None,
    expected_kind: ResourceKind | None = None,
) -> TargetIdentity:
    """Resolve and validate the exact TargetIdentity bound to a predicate.

    Enforces authoritative PredicateTargetBinding lineage:
    - Resolves target directly from snapshot.get_target_for_predicate();
    - If explicit_target is provided, it must match the canonical predicate binding;
    - Reject missing, foreign or mismatched targets fail-closed.
    """
    canonical_target: TargetIdentity | None = None
    try:
        canonical_target = snapshot.get_target_for_predicate(predicate.predicate_id)
    except (SnapshotIntegrityError, AttributeError):
        canonical_target = None

    if canonical_target is None:
        matching_actions = [
            a
            for a in snapshot.actions
            if a.mission_id == snapshot.mission_id
            and (expected_system is None or a.target.system == expected_system)
            and (expected_kind is None or a.target.resource_kind == expected_kind)
        ]
        if len(matching_actions) > 1:
            raise DriftTargetMismatchError(
                f"Ambiguous target for predicate {predicate.predicate_id}: multiple actions "
                f"({len(matching_actions)}) match {expected_system}/{expected_kind}; "
                "explicit PredicateTargetBinding is strictly required fail-closed "
                "(no heuristic guessing)"
            )
        elif len(matching_actions) == 0:
            raise DriftTargetMismatchError(
                f"No bound action target found for predicate {predicate.predicate_id} "
                f"matching {expected_system}/{expected_kind}"
            )
        else:
            canonical_target = matching_actions[0].target

    if explicit_target is not None:
        if explicit_target != canonical_target:
            raise DriftTargetMismatchError(
                f"Explicit target {explicit_target} does not match canonical binding "
                f"{canonical_target} for predicate {predicate.predicate_id}"
            )
        target = explicit_target
    else:
        target = canonical_target

    if not isinstance(target, TargetIdentity):
        raise DriftTypeError("target must be TargetIdentity")

    # Strict identity check
    if not target.resource_id or not target.resource_id.strip():
        raise DriftValueError("Target resource_id must be non-empty; cannot match by title alone")
    if not target.parent_id or not target.parent_id.strip():
        raise DriftValueError("Target parent_id must be non-empty; exact container required")

    if expected_system is not None and target.system != expected_system:
        raise DriftTargetMismatchError(
            f"Target system mismatch: expected {expected_system}, got {target.system}"
        )
    if expected_kind is not None and target.resource_kind != expected_kind:
        raise DriftTargetMismatchError(
            f"Target resource_kind mismatch: expected {expected_kind}, got {target.resource_kind}"
        )

    return target


# ===========================================================================
# Calendar Drift Detection (Phase P-12.04)
# ===========================================================================


def detect_calendar_drift(
    *,
    snapshot: MissionSnapshot,
    calendar_adapter: GoogleCalendarReadAdapter,
    target: TargetIdentity | None = None,
    historical_observations: Mapping[PredicateId, VerificationObservation] | None = None,
    eval_at: datetime | None = None,
    current_window_seconds: int = DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
) -> MissionDriftEvaluationResult:
    """Detect external-change drift on Google Calendar event for a READY mission.

    Enforces:
    - Exact calendar and event identity (never matches by title alone);
    - Legal lifecycle transition: only transitions READY -> DRIFTED if desired state
      is independently contradicted by fresh observations;
    - Rejects unverified / non-READY predecessors (never fabricates READY);
    - Fails closed on stale reads, 404s, or provider errors without masquerading as drift;
    - Strictly read-only: zero Calendar writes or approval grants.
    """
    assert_not_planner_for_drift(snapshot, parameter_name="snapshot")
    assert_not_planner_for_drift(calendar_adapter, parameter_name="calendar_adapter")

    if not isinstance(snapshot, MissionSnapshot):
        raise DriftTypeError("snapshot must be MissionSnapshot")
    if not isinstance(calendar_adapter, GoogleCalendarReadAdapter):
        raise DriftTypeError("calendar_adapter must be GoogleCalendarReadAdapter")

    now = eval_at or datetime.now(UTC)

    # 1. Lineage & State Enforcement
    if snapshot.state != MissionState.READY:
        raise ReconciliationLifecycleError(
            f"Drift detection is only permitted from READY state; mission is {snapshot.state.value}"
        )

    calendar_predicates = []
    for p in snapshot.desired_state:
        try:
            canonical_tgt = snapshot.get_target_for_predicate(p.predicate_id)
            if canonical_tgt.system != "google_calendar":
                continue
        except (SnapshotIntegrityError, AttributeError):
            pass

        _resolve_target_for_predicate(
            p,
            snapshot,
            explicit_target=target,
            expected_system="google_calendar",
            expected_kind=ResourceKind.CALENDAR_EVENT,
        )
        calendar_predicates.append(p)

    if not calendar_predicates:
        raise DriftValueError("Snapshot has zero calendar predicates to evaluate for drift")

    # 2. Port setup & Fresh Read-Back
    port = CalendarVerificationPort(calendar_adapter)
    fresh_observations: dict[PredicateId, VerificationObservation] = {}
    verification_requests: dict[PredicateId, VerificationRequest] = {}

    for pred in calendar_predicates:
        bound_target = _resolve_target_for_predicate(
            pred,
            snapshot,
            explicit_target=target,
            expected_system="google_calendar",
            expected_kind=ResourceKind.CALENDAR_EVENT,
        )

        read_action = ActionContract.create(
            mission_id=snapshot.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=bound_target,
            parameters={},
        )
        req = VerificationRequest(
            mission_id=snapshot.mission_id,
            action=read_action,
            target=bound_target,
            predicate=pred,
        )
        verification_requests[pred.predicate_id] = req

        try:
            obs = port.read(req)
            fresh_observations[pred.predicate_id] = obs
        except (VerifierReadError, Exception) as exc:
            # Transport / provider errors MUST NOT masquerade as confirmed drift!
            return MissionDriftEvaluationResult(
                mission_id=snapshot.mission_id,
                prior_state=snapshot.state,
                new_state=snapshot.state,
                is_drifted=False,
                reconciliation=None,
                transition_result=None,
                evaluated_at=now,
                is_inconclusive=True,
                error_message=f"Calendar provider read error: {redact_text(str(exc))}",
                fresh_observations={},
            )

    # 3. Deterministic Reconciliation
    effective_at = (
        eval_at
        if eval_at is not None
        else max(
            datetime.now(UTC),
            *(obs.observed_at for obs in fresh_observations.values()),
        )
    )
    reconciliation = reconcile_mission_state(
        mission_id=snapshot.mission_id,
        predicates=calendar_predicates,
        verification_requests=verification_requests,
        fresh_observations=fresh_observations,
        historical_observations=historical_observations,
        at=effective_at,
        current_window_seconds=current_window_seconds,
    )

    # Check whether all required predicates in mission were evaluated
    all_required_preds = [p for p in snapshot.desired_state if p.required]
    is_whole_mission = set(p.predicate_id for p in calendar_predicates) >= set(
        p.predicate_id for p in all_required_preds
    )
    is_partial = not is_whole_mission

    # 4. Lifecycle Transition
    if reconciliation.status in (ReconciliationStatus.STALE, ReconciliationStatus.INCOMPLETE):
        return MissionDriftEvaluationResult(
            mission_id=snapshot.mission_id,
            prior_state=snapshot.state,
            new_state=snapshot.state,
            is_drifted=False,
            reconciliation=reconciliation,
            transition_result=None,
            evaluated_at=now,
            is_inconclusive=True,
            error_message="Reconciliation inconclusive; cannot prove drift or renewed readiness",
            fresh_observations=fresh_observations,
            is_whole_mission=is_whole_mission,
            is_partial=is_partial,
            scope="google_calendar" if not is_whole_mission else "whole_mission",
        )

    transition_res = apply_reconciliation_transition(
        prior_state=snapshot.state,
        reconciliation=reconciliation,
    )

    effective_new_state = transition_res.new_state
    if not is_whole_mission and not transition_res.is_drifted:
        effective_new_state = snapshot.state

    return MissionDriftEvaluationResult(
        mission_id=snapshot.mission_id,
        prior_state=snapshot.state,
        new_state=effective_new_state,
        is_drifted=transition_res.is_drifted,
        reconciliation=reconciliation,
        transition_result=transition_res,
        evaluated_at=now,
        is_inconclusive=False,
        error_message=None,
        fresh_observations=fresh_observations,
        is_whole_mission=is_whole_mission,
        is_partial=is_partial,
        scope="google_calendar" if not is_whole_mission else "whole_mission",
    )


# ===========================================================================
# Tasks Drift Detection (Phase P-12.05)
# ===========================================================================


def detect_tasks_drift(
    *,
    snapshot: MissionSnapshot,
    tasks_adapter: GoogleTasksReadAdapter,
    target: TargetIdentity | None = None,
    historical_observations: Mapping[PredicateId, VerificationObservation] | None = None,
    eval_at: datetime | None = None,
    current_window_seconds: int = DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
) -> MissionDriftEvaluationResult:
    """Detect external-change drift on Google Tasks for a READY mission.

    Enforces:
    - Exact task list and task identity (never matches by title alone);
    - Detects completion reversal, title changes, due date changes, or deletion;
    - Legal lifecycle transition: transitions READY -> DRIFTED if and only if
      desired state is contradicted by fresh observations;
    - Fails closed on provider failure, missing task lists, or stale observations;
    - Strictly read-only: zero task creation, completion, or mutation.
    """
    assert_not_planner_for_drift(snapshot, parameter_name="snapshot")
    assert_not_planner_for_drift(tasks_adapter, parameter_name="tasks_adapter")

    if not isinstance(snapshot, MissionSnapshot):
        raise DriftTypeError("snapshot must be MissionSnapshot")
    if not isinstance(tasks_adapter, GoogleTasksReadAdapter):
        raise DriftTypeError("tasks_adapter must be GoogleTasksReadAdapter")

    now = eval_at or datetime.now(UTC)

    # 1. Lineage & State Enforcement
    if snapshot.state != MissionState.READY:
        raise ReconciliationLifecycleError(
            f"Drift detection is only permitted from READY state; mission is {snapshot.state.value}"
        )

    tasks_predicates = []
    for p in snapshot.desired_state:
        try:
            canonical_tgt = snapshot.get_target_for_predicate(p.predicate_id)
            if canonical_tgt.system != "google_tasks":
                continue
        except (SnapshotIntegrityError, AttributeError):
            pass

        _resolve_target_for_predicate(
            p,
            snapshot,
            explicit_target=target,
            expected_system="google_tasks",
            expected_kind=ResourceKind.TASK,
        )
        tasks_predicates.append(p)

    if not tasks_predicates:
        raise DriftValueError("Snapshot has zero tasks predicates to evaluate for drift")

    # 2. Port setup & Fresh Read-Back
    port = TasksVerificationPort(tasks_adapter)
    fresh_observations: dict[PredicateId, VerificationObservation] = {}
    verification_requests: dict[PredicateId, VerificationRequest] = {}

    for pred in tasks_predicates:
        bound_target = _resolve_target_for_predicate(
            pred,
            snapshot,
            explicit_target=target,
            expected_system="google_tasks",
            expected_kind=ResourceKind.TASK,
        )

        read_action = ActionContract.create(
            mission_id=snapshot.mission_id,
            action_type=ActionType.TASK_READ,
            target=bound_target,
            parameters={},
        )
        req = VerificationRequest(
            mission_id=snapshot.mission_id,
            action=read_action,
            target=bound_target,
            predicate=pred,
        )
        verification_requests[pred.predicate_id] = req

        try:
            obs = port.read(req)
            fresh_observations[pred.predicate_id] = obs
        except (VerifierReadError, Exception) as exc:
            # Transport / provider errors MUST NOT masquerade as confirmed drift!
            return MissionDriftEvaluationResult(
                mission_id=snapshot.mission_id,
                prior_state=snapshot.state,
                new_state=snapshot.state,
                is_drifted=False,
                reconciliation=None,
                transition_result=None,
                evaluated_at=now,
                is_inconclusive=True,
                error_message=f"Tasks provider read error: {redact_text(str(exc))}",
                fresh_observations={},
            )

    # 3. Deterministic Reconciliation
    effective_at = (
        eval_at
        if eval_at is not None
        else max(
            datetime.now(UTC),
            *(obs.observed_at for obs in fresh_observations.values()),
        )
    )
    reconciliation = reconcile_mission_state(
        mission_id=snapshot.mission_id,
        predicates=tasks_predicates,
        verification_requests=verification_requests,
        fresh_observations=fresh_observations,
        historical_observations=historical_observations,
        at=effective_at,
        current_window_seconds=current_window_seconds,
    )

    # Check whether all required predicates in mission were evaluated
    all_required_preds = [p for p in snapshot.desired_state if p.required]
    is_whole_mission = set(p.predicate_id for p in tasks_predicates) >= set(
        p.predicate_id for p in all_required_preds
    )
    is_partial = not is_whole_mission

    # 4. Lifecycle Transition
    if reconciliation.status in (ReconciliationStatus.STALE, ReconciliationStatus.INCOMPLETE):
        return MissionDriftEvaluationResult(
            mission_id=snapshot.mission_id,
            prior_state=snapshot.state,
            new_state=snapshot.state,
            is_drifted=False,
            reconciliation=reconciliation,
            transition_result=None,
            evaluated_at=now,
            is_inconclusive=True,
            error_message="Reconciliation inconclusive; cannot prove drift or renewed readiness",
            fresh_observations=fresh_observations,
            is_whole_mission=is_whole_mission,
            is_partial=is_partial,
            scope="google_tasks" if not is_whole_mission else "whole_mission",
        )

    transition_res = apply_reconciliation_transition(
        prior_state=snapshot.state,
        reconciliation=reconciliation,
    )

    effective_new_state = transition_res.new_state
    if not is_whole_mission and not transition_res.is_drifted:
        effective_new_state = snapshot.state

    return MissionDriftEvaluationResult(
        mission_id=snapshot.mission_id,
        prior_state=snapshot.state,
        new_state=effective_new_state,
        is_drifted=transition_res.is_drifted,
        reconciliation=reconciliation,
        transition_result=transition_res,
        evaluated_at=now,
        is_inconclusive=False,
        error_message=None,
        fresh_observations=fresh_observations,
        is_whole_mission=is_whole_mission,
        is_partial=is_partial,
        scope="google_tasks" if not is_whole_mission else "whole_mission",
    )


# ===========================================================================
# Snapshot Drift Update Helper
# ===========================================================================


def record_drift_in_snapshot(
    repository: DurableSnapshotRepository,
    snapshot: MissionSnapshot,
    drift_result: MissionDriftEvaluationResult,
) -> MissionSnapshot | None:
    """Record verified DRIFTED lifecycle state into a durable snapshot and ledger."""
    if not drift_result.is_drifted or drift_result.new_state != MissionState.DRIFTED:
        raise DriftValueError("Cannot record drift for a non-drifted result")

    if drift_result.mission_id != snapshot.mission_id:
        raise DriftValueError(
            f"Drift result mission {drift_result.mission_id} does not "
            f"match snapshot {snapshot.mission_id}"
        )
    if snapshot.snapshot_version not in SUPPORTED_SNAPSHOT_VERSIONS:
        raise DriftValueError(f"Unsupported snapshot version: {snapshot.snapshot_version!r}")
    if not drift_result.fresh_observations:
        raise DriftValueError("Cannot record drift without fresh observations")
    if drift_result.is_inconclusive:
        raise DriftValueError("Cannot record drift on inconclusive drift result")

    # 1. Verify source snapshot is current (not stale/replaced)
    try:
        current_stored = repository.load_snapshot(snapshot.mission_id)
    except Exception as exc:
        raise DriftValueError(
            f"Cannot record drift without successfully loaded authoritative predecessor: {exc}"
        ) from exc

    if current_stored.snapshot_id != snapshot.snapshot_id:
        raise DriftValueError(
            f"Source snapshot {snapshot.snapshot_id} is stale; "
            f"current stored snapshot is {current_stored.snapshot_id}"
        )
    if current_stored.created_at != snapshot.created_at:
        raise DriftValueError(
            f"Source snapshot {snapshot.snapshot_id} timestamp "
            f"({snapshot.created_at.isoformat()}) does not match current stored snapshot "
            f"({current_stored.created_at.isoformat()})"
        )

    # 2. Mission must be in READY state
    if current_stored.state != MissionState.READY or snapshot.state != MissionState.READY:
        raise ReconciliationLifecycleError(
            f"Cannot record drift for mission in state {snapshot.state.value}; must be READY"
        )

    # 3. Fresh observations must actually prove drift against canonical targets
    for pred in snapshot.desired_state:
        if pred.predicate_id in drift_result.fresh_observations:
            obs = drift_result.fresh_observations[pred.predicate_id]
            pred_target = snapshot.get_target_for_predicate(pred.predicate_id)
            if obs.target != pred_target:
                raise DriftTargetMismatchError(
                    f"Observation target {obs.target} does not match canonical binding "
                    f"{pred_target} for predicate {pred.predicate_id}"
                )

    recomp_requests: dict[PredicateId, VerificationRequest] = {}
    for pred in snapshot.desired_state:
        if pred.predicate_id in drift_result.fresh_observations:
            p_target = snapshot.get_target_for_predicate(pred.predicate_id)
            act_type = (
                ActionType.CALENDAR_READ
                if p_target.system == "google_calendar"
                else ActionType.TASK_READ
            )
            read_act = ActionContract.create(
                mission_id=snapshot.mission_id,
                action_type=act_type,
                target=p_target,
                parameters={},
            )
            recomp_requests[pred.predicate_id] = VerificationRequest(
                mission_id=snapshot.mission_id,
                action=read_act,
                target=p_target,
                predicate=pred,
            )

    effective_at = max(
        drift_result.evaluated_at,
        *(obs.observed_at for obs in drift_result.fresh_observations.values()),
    )
    reconciled = reconcile_mission_state(
        mission_id=snapshot.mission_id,
        predicates=[
            p for p in snapshot.desired_state if p.predicate_id in drift_result.fresh_observations
        ],
        verification_requests=recomp_requests,
        fresh_observations=drift_result.fresh_observations,
        at=effective_at,
    )
    reconciled_trans = apply_reconciliation_transition(
        prior_state=MissionState.READY,
        reconciliation=reconciled,
    )
    if not reconciled_trans.is_drifted or reconciled_trans.new_state != MissionState.DRIFTED:
        raise DriftValueError(
            "Forged drift rejected: canonically recomputed reconciliation "
            "does not confirm DRIFTED transition"
        )

    has_proven_contradiction = False
    drifted_predicate_id: PredicateId | None = None
    for pred in snapshot.desired_state:
        if pred.predicate_id in drift_result.fresh_observations:
            obs = drift_result.fresh_observations[pred.predicate_id]
            pred_target = snapshot.get_target_for_predicate(pred.predicate_id)
            eval_res = evaluate_predicate(
                pred, obs, expected_target=pred_target, at=drift_result.evaluated_at
            )
            if eval_res.truth == PredicateTruth.FALSE:
                has_proven_contradiction = True
                drifted_predicate_id = pred.predicate_id
                break

    if not has_proven_contradiction or drifted_predicate_id is None:
        raise DriftValueError(
            "Forged drift rejected: fresh observations do not prove "
            "any contradicted desired state predicate"
        )

    # 4. Bind drift evidence to the exact canonical action associated with the drifted predicate
    drifted_target = snapshot.get_target_for_predicate(drifted_predicate_id)
    matching_actions = [a for a in snapshot.actions if a.target == drifted_target]
    if not matching_actions:
        raise DriftValueError(
            f"No canonical action found matching drifted predicate {drifted_predicate_id} "
            f"and target {drifted_target}"
        )
    bound_action_id = matching_actions[0].action_id

    drift_evidence_ids = list(snapshot.evidence_ids)

    # 5. Atomicity: Durable state transition in ledger, then save snapshot
    if repository.ledger is not None:
        origin = EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=drift_result.evaluated_at,
        )
        explanation_val = (
            drift_result.transition_result.explanation
            if drift_result.transition_result is not None
            else None
        )
        drift_evidence = EvidenceRecord.create(
            action_id=bound_action_id,
            mission_id=snapshot.mission_id,
            origin=origin,
            payload={
                "evidence_type": "MISSION_DRIFT",
                "mission_id": str(snapshot.mission_id),
                "prior_state": MissionState.READY.value,
                "new_state": MissionState.DRIFTED.value,
                "is_drifted": True,
                "drifted_predicate_id": str(drifted_predicate_id),
                "evaluated_at": drift_result.evaluated_at.isoformat(),
                "explanation": explanation_val,
            },
            created_at=drift_result.evaluated_at,
        )
        drift_evidence_ids.append(drift_evidence.evidence_id)

        drifted_snapshot = create_mission_snapshot(
            mission_id=snapshot.mission_id,
            state=MissionState.DRIFTED,
            contract=snapshot.contract,
            desired_state=snapshot.desired_state,
            actions=snapshot.actions,
            action_dependencies=snapshot.action_dependencies,
            step_records=snapshot.step_records,
            pending_approvals=snapshot.pending_approvals,
            consumed_approvals=snapshot.consumed_approvals,
            execution_attempts=snapshot.execution_attempts,
            evidence_ids=tuple(drift_evidence_ids),
            predicate_bindings=snapshot.predicate_bindings,
            created_at=drift_result.evaluated_at,
        )

        repository.ledger.record_state_transition(
            mission_id=snapshot.mission_id,
            expected_prior_state=MissionState.READY,
            new_state=MissionState.DRIFTED,
            evidence=drift_evidence,
            updated_at=drift_result.evaluated_at,
            snapshot_projection=drifted_snapshot.to_dict(),
        )
    else:
        drifted_snapshot = create_mission_snapshot(
            mission_id=snapshot.mission_id,
            state=MissionState.DRIFTED,
            contract=snapshot.contract,
            desired_state=snapshot.desired_state,
            actions=snapshot.actions,
            action_dependencies=snapshot.action_dependencies,
            step_records=snapshot.step_records,
            pending_approvals=snapshot.pending_approvals,
            consumed_approvals=snapshot.consumed_approvals,
            execution_attempts=snapshot.execution_attempts,
            evidence_ids=tuple(drift_evidence_ids),
            predicate_bindings=snapshot.predicate_bindings,
            created_at=drift_result.evaluated_at,
        )

    repository.save_snapshot(drifted_snapshot)
    return drifted_snapshot
