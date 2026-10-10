"""Tests for Durable Mission Snapshot Repository (Phase P-12.01).

Validates:
- Complete durable round trip preserving full mission identity and contracts.
- Inconsistent identity and lineage rejection fail-closed.
- Corruption and truncated file rejection fail-closed.
- Unknown version rejection fail-closed.
- Partial write / atomic replacement resilience.
- Snapshot and ledger consistency validation.
- Model / planner proposal rejection fail-closed.
- Never silently turns missing/corrupted data into READY.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from stilldone.approval_consumption import (
    ApprovalConsumptionRecord,
    ApprovalUsageStatus,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalId,
    BindingHash,
)
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    FreshnessMode,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot
from stilldone.evidence import EvidenceId
from stilldone.execution.state import (
    ActionExecutionStatus,
    ProviderExecutionResult,
    StepExecutionRecord,
)
from stilldone.ledger import (
    ActionRecord,
    DurableFileLedger,
    MissionRecord,
)
from stilldone.planning.contracts import (
    PlannerInput,
)
from stilldone.snapshot import (
    CANONICAL_SNAPSHOT_VERSION,
    DurableSnapshotRepository,
    MissionSnapshot,
    PlannerSnapshotAuthorityError,
    SnapshotCorruptionError,
    SnapshotIntegrityError,
    SnapshotLedgerConflictError,
    SnapshotLineageError,
    SnapshotNotFoundError,
    UnknownSnapshotVersionError,
    create_mission_snapshot,
)


@pytest.fixture
def mission_id() -> MissionId:
    return MissionId.generate()


@pytest.fixture
def intent(mission_id: MissionId) -> UserIntentSnapshot:
    return UserIntentSnapshot(
        text="Get my family ready for tomorrow morning. We need to leave by 7:30.",
        captured_at=datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC),
        mission_id=mission_id,
    )


@pytest.fixture
def contract(mission_id: MissionId, intent: UserIntentSnapshot) -> MissionContract:
    return MissionContract(
        mission_id=mission_id,
        intent=intent,
        created_at=datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC),
        schema_version="v1",
    )


@pytest.fixture
def sample_action(mission_id: MissionId) -> ActionContract:
    target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_leave_school_001",
        parent_id="c_demo_calendar@group.calendar.google.com",
    )
    return ActionContract(
        action_id=ActionId.generate(),
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_UPDATE,
        target=target,
        parameters=NormalizedParameters.from_dict(
            {
                "start_time": "2026-10-03T07:30:00+03:00",
                "summary": "Leave for school",
            }
        ),
    )


@pytest.fixture
def sample_predicate(mission_id: MissionId) -> DesiredStatePredicate:
    return DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=mission_id,
        subject="start_time",
        operator=PredicateOperator.EQUALS,
        expected_value="2026-10-03T07:30:00+03:00",
        freshness=FreshnessContract(mode=FreshnessMode.MAX_AGE, max_age_seconds=300),
        required=True,
    )


def test_durable_snapshot_round_trip_directory_mode(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    repo = DurableSnapshotRepository(tmp_path)

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.VERIFYING,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        action_dependencies={sample_action.action_id: ()},
        created_at=datetime(2026, 10, 3, 6, 10, 0, tzinfo=UTC),
    )

    repo.save_snapshot(snapshot)

    # Load back in fresh instance
    loaded = repo.load_snapshot(mission_id)
    assert loaded.snapshot_id == snapshot.snapshot_id
    assert loaded.snapshot_version == CANONICAL_SNAPSHOT_VERSION
    assert loaded.mission_id == mission_id
    assert loaded.state == MissionState.VERIFYING
    assert loaded.contract == contract
    assert len(loaded.actions) == 1
    assert loaded.actions[0] == sample_action
    assert len(loaded.desired_state) == 1
    assert loaded.desired_state[0] == sample_predicate
    assert sample_action.action_id in loaded.step_records
    assert loaded.step_records[sample_action.action_id].status == ActionExecutionStatus.NOT_RUN


def test_durable_snapshot_round_trip_file_mode(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    log_file = tmp_path / "snapshots.jsonl"
    repo = DurableSnapshotRepository(log_file)

    now = datetime(2026, 10, 3, 6, 15, 0, tzinfo=UTC)
    from stilldone.approval_consumption import ApprovalConsumptionRecord, ApprovalUsageStatus
    from stilldone.domain.authority import ApprovalId, BindingHash

    consumed_appr = ApprovalConsumptionRecord(
        approval_id=ApprovalId.generate(),
        mission_id=mission_id,
        action_id=sample_action.action_id,
        binding_hash=BindingHash("0" * 64),
        status=ApprovalUsageStatus.CONSUMED,
        consumed_at=now,
        attempt_number=1,
        reason="Human approved",
    )
    attempt = ExecutionAttempt(
        action_id=sample_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    provider_result = ProviderExecutionResult(
        action_type=ActionType.CALENDAR_UPDATE,
        success=True,
        status_name="UPDATED",
        writes_performed=1,
        captured_at=now,
    )
    step_rec = StepExecutionRecord(
        action_id=sample_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=attempt,
        provider_result=provider_result,
    )
    evidence_id = EvidenceId("e" * 64)

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        step_records={sample_action.action_id: step_rec},
        consumed_approvals=[consumed_appr],
        execution_attempts=[attempt],
        evidence_ids=[evidence_id],
        created_at=now,
    )

    repo.save_snapshot(snapshot)

    # Fresh repository instance pointing to the same file
    fresh_repo = DurableSnapshotRepository(log_file)
    loaded = fresh_repo.load_snapshot(mission_id)
    assert loaded.mission_id == mission_id
    assert loaded.state == MissionState.READY
    assert (
        loaded.step_records[sample_action.action_id].status
        == ActionExecutionStatus.EXECUTION_SUCCEEDED
    )
    assert loaded.evidence_ids == (evidence_id,)


def test_inconsistent_identity_and_lineage_rejection(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    foreign_mission_id = MissionId.generate()

    # Foreign predicate
    foreign_pred = DesiredStatePredicate(
        predicate_id=PredicateId.generate(),
        mission_id=foreign_mission_id,
        subject="status",
        operator=PredicateOperator.EQUALS,
        expected_value="confirmed",
        freshness=FreshnessContract(mode=FreshnessMode.CURRENT),
        required=True,
    )
    with pytest.raises(SnapshotLineageError, match="does not match snapshot mission"):
        create_mission_snapshot(
            mission_id=mission_id,
            state=MissionState.DRAFT,
            contract=contract,
            desired_state=[foreign_pred],
            actions=[sample_action],
        )

    # Foreign action
    foreign_target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_other",
    )
    foreign_action = ActionContract(
        action_id=ActionId.generate(),
        mission_id=foreign_mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=foreign_target,
        parameters=NormalizedParameters.from_dict({}),
    )
    with pytest.raises(SnapshotLineageError, match="does not match snapshot mission"):
        create_mission_snapshot(
            mission_id=mission_id,
            state=MissionState.DRAFT,
            contract=contract,
            desired_state=[sample_predicate],
            actions=[foreign_action],
        )


def test_unknown_snapshot_version_rejected(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    with pytest.raises(UnknownSnapshotVersionError, match="Unsupported snapshot version"):
        create_mission_snapshot(
            mission_id=mission_id,
            state=MissionState.DRAFT,
            contract=contract,
            desired_state=[sample_predicate],
            actions=[sample_action],
            snapshot_version="v99",
        )


def test_corruption_and_truncated_file_fail_closed(
    tmp_path: Path,
    mission_id: MissionId,
) -> None:
    repo = DurableSnapshotRepository(tmp_path)
    snap_file = tmp_path / f"{mission_id}.snapshot.json"

    # Corrupt JSON syntax
    snap_file.write_text("{corrupted json data...", encoding="utf-8")
    with pytest.raises(SnapshotCorruptionError):
        repo.load_snapshot(mission_id)

    # Empty 0-byte file
    snap_file.write_text("", encoding="utf-8")
    with pytest.raises(SnapshotCorruptionError, match="empty"):
        repo.load_snapshot(mission_id)

    # Missing file
    non_existent_id = MissionId.generate()
    with pytest.raises(SnapshotNotFoundError):
        repo.load_snapshot(non_existent_id)


def test_planner_model_proposals_rejected_fail_closed(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    planner_input = PlannerInput(
        intent="Do something",
        mission_id=mission_id,
    )

    repo = DurableSnapshotRepository(Path("dummy_dir"))
    with pytest.raises(PlannerSnapshotAuthorityError):
        repo.save_snapshot(planner_input)  # type: ignore[arg-type]


def test_snapshot_ledger_consistency_verification(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    ledger_path = tmp_path / "mission.ledger"
    ledger = DurableFileLedger(ledger_path)

    # Snapshot referencing mission not in ledger -> conflict error
    snap_repo = DurableSnapshotRepository(tmp_path / "snapshots", ledger=ledger)
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
    )

    with pytest.raises(SnapshotLedgerConflictError, match="does not exist in ledger"):
        snap_repo.save_snapshot(snapshot)

    # Now append mission and action to ledger
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.DRAFT,
            created_at=contract.created_at,
            updated_at=contract.created_at,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=contract.created_at,
        )
    )

    # Save should now succeed
    snap_repo.save_snapshot(snapshot)
    loaded = snap_repo.load_snapshot(mission_id)
    assert loaded.mission_id == mission_id


def test_missing_required_fields_fails_closed_integrity(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    snap = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
    )
    data = snap.to_dict()
    # Remove a required field
    del data["desired_state"]
    with pytest.raises(
        SnapshotIntegrityError, match="Missing required snapshot field: 'desired_state'"
    ):
        MissionSnapshot.from_dict(data)


def test_rich_snapshot_round_trip_with_approvals_and_attempts(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    repo = DurableSnapshotRepository(tmp_path)
    now = datetime(2026, 10, 3, 6, 30, 0, tzinfo=UTC)

    # Create pending approval
    from stilldone.action_policy import validate_action_contract
    from stilldone.pending_approval import create_pending_approval

    validated_act = validate_action_contract(sample_action)
    pending_appr = create_pending_approval(validated_act, requested_at=now)

    # Create consumed approval
    consumed_appr = ApprovalConsumptionRecord(
        approval_id=ApprovalId.generate(),
        mission_id=mission_id,
        action_id=sample_action.action_id,
        binding_hash=BindingHash(
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        status=ApprovalUsageStatus.CONSUMED,
        consumed_at=now,
        attempt_number=1,
        reason="Human approved via UI",
    )

    # Create execution attempt
    attempt = ExecutionAttempt(
        action_id=sample_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )

    # Provider result
    provider_result = ProviderExecutionResult(
        action_type=ActionType.CALENDAR_UPDATE,
        success=True,
        status_name="UPDATED",
        writes_performed=1,
        captured_at=now,
        details={"summary": "Leave for school"},
    )

    # Step execution record
    step_rec = StepExecutionRecord(
        action_id=sample_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=attempt,
        provider_result=provider_result,
    )

    evidence_id = EvidenceId("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

    snap = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.VERIFYING,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        step_records={sample_action.action_id: step_rec},
        pending_approvals=[pending_appr],
        consumed_approvals=[consumed_appr],
        execution_attempts=[attempt],
        evidence_ids=[evidence_id],
        created_at=now,
    )

    repo.save_snapshot(snap)
    reloaded = repo.load_snapshot(mission_id)

    assert reloaded.mission_id == mission_id
    assert len(reloaded.pending_approvals) == 1
    assert reloaded.pending_approvals[0].pending_approval_id == pending_appr.pending_approval_id
    assert len(reloaded.consumed_approvals) == 1
    assert reloaded.consumed_approvals[0].approval_id == consumed_appr.approval_id
    assert len(reloaded.execution_attempts) == 1
    assert reloaded.execution_attempts[0].attempt_id == attempt.attempt_id
    step_record = reloaded.step_records[sample_action.action_id]
    assert step_record.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
    assert step_record.provider_result is not None
    assert step_record.provider_result.writes_performed == 1
    assert reloaded.evidence_ids == (evidence_id,)


def test_ready_snapshot_missing_step_records_rejected(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Cannot fabricate a READY snapshot without step execution records."""
    with pytest.raises(SnapshotIntegrityError, match="missing step records"):
        create_mission_snapshot(
            mission_id=mission_id,
            state=MissionState.READY,
            contract=contract,
            desired_state=[sample_predicate],
            actions=[sample_action],
            step_records=None,
        )


