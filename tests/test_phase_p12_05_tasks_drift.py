"""Tests for External-Change Drift Detection on Google Tasks (Phase P-12.05).

Validates:
- Detects relevant task state changes: completion reversal, missing task,
  mismatched bound properties.
- Preserves exact task ID and task-list identity (never matches by title alone).
- Uses fresh read-back; never trusts historical execution success as current truth.
- Persists truthful drift evidence and legal lifecycle transition (READY -> DRIFTED).
- Shared domain contracts maintain consistency between Calendar and Tasks.
- Strictly read-only: zero task creation, completion, or mutation.
- Proves stable state, genuine drift (completion reversal & title change), missing task,
  stale state, wrong task-list identity, provider failure, cross-provider parity, and
  non-READY rejection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stilldone.adapters.calendar import (
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
)
from stilldone.adapters.tasks import (
    FakeGoogleTasksTransport,
    GoogleTasksReadAdapter,
    TaskTransportError,
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
    detect_tasks_drift,
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
def tasks_target() -> TargetIdentity:
    return TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task_pack_backpacks_001",
        parent_id="list_demo_tasks",
    )


@pytest.fixture
def demo_scope(tasks_target: TargetIdentity) -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id="c_demo@group.calendar.google.com",
        task_list_id=tasks_target.parent_id or "list_demo_tasks",
    )


def _make_ready_tasks_snapshot(
    mission_id: MissionId,
    target: TargetIdentity,
    *,
    expected_title: str = "Pack backpacks",
    expected_status: str = "completed",
    expected_due: str | None = "2026-10-03",
    state: MissionState = MissionState.READY,
) -> tuple[MissionSnapshot, DesiredStatePredicate, DesiredStatePredicate]:
    pred_status = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value=expected_status,
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_title = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="title",
        operator=PredicateOperator.EQUALS,
        expected_value=expected_title,
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=target,
        parameters={},
    )

    contract = MissionContract.create(
        text="Ensure backpacks are packed",
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
        desired_state=(pred_status, pred_title),
        actions=(action,),
        step_records=step_records,
        execution_attempts=execution_attempts,
        evidence_ids=evidence_ids,
        created_at=now,
    )
    return snapshot, pred_status, pred_title


def test_tasks_stable_state_remains_ready(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Stable state: tasks state on provider matches desired state; mission remains READY."""
    fake_transport = FakeGoogleTasksTransport()
    fake_transport.seed_task(
        task_list_id=tasks_target.parent_id or "",
        task_id=tasks_target.resource_id,
        title="Pack backpacks",
        status="completed",
        due="2026-10-03",
    )
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)

    result = detect_tasks_drift(snapshot=snapshot, tasks_adapter=adapter)

    assert result.is_drifted is False
    assert result.is_inconclusive is False
    assert result.prior_state == MissionState.READY
    assert result.new_state == MissionState.READY
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.STILL_TRUE
    assert fake_transport.writes_count == 0  # Read-only


