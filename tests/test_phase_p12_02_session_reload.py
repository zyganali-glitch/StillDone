"""Tests for Mission Session Reload & Resume Across Fresh Processes (Phase P-12.02).

Validates:
- Full canonical state rehydration across fresh runtime instances and re-opened durable storage.
- Preserves NOT_RUN, BLOCKED, and ambiguous outcomes without silently altering them.
- An interrupted / uncertain mutation strictly requires read-before-retry.
- A consumed approval cannot authorize a second provider mutation.
- Zero external writes / mutations are replayed during reload.
- Process-local versus distributed guarantee distinction is preserved.
- Fresh objects and re-opened durable files are used (zero in-memory reference reuse).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stilldone.action_policy import validate_action_contract
from stilldone.approval_consumption import (
    ApprovalLedger,
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
    ApprovalGrant,
    AuthorityClass,
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
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.evidence import compute_evidence_id
from stilldone.execution.state import (
    ActionExecutionStatus,
    StepExecutionRecord,
)
from stilldone.ledger import (
    ActionRecord,
    DurableFileLedger,
    EvidenceRecord,
    MissionRecord,
)
from stilldone.pending_approval import (
    create_pending_approval,
)
from stilldone.session import (
    ReplayAttemptForbiddenError,
    UncertainMutationRequiresReadbackError,
    resume_mission_session,
)
from stilldone.snapshot import (
    DurableSnapshotRepository,
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
def cal_action(mission_id: MissionId) -> ActionContract:
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
def blocked_action(mission_id: MissionId) -> ActionContract:
    target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task_confirm_departure",
        parent_id="list_demo_tasks",
    )
    return ActionContract(
        action_id=ActionId.generate(),
        mission_id=mission_id,
        action_type=ActionType.TASK_CREATE,
        target=target,
        parameters=NormalizedParameters.from_dict(
            {
                "title": "Confirm departure at 7:30",
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


def test_resume_session_fresh_process_rehydration(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    cal_action: ActionContract,
    blocked_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    ledger_path = tmp_path / "mission.ledger"
    storage_path = tmp_path / "snapshots"
    now = datetime(2026, 10, 3, 6, 10, 0, tzinfo=UTC)

    # 1. Setup durable ledger in process 1
    ledger1 = DurableFileLedger(ledger_path)
    ledger1.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.EXECUTING,
            created_at=now,
            updated_at=now,
        )
    )
    ledger1.append_action(
        ActionRecord(
            action_id=cal_action.action_id,
            mission_id=mission_id,
            action=cal_action,
            approval_id=None,
            created_at=now,
        )
    )
    ledger1.append_action(
        ActionRecord(
            action_id=blocked_action.action_id,
            mission_id=mission_id,
            action=blocked_action,
            approval_id=None,
            created_at=now,
        )
    )

    # 2. Record consumed approval in ledger
    approval_ledger1 = ApprovalLedger(ledger=ledger1)
    validated_act = validate_action_contract(cal_action)
    pending_appr = create_pending_approval(validated_act, requested_at=now)

    grant = ApprovalGrant.create(
        action=cal_action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    approval_ledger1.consume(
        grant=grant,
        action=cal_action,
        attempt_number=1,
        at=now,
    )
    consumed_rec = approval_ledger1.get_consumed_records_for_action(cal_action.action_id)[0]

    # 3. Step records preserving NOT_RUN and BLOCKED
    step_records = {
        cal_action.action_id: StepExecutionRecord(
            action_id=cal_action.action_id,
            status=ActionExecutionStatus.NOT_RUN,
        ),
        blocked_action.action_id: StepExecutionRecord(
            action_id=blocked_action.action_id,
            status=ActionExecutionStatus.BLOCKED,
            blocked_by=cal_action.action_id,
        ),
    }

    # 4. Save durable snapshot
    snap_repo1 = DurableSnapshotRepository(storage_path, ledger=ledger1)
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.EXECUTING,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[cal_action, blocked_action],
        action_dependencies={
            cal_action.action_id: (),
            blocked_action.action_id: (cal_action.action_id,),
        },
        step_records=step_records,
        pending_approvals=[pending_appr],
        consumed_approvals=[consumed_rec],
        created_at=now,
    )
    snap_repo1.save_snapshot(snapshot)

    # Completely drop all in-memory references from process 1
    del ledger1, snap_repo1, approval_ledger1

    # 5. Restore in fresh runtime instance (Process 2)
    session = resume_mission_session(
        storage_path=storage_path,
        ledger_path=ledger_path,
        mission_id=mission_id,
    )

    # Invariants verification
    assert session.mission_id == mission_id
    assert session.state == MissionState.EXECUTING
    assert session.contract == contract
    assert len(session.actions) == 2
    assert session.reloaded_writes_performed == 0
    assert session.CONCURRENCY_GUARANTEE_SCOPE == "PROCESS_LOCAL"

    # Step statuses preserved
    assert session.get_step_status(cal_action.action_id) == ActionExecutionStatus.NOT_RUN
    assert session.get_step_status(blocked_action.action_id) == ActionExecutionStatus.BLOCKED

    # Consumed grant cannot authorize a second write
    assert session.is_consumed(cal_action.action_id) is True
    with pytest.raises(ReplayAttemptForbiddenError, match="already been consumed"):
        session.assert_can_attempt_mutation(cal_action.action_id)


def test_resume_session_interrupted_mutation_requires_read_before_retry(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    cal_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    ledger_path = tmp_path / "mission.ledger"
    storage_path = tmp_path / "snapshots"
    now = datetime(2026, 10, 3, 6, 20, 0, tzinfo=UTC)

    ledger = DurableFileLedger(ledger_path)
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.EXECUTING,
            created_at=now,
            updated_at=now,
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

    # Append UNCERTAIN_POST_EXECUTION_FAILURE evidence to ledger
    origin = EvidenceOrigin.create(
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
        observed_at=now,
    )
    uncertain_payload = {
        "evidence_type": "UNCERTAIN_POST_EXECUTION_FAILURE",
        "action_id": str(cal_action.action_id),
        "mission_id": str(mission_id),
        "attempt_number": 1,
        "error_classification": "TIMEOUT",
    }
    eid = compute_evidence_id({"origin": origin, "payload": uncertain_payload})
    ev_record = EvidenceRecord(
        evidence_id=eid,
        action_id=cal_action.action_id,
        mission_id=mission_id,
        origin=origin,
        payload=uncertain_payload,
        created_at=now,
    )
    ledger.append_evidence(ev_record)

    attempt = ExecutionAttempt(
        action_id=cal_action.action_id,
        idempotency_key=IdempotencyKey.generate(),
        attempt_number=1,
        started_at=now,
    )

    step_rec = StepExecutionRecord(
        action_id=cal_action.action_id,
        status=ActionExecutionStatus.EXECUTION_FAILED,
        attempt=attempt,
        error_message="Network timeout during dispatch",
    )

    repo = DurableSnapshotRepository(storage_path, ledger=ledger)
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.EXECUTING,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[cal_action],
        step_records={cal_action.action_id: step_rec},
        execution_attempts=[attempt],
        evidence_ids=[eid],
        created_at=now,
    )
    repo.save_snapshot(snapshot)

    # Reopen fresh session
    session = resume_mission_session(
        storage_path=storage_path,
        ledger_path=ledger_path,
        mission_id=mission_id,
    )

    # Must detect ambiguous outcome
    assert session.is_ambiguous_outcome(cal_action.action_id) is True
    assert session.requires_read_before_retry(cal_action.action_id) is True

    # Attempting to mutate directly without read-before-retry fails closed
    with pytest.raises(
        UncertainMutationRequiresReadbackError, match="read-back is strictly required"
    ):
        session.assert_can_attempt_mutation(cal_action.action_id)


def test_resume_session_creates_fresh_isolated_instances(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    cal_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    ledger_path = tmp_path / "mission.ledger"
    storage_path = tmp_path / "snapshots"
    now = datetime(2026, 10, 3, 6, 25, 0, tzinfo=UTC)

    ledger = DurableFileLedger(ledger_path)
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.DRAFT,
            created_at=now,
            updated_at=now,
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
    repo = DurableSnapshotRepository(storage_path, ledger=ledger)
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[cal_action],
        created_at=now,
    )
    repo.save_snapshot(snapshot)

    # Resume session A
    session_a = resume_mission_session(
        storage_path=storage_path,
        ledger_path=ledger_path,
        mission_id=mission_id,
    )

    # Resume session B
    session_b = resume_mission_session(
        storage_path=storage_path,
        ledger_path=ledger_path,
        mission_id=mission_id,
    )

    # Invariants: fresh objects, not same in-memory instances
    assert session_a is not session_b
    assert session_a.snapshot is not session_b.snapshot
    assert session_a.ledger is not session_b.ledger
    assert session_a.approval_ledger is not session_b.approval_ledger
    assert session_a.snapshot == session_b.snapshot
    assert session_a.reloaded_writes_performed == 0
    assert session_b.reloaded_writes_performed == 0


def test_resume_session_ledger_read_failure_fails_closed(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    cal_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When reading evidence from ledger fails during resume, raises SessionRestoreError."""
    from stilldone.session import SessionRestoreError

    ledger_path = tmp_path / "mission.ledger"
    storage_path = tmp_path / "snapshots"
    now = datetime(2026, 10, 3, 6, 25, 0, tzinfo=UTC)

    ledger = DurableFileLedger(ledger_path)
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.DRAFT,
            created_at=now,
            updated_at=now,
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
    repo = DurableSnapshotRepository(storage_path, ledger=ledger)
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[cal_action],
        created_at=now,
    )
    repo.save_snapshot(snapshot)

    # Monkeypatch DurableFileLedger.get_evidence_for_mission to simulate I/O or storage failure
    def _broken_get_evidence(self: Any, mid: MissionId) -> Any:
        raise OSError("Disk read error while fetching evidence")

    monkeypatch.setattr(DurableFileLedger, "get_evidence_for_mission", _broken_get_evidence)

    with pytest.raises(SessionRestoreError, match="Failed to read evidence records from ledger"):
        resume_mission_session(
            storage_path=storage_path,
            ledger_path=ledger_path,
            mission_id=mission_id,
        )