def test_ready_snapshot_not_run_step_status_rejected(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Cannot mark a snapshot READY if step status is NOT_RUN."""
    step_rec = StepExecutionRecord(
        action_id=sample_action.action_id,
        status=ActionExecutionStatus.NOT_RUN,
    )
    with pytest.raises(SnapshotIntegrityError, match="non-succeeded status"):
        create_mission_snapshot(
            mission_id=mission_id,
            state=MissionState.READY,
            contract=contract,
            desired_state=[sample_predicate],
            actions=[sample_action],
            step_records={sample_action.action_id: step_rec},
            evidence_ids=[EvidenceId("e" * 64)],
        )


def test_ready_snapshot_zero_evidence_rejected(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Cannot mark a snapshot READY with actions but zero evidence IDs."""
    now = datetime(2026, 10, 3, 6, 30, 0, tzinfo=UTC)
    attempt = ExecutionAttempt(
        action_id=sample_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr = ProviderExecutionResult(
        action_type=ActionType.CALENDAR_UPDATE,
        success=True,
        status_name="UPDATED",
        writes_performed=1,
        captured_at=now,
    )
    step_rec = StepExecutionRecord(
        action_id=sample_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=attempt,
        provider_result=pr,
    )
    with pytest.raises(SnapshotIntegrityError, match="zero evidence IDs"):
        create_mission_snapshot(
            mission_id=mission_id,
            state=MissionState.READY,
            contract=contract,
            desired_state=[sample_predicate],
            actions=[sample_action],
            step_records={sample_action.action_id: step_rec},
            evidence_ids=(),
        )


def test_forged_ready_over_persisted_draft_rejected(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """DurableSnapshotRepository rejects saving a READY snapshot when ledger records DRAFT."""
    ledger_path = tmp_path / "mission.ledger"
    ledger = DurableFileLedger(ledger_path)
    snap_repo = DurableSnapshotRepository(tmp_path / "snapshots", ledger=ledger)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.DRAFT,
            created_at=contract.created_at,
            updated_at=contract.created_at,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=contract.created_at,
        )
    )

    now = datetime(2026, 10, 3, 6, 30, 0, tzinfo=UTC)
    attempt = ExecutionAttempt(
        action_id=sample_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    pr = ProviderExecutionResult(
        action_type=ActionType.CALENDAR_UPDATE,
        success=True,
        status_name="UPDATED",
        writes_performed=1,
        captured_at=now,
    )
    step_rec = StepExecutionRecord(
        action_id=sample_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=attempt,
        provider_result=pr,
    )
    from stilldone.approval_consumption import ApprovalConsumptionRecord, ApprovalUsageStatus
    from stilldone.domain.authority import ApprovalId, BindingHash

    consumed_appr = ApprovalConsumptionRecord(
        approval_id=ApprovalId.generate(),
        mission_id=mission_id,
        action_id=sample_action.action_id,
        binding_hash=BindingHash("0" * 64),
        status=ApprovalUsageStatus.CONSUMED,
        consumed_at=now,
        attempt_number=1,
        reason="Human approved",
    )

    forged_ready_snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        step_records={sample_action.action_id: step_rec},
        consumed_approvals=[consumed_appr],
        execution_attempts=[attempt],
        evidence_ids=[EvidenceId("e" * 64)],
    )

    with pytest.raises(SnapshotLedgerConflictError, match="contradicts ledger state"):
        snap_repo.save_snapshot(forged_ready_snapshot)


def test_snapshot_ledger_foreign_evidence_rejected(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Snapshot with evidence not belonging to mission/action is rejected by ledger check."""
    from stilldone.domain.provenance import EvidenceOrigin
    from stilldone.ledger import EvidenceRecord

    ledger_path = tmp_path / "mission.ledger"
    ledger = DurableFileLedger(ledger_path)
    snap_repo = DurableSnapshotRepository(tmp_path / "snapshots", ledger=ledger)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=contract.created_at,
            updated_at=contract.created_at,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=contract.created_at,
        )
    )

    # Append foreign mission and action to ledger first
    foreign_mission_id = MissionId.generate()
    ledger.append_mission(
        MissionRecord(
            mission_id=foreign_mission_id,
            contract=MissionContract.create(text="Foreign mission", mission_id=foreign_mission_id),
            state=MissionState.DRAFT,
            created_at=contract.created_at,
            updated_at=contract.created_at,
        )
    )
    foreign_action = ActionContract(
        action_id=ActionId.generate(),
        mission_id=foreign_mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=sample_action.target,
        parameters=NormalizedParameters.from_dict({}),
    )
    ledger.append_action(
        ActionRecord(
            action_id=foreign_action.action_id,
            mission_id=foreign_mission_id,
            action=foreign_action,
            approval_id=None,
            created_at=contract.created_at,
        )
    )

    foreign_ev_record = EvidenceRecord.create(
        action_id=foreign_action.action_id,
        mission_id=foreign_mission_id,
        origin=EvidenceOrigin.fixture(),
        payload={"summary": "Foreign event"},
    )
    ledger.append_evidence(foreign_ev_record)

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.VERIFYING,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        evidence_ids=[foreign_ev_record.evidence_id],
    )

    with pytest.raises(SnapshotLedgerConflictError, match="expected snapshot mission"):
        snap_repo.save_snapshot(snapshot)


def test_snapshot_corrupted_boolean_string_rejected(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """String 'false' must raise SnapshotCorruptionError instead of bool() coercion."""
    snap = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
    )
    data = snap.to_dict()
    # Corrupt required boolean with string "false"
    data["desired_state"][0]["required"] = "false"
    with pytest.raises(SnapshotCorruptionError, match="must be a boolean"):
        MissionSnapshot.from_dict(data)


def test_snapshot_tampered_pending_approval_rejected(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Tampering with serialized pending approval fields raises SnapshotIntegrityError."""
    from stilldone.action_policy import validate_action_contract
    from stilldone.pending_approval import create_pending_approval

    now = datetime(2026, 10, 3, 6, 30, 0, tzinfo=UTC)
    pa = create_pending_approval(validate_action_contract(sample_action), requested_at=now)

    snap = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        pending_approvals=[pa],
    )
    data = snap.to_dict()
    # Tamper with authority class
    data["pending_approvals"][0]["authority_class"] = "READ_ONLY"
    with pytest.raises(SnapshotIntegrityError, match="does not match"):
        MissionSnapshot.from_dict(data)


def test_forged_ready_with_unrelated_evidence_rejected_by_consistency_check(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """A READY mission in ledger with only generic/unrelated evidence fails closed."""
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import (
        ActionRecord,
        DurableFileLedger,
        EvidenceRecord,
        MissionRecord,
    )

    ledger_path = tmp_path / "forged.ledger"
    ledger = DurableFileLedger(ledger_path)
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    # Append mission in VERIFYING state first
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )
    # Generic, unrelated evidence (lacks verification proof)
    unrelated_evidence = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={"metrics": {"cpu": 95}, "note": "unrelated generic payload"},
        created_at=now,
    )
    ledger.append_evidence(unrelated_evidence)

    # Transitioning to READY in ledger should fail because evidence is NOT verification evidence
    from stilldone.transitions import IllegalStatePromotionError

    with pytest.raises(IllegalStatePromotionError, match="lacks verification"):
        ledger.update_mission_state(
            mission_id=mission_id,
            new_state=MissionState.READY,
            updated_at=now,
        )


