"""Tests for deterministic mission readiness computation (Phase P-09.04).

Enforces StillDone core architectural laws:
- Mission READY must be computed from deterministic verification facts.
- READY requires all required desired-state predicates TRUE and observations FRESH.
- Execution success alone is INSUFFICIENT.
- Provider success alone is INSUFFICIENT.
- Model / planner output has ZERO verification authority.
- No model prose may directly create VERIFIED or READY.
- Deterministic same inputs produce identical readiness determination.
- Zero network calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.attempts import create_execution_attempt
from stilldone.execution.contracts import MissionExecutionContract
from stilldone.execution.scheduler import schedule_execution
from stilldone.execution.state import (
    ExecutionStateTracker,
    ProviderExecutionResult,
)
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    PlannerInput,
    SymbolicTargetRef,
)
from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    VerificationObservation,
    VerificationRequest,
)
from stilldone.verifier.freshness import (
    FreshnessResult,
    FreshnessStatus,
    NaiveDatetimeError,
)
from stilldone.verifier.predicates import (
    PredicateEvaluationResult,
    PredicateTruth,
)
from stilldone.verifier.readiness import (
    PlannerReadinessAuthorityError,
    ReadinessContractTypeError,
    ReadinessContractValueError,
    assert_not_planner_or_execution_payload,
    compute_mission_readiness,
)

# ===========================================================================
# Test Fixtures & Helpers
# ===========================================================================

T0 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
T_OBS = datetime(2026, 10, 5, 12, 1, 0, tzinfo=UTC)
T_EVAL = datetime(2026, 10, 5, 12, 2, 0, tzinfo=UTC)
T_STALE_EVAL = datetime(2026, 10, 5, 12, 10, 0, tzinfo=UTC)

CAL_TARGET = TargetIdentity(
    system="google_calendar",
    resource_kind=ResourceKind.CALENDAR_EVENT,
    resource_id="event_123",
    parent_id="primary",
)

TASKS_TARGET = TargetIdentity(
    system="google_tasks",
    resource_kind=ResourceKind.TASK_LIST,
    resource_id="default",
    parent_id=None,
)

TASKS_OBS_TARGET = TargetIdentity(
    system="google_tasks",
    resource_kind=ResourceKind.TASK,
    resource_id="task_456",
    parent_id="default",
)


def _make_calendar_predicate(
    mission_id: MissionId,
    expected_status: str = "confirmed",
    max_age_seconds: int = 300,
    required: bool = True,
) -> DesiredStatePredicate:
    return DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value=expected_status,
        required=required,
        freshness=FreshnessContract.max_age(max_age_seconds),
    )


def _make_tasks_predicate(
    mission_id: MissionId,
    expected_status: str = "needsAction",
    max_age_seconds: int = 300,
    required: bool = True,
) -> DesiredStatePredicate:
    return DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value=expected_status,
        required=required,
        freshness=FreshnessContract.max_age(max_age_seconds),
    )


def _make_calendar_observation(
    cal_target: TargetIdentity = CAL_TARGET,
    status: str = "confirmed",
    observed_at: datetime = T_OBS,
) -> VerificationObservation:
    return VerificationObservation(
        target=cal_target,
        observed_at=observed_at,
        exists=True,
        properties={"status": status, "summary": "School dropoff"},
        provenance=EvidenceProvenance.FIXTURE,
    )


def _make_tasks_observation(
    tasks_target: TargetIdentity = TASKS_OBS_TARGET,
    status: str = "needsAction",
    observed_at: datetime = T_OBS,
) -> VerificationObservation:
    return VerificationObservation(
        target=tasks_target,
        observed_at=observed_at,
        exists=True,
        properties={"status": status, "title": "Pack backpacks"},
        provenance=EvidenceProvenance.FIXTURE,
    )


def _make_calendar_request(
    mission_id: MissionId,
    predicate: DesiredStatePredicate,
    target: TargetIdentity = CAL_TARGET,
) -> VerificationRequest:
    action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target,
        parameters={},
    )
    return VerificationRequest(
        mission_id=mission_id,
        action=action,
        target=target,
        predicate=predicate,
    )


def _make_tasks_request(
    mission_id: MissionId,
    predicate: DesiredStatePredicate,
    target: TargetIdentity = TASKS_OBS_TARGET,
) -> VerificationRequest:
    action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=target,
        parameters={},
    )
    return VerificationRequest(
        mission_id=mission_id,
        action=action,
        target=target,
        predicate=predicate,
    )


def _make_execution_record(
    mission_id: MissionId,
    actions_with_success: list[tuple[ActionContract, bool]],
) -> Any:
    """Helper to build a realistic MissionExecutionRecord."""
    action_contracts = tuple(a for a, _ in actions_with_success)
    contract = MissionExecutionContract(
        mission_id=mission_id,
        actions=action_contracts,
        dependencies={a.action_id: frozenset() for a in action_contracts},
    )
    schedule = schedule_execution(contract)
    tracker = ExecutionStateTracker(contract, schedule)

    for action, succeeds in actions_with_success:
        aid = action.action_id
        can_run, _ = tracker.can_execute(aid)
        if can_run:
            tracker.mark_in_progress(aid)
            attempt = create_execution_attempt(aid, started_at=T0)
            if succeeds:
                pres = ProviderExecutionResult(
                    action_type=action.action_type,
                    success=True,
                    status_name="SUCCESS",
                )
                tracker.record_success(aid, attempt=attempt, provider_result=pres)
            else:
                pres = ProviderExecutionResult(
                    action_type=action.action_type,
                    success=False,
                    status_name="FAILED",
                    error_message="Simulated provider failure",
                )
                tracker.record_failure(
                    aid,
                    attempt=attempt,
                    provider_result=pres,
                    error_message="Simulated provider failure",
                )

    return tracker.snapshot()


# ===========================================================================
# Required Test 1: All Predicates TRUE + Fresh -> Readiness Eligible
# ===========================================================================


class TestReadinessEligible:
    """Requirement 1: all predicates TRUE + fresh -> readiness eligible."""

    def test_all_predicates_true_and_fresh_yields_ready(self) -> None:
        mission_id = MissionId.generate()

        pred1 = _make_calendar_predicate(mission_id, expected_status="confirmed")
        pred2 = _make_tasks_predicate(mission_id, expected_status="needsAction")

        obs1 = _make_calendar_observation(status="confirmed", observed_at=T_OBS)
        obs2 = _make_tasks_observation(status="needsAction", observed_at=T_OBS)

        req1 = _make_calendar_request(mission_id, pred1)
        req2 = _make_tasks_request(mission_id, pred2)

        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred1, pred2],
            verification_requests={
                pred1.predicate_id: req1,
                pred2.predicate_id: req2,
            },
            observations={
                pred1.predicate_id: obs1,
                pred2.predicate_id: obs2,
            },
            current_state=MissionState.VERIFYING,
            at=T_EVAL,
        )

        assert det.is_ready is True
        assert det.state == MissionState.READY
        assert det.satisfied_predicate_ids == (pred1.predicate_id, pred2.predicate_id)
        assert det.failed_predicate_ids == ()
        assert det.stale_predicate_ids == ()
        assert det.missing_predicate_ids == ()
        assert det.unverified_action_ids == ()
        assert len(det.predicate_evaluations) == 2
        assert len(det.freshness_evaluations) == 2

    def test_with_execution_record_where_all_succeeded(self) -> None:
        mission_id = MissionId.generate()
        aid1 = ActionId.generate()
        aid2 = ActionId.generate()

        a1 = ActionContract.create(
            action_id=aid1,
            mission_id=mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=CAL_TARGET,
            parameters={"summary": "School dropoff"},
        )
        a2 = ActionContract.create(
            action_id=aid2,
            mission_id=mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Pack backpacks"},
        )

        exec_rec = _make_execution_record(mission_id, [(a1, True), (a2, True)])

        pred1 = _make_calendar_predicate(mission_id, expected_status="confirmed")
        pred2 = _make_tasks_predicate(mission_id, expected_status="needsAction")

        obs1 = _make_calendar_observation(status="confirmed", observed_at=T_OBS)
        obs2 = _make_tasks_observation(status="needsAction", observed_at=T_OBS)

        req1 = _make_calendar_request(mission_id, pred1)
        req2 = _make_tasks_request(mission_id, pred2)

        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred1, pred2],
            verification_requests={
                pred1.predicate_id: req1,
                pred2.predicate_id: req2,
            },
            observations={
                pred1.predicate_id: obs1,
                pred2.predicate_id: obs2,
            },
            execution_record=exec_rec,
            current_state=MissionState.VERIFYING,
            at=T_EVAL,
        )

        assert det.is_ready is True
        assert det.state == MissionState.READY
        assert det.unverified_action_ids == ()


# ===========================================================================
# Required Test 2: One FALSE -> Not READY
# ===========================================================================


class TestReadinessPredicateFalse:
    """Requirement 2: one FALSE -> not READY."""

    def test_one_predicate_false_prevents_ready(self) -> None:
        mission_id = MissionId.generate()

        pred1 = _make_calendar_predicate(mission_id, expected_status="confirmed")
        pred2 = _make_tasks_predicate(mission_id, expected_status="needsAction")

        # obs1 matches, but obs2 has different status: "completed" != "needsAction"
        obs1 = _make_calendar_observation(status="confirmed", observed_at=T_OBS)
        obs2 = _make_tasks_observation(status="completed", observed_at=T_OBS)

        req1 = _make_calendar_request(mission_id, pred1)
        req2 = _make_tasks_request(mission_id, pred2)

        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred1, pred2],
            verification_requests={
                pred1.predicate_id: req1,
                pred2.predicate_id: req2,
            },
            observations={
                pred1.predicate_id: obs1,
                pred2.predicate_id: obs2,
            },
            current_state=MissionState.VERIFYING,
            at=T_EVAL,
        )

        assert det.is_ready is False
        assert det.state != MissionState.READY
        assert det.failed_predicate_ids == (pred2.predicate_id,)
        assert det.satisfied_predicate_ids == (pred1.predicate_id,)
        assert any("evaluated FALSE" in r for r in det.reasons)


# ===========================================================================
# Required Test 3: One STALE -> Not READY
# ===========================================================================


class TestReadinessStaleObservation:
    """Requirement 3: one STALE -> not READY."""

    def test_stale_observation_prevents_ready(self) -> None:
        mission_id = MissionId.generate()

        # max_age_seconds is 300 (5 minutes)
        pred1 = _make_calendar_predicate(
            mission_id, expected_status="confirmed", max_age_seconds=300
        )
        pred2 = _make_tasks_predicate(
            mission_id, expected_status="needsAction", max_age_seconds=300
        )

        # Observed at T_OBS (12:01:00), but evaluation is at T_STALE_EVAL (12:10:00, 9 min later)
        obs1 = _make_calendar_observation(status="confirmed", observed_at=T_OBS)
        obs2 = _make_tasks_observation(status="needsAction", observed_at=T_OBS)

        req1 = _make_calendar_request(mission_id, pred1)
        req2 = _make_tasks_request(mission_id, pred2)

        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred1, pred2],
            verification_requests={
                pred1.predicate_id: req1,
                pred2.predicate_id: req2,
            },
            observations={
                pred1.predicate_id: obs1,
                pred2.predicate_id: obs2,
            },
            current_state=MissionState.VERIFYING,
            at=T_STALE_EVAL,
        )

        assert det.is_ready is False
        assert det.state != MissionState.READY
        assert pred1.predicate_id in det.stale_predicate_ids
        assert pred2.predicate_id in det.stale_predicate_ids
        assert any("STALE" in r for r in det.reasons)


# ===========================================================================
# Required Test 4: Missing Verifier Result -> Not READY
# ===========================================================================


class TestReadinessMissingVerifierResult:
    """Requirement 4: missing verifier result -> not READY."""

    def test_missing_observation_prevents_ready(self) -> None:
        mission_id = MissionId.generate()

        pred1 = _make_calendar_predicate(mission_id, expected_status="confirmed")
        pred2 = _make_tasks_predicate(mission_id, expected_status="needsAction")

        # Only pred1 has an observation; pred2 has none
        obs1 = _make_calendar_observation(status="confirmed", observed_at=T_OBS)

        req1 = _make_calendar_request(mission_id, pred1)
        req2 = _make_tasks_request(mission_id, pred2)

        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred1, pred2],
            verification_requests={
                pred1.predicate_id: req1,
                pred2.predicate_id: req2,
            },
            observations={pred1.predicate_id: obs1},
            current_state=MissionState.VERIFYING,
            at=T_EVAL,
        )

        assert det.is_ready is False
        assert det.state != MissionState.READY
        assert det.missing_predicate_ids == (pred2.predicate_id,)
        assert any("Missing required verifier observation" in r for r in det.reasons)


# ===========================================================================
# Required Test 5: Execution Succeeded but Predicate FALSE -> Not READY
# ===========================================================================


class TestReadinessExecutionSucceededPredicateFalse:
    """Requirement 5: execution succeeded but predicate FALSE -> not READY."""

    def test_execution_success_does_not_override_predicate_false(self) -> None:
        mission_id = MissionId.generate()
        aid1 = ActionId.generate()

        a1 = ActionContract.create(
            action_id=aid1,
            mission_id=mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=CAL_TARGET,
            parameters={"summary": "School dropoff"},
        )
        # Execution succeeded at tool layer!
        exec_rec = _make_execution_record(mission_id, [(a1, True)])
        assert exec_rec.is_all_succeeded is True

        pred1 = _make_calendar_predicate(mission_id, expected_status="confirmed")
        # But read-back observed "cancelled" status!
        obs1 = _make_calendar_observation(status="cancelled", observed_at=T_OBS)
        req1 = _make_calendar_request(mission_id, pred1)

        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred1],
            verification_requests={pred1.predicate_id: req1},
            observations={pred1.predicate_id: obs1},
            execution_record=exec_rec,
            current_state=MissionState.VERIFYING,
            at=T_EVAL,
        )

        # Execution succeeded, but predicate evaluated FALSE -> NOT READY
        assert det.is_ready is False
        assert det.state != MissionState.READY
        assert det.failed_predicate_ids == (pred1.predicate_id,)
        assert any("evaluated FALSE" in r for r in det.reasons)


# ===========================================================================
# Required Test 6: All Provider Calls Succeeded but Read-Back Missing -> Not READY
# ===========================================================================


class TestReadinessProviderSuccessWithoutReadBack:
    """Requirement 6: all provider calls succeeded but read-back missing -> not READY."""

    def test_provider_success_alone_without_readback_cannot_create_ready(self) -> None:
        mission_id = MissionId.generate()
        aid1 = ActionId.generate()
        aid2 = ActionId.generate()

        a1 = ActionContract.create(
            action_id=aid1,
            mission_id=mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=CAL_TARGET,
            parameters={"summary": "School dropoff"},
        )
        a2 = ActionContract.create(
            action_id=aid2,
            mission_id=mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Pack backpacks"},
        )
        # All provider calls succeeded
        exec_rec = _make_execution_record(mission_id, [(a1, True), (a2, True)])
        assert exec_rec.is_all_succeeded is True

        pred1 = _make_calendar_predicate(mission_id, expected_status="confirmed")
        pred2 = _make_tasks_predicate(mission_id, expected_status="needsAction")

        req1 = _make_calendar_request(mission_id, pred1)
        req2 = _make_tasks_request(mission_id, pred2)

        # Zero observations provided (read-back missing completely)
        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred1, pred2],
            verification_requests={
                pred1.predicate_id: req1,
                pred2.predicate_id: req2,
            },
            observations={},
            execution_record=exec_rec,
            current_state=MissionState.VERIFYING,
            at=T_EVAL,
        )

        assert det.is_ready is False
        assert det.state != MissionState.READY
        assert det.missing_predicate_ids == (pred1.predicate_id, pred2.predicate_id)


# ===========================================================================
# Required Test 7: Model / Planner Object Cannot Create READY
# ===========================================================================


class TestReadinessModelPlannerRejection:
    """Requirement 7: model/planner object cannot create READY."""

    def test_rejects_candidate_plan_proposal(self) -> None:
        mission_id = MissionId.generate()
        step = CandidateActionProposal.create(
            action_type=ActionType.CALENDAR_UPDATE,
            target_ref=SymbolicTargetRef.CALENDAR_EVENT,
            parameters={"summary": "School dropoff"},
        )
        plan = CandidatePlanProposal.create(
            mission_id=mission_id,
            steps=[step],
        )

        with pytest.raises(PlannerReadinessAuthorityError, match="ZERO verification authority"):
            assert_not_planner_or_execution_payload(plan)

        with pytest.raises(PlannerReadinessAuthorityError, match="ZERO verification authority"):
            compute_mission_readiness(
                mission_id=mission_id,
                predicates=plan,  # type: ignore[arg-type]
                at=T_EVAL,
            )

    def test_rejects_candidate_action_proposal(self) -> None:
        step = CandidateActionProposal.create(
            action_type=ActionType.CALENDAR_UPDATE,
            target_ref=SymbolicTargetRef.CALENDAR_EVENT,
            parameters={"summary": "Dropoff"},
        )
        with pytest.raises(PlannerReadinessAuthorityError, match="ZERO verification authority"):
            assert_not_planner_or_execution_payload(step)

    def test_rejects_planner_input(self) -> None:
        mission_id = MissionId.generate()
        p_in = PlannerInput(mission_id=mission_id, intent="Fix morning schedule")
        with pytest.raises(PlannerReadinessAuthorityError, match="ZERO verification authority"):
            assert_not_planner_or_execution_payload(p_in)

    def test_rejects_execution_payload_substitution(self) -> None:
        pres = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_UPDATE,
            success=True,
            status_name="SUCCESS",
        )
        with pytest.raises(
            ExecutionPayloadSubstitutionError, match="cannot substitute for verification"
        ):
            assert_not_planner_or_execution_payload(pres)

    def test_rejects_raw_string_prose_claiming_readiness(self) -> None:
        mission_id = MissionId.generate()
        with pytest.raises(
            ReadinessContractTypeError, match="String prose cannot substitute for structured"
        ):
            compute_mission_readiness(
                mission_id=mission_id,
                predicates="All events created successfully and verified READY!",  # type: ignore[arg-type]
                at=T_EVAL,
            )


# ===========================================================================
# Required Test 8: Deterministic Same Inputs -> Same Readiness Result
# ===========================================================================


class TestReadinessDeterminism:
    """Requirement 8: deterministic same inputs -> same readiness result."""

    def test_identical_inputs_produce_identical_determinations(self) -> None:
        mission_id = MissionId.generate()

        pred = _make_calendar_predicate(mission_id, expected_status="confirmed")
        obs = _make_calendar_observation(status="confirmed", observed_at=T_OBS)
        req = _make_calendar_request(mission_id, pred)

        det1 = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred],
            verification_requests={pred.predicate_id: req},
            observations={pred.predicate_id: obs},
            current_state=MissionState.VERIFYING,
            at=T_EVAL,
        )

        det2 = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred],
            verification_requests={pred.predicate_id: req},
            observations={pred.predicate_id: obs},
            current_state=MissionState.VERIFYING,
            at=T_EVAL,
        )

        assert det1 == det2
        assert det1.is_ready == det2.is_ready
        assert det1.state == det2.state
        assert det1.reasons == det2.reasons
        assert det1.satisfied_predicate_ids == det2.satisfied_predicate_ids
        assert det1.to_dict() == det2.to_dict()


# ===========================================================================
# Boundary & Defensive Invariant Tests
# ===========================================================================


class TestReadinessBoundaryInvariants:
    """Defensive boundary checks verifying fail-closed lifecycle invariants."""

    def test_current_state_not_verifying_cannot_enter_ready(self) -> None:
        mission_id = MissionId.generate()
        pred = _make_calendar_predicate(mission_id, expected_status="confirmed")
        obs = _make_calendar_observation(status="confirmed", observed_at=T_OBS)
        req = _make_calendar_request(mission_id, pred)

        # Attempting readiness check while mission is still EXECUTING
        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred],
            verification_requests={pred.predicate_id: req},
            observations={pred.predicate_id: obs},
            current_state=MissionState.EXECUTING,
            at=T_EVAL,
        )

        assert det.is_ready is False
        assert det.state == MissionState.EXECUTING
        assert any("READY may only be entered from VERIFYING" in r for r in det.reasons)

    def test_zero_predicates_cannot_be_ready(self) -> None:
        mission_id = MissionId.generate()
        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[],
            current_state=MissionState.VERIFYING,
            at=T_EVAL,
        )
        assert det.is_ready is False
        assert any("at least one desired-state predicate" in r for r in det.reasons)

    def test_naive_datetime_fails_closed(self) -> None:
        mission_id = MissionId.generate()
        naive_at = datetime(2026, 10, 5, 12, 0, 0)
        with pytest.raises(NaiveDatetimeError):
            compute_mission_readiness(
                mission_id=mission_id,
                predicates=[],
                at=naive_at,
            )

    def test_mismatched_predicate_mission_id_fails_closed(self) -> None:
        mission_id1 = MissionId.generate()
        mission_id2 = MissionId.generate()

        pred = _make_calendar_predicate(mission_id2)
        with pytest.raises(ReadinessContractValueError, match="does not match"):
            compute_mission_readiness(
                mission_id=mission_id1,
                predicates=[pred],
                at=T_EVAL,
            )

    def test_mismatched_execution_record_mission_id_fails_closed(self) -> None:
        mission_id1 = MissionId.generate()
        mission_id2 = MissionId.generate()

        aid = ActionId.generate()
        a = ActionContract.create(
            action_id=aid,
            mission_id=mission_id2,
            action_type=ActionType.CALENDAR_UPDATE,
            target=CAL_TARGET,
            parameters={"summary": "School dropoff"},
        )
        exec_rec = _make_execution_record(mission_id2, [(a, True)])
        pred = _make_calendar_predicate(mission_id1)

        with pytest.raises(ReadinessContractValueError, match="does not match"):
            compute_mission_readiness(
                mission_id=mission_id1,
                predicates=[pred],
                execution_record=exec_rec,
                at=T_EVAL,
            )


# ===========================================================================
# Adversarial Tests: Canonical Lineage & Anti-Forgery (Phase P-09.04 Repair)
# ===========================================================================


class TestReadinessAdversarialLineage:
    """Proves that READY cannot be forged from detached, relabeled, or invalid facts.

    Scenarios:
    1. relabeled predicate evaluation cannot promote READY
    2. relabeled freshness result cannot promote READY
    3. forged TRUE cannot override observation that evaluates FALSE
    4. forged FRESH cannot override observation that is STALE
    5. target mismatch between request and observation blocks READY
    6. mission_id mismatch in request blocks READY
    7. predicate mismatch between request and desired state blocks READY
    8. missing verification request blocks READY
    9. missing verification observation blocks READY
    10. execution success + provider success + forged truth CANNOT produce READY
    """

    def test_relabeled_predicate_evaluation_cannot_promote_ready(self) -> None:
        """Supplied evaluation with mismatched predicate_id or foreign predicate is rejected."""
        mission_id = MissionId.generate()
        pred = _make_calendar_predicate(mission_id)
        obs = _make_calendar_observation()
        req = _make_calendar_request(mission_id, pred)
        foreign_pid = PredicateId.generate()

        forged_eval = PredicateEvaluationResult(
            predicate_id=foreign_pid,
            truth=PredicateTruth.TRUE,
            subject=pred.subject,
            operator=pred.operator,
            expected_value=pred.expected_value,
        )

        with pytest.raises(ReadinessContractValueError, match="foreign predicate"):
            compute_mission_readiness(
                mission_id=mission_id,
                predicates=[pred],
                verification_requests={pred.predicate_id: req},
                observations={pred.predicate_id: obs},
                predicate_evaluations={foreign_pid: forged_eval},
                at=T_EVAL,
            )

    def test_relabeled_freshness_result_cannot_promote_ready(self) -> None:
        """Supplied freshness evaluation with foreign predicate is rejected."""
        mission_id = MissionId.generate()
        pred = _make_calendar_predicate(mission_id)
        obs = _make_calendar_observation()
        req = _make_calendar_request(mission_id, pred)
        foreign_pid = PredicateId.generate()

        forged_fresh = FreshnessResult(
            status=FreshnessStatus.FRESH,
            observed_at=T_OBS,
            evaluated_at=T_EVAL,
            valid_until=T_EVAL,
            age_seconds=0.0,
            reason="Forged fresh",
        )

        with pytest.raises(ReadinessContractValueError, match="foreign predicate"):
            compute_mission_readiness(
                mission_id=mission_id,
                predicates=[pred],
                verification_requests={pred.predicate_id: req},
                observations={pred.predicate_id: obs},
                freshness_evaluations={foreign_pid: forged_fresh},
                at=T_EVAL,
            )

    def test_forged_true_cannot_override_observation_that_evaluates_false(self) -> None:
        """Caller cannot inject TRUE if canonical observation evaluates FALSE."""
        mission_id = MissionId.generate()
        pred = _make_calendar_predicate(mission_id, expected_status="confirmed")
        # Observation is actually cancelled!
        obs = _make_calendar_observation(status="cancelled", observed_at=T_OBS)
        req = _make_calendar_request(mission_id, pred)

        forged_eval = PredicateEvaluationResult(
            predicate_id=pred.predicate_id,
            truth=PredicateTruth.TRUE,
            subject=pred.subject,
            operator=pred.operator,
            expected_value=pred.expected_value,
        )

        with pytest.raises(
            ReadinessContractValueError, match="Contradiction: supplied evaluation claims TRUE"
        ):
            compute_mission_readiness(
                mission_id=mission_id,
                predicates=[pred],
                verification_requests={pred.predicate_id: req},
                observations={pred.predicate_id: obs},
                predicate_evaluations={pred.predicate_id: forged_eval},
                at=T_EVAL,
            )

    def test_forged_fresh_cannot_override_observation_that_is_stale(self) -> None:
        """Caller cannot inject FRESH if canonical observation is STALE."""
        mission_id = MissionId.generate()
        pred = _make_calendar_predicate(mission_id, max_age_seconds=60)
        # Observation is 9 minutes old (STALE at T_STALE_EVAL)
        obs = _make_calendar_observation(observed_at=T_OBS)
        req = _make_calendar_request(mission_id, pred)

        forged_fresh = FreshnessResult(
            status=FreshnessStatus.FRESH,
            observed_at=T_OBS,
            evaluated_at=T_STALE_EVAL,
            valid_until=T_STALE_EVAL,
            age_seconds=0.0,
            reason="Forged fresh",
        )

        with pytest.raises(
            ReadinessContractValueError, match="Contradiction: supplied evaluation claims FRESH"
        ):
            compute_mission_readiness(
                mission_id=mission_id,
                predicates=[pred],
                verification_requests={pred.predicate_id: req},
                observations={pred.predicate_id: obs},
                freshness_evaluations={pred.predicate_id: forged_fresh},
                at=T_STALE_EVAL,
            )

    def test_target_mismatch_between_request_and_observation_blocks_ready(self) -> None:
        """Observation for a different target than the request fails closed and blocks READY."""
        mission_id = MissionId.generate()
        pred = _make_calendar_predicate(mission_id)
        other_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-other-different",
            parent_id="primary",
        )
        obs_wrong_target = _make_calendar_observation(cal_target=other_target)
        req = _make_calendar_request(mission_id, pred, target=CAL_TARGET)

        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred],
            verification_requests={pred.predicate_id: req},
            observations={pred.predicate_id: obs_wrong_target},
            at=T_EVAL,
        )

        assert det.is_ready is False
        assert det.state != MissionState.READY
        assert pred.predicate_id in det.failed_predicate_ids

    def test_mission_id_mismatch_in_request_blocks_ready(self) -> None:
        """VerificationRequest with different mission_id fails closed."""
        mission_id1 = MissionId.generate()
        mission_id2 = MissionId.generate()
        pred = _make_calendar_predicate(mission_id1)
        obs = _make_calendar_observation()

        # Request bound to mission_id2
        action2 = ActionContract.create(
            mission_id=mission_id2,
            action_type=ActionType.CALENDAR_READ,
            target=CAL_TARGET,
            parameters={},
        )
        req = VerificationRequest(
            mission_id=mission_id2,
            action=action2,
            target=CAL_TARGET,
            predicate=None,
        )

        with pytest.raises(ReadinessContractValueError, match="mission_id"):
            compute_mission_readiness(
                mission_id=mission_id1,
                predicates=[pred],
                verification_requests={pred.predicate_id: req},
                observations={pred.predicate_id: obs},
                at=T_EVAL,
            )

    def test_predicate_mismatch_between_request_and_desired_state_blocks_ready(self) -> None:
        """VerificationRequest referencing a different predicate fails closed."""
        mission_id = MissionId.generate()
        pred1 = _make_calendar_predicate(mission_id)
        pred2 = _make_calendar_predicate(mission_id)
        obs = _make_calendar_observation()

        # Request for pred1 references pred2 instead
        action = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=CAL_TARGET,
            parameters={},
        )
        mismatched_req = VerificationRequest(
            mission_id=mission_id,
            action=action,
            target=CAL_TARGET,
            predicate=pred2,
        )

        with pytest.raises(
            ReadinessContractValueError, match="does not match desired state predicate"
        ):
            compute_mission_readiness(
                mission_id=mission_id,
                predicates=[pred1],
                verification_requests={pred1.predicate_id: mismatched_req},
                observations={pred1.predicate_id: obs},
                at=T_EVAL,
            )

    def test_missing_verification_request_blocks_ready(self) -> None:
        """Missing verification request marks predicate missing and blocks READY."""
        mission_id = MissionId.generate()
        pred = _make_calendar_predicate(mission_id)
        obs = _make_calendar_observation()

        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred],
            verification_requests={},
            observations={pred.predicate_id: obs},
            at=T_EVAL,
        )

        assert det.is_ready is False
        assert det.state != MissionState.READY
        assert pred.predicate_id in det.missing_predicate_ids

    def test_missing_verification_observation_blocks_ready(self) -> None:
        """Missing verification observation marks predicate missing and blocks READY."""
        mission_id = MissionId.generate()
        pred = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, pred)

        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[pred],
            verification_requests={pred.predicate_id: req},
            observations={},
            at=T_EVAL,
        )

        assert det.is_ready is False
        assert det.state != MissionState.READY
        assert pred.predicate_id in det.missing_predicate_ids

    def test_execution_and_provider_success_with_forged_truth_cannot_produce_ready(self) -> None:
        """Execution success + provider success cannot forge READY when read-back
        is contradictory.
        """
        mission_id = MissionId.generate()
        aid = ActionId.generate()
        action = ActionContract.create(
            action_id=aid,
            mission_id=mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=CAL_TARGET,
            parameters={"summary": "School dropoff"},
        )
        exec_rec = _make_execution_record(mission_id, [(action, True)])
        assert exec_rec.is_all_succeeded is True

        pred = _make_calendar_predicate(mission_id, expected_status="confirmed")
        req = _make_calendar_request(mission_id, pred)
        # Reality: cancelled!
        obs = _make_calendar_observation(status="cancelled")

        forged_eval = PredicateEvaluationResult(
            predicate_id=pred.predicate_id,
            truth=PredicateTruth.TRUE,
            subject=pred.subject,
            operator=pred.operator,
            expected_value=pred.expected_value,
        )

        with pytest.raises(
            ReadinessContractValueError, match="Contradiction: supplied evaluation claims TRUE"
        ):
            compute_mission_readiness(
                mission_id=mission_id,
                predicates=[pred],
                verification_requests={pred.predicate_id: req},
                observations={pred.predicate_id: obs},
                predicate_evaluations={pred.predicate_id: forged_eval},
                execution_record=exec_rec,
                at=T_EVAL,
            )