def test_resume_session_consumed_approval_disagreement_fails_closed(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    cal_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """When snapshot consumed approval is missing from ApprovalLedger, resume fails closed."""
    from stilldone.approval_consumption import ApprovalConsumptionRecord, ApprovalUsageStatus
    from stilldone.domain.authority import ApprovalId, BindingHash
    from stilldone.session import SessionRestoreError

    ledger_path = tmp_path / "mission.ledger"
    storage_path = tmp_path / "snapshots"
    now = datetime(2026, 10, 3, 6, 25, 0, tzinfo=UTC)

    ledger = DurableFileLedger(ledger_path)
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.DRAFT,
            created_at=now,
            updated_at=now,
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
    repo = DurableSnapshotRepository(storage_path, ledger=ledger)

    # Synthetic consumed approval in snapshot not present in ledger
    foreign_consumed = ApprovalConsumptionRecord(
        approval_id=ApprovalId.generate(),
        mission_id=mission_id,
        action_id=cal_action.action_id,
        binding_hash=BindingHash("a" * 64),
        status=ApprovalUsageStatus.CONSUMED,
        consumed_at=now,
        attempt_number=1,
        reason="Phantom approval",
    )

    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.DRAFT,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[cal_action],
        consumed_approvals=[foreign_consumed],
        created_at=now,
    )
    repo.save_snapshot(snapshot)

    with pytest.raises(SessionRestoreError, match="not found in durable approval ledger"):
        resume_mission_session(
            storage_path=storage_path,
            ledger_path=ledger_path,
            mission_id=mission_id,
        )


