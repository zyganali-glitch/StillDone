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
from stilldone.domain.action import ActionContract, ActionType, ResourceKind, TargetIdentity
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
    RevalidationValueError,
    StandardTargetReader,
    revalidate_mission,
)
from stilldone.snapshot import MissionSnapshot
from stilldone.verifier.contracts import (
    VerificationObservation,
    VerifierReadError,
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


@pytest.fixture
def cal_action(mission_id: MissionId, target_calendar: TargetIdentity) -> ActionContract:
    return ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target_calendar,
        parameters={},
    )


@pytest.fixture
def tasks_action(mission_id: MissionId, target_tasks: TargetIdentity) -> ActionContract:
    return ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=target_tasks,
        parameters={},
    )


def test_revalidation_distinguishes_true_and_false(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
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
        actions=[cal_action],
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
    cal_action: ActionContract,
    tasks_action: ActionContract,
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
        actions=[cal_action, tasks_action],
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
    cal_action: ActionContract,
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
        actions=[cal_action],
        at=now,
    )

    assert result.outcomes[pred.predicate_id].status == RevalidationPredicateStatus.NOT_EVALUABLE


def test_revalidation_bounded_work_limit_produces_not_run_and_partial(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
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
        actions=[cal_action],
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
    cal_action: ActionContract,
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
            actions=[cal_action],
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
    cal_action: ActionContract,
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
        actions=[cal_action],
    )

    assert result.all_true is True
    assert result.is_still_true is True
    assert result.writes_performed == 0
    assert result.outcomes[pred.predicate_id].status == RevalidationPredicateStatus.TRUE
    assert result.outcomes[pred.predicate_id].observed_value == "Verified Event"


def test_revalidation_empty_predicates_fails_closed(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
) -> None:
    """Vacuous revalidation with empty predicates is rejected fail-closed."""
    from stilldone.revalidation import RevalidationValueError

    with pytest.raises(RevalidationValueError, match="zero predicates"):
        revalidate_mission(
            mission_id=mission_id,
            predicates=[],
            target_map={},
            target_reader=lambda t, s: None,  # type: ignore[arg-type,return-value]
        )


def test_revalidation_foreign_target_fails_closed(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """When actions are provided, target_map must reference targets belonging to those actions."""
    from stilldone.domain.action import ActionContract, ActionId, ActionType, NormalizedParameters
    from stilldone.revalidation import RevalidationValueError

    mission_action = ActionContract(
        action_id=ActionId.generate(),
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target_calendar,
        parameters=NormalizedParameters.from_dict({}),
    )

    foreign_target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_foreign_123",
        parent_id="foreign_cal",
    )

    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Verified Event",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    with pytest.raises(RevalidationValueError, match="does not match any action target"):
        revalidate_mission(
            mission_id=mission_id,
            predicates=[pred],
            target_map={pred.predicate_id: foreign_target},
            target_reader=lambda t, s: None,  # type: ignore[arg-type,return-value]
            actions=[mission_action],
        )


def test_revalidation_redacts_error_message(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Provider error messages must have secrets and emails redacted."""
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Secret Meeting",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    def leaking_reader(target: TargetIdentity, subject: str) -> None:
        raise RuntimeError("Failed to contact user@example.com with bearer secret_token_xyz")

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        target_map={pred.predicate_id: target_calendar},
        target_reader=leaking_reader,  # type: ignore[arg-type]
        actions=[cal_action],
    )

    assert result.all_true is False
    outcome = result.outcomes[pred.predicate_id]
    assert outcome.status == RevalidationPredicateStatus.PROVIDER_ERROR
    assert outcome.error_message is not None
    assert "user@example.com" not in outcome.error_message
    assert "secret_token_xyz" not in outcome.error_message
    assert "[REDACTED_EMAIL]" in outcome.error_message
    assert "[REDACTED_SECRET]" in outcome.error_message


def test_revalidation_requires_authoritative_actions_or_snapshot_fails_closed(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
) -> None:
    """Passing actions=None and snapshot=None fails closed to prevent unauthenticated bypass."""
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    with pytest.raises(RevalidationValueError, match="authoritative mission context"):
        revalidate_mission(
            mission_id=mission_id,
            predicates=[pred],
            target_map={pred.predicate_id: target_calendar},
            target_reader=lambda t, s: None,  # type: ignore[arg-type,return-value]
            actions=None,
            snapshot=None,
        )


def test_revalidation_mismatched_observation_target_fails_closed(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Reader returning an observation for a mismatched target identity fails closed."""
    now = datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    wrong_target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="wrong_event_id",
        parent_id=target_calendar.parent_id,
    )

    def wrong_target_reader(target: TargetIdentity, subject: str) -> VerificationObservation:
        return VerificationObservation(
            target=wrong_target,
            observed_at=now,
            exists=True,
            properties={subject: "Leave for school"},
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
        )

    with pytest.raises(RevalidationValueError, match="does not match expected target"):
        revalidate_mission(
            mission_id=mission_id,
            predicates=[pred],
            target_map={pred.predicate_id: target_calendar},
            target_reader=wrong_target_reader,
            actions=[cal_action],
            at=now,
        )


