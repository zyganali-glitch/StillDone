"""Tests for Deterministic Bounded Revalidation (Phase P-12.03).

Validates:
- Reads exact previously bound external targets.
- Correctly distinguishes all 6 revalidation outcomes:
  1. TRUE: matches expected and is fresh;
  2. FALSE: contradicts expected and is fresh;
  3. STALE: expired freshness;
  4. NOT_EVALUABLE: missing property or not found;
  5. PROVIDER_ERROR: network / transport / 5xx error;
  6. NOT_RUN: work budget limit reached (partial result).
- Applies bounded per-call work ceiling (max_reads_per_call) with clear partial flag.
- Model proposals and historic receipts rejected fail-closed.
- Zero provider writes, zero approvals consumed (strictly read-only).
- Deterministic proof path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stilldone.adapters.calendar import (
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import ResourceKind, TargetIdentity
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    FreshnessMode,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.planning.contracts import PlannerInput
from stilldone.revalidation import (
    HistoricalReceiptSubstitutionError,
    PlannerRevalidationAuthorityError,
    RevalidationPredicateStatus,
    StandardTargetReader,
    revalidate_mission,
)
from stilldone.verifier.contracts import (
    VerificationObservation,
)


@pytest.fixture
def mission_id() -> MissionId:
    return MissionId.generate()


@pytest.fixture
def target_calendar() -> TargetIdentity:
    return TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_leave_school_001",
        parent_id="c_demo@group.calendar.google.com",
    )


@pytest.fixture
def target_tasks() -> TargetIdentity:
    return TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task_pack_backpacks",
        parent_id="list_demo_tasks",
    )


def test_revalidation_distinguishes_true_and_false(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
) -> None:
    now = datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC)

    pred1 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="start_time",
        operator=PredicateOperator.EQUALS,
        expected_value="2026-10-03T07:30:00+03:00",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred2 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    # Reader returns true for start_time, false for summary (changed externally to "Stay home")
    def mock_reader(target: TargetIdentity, subject: str) -> VerificationObservation:
        obs_val = "2026-10-03T07:30:00+03:00" if subject == "start_time" else "Stay home"
        return VerificationObservation(
            target=target,
            observed_at=now,
            exists=True,
            properties={subject: obs_val},
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
        )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred1, pred2],
        target_map={pred1.predicate_id: target_calendar, pred2.predicate_id: target_calendar},
        target_reader=mock_reader,
        at=now,
    )

    assert result.all_true is False
    assert result.has_false is True
    assert result.writes_performed == 0
    assert result.outcomes[pred1.predicate_id].status == RevalidationPredicateStatus.TRUE
    assert result.outcomes[pred2.predicate_id].status == RevalidationPredicateStatus.FALSE
    assert result.outcomes[pred2.predicate_id].observed_value == "Stay home"


def test_revalidation_distinguishes_stale_and_provider_error(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    target_tasks: TargetIdentity,
) -> None:
    eval_at = datetime(2026, 10, 3, 7, 10, 0, tzinfo=UTC)
    stale_at = eval_at - timedelta(seconds=600)  # 10 minutes ago, exceeds 300s window

    pred_stale = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="start_time",
        operator=PredicateOperator.EQUALS,
        expected_value="2026-10-03T07:30:00+03:00",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_error = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="completed",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    def mock_reader(target: TargetIdentity, subject: str) -> VerificationObservation:
        if target.system == "google_calendar":
            return VerificationObservation(
                target=target,
                observed_at=stale_at,
                exists=True,
                properties={"start_time": "2026-10-03T07:30:00+03:00"},
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
            )
        raise ConnectionError("Google Tasks API 503 Service Unavailable")

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred_stale, pred_error],
        target_map={
            pred_stale.predicate_id: target_calendar,
            pred_error.predicate_id: target_tasks,
        },
        target_reader=mock_reader,
        at=eval_at,
    )

    assert result.has_stale is True
    assert result.has_provider_error is True
    assert result.outcomes[pred_stale.predicate_id].status == RevalidationPredicateStatus.STALE
    assert (
        result.outcomes[pred_error.predicate_id].status
        == RevalidationPredicateStatus.PROVIDER_ERROR
    )
    assert "503" in (result.outcomes[pred_error.predicate_id].error_message or "")


def test_revalidation_distinguishes_not_evaluable(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
) -> None:
    now = datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC)

    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="color_id",  # property absent from observation properties
        operator=PredicateOperator.EQUALS,
        expected_value="blue",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    def mock_reader(target: TargetIdentity, subject: str) -> VerificationObservation:
        return VerificationObservation(
            target=target,
            observed_at=now,
            exists=True,
            properties={"start_time": "2026-10-03T07:30:00+03:00"},
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
        )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        target_map={pred.predicate_id: target_calendar},
        target_reader=mock_reader,
        at=now,
    )

    assert result.outcomes[pred.predicate_id].status == RevalidationPredicateStatus.NOT_EVALUABLE


def test_revalidation_bounded_work_limit_produces_not_run_and_partial(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
) -> None:
    now = datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC)

    preds = [
        DesiredStatePredicate(
            predicate_id=PredicateId.generate(),
            mission_id=mission_id,
            subject=f"field_{i}",
            operator=PredicateOperator.EQUALS,
            expected_value=f"val_{i}",
            freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
            required=True,
        )
        for i in range(5)
    ]
    target_map = {p.predicate_id: target_calendar for p in preds}

    # Set max_reads_per_call = 2
    def mock_reader(target: TargetIdentity, subject: str) -> VerificationObservation:
        return VerificationObservation(
            target=target,
            observed_at=now,
            exists=True,
            properties={subject: "val_match"},
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
        )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=preds,
        target_map=target_map,
        target_reader=mock_reader,
        at=now,
        max_reads_per_call=2,
    )

    assert result.reads_performed == 2
    assert result.predicates_count == 5
    assert result.evaluated_count == 2
    assert result.has_not_run is True
    assert result.is_partial is True
    assert result.outcomes[preds[0].predicate_id].status in (
        RevalidationPredicateStatus.TRUE,
        RevalidationPredicateStatus.FALSE,
    )
    assert result.outcomes[preds[2].predicate_id].status == RevalidationPredicateStatus.NOT_RUN
    assert result.outcomes[preds[3].predicate_id].status == RevalidationPredicateStatus.NOT_RUN
    assert result.outcomes[preds[4].predicate_id].status == RevalidationPredicateStatus.NOT_RUN


def test_historical_observation_replay_rejected_fail_closed(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
) -> None:
    now = datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC)

    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="start_time",
        operator=PredicateOperator.EQUALS,
        expected_value="2026-10-03T07:30:00+03:00",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    historical_obs = VerificationObservation(
        target=target_calendar,
        observed_at=now,
        exists=True,
        properties={"start_time": "2026-10-03T07:30:00+03:00"},
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    # Attempting to return the exact same historical observation object raises error
    def mock_reader(target: TargetIdentity, subject: str) -> VerificationObservation:
        return historical_obs

    with pytest.raises(HistoricalReceiptSubstitutionError, match="Historical observation"):
        revalidate_mission(
            mission_id=mission_id,
            predicates=[pred],
            target_map={pred.predicate_id: target_calendar},
            target_reader=mock_reader,
            at=now,
            historical_observations={pred.predicate_id: historical_obs},
        )


def test_planner_model_proposals_rejected_in_revalidation(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
) -> None:
    planner_input = PlannerInput(intent="Revalidate everything", mission_id=mission_id)

    with pytest.raises(PlannerRevalidationAuthorityError):
        revalidate_mission(
            mission_id=mission_id,
            predicates=planner_input,  # type: ignore[arg-type]
            target_map={},
            target_reader=lambda t, s: None,  # type: ignore[arg-type,return-value]
        )


def test_deterministic_proof_path_with_standard_target_reader(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
) -> None:
    """Deterministic proof path exercising StandardTargetReader with GoogleCalendar adapter."""
    fake_transport = FakeGoogleCalendarTransport()
    cal_id = target_calendar.parent_id or "c_demo@group.calendar.google.com"
    fake_transport.seed_event(
        calendar_id=cal_id,
        event_id=target_calendar.resource_id,
        summary="Verified Event",
        start_time="2026-10-03T09:00:00+03:00",
        end_time="2026-10-03T10:00:00+03:00",
        status="confirmed",
    )

    scope = DemoResourceScope(
        calendar_id=cal_id,
        task_list_id="list_demo_tasks",
    )
    cal_adapter = GoogleCalendarReadAdapter(
        scope=scope,
        transport=fake_transport,
    )

    standard_reader = StandardTargetReader(calendar_read_adapter=cal_adapter)

    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Verified Event",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        target_map={pred.predicate_id: target_calendar},
        target_reader=standard_reader,
    )

    assert result.all_true is True
    assert result.is_still_true is True
    assert result.writes_performed == 0
    assert result.outcomes[pred.predicate_id].status == RevalidationPredicateStatus.TRUE
    assert result.outcomes[pred.predicate_id].observed_value == "Verified Event"
