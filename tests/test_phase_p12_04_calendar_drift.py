"""Tests for External-Change Drift Detection on Google Calendar (Phase P-12.04).

Validates:
- Compares fresh independently observed Calendar state against persisted desired state.
- Detects time, summary, status, and availability changes.
- Preserves exact event and calendar identity; never matches events by title alone.
- Legitimate persisted READY mission transitions to DRIFTED through canonical lifecycle rules.
- Does NOT fabricate a READY predecessor solely to demonstrate drift (non-READY rejected).
- Errors and stale reads do NOT masquerade as confirmed drift (fail closed / inconclusive).
- Zero Calendar writes or new approval consumption (strictly read-only).
- Proves stable state, changed state, missing event, stale read, wrong event, API failure,
  and repeated revalidation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stilldone.adapters.calendar import (
    CalendarTransportError,
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
from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.drift import (
    DriftTargetMismatchError,
    detect_calendar_drift,
    record_drift_in_snapshot,
)
from stilldone.evidence import EvidenceId
from stilldone.execution.state import (
    ActionExecutionStatus,
    ProviderExecutionResult,
    StepExecutionRecord,
)
from stilldone.snapshot import (
    DurableSnapshotRepository,
    MissionSnapshot,
    create_mission_snapshot,
)
from stilldone.verifier.reconciliation import (
    ReconciliationLifecycleError,
    ReconciliationStatus,
)


@pytest.fixture
def mission_id() -> MissionId:
    return MissionId.generate()


@pytest.fixture
def cal_target() -> TargetIdentity:
    return TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_school_departure_001",
        parent_id="c_demo@group.calendar.google.com",
    )


@pytest.fixture
def demo_scope(cal_target: TargetIdentity) -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=cal_target.parent_id or "c_demo@group.calendar.google.com",
        task_list_id="list_demo_tasks",
    )


def _make_ready_snapshot(
    mission_id: MissionId,
    target: TargetIdentity,
    *,
    expected_summary: str = "Leave for school",
    expected_start: str = "2026-10-03T07:30:00+03:00",
    expected_status: str = "confirmed",
    state: MissionState = MissionState.READY,
) -> tuple[MissionSnapshot, DesiredStatePredicate, DesiredStatePredicate]:
    pred_summary = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value=expected_summary,
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_start = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="start_time",
        operator=PredicateOperator.EQUALS,
        expected_value=expected_start,
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target,
        parameters={},
    )

    contract = MissionContract.create(
        text="Ensure departure calendar is verified",
        mission_id=mission_id,
        created_at=datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC),
    )

    step_records = None
    execution_attempts = None
    evidence_ids = None
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    if state == MissionState.READY:
        attempt = ExecutionAttempt(
            action_id=action.action_id,
            idempotency_key=IdempotencyKey.generate(),
            attempt_number=1,
            started_at=now,
        )
        provider_result = ProviderExecutionResult(
            action_type=action.action_type,
            success=True,
            status_name="READ_OK",
            writes_performed=0,
            captured_at=now,
        )
        step_rec = StepExecutionRecord(
            action_id=action.action_id,
            status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
            attempt=attempt,
            provider_result=provider_result,
        )
        step_records = {action.action_id: step_rec}
        execution_attempts = [attempt]
        evidence_ids = [EvidenceId("e" * 64)]

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=state,
        contract=contract,
        desired_state=(pred_summary, pred_start),
        actions=(action,),
        step_records=step_records,
        execution_attempts=execution_attempts,
        evidence_ids=evidence_ids,
        created_at=now,
    )
    return snapshot, pred_summary, pred_start


def test_calendar_stable_state_remains_ready(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Stable state: calendar event matches desired state; mission remains READY."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Leave for school",
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is False
    assert result.is_inconclusive is False
    assert result.prior_state == MissionState.READY
    assert result.new_state == MissionState.READY
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.STILL_TRUE
    assert fake_transport.writes_count == 0  # Read-only verification


def test_calendar_changed_summary_detects_drift_and_transitions(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
    tmp_path: Path,
) -> None:
    """Changed state: external event summary changed to 'Stay home'; transitions to DRIFTED."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Stay home",  # Changed externally!
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, pred_summary, _ = _make_ready_snapshot(mission_id, cal_target)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is True
    assert result.is_inconclusive is False
    assert result.prior_state == MissionState.READY
    assert result.new_state == MissionState.DRIFTED
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE
    assert pred_summary.predicate_id in result.reconciliation.drifted_predicate_ids

    # Persist in durable ledger-backed repository
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    ledger = DurableFileLedger(tmp_path / "change_summary.ledger")
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=snapshot.contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    for act in snapshot.actions:
        ledger.append_action(
            ActionRecord(
                action_id=act.action_id,
                mission_id=mission_id,
                action=act,
                approval_id=None,
                created_at=now,
            )
        )
    for p in snapshot.desired_state:
        verif_ev = EvidenceRecord.create(
            action_id=snapshot.actions[0].action_id,
            mission_id=mission_id,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
                observed_at=now,
            ),
            payload={
                "evidence_type": "PREDICATE_EVALUATION",
                "predicate_id": str(p.predicate_id),
                "truth": "TRUE",
                "is_true": True,
                "observations": {
                    "summary": "Leave for school",
                    "start_time": "2026-10-03T07:30:00+03:00",
                },
            },
            created_at=now,
        )
        ledger.append_evidence(verif_ev)
    ev_recs = tuple(ledger.get_evidence_for_mission(mission_id))
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=[e.evidence_id for e in ev_recs],
        created_at=now,
    )
    ledger.update_mission_state(
        mission_id=mission_id,
        new_state=MissionState.READY,
        updated_at=now,
        snapshot_projection=snapshot.to_dict(),
    )

    repo = DurableSnapshotRepository(storage_path=str(tmp_path / "snaps"), ledger=ledger)
    repo.save_snapshot(snapshot)
    drifted_snap = record_drift_in_snapshot(repo, snapshot, result)
    assert drifted_snap is not None
    assert drifted_snap.state == MissionState.DRIFTED
    loaded = repo.load_snapshot(mission_id)
    assert loaded.state == MissionState.DRIFTED