def test_ledger_update_mission_state_rejects_illegal_promotion(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
) -> None:
    """Updating state directly from DRAFT to READY raises IllegalStatePromotionError."""
    from stilldone.ledger import DurableFileLedger, MissionRecord
    from stilldone.transitions import IllegalStatePromotionError

    ledger_path = tmp_path / "lifecycle.ledger"
    ledger = DurableFileLedger(ledger_path)
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.DRAFT,
            created_at=now,
            updated_at=now,
        )
    )

    with pytest.raises(IllegalStatePromotionError, match="Illegal promotion to READY"):
        ledger.update_mission_state(
            mission_id=mission_id,
            new_state=MissionState.READY,
            updated_at=now,
        )


def test_legitimate_verifying_to_ready_transition_with_verification_evidence(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Legitimate VERIFYING -> READY transition with genuine verification evidence
    passes consistency check.
    """
    from stilldone.domain.execution import IdempotencyKey
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
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

    ledger_path = tmp_path / "legit.ledger"
    ledger = DurableFileLedger(ledger_path)
    repo = DurableSnapshotRepository(tmp_path / "snaps", ledger=ledger)
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )

    # Genuine verification evidence matching canonical contract
    verif_evidence = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )
    ledger.append_evidence(verif_evidence)

    # Legal transition VERIFYING -> READY
    ledger.update_mission_state(
        mission_id=mission_id,
        new_state=MissionState.READY,
        updated_at=now,
    )

    from stilldone.approval_consumption import ApprovalConsumptionRecord, ApprovalUsageStatus
    from stilldone.domain.authority import ApprovalId, BindingHash

    consumed_appr = ApprovalConsumptionRecord(
        approval_id=ApprovalId.generate(),
        mission_id=mission_id,
        action_id=sample_action.action_id,
        binding_hash=BindingHash("0" * 64),
        status=ApprovalUsageStatus.CONSUMED,
        consumed_at=now,
        attempt_number=1,
        reason="Human approved",
    )

    attempt = ExecutionAttempt(
        action_id=sample_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    step_rec = StepExecutionRecord(
        action_id=sample_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=attempt,
        provider_result=ProviderExecutionResult(
            action_type=sample_action.action_type,
            success=True,
            status_name="READ_OK",
            writes_performed=0,
            captured_at=now,
        ),
    )

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        step_records={sample_action.action_id: step_rec},
        consumed_approvals=[consumed_appr],
        execution_attempts=[attempt],
        evidence_ids=[verif_evidence.evidence_id],
        created_at=now,
    )

    # Verification consistency succeeds
    repo.verify_consistency_with_ledger(snapshot)
    repo.save_snapshot(snapshot)
    loaded = repo.load_snapshot(mission_id)
    assert loaded.state == MissionState.READY


def test_snapshot_predicate_target_binding_round_trip(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Explicit PredicateTargetBinding survives durable snapshot round-trip."""
    from stilldone.domain.desired_state import PredicateTargetBinding

    repo = DurableSnapshotRepository(tmp_path / "snaps")
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    binding = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        predicate_bindings=[binding],
        created_at=now,
    )

    repo.save_snapshot(snapshot)
    loaded = repo.load_snapshot(mission_id)

    assert len(loaded.predicate_bindings) == 1
    loaded_b = loaded.predicate_bindings[0]
    assert loaded_b.predicate_id == sample_predicate.predicate_id
    assert loaded_b.mission_id == mission_id
    assert loaded_b.target == sample_action.target
    assert loaded.get_target_for_predicate(sample_predicate.predicate_id) == sample_action.target


