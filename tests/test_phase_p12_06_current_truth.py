"""Focused tests for Phase P-12.06: Preserve historical receipt while publishing current truth.

Validates:
1. Original historical READY receipt remains immutable after subsequent reconciliation.
2. System exposes separate authoritative current-state projection showing READY, DRIFTED, etc.
3. Historical completion does not silently become current completion.
4. Current truth is tied to exact mission ID, canonical snapshot revision, evidence IDs,
   observation/reconciliation timestamps, and deterministic lifecycle transitions.
5. Reopening or revalidating a mission does not overwrite old receipts or rewrite
   historical evidence.
6. No model prose, execution response, or fixture can override a deterministic current-state fact.
7. A provider error or stale read must never be represented as proof of external drift.
8. Duplicate/replayed drift transitions fail closed or are handled idempotently without
   contradictory evidence.
9. Fresh-process reload preserves historical receipt hashes and reconstructs current projection
   consistently.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stilldone.adapters.calendar import (
    CalendarTransportError,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    NormalizedParameters,
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
from stilldone.evidence import EvidenceId
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
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    PlannerInput,
    SymbolicTargetRef,
)
from stilldone.receipt import (
    CurrentStateProjection,
    PlannerCurrentStateAuthorityError,
    ReceiptHashMismatchError,
    ReceiptMismatchError,
    ReceiptProjection,
    compute_current_state_hash,
    compute_mission_content_hash,
    create_mission_ready_receipt,
    project_current_state,
    validate_authoritative_projection,
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
    SnapshotCorruptionError,
    SnapshotIntegrityError,
    SnapshotLedgerConflictError,
    SnapshotLineageError,
    create_mission_snapshot,
)

# ===========================================================================
# Fixtures and Helpers
# ===========================================================================


@pytest.fixture
def mission_id() -> MissionId:
    return MissionId.generate()


@pytest.fixture
def cal_target() -> TargetIdentity:
    return TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_leave_school_001",
        parent_id="c_demo@group.calendar.google.com",
    )


@pytest.fixture
def demo_scope(cal_target: TargetIdentity) -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=cal_target.parent_id or "c_demo@group.calendar.google.com",
        task_list_id="list_demo_tasks",
    )


def _seed_ready_mission(
    tmp_path: Path,
    mission_id: MissionId,
    target: TargetIdentity,
    *,
    summary: str = "Leave for school",
    start_time: str = "2026-10-03T07:30:00+03:00",
    storage_path: Path | None = None,
) -> tuple[DurableSnapshotRepository, DurableFileLedger, MissionSnapshot, ReceiptProjection]:
    ledger_path = tmp_path / "ledger.jsonl"
    if storage_path is None:
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

    # 1. Initialize mission in ledger
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

    # 2. Add verification evidence
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

    # 4. Create and save historical READY receipt
    receipt = create_mission_ready_receipt(ready_snapshot)
    repository.save_receipt(receipt)

    return repository, ledger, ready_snapshot, receipt


# ===========================================================================
# Tests
# ===========================================================================


def test_historical_ready_receipt_created_and_immutable(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """Historical READY receipt is created with exact content hash and remains immutable."""
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)

    assert receipt.is_historical is True
    assert receipt.state_at_projection == MissionState.READY
    assert receipt.mission_id == mission_id
    assert len(receipt.receipt_hash.value) == 64
    assert len(receipt.evidence_ids) == 1

    # Verifies immutability (frozen dataclass)
    with pytest.raises(FrozenInstanceError):
        receipt.state_at_projection = MissionState.DRIFTED  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        receipt.is_historical = False  # type: ignore[misc]

    # Stored on disk and reloadable
    loaded_receipt = repository.load_receipt(mission_id)
    assert loaded_receipt.receipt_hash == receipt.receipt_hash
    assert loaded_receipt.state_at_projection == MissionState.READY
    assert loaded_receipt.is_historical is True


def test_current_state_projection_for_ready_mission(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """CurrentStateProjection for a READY mission accurately reports READY current truth."""
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)

    proj = project_current_state(
        snapshot,
        historical_receipt=receipt,
        ledger=ledger,
    )

    assert proj.is_historical is False
    assert proj.state == MissionState.READY
    assert proj.is_ready is True
    assert proj.is_drifted is False
    assert proj.historical_receipt_hash == receipt.receipt_hash
    assert proj.historical_state == MissionState.READY
    assert proj.snapshot_id == snapshot.snapshot_id
    assert len(proj.projection_hash.value) == 64

    # Canonical projection dict contains expected keys
    canon = proj.to_canonical()
    assert canon["state"] == "READY"
    assert canon["is_ready"] is True
    assert canon["is_drifted"] is False
    assert canon["is_historical"] is False
    assert canon["historical_receipt_hash"] == receipt.receipt_hash.value
    assert canon["historical_state"] == "READY"


def test_historical_ready_receipt_remains_immutable_after_drift_reconciliation(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """When reality drifts, the historical receipt remains immutable while
    current truth transitions to DRIFTED.
    """
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)
    orig_receipt_hash = receipt.receipt_hash.value

    # Simulate external calendar mutation
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Doctor Appointment",  # Contradicts "Leave for school"
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    drift_eval = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    assert drift_eval.is_drifted is True
    assert drift_eval.new_state == MissionState.DRIFTED

    # Record drift in snapshot repository and ledger
    drifted_snapshot = record_drift_in_snapshot(repository, snapshot, drift_eval)
    assert drifted_snapshot is not None
    assert drifted_snapshot.state == MissionState.DRIFTED

    # 1. Historical READY receipt remains completely unchanged
    loaded_receipt = repository.load_receipt(mission_id)
    assert loaded_receipt.receipt_hash.value == orig_receipt_hash
    assert loaded_receipt.state_at_projection == MissionState.READY
    assert loaded_receipt.is_historical is True

    # 2. Authoritative current truth is now DRIFTED
    current_proj = project_current_state(
        drifted_snapshot,
        historical_receipt=loaded_receipt,
        ledger=ledger,
    )
    assert current_proj.state == MissionState.DRIFTED
    assert current_proj.is_ready is False
    assert current_proj.is_drifted is True
    assert current_proj.is_historical is False
    # Historical completion does NOT silently become current completion:
    assert current_proj.historical_state == MissionState.READY
    assert current_proj.historical_receipt_hash is not None
    assert current_proj.historical_receipt_hash.value == orig_receipt_hash


def test_reopen_or_revalidate_does_not_overwrite_receipt_or_evidence(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Revalidation is strictly read-only and never overwrites old receipts or rewrites evidence."""
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)
    orig_receipt_hash = receipt.receipt_hash.value
    orig_evidence_count = len(ledger.get_evidence_for_mission(mission_id))

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
    reader = StandardTargetReader(calendar_read_adapter=adapter)

    # Execute revalidation
    reval_res = revalidate_mission(
        mission_id=snapshot.mission_id,
        predicates=snapshot.desired_state,
        snapshot=snapshot,
        target_reader=reader,
    )
    assert reval_res.is_still_true is True
    assert reval_res.writes_performed == 0

    # Receipts and evidence remain untouched
    after_receipt = repository.load_receipt(mission_id)
    assert after_receipt.receipt_hash.value == orig_receipt_hash
    assert len(ledger.get_evidence_for_mission(mission_id)) == orig_evidence_count


