"""Tests for deterministic mission state reconciliation (Phase P-09.05).

Enforces StillDone core architectural laws:
- StillDone thesis: "Done, and still true."
- READY is not permanent merely because it was once true.
- Reconciliation re-evaluates previously verified missions against fresh external read-back.
- Historical verification evidence != current truth.
- Model / planner output has ZERO verification authority.
- Identical or older historical observations are rejected as replay.
- Deterministic runtime owns all reconciliation determinations.
- Zero network calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    FreshnessMode,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.state import ProviderExecutionResult
from stilldone.planning.contracts import (
    PlannerInput,
)
from stilldone.verifier.contracts import (
    ExecutionPayloadSubstitutionError,
    VerificationObservation,
    VerificationRequest,
    VerifierTargetMismatchError,
)
from stilldone.verifier.freshness import (
    FreshnessStatus,
    NaiveDatetimeError,
)
from stilldone.verifier.predicates import PredicateTruth
from stilldone.verifier.readiness import compute_mission_readiness
from stilldone.verifier.reconciliation import (
    HistoricalObservationSubstitutionError,
    InconclusiveReconciliationError,
    PlannerReconciliationAuthorityError,
    ReconciliationContractTypeError,
    ReconciliationContractValueError,
    ReconciliationDetermination,
    ReconciliationLifecycleError,
    ReconciliationStatus,
    apply_reconciliation_transition,
    reconcile_mission_state,
)

# ===========================================================================
# Test Fixtures & Constants
# ===========================================================================

T_HIST = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
T_FRESH = datetime(2026, 10, 5, 12, 5, 0, tzinfo=UTC)
T_EVAL = datetime(2026, 10, 5, 12, 6, 0, tzinfo=UTC)

CAL_TARGET = TargetIdentity(
    system="google_calendar",
    resource_kind=ResourceKind.CALENDAR_EVENT,
    resource_id="event_123",
    parent_id="primary",
)

TASKS_TARGET = TargetIdentity(
    system="google_tasks",
    resource_kind=ResourceKind.TASK,
    resource_id="task_456",
    parent_id="list_789",
)


def _make_calendar_predicate(
    mission_id: MissionId, pid: PredicateId | None = None
) -> DesiredStatePredicate:
    return DesiredStatePredicate(
        predicate_id=pid or PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="confirmed",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )


def _make_tasks_predicate(
    mission_id: MissionId, pid: PredicateId | None = None
) -> DesiredStatePredicate:
    return DesiredStatePredicate(
        predicate_id=pid or PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="completed",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )


def _make_calendar_request(
    mission_id: MissionId, predicate: DesiredStatePredicate
) -> VerificationRequest:
    action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_UPDATE,
        target=CAL_TARGET,
        parameters={"status": "confirmed"},
    )
    return VerificationRequest(
        mission_id=mission_id,
        action=action,
        target=CAL_TARGET,
        predicate=predicate,
    )


def _make_tasks_request(
    mission_id: MissionId, predicate: DesiredStatePredicate
) -> VerificationRequest:
    action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=TASKS_TARGET,
        parameters={},
    )
    return VerificationRequest(
        mission_id=mission_id,
        action=action,
        target=TASKS_TARGET,
        predicate=predicate,
    )


# ===========================================================================
# P-09.05 Reconciliation Logic Tests
# ===========================================================================


class TestMissionReconciliation:
    """Verifies deterministic reconciliation against fresh external read-back."""

    def test_reconcile_still_true_when_all_required_predicates_true_and_fresh(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        hist_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_HIST,
            exists=True,
            properties={"status": "confirmed"},
            provenance=EvidenceProvenance.FIXTURE,
        )
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
            provenance=EvidenceProvenance.FIXTURE,
        )

        res = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            historical_observations={p.predicate_id: hist_obs},
            at=T_EVAL,
        )

        assert res.status == ReconciliationStatus.STILL_TRUE
        assert res.is_still_true is True
        assert res.satisfied_predicate_ids == (p.predicate_id,)
        assert len(res.drifted_predicate_ids) == 0
        assert len(res.stale_predicate_ids) == 0
        assert len(res.incomplete_predicate_ids) == 0
        assert res.predicate_evaluations[p.predicate_id].truth == PredicateTruth.TRUE
        assert res.freshness_evaluations[p.predicate_id].status == FreshnessStatus.FRESH

    def test_reconcile_no_longer_true_when_required_predicate_evaluates_false(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        hist_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_HIST,
            exists=True,
            properties={"status": "confirmed"},
        )
        # Event was cancelled externally!
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "cancelled"},
        )

        res = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            historical_observations={p.predicate_id: hist_obs},
            at=T_EVAL,
        )

        assert res.status == ReconciliationStatus.NO_LONGER_TRUE
        assert res.is_still_true is False
        assert res.drifted_predicate_ids == (p.predicate_id,)
        assert len(res.satisfied_predicate_ids) == 0

    def test_reconcile_stale_when_fresh_observation_is_outside_freshness_window(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        # Fresh observation is older than max_age_seconds (standard is 300s = 5m)
        obs_time = T_EVAL - timedelta(seconds=600)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=obs_time,
            exists=True,
            properties={"status": "confirmed"},
        )

        res = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            at=T_EVAL,
        )

        assert res.status == ReconciliationStatus.STALE
        assert res.is_still_true is False
        assert res.stale_predicate_ids == (p.predicate_id,)

    def test_reconcile_incomplete_when_required_observation_missing(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        res = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={},  # missing observation for required predicate
            at=T_EVAL,
        )

        assert res.status == ReconciliationStatus.INCOMPLETE
        assert res.is_still_true is False
        assert res.incomplete_predicate_ids == (p.predicate_id,)

    def test_reconcile_incomplete_when_required_verification_request_missing(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        res = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={},  # missing request
            fresh_observations={p.predicate_id: fresh_obs},
            at=T_EVAL,
        )

        assert res.status == ReconciliationStatus.INCOMPLETE
        assert res.incomplete_predicate_ids == (p.predicate_id,)

    def test_reject_identical_historical_observation_reused_as_fresh(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        hist_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_HIST,
            exists=True,
            properties={"status": "confirmed"},
        )

        with pytest.raises(HistoricalObservationSubstitutionError) as exc_info:
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[p],
                verification_requests={p.predicate_id: req},
                fresh_observations={p.predicate_id: hist_obs},  # identical object
                historical_observations={p.predicate_id: hist_obs},
                at=T_EVAL,
            )
        assert "Identical historical observation object reused" in str(exc_info.value)

    def test_reject_fresh_observation_timestamp_not_strictly_newer_than_historical(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        hist_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_HIST,
            exists=True,
            properties={"status": "confirmed"},
        )
        # Separate object, but timestamp is older or equal
        stale_fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_HIST,  # not newer!
            exists=True,
            properties={"status": "confirmed"},
        )

        with pytest.raises(HistoricalObservationSubstitutionError) as exc_info:
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[p],
                verification_requests={p.predicate_id: req},
                fresh_observations={p.predicate_id: stale_fresh_obs},
                historical_observations={p.predicate_id: hist_obs},
                at=T_EVAL,
            )
        assert "is not strictly newer than historical observation" in str(exc_info.value)

    def test_reject_execution_payload_substitution(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)

        exec_res = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_READ,
            success=True,
            status_name="SUCCESS",
        )

        with pytest.raises(ExecutionPayloadSubstitutionError):
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[p],
                verification_requests={p.predicate_id: exec_res},  # type: ignore[dict-item]
                fresh_observations={},
                at=T_EVAL,
            )

    def test_reject_model_planner_proposals(self) -> None:
        mission_id = MissionId.generate()
        planner_input = PlannerInput(
            mission_id=mission_id,
            intent="I think everything is done",
        )

        with pytest.raises(PlannerReconciliationAuthorityError):
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[planner_input],  # type: ignore[list-item]
                verification_requests={},
                fresh_observations={},
                at=T_EVAL,
            )

    def test_reject_naive_datetime(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        with pytest.raises(NaiveDatetimeError):
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[p],
                verification_requests={p.predicate_id: req},
                fresh_observations={p.predicate_id: fresh_obs},
                at=datetime(2026, 10, 5, 12, 0, 0),  # naive!
            )

    def test_reject_request_predicate_none(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        action = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=CAL_TARGET,
            parameters={"status": "confirmed"},
        )
        req_without_pred = VerificationRequest(
            mission_id=mission_id,
            action=action,
            target=CAL_TARGET,
            predicate=None,
        )
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        with pytest.raises(ReconciliationContractValueError) as exc_info:
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[p],
                verification_requests={p.predicate_id: req_without_pred},
                fresh_observations={p.predicate_id: fresh_obs},
                at=T_EVAL,
            )
        assert "predicate cannot be None" in str(exc_info.value)

    def test_reject_request_lineage_mismatch(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        action = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=CAL_TARGET,
            parameters={"status": "confirmed"},
        )
        # Request with mismatched target id
        mismatched_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="different_event",
            parent_id="primary",
        )
        req = VerificationRequest(
            mission_id=mission_id,
            action=action,
            target=mismatched_target,
            predicate=p,
        )
        fresh_obs = VerificationObservation(
            target=mismatched_target,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        with pytest.raises(VerifierTargetMismatchError):
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[p],
                verification_requests={p.predicate_id: req},
                fresh_observations={p.predicate_id: fresh_obs},
                at=T_EVAL,
            )

    def test_determination_immutability_and_serialization(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        res = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            at=T_EVAL,
        )

        assert isinstance(res, ReconciliationDetermination)
        # Attempt mutation of frozen dataclass
        with pytest.raises(AttributeError):
            res.status = ReconciliationStatus.NO_LONGER_TRUE  # type: ignore[misc]

        d = res.to_dict()
        assert d["mission_id"] == str(mission_id)
        assert d["status"] == "STILL_TRUE"
        assert d["satisfied_predicate_ids"] == [str(p.predicate_id)]


# ===========================================================================
# P-09.06 Lifecycle Transition & Drift Downgrade Tests
# ===========================================================================


class TestReconciliationTransition:
    """Verifies deterministic READY -> DRIFTED downgrade and privacy guarantees."""

    def test_ready_remains_ready_when_still_true(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            at=T_EVAL,
        )

        transition = apply_reconciliation_transition(
            prior_state=MissionState.READY,
            reconciliation=reconciliation,
        )

        assert transition.mission_id == mission_id
        assert transition.prior_state == MissionState.READY
        assert transition.new_state == MissionState.READY
        assert transition.is_drifted is False
        assert transition.explanation is None

    def test_ready_transitions_to_drifted_when_no_longer_true(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "cancelled"},
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            at=T_EVAL,
        )

        transition = apply_reconciliation_transition(
            prior_state=MissionState.READY,
            reconciliation=reconciliation,
        )

        assert transition.prior_state == MissionState.READY
        assert transition.new_state == MissionState.DRIFTED
        assert transition.is_drifted is True
        assert transition.explanation is not None
        assert "drifted from READY" in transition.explanation
        assert str(p.predicate_id) in transition.explanation
        # Privacy guarantee: no raw resource IDs or properties in explanation
        assert "event_123" not in transition.explanation
        assert "cancelled" not in transition.explanation

    def test_ready_does_not_transition_when_stale_and_fails_closed(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_EVAL - timedelta(seconds=600),
            exists=True,
            properties={"status": "confirmed"},
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            at=T_EVAL,
        )
        assert reconciliation.status == ReconciliationStatus.STALE

        # STALE does NOT produce DRIFTED: fails closed via InconclusiveReconciliationError
        with pytest.raises(InconclusiveReconciliationError) as exc_info:
            apply_reconciliation_transition(
                prior_state=MissionState.READY,
                reconciliation=reconciliation,
            )

        assert exc_info.value.status == ReconciliationStatus.STALE
        assert exc_info.value.reconciliation is reconciliation
        assert "observation stale" in str(exc_info.value)
        assert "does not prove desired state false" in str(exc_info.value)
        assert isinstance(exc_info.value, ReconciliationLifecycleError)

    def test_ready_does_not_transition_when_incomplete_and_fails_closed(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={},  # missing observation
            at=T_EVAL,
        )
        assert reconciliation.status == ReconciliationStatus.INCOMPLETE

        # INCOMPLETE does NOT produce DRIFTED: fails closed via InconclusiveReconciliationError
        with pytest.raises(InconclusiveReconciliationError) as exc_info:
            apply_reconciliation_transition(
                prior_state=MissionState.READY,
                reconciliation=reconciliation,
            )

        assert exc_info.value.status == ReconciliationStatus.INCOMPLETE
        assert exc_info.value.reconciliation is reconciliation
        assert "missing verification facts" in str(exc_info.value)
        assert "does not prove desired state false" in str(exc_info.value)
        assert isinstance(exc_info.value, ReconciliationLifecycleError)

    def test_reject_transition_from_non_ready_state(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            at=T_EVAL,
        )

        for invalid_state in (
            MissionState.VERIFYING,
            MissionState.EXECUTING,
            MissionState.PARTIAL,
            MissionState.DRAFT,
            MissionState.FAILED,
            MissionState.CANCELLED,
        ):
            with pytest.raises(ReconciliationLifecycleError) as exc_info:
                apply_reconciliation_transition(
                    prior_state=invalid_state,
                    reconciliation=reconciliation,
                )
            assert "only allowed from READY state" in str(exc_info.value)

    def test_reject_planner_proposal_as_transition_reconciliation(self) -> None:
        planner_input = PlannerInput(
            mission_id=MissionId.generate(),
            intent="I say this is verified",
        )

        with pytest.raises(PlannerReconciliationAuthorityError):
            apply_reconciliation_transition(
                prior_state=MissionState.READY,
                reconciliation=planner_input,  # type: ignore[arg-type]
            )

    def test_transition_result_serialization(self) -> None:
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            at=T_EVAL,
        )

        transition = apply_reconciliation_transition(
            prior_state=MissionState.READY,
            reconciliation=reconciliation,
        )

        d = transition.to_dict()
        assert d["mission_id"] == str(mission_id)
        assert d["prior_state"] == "READY"
        assert d["new_state"] == "READY"
        assert d["is_drifted"] is False
        assert d["explanation"] is None
        assert "reconciliation" in d


# ===========================================================================
# P-09.07 Adversarial Read-Back & Reconciliation Tests
# ===========================================================================


class TestAdversarialReadbackReconciliation:
    """Verifies all 10 adversarial reconciliation and read-back scenarios."""

    def test_01_executor_success_alone_cannot_produce_ready_or_still_true(self) -> None:
        """Scenario 1: Executor success alone cannot produce READY/STILL_TRUE."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)

        # compute_mission_readiness without verification requests cannot produce READY
        det = compute_mission_readiness(
            mission_id=mission_id,
            predicates=[p],
            at=T_EVAL,
        )
        assert det.is_ready is False
        assert det.state != MissionState.READY

        # An execution payload cannot substitute for verification facts in reconciliation
        exec_payload = ProviderExecutionResult(
            action_type=ActionType.CALENDAR_UPDATE,
            success=True,
            status_name="SUCCESS",
        )
        with pytest.raises(ExecutionPayloadSubstitutionError):
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[p],
                verification_requests={p.predicate_id: exec_payload},  # type: ignore[dict-item]
                fresh_observations={},
                at=T_EVAL,
            )

    def test_02_executor_success_with_readback_mismatch_produces_no_longer_true_and_drifted(
        self,
    ) -> None:
        """Scenario 2: Executor success + readback mismatch -> NO_LONGER_TRUE / DRIFTED."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        # Read-back reveals that reality did not take the update (remains 'unconfirmed')
        mismatched_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "unconfirmed"},
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: mismatched_obs},
            at=T_EVAL,
        )
        assert reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE
        assert reconciliation.is_still_true is False

        transition = apply_reconciliation_transition(
            prior_state=MissionState.READY,
            reconciliation=reconciliation,
        )
        assert transition.new_state == MissionState.DRIFTED
        assert transition.is_drifted is True

    def test_03_readback_observation_missing_required_property_produces_no_longer_true_and_drifted(
        self,
    ) -> None:
        """Scenario 3: Read-back observation missing required property -> NO_LONGER_TRUE."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        # Observation exists, but missing 'status' property
        missing_prop_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={},  # 'status' missing
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: missing_prop_obs},
            at=T_EVAL,
        )
        assert reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE

        transition = apply_reconciliation_transition(
            prior_state=MissionState.READY,
            reconciliation=reconciliation,
        )
        assert transition.new_state == MissionState.DRIFTED
        assert transition.is_drifted is True

    def test_04_stale_fresh_observation_does_not_produce_drifted_and_fails_closed(self) -> None:
        """Scenario 4: Stale fresh observation -> STALE, fails closed (does NOT produce DRIFTED)."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        # Observation is 10 minutes old (> 300s window)
        stale_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_EVAL - timedelta(seconds=600),
            exists=True,
            properties={"status": "confirmed"},
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: stale_obs},
            at=T_EVAL,
        )
        assert reconciliation.status == ReconciliationStatus.STALE

        # STALE does NOT produce DRIFTED: fails closed via InconclusiveReconciliationError
        with pytest.raises(InconclusiveReconciliationError) as exc_info:
            apply_reconciliation_transition(
                prior_state=MissionState.READY,
                reconciliation=reconciliation,
            )
        assert exc_info.value.status == ReconciliationStatus.STALE
        assert exc_info.value.reconciliation is reconciliation
        assert "observation stale" in str(exc_info.value)
        assert "does not prove desired state false" in str(exc_info.value)

    def test_05_observation_older_than_historical_verification_rejected_as_replay(self) -> None:
        """Scenario 5: Observation older than historical observation -> rejected as replay."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        hist_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_HIST,
            exists=True,
            properties={"status": "confirmed"},
        )
        older_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_HIST - timedelta(seconds=10),
            exists=True,
            properties={"status": "confirmed"},
        )

        with pytest.raises(HistoricalObservationSubstitutionError) as exc_info:
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[p],
                verification_requests={p.predicate_id: req},
                fresh_observations={p.predicate_id: older_obs},
                historical_observations={p.predicate_id: hist_obs},
                at=T_EVAL,
            )
        assert "is not strictly newer than historical observation" in str(exc_info.value)

    def test_06_identical_observation_object_reused_as_fresh_rejected(self) -> None:
        """Scenario 6: Identical observation object reused as fresh -> rejected."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_HIST,
            exists=True,
            properties={"status": "confirmed"},
        )

        with pytest.raises(HistoricalObservationSubstitutionError) as exc_info:
            reconcile_mission_state(
                mission_id=mission_id,
                predicates=[p],
                verification_requests={p.predicate_id: req},
                fresh_observations={p.predicate_id: obs},
                historical_observations={p.predicate_id: obs},
                at=T_EVAL,
            )
        assert "Identical historical observation object reused" in str(exc_info.value)

    def test_07_missing_observation_for_required_predicate_produces_incomplete_and_fails_closed(
        self,
    ) -> None:
        """Scenario 7: Missing observation for required predicate -> INCOMPLETE, fails closed."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={},  # missing observation for required predicate
            at=T_EVAL,
        )
        assert reconciliation.status == ReconciliationStatus.INCOMPLETE

        # INCOMPLETE does NOT produce DRIFTED: fails closed via InconclusiveReconciliationError
        with pytest.raises(InconclusiveReconciliationError) as exc_info:
            apply_reconciliation_transition(
                prior_state=MissionState.READY,
                reconciliation=reconciliation,
            )
        assert exc_info.value.status == ReconciliationStatus.INCOMPLETE
        assert exc_info.value.reconciliation is reconciliation
        assert "missing verification facts" in str(exc_info.value)
        assert "does not prove desired state false" in str(exc_info.value)

    def test_08_non_ready_mission_attempted_reconciliation_transition_rejected(self) -> None:
        """Scenario 8: Non-READY mission attempted reconciliation transition -> rejected."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            at=T_EVAL,
        )

        with pytest.raises(ReconciliationLifecycleError):
            apply_reconciliation_transition(
                prior_state=MissionState.VERIFYING,
                reconciliation=reconciliation,
            )

    def test_09_model_proposal_passed_as_reconciliation_proof_rejected(self) -> None:
        """Scenario 9: Model proposal passed as reconciliation proof -> rejected."""
        planner_input = PlannerInput(
            mission_id=MissionId.generate(),
            intent="Model hallucinating verification outcome",
        )

        with pytest.raises(PlannerReconciliationAuthorityError):
            reconcile_mission_state(
                mission_id=planner_input.mission_id,
                predicates=[planner_input],  # type: ignore[list-item]
                verification_requests={},
                fresh_observations={},
                at=T_EVAL,
            )

    def test_10_valid_fresh_readback_yields_still_true_and_remains_ready(
        self,
    ) -> None:
        """Scenario 10: Valid fresh readback proving desired state -> STILL_TRUE / remains READY."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)
        req = _make_calendar_request(mission_id, p)

        hist_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_HIST,
            exists=True,
            properties={"status": "confirmed"},
        )
        fresh_obs = VerificationObservation(
            target=CAL_TARGET,
            observed_at=T_FRESH,
            exists=True,
            properties={"status": "confirmed"},
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: req},
            fresh_observations={p.predicate_id: fresh_obs},
            historical_observations={p.predicate_id: hist_obs},
            at=T_EVAL,
        )
        assert reconciliation.status == ReconciliationStatus.STILL_TRUE
        assert reconciliation.is_still_true is True

        transition = apply_reconciliation_transition(
            prior_state=MissionState.READY,
            reconciliation=reconciliation,
        )
        assert transition.new_state == MissionState.READY
        assert transition.is_drifted is False
        assert transition.explanation is None

    def test_11_string_prose_passed_as_reconciliation_authority_rejected(self) -> None:
        """Scenario 11: String prose passed as reconciliation authority -> rejected fail closed."""
        with pytest.raises(ReconciliationContractTypeError) as exc_info:
            apply_reconciliation_transition(
                prior_state=MissionState.READY,
                reconciliation="I certify this mission is true",  # type: ignore[arg-type]
            )
        assert "reconciliation must be ReconciliationDetermination" in str(
            exc_info.value
        ) or "String prose cannot substitute" in str(exc_info.value)

    def test_12_privacy_check_drifted_explanation_omits_sensitive_data(self) -> None:
        """Scenario 12: Privacy check: DRIFTED explanation omits resource IDs, titles, notes."""
        mission_id = MissionId.generate()
        p = _make_calendar_predicate(mission_id)

        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="secret_event_99999",
            parent_id="private_calendar_alpha",
        )

        sensitive_obs = VerificationObservation(
            target=target,
            observed_at=T_FRESH,
            exists=True,
            properties={
                "status": "cancelled",
                "summary": "Secret Executive Board Meeting",
                "description": "Confidential acquisition strategy notes",
            },
        )

        action = ActionContract.create(
            mission_id=mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=target,
            parameters={},
        )
        sensitive_req = VerificationRequest(
            mission_id=mission_id,
            action=action,
            target=target,
            predicate=p,
        )

        reconciliation = reconcile_mission_state(
            mission_id=mission_id,
            predicates=[p],
            verification_requests={p.predicate_id: sensitive_req},
            fresh_observations={p.predicate_id: sensitive_obs},
            at=T_EVAL,
        )
        assert reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE

        transition = apply_reconciliation_transition(
            prior_state=MissionState.READY,
            reconciliation=reconciliation,
        )
        assert transition.new_state == MissionState.DRIFTED
        assert transition.is_drifted is True
        assert transition.explanation is not None

        # Verify explanation ONLY contains predicate ID, strictly omitting sensitive data
        assert str(p.predicate_id) in transition.explanation
        assert "secret_event_99999" not in transition.explanation
        assert "private_calendar_alpha" not in transition.explanation
        assert "Secret Executive Board" not in transition.explanation
        assert "Confidential" not in transition.explanation
        assert "cancelled" not in transition.explanation