def test_snapshot_predicate_target_binding_rejected_when_target_foreign(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """PredicateTargetBinding target not present in any action is rejected fail-closed."""
    from stilldone.domain.desired_state import PredicateTargetBinding

    foreign_target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="foreign_event_999",
        parent_id="c_other@group.calendar.google.com",
    )
    binding = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=foreign_target,
    )

    with pytest.raises(SnapshotLineageError, match="does not match any action target"):
        create_mission_snapshot(
            mission_id=mission_id,
            state=MissionState.DRAFT,
            contract=contract,
            desired_state=[sample_predicate],
            actions=[sample_action],
            predicate_bindings=[binding],
        )


def test_snapshot_predicate_target_binding_rejected_when_duplicate_predicate_id(
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Duplicate predicate ID in predicate_bindings is rejected fail-closed."""
    from stilldone.domain.desired_state import PredicateTargetBinding

    b1 = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )
    b2 = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )

    with pytest.raises(SnapshotIntegrityError, match="Duplicate predicate target binding"):
        create_mission_snapshot(
            mission_id=mission_id,
            state=MissionState.DRAFT,
            contract=contract,
            desired_state=[sample_predicate],
            actions=[sample_action],
            predicate_bindings=[b1, b2],
        )


def test_ledger_rejects_loose_flags_for_ready_promotion(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
) -> None:
    """Loose flags, superficial status, fixture provenance, and empty predicate evaluations
    fail closed with IllegalStatePromotionError when attempting promotion to READY in ledger.
    """
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import (
        ActionRecord,
        DurableFileLedger,
        EvidenceRecord,
        MissionRecord,
    )
    from stilldone.transitions import IllegalStatePromotionError

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)

    loose_payloads: list[dict[str, Any]] = [
        {"verification": True},
        {"is_verified": True},
        {"initial_verification": True},
        {"is_ready": True},
        {"status": "VERIFIED"},
        {"status": "READ_OK"},
        {"evidence_type": "PREDICATE_EVALUATION", "predicate_id": "", "truth": "TRUE"},
        {"evidence_type": "PREDICATE_EVALUATION", "predicate_id": "p1", "truth": "FALSE"},
        {"evidence_type": "MISSION_READINESS", "is_ready": True, "failed_predicate_ids": ["p1"]},
    ]

    for i, payload in enumerate(loose_payloads):
        ledger = DurableFileLedger(tmp_path / f"loose_{i}.ledger")
        ledger.append_mission(
            MissionRecord(
                mission_id=mission_id,
                contract=contract,
                state=MissionState.VERIFYING,
                created_at=now,
                updated_at=now,
            )
        )
        ledger.append_action(
            ActionRecord(
                action_id=sample_action.action_id,
                mission_id=mission_id,
                action=sample_action,
                approval_id=None,
                created_at=now,
            )
        )
        ev = EvidenceRecord.create(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
                observed_at=now,
            ),
            payload=payload,
            created_at=now,
        )
        ledger.append_evidence(ev)

        with pytest.raises(IllegalStatePromotionError, match="lacks verification"):
            ledger.update_mission_state(
                mission_id=mission_id,
                new_state=MissionState.READY,
                updated_at=now,
            )

    # Fixture provenance must also be rejected even with valid-looking payload
    ledger_fix = DurableFileLedger(tmp_path / "fixture.ledger")
    ledger_fix.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger_fix.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )
    ev_fix = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.FIXTURE,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": "p1",
            "truth": "TRUE",
        },
        created_at=now,
    )
    ledger_fix.append_evidence(ev_fix)
    with pytest.raises(IllegalStatePromotionError, match="lacks verification"):
        ledger_fix.update_mission_state(
            mission_id=mission_id,
            new_state=MissionState.READY,
            updated_at=now,
        )


def test_snapshot_crash_recovery_from_ledger_durable_transition(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """When a process crashes after ledger durable transition commit but before snapshot
    storage write completes, DurableSnapshotRepository.load_snapshot() deterministically
    recovers the projection from the ledger journal and heals the snapshot storage.
    """
    from stilldone.approval_consumption import ApprovalConsumptionRecord, ApprovalUsageStatus
    from stilldone.domain.authority import ApprovalId, BindingHash
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import (
        ActionRecord,
        DurableFileLedger,
        EvidenceRecord,
        MissionRecord,
    )

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger_file = tmp_path / "recovery.ledger"
    ledger = DurableFileLedger(ledger_file)
    snap_dir = tmp_path / "snaps"
    repo = DurableSnapshotRepository(snap_dir, ledger=ledger)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )
    ev = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )

    consumed_appr = ApprovalConsumptionRecord(
        approval_id=ApprovalId.generate(),
        mission_id=mission_id,
        action_id=sample_action.action_id,
        binding_hash=BindingHash("0" * 64),
        status=ApprovalUsageStatus.CONSUMED,
        consumed_at=now,
        attempt_number=1,
        reason="Human approved",
    )
    attempt = ExecutionAttempt(
        action_id=sample_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    step_rec = StepExecutionRecord(
        action_id=sample_action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=attempt,
        provider_result=ProviderExecutionResult(
            action_type=sample_action.action_type,
            success=True,
            status_name="READ_OK",
            writes_performed=0,
            captured_at=now,
        ),
    )
    binding = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )

    # Initial snapshot saved in VERIFYING state
    initial_snap = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.VERIFYING,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        predicate_bindings=[binding],
        created_at=now,
    )
    repo.save_snapshot(initial_snap)

    # Create target READY snapshot projection
    ready_snap = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        predicate_bindings=[binding],
        step_records={sample_action.action_id: step_rec},
        consumed_approvals=[consumed_appr],
        execution_attempts=[attempt],
        evidence_ids=[ev.evidence_id],
        created_at=now,
    )

    # Commit durable state transition in ledger journal
    ledger.record_state_transition(
        mission_id=mission_id,
        expected_prior_state=MissionState.VERIFYING,
        new_state=MissionState.READY,
        evidence=ev,
        snapshot_projection=ready_snap.to_dict(),
        updated_at=now,
    )

    # Simulate CRASH: snapshot file on disk was NOT updated (remains VERIFYING)
    fresh_ledger = DurableFileLedger(ledger_file)
    fresh_repo = DurableSnapshotRepository(snap_dir, ledger=fresh_ledger)

    # load_snapshot() detects that disk snapshot lags behind committed durable transition,
    # recovers projection deterministically, and heals disk snapshot
    recovered = fresh_repo.load_snapshot(mission_id)
    assert recovered.state == MissionState.READY
    assert recovered.snapshot_id == ready_snap.snapshot_id

    # Verify that disk storage was healed
    unconnected_repo = DurableSnapshotRepository(snap_dir, ledger=None)
    disk_loaded = unconnected_repo.load_snapshot(mission_id)
    assert disk_loaded.state == MissionState.READY
    assert disk_loaded.snapshot_id == ready_snap.snapshot_id


def _make_test_ready_snapshot(
    mission_id: MissionId,
    contract: MissionContract,
    predicate: DesiredStatePredicate,
    action: ActionContract,
    binding: Any,
    evidence_ids: Any,
    now: datetime,
) -> MissionSnapshot:
    from stilldone.approval_consumption import ApprovalConsumptionRecord, ApprovalUsageStatus
    from stilldone.domain.authority import ApprovalId, BindingHash

    consumed_appr = ApprovalConsumptionRecord(
        approval_id=ApprovalId.generate(),
        mission_id=mission_id,
        action_id=action.action_id,
        binding_hash=BindingHash("0" * 64),
        status=ApprovalUsageStatus.CONSUMED,
        consumed_at=now,
        attempt_number=1,
        reason="Human approved",
    )
    attempt = ExecutionAttempt(
        action_id=action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )
    step_rec = StepExecutionRecord(
        action_id=action.action_id,
        status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
        attempt=attempt,
        provider_result=ProviderExecutionResult(
            action_type=action.action_type,
            success=True,
            status_name="READ_OK",
            writes_performed=0,
            captured_at=now,
        ),
    )
    return create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=[predicate],
        actions=[action],
        predicate_bindings=[binding],
        consumed_approvals=[consumed_appr],
        step_records={action.action_id: step_rec},
        execution_attempts=[attempt],
        evidence_ids=evidence_ids,
        created_at=now,
    )


def test_verify_consistency_rejects_unrelated_predicate_evidence(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """verify_consistency_with_ledger() rejects verification evidence whose predicate_id
    does not match the bound predicate ID.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord
    from stilldone.snapshot import SnapshotLedgerConflictError

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger = DurableFileLedger(tmp_path / "unrelated.ledger")
    repo = DurableSnapshotRepository(tmp_path / "snaps", ledger=ledger)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )
    # Evidence has predicate_id="different_pid_123"
    ev = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": "different_pid_123",
            "truth": "TRUE",
            "is_true": True,
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )
    ledger.append_evidence(ev)
    ledger.update_mission_state(
        mission_id=mission_id,
        new_state=MissionState.READY,
        updated_at=now,
    )

    binding = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )
    snapshot = _make_test_ready_snapshot(
        mission_id=mission_id,
        contract=contract,
        predicate=sample_predicate,
        action=sample_action,
        binding=binding,
        evidence_ids=[ev.evidence_id],
        now=now,
    )

    with pytest.raises(
        SnapshotLedgerConflictError,
        match="bound target lacks verification evidence",
    ):
        repo.verify_consistency_with_ledger(snapshot)


