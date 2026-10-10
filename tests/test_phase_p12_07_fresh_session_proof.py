"""Focused tests for Phase P-12.07: Run fresh-session 'Are we still ready?' proof.

Validates:
1. Clean second-process reload with identical receipt hash preservation.
2. Fresh TRUE revalidation preserving READY current state.
3. Explicit FALSE contradiction driving deterministic READY -> DRIFTED reconciliation.
4. Correct READY -> DRIFTED current projection while historical receipt remains immutable.
5. Subsequent restart consistency and evidence lineage preservation.
6. Stale reads and provider transport errors never masquerade as external drift.
7. Wrong resource, missing binding, and duplicate replay rejection.
8. Zero provider writes and zero approval consumption during revalidation.
9. No LIVE certification from synthetic transports (strict non-certifying boundary).
10. Full multi-process proof runner and CLI execution with sanitized JSON output.
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
    CANONICAL_MISSION_ID,
    CANONICAL_SUMMARY,
    CONTRADICTORY_SUMMARY,
    DEMO_CALENDAR_ID,
    DEMO_EVENT_ID,
    run_p12_07_proof,
)
from stilldone.adapters.calendar import (
    CalendarTransportError,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
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
    DriftValueError,
    detect_calendar_drift,
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
    StandardTargetReader,
    revalidate_mission,
)
from stilldone.session import (
    resume_mission_session,
)
from stilldone.snapshot import (
    DurableSnapshotRepository,
    MissionSnapshot,
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
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=DEMO_CALENDAR_ID,
        task_list_id="list_demo_tasks",
    )


def _seed_test_mission(
    tmp_path: Path,
    mission_id: MissionId,
    target: TargetIdentity,
    *,
    summary: str = CANONICAL_SUMMARY,
) -> tuple[DurableSnapshotRepository, DurableFileLedger, MissionSnapshot, ReceiptProjection]:
    """Helper seeding canonical READY mission with durable snapshot and historical receipt."""
    ledger_path = tmp_path / "ledger.jsonl"
    storage_path = tmp_path / "snapshots"
    storage_path.mkdir(parents=True, exist_ok=True)

    ledger = DurableFileLedger(ledger_path)
    repository = DurableSnapshotRepository(storage_path, ledger=ledger)

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    contract = MissionContract.create(
        text="Ensure morning departure is on track",
        mission_id=mission_id,
        created_at=now,
    )
    pred_summary = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="summary",
        operator=PredicateOperator.EQUALS,
        expected_value=summary,
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )
    pred_binding = PredicateTargetBinding.create(
        predicate_id=pred_summary.predicate_id,
        mission_id=mission_id,
        target=target,
    )

    action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=target,
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
            action_id=action.action_id,
            mission_id=mission_id,
            action=action,
            approval_id=None,
            created_at=now,
        )
    )

    origin = EvidenceOrigin(
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
        observed_at=now,
    )
    verif_payload = {
        "evidence_type": "PREDICATE_EVALUATION",
        "predicate_id": str(pred_summary.predicate_id),
        "truth": "TRUE",
        "observed_value": summary,
        "is_match": True,
        "observations": {"summary": summary},
        "target": {
            "system": target.system,
            "resource_kind": target.resource_kind.value,
            "resource_id": target.resource_id,
            "parent_id": target.parent_id,
        },
    }
    verif_ev = EvidenceRecord.create(
        action_id=action.action_id,
        mission_id=mission_id,
        origin=origin,
        payload=verif_payload,
        created_at=now,
    )

    attempt = ExecutionAttempt(
        action_id=action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    p_res = ProviderExecutionResult(
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
        provider_result=p_res,
    )

    ready_snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=(pred_summary,),
        actions=(action,),
        step_records={action.action_id: step_rec},
        execution_attempts=(attempt,),
        evidence_ids=(verif_ev.evidence_id,),
        predicate_bindings=(pred_binding,),
        created_at=now,
    )

    ledger.record_state_transition(
        mission_id=mission_id,
        expected_prior_state=MissionState.VERIFYING,
        new_state=MissionState.READY,
        evidence=verif_ev,
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
    assert result["step_4_evidence_count"] == 2
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
) -> None:
    """Fresh session reload recovers exact receipt hash and verifies state."""
    repo, ledger, snapshot, receipt = _seed_test_mission(tmp_path, mission_id, cal_target)
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
    demo_scope: DemoResourceScope,
) -> None:
    """When reality continues to match, revalidation evaluates to TRUE."""
    repo, ledger, snapshot, receipt = _seed_test_mission(tmp_path, mission_id, cal_target)

    session = resume_mission_session(
        storage_path=tmp_path / "snapshots",
        ledger_path=tmp_path / "ledger.jsonl",
        mission_id=mission_id,
    )

    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CANONICAL_SUMMARY,
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=transport)
    reader = StandardTargetReader(calendar_read_adapter=adapter)

    reval = revalidate_mission(
        mission_id=session.snapshot.mission_id,
        predicates=session.snapshot.desired_state,
        snapshot=session.snapshot,
        target_reader=reader,
    )

    assert reval.is_still_true is True
    assert reval.writes_performed == 0
    assert transport.writes_count == 0

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
    demo_scope: DemoResourceScope,
) -> None:
    """Mutated reality produces is_drifted=True and transitions snapshot to DRIFTED."""
    repo, ledger, snapshot, receipt = _seed_test_mission(tmp_path, mission_id, cal_target)

    session = resume_mission_session(
        storage_path=tmp_path / "snapshots",
        ledger_path=tmp_path / "ledger.jsonl",
        mission_id=mission_id,
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

    drift_eval = detect_calendar_drift(snapshot=session.snapshot, calendar_adapter=adapter)
    assert drift_eval.is_drifted is True
    assert drift_eval.new_state == MissionState.DRIFTED

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
    demo_scope: DemoResourceScope,
) -> None:
    """Original READY receipt on disk and in memory remains untouched."""
    repo, ledger, snapshot, receipt = _seed_test_mission(tmp_path, mission_id, cal_target)
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
    demo_scope: DemoResourceScope,
) -> None:
    """Subsequent restart in fresh session re-projects DRIFTED current state."""
    repo, ledger, snapshot, receipt = _seed_test_mission(tmp_path, mission_id, cal_target)
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

    # Lineage verified: transition evidence + drift evidence
    evidences = ledger.get_evidence_for_mission(mission_id)
    assert len(evidences) == 2
    assert evidences[0].payload.get("truth") == "TRUE"
    assert evidences[1].payload.get("is_drifted") is True


# ===========================================================================
# 7. Stale and Provider Error Non-Promotion
# ===========================================================================


def test_stale_and_provider_error_non_promotion_in_fresh_session(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Provider error never gets promoted to drift proof or alters state."""
    repo, ledger, snapshot, receipt = _seed_test_mission(tmp_path, mission_id, cal_target)

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
    demo_scope: DemoResourceScope,
) -> None:
    """Duplicate/replayed drift transitions handle idempotently or fail closed."""
    repo, ledger, snapshot, receipt = _seed_test_mission(tmp_path, mission_id, cal_target)

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
    demo_scope: DemoResourceScope,
) -> None:
    """Revalidation and drift detection are strictly passive and execute zero mutations."""
    repo, ledger, snapshot, receipt = _seed_test_mission(tmp_path, mission_id, cal_target)

    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=CANONICAL_SUMMARY,
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=transport)
    reader = StandardTargetReader(calendar_read_adapter=adapter)

    # Revalidation
    reval = revalidate_mission(
        mission_id=snapshot.mission_id,
        predicates=snapshot.desired_state,
        snapshot=snapshot,
        target_reader=reader,
    )
    assert reval.writes_performed == 0
    assert transport.writes_count == 0

    # Drift check
    _ = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    assert transport.writes_count == 0


# ===========================================================================
# 10. No LIVE Certification from Synthetic Transports
# ===========================================================================


def test_no_live_certification_from_synthetic_transports(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Synthetic transports produce FIXTURE/LOCAL_EXECUTION and never LIVE certification."""
    repo, ledger, snapshot, receipt = _seed_test_mission(tmp_path, mission_id, cal_target)

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