def test_tasks_completion_reversal_detects_drift(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Completion reversal: task status reverted from 'completed' to 'needsAction' -> DRIFTED."""
    fake_transport = FakeGoogleTasksTransport()
    fake_transport.seed_task(
        task_list_id=tasks_target.parent_id or "",
        task_id=tasks_target.resource_id,
        title="Pack backpacks",
        status="needsAction",  # Completion reversed externally!
        due="2026-10-03",
    )
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, pred_status, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)

    result = detect_tasks_drift(snapshot=snapshot, tasks_adapter=adapter)

    assert result.is_drifted is True
    assert result.is_inconclusive is False
    assert result.prior_state == MissionState.READY
    assert result.new_state == MissionState.DRIFTED
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE
    assert pred_status.predicate_id in result.reconciliation.drifted_predicate_ids

    # Persist in durable snapshot repository
    repo = DurableSnapshotRepository(storage_path=str(tmp_path))
    repo.save_snapshot(snapshot)
    drifted_snap = record_drift_in_snapshot(repo, snapshot, result)
    assert drifted_snap is not None
    assert drifted_snap.state == MissionState.DRIFTED
    loaded = repo.load_snapshot(mission_id)
    assert loaded.state == MissionState.DRIFTED


def test_tasks_changed_title_detects_drift(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Changed property: task title changed externally; transitions to DRIFTED."""
    fake_transport = FakeGoogleTasksTransport()
    fake_transport.seed_task(
        task_list_id=tasks_target.parent_id or "",
        task_id=tasks_target.resource_id,
        title="Unpack backpacks",  # Changed externally
        status="completed",
        due="2026-10-03",
    )
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, pred_title = _make_ready_tasks_snapshot(mission_id, tasks_target)

    result = detect_tasks_drift(snapshot=snapshot, tasks_adapter=adapter)

    assert result.is_drifted is True
    assert result.new_state == MissionState.DRIFTED
    assert result.reconciliation is not None
    assert pred_title.predicate_id in result.reconciliation.drifted_predicate_ids


def test_tasks_missing_task_404_detects_drift(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Missing task: task deleted externally (404); desired state contradicted -> DRIFTED."""
    fake_transport = FakeGoogleTasksTransport()
    # No task seeded => returns 404 / NOT_FOUND
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)

    result = detect_tasks_drift(snapshot=snapshot, tasks_adapter=adapter)

    assert result.is_drifted is True
    assert result.new_state == MissionState.DRIFTED
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.NO_LONGER_TRUE


def test_tasks_stale_read_is_inconclusive_no_false_drift(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Stale read: observation expired; fails closed as inconclusive without false drift."""
    fake_transport = FakeGoogleTasksTransport()
    fake_transport.seed_task(
        task_list_id=tasks_target.parent_id or "",
        task_id=tasks_target.resource_id,
        title="Different task",
        status="needsAction",
    )
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)

    # Evaluate at a point 10 hours in the future
    future_time = datetime.now(UTC) + timedelta(hours=10)
    result = detect_tasks_drift(
        snapshot=snapshot,
        tasks_adapter=adapter,
        eval_at=future_time,
    )

    assert result.is_drifted is False
    assert result.is_inconclusive is True
    assert result.new_state == MissionState.READY


def test_tasks_api_failure_is_inconclusive_no_false_drift(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API failure: 503 error during read; inconclusive, remains READY without false drift."""
    fake_transport = FakeGoogleTasksTransport()
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)

    def failing_get_task(*args: object, **kwargs: object) -> None:
        raise TaskTransportError("503 Service Unavailable", status_code=503)

    monkeypatch.setattr(fake_transport, "get_task", failing_get_task)

    result = detect_tasks_drift(snapshot=snapshot, tasks_adapter=adapter)

    assert result.is_drifted is False
    assert result.is_inconclusive is True
    assert result.new_state == MissionState.READY
    assert "provider" in (result.error_message or "").lower()


def test_tasks_wrong_identity_or_target_mismatch_fails_closed(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Wrong target or mismatched system fails closed."""
    fake_transport = FakeGoogleTasksTransport()
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)

    wrong_target = TargetIdentity(
        system="google_calendar",  # Mismatched system
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="wrong_id",
        parent_id="wrong_cal",
    )

    with pytest.raises(DriftTargetMismatchError):
        detect_tasks_drift(
            snapshot=snapshot,
            tasks_adapter=adapter,
            target=wrong_target,
        )


def test_tasks_non_ready_predecessor_rejected_fail_closed(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Non-READY predecessor rejected fail-closed."""
    fake_transport = FakeGoogleTasksTransport()
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)

    unready_snapshot, _, _ = _make_ready_tasks_snapshot(
        mission_id, tasks_target, state=MissionState.DRAFT
    )

    with pytest.raises(ReconciliationLifecycleError):
        detect_tasks_drift(snapshot=unready_snapshot, tasks_adapter=adapter)


def test_cross_provider_parity_calendar_and_tasks(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Cross-provider parity: Calendar and Tasks drift logic share the same lifecycle behavior."""
    # Calendar setup
    cal_target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_parity_test_001",
        parent_id=demo_scope.calendar_id,
    )
    fake_cal_transport = FakeGoogleCalendarTransport()
    fake_cal_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Parity Event",
        start_time="2026-10-03T07:30:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_cal_transport)

    pred_cal = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value="Parity Event",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    action_cal = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target,
        parameters={},
    )
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    att_cal = ExecutionAttempt(
        action_id=action_cal.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr_cal = ProviderExecutionResult(
        action_type=action_cal.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    step_cal = StepExecutionRecord(
        action_id=action_cal.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att_cal,
        provider_result=pr_cal,
    )

    cal_snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=MissionContract.create(
            text="Parity calendar check",
            mission_id=mission_id,
            created_at=now,
        ),
        desired_state=(pred_cal,),
        actions=(action_cal,),
        step_records={action_cal.action_id: step_cal},
        execution_attempts=(att_cal,),
        evidence_ids=(EvidenceId("e" * 64),),
        created_at=now,
    )

    # Tasks setup
    fake_tasks_transport = FakeGoogleTasksTransport()
    fake_tasks_transport.seed_task(
        task_list_id=tasks_target.parent_id or "",
        task_id=tasks_target.resource_id,
        title="Parity Task",
        status="completed",
    )
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_tasks_transport)

    pred_tasks = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="title",
        operator=PredicateOperator.EQUALS,
        expected_value="Parity Task",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    action_tasks = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=tasks_target,
        parameters={},
    )
    att_tasks = ExecutionAttempt(
        action_id=action_tasks.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr_tasks = ProviderExecutionResult(
        action_type=action_tasks.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    step_tasks = StepExecutionRecord(
        action_id=action_tasks.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=att_tasks,
        provider_result=pr_tasks,
    )

    tasks_snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=MissionContract.create(
            text="Parity task check",
            mission_id=mission_id,
            created_at=now,
        ),
        desired_state=(pred_tasks,),
        actions=(action_tasks,),
        step_records={action_tasks.action_id: step_tasks},
        execution_attempts=(att_tasks,),
        evidence_ids=(EvidenceId("e" * 64),),
        created_at=now,
    )

    cal_res = detect_calendar_drift(snapshot=cal_snapshot, calendar_adapter=cal_adapter)
    tasks_res = detect_tasks_drift(snapshot=tasks_snapshot, tasks_adapter=tasks_adapter)

    # Both providers must yield identical lifecycle parity on matching state
    assert cal_res.is_drifted == tasks_res.is_drifted is False
    assert cal_res.new_state == tasks_res.new_state == MissionState.READY
    assert cal_res.is_inconclusive == tasks_res.is_inconclusive is False
    assert cal_res.reconciliation is not None
    assert tasks_res.reconciliation is not None
    assert cal_res.reconciliation.status == ReconciliationStatus.STILL_TRUE
    assert tasks_res.reconciliation.status == ReconciliationStatus.STILL_TRUE


def test_tasks_drift_ambiguous_targets_fails_closed(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Multiple tasks actions without explicit target fails closed with DriftTargetMismatchError."""
    fake_tasks_transport = FakeGoogleTasksTransport()
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_tasks_transport)

    task_pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="title",
        operator=PredicateOperator.EQUALS,
        expected_value="Task 1",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    target2 = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task_pack_backpacks_002",
        parent_id=tasks_target.parent_id,
    )

    action1 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=tasks_target,
        parameters={},
    )
    action2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
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
        contract=MissionContract.create("Multi-tasks", mission_id=mission_id),
        desired_state=(task_pred,),
        actions=(action1, action2),
        step_records={action1.action_id: step1, action2.action_id: step2},
        execution_attempts=(att1, att2),
        evidence_ids=(EvidenceId("e" * 64),),
        created_at=now,
    )

    with pytest.raises(DriftTargetMismatchError, match="Ambiguous target for predicate"):
        detect_tasks_drift(snapshot=snapshot, tasks_adapter=tasks_adapter)


def test_tasks_record_drift_updates_ledger_state_and_records_evidence(
    tmp_path: Path,
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """When repo has attached ledger, record_drift updates state and appends evidence."""
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    ledger_path = tmp_path / "mission.ledger"
    ledger = DurableFileLedger(ledger_path)
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    snapshot, _, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)

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
    verif_evidence = EvidenceRecord.create(
        action_id=snapshot.actions[0].action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(snapshot.desired_state[0].predicate_id),
            "truth": "TRUE",
            "is_true": True,
        },
        created_at=now,
    )
    ledger.append_evidence(verif_evidence)
    ledger.update_mission_state(
        mission_id=mission_id,
        new_state=MissionState.READY,
        updated_at=now,
    )
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

    fake_transport = FakeGoogleTasksTransport()
    # Task completion reversal: status changed to "needsAction"
    fake_transport.seed_task(
        task_list_id=tasks_target.parent_id or "",
        task_id=tasks_target.resource_id,
        title="Pack backpacks",
        status="needsAction",
    )
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    result = detect_tasks_drift(snapshot=snapshot, tasks_adapter=adapter)
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


def test_tasks_record_drift_rejected_when_not_drifted(
    tmp_path: Path,
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """record_drift_in_snapshot rejects non-drifted results with ValueError."""
    fake_transport = FakeGoogleTasksTransport()
    fake_transport.seed_task(
        task_list_id=tasks_target.parent_id or "",
        task_id=tasks_target.resource_id,
        title="Pack backpacks",
        status="completed",
    )
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)
    result = detect_tasks_drift(snapshot=snapshot, tasks_adapter=adapter)
    assert result.is_drifted is False

    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps")
    repo.save_snapshot(snapshot)

    with pytest.raises(ValueError, match="Cannot record drift for a non-drifted result"):
        record_drift_in_snapshot(repo, snapshot, result)


def test_tasks_record_drift_rejected_when_source_snapshot_stale(
    tmp_path: Path,
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """record_drift_in_snapshot rejects stale/superseded source snapshot."""
    fake_transport = FakeGoogleTasksTransport()
    fake_transport.seed_task(
        task_list_id=tasks_target.parent_id or "",
        task_id=tasks_target.resource_id,
        title="Pack backpacks",
        status="needsAction",
    )
    adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)
    snapshot, _, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)
    result = detect_tasks_drift(snapshot=snapshot, tasks_adapter=adapter)
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


def test_tasks_record_drift_rejected_when_observations_do_not_contradict(
    tmp_path: Path,
    mission_id: MissionId,
    tasks_target: TargetIdentity,
) -> None:
    """record_drift_in_snapshot rejects forged drift where observations
    actually match desired state.
    """
    from stilldone.domain.provenance import EvidenceProvenance
    from stilldone.drift import MissionDriftEvaluationResult
    from stilldone.verifier.contracts import VerificationObservation

    snapshot, pred_status, _ = _make_ready_tasks_snapshot(mission_id, tasks_target)
    repo = DurableSnapshotRepository(storage_path=tmp_path / "snaps")
    repo.save_snapshot(snapshot)

    obs = VerificationObservation(
        target=tasks_target,
        observed_at=datetime.now(UTC),
        exists=True,
        properties={"status": pred_status.expected_value},
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
        fresh_observations={pred_status.predicate_id: obs},
    )

    with pytest.raises(ValueError, match="Forged drift rejected"):
        record_drift_in_snapshot(repo, snapshot, forged_result)


def test_tasks_drift_explicit_binding_resolves_multi_target_mission(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """When multiple actions exist, explicit PredicateTargetBinding resolves without ambiguity."""
    from stilldone.domain.desired_state import PredicateTargetBinding

    fake_transport = FakeGoogleTasksTransport()
    fake_transport.seed_task(
        task_list_id=tasks_target.parent_id or "",
        task_id=tasks_target.resource_id,
        title="Original title",
        status="needsAction",
    )
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)

    task_pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="completed",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )

    target2 = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task_other_002",
        parent_id=tasks_target.parent_id,
    )

    action1 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=tasks_target,
        parameters={},
    )
    action2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
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
        predicate_id=task_pred.predicate_id,
        mission_id=mission_id,
        target=tasks_target,
    )

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=MissionContract.create("Multi-tasks-bound", mission_id=mission_id),
        desired_state=(task_pred,),
        actions=(action1, action2),
        predicate_bindings=(binding,),
        step_records={action1.action_id: step1, action2.action_id: step2},
        execution_attempts=(att1, att2),
        evidence_ids=(EvidenceId("e" * 64),),
        created_at=now,
    )

    # With explicit binding, no ambiguity error; evaluates tasks_target
    result = detect_tasks_drift(snapshot=snapshot, tasks_adapter=tasks_adapter)
    assert result.is_drifted is True
    assert result.new_state == MissionState.DRIFTED


def test_tasks_drift_target_override_contradicting_canonical_binding_rejected(
    mission_id: MissionId,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """A caller target override pointing to a different legitimate action contradicts
    the canonical PredicateTargetBinding and is rejected with DriftTargetMismatchError.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.drift import DriftTargetMismatchError

    fake_transport = FakeGoogleTasksTransport()
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=fake_transport)

    task_pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="completed",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    target2 = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task_other_002",
        parent_id=tasks_target.parent_id,
    )
    action1 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=tasks_target,
        parameters={},
    )
    action2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
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
        predicate_id=task_pred.predicate_id,
        mission_id=mission_id,
        target=tasks_target,
    )
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=MissionContract.create("Multi-tasks-bound", mission_id=mission_id),
        desired_state=(task_pred,),
        actions=(action1, action2),
        predicate_bindings=(binding,),
        step_records={action1.action_id: step1, action2.action_id: step2},
        execution_attempts=(att1, att2),
        evidence_ids=(EvidenceId("e" * 64),),
        created_at=now,
    )

    with pytest.raises(DriftTargetMismatchError, match="does not match canonical binding"):
        detect_tasks_drift(
            snapshot=snapshot,
            tasks_adapter=tasks_adapter,
            target=target2,
        )
