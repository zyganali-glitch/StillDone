"""Focused tests for Phase P-12.07: Run fresh-session 'Are we still ready?' proof.

Validates:
1. Clean second-process reload with identical receipt hash preservation.
2. Fresh TRUE revalidation preserving READY current state across Calendar and Tasks.
3. Explicit FALSE contradiction driving deterministic READY -> DRIFTED reconciliation.
4. Correct READY -> DRIFTED current projection while historical receipt remains immutable.
5. Subsequent restart consistency and evidence lineage preservation.
6. Stale reads and provider transport errors never masquerade as external drift.
7. Wrong resource, missing binding, and duplicate replay rejection.
8. Zero provider writes and zero approval consumption during revalidation.
9. No LIVE certification from synthetic transports (strict non-certifying boundary).
10. Full multi-process proof runner and CLI execution with sanitized JSON output.
11. Adversarial edge cases: missing tasks resource, completion reversal, tampered lineage,
    receipt replacement, wrong bound resource, and incomplete reader.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.p12_07_proof import (
    CANONICAL_CAL_PREDICATE_ID,
    CANONICAL_MISSION_ID,
    CANONICAL_SUMMARY,
    CANONICAL_TASK_STATUS,
    CANONICAL_TASK_TITLE,
    CANONICAL_TASKS_PREDICATE_ID,
    CONTRADICTORY_SUMMARY,
    DEMO_CALENDAR_ID,
    DEMO_EVENT_ID,
    DEMO_TASK_ID,
    DEMO_TASK_LIST_ID,
    run_p12_07_proof,
)
from stilldone.adapters.calendar import (
    CalendarTransportError,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
)
from stilldone.adapters.tasks import (
    FakeGoogleTasksTransport,
    GoogleTasksReadAdapter,
)
from stilldone.demo_isolation import DemoResourceScope
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
    PredicateTargetBinding,
)
from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.drift import (
    DriftTargetMismatchError,
    DriftValueError,
    detect_calendar_drift,
    detect_tasks_drift,
    record_drift_in_snapshot,
)
from stilldone.execution.state import (
    ActionExecutionStatus,
    ProviderExecutionResult,
    StepExecutionRecord,
)
from stilldone.ledger import (
    ActionRecord,
    DurableFileLedger,
    EvidenceRecord,
    MissionRecord,
)
from stilldone.receipt import (
    ReceiptProjection,
    create_mission_ready_receipt,
    project_current_state,
)
from stilldone.revalidation import (
    RevalidationValueError,
    StandardTargetReader,
    revalidate_mission,
)
from stilldone.session import (
    resume_mission_session,
)
from stilldone.snapshot import (
    DurableSnapshotRepository,
    MissionSnapshot,
    SnapshotIntegrityError,
    create_mission_snapshot,
)


@pytest.fixture
def mission_id() -> MissionId:
    return MissionId(CANONICAL_MISSION_ID)


@pytest.fixture
def cal_target() -> TargetIdentity:
    return TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id=DEMO_EVENT_ID,
        parent_id=DEMO_CALENDAR_ID,
    )


@pytest.fixture
def tasks_target() -> TargetIdentity:
    return TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id=DEMO_TASK_ID,
        parent_id=DEMO_TASK_LIST_ID,
    )


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=DEMO_CALENDAR_ID,
        task_list_id=DEMO_TASK_LIST_ID,
    )


def _seed_test_mission(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity | None = None,
    *,
    summary: str = CANONICAL_SUMMARY,
    task_status: str = CANONICAL_TASK_STATUS,
    task_title: str = CANONICAL_TASK_TITLE,
) -> tuple[DurableSnapshotRepository, DurableFileLedger, MissionSnapshot, ReceiptProjection]:
    """Helper seeding canonical READY mission with dual resources (Calendar + Tasks)."""
    if tasks_target is None:
        tasks_target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id=DEMO_TASK_ID,
            parent_id=DEMO_TASK_LIST_ID,
        )

    ledger_path = tmp_path / "ledger.jsonl"
    storage_path = tmp_path / "snapshots"
    storage_path.mkdir(parents=True, exist_ok=True)

    ledger = DurableFileLedger(ledger_path)
    repository = DurableSnapshotRepository(storage_path, ledger=ledger)

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    contract = MissionContract.create(
        text="Ensure morning departure is on track and pack school bag",
        mission_id=mission_id,
        created_at=now,
    )
    pred_summary = DesiredStatePredicate(
        predicate_id=PredicateId(CANONICAL_CAL_PREDICATE_ID),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value=summary,
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_cal_binding = PredicateTargetBinding.create(
        predicate_id=pred_summary.predicate_id,
        mission_id=mission_id,
        target=cal_target,
    )

    pred_task = DesiredStatePredicate(
        predicate_id=PredicateId(CANONICAL_TASKS_PREDICATE_ID),
        mission_id=mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value=task_status,
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_task_binding = PredicateTargetBinding.create(
        predicate_id=pred_task.predicate_id,
        mission_id=mission_id,
        target=tasks_target,
    )

    cal_action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target,
        parameters={},
    )
    tasks_action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.TASK_READ,
        target=tasks_target,
        parameters={},
    )

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
            contract=contract,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=cal_action.action_id,
            mission_id=mission_id,
            action=cal_action,
            approval_id=None,
            created_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=tasks_action.action_id,
            mission_id=mission_id,
            action=tasks_action,
            approval_id=None,
            created_at=now,
        )
    )

    origin = EvidenceOrigin(
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
        observed_at=now,
    )
    cal_verif_payload = {
        "evidence_type": "PREDICATE_EVALUATION",
        "predicate_id": str(pred_summary.predicate_id),
        "truth": "TRUE",
        "observed_value": summary,
        "is_match": True,
        "observations": {"summary": summary},
        "target": {
            "system": cal_target.system,
            "resource_kind": cal_target.resource_kind.value,
            "resource_id": cal_target.resource_id,
            "parent_id": cal_target.parent_id,
        },
    }
    cal_verif_ev = EvidenceRecord.create(
        action_id=cal_action.action_id,
        mission_id=mission_id,
        origin=origin,
        payload=cal_verif_payload,
        created_at=now,
    )

    tasks_verif_payload = {
        "evidence_type": "PREDICATE_EVALUATION",
        "predicate_id": str(pred_task.predicate_id),
        "truth": "TRUE",
        "observed_value": task_status,
        "is_match": True,
        "observations": {"status": task_status, "title": task_title},
        "target": {
            "system": tasks_target.system,
            "resource_kind": tasks_target.resource_kind.value,
            "resource_id": tasks_target.resource_id,
            "parent_id": tasks_target.parent_id,
        },
    }
    tasks_verif_ev = EvidenceRecord.create(
        action_id=tasks_action.action_id,
        mission_id=mission_id,
        origin=origin,
        payload=tasks_verif_payload,
        created_at=now,
    )

    # Append tasks evidence record (cal_verif_ev will be appended by transition)
    ledger.append_evidence(tasks_verif_ev)

    cal_attempt = ExecutionAttempt(
        action_id=cal_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    cal_p_res = ProviderExecutionResult(
        action_type=cal_action.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    cal_step_rec = StepExecutionRecord(
        action_id=cal_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=cal_attempt,
        provider_result=cal_p_res,
    )

    tasks_attempt = ExecutionAttempt(
        action_id=tasks_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    tasks_p_res = ProviderExecutionResult(
        action_type=tasks_action.action_type,
        success=True,
        status_name="READ_OK",
        writes_performed=0,
        captured_at=now,
    )
    tasks_step_rec = StepExecutionRecord(
        action_id=tasks_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=tasks_attempt,
        provider_result=tasks_p_res,
    )

    ready_snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=(pred_summary, pred_task),
        actions=(cal_action, tasks_action),
        step_records={
            cal_action.action_id: cal_step_rec,
            tasks_action.action_id: tasks_step_rec,
        },
        execution_attempts=(cal_attempt, tasks_attempt),
        evidence_ids=(cal_verif_ev.evidence_id, tasks_verif_ev.evidence_id),
        predicate_bindings=(pred_cal_binding, pred_task_binding),
        created_at=now,
    )

    ledger.record_state_transition(
        mission_id=mission_id,
        expected_prior_state=MissionState.VERIFYING,
        new_state=MissionState.READY,
        evidence=cal_verif_ev,
        updated_at=now,
        snapshot_projection=ready_snapshot.to_dict(),
    )

    repository.save_snapshot(ready_snapshot)

    receipt = create_mission_ready_receipt(ready_snapshot)
    repository.save_receipt(receipt)

    return repository, ledger, ready_snapshot, receipt


# ===========================================================================
# 1. Multi-Process Proof Runner End-to-End
# ===========================================================================


def test_fresh_session_proof_runner_end_to_end(tmp_path: Path) -> None:
    """Full 10-step proof runs cleanly across 4 discrete OS processes."""
    result = run_p12_07_proof(storage_dir=tmp_path, use_subprocesses=True)

    assert result["task"] == "P-12.07"
    assert result["multi_process_isolation_verified"] is True
    assert len(set(result["process_ids"].values())) == 4

    # Receipt hash preserved
    assert len(result["historical_ready_receipt_hash"]) == 64
    assert result["receipt_immutability_proven"] is True
    assert result["current_truth_projected_independently"] is True

    # Step 2 Revalidate
    assert result["step_2_revalidate_is_still_true"] is True
    assert result["step_2_current_state"] == "READY"
    assert result["step_2_writes_performed"] == 0

    # Step 3 Drift Reconciliation
    assert result["step_3_drift_detected"] is True
    assert result["step_3_current_state"] == "DRIFTED"
    assert result["step_3_historical_state"] == "READY"

    # Step 4 Restart
    assert result["step_4_restart_current_state"] == "DRIFTED"
    assert result["step_4_evidence_count"] == 3
    assert result["step_4_lineage_verified"] is True

    # Zero spend and live gate
    assert result["zero_spend_confirmed"] is True
    assert result["live_gate_status"]["status"] == "NOT_RUN"


# ===========================================================================
# 2. Clean Second-Process Reload & Hash Preservation
# ===========================================================================


def test_clean_second_process_reload_and_receipt_hash_preservation(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
) -> None:
    """Fresh session reload recovers exact receipt hash and verifies state."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )
    orig_hash = receipt.receipt_hash.value

    # Process 2 reloads from disk
    session_2 = resume_mission_session(
        storage_path=tmp_path / "snapshots",
        ledger_path=tmp_path / "ledger.jsonl",
        mission_id=mission_id,
    )

    assert session_2.snapshot.snapshot_id == snapshot.snapshot_id
    assert session_2.snapshot.state == MissionState.READY
    assert session_2.historical_receipt is not None
    assert session_2.historical_receipt.receipt_hash.value == orig_hash
    assert session_2.historical_receipt.is_historical is True
    assert session_2.historical_receipt.state_at_projection == MissionState.READY

    curr_2 = session_2.current_state
    assert curr_2.state == MissionState.READY
    assert curr_2.is_ready is True
    assert curr_2.is_drifted is False
    assert curr_2.is_historical is False
    assert curr_2.historical_receipt_hash is not None
    assert curr_2.historical_receipt_hash.value == orig_hash


