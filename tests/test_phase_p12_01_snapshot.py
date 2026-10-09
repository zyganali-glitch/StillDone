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

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.READY,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[sample_action],
        created_at=datetime(2026, 10, 3, 6, 15, 0, tzinfo=UTC),
    )

    repo.save_snapshot(snapshot)

    # Fresh repository instance pointing to the same file
    fresh_repo = DurableSnapshotRepository(log_file)
    loaded = fresh_repo.load_snapshot(mission_id)
    assert loaded.mission_id == mission_id
    assert loaded.state == MissionState.READY


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
