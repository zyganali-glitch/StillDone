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
from stilldone.verifier.reconciliation import (
    HistoricalObservationSubstitutionError,
    PlannerReconciliationAuthorityError,
    ReconciliationContractValueError,
    ReconciliationDetermination,
    ReconciliationStatus,
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