def test_ledger_replay_rejects_tampered_evidence_id_in_durable_transition(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """DurableFileLedger replay rejects a durable_transition journal entry if its
    embedded evidence ID was tampered with.
    """
    import json

    from stilldone.application.ports.ledger_port import RecordConflictError
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger_path = tmp_path / "tampered.ledger"
    ledger = DurableFileLedger(ledger_path)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )
    ev = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )
    binding = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )
    ready_snap = _make_test_ready_snapshot(
        mission_id=mission_id,
        contract=contract,
        predicate=sample_predicate,
        action=sample_action,
        binding=binding,
        evidence_ids=[ev.evidence_id],
        now=now,
    )
    ledger.record_state_transition(
        mission_id=mission_id,
        expected_prior_state=MissionState.VERIFYING,
        new_state=MissionState.READY,
        evidence=ev,
        snapshot_projection=ready_snap.to_dict(),
        updated_at=now,
    )

    # Read journal lines and tamper with the evidence_id in the durable_transition entry
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    tampered_lines = []
    for line in lines:
        entry = json.loads(line)
        if entry.get("record_type") == "durable_transition":
            entry["evidence"]["evidence_id"] = "bad" * 21 + "a"
        tampered_lines.append(json.dumps(entry))
    ledger_path.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    with pytest.raises(RecordConflictError, match="failed content-address validation"):
        DurableFileLedger(ledger_path)


