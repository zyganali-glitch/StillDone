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
    SnapshotLedgerConflictError,
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
) -> tuple[DurableSnapshotRepository, DurableFileLedger, MissionSnapshot, ReceiptProjection]:
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