def test_revalidation_synthetic_reader_live_provenance_rejected(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Synthetic callback reader cannot assert LIVE_GOOGLE provenance."""
    now = datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    def fake_live_reader(target: TargetIdentity, subject: str) -> VerificationObservation:
        return VerificationObservation(
            target=target,
            observed_at=now,
            exists=True,
            properties={subject: "Leave for school"},
            provenance=EvidenceProvenance.LIVE_GOOGLE,
        )

    with pytest.raises(RevalidationValueError, match="cannot assert live provenance"):
        revalidate_mission(
            mission_id=mission_id,
            predicates=[pred],
            target_map={pred.predicate_id: target_calendar},
            target_reader=fake_live_reader,
            actions=[cal_action],
            at=now,
        )


def test_revalidation_unsupported_provider_system_rejected(
    mission_id: MissionId,
) -> None:
    """Target system outside supported providers fails closed."""
    unsupported_target = TargetIdentity(
        system="unsupported_external_crm",
        resource_kind=ResourceKind.TASK,
        resource_id="item_123",
        parent_id="board_abc",
    )
    unsupported_action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=unsupported_target,
        parameters={},
    )
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="done",
        freshness=FreshnessContract(mode=FreshnessMode.CURRENT),
        required=True,
    )
    with pytest.raises(RevalidationValueError, match="not a supported provider"):
        revalidate_mission(
            mission_id=mission_id,
            predicates=[pred],
            target_map={pred.predicate_id: unsupported_target},
            target_reader=lambda t, s: None,  # type: ignore[arg-type,return-value]
            actions=[unsupported_action],
        )


def test_revalidation_target_map_contradicting_snapshot_binding_rejected(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Caller target_map override contradicting canonical snapshot.predicate_bindings
    is rejected with RevalidationValueError.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.lifecycle import MissionState
    from stilldone.domain.mission import MissionContract
    from stilldone.snapshot import create_mission_snapshot

    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    target2 = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="different_event_999",
        parent_id=target_calendar.parent_id,
    )
    action2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target2,
        parameters={},
    )
    binding = PredicateTargetBinding.create(
        predicate_id=pred.predicate_id,
        mission_id=mission_id,
        target=target_calendar,
    )
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=MissionContract.create("Reval contract", mission_id=mission_id),
        desired_state=[pred],
        actions=[cal_action, action2],
        predicate_bindings=[binding],
    )

    with pytest.raises(RevalidationValueError, match="contradicts canonical snapshot binding"):
        revalidate_mission(
            mission_id=mission_id,
            predicates=[pred],
            target_map={pred.predicate_id: target2},
            target_reader=lambda t, s: None,  # type: ignore[arg-type,return-value]
            snapshot=snapshot,
        )


def test_revalidation_synthetic_callback_marks_non_certifying(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """revalidate_mission() with synthetic/reader callback or caller actions sets
    is_certifying_live_authority=False fail-closed.
    """
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    obs = VerificationObservation(
        target=target_calendar,
        observed_at=now,
        exists=True,
        properties={"summary": "Leave for school"},
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        actions=[cal_action],
        target_map={pred.predicate_id: target_calendar},
        target_reader=lambda t, s: obs,
        at=now,
    )
    assert result.all_true is True
    assert result.is_certifying_live_authority is False


def test_revalidation_all_error_outcomes_marks_non_certifying(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Revalidation where all outcomes are PROVIDER_ERROR
    sets is_certifying_live_authority=False.
    """
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    def failing_reader(t: TargetIdentity, s: str) -> VerificationObservation:
        raise VerifierReadError("Calendar API 503 Service Unavailable")

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        actions=[cal_action],
        target_map={pred.predicate_id: target_calendar},
        target_reader=failing_reader,
        at=now,
    )
    assert result.all_true is False
    assert result.has_provider_error is True
    assert result.is_certifying_live_authority is False