def test_ledger_replay_rejects_mismatched_projection_mission_id(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """DurableFileLedger replay rejects durable_transition entry if snapshot_projection
    mission_id differs from transition mission_id.
    """
    import json

    from stilldone.application.ports.ledger_port import RecordConflictError
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger_path = tmp_path / "mismatch_proj.ledger"
    ledger = DurableFileLedger(ledger_path)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )
    ev = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )
    binding = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )
    ready_snap = _make_test_ready_snapshot(
        mission_id=mission_id,
        contract=contract,
        predicate=sample_predicate,
        action=sample_action,
        binding=binding,
        evidence_ids=[ev.evidence_id],
        now=now,
    )
    ledger.record_state_transition(
        mission_id=mission_id,
        expected_prior_state=MissionState.VERIFYING,
        new_state=MissionState.READY,
        evidence=ev,
        snapshot_projection=ready_snap.to_dict(),
        updated_at=now,
    )

    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    tampered_lines = []
    for line in lines:
        entry = json.loads(line)
        if entry.get("record_type") == "durable_transition":
            entry["snapshot_projection"]["mission_id"] = "foreign_mission_999"
        tampered_lines.append(json.dumps(entry))
    ledger_path.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    with pytest.raises(RecordConflictError, match="does not match transition mission"):
        DurableFileLedger(ledger_path)