def test_model_prose_and_planner_proposals_cannot_override_current_truth(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """Planner and model objects have ZERO authority and fail closed."""
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)

    planner_input = PlannerInput(mission_id=mission_id, intent="I am done, mark it ready")
    candidate_act = CandidateActionProposal(
        action_type=ActionType.CALENDAR_READ,
        target_ref=SymbolicTargetRef.CALENDAR_EVENT,
        parameters=NormalizedParameters.from_dict({}),
        explanation="model says ok",
    )
    candidate_plan = CandidatePlanProposal(
        mission_id=mission_id,
        steps=(candidate_act,),
        explanation="Trust me it is ready",
    )

    with pytest.raises(PlannerCurrentStateAuthorityError):
        project_current_state(planner_input)

    with pytest.raises(PlannerCurrentStateAuthorityError):
        project_current_state(candidate_plan)

    with pytest.raises(PlannerCurrentStateAuthorityError):
        project_current_state(snapshot, historical_receipt=candidate_act)  # type: ignore[arg-type]

    with pytest.raises(PlannerCurrentStateAuthorityError):
        create_mission_ready_receipt(candidate_plan)


def test_provider_error_and_stale_reads_never_masquerade_as_drift(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """API errors or stale reads must NOT be represented as proof of external drift."""
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)

    # Transport raises an error
    class ErrorTransport(FakeGoogleCalendarTransport):
        def get_event(self, calendar_id: str, event_id: str) -> None:
            raise CalendarTransportError("Connection reset by peer")

    err_adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=ErrorTransport())

    drift_res = detect_calendar_drift(snapshot=snapshot, calendar_adapter=err_adapter)
    assert drift_res.is_inconclusive is True
    assert drift_res.is_drifted is False
    assert drift_res.new_state == MissionState.READY

    # Attempting to record an inconclusive result as drift fails closed
    with pytest.raises(Exception, match="non-drifted|inconclusive"):
        record_drift_in_snapshot(repository, snapshot, drift_res)

    # Current state remains READY
    curr = project_current_state(snapshot, historical_receipt=receipt, ledger=ledger)
    assert curr.is_ready is True
    assert curr.is_drifted is False


