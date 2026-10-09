"""Deterministic bounded revalidation command and engine for StillDone.

Phase P-12.03:
Implements deterministic, read-only revalidation of canonical desired-state
predicates against fresh external observations.

Core Architectural Laws:
- Reads the exact previously bound external targets.
- Re-evaluates freshness and predicate truth from new independent observations.
- Applies bounded per-call work ceiling (max_reads_per_call).
- Deterministic outcome classification:
  * TRUE: Predicate evaluates to true on fresh external state;
  * FALSE: Predicate evaluates to false on fresh external state;
  * STALE: Observation failed freshness window (expired observation);
  * NOT_EVALUABLE: Target or property absent/incompatible (not found / unparseable);
  * PROVIDER_ERROR: Transport/API error during read-back;
  * NOT_RUN: Predicate evaluation was skipped due to per-call budget limit.
- Model text or historic receipts cannot substitute for fresh observations.
- Revalidation is strictly read-only: zero provider writes, zero approvals consumed.
- Zero OAuth expansion or unprotected MCP exposure.
"""

from __future__ import annotations

import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.adapters.calendar import GoogleCalendarReadAdapter
from stilldone.adapters.tasks import GoogleTasksReadAdapter
from stilldone.domain.action import ActionContract, ActionType, ResourceKind, TargetIdentity
from stilldone.domain.desired_state import DesiredStatePredicate, PredicateId
from stilldone.domain.mission import MissionId
from stilldone.verifier.contracts import (
    VerificationObservation,
    VerificationRequest,
    VerifierReadError,
)
from stilldone.verifier.dispatch import (
    CalendarVerificationPort,
    TasksVerificationPort,
    VerifierDispatcher,
)
from stilldone.verifier.freshness import (
    DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
    FreshnessResult,
    FreshnessStatus,
    evaluate_observation_freshness,
)
from stilldone.verifier.predicates import (
    PredicateEvaluationResult,
    PredicateTruth,
    _extract_observed_value,
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
# Revalidation Vocabulary & Outcome Types
# ===========================================================================


class RevalidationPredicateStatus(StrEnum):
    """Deterministic closed vocabulary for individual predicate revalidation outcome."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    STALE = "STALE"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    NOT_RUN = "NOT_RUN"


# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class RevalidationError(Exception):
    """Base exception for all StillDone revalidation failures."""


class RevalidationTypeError(RevalidationError, TypeError):
    """Raised when an argument has an invalid type."""


class RevalidationValueError(RevalidationError, ValueError):
    """Raised when an argument has an invalid value."""


class HistoricalReceiptSubstitutionError(RevalidationError, ValueError):
    """Raised when historical receipt or prose is substituted for fresh observation."""


class PlannerRevalidationAuthorityError(RevalidationError, TypeError):
    """Raised when a planner/model proposal is passed as authority for revalidation."""


def assert_not_planner_for_revalidation(obj: Any, *, parameter_name: str = "argument") -> None:
    """Reject planner/model proposals fail-closed."""
    for pt in _PLANNER_TYPES:
        if isinstance(obj, pt):
            raise PlannerRevalidationAuthorityError(
                f"Model/planner proposal {type(obj).__name__} has ZERO authority "
                f"in revalidation ({parameter_name})"
            )


# ===========================================================================
# Revalidation Aggregate Contracts
# ===========================================================================


@dataclass(frozen=True)
class PredicateRevalidationOutcome:
    """Immutable outcome of revalidating a single desired-state predicate."""

    predicate_id: PredicateId
    status: RevalidationPredicateStatus
    target: TargetIdentity
    subject: str
    expected_value: Any
    observed_value: Any | None = None
    freshness_status: FreshnessStatus | None = None
    error_message: str | None = None
    observed_at: datetime | None = None
    observation: VerificationObservation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.predicate_id, PredicateId):
            raise RevalidationTypeError("predicate_id must be PredicateId")
        if not isinstance(self.status, RevalidationPredicateStatus):
            raise RevalidationTypeError("status must be RevalidationPredicateStatus")
        if not isinstance(self.target, TargetIdentity):
            raise RevalidationTypeError("target must be TargetIdentity")
        if not isinstance(self.subject, str):
            raise RevalidationTypeError("subject must be a string")


@dataclass(frozen=True)
class MissionRevalidationResult:
    """Immutable summary of a bounded mission revalidation operation."""

    mission_id: MissionId
    evaluated_at: datetime
    predicates_count: int
    evaluated_count: int
    outcomes: Mapping[PredicateId, PredicateRevalidationOutcome]
    all_true: bool
    has_false: bool
    has_stale: bool
    has_provider_error: bool
    has_not_run: bool
    is_partial: bool
    reads_performed: int
    writes_performed: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise RevalidationTypeError("mission_id must be MissionId")
        if not isinstance(self.evaluated_at, datetime):
            raise RevalidationTypeError("evaluated_at must be datetime")
        if self.writes_performed != 0:
            raise RevalidationValueError("Revalidation is read-only; writes_performed must be 0")

        # Freeze mapping view
        if isinstance(self.outcomes, dict):
            object.__setattr__(self, "outcomes", types.MappingProxyType(dict(self.outcomes)))

    @property
    def is_still_true(self) -> bool:
        """True if and only if all predicates were evaluated and are TRUE with zero failures."""
        return self.all_true and not self.is_partial and not self.has_provider_error


# ===========================================================================
# Standard Target Reader Dispatch
# ===========================================================================


class StandardTargetReader:
    """Read-only dispatch reader for Google Calendar, Google Tasks, and other targets."""

    def __init__(
        self,
        *,
        calendar_read_adapter: GoogleCalendarReadAdapter | None = None,
        tasks_read_adapter: GoogleTasksReadAdapter | None = None,
        dispatcher: VerifierDispatcher | None = None,
    ) -> None:
        self._calendar_adapter = calendar_read_adapter
        self._tasks_adapter = tasks_read_adapter
        self._dispatcher = dispatcher
        self._calendar_port = (
            CalendarVerificationPort(calendar_read_adapter)
            if calendar_read_adapter is not None
            else None
        )
        self._tasks_port = (
            TasksVerificationPort(tasks_read_adapter) if tasks_read_adapter is not None else None
        )

    def read_target(
        self,
        target: TargetIdentity,
        subject: str,
        *,
        mission_id: MissionId | None = None,
        at: datetime | None = None,
    ) -> VerificationObservation:
        """Read fresh state for target, returning VerificationObservation or raising error."""
        effective_mid = mission_id or MissionId.generate()

        if (
            target.system == "google_calendar"
            and target.resource_kind == ResourceKind.CALENDAR_EVENT
        ):
            if self._dispatcher is not None and self._dispatcher.has_route(
                target.system, target.resource_kind
            ):
                req = VerificationRequest(
                    mission_id=effective_mid,
                    action=ActionContract.create(
                        mission_id=effective_mid,
                        action_type=ActionType.CALENDAR_READ,
                        target=target,
                        parameters={},
                    ),
                    target=target,
                )
                return self._dispatcher.dispatch(req)
            if self._calendar_port is None:
                raise RevalidationValueError("No calendar read port configured for calendar target")
            req = VerificationRequest(
                mission_id=effective_mid,
                action=ActionContract.create(
                    mission_id=effective_mid,
                    action_type=ActionType.CALENDAR_READ,
                    target=target,
                    parameters={},
                ),
                target=target,
            )
            return self._calendar_port.read(req)

        elif target.system == "google_tasks" and target.resource_kind == ResourceKind.TASK:
            if self._dispatcher is not None and self._dispatcher.has_route(
                target.system, target.resource_kind
            ):
                req = VerificationRequest(
                    mission_id=effective_mid,
                    action=ActionContract.create(
                        mission_id=effective_mid,
                        action_type=ActionType.TASK_READ,
                        target=target,
                        parameters={},
                    ),
                    target=target,
                )
                return self._dispatcher.dispatch(req)
            if self._tasks_port is None:
                raise RevalidationValueError("No tasks read port configured for tasks target")
            req = VerificationRequest(
                mission_id=effective_mid,
                action=ActionContract.create(
                    mission_id=effective_mid,
                    action_type=ActionType.TASK_READ,
                    target=target,
                    parameters={},
                ),
                target=target,
            )
            return self._tasks_port.read(req)

        raise RevalidationValueError(
            f"Unsupported target system/kind: {target.system}/{target.resource_kind}"
        )


# ===========================================================================
# Deterministic Bounded Revalidation Engine
# ===========================================================================


def revalidate_mission(
    *,
    mission_id: MissionId,
    predicates: Sequence[DesiredStatePredicate],
    target_map: Mapping[PredicateId, TargetIdentity],
    target_reader: (
        Callable[[TargetIdentity, str], VerificationObservation] | StandardTargetReader
    ),
    at: datetime | None = None,
    max_reads_per_call: int = 10,
    historical_observations: Mapping[PredicateId, VerificationObservation] | None = None,
    current_window_seconds: int = DEFAULT_CURRENT_FRESHNESS_WINDOW_SECONDS,
) -> MissionRevalidationResult:
    """Execute bounded read-only revalidation against fresh external state.

    Enforces:
    - Bounded work budget: limits reads to max_reads_per_call;
    - Zero mutation: no provider writes, no approval consumption;
    - Clear distinction between TRUE, FALSE, STALE, NOT_EVALUABLE, PROVIDER_ERROR, NOT_RUN;
    - Rejection of historical replays and model prose.
    """
    assert_not_planner_for_revalidation(mission_id, parameter_name="mission_id")
    assert_not_planner_for_revalidation(predicates, parameter_name="predicates")
    assert_not_planner_for_revalidation(target_map, parameter_name="target_map")

    if not isinstance(mission_id, MissionId):
        raise RevalidationTypeError("mission_id must be MissionId")
    if not isinstance(predicates, Sequence):
        raise RevalidationTypeError("predicates must be a Sequence")
    if not isinstance(target_map, Mapping):
        raise RevalidationTypeError("target_map must be a Mapping")
    if max_reads_per_call < 1:
        raise RevalidationValueError("max_reads_per_call must be >= 1")

    eval_at = at or datetime.now(UTC)
    if eval_at.tzinfo is None:
        raise RevalidationValueError("Evaluation timestamp 'at' must be timezone-aware")
    eval_at = eval_at.astimezone(UTC)

    def execute_read(tgt: TargetIdentity, subj: str) -> VerificationObservation:
        if isinstance(target_reader, StandardTargetReader):
            return target_reader.read_target(tgt, subj, mission_id=mission_id, at=eval_at)
        return target_reader(tgt, subj)

    outcomes: dict[PredicateId, PredicateRevalidationOutcome] = {}
    reads_done: int = 0

    for i, pred in enumerate(predicates):
        if not isinstance(pred, DesiredStatePredicate):
            raise RevalidationTypeError(f"predicates[{i}] must be DesiredStatePredicate")
        if pred.mission_id != mission_id:
            raise RevalidationValueError(
                f"Predicate {pred.predicate_id} mission {pred.mission_id} does not match "
                f"{mission_id}"
            )

        if pred.predicate_id not in target_map:
            raise RevalidationValueError(
                f"Missing target mapping for predicate {pred.predicate_id}"
            )
        target = target_map[pred.predicate_id]
        if not isinstance(target, TargetIdentity):
            raise RevalidationTypeError("target_map values must be TargetIdentity")

        # Work budget check
        if reads_done >= max_reads_per_call:
            outcomes[pred.predicate_id] = PredicateRevalidationOutcome(
                predicate_id=pred.predicate_id,
                status=RevalidationPredicateStatus.NOT_RUN,
                target=target,
                subject=pred.subject,
                expected_value=pred.expected_value,
                error_message="Per-call work budget exceeded",
            )
            continue

        # Execute read
        reads_done += 1
        obs: VerificationObservation | None = None
        provider_error_msg: str | None = None

        try:
            obs = execute_read(target, pred.subject)
            if not isinstance(obs, VerificationObservation):
                raise RevalidationTypeError(
                    f"Reader returned {type(obs).__name__}, expected VerificationObservation"
                )
        except (VerifierReadError, Exception) as exc:
            provider_error_msg = str(exc)

        if provider_error_msg is not None or obs is None:
            outcomes[pred.predicate_id] = PredicateRevalidationOutcome(
                predicate_id=pred.predicate_id,
                status=RevalidationPredicateStatus.PROVIDER_ERROR,
                target=target,
                subject=pred.subject,
                expected_value=pred.expected_value,
                error_message=provider_error_msg or "Provider read failed",
            )
            continue

        # Validate against historical replay
        if historical_observations is not None and pred.predicate_id in historical_observations:
            hist_obs = historical_observations[pred.predicate_id]
            if obs is hist_obs:
                raise HistoricalReceiptSubstitutionError(
                    f"Historical observation object reused for predicate {pred.predicate_id}"
                )
            if obs.observed_at <= hist_obs.observed_at:
                raise HistoricalReceiptSubstitutionError(
                    f"Observation timestamp for predicate {pred.predicate_id} "
                    f"({obs.observed_at.isoformat()}) did not advance beyond "
                    f"historical ({hist_obs.observed_at.isoformat()})"
                )

        # Freshness evaluation
        obs_eval_at = eval_at if at is not None else max(datetime.now(UTC), obs.observed_at)
        freshness_res: FreshnessResult = evaluate_observation_freshness(
            obs,
            pred.freshness,
            at=obs_eval_at,
            current_window_seconds=current_window_seconds,
        )

        # Predicate evaluation
        pred_res: PredicateEvaluationResult = evaluate_predicate(
            pred, obs, expected_target=target, at=obs_eval_at
        )

        found_val, extracted_val = _extract_observed_value(obs, pred.subject)
        observed_val = extracted_val if found_val else None

        if freshness_res.status != FreshnessStatus.FRESH:
            outcomes[pred.predicate_id] = PredicateRevalidationOutcome(
                predicate_id=pred.predicate_id,
                status=RevalidationPredicateStatus.STALE,
                target=target,
                subject=pred.subject,
                expected_value=pred.expected_value,
                observed_value=observed_val,
                freshness_status=freshness_res.status,
                error_message=freshness_res.reason,
                observed_at=obs.observed_at,
                observation=obs,
            )
            continue

        if pred_res.truth == PredicateTruth.TRUE:
            pred_status = RevalidationPredicateStatus.TRUE
        elif pred_res.truth == PredicateTruth.FALSE:
            pred_status = RevalidationPredicateStatus.FALSE
        else:
            pred_status = RevalidationPredicateStatus.NOT_EVALUABLE

        outcomes[pred.predicate_id] = PredicateRevalidationOutcome(
            predicate_id=pred.predicate_id,
            status=pred_status,
            target=target,
            subject=pred.subject,
            expected_value=pred.expected_value,
            observed_value=observed_val,
            freshness_status=freshness_res.status,
            error_message=(
                pred_res.reason if pred_status != RevalidationPredicateStatus.TRUE else None
            ),
            observed_at=obs.observed_at,
            observation=obs,
        )

    # Compute overall aggregates
    all_true = len(outcomes) == len(predicates) and all(
        o.status == RevalidationPredicateStatus.TRUE for o in outcomes.values()
    )
    has_false = any(o.status == RevalidationPredicateStatus.FALSE for o in outcomes.values())
    has_stale = any(o.status == RevalidationPredicateStatus.STALE for o in outcomes.values())
    has_provider_error = any(
        o.status == RevalidationPredicateStatus.PROVIDER_ERROR for o in outcomes.values()
    )
    has_not_run = any(o.status == RevalidationPredicateStatus.NOT_RUN for o in outcomes.values())

    return MissionRevalidationResult(
        mission_id=mission_id,
        evaluated_at=eval_at,
        predicates_count=len(predicates),
        evaluated_count=reads_done,
        outcomes=outcomes,
        all_true=all_true,
        has_false=has_false,
        has_stale=has_stale,
        has_provider_error=has_provider_error,
        has_not_run=has_not_run,
        is_partial=has_not_run,
        reads_performed=reads_done,
        writes_performed=0,
    )