def test_load_snapshot_raises_on_healing_write_failure(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_snapshot() raises SnapshotIntegrityError when disk snapshot healing
    write fails fail-closed.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord
    from stilldone.snapshot import SnapshotIntegrityError

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger_file = tmp_path / "healing_fail.ledger"
    ledger = DurableFileLedger(ledger_file)
    snap_dir = tmp_path / "snaps"
    repo = DurableSnapshotRepository(snap_dir, ledger=ledger)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )
    ev = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )
    binding = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )
    ready_snap = _make_test_ready_snapshot(
        mission_id=mission_id,
        contract=contract,
        predicate=sample_predicate,
        action=sample_action,
        binding=binding,
        evidence_ids=[ev.evidence_id],
        now=now,
    )
    ledger.record_state_transition(
        mission_id=mission_id,
        expected_prior_state=MissionState.VERIFYING,
        new_state=MissionState.READY,
        evidence=ev,
        snapshot_projection=ready_snap.to_dict(),
        updated_at=now,
    )

    # Mock save_snapshot to simulate disk I/O write failure
    def mock_save_fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("Disk full simulation")

    monkeypatch.setattr(repo, "save_snapshot", mock_save_fail)

    with pytest.raises(SnapshotIntegrityError, match="Failed to heal snapshot projection"):
        repo.load_snapshot(mission_id)


def _make_full_ready_snapshot(
    mission_id: MissionId,
    contract: MissionContract,
    desired_state: list[DesiredStatePredicate],
    actions: list[ActionContract],
    predicate_bindings: list[Any],
    evidence_ids: list[Any],
    now: datetime,
) -> MissionSnapshot:
    from stilldone.approval_consumption import ApprovalConsumptionRecord, ApprovalUsageStatus
    from stilldone.domain.authority import ApprovalId, BindingHash
    from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
    from stilldone.execution.state import (
        ActionExecutionStatus,
        ProviderExecutionResult,
        StepExecutionRecord,
    )

    consumed_list = []
    attempt_list = []
    step_records = {}
    for act in actions:
        appr = ApprovalConsumptionRecord(
            approval_id=ApprovalId.generate(),
            mission_id=mission_id,
            action_id=act.action_id,
            binding_hash=BindingHash("0" * 64),
            status=ApprovalUsageStatus.CONSUMED,
            consumed_at=now,
            attempt_number=1,
            reason="Human approved",
        )
        consumed_list.append(appr)
        att = ExecutionAttempt(
            action_id=act.action_id,
            idempotency_key=IdempotencyKey.generate(),
            attempt_number=1,
            started_at=now,
        )
        attempt_list.append(att)
        step_records[act.action_id] = StepExecutionRecord(
            action_id=act.action_id,
            status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
            attempt=att,
            provider_result=ProviderExecutionResult(
                action_type=act.action_type,
                success=True,
                status_name="READ_OK",
                writes_performed=0,
                captured_at=now,
            ),
        )
    return create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=desired_state,
        actions=actions,
        predicate_bindings=predicate_bindings,
        consumed_approvals=consumed_list,
        step_records=step_records,
        execution_attempts=attempt_list,
        evidence_ids=evidence_ids,
        created_at=now,
    )


def test_ready_rejected_with_correctly_shaped_but_false_observation(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Evidence with well-formed PREDICATE_EVALUATION shape but false/contradicting
    observation value fails closed with IllegalStatePromotionError when promoting to READY.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord
    from stilldone.transitions import IllegalStatePromotionError

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger = DurableFileLedger(tmp_path / "false_obs.ledger")
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )
    # Correctly shaped PREDICATE_EVALUATION, but observation start_time contradicts expected 07:30
    ev = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "expected_value": "2026-10-03T07:30:00+03:00",
            "observations": {"start_time": "2026-10-03T09:00:00+03:00"},
        },
        created_at=now,
    )

    binding = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )
    ready_snap = _make_full_ready_snapshot(
        mission_id=mission_id,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        predicate_bindings=[binding],
        evidence_ids=[ev.evidence_id],
        now=now,
    )

    with pytest.raises(IllegalStatePromotionError, match="contradicts expected value"):
        ledger.record_state_transition(
            mission_id=mission_id,
            expected_prior_state=MissionState.VERIFYING,
            new_state=MissionState.READY,
            evidence=ev,
            snapshot_projection=ready_snap.to_dict(),
            updated_at=now,
        )