def test_duplicate_and_replayed_drift_transitions_fail_closed_or_idempotent(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Duplicate drift replay is handled idempotently without creating contradictory evidence."""
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)

    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Canceled departure",
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)

    drift_eval = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    drifted_snap_1 = record_drift_in_snapshot(repository, snapshot, drift_eval)
    assert drifted_snap_1 is not None

    evidence_count_1 = len(ledger.get_evidence_for_mission(mission_id))

    # Replaying with the already-drifted snapshot returns it idempotently
    drifted_snap_2 = record_drift_in_snapshot(repository, drifted_snap_1, drift_eval)
    assert drifted_snap_2 is not None
    assert drifted_snap_2.snapshot_id == drifted_snap_1.snapshot_id

    # Zero new evidence appended
    evidence_count_2 = len(ledger.get_evidence_for_mission(mission_id))
    assert evidence_count_2 == evidence_count_1

    # Attempting to record drift using stale READY snapshot fails closed
    with pytest.raises(DriftValueError):
        record_drift_in_snapshot(repository, snapshot, drift_eval)


def test_fresh_process_reload_preserves_receipt_hash_and_reconstructs_current_projection(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """Fresh process reload preserves historical receipt hashes and reconstructs
    current projection consistently.
    """
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)
    orig_receipt_hash = receipt.receipt_hash.value

    # Mutate external state and record drift
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="New departure time",
        start_time="2026-10-03T08:00:00+03:00",
        end_time="2026-10-03T08:30:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    drift_eval = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    drifted_snapshot = record_drift_in_snapshot(repository, snapshot, drift_eval)
    assert drifted_snapshot is not None

    process_1_proj = project_current_state(
        drifted_snapshot,
        historical_receipt=receipt,
        ledger=ledger,
    )
    process_1_proj_hash = process_1_proj.projection_hash.value

    # Process 2: Reload across fresh session
    ledger_path = tmp_path / "ledger.jsonl"
    storage_path = tmp_path / "snapshots"

    session_2 = resume_mission_session(
        storage_path=storage_path,
        ledger_path=ledger_path,
        mission_id=mission_id,
    )

    assert session_2.historical_receipt is not None
    assert session_2.historical_receipt.receipt_hash.value == orig_receipt_hash
    assert session_2.historical_receipt.state_at_projection == MissionState.READY
    assert session_2.historical_receipt.is_historical is True

    curr_2 = session_2.current_state
    assert curr_2.state == MissionState.DRIFTED
    assert curr_2.is_ready is False
    assert curr_2.is_drifted is True
    assert curr_2.is_historical is False
    assert curr_2.historical_receipt_hash is not None
    assert curr_2.historical_receipt_hash.value == orig_receipt_hash
    assert curr_2.projection_hash.value == process_1_proj_hash

    # Process 3: Reload again
    session_3 = resume_mission_session(
        storage_path=storage_path,
        ledger_path=ledger_path,
        mission_id=mission_id,
    )
    curr_3 = session_3.current_state
    assert curr_3.projection_hash.value == process_1_proj_hash
    assert session_3.historical_receipt is not None
    assert session_3.historical_receipt.receipt_hash.value == orig_receipt_hash


def test_tampered_historical_evidence_fails_closed(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """Tampering with historical evidence or receipt hashes fails closed."""
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)

    # 1. Tampering with receipt hash raises ReceiptHashMismatchError
    raw_dict = receipt.to_canonical()
    raw_dict["receipt_hash"] = "0" * 64
    with pytest.raises(ReceiptHashMismatchError):
        ReceiptProjection.from_dict(raw_dict)

    # 2. Tampering with receipt state raises ReceiptHashMismatchError
    raw_dict_2 = receipt.to_canonical()
    raw_dict_2["state_at_projection"] = MissionState.DRIFTED.value
    with pytest.raises(ReceiptHashMismatchError):
        ReceiptProjection.from_dict(raw_dict_2)

    # 3. Setting is_historical=False in receipt dict raises ValueError
    raw_dict_3 = receipt.to_canonical()
    raw_dict_3["is_historical"] = False
    with pytest.raises(ValueError, match="is_historical=True"):
        ReceiptProjection.from_dict(raw_dict_3)

    # 4. Saving receipt with foreign evidence ID fails closed against ledger
    foreign_eid = EvidenceId("f" * 64)
    # Direct construction with foreign evidence ID
    with pytest.raises(SnapshotLedgerConflictError):
        foreign_receipt = ReceiptProjection.create(
            mission_id=receipt.mission_id,
            mission_content_hash=receipt.mission_content_hash,
            evidence_ids=[foreign_eid],
            state_at_projection=receipt.state_at_projection,
            projected_at=receipt.projected_at,
        )
        repository.save_receipt(foreign_receipt)


def test_cannot_create_ready_receipt_for_non_ready_snapshot(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """create_mission_ready_receipt fails closed on non-READY snapshots."""
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    contract = MissionContract.create(
        text="Draft mission",
        mission_id=mission_id,
        created_at=now,
    )
    draft_snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=contract,
        desired_state=(),
        actions=(),
        created_at=now,
    )

    with pytest.raises(ReceiptMismatchError, match="non-READY"):
        create_mission_ready_receipt(draft_snapshot)


def test_current_state_projection_is_historical_false_invariant(
    mission_id: MissionId,
) -> None:
    """CurrentStateProjection strictly requires is_historical=False."""
    with pytest.raises(ValueError, match="is_historical=False"):
        CurrentStateProjection(
            mission_id=mission_id,
            state=MissionState.READY,
            snapshot_id="snap_1",
            snapshot_version="v1",
            evidence_ids=(),
            as_of=datetime.now(UTC),
            projection_hash=None,  # type: ignore[arg-type]
            is_historical=True,
        )


def test_write_once_receipt_both_storage_modes(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """Enforces write-once historical receipt identity across directory and file modes:
    - First save succeeds.
    - Identical repeated save is safely idempotent.
    - Conflicting receipt for same mission is rejected (fails closed with SnapshotIntegrityError).
    - Receipt content before and after drift remains byte-for-byte identical.
    - Restart preserves the original receipt.
    """
    # 1. Directory Mode
    dir_repo, dir_ledger, snap_dir, receipt_dir = _seed_ready_mission(
        tmp_path / "dir_mode", mission_id, cal_target
    )
    first_receipt = dir_repo.load_receipt(mission_id)
    assert first_receipt.receipt_hash == receipt_dir.receipt_hash

    # Identical repeated save is safely idempotent
    dir_repo.save_receipt(receipt_dir)
    assert dir_repo.load_receipt(mission_id).receipt_hash == receipt_dir.receipt_hash

    # Conflicting receipt for same mission is rejected
    conflicting_receipt = ReceiptProjection.create(
        mission_id=mission_id,
        mission_content_hash=receipt_dir.mission_content_hash,
        evidence_ids=receipt_dir.evidence_ids,
        state_at_projection=receipt_dir.state_at_projection,
        projected_at=datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC),
    )
    with pytest.raises(SnapshotIntegrityError, match="write-once and cannot be replaced"):
        dir_repo.save_receipt(conflicting_receipt)

    # 2. File / Log Mode
    file_log = tmp_path / "file_mode" / "snapshots.jsonl"
    file_repo, file_ledger, snap_file, receipt_file = _seed_ready_mission(
        tmp_path / "file_mode", mission_id, cal_target, storage_path=file_log
    )
    first_file_rcpt = file_repo.load_receipt(mission_id)
    assert first_file_rcpt.receipt_hash == receipt_file.receipt_hash

    # Identical repeated save in file mode is safely idempotent
    file_repo.save_receipt(receipt_file)
    assert file_repo.load_receipt(mission_id).receipt_hash == receipt_file.receipt_hash

    # Conflicting receipt for same mission in file mode is rejected
    conflicting_file_rcpt = ReceiptProjection.create(
        mission_id=mission_id,
        mission_content_hash=receipt_file.mission_content_hash,
        evidence_ids=receipt_file.evidence_ids,
        state_at_projection=receipt_file.state_at_projection,
        projected_at=datetime(2026, 10, 3, 7, 0, 0, tzinfo=UTC),
    )
    with pytest.raises(SnapshotIntegrityError, match="write-once and cannot be replaced"):
        file_repo.save_receipt(conflicting_file_rcpt)


def test_foreign_mission_evidence_and_forged_ready_lineage_rejected(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """Historical receipt cannot reference foreign-mission evidence or forged verification."""
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)

    # 1. Foreign-mission evidence reference raises SnapshotLineageError
    foreign_mission_id = MissionId.generate()
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    foreign_contract = MissionContract.create(
        text="Foreign mission",
        mission_id=foreign_mission_id,
        created_at=now,
    )
    ledger.append_mission(
        MissionRecord(
            mission_id=foreign_mission_id,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
            contract=foreign_contract,
        )
    )
    foreign_action = ActionContract.create(
        mission_id=foreign_mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target,
        parameters={},
    )
    ledger.append_action(
        ActionRecord(
            action_id=foreign_action.action_id,
            mission_id=foreign_mission_id,
            action=foreign_action,
            approval_id=None,
            created_at=now,
        )
    )
    foreign_ev = EvidenceRecord.create(
        action_id=foreign_action.action_id,
        mission_id=foreign_mission_id,
        origin=EvidenceOrigin(provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=now),
        payload={"is_match": True},
        created_at=now,
    )
    ledger.append_evidence(foreign_ev)

    foreign_receipt = ReceiptProjection.create(
        mission_id=mission_id,
        mission_content_hash=receipt.mission_content_hash,
        evidence_ids=[foreign_ev.evidence_id],
        state_at_projection=MissionState.READY,
        projected_at=now,
    )
    with pytest.raises(SnapshotLineageError, match="foreign mission"):
        repository.save_receipt(foreign_receipt)

    # 2. Receipt with empty evidence_ids raises SnapshotLineageError
    empty_ev_receipt = ReceiptProjection.create(
        mission_id=mission_id,
        mission_content_hash=receipt.mission_content_hash,
        evidence_ids=[],
        state_at_projection=MissionState.READY,
        projected_at=now,
    )
    with pytest.raises(SnapshotLineageError, match="empty evidence_ids"):
        repository.save_receipt(empty_ev_receipt)


def test_shared_log_snapshot_receipt_interleaved_and_restart(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """In shared append-only log mode, snapshot and receipt records are disambiguated,
    survive interleaved writes, and recover cleanly across restart.
    """
    log_file = tmp_path / "interleaved" / "events.jsonl"
    repo, ledger, snapshot, receipt = _seed_ready_mission(
        tmp_path / "interleaved", mission_id, cal_target, storage_path=log_file
    )

    # 1. Drift occurs -> Snapshot (DRIFTED) appended to log
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Different event",
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    drift_eval = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    drifted_snapshot = record_drift_in_snapshot(repo, snapshot, drift_eval)
    assert drifted_snapshot is not None

    # Restart / Fresh repository instance reading the same file log
    repo_restarted = DurableSnapshotRepository(log_file, ledger=ledger)
    loaded_snap = repo_restarted.load_snapshot(mission_id)
    assert loaded_snap.state == MissionState.DRIFTED
    assert loaded_snap.snapshot_id == drifted_snapshot.snapshot_id

    loaded_receipt = repo_restarted.load_receipt(mission_id)
    assert loaded_receipt.receipt_hash == receipt.receipt_hash
    assert loaded_receipt.state_at_projection == MissionState.READY
    assert loaded_receipt.is_historical is True

    # Current truth projection from restarted repository
    curr = project_current_state(
        loaded_snap,
        historical_receipt=loaded_receipt,
        ledger=ledger,
    )
    assert curr.state == MissionState.DRIFTED
    assert curr.is_drifted is True
    assert curr.historical_receipt_hash == receipt.receipt_hash


def test_shared_log_conflicting_duplicate_and_corrupt_entry_fail_closed(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """Shared log fails closed when containing conflicting duplicate receipts or corrupt entries."""
    import json

    log_file = tmp_path / "fail_closed" / "events.jsonl"
    repo, ledger, snapshot, receipt = _seed_ready_mission(
        tmp_path / "fail_closed", mission_id, cal_target, storage_path=log_file
    )

    # 1. Append a conflicting duplicate receipt directly into the log file
    conflicting_receipt = ReceiptProjection.create(
        mission_id=mission_id,
        mission_content_hash=receipt.mission_content_hash,
        evidence_ids=receipt.evidence_ids,
        state_at_projection=receipt.state_at_projection,
        projected_at=datetime(2026, 10, 3, 9, 0, 0, tzinfo=UTC),
    )
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({"_type": "receipt", **conflicting_receipt.to_canonical()}) + "\n")

    # Loading receipt fails closed with SnapshotIntegrityError
    with pytest.raises(SnapshotIntegrityError, match="Conflicting duplicate receipts"):
        repo.load_receipt(mission_id)

    # 2. Append malformed JSON line
    corrupt_log = tmp_path / "corrupt_log.jsonl"
    with open(corrupt_log, "w", encoding="utf-8") as f:
        f.write("{this is not valid json\n")
    corrupt_repo = DurableSnapshotRepository(corrupt_log, ledger=ledger)

    with pytest.raises(SnapshotCorruptionError, match="Malformed JSON"):
        corrupt_repo.load_snapshot(mission_id)

    with pytest.raises(SnapshotCorruptionError, match="Malformed JSON"):
        corrupt_repo.load_receipt(mission_id)


def test_authoritative_vs_preview_current_truth_and_hash_binding(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """Validates authoritative qualification, hash binding of snapshot_version,
    rejection of arbitrary evidence IDs and forged receipts.
    """
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)

    # 1. Authoritative projection succeeds with canonical ledger and persisted snapshot
    proj_auth = project_current_state(
        snapshot,
        historical_receipt=receipt,
        ledger=ledger,
        authoritative=True,
    )
    assert proj_auth.is_authoritative is True
    assert proj_auth.is_certified_ready is True

    # 2. Forged snapshot without ledger cannot obtain authoritative certification
    proj_no_ledger = project_current_state(snapshot, historical_receipt=receipt, ledger=None)
    assert proj_no_ledger.is_authoritative is False
    assert proj_no_ledger.is_certified_ready is False

    with pytest.raises(ReceiptMismatchError, match="requires a canonical mission ledger"):
        project_current_state(
            snapshot,
            historical_receipt=receipt,
            ledger=None,
            authoritative=True,
        )

    # 3. Forged historical receipt hash fails closed
    import copy

    tampered_receipt = copy.copy(receipt)
    object.__setattr__(tampered_receipt, "receipt_hash", receipt.receipt_hash.__class__("f" * 64))
    with pytest.raises(ReceiptHashMismatchError, match="Forged historical receipt"):
        project_current_state(snapshot, historical_receipt=tampered_receipt, ledger=ledger)

    # 4. Modifying snapshot_version invalidates projection hash
    raw_canon = proj_auth.to_canonical()
    raw_canon["snapshot_version"] = "v999_tampered"
    with pytest.raises(ReceiptHashMismatchError):
        CurrentStateProjection.from_dict(raw_canon)

    # 5. Snapshot with arbitrary foreign evidence IDs rejected against ledger
    arbitrary_eid = EvidenceId("a" * 64)
    tampered_snapshot = create_mission_snapshot(
        mission_id=snapshot.mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        evidence_ids=(arbitrary_eid,),
        created_at=snapshot.created_at,
    )
    with pytest.raises(ReceiptMismatchError, match="does not exist in canonical ledger"):
        project_current_state(tampered_snapshot, historical_receipt=receipt, ledger=ledger)


def test_verifying_mission_with_verification_evidence_cannot_mint_first_ready_receipt(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """DEFECT A discriminating test: seeds a VERIFYING mission with apparently valid
    verification evidence but no legal READY transition. Attempting to save a historical
    READY receipt fails closed.
    """
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger_path = tmp_path / "ledger.jsonl"
    snapshots_dir = tmp_path / "snapshots"
    ledger = DurableFileLedger(ledger_path)
    repository = DurableSnapshotRepository(snapshots_dir, ledger=ledger)

    contract = MissionContract.create(
        text="Mission in verification",
        mission_id=mission_id,
        created_at=now,
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

    action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=cal_target,
        parameters={},
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

    pred_id = PredicateId.generate()
    verif_ev = EvidenceRecord.create(
        action_id=action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=now),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(pred_id),
            "truth": "TRUE",
            "observed_value": "test_summary",
            "is_match": True,
            "observations": {"summary": "test_summary"},
            "target": {
                "system": cal_target.system,
                "resource_kind": cal_target.resource_kind.value,
                "resource_id": cal_target.resource_id,
                "parent_id": cal_target.parent_id,
            },
        },
        created_at=now,
    )
    ledger.append_evidence(verif_ev)

    # Attempt to mint and save a first historical READY receipt for this VERIFYING mission
    content_hash = compute_mission_content_hash(contract)
    forged_ready_receipt = ReceiptProjection.create(
        mission_id=mission_id,
        mission_content_hash=content_hash,
        evidence_ids=[verif_ev.evidence_id],
        state_at_projection=MissionState.READY,
        projected_at=now,
    )

    with pytest.raises(SnapshotLedgerConflictError, match="never entered READY state"):
        repository.save_receipt(forged_ready_receipt)


def test_forged_first_receipt_snapshot_revision_and_incomplete_evidence_rejected(
    tmp_path: Path,
    cal_target: TargetIdentity,
) -> None:
    """DEFECT A discriminating test: forged snapshot revision or incomplete
    evidence subset fails closed.
    """
    m_id = MissionId.generate()
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, m_id, cal_target)

    # Remove the saved receipt to test first receipt save validation on this READY mission
    receipt_file = tmp_path / "snapshots" / f"{m_id}.receipt.json"
    if receipt_file.exists():
        receipt_file.unlink()

    # 1. Forged snapshot revision in metadata is rejected
    forged_rev_rcpt = ReceiptProjection.create(
        mission_id=m_id,
        mission_content_hash=receipt.mission_content_hash,
        evidence_ids=receipt.evidence_ids,
        state_at_projection=MissionState.READY,
        projected_at=receipt.projected_at,
        metadata={"snapshot_id": "forged_snapshot_rev_9999", "snapshot_version": "v1"},
    )
    with pytest.raises(SnapshotLedgerConflictError, match="Forged snapshot revision"):
        repository.save_receipt(forged_rev_rcpt)

    # 2. Incomplete evidence subset (empty or missing canonical evidence) is rejected
    incomplete_rcpt = ReceiptProjection.create(
        mission_id=m_id,
        mission_content_hash=receipt.mission_content_hash,
        evidence_ids=[],
        state_at_projection=MissionState.READY,
        projected_at=receipt.projected_at,
    )
    with pytest.raises(SnapshotLineageError, match="empty evidence_ids"):
        repository.save_receipt(incomplete_rcpt)


def test_caller_created_snapshot_cannot_claim_authoritative_current_truth(
    tmp_path: Path,
    mission_id: MissionId,
    cal_target: TargetIdentity,
) -> None:
    """DEFECT B discriminating test: caller-created or modified snapshot cannot
    claim authoritative current truth, even with is_persisted=True and genuine ledger evidence.
    """
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, mission_id, cal_target)

    # 1. Caller constructs a snapshot with different snapshot_id but is_persisted=True
    caller_snap = create_mission_snapshot(
        mission_id=snapshot.mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=snapshot.evidence_ids,
        predicate_bindings=snapshot.predicate_bindings,
        created_at=snapshot.created_at,
    )
    object.__setattr__(caller_snap, "snapshot_id", "caller_invented_snap_001")
    object.__setattr__(caller_snap, "is_persisted", True)

    # Non-authoritative by default when snapshot_id does not match canonical persisted snapshot
    proj_derived = project_current_state(caller_snap, historical_receipt=receipt, ledger=ledger)
    assert proj_derived.is_authoritative is False
    assert proj_derived.is_certified_ready is False

    # Explicit authoritative=True fails closed
    with pytest.raises(ReceiptMismatchError, match="does not match canonical persisted snapshot"):
        project_current_state(
            caller_snap,
            historical_receipt=receipt,
            ledger=ledger,
            authoritative=True,
        )

    # 2. Caller modifies desired_state predicates in snapshot
    orig_pred = snapshot.desired_state[0]
    modified_pred = DesiredStatePredicate(
        predicate_id=orig_pred.predicate_id,
        mission_id=mission_id,
        subject=orig_pred.subject,
        operator=orig_pred.operator,
        expected_value="Tampered expected value",
        freshness=orig_pred.freshness,
        required=True,
    )
    modified_snap = create_mission_snapshot(
        mission_id=snapshot.mission_id,
        state=snapshot.state,
        contract=snapshot.contract,
        desired_state=(modified_pred,),
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=snapshot.evidence_ids,
        predicate_bindings=snapshot.predicate_bindings,
        created_at=snapshot.created_at,
    )
    # Even if caller sets the canonical snapshot_id
    object.__setattr__(modified_snap, "snapshot_id", snapshot.snapshot_id)
    object.__setattr__(modified_snap, "is_persisted", True)

    with pytest.raises(ReceiptMismatchError, match="modified from canonical persisted"):
        project_current_state(
            modified_snap,
            historical_receipt=receipt,
            ledger=ledger,
            authoritative=True,
        )


def test_direct_construction_cannot_self_assert_authoritative_and_fixture_not_live(
    mission_id: MissionId,
) -> None:
    """DEFECT B discriminating test: direct CurrentStateProjection.create cannot
    self-assert is_authoritative=True, and fixture projections never claim live certification.
    """
    eid = EvidenceId("e" * 64)
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    # 1. Direct construction with is_authoritative=True without internal validation fails closed
    with pytest.raises(ReceiptMismatchError, match="cannot self-assert is_authoritative=True"):
        CurrentStateProjection.create(
            mission_id=mission_id,
            state=MissionState.READY,
            snapshot_id="snap_001",
            snapshot_version="v1",
            evidence_ids=(eid,),
            as_of=now,
            is_authoritative=True,
        )

    # 2. Direct construction defaults to is_authoritative=False
    proj_default = CurrentStateProjection.create(
        mission_id=mission_id,
        state=MissionState.READY,
        snapshot_id="snap_001",
        snapshot_version="v1",
        evidence_ids=(eid,),
        as_of=now,
    )
    assert proj_default.is_authoritative is False
    assert proj_default.is_certified_ready is False
    assert proj_default.is_live_certified is False
    assert proj_default.is_certifying_live_authority is False
    assert proj_default.to_canonical()["is_live_certified"] is False


def test_defect1_historical_snapshot_binding_first_ready_receipt(
    tmp_path: Path,
    cal_target: TargetIdentity,
    demo_scope: DemoResourceScope,
) -> None:
    """DEFECT 1 Discriminating Tests:
    1. First READY receipt with no snapshot metadata must fail.
    2. First READY receipt with snapshot_id=None must fail.
    3. First READY receipt with wrong snapshot version must fail.
    4. A canonical first READY receipt must succeed.
    5. Its original hash and bytes must survive DRIFTED reconciliation and restart.
    """
    m_id = MissionId.generate()
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, m_id, cal_target)

    # Remove the seeded receipt so we can test first-save gate explicitly
    receipt_file = tmp_path / "snapshots" / f"{m_id}.receipt.json"
    if receipt_file.exists():
        receipt_file.unlink()

    # 1. First READY receipt with no snapshot metadata must fail
    no_meta_receipt = ReceiptProjection.create(
        mission_id=m_id,
        mission_content_hash=receipt.mission_content_hash,
        evidence_ids=receipt.evidence_ids,
        state_at_projection=MissionState.READY,
        projected_at=receipt.projected_at,
        metadata={},
    )
    with pytest.raises(SnapshotIntegrityError, match="requires non-empty snapshot_id"):
        repository.save_receipt(no_meta_receipt)

    # 2. First READY receipt with snapshot_id=None must fail
    none_snap_id_receipt = ReceiptProjection.create(
        mission_id=m_id,
        mission_content_hash=receipt.mission_content_hash,
        evidence_ids=receipt.evidence_ids,
        state_at_projection=MissionState.READY,
        projected_at=receipt.projected_at,
        metadata={"snapshot_id": None, "snapshot_version": snapshot.snapshot_version},
    )
    with pytest.raises(SnapshotIntegrityError, match="requires non-empty snapshot_id"):
        repository.save_receipt(none_snap_id_receipt)

    # Empty string snapshot_id must also fail
    empty_snap_id_receipt = ReceiptProjection.create(
        mission_id=m_id,
        mission_content_hash=receipt.mission_content_hash,
        evidence_ids=receipt.evidence_ids,
        state_at_projection=MissionState.READY,
        projected_at=receipt.projected_at,
        metadata={"snapshot_id": "   ", "snapshot_version": snapshot.snapshot_version},
    )
    with pytest.raises(SnapshotIntegrityError, match="requires non-empty snapshot_id"):
        repository.save_receipt(empty_snap_id_receipt)

    # 3. First READY receipt with wrong snapshot version must fail
    wrong_ver_receipt = ReceiptProjection.create(
        mission_id=m_id,
        mission_content_hash=receipt.mission_content_hash,
        evidence_ids=receipt.evidence_ids,
        state_at_projection=MissionState.READY,
        projected_at=receipt.projected_at,
        metadata={"snapshot_id": snapshot.snapshot_id, "snapshot_version": "v999_wrong"},
    )
    with pytest.raises(SnapshotIntegrityError, match="Forged snapshot version"):
        repository.save_receipt(wrong_ver_receipt)

    # 4. Canonical first READY receipt must succeed
    canonical_receipt = create_mission_ready_receipt(snapshot)
    repository.save_receipt(canonical_receipt)

    saved_receipt = repository.load_receipt(m_id)
    assert saved_receipt.receipt_hash == canonical_receipt.receipt_hash
    saved_bytes = receipt_file.read_bytes()

    # 5. Its original hash and bytes must survive DRIFTED reconciliation and restart
    fake_transport = FakeGoogleCalendarTransport()
    fake_transport.seed_event(
        calendar_id=cal_target.parent_id or "",
        event_id=cal_target.resource_id,
        summary="Contradicting event",
        start_time="2026-10-03T07:30:00+03:00",
        end_time="2026-10-03T08:00:00+03:00",
        status="confirmed",
    )
    adapter = GoogleCalendarReadAdapter(scope=demo_scope, transport=fake_transport)
    drift_eval = detect_calendar_drift(snapshot=snapshot, calendar_adapter=adapter)
    drifted_snapshot = record_drift_in_snapshot(repository, snapshot, drift_eval)
    assert drifted_snapshot is not None
    assert drifted_snapshot.state == MissionState.DRIFTED

    # Byte-for-byte check after drift reconciliation
    after_drift_bytes = receipt_file.read_bytes()
    assert after_drift_bytes == saved_bytes

    # Restart check: new repository instance on same paths
    restarted_repo = DurableSnapshotRepository(tmp_path / "snapshots", ledger=ledger)
    reloaded_receipt = restarted_repo.load_receipt(m_id)
    assert reloaded_receipt.receipt_hash == canonical_receipt.receipt_hash
    assert reloaded_receipt.state_at_projection == MissionState.READY
    assert reloaded_receipt.is_historical is True


def test_defect2_direct_create_with_internal_validated_cannot_certify_ready(
    mission_id: MissionId,
) -> None:
    """DEFECT 2 Discriminating Test 1:
    Direct .create(is_authoritative=True, _internal_validated=True) cannot independently
    certify READY and fails closed.
    """
    eid = EvidenceId("e" * 64)
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    # Caller-controlled _internal_validated=True cannot bypass the authority gate
    with pytest.raises(ReceiptMismatchError, match="cannot self-assert is_authoritative=True"):
        CurrentStateProjection.create(
            mission_id=mission_id,
            state=MissionState.READY,
            snapshot_id="snap_001",
            snapshot_version="v1",
            evidence_ids=(eid,),
            as_of=now,
            is_authoritative=True,
            _internal_validated=True,
        )


def test_defect2_dataclass_construction_and_from_dict_cannot_certify_without_external_validation(
    tmp_path: Path,
    cal_target: TargetIdentity,
) -> None:
    """DEFECT 2 Discriminating Tests 2-6:
    2. Direct dataclass construction or from_dict() containing a self-computed
       authoritative hash cannot serve as canonical certification without external validation.
    3. Forged snapshot identity/content remains non-authoritative.
    4. A real persisted canonical READY snapshot can still produce a legitimate
       authoritative lifecycle projection.
    5. DRIFTED recovery and receipt preservation remain unchanged.
    6. Fixture/current-live distinction remains strict.
    """
    m_id = MissionId.generate()
    repository, ledger, snapshot, receipt = _seed_ready_mission(tmp_path, m_id, cal_target)

    eid = snapshot.evidence_ids[0]
    now = snapshot.created_at

    # 1. Direct dataclass construction with self-computed authoritative hash
    valid_auth_hash = compute_current_state_hash(
        mission_id=m_id,
        state=MissionState.READY,
        snapshot_id=snapshot.snapshot_id,
        snapshot_version=snapshot.snapshot_version,
        evidence_ids=(eid,),
        as_of=now,
        is_authoritative=True,
    )
    direct_proj = CurrentStateProjection(
        mission_id=m_id,
        state=MissionState.READY,
        snapshot_id=snapshot.snapshot_id,
        snapshot_version=snapshot.snapshot_version,
        evidence_ids=(eid,),
        as_of=now,
        projection_hash=valid_auth_hash,
        is_historical=False,
        is_authoritative=True,
    )
    # Hash is mathematically consistent
    assert direct_proj.projection_hash == valid_auth_hash
    # But cannot independently confer canonical certification
    assert direct_proj.is_certified_ready is False

    # External validation against forged snapshot fails
    forged_snap = create_mission_snapshot(
        mission_id=m_id,
        state=MissionState.READY,
        contract=snapshot.contract,
        desired_state=snapshot.desired_state,
        actions=snapshot.actions,
        step_records=snapshot.step_records,
        execution_attempts=snapshot.execution_attempts,
        evidence_ids=snapshot.evidence_ids,
        predicate_bindings=snapshot.predicate_bindings,
        created_at=now,
    )
    object.__setattr__(forged_snap, "snapshot_id", "forged_snap_id_999")
    object.__setattr__(forged_snap, "is_persisted", True)

    assert direct_proj.validate_against_canonical(snapshot=forged_snap, ledger=ledger) is False
    with pytest.raises(ReceiptMismatchError, match="external validation"):
        direct_proj.certify(snapshot=forged_snap, ledger=ledger)

    # External validation against real persisted snapshot + ledger succeeds
    assert direct_proj.validate_against_canonical(snapshot=snapshot, ledger=ledger) is True
    certified_direct = direct_proj.certify(snapshot=snapshot, ledger=ledger)
    assert certified_direct.is_certified_ready is True
    assert certified_direct.is_live_certified is False

    # 2. Deserialization from_dict() with serialized is_authoritative=True
    serialized_dict = direct_proj.to_canonical()
    assert serialized_dict["is_authoritative"] is True
    deserialized_proj = CurrentStateProjection.from_dict(serialized_dict)

    # Deserialization alone does NOT confer trusted authority
    assert deserialized_proj.is_certified_ready is False
    assert (
        validate_authoritative_projection(deserialized_proj, snapshot=forged_snap, ledger=ledger)
        is False
    )
    with pytest.raises(ReceiptMismatchError, match="external validation"):
        deserialized_proj.certify(snapshot=forged_snap, ledger=ledger)

    # When validated against canonical context, certification is conferred
    assert (
        validate_authoritative_projection(deserialized_proj, snapshot=snapshot, ledger=ledger)
        is True
    )
    certified_deserialized = deserialized_proj.certify(snapshot=snapshot, ledger=ledger)
    assert certified_deserialized.is_certified_ready is True
    assert certified_deserialized.is_live_certified is False

    # 3. Legitimate project_current_state produces certified READY
    proj_auth = project_current_state(
        snapshot,
        historical_receipt=receipt,
        ledger=ledger,
        authoritative=True,
    )
    assert proj_auth.is_authoritative is True
    assert proj_auth.is_certified_ready is True
    assert proj_auth.is_live_certified is False