def test_revalidation_all_not_run_outcomes_marks_non_certifying(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Revalidation where budget prevents execution (NOT_RUN)
    sets is_certifying_live_authority=False.
    """
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    pred1 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred2 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="confirmed",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    obs = VerificationObservation(
        target=target_calendar,
        observed_at=now,
        exists=True,
        properties={"summary": "Leave for school", "status": "confirmed"},
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred1, pred2],
        actions=[cal_action],
        target_map={
            pred1.predicate_id: target_calendar,
            pred2.predicate_id: target_calendar,
        },
        target_reader=lambda t, s: obs,
        max_reads_per_call=1,
        at=now,
    )
    assert result.has_not_run is True
    assert result.is_certifying_live_authority is False


def test_revalidation_all_false_outcomes_marks_non_certifying(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Revalidation where all outcomes evaluate to FALSE sets is_certifying_live_authority=False."""
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    obs = VerificationObservation(
        target=target_calendar,
        observed_at=now,
        exists=True,
        properties={"summary": "Completely Different Summary"},
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        actions=[cal_action],
        target_map={pred.predicate_id: target_calendar},
        target_reader=lambda t, s: obs,
        at=now,
    )
    assert result.all_true is False
    assert result.has_false is True
    assert result.is_certifying_live_authority is False


def test_revalidation_mixed_outcomes_marks_non_certifying(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Revalidation with mixed outcomes (one TRUE, one FALSE)
    sets is_certifying_live_authority=False.
    """
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    pred1 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred2 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="confirmed",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    def reader(t: TargetIdentity, s: str) -> VerificationObservation:
        return VerificationObservation(
            target=t,
            observed_at=now,
            exists=True,
            properties={"summary": "Leave for school", "status": "cancelled"},
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
        )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred1, pred2],
        actions=[cal_action],
        target_map={
            pred1.predicate_id: target_calendar,
            pred2.predicate_id: target_calendar,
        },
        target_reader=reader,
        at=now,
    )
    assert result.all_true is False
    assert result.has_false is True
    assert result.is_certifying_live_authority is False


def test_revalidation_unpersisted_or_empty_snapshot_marks_non_certifying(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Caller-provided snapshot lacking snapshot_id or predicate_bindings fails
    is_certifying_live_authority check fail-closed.
    """
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    obs = VerificationObservation(
        target=target_calendar,
        observed_at=now,
        exists=True,
        properties={"summary": "Leave for school"},
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    class DummyUnpersistedSnapshot:
        snapshot_id = ""
        predicate_bindings = ()

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        actions=[cal_action],
        target_map={pred.predicate_id: target_calendar},
        target_reader=lambda t, s: obs,
        snapshot=DummyUnpersistedSnapshot(),
        at=now,
    )
    assert result.all_true is True
    assert result.is_certifying_live_authority is False


def test_revalidation_legitimate_standard_reader_live_provenance_certifies(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """StandardTargetReader backed by MockLiveTransport with DRAFT snapshot computes
    predicate truth (all_true=True) but strictly rejects live authority certification
    (is_certifying_live_authority=False).
    """
    from typing import Any

    from stilldone.adapters.calendar import CalendarTransportEvent, GoogleCalendarReadAdapter
    from stilldone.demo_isolation import DemoResourceScope
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.lifecycle import MissionState
    from stilldone.domain.mission import MissionContract
    from stilldone.snapshot import create_mission_snapshot

    now = datetime.now(tz=UTC)
    cal_id = target_calendar.parent_id or "c_demo@group.calendar.google.com"

    class MockLiveTransport:
        def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
            return CalendarTransportEvent(
                id=event_id,
                etag="etag_live_123",
                summary="Leave for school",
                start_time="2026-10-03T07:30:00+03:00",
                end_time="2026-10-03T08:00:00+03:00",
                all_day=False,
                status="confirmed",
            )

        def update_event(
            self,
            calendar_id: str,
            event_id: str,
            payload: dict[str, Any],
            if_match: str,
            send_updates: str = "none",
        ) -> CalendarTransportEvent:
            raise NotImplementedError()

    scope = DemoResourceScope(calendar_id=cal_id, task_list_id="list_demo")
    adapter = GoogleCalendarReadAdapter(scope=scope, transport=MockLiveTransport())
    standard_reader = StandardTargetReader(calendar_read_adapter=adapter)

    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    binding = PredicateTargetBinding.create(
        predicate_id=pred.predicate_id,
        mission_id=mission_id,
        target=target_calendar,
    )
    snap = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=MissionContract.create("Live Test Contract", mission_id=mission_id),
        desired_state=[pred],
        actions=[cal_action],
        predicate_bindings=[binding],
        created_at=now,
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        snapshot=snap,
        target_reader=standard_reader,
    )

    assert result.all_true is True
    assert result.is_certifying_live_authority is False


def test_revalidation_forged_live_provenance_rejected(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Reader claiming LIVE_GOOGLE without trusted live capability fails closed."""
    now = datetime.now(tz=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    def forged_callback(t: TargetIdentity, s: str) -> VerificationObservation:
        return VerificationObservation(
            target=t,
            observed_at=now,
            exists=True,
            properties={"summary": "Leave for school"},
            provenance=EvidenceProvenance.LIVE_GOOGLE,
        )

    with pytest.raises(RevalidationValueError, match="cannot assert live provenance"):
        revalidate_mission(
            mission_id=mission_id,
            predicates=[pred],
            actions=[cal_action],
            target_map={pred.predicate_id: target_calendar},
            target_reader=forged_callback,
            at=now,
        )


def test_revalidation_draft_snapshot_fails_live_certification(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """A DRAFT snapshot cannot certify current verified READY state."""
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.lifecycle import MissionState
    from stilldone.domain.mission import MissionContract
    from stilldone.snapshot import create_mission_snapshot

    now = datetime.now(tz=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    binding = PredicateTargetBinding.create(
        predicate_id=pred.predicate_id,
        mission_id=mission_id,
        target=target_calendar,
    )
    snap = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=MissionContract.create("Draft Contract", mission_id=mission_id),
        desired_state=[pred],
        actions=[cal_action],
        predicate_bindings=[binding],
        created_at=now,
    )
    obs = VerificationObservation(
        target=target_calendar,
        observed_at=now,
        exists=True,
        properties={"summary": "Leave for school"},
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        snapshot=snap,
        target_reader=lambda t, s: obs,
        at=now,
    )
    assert result.all_true is True
    assert result.is_certifying_live_authority is False


def test_revalidation_unpersisted_ready_snapshot_fails_live_certification(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """An unpersisted READY snapshot (is_persisted=False) cannot certify live authority."""
    from stilldone.approval_consumption import ApprovalConsumptionRecord, ApprovalUsageStatus
    from stilldone.domain.authority import ApprovalId, BindingHash
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.execution import AttemptId, ExecutionAttempt, IdempotencyKey
    from stilldone.domain.lifecycle import MissionState
    from stilldone.domain.mission import MissionContract
    from stilldone.evidence import EvidenceId
    from stilldone.execution.state import (
        ActionExecutionStatus,
        ProviderExecutionResult,
        StepExecutionRecord,
    )
    from stilldone.snapshot import MissionSnapshot

    now = datetime.now(tz=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    binding = PredicateTargetBinding.create(
        predicate_id=pred.predicate_id,
        mission_id=mission_id,
        target=target_calendar,
    )
    contract = MissionContract.create("Ready Contract", mission_id=mission_id)
    attempt = ExecutionAttempt(
        action_id=cal_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
        attempt_id=AttemptId.generate(),
    )
    provider_res = ProviderExecutionResult(
        action_type=cal_action.action_type,
        success=True,
        status_name="SUCCESS",
        writes_performed=0,
        captured_at=now,
        details={},
    )
    step_rec = StepExecutionRecord(
        action_id=cal_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=attempt,
        provider_result=provider_res,
    )
    appr = ApprovalConsumptionRecord(
        approval_id=ApprovalId.generate(),
        mission_id=mission_id,
        action_id=cal_action.action_id,
        binding_hash=BindingHash("0" * 64),
        status=ApprovalUsageStatus.CONSUMED,
        consumed_at=now,
        attempt_number=1,
        reason="Approved",
    )
    unpersisted_snap = MissionSnapshot(
        snapshot_id="snap_unpersisted_123",
        snapshot_version="v1",
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=(pred,),
        actions=(cal_action,),
        action_dependencies={cal_action.action_id: ()},
        step_records={cal_action.action_id: step_rec},
        pending_approvals=(),
        consumed_approvals=(appr,),
        execution_attempts=(attempt,),
        evidence_ids=(EvidenceId("a" * 64),),
        created_at=now,
        predicate_bindings=(binding,),
        is_persisted=False,
    )
    obs = VerificationObservation(
        target=target_calendar,
        observed_at=now,
        exists=True,
        properties={"summary": "Leave for school"},
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        snapshot=unpersisted_snap,
        target_reader=lambda t, s: obs,
        at=now,
    )
    assert result.all_true is True
    assert result.is_certifying_live_authority is False


def test_revalidation_genuine_fixture_read_success_without_certification(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Fixture reads compute predicate truth successfully (all_true=True)
    without granting live authority certification (is_certifying_live_authority=False).
    """
    now = datetime.now(tz=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    fixture_obs = VerificationObservation(
        target=target_calendar,
        observed_at=now,
        exists=True,
        properties={"summary": "Leave for school"},
        provenance=EvidenceProvenance.FIXTURE,
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        actions=[cal_action],
        target_map={pred.predicate_id: target_calendar},
        target_reader=lambda t, s: fixture_obs,
        at=now,
    )
    assert result.all_true is True
    assert result.is_still_true is True
    assert result.is_certifying_live_authority is False


def _make_dummy_ready_snapshot(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
    pred: DesiredStatePredicate,
    *,
    is_persisted: bool = False,
    now: datetime | None = None,
) -> MissionSnapshot:
    from stilldone.approval_consumption import ApprovalConsumptionRecord, ApprovalUsageStatus
    from stilldone.domain.authority import ApprovalId, BindingHash
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.execution import AttemptId, ExecutionAttempt, IdempotencyKey
    from stilldone.domain.lifecycle import MissionState
    from stilldone.domain.mission import MissionContract
    from stilldone.evidence import EvidenceId
    from stilldone.execution.state import (
        ActionExecutionStatus,
        ProviderExecutionResult,
        StepExecutionRecord,
    )

    eval_now = now or datetime.now(tz=UTC)
    binding = PredicateTargetBinding.create(
        predicate_id=pred.predicate_id,
        mission_id=mission_id,
        target=target_calendar,
    )
    contract = MissionContract.create("Ready Snapshot Contract", mission_id=mission_id)
    attempt = ExecutionAttempt(
        action_id=cal_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=eval_now,
        attempt_id=AttemptId.generate(),
    )
    provider_res = ProviderExecutionResult(
        action_type=cal_action.action_type,
        success=True,
        status_name="SUCCESS",
        writes_performed=0,
        captured_at=eval_now,
        details={},
    )
    step_rec = StepExecutionRecord(
        action_id=cal_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=attempt,
        provider_result=provider_res,
    )
    appr = ApprovalConsumptionRecord(
        approval_id=ApprovalId.generate(),
        mission_id=mission_id,
        action_id=cal_action.action_id,
        binding_hash=BindingHash("0" * 64),
        status=ApprovalUsageStatus.CONSUMED,
        consumed_at=eval_now,
        attempt_number=1,
        reason="Approved",
    )
    return MissionSnapshot(
        snapshot_id=f"snap_{mission_id}_{int(eval_now.timestamp())}",
        snapshot_version="v1",
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=(pred,),
        actions=(cal_action,),
        action_dependencies={cal_action.action_id: ()},
        step_records={cal_action.action_id: step_rec},
        pending_approvals=(),
        consumed_approvals=(appr,),
        execution_attempts=(attempt,),
        evidence_ids=(EvidenceId("a" * 64),),
        created_at=eval_now,
        predicate_bindings=(binding,),
        is_persisted=is_persisted,
    )


def test_custom_fake_transport_with_capability_flag_remains_non_certifying(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Fake transport without mock/fake declaring capability remains non-certifying."""
    from typing import Any

    from stilldone.adapters.calendar import CalendarTransportEvent, GoogleCalendarReadAdapter
    from stilldone.demo_isolation import DemoResourceScope

    now = datetime.now(tz=UTC)
    cal_id = target_calendar.parent_id or "c_demo@group.calendar.google.com"

    class CustomCloudProductionGateway:
        is_live_network_capable = True

        def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
            return CalendarTransportEvent(
                id=event_id,
                etag="etag_custom_gateway_1",
                summary="Leave for school",
                start_time="2026-10-03T07:30:00+03:00",
                end_time="2026-10-03T08:00:00+03:00",
                all_day=False,
                status="confirmed",
            )

        def update_event(
            self,
            calendar_id: str,
            event_id: str,
            payload: dict[str, Any],
            if_match: str,
            send_updates: str = "none",
        ) -> CalendarTransportEvent:
            raise NotImplementedError()

    scope = DemoResourceScope(calendar_id=cal_id, task_list_id="list_demo")
    adapter = GoogleCalendarReadAdapter(scope=scope, transport=CustomCloudProductionGateway())
    reader = StandardTargetReader(calendar_read_adapter=adapter)

    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    snap = _make_dummy_ready_snapshot(
        mission_id, target_calendar, cal_action, pred, now=now, is_persisted=True
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        snapshot=snap,
        target_reader=reader,
    )

    assert result.all_true is True
    assert result.is_certifying_live_authority is False


def test_caller_created_ready_snapshot_declaring_is_persisted_cannot_certify(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Caller-created READY snapshot setting is_persisted=True cannot confer live certification."""
    now = datetime.now(tz=UTC)
    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    snap = _make_dummy_ready_snapshot(
        mission_id, target_calendar, cal_action, pred, now=now, is_persisted=True
    )
    obs = VerificationObservation(
        target=target_calendar,
        observed_at=now,
        exists=True,
        properties={"summary": "Leave for school"},
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        snapshot=snap,
        target_reader=lambda t, s: obs,
        at=now,
    )
    assert result.all_true is True
    assert result.is_certifying_live_authority is False


def test_fixture_observation_falsely_labeled_live_google_cannot_certify(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """A fixture observation claiming LIVE_GOOGLE cannot confer live certification."""
    from typing import Any

    from stilldone.adapters.calendar import CalendarTransportEvent, GoogleCalendarReadAdapter
    from stilldone.demo_isolation import DemoResourceScope

    now = datetime.now(tz=UTC)
    cal_id = target_calendar.parent_id or "c_demo@group.calendar.google.com"

    class SyntheticCarrierTransport:
        def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
            return CalendarTransportEvent(
                id=event_id,
                etag="etag_carrier_1",
                summary="Leave for school",
                start_time="2026-10-03T07:30:00+03:00",
                end_time="2026-10-03T08:00:00+03:00",
                all_day=False,
                status="confirmed",
            )

        def update_event(
            self,
            calendar_id: str,
            event_id: str,
            payload: dict[str, Any],
            if_match: str,
            send_updates: str = "none",
        ) -> CalendarTransportEvent:
            raise NotImplementedError()

    scope = DemoResourceScope(calendar_id=cal_id, task_list_id="list_demo")
    adapter = GoogleCalendarReadAdapter(scope=scope, transport=SyntheticCarrierTransport())
    reader = StandardTargetReader(calendar_read_adapter=adapter)

    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    snap = _make_dummy_ready_snapshot(
        mission_id, target_calendar, cal_action, pred, now=now, is_persisted=True
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        snapshot=snap,
        target_reader=reader,
    )
    assert result.all_true is True
    assert result.is_certifying_live_authority is False


def test_official_production_transport_identity_alone_cannot_certify(
    mission_id: MissionId,
    target_calendar: TargetIdentity,
    cal_action: ActionContract,
) -> None:
    """Official transport class identity alone without verified network execution cannot certify."""
    from unittest.mock import MagicMock

    from stilldone.adapters.calendar import (
        GoogleApiClientCalendarTransport,
        GoogleCalendarReadAdapter,
    )
    from stilldone.demo_isolation import DemoResourceScope

    now = datetime.now(tz=UTC)
    cal_id = target_calendar.parent_id or "c_demo@group.calendar.google.com"

    mock_service = MagicMock()
    mock_service.events().get().execute.return_value = {
        "id": target_calendar.resource_id,
        "etag": '"etag_google_client_1"',
        "summary": "Leave for school",
        "status": "confirmed",
        "start": {"dateTime": "2026-10-03T07:30:00+03:00"},
        "end": {"dateTime": "2026-10-03T08:00:00+03:00"},
    }
    prod_transport = GoogleApiClientCalendarTransport(service=mock_service)
    scope = DemoResourceScope(calendar_id=cal_id, task_list_id="list_demo")
    adapter = GoogleCalendarReadAdapter(scope=scope, transport=prod_transport)
    reader = StandardTargetReader(calendar_read_adapter=adapter)

    pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    snap = _make_dummy_ready_snapshot(
        mission_id, target_calendar, cal_action, pred, now=now, is_persisted=True
    )

    result = revalidate_mission(
        mission_id=mission_id,
        predicates=[pred],
        snapshot=snap,
        target_reader=reader,
    )
    assert result.all_true is True
    assert result.is_certifying_live_authority is False
