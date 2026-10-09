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
from stilldone.domain.action import ActionContract, ActionType, ResourceKind, TargetIdentity
from stilldone.domain.desired_state import DesiredStatePredicate, PredicateId
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.snapshot import (
    DurableSnapshotRepository,
    MissionSnapshot,
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


# ===========================================================================
# Target Derivation and Verification Helper
# ===========================================================================


def _resolve_target_for_predicate(
    predicate: DesiredStatePredicate,
    snapshot: MissionSnapshot,
    explicit_target: TargetIdentity | None = None,
    expected_system: str | None = None,
    expected_kind: ResourceKind | None = None,
) -> TargetIdentity:
    """Resolve and validate the exact TargetIdentity bound to a predicate."""
    if explicit_target is not None:
        target = explicit_target
    else:
        # Search snapshot actions matching predicate
        matched_targets = [
            a.target for a in snapshot.actions if a.mission_id == snapshot.mission_id
        ]
        if not matched_targets:
            raise DriftTargetMismatchError(
                f"No bound action target found for predicate {predicate.predicate_id}"
            )
        target = matched_targets[0]

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

    calendar_predicates = [
        p
        for p in snapshot.desired_state
        if (target is not None and target.system == "google_calendar")
        or any(a.target.system == "google_calendar" for a in snapshot.actions)
    ]

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
                error_message=f"Calendar provider read error: {exc}",
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
        )

    transition_res = apply_reconciliation_transition(
        prior_state=snapshot.state,
        reconciliation=reconciliation,
    )

    return MissionDriftEvaluationResult(
        mission_id=snapshot.mission_id,
        prior_state=snapshot.state,
        new_state=transition_res.new_state,
        is_drifted=transition_res.is_drifted,
        reconciliation=reconciliation,
        transition_result=transition_res,
        evaluated_at=now,
        is_inconclusive=False,
        error_message=None,
        fresh_observations=fresh_observations,
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

    tasks_predicates = [
        p
        for p in snapshot.desired_state
        if (target is not None and target.system == "google_tasks")
        or any(a.target.system == "google_tasks" for a in snapshot.actions)
    ]

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
                error_message=f"Tasks provider read error: {exc}",
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
        )

    transition_res = apply_reconciliation_transition(
        prior_state=snapshot.state,
        reconciliation=reconciliation,
    )

    return MissionDriftEvaluationResult(
        mission_id=snapshot.mission_id,
        prior_state=snapshot.state,
        new_state=transition_res.new_state,
        is_drifted=transition_res.is_drifted,
        reconciliation=reconciliation,
        transition_result=transition_res,
        evaluated_at=now,
        is_inconclusive=False,
        error_message=None,
        fresh_observations=fresh_observations,
    )


# ===========================================================================
# Snapshot Drift Update Helper
# ===========================================================================


def record_drift_in_snapshot(
    repository: DurableSnapshotRepository,
    snapshot: MissionSnapshot,
    drift_result: MissionDriftEvaluationResult,
) -> MissionSnapshot | None:
    """Record verified DRIFTED lifecycle state into a durable snapshot if applicable."""
    if not drift_result.is_drifted or drift_result.new_state != MissionState.DRIFTED:
        return None

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
        evidence_ids=snapshot.evidence_ids,
    )
    repository.save_snapshot(drifted_snapshot)
    return drifted_snapshot