def test_resume_session_interrupted_attempt_newer_than_snapshot_detected(
    tmp_path: Path,
    mission_id: MissionId,
    contract: MissionContract,
    cal_action: ActionContract,
    sample_predicate: DesiredStatePredicate,
) -> None:
    """An attempt logged to ledger after snapshot creation is recognized by P-10 recovery."""
    ledger_path = tmp_path / "mission.ledger"
    storage_path = tmp_path / "snapshots"
    t0 = datetime(2026, 10, 3, 6, 20, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)

    ledger = DurableFileLedger(ledger_path)
    ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=contract,
            state=MissionState.EXECUTING,
            created_at=t0,
            updated_at=t0,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=cal_action.action_id,
            mission_id=mission_id,
            action=cal_action,
            approval_id=None,
            created_at=t0,
        )
    )

    # Snapshot saved at t0 without attempts
    repo = DurableSnapshotRepository(storage_path, ledger=ledger)
    snapshot = create_mission_snapshot(
        mission_id=mission_id,
        state=MissionState.EXECUTING,
        contract=contract,
        desired_state=[sample_predicate],
        actions=[cal_action],
        created_at=t0,
    )
    repo.save_snapshot(snapshot)

    # After snapshot was created, an execution attempt occurred at t1 with ambiguous timeout
    from stilldone.recovery.continuity import record_execution_attempt

    record_execution_attempt(
        ledger=ledger,
        action=cal_action,
        attempt_number=1,
        error=TimeoutError("Network timeout during provider dispatch"),
        observed_at=t1,
    )

    # Resume session
    session = resume_mission_session(
        storage_path=storage_path,
        ledger_path=ledger_path,
        mission_id=mission_id,
    )

    # Even though snapshot predates the attempt, canonical recovery state from ledger detects it
    assert session.is_ambiguous_outcome(cal_action.action_id) is True
    assert session.requires_read_before_retry(cal_action.action_id) is True
    with pytest.raises(
        UncertainMutationRequiresReadbackError, match="read-back is strictly required"
    ):
        session.assert_can_attempt_mutation(cal_action.action_id)