def test_ready_rejected_with_missing_required_predicate(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """When a mission requires two predicates and only one has verification evidence,
    READY promotion fails closed with IllegalStatePromotionError.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord
    from stilldone.transitions import IllegalStatePromotionError

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger = DurableFileLedger(tmp_path / "missing_pred.ledger")
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
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

    # Only provide evidence for sample_predicate, not pred2
    ev = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )

    b1 = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )
    b2 = PredicateTargetBinding.create(
        predicate_id=pred2.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )

    ready_snap = _make_full_ready_snapshot(
        mission_id=mission_id,
        contract=contract,
        desired_state=[sample_predicate, pred2],
        actions=[sample_action],
        predicate_bindings=[b1, b2],
        evidence_ids=[ev.evidence_id],
        now=now,
    )

    with pytest.raises(IllegalStatePromotionError, match="lacks verified evidence"):
        ledger.record_state_transition(
            mission_id=mission_id,
            expected_prior_state=MissionState.VERIFYING,
            new_state=MissionState.READY,
            evidence=ev,
            snapshot_projection=ready_snap.to_dict(),
            updated_at=now,
        )


def test_ready_rejected_with_wrong_bound_resource(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """When a predicate is bound to a foreign target not matching the verified action target,
    READY promotion fails closed with IllegalStatePromotionError.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord
    from stilldone.transitions import IllegalStatePromotionError

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger = DurableFileLedger(tmp_path / "wrong_target.ledger")
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )

    other_target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="different_event_888",
        parent_id=sample_action.target.parent_id,
    )
    action2 = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=other_target,
        parameters={},
    )
    ledger.append_action(
        ActionRecord(
            action_id=action2.action_id,
            mission_id=mission_id,
            action=action2,
            approval_id=None,
            created_at=now,
        )
    )

    ev = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )

    b_wrong = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=other_target,
    )

    ready_snap = _make_full_ready_snapshot(
        mission_id=mission_id,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action, action2],
        predicate_bindings=[b_wrong],
        evidence_ids=[ev.evidence_id],
        now=now,
    )

    with pytest.raises(IllegalStatePromotionError):
        ledger.record_state_transition(
            mission_id=mission_id,
            expected_prior_state=MissionState.VERIFYING,
            new_state=MissionState.READY,
            evidence=ev,
            snapshot_projection=ready_snap.to_dict(),
            updated_at=now,
        )


def test_ready_rejected_with_stale_verification(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """Stale verification evidence (freshness_status='STALE' or is_stale=True)
    is rejected fail closed with IllegalStatePromotionError.
    """
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord
    from stilldone.transitions import IllegalStatePromotionError

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger = DurableFileLedger(tmp_path / "stale_verif.ledger")
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )

    ev_stale = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "freshness_status": "STALE",
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )
    ledger.append_evidence(ev_stale)

    with pytest.raises(IllegalStatePromotionError, match="lacks verification"):
        ledger.update_mission_state(
            mission_id=mission_id,
            new_state=MissionState.READY,
            updated_at=now,
        )


def test_ready_rejected_with_forged_readiness_summary(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
) -> None:
    """MISSION_READINESS evidence payload with failed_predicate_ids or unverified_action_ids
    fails closed with IllegalStatePromotionError when attempting promotion to READY.
    """
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord
    from stilldone.transitions import IllegalStatePromotionError

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger = DurableFileLedger(tmp_path / "forged_ready.ledger")
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )

    ev_forged = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "MISSION_READINESS",
            "is_ready": True,
            "satisfied_predicate_ids": ["p1"],
            "failed_predicate_ids": ["p2"],
        },
        created_at=now,
    )
    ledger.append_evidence(ev_forged)

    with pytest.raises(IllegalStatePromotionError, match="lacks verification"):
        ledger.update_mission_state(
            mission_id=mission_id,
            new_state=MissionState.READY,
            updated_at=now,
        )


def test_ready_accepted_with_legitimate_fully_verified_positive_path(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    sample_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """A legitimate, fully-verified mission with matching observation, canonical binding,
    and valid projection is promoted to READY successfully.
    """
    from stilldone.domain.desired_state import PredicateTargetBinding
    from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
    from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord, MissionRecord

    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=UTC)
    ledger = DurableFileLedger(tmp_path / "legit_ready.ledger")
    repo = DurableSnapshotRepository(tmp_path / "snaps", ledger=ledger)

    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=sample_action.action_id,
            mission_id=mission_id,
            action=sample_action,
            approval_id=None,
            created_at=now,
        )
    )

    ev = EvidenceRecord.create(
        action_id=sample_action.action_id,
        mission_id=mission_id,
        origin=EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            observed_at=now,
        ),
        payload={
            "evidence_type": "PREDICATE_EVALUATION",
            "predicate_id": str(sample_predicate.predicate_id),
            "truth": "TRUE",
            "is_true": True,
            "observations": {"start_time": "2026-10-03T07:30:00+03:00"},
        },
        created_at=now,
    )
    binding = PredicateTargetBinding.create(
        predicate_id=sample_predicate.predicate_id,
        mission_id=mission_id,
        target=sample_action.target,
    )
    ready_snap = _make_test_ready_snapshot(
        mission_id=mission_id,
        contract=contract,
        predicate=sample_predicate,
        action=sample_action,
        binding=binding,
        evidence_ids=[ev.evidence_id],
        now=now,
    )

    ledger.record_state_transition(
        mission_id=mission_id,
        expected_prior_state=MissionState.VERIFYING,
        new_state=MissionState.READY,
        evidence=ev,
        snapshot_projection=ready_snap.to_dict(),
        updated_at=now,
    )

    # Mission state in ledger is now READY
    m_rec = ledger.get_mission(mission_id)
    assert m_rec is not None
    assert m_rec.state == MissionState.READY

    # Snapshot loaded from repo is recovered/healed to READY
    loaded_snap = repo.load_snapshot(mission_id)
    assert loaded_snap.state == MissionState.READY
    assert loaded_snap.snapshot_id == ready_snap.snapshot_id