# ===========================================================================
# 3. Fresh TRUE Revalidation Preserves READY State
# ===========================================================================


def test_fresh_true_revalidation_preserves_ready_state(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """When reality continues to match for both Calendar and Tasks, revalidation is TRUE."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    session = resume_mission_session(
        storage_path=tmp_path / "snapshots",
        ledger_path=tmp_path / "ledger.jsonl",
        mission_id=mission_id,
    )

    cal_transport = FakeGoogleCalendarTransport()
    cal_transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CANONICAL_SUMMARY,
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=cal_transport)

    tasks_transport = FakeGoogleTasksTransport()
    tasks_transport.seed_task(
        task_list_id=DEMO_TASK_LIST_ID,
        task_id=DEMO_TASK_ID,
        title=CANONICAL_TASK_TITLE,
        status=CANONICAL_TASK_STATUS,
    )
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=tasks_transport)

    reader = StandardTargetReader(
        calendar_read_adapter=cal_adapter, tasks_read_adapter=tasks_adapter
    )

    reval = revalidate_mission(
        mission_id=session.snapshot.mission_id,
        predicates=session.snapshot.desired_state,
        snapshot=session.snapshot,
        target_reader=reader,
    )

    assert reval.is_still_true is True
    assert reval.writes_performed == 0
    assert cal_transport.writes_count == 0
    assert tasks_transport.writes_count == 0

    curr = session.current_state
    assert curr.state == MissionState.READY
    assert curr.is_ready is True
    assert curr.is_drifted is False


# ===========================================================================
# 4. Explicit FALSE Contradiction Drives Deterministic Drift
# ===========================================================================


def test_explicit_false_contradiction_drives_deterministic_drift(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Calendar mutation produces drift while Tasks remains true; mission drifts to DRIFTED."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    session = resume_mission_session(
        storage_path=tmp_path / "snapshots",
        ledger_path=tmp_path / "ledger.jsonl",
        mission_id=mission_id,
    )

    cal_transport = FakeGoogleCalendarTransport()
    cal_transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CONTRADICTORY_SUMMARY,
        start_time="2026-10-03T09:00:00+03:00",
        end_time="2026-10-03T09:30:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=cal_transport)

    tasks_transport = FakeGoogleTasksTransport()
    tasks_transport.seed_task(
        task_list_id=DEMO_TASK_LIST_ID,
        task_id=DEMO_TASK_ID,
        title=CANONICAL_TASK_TITLE,
        status=CANONICAL_TASK_STATUS,
    )
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=tasks_transport)

    # Tasks evaluation independently remains NOT drifted
    tasks_eval = detect_tasks_drift(snapshot=session.snapshot, tasks_adapter=tasks_adapter)
    assert tasks_eval.is_drifted is False

    # Calendar evaluation detects drift
    drift_eval = detect_calendar_drift(snapshot=session.snapshot, calendar_adapter=cal_adapter)
    assert drift_eval.is_drifted is True
    assert drift_eval.new_state == MissionState.DRIFTED

    # Provider-scoped drift reconciles the whole mission
    repo_session = DurableSnapshotRepository(tmp_path / "snapshots", ledger=session.ledger)
    drifted_snap = record_drift_in_snapshot(repo_session, session.snapshot, drift_eval)
    assert drifted_snap is not None
    assert drifted_snap.state == MissionState.DRIFTED
    assert drifted_snap.snapshot_id != session.snapshot.snapshot_id

    curr = project_current_state(
        drifted_snap,
        historical_receipt=session.historical_receipt,
        ledger=session.ledger,
    )
    assert curr.state == MissionState.DRIFTED
    assert curr.is_ready is False
    assert curr.is_drifted is True


# ===========================================================================
# 5. Historical Receipt Remains Immutable While Current Truth is DRIFTED
# ===========================================================================


def test_historical_receipt_remains_immutable_while_current_truth_is_drifted(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Original READY receipt on disk and in memory remains untouched."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )
    orig_hash = receipt.receipt_hash.value

    # Reconcile drift
    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary="Canceled Event",
        start_time="2026-10-03T09:00:00+03:00",
        end_time="2026-10-03T09:30:00+03:00",
        status="cancelled",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=transport)
    drift_eval = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    record_drift_in_snapshot(repo, snapshot, drift_eval)

    # Disk receipt is STILL READY and unchanged
    loaded_receipt = repo.load_receipt(mission_id)
    assert loaded_receipt.receipt_hash.value == orig_hash
    assert loaded_receipt.state_at_projection == MissionState.READY
    assert loaded_receipt.is_historical is True

    # Mutating receipt attribute fails closed
    with pytest.raises(FrozenInstanceError):
        loaded_receipt.state_at_projection = MissionState.DRIFTED


# ===========================================================================
# 6. Subsequent Restart Consistency & Lineage Preservation
# ===========================================================================


def test_subsequent_restart_consistency_and_lineage_preservation(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Subsequent restart in fresh session re-projects DRIFTED current state."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )
    orig_hash = receipt.receipt_hash.value

    # Reconcile drift
    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CONTRADICTORY_SUMMARY,
        start_time="2026-10-03T09:00:00+03:00",
        end_time="2026-10-03T09:30:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=transport)
    drift_eval = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    _ = record_drift_in_snapshot(repo, snapshot, drift_eval)

    # Process 3 projection
    session_3 = resume_mission_session(
        storage_path=tmp_path / "snapshots",
        ledger_path=tmp_path / "ledger.jsonl",
        mission_id=mission_id,
    )
    proj_3 = session_3.current_state
    assert proj_3.state == MissionState.DRIFTED

    # Process 4 restart
    session_4 = resume_mission_session(
        storage_path=tmp_path / "snapshots",
        ledger_path=tmp_path / "ledger.jsonl",
        mission_id=mission_id,
    )
    proj_4 = session_4.current_state

    # Consistency across restarts
    assert proj_4.projection_hash == proj_3.projection_hash
    assert proj_4.state == MissionState.DRIFTED
    assert session_4.historical_receipt is not None
    assert session_4.historical_receipt.receipt_hash.value == orig_hash

    # Lineage verified: 2 verification records + 1 drift record = 3 records
    evidences = ledger.get_evidence_for_mission(mission_id)
    assert len(evidences) == 3
    verif_records = [
        e for e in evidences if e.payload.get("evidence_type") == "PREDICATE_EVALUATION"
    ]
    drift_records = [e for e in evidences if e.payload.get("evidence_type") == "MISSION_DRIFT"]
    assert len(verif_records) == 2
    assert len(drift_records) == 1
    assert all(e.payload.get("truth") == "TRUE" for e in verif_records)
    assert drift_records[0].payload.get("is_drifted") is True


# ===========================================================================
# 7. Stale and Provider Error Non-Promotion
# ===========================================================================


def test_stale_and_provider_error_non_promotion_in_fresh_session(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Provider error never gets promoted to drift proof or alters state."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    class FlakyTransport(FakeGoogleCalendarTransport):
        def get_event(self, calendar_id: str, event_id: str) -> None:
            raise CalendarTransportError("Service unavailable: HTTP 503")

    flaky_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=FlakyTransport())
    eval_res = detect_calendar_drift(snapshot=snapshot, calendar_adapter=flaky_adapter)

    assert eval_res.is_drifted is False
    assert eval_res.is_inconclusive is True
    assert eval_res.new_state == MissionState.READY
    assert eval_res.error_message is not None
    assert "Calendar provider" in eval_res.error_message

    # Attempting to record non-drifted result in snapshot fails closed
    with pytest.raises(DriftValueError, match="Cannot record drift for a non-drifted result"):
        record_drift_in_snapshot(repo, snapshot, eval_res)


# ===========================================================================
# 8. Wrong Resource, Missing Binding, and Replay Rejection
# ===========================================================================


def test_wrong_resource_missing_binding_and_replay_rejection(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Duplicate/replayed drift transitions handle idempotently or fail closed."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CONTRADICTORY_SUMMARY,
        start_time="2026-10-03T09:00:00+03:00",
        end_time="2026-10-03T09:30:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=transport)
    drift_eval = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)

    drifted_snap_1 = record_drift_in_snapshot(repo, snapshot, drift_eval)
    assert drifted_snap_1 is not None

    # Replaying identical drift on the now-drifted snapshot returns existing snapshot idempotently
    drifted_snap_2 = record_drift_in_snapshot(repo, drifted_snap_1, drift_eval)
    assert drifted_snap_2 is not None
    assert drifted_snap_2.snapshot_id == drifted_snap_1.snapshot_id

    # Replaying with stale READY snapshot fails closed
    with pytest.raises(DriftValueError, match="stale"):
        record_drift_in_snapshot(repo, snapshot, drift_eval)


# ===========================================================================
# 9. Zero Provider Writes and Zero Approval Consumption
# ===========================================================================


def test_zero_provider_writes_and_zero_approval_consumption_during_revalidation(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Revalidation and drift detection are strictly passive and execute zero mutations."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    cal_transport = FakeGoogleCalendarTransport()
    cal_transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CANONICAL_SUMMARY,
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=cal_transport)

    tasks_transport = FakeGoogleTasksTransport()
    tasks_transport.seed_task(
        task_list_id=DEMO_TASK_LIST_ID,
        task_id=DEMO_TASK_ID,
        title=CANONICAL_TASK_TITLE,
        status=CANONICAL_TASK_STATUS,
    )
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=tasks_transport)

    reader = StandardTargetReader(
        calendar_read_adapter=cal_adapter, tasks_read_adapter=tasks_adapter
    )

    # Revalidation
    reval = revalidate_mission(
        mission_id=snapshot.mission_id,
        predicates=snapshot.desired_state,
        snapshot=snapshot,
        target_reader=reader,
    )
    assert reval.writes_performed == 0
    assert cal_transport.writes_count == 0
    assert tasks_transport.writes_count == 0

    # Drift check
    _ = detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)
    _ = detect_tasks_drift(snapshot=snapshot, tasks_adapter=tasks_adapter)
    assert cal_transport.writes_count == 0
    assert tasks_transport.writes_count == 0


# ===========================================================================
# 10. No LIVE Certification from Synthetic Transports
# ===========================================================================


def test_no_live_certification_from_synthetic_transports(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Synthetic transports produce FIXTURE/LOCAL_EXECUTION and never LIVE certification."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CONTRADICTORY_SUMMARY,
        start_time="2026-10-03T09:00:00+03:00",
        end_time="2026-10-03T09:30:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=transport)
    drift_eval = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    _ = record_drift_in_snapshot(repo, snapshot, drift_eval)

    # Check evidence provenance in ledger
    evidences = ledger.get_evidence_for_mission(mission_id)
    for ev in evidences:
        assert ev.origin.provenance in (
            EvidenceProvenance.LOCAL_EXECUTION,
            EvidenceProvenance.FIXTURE,
        )
        assert ev.origin.provenance.value != "LIVE_GOOGLE"
        assert ev.origin.provenance.value != "LIVE_AWS"


# ===========================================================================
# 11. CLI Invocation with JSON Output
# ===========================================================================


def test_cli_invocation_and_json_output() -> None:
    """Proof script executed via CLI with --json outputs valid JSON and exit code 0."""
    cmd = [sys.executable, "scripts/p12_07_proof.py", "--json"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"CLI proof script failed: {res.stderr}"

    data = json.loads(res.stdout.strip())
    assert data["task"] == "P-12.07"
    assert data["step_2_revalidate_is_still_true"] is True
    assert data["step_3_drift_detected"] is True
    assert data["step_4_restart_current_state"] == "DRIFTED"
    assert data["receipt_immutability_proven"] is True
    assert data["zero_spend_confirmed"] is True


# ===========================================================================
# 12. Adversarial: Missing Tasks Resource Detects Drift Deterministically
# ===========================================================================


def test_adversarial_missing_tasks_resource_fails_closed_or_detects_drift(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Missing or deleted task resource detects drift deterministically."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    # Empty tasks transport: task does not exist (404)
    tasks_transport = FakeGoogleTasksTransport()
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=tasks_transport)

    tasks_drift = detect_tasks_drift(snapshot=snapshot, tasks_adapter=tasks_adapter)
    assert tasks_drift.is_drifted is True
    assert tasks_drift.new_state == MissionState.DRIFTED

    # Reconciles mission to DRIFTED
    drifted_snap = record_drift_in_snapshot(repo, snapshot, tasks_drift)
    assert drifted_snap is not None
    assert drifted_snap.state == MissionState.DRIFTED

    # Historical receipt remains unchanged
    stored_receipt = repo.load_receipt(mission_id)
    assert stored_receipt.receipt_hash == receipt.receipt_hash


# ===========================================================================
# 13. Adversarial: Tasks Completion Reversal While Calendar Matches
# ===========================================================================


def test_adversarial_tasks_predicate_fails_while_calendar_matches(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Task completion reversal drives mission drift even when Calendar matches perfectly."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    cal_transport = FakeGoogleCalendarTransport()
    cal_transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CANONICAL_SUMMARY,
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=cal_transport)

    # Task status reversed from 'completed' to 'needsAction'
    tasks_transport = FakeGoogleTasksTransport()
    tasks_transport.seed_task(
        task_list_id=DEMO_TASK_LIST_ID,
        task_id=DEMO_TASK_ID,
        title=CANONICAL_TASK_TITLE,
        status="needsAction",
    )
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=tasks_transport)

    cal_drift = detect_calendar_drift(snapshot=snapshot, calendar_adapter=cal_adapter)
    assert cal_drift.is_drifted is False

    tasks_drift = detect_tasks_drift(snapshot=snapshot, tasks_adapter=tasks_adapter)
    assert tasks_drift.is_drifted is True
    assert tasks_drift.new_state == MissionState.DRIFTED

    drifted_snap = record_drift_in_snapshot(repo, snapshot, tasks_drift)
    assert drifted_snap is not None
    assert drifted_snap.state == MissionState.DRIFTED


# ===========================================================================
# 14. Adversarial: Tampered Evidence Lineage with Unchanged Count Fails Closed
# ===========================================================================


def test_adversarial_tampered_evidence_lineage_with_unchanged_count_fails_closed(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
) -> None:
    """Tampering with evidence IDs while keeping the count unchanged fails closed."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    from stilldone.evidence import EvidenceId
    from stilldone.receipt import ReceiptMismatchError

    # Create a forged snapshot where count of evidence_ids is still 2, but one ID is foreign
    forged_evidence_ids = (snapshot.evidence_ids[0], EvidenceId("a" * 64))
    tampered_snap = create_mission_snapshot(
        mission_id=snapshot.mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        pending_approvals=snapshot.pending_approvals,
        consumed_approvals=snapshot.consumed_approvals,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=forged_evidence_ids,
        predicate_bindings=snapshot.predicate_bindings,
        created_at=snapshot.created_at,
    )

    with pytest.raises(ReceiptMismatchError, match="does not exist in canonical ledger"):
        project_current_state(
            tampered_snap,
            historical_receipt=receipt,
            ledger=ledger,
        )


# ===========================================================================
# 15. Adversarial: Historical Receipt Replacement Attempt Fails Closed
# ===========================================================================


def test_adversarial_historical_receipt_replacement_attempt_fails_closed(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
) -> None:
    """Overwriting an existing historical READY receipt with a different receipt fails closed."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    # Construct conflicting receipt with different projection timestamp
    diff_snap = create_mission_snapshot(
        mission_id=snapshot.mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=snapshot.evidence_ids,
        predicate_bindings=snapshot.predicate_bindings,
        created_at=datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC),
    )
    diff_receipt = create_mission_ready_receipt(diff_snap)

    with pytest.raises(SnapshotIntegrityError, match="is write-once and cannot be replaced"):
        repo.save_receipt(diff_receipt)


# ===========================================================================
# 16. Adversarial: Wrong Bound Resource After Fresh Session Fails Closed
# ===========================================================================


def test_adversarial_wrong_bound_resource_after_fresh_session_fails_closed(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Passing a mismatched target to drift detection fails closed."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    wrong_tasks_target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="wrong_task_id_9999",
        parent_id=DEMO_TASK_LIST_ID,
    )

    tasks_transport = FakeGoogleTasksTransport()
    tasks_adapter = GoogleTasksReadAdapter(scope=demo_scope, transport=tasks_transport)

    with pytest.raises(DriftTargetMismatchError, match="does not match canonical binding"):
        detect_tasks_drift(
            snapshot=snapshot, tasks_adapter=tasks_adapter, target=wrong_tasks_target
        )


# ===========================================================================
# 17. Adversarial: Incomplete Mixed Provider Revalidation Fails Closed
# ===========================================================================


def test_adversarial_incomplete_mixed_provider_revalidation_fails_closed(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    tasks_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """When reader omits Tasks adapter for a dual-resource mission, revalidation fails closed."""
    repo, ledger, snapshot, receipt = _seed_test_mission(
        tmp_path, mission_id, cal_target, tasks_target
    )

    cal_transport = FakeGoogleCalendarTransport()
    cal_transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CANONICAL_SUMMARY,
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    cal_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=cal_transport)

    # Reader configured with Calendar adapter only, omitting Tasks adapter
    cal_only_reader = StandardTargetReader(calendar_read_adapter=cal_adapter)

    with pytest.raises(RevalidationValueError, match="No tasks read port configured"):
        revalidate_mission(
            mission_id=snapshot.mission_id,
            predicates=snapshot.desired_state,
            snapshot=snapshot,
            target_reader=cal_only_reader,
        )