def test_calendar_changed_start_time_detects_drift(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Changed state: external start_time shifted by 1 hour; transitions to DRIFTED."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Leave for school",
        start_time="2026-10-03T08:30:00+03:00",  # Shifted from 07:30 to 08:30
        end_time="2026-10-03T09:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, pred_start = _make_ready_snapshot(mission_id, cal_target)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is True
    assert result.new_state == MissionState.DRIFTED
    assert result.reconciliation is not None
    assert pred_start.predicate_id in result.reconciliation.drifted_predicate_ids


def test_calendar_missing_event_404_detects_drift(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Missing event: external event deleted (404); desired state contradicted -> DRIFTED."""
    fake_transport = FakeGoogleCalendarTransport()
    # No event seeded => transport returns 404 / NOT_FOUND
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is True
    assert result.new_state == MissionState.DRIFTED
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE


def test_calendar_stale_read_is_inconclusive_no_false_drift(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Stale read: observation expired relative to eval_at; fails closed as inconclusive."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Different Event",
        start_time="2026-10-03T07:30:00+03:00",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    # Evaluate at a point far in future (10 hours later) so fresh read-back is stale
    future_time = datetime.now(UTC) + timedelta(hours=10)
    result = detect_calendar_drift(
        snapshot=snapshot,
        calendar_adapter=adapter,
        eval_at=future_time,
    )

    # Stale read MUST NOT masquerade as confirmed drift!
    assert result.is_drifted is False
    assert result.is_inconclusive is True
    assert result.new_state == MissionState.READY  # Remains in prior state


def test_calendar_api_failure_is_inconclusive_no_false_drift(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API failure: 503 error during read; inconclusive, remains READY without false drift."""
    fake_transport = FakeGoogleCalendarTransport()
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    def failing_get_event(*args: object, **kwargs: object) -> None:
        raise CalendarTransportError("503 Service Unavailable", status_code=503)

    monkeypatch.setattr(fake_transport, "get_event", failing_get_event)

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert result.is_drifted is False
    assert result.is_inconclusive is True
    assert result.new_state == MissionState.READY
    assert "provider" in (result.error_message or "").lower()


def test_calendar_wrong_event_or_target_mismatch_fails_closed(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Wrong event or title-only match attempt fails closed."""
    fake_transport = FakeGoogleCalendarTransport()
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    wrong_target = TargetIdentity(
        system="google_tasks",  # Mismatched system
        resource_kind=ResourceKind.TASK,
        resource_id="wrong_id",
        parent_id="wrong_list",
    )

    with pytest.raises(DriftTargetMismatchError):
        detect_calendar_drift(
            snapshot=snapshot,
            calendar_adapter=adapter,
            target=wrong_target,
        )


def test_calendar_non_ready_predecessor_rejected_fail_closed(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Non-READY predecessor rejected: cannot fabricate READY to demonstrate drift."""
    fake_transport = FakeGoogleCalendarTransport()
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    # Mission in VERIFYING state, never established as READY
    unready_snapshot, _, _ = _make_ready_snapshot(
        mission_id, cal_target, state=MissionState.VERIFYING
    )

    with pytest.raises(
        ReconciliationLifecycleError, match="Drift detection is only permitted from READY"
    ):
        detect_calendar_drift(snapshot=unready_snapshot, calendar_adapter=adapter)


def test_calendar_repeated_revalidation_is_idempotent(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Repeated revalidation on stable state consistently yields STILL_TRUE / READY."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Leave for school",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    res1 = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    res2 = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    assert res1.new_state == MissionState.READY
    assert res2.new_state == MissionState.READY
    assert res1.is_drifted is False
    assert res2.is_drifted is False


def test_calendar_drift_mixed_provider_mission(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Mixed provider mission: Calendar drift detection only evaluates calendar predicates."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Leave for school",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    cal_pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Leave for school",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    # Tasks predicate in same mission
    tasks_pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="title",
        operator=PredicateOperator.EQUALS,
        expected_value="Pack lunch",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    cal_action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target,
        parameters={},
    )
    tasks_target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task_lunch_001",
        parent_id="list_demo_tasks",
    )
    tasks_action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_CREATE,
        target=tasks_target,
        parameters={"title": "Pack lunch"},
    )

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    att1 = ExecutionAttempt(
        action_id=cal_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr1 = ProviderExecutionResult(
        action_type=cal_action.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    step1 = StepExecutionRecord(
        action_id=cal_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att1,
        provider_result=pr1,
    )

    att2 = ExecutionAttempt(
        action_id=tasks_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr2 = ProviderExecutionResult(
        action_type=tasks_action.action_type,
        success=True,
        status_name="CREATED",
        writes_performed=1,
        captured_at=now,
    )
    step2 = StepExecutionRecord(
        action_id=tasks_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att2,
        provider_result=pr2,
    )

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=MissionContract.create("Mixed mission", mission_id=mission_id),
        desired_state=(cal_pred, tasks_pred),
        actions=(cal_action, tasks_action),
        step_records={cal_action.action_id: step1, tasks_action.action_id: step2},
        execution_attempts=(att1, att2),
        evidence_ids=(EvidenceId("e" * 64),),
        predicate_bindings={
            cal_pred.predicate_id: cal_target,
            tasks_pred.predicate_id: tasks_target,
        },
        created_at=now,
    )

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)
    assert result.is_drifted is False
    assert result.new_state == MissionState.READY
    assert result.is_partial is True
    assert result.is_whole_mission is False
    assert result.scope == "google_calendar"


def test_calendar_drift_ambiguous_targets_fails_closed(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Ambiguous calendar actions without target fails closed with DriftTargetMismatchError."""
    fake_transport = FakeGoogleCalendarTransport()
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    cal_pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Event 1",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    target2 = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_school_departure_002",
        parent_id=cal_target.parent_id,
    )

    action1 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target,
        parameters={},
    )
    action2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target2,
        parameters={},
    )

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    att1 = ExecutionAttempt(
        action_id=action1.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr1 = ProviderExecutionResult(
        action_type=action1.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    step1 = StepExecutionRecord(
        action_id=action1.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att1,
        provider_result=pr1,
    )
    att2 = ExecutionAttempt(
        action_id=action2.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr2 = ProviderExecutionResult(
        action_type=action2.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    step2 = StepExecutionRecord(
        action_id=action2.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att2,
        provider_result=pr2,
    )

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=MissionContract.create("Multi-calendar", mission_id=mission_id),
        desired_state=(cal_pred,),
        actions=(action1, action2),
        step_records={action1.action_id: step1, action2.action_id: step2},
        execution_attempts=(att1, att2),
        evidence_ids=(EvidenceId("e" * 64),),
        created_at=now,
    )

    with pytest.raises(DriftTargetMismatchError, match="Ambiguous target for predicate"):
        detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)


def test_record_drift_updates_ledger_state_and_records_evidence(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """When repo has attached ledger, record_drift updates state and appends evidence."""
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    ledger_path = tmp_path / "mission.ledger"
    ledger = DurableFileLedger(ledger_path)
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=snapshot.contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    for act in snapshot.actions:
        ledger.append_action(
            ActionRecord(
                action_id=act.action_id,
                mission_id=mission_id,
                action=act,
                approval_id=None,
                created_at=now,
            )
        )
    for p in snapshot.desired_state:
        verif_evidence = EvidenceRecord.create(
            action_id=snapshot.actions[0].action_id,
            mission_id=mission_id,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
                observed_at=now,
            ),
            payload={
                "evidence_type": "PREDICATE_EVALUATION",
                "predicate_id": str(p.predicate_id),
                "truth": "TRUE",
                "is_true": True,
                "observations": {
                    "summary": "Leave for school",
                    "start_time": "2026-10-03T07:30:00+03:00",
                },
            },
            created_at=now,
        )
        ledger.append_evidence(verif_evidence)
    # Re-align snapshot evidence_ids with ledger evidence
    ev_recs = tuple(ledger.get_evidence_for_mission(mission_id))
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=[e.evidence_id for e in ev_recs],
        created_at=now,
    )
    ledger.update_mission_state(
        mission_id=mission_id,
        new_state=MissionState.READY,
        updated_at=now,
        snapshot_projection=snapshot.to_dict(),
    )

    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Drifted event text",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    assert result.is_drifted is True

    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps", ledger=ledger)
    repo.save_snapshot(snapshot)
    drifted_snap = record_drift_in_snapshot(repo, snapshot, result)

    assert drifted_snap is not None
    assert drifted_snap.state == MissionState.DRIFTED
    # Check ledger state was updated to DRIFTED
    m_rec = ledger.get_mission(mission_id)
    assert m_rec is not None
    assert m_rec.state == MissionState.DRIFTED
    # Check drift evidence was appended
    ev_records = tuple(ledger.get_evidence_for_mission(mission_id))
    assert len(ev_records) > 0
    drift_ev = next(
        (e for e in ev_records if e.payload.get("evidence_type") == "MISSION_DRIFT"), None
    )
    assert drift_ev is not None
    assert drift_ev.payload.get("new_state") == "DRIFTED"
    assert drift_ev.action_id == snapshot.actions[0].action_id


def test_record_drift_rejected_when_not_drifted(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """record_drift_in_snapshot rejects non-drifted results with ValueError."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Leave for school",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)
    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    assert result.is_drifted is False

    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps")
    repo.save_snapshot(snapshot)

    with pytest.raises(ValueError, match="Cannot record drift for a non-drifted result"):
        record_drift_in_snapshot(repo, snapshot, result)


def test_record_drift_rejected_when_source_snapshot_stale(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """record_drift_in_snapshot rejects stale/superseded source snapshot."""
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Drifted event text",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)
    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    assert result.is_drifted is True

    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps")
    repo.save_snapshot(snapshot)

    # Save newer snapshot in repository
    newer_snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=snapshot.evidence_ids,
        snapshot_id=f"{snapshot.snapshot_id}_rev2",
        created_at=datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC),
    )
    repo.save_snapshot(newer_snapshot)

    # Attempting to record drift against old snapshot fails closed
    with pytest.raises(ValueError, match="is stale"):
        record_drift_in_snapshot(repo, snapshot, result)


def test_record_drift_rejected_when_observations_do_not_contradict(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """record_drift_in_snapshot rejects forged drift where observations
    actually match desired state.
    """
    from stilldone.domain.provenance import EvidenceProvenance
    from stilldone.drift import MissionDriftEvaluationResult
    from stilldone.verifier.contracts import VerificationObservation

    snapshot, pred_summary, _ = _make_ready_snapshot(mission_id, cal_target)
    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps")
    repo.save_snapshot(snapshot)

    obs = VerificationObservation(
        target=cal_target,
        observed_at=datetime.now(UTC),
        exists=True,
        properties={"summary": pred_summary.expected_value},
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    # Forged drift result claiming is_drifted=True but observations match expected_value
    forged_result = MissionDriftEvaluationResult(
        mission_id=mission_id,
        prior_state=MissionState.READY,
        new_state=MissionState.DRIFTED,
        is_drifted=True,
        reconciliation=None,
        transition_result=None,
        evaluated_at=datetime.now(UTC),
        is_inconclusive=False,
        error_message=None,
        fresh_observations={pred_summary.predicate_id: obs},
    )

    with pytest.raises(ValueError, match="Forged drift rejected"):
        record_drift_in_snapshot(repo, snapshot, forged_result)


def test_calendar_drift_explicit_binding_resolves_multi_target_mission(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """When multiple actions exist, explicit PredicateTargetBinding resolves without ambiguity."""
    from stilldone.domain.desired_state import PredicateTargetBinding

    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Changed summary",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    cal_pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Original summary",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    target2 = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_school_departure_002",
        parent_id=cal_target.parent_id,
    )

    action1 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target,
        parameters={},
    )
    action2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target2,
        parameters={},
    )

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    att1 = ExecutionAttempt(
        action_id=action1.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr1 = ProviderExecutionResult(
        action_type=action1.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    step1 = StepExecutionRecord(
        action_id=action1.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att1,
        provider_result=pr1,
    )
    att2 = ExecutionAttempt(
        action_id=action2.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr2 = ProviderExecutionResult(
        action_type=action2.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    step2 = StepExecutionRecord(
        action_id=action2.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att2,
        provider_result=pr2,
    )

    binding = PredicateTargetBinding.create(
        predicate_id=cal_pred.predicate_id,
        mission_id=mission_id,
        target=cal_target,
    )

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=MissionContract.create("Multi-calendar-bound", mission_id=mission_id),
        desired_state=(cal_pred,),
        actions=(action1, action2),
        predicate_bindings=(binding,),
        step_records={action1.action_id: step1, action2.action_id: step2},
        execution_attempts=(att1, att2),
        evidence_ids=(EvidenceId("e" * 64),),
        created_at=now,
    )

    # With explicit binding, no ambiguity error; evaluates cal_target
    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)
    assert result.is_drifted is True
    assert result.new_state == MissionState.DRIFTED


def test_calendar_drift_target_override_contradicting_canonical_binding_rejected(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """A caller target override pointing to a different legitimate action contradicts
    the canonical PredicateTargetBinding and is rejected with DriftTargetMismatchError.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.drift import DriftTargetMismatchError

    fake_transport = FakeGoogleCalendarTransport()
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    cal_pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Original summary",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    target2 = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_school_departure_002",
        parent_id=cal_target.parent_id,
    )
    action1 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target,
        parameters={},
    )
    action2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target2,
        parameters={},
    )
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    att1 = ExecutionAttempt(
        action_id=action1.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr1 = ProviderExecutionResult(
        action_type=action1.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    step1 = StepExecutionRecord(
        action_id=action1.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att1,
        provider_result=pr1,
    )
    att2 = ExecutionAttempt(
        action_id=action2.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr2 = ProviderExecutionResult(
        action_type=action2.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    step2 = StepExecutionRecord(
        action_id=action2.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att2,
        provider_result=pr2,
    )
    binding = PredicateTargetBinding.create(
        predicate_id=cal_pred.predicate_id,
        mission_id=mission_id,
        target=cal_target,
    )
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=MissionContract.create("Multi-calendar-bound", mission_id=mission_id),
        desired_state=(cal_pred,),
        actions=(action1, action2),
        predicate_bindings=(binding,),
        step_records={action1.action_id: step1, action2.action_id: step2},
        execution_attempts=(att1, att2),
        evidence_ids=(EvidenceId("e" * 64),),
        created_at=now,
    )

    with pytest.raises(DriftTargetMismatchError, match="does not match canonical binding"):
        detect_calendar_drift(
            snapshot=snapshot,
            calendar_adapter=cal_adapter,
            target=target2,
        )


def test_mixed_mission_two_calendar_and_two_tasks_drift_evaluation(
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Mission with two Calendar events and two Tasks tasks:
    Calendar drift strictly inspects Calendar predicates and ignores Tasks predicates.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding

    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Event 1",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    cal_target2 = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_cal_002",
        parent_id=cal_target.parent_id,
    )
    fake_transport.seed_event(
        calendar_id=cal_target2.parent_id or "",
        event_id=cal_target2.resource_id,
        summary="Event 2",
        start_time="2026-10-03T08:30:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    tasks_target1 = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task_001",
        parent_id="list_001",
    )
    tasks_target2 = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task_002",
        parent_id="list_001",
    )

    pred_c1 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="confirmed",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_c2 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Event 2",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_t1 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="needsAction",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_t2 = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="title",
        operator=PredicateOperator.EQUALS,
        expected_value="Task 2",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    act_c1 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target,
        parameters={},
    )
    act_c2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target2,
        parameters={},
    )
    act_t1 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=tasks_target1,
        parameters={},
    )
    act_t2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=tasks_target2,
        parameters={},
    )

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    step_records = {}
    attempts = []
    for act in (act_c1, act_c2, act_t1, act_t2):
        att = ExecutionAttempt(
            action_id=act.action_id,
            idempotency_key=IdempotencyKey.generate(),
            attempt_number=1,
            started_at=now,
        )
        attempts.append(att)
        pr = ProviderExecutionResult(
            action_type=act.action_type,
            success=True,
            status_name="READ_OK",
            writes_performed=0,
            captured_at=now,
        )
        step_records[act.action_id] = StepExecutionRecord(
            action_id=act.action_id,
            status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
            attempt=att,
            provider_result=pr,
        )

    bindings = (
        PredicateTargetBinding.create(
            predicate_id=pred_c1.predicate_id, mission_id=mission_id, target=cal_target
        ),
        PredicateTargetBinding.create(
            predicate_id=pred_c2.predicate_id, mission_id=mission_id, target=cal_target2
        ),
        PredicateTargetBinding.create(
            predicate_id=pred_t1.predicate_id, mission_id=mission_id, target=tasks_target1
        ),
        PredicateTargetBinding.create(
            predicate_id=pred_t2.predicate_id, mission_id=mission_id, target=tasks_target2
        ),
    )

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=MissionContract.create("2-Cal-2-Tasks", mission_id=mission_id),
        desired_state=(pred_c1, pred_c2, pred_t1, pred_t2),
        actions=(act_c1, act_c2, act_t1, act_t2),
        predicate_bindings=bindings,
        step_records=step_records,
        execution_attempts=attempts,
        evidence_ids=(EvidenceId("e" * 64),),
        created_at=now,
    )

    result = detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)
    assert result.is_drifted is False
    assert result.new_state == MissionState.READY
    assert result.is_partial is True
    assert result.scope == "google_calendar"
    assert len(result.fresh_observations) == 2
    assert pred_c1.predicate_id in result.fresh_observations
    assert pred_c2.predicate_id in result.fresh_observations
    assert pred_t1.predicate_id not in result.fresh_observations
    assert pred_t2.predicate_id not in result.fresh_observations


def test_drift_recording_rejects_stale_predecessor(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """record_drift_in_snapshot() rejects a stale predecessor snapshot whose state
    has already advanced in the repository.
    """
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Changed summary",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    snapshot, pred_summary, _ = _make_ready_snapshot(mission_id, cal_target)
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger_path = tmp_path / "mission_stale.ledger"
    ledger = DurableFileLedger(ledger_path)
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=snapshot.contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    for act in snapshot.actions:
        ledger.append_action(
            ActionRecord(
                action_id=act.action_id,
                mission_id=mission_id,
                action=act,
                approval_id=None,
                created_at=now,
            )
        )
    for p in snapshot.desired_state:
        verif_ev = EvidenceRecord.create(
            action_id=snapshot.actions[0].action_id,
            mission_id=mission_id,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
                observed_at=now,
            ),
            payload={
                "evidence_type": "PREDICATE_EVALUATION",
                "predicate_id": str(p.predicate_id),
                "truth": "TRUE",
                "is_true": True,
                "observations": {
                    "summary": "Leave for school",
                    "start_time": "2026-10-03T07:30:00+03:00",
                },
            },
            created_at=now,
        )
        ledger.append_evidence(verif_ev)
    ev_recs = tuple(ledger.get_evidence_for_mission(mission_id))
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=[e.evidence_id for e in ev_recs],
        created_at=now,
    )
    ledger.update_mission_state(
        mission_id=mission_id,
        new_state=MissionState.READY,
        updated_at=now,
        snapshot_projection=snapshot.to_dict(),
    )

    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps", ledger=ledger)
    repo.save_snapshot(snapshot)

    drift_res = detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)
    assert drift_res.is_drifted is True

    # Record first drift transition: snapshot advances to DRIFTED
    record_drift_in_snapshot(repo, snapshot, drift_res)

    # Calling record_drift_in_snapshot with the original READY snapshot again fails closed
    # because repository snapshot is now DRIFTED (predecessor state mismatch)
    with pytest.raises(ValueError, match="is stale; current stored snapshot is"):
        record_drift_in_snapshot(repo, snapshot, drift_res)


def test_record_drift_rejects_ledger_less_repository(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """record_drift_in_snapshot rejects repository without attached ledger fail-closed."""
    from stilldone.drift import DriftValueError

    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Changed summary",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_snapshot(mission_id, cal_target)
    drift_res = detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)
    assert drift_res.is_drifted is True

    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps", ledger=None)
    repo.save_snapshot(snapshot)

    with pytest.raises(DriftValueError, match="requires an approved ledger-backed"):
        record_drift_in_snapshot(repo, snapshot, drift_res)


def test_record_drift_rejects_caller_snapshot_with_altered_desired_state(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Caller-provided snapshot with identical snapshot_id and created_at but altered desired_state
    fails closed with DriftValueError (tampering / mismatch detected).
    """
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.drift import DriftValueError
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Changed summary",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, pred_summary, _ = _make_ready_snapshot(mission_id, cal_target)

    ledger_path = tmp_path / "drift_tamper.ledger"
    ledger = DurableFileLedger(ledger_path)
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=snapshot.contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    for act in snapshot.actions:
        ledger.append_action(
            ActionRecord(
                action_id=act.action_id,
                mission_id=mission_id,
                action=act,
                approval_id=None,
                created_at=now,
            )
        )
    for p in snapshot.desired_state:
        verif_ev = EvidenceRecord.create(
            action_id=snapshot.actions[0].action_id,
            mission_id=mission_id,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
                observed_at=now,
            ),
            payload={
                "evidence_type": "PREDICATE_EVALUATION",
                "predicate_id": str(p.predicate_id),
                "truth": "TRUE",
                "is_true": True,
                "observations": {
                    "summary": "Leave for school",
                    "start_time": "2026-10-03T07:30:00+03:00",
                },
            },
            created_at=now,
        )
        ledger.append_evidence(verif_ev)
    ev_recs = tuple(ledger.get_evidence_for_mission(mission_id))
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=[e.evidence_id for e in ev_recs],
        created_at=now,
    )
    ledger.update_mission_state(
        mission_id=mission_id,
        new_state=MissionState.READY,
        updated_at=now,
        snapshot_projection=snapshot.to_dict(),
    )

    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps", ledger=ledger)
    repo.save_snapshot(snapshot)

    drift_res = detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)
    assert drift_res.is_drifted is True

    # Construct tampered snapshot with identical snapshot_id and created_at
    # but altered predicate expected_value
    tampered_pred = DesiredStatePredicate(
        predicate_id=pred_summary.predicate_id,
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Tampered Expected Value",
        freshness=pred_summary.freshness,
        required=True,
    )
    tampered_snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=[tampered_pred, snapshot.desired_state[1]],
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=snapshot.evidence_ids,
        snapshot_id=snapshot.snapshot_id,
        created_at=snapshot.created_at,
    )

    with pytest.raises(DriftValueError, match="content tampering / mismatch detected"):
        record_drift_in_snapshot(repo, tampered_snapshot, drift_res)


def test_record_drift_durable_evidence_contains_exact_mismatch_details(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """record_drift_in_snapshot creates durable MISSION_DRIFT evidence
    with exact mismatch details.
    """
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Changed summary",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, pred_summary, _ = _make_ready_snapshot(mission_id, cal_target)

    ledger_path = tmp_path / "drift_details.ledger"
    ledger = DurableFileLedger(ledger_path)
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=snapshot.contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    for act in snapshot.actions:
        ledger.append_action(
            ActionRecord(
                action_id=act.action_id,
                mission_id=mission_id,
                action=act,
                approval_id=None,
                created_at=now,
            )
        )
    for p in snapshot.desired_state:
        verif_ev = EvidenceRecord.create(
            action_id=snapshot.actions[0].action_id,
            mission_id=mission_id,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
                observed_at=now,
            ),
            payload={
                "evidence_type": "PREDICATE_EVALUATION",
                "predicate_id": str(p.predicate_id),
                "truth": "TRUE",
                "is_true": True,
                "observations": {
                    "summary": "Leave for school",
                    "start_time": "2026-10-03T07:30:00+03:00",
                },
            },
            created_at=now,
        )
        ledger.append_evidence(verif_ev)
    ev_recs = tuple(ledger.get_evidence_for_mission(mission_id))
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=[e.evidence_id for e in ev_recs],
        created_at=now,
    )
    ledger.update_mission_state(
        mission_id=mission_id,
        new_state=MissionState.READY,
        updated_at=now,
        snapshot_projection=snapshot.to_dict(),
    )

    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps", ledger=ledger)
    repo.save_snapshot(snapshot)

    drift_res = detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)
    assert drift_res.is_drifted is True

    record_drift_in_snapshot(repo, snapshot, drift_res)

    all_evs = ledger.get_evidence_for_mission(mission_id)
    drift_ev = next(e for e in all_evs if e.payload.get("evidence_type") == "MISSION_DRIFT")
    payload = drift_ev.payload

    assert payload["source_snapshot_id"] == snapshot.snapshot_id
    assert payload["predicate_id"] == str(pred_summary.predicate_id)
    assert payload["target"]["resource_id"] == cal_target.resource_id
    assert payload["provider"] == cal_target.system
    assert payload["expected_value"] == "Leave for school"
    assert payload["observed_value"] == "Changed summary"
    assert payload["freshness_status"] == "FRESH"
    assert payload["is_drifted"] is True
    assert payload["prior_state"] == "READY"
    assert payload["new_state"] == "DRIFTED"
    assert "mismatch_reason" in payload
