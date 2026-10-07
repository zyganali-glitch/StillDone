"""Tests for durable ledger recovery continuity and process restart (Phase P-10.05).

Enforces StillDone core architectural laws:
- Reuses canonical StillDone ledger/state architecture (MissionLedgerPort).
- DurableFileLedger preserves append-only integrity and durability across restarts.
- On restart, reconstructs deterministic recovery state:
  * Attempt count is reconstructed from durable facts; NEVER reset to 0.
  * Intended mutation identity is deterministic; NEVER regenerated differently.
  * Ambiguous outcome (e.g. timeout) is preserved; NEVER converted to SUCCESS.
  * High-duplicate-risk mutations preserve requires_verification_before_retry;
    NEVER silently re-executed.
  * Attempt ceiling budget survives restart; restart cannot reset retry budget.
- Model / planner proposals have ZERO authority over recovery state reconstruction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.ledger import (
    ActionRecord,
    DuplicateRecordError,
    DurableFileLedger,
    MissionRecord,
    RecordConflictError,
)
from stilldone.planning.contracts import PlannerInput
from stilldone.recovery.continuity import (
    ActionRecoveryState,
    reconstruct_action_recovery_state,
    record_duplicate_determination,
    record_execution_attempt,
)
from stilldone.recovery.duplicate import (
    DuplicateDeterminationStatus,
    DuplicateEvidenceRecord,
    derive_intended_mutation_identity,
)
from stilldone.recovery.idempotency import (
    PlannerRecoveryAuthorityError,
    derive_idempotency_key,
)
from stilldone.recovery.orchestrator import (
    RecoveryActionType,
)
from stilldone.recovery.retry import (
    RetryPolicy,
)

TASKS_TARGET = TargetIdentity(
    system="google_tasks",
    resource_kind=ResourceKind.TASK_LIST,
    resource_id="demo_tasks_123",
    parent_id=None,
)

CAL_TARGET = TargetIdentity(
    system="google_calendar",
    resource_kind=ResourceKind.CALENDAR_EVENT,
    resource_id="event_xyz",
    parent_id="demo_cal@example.com",
)


def _seed_mission_and_action(
    ledger: DurableFileLedger,
    action_type: ActionType,
    target: TargetIdentity,
    parameters: dict[str, str],
) -> tuple[MissionContract, ActionContract]:
    mission = MissionContract.create("Prepare family for tomorrow")
    action = ActionContract.create(
        mission_id=mission.mission_id,
        action_type=action_type,
        target=target,
        parameters=parameters,
    )

    ledger.append_mission(
        MissionRecord(
            mission_id=mission.mission_id,
            contract=mission,
            state=MissionState.EXECUTING,
            created_at=mission.created_at,
            updated_at=mission.created_at,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=action.action_id,
            mission_id=mission.mission_id,
            action=action,
            approval_id=None,
            created_at=mission.created_at,
        )
    )
    return mission, action


class TestDurableFileLedgerBasics:
    """Verifies durable append-only file ledger properties and reload integrity."""

    def test_durable_file_ledger_classification_and_persistence(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        assert ledger1.IS_DURABLE is True
        assert ledger1.DURABILITY_CLASSIFICATION == "DURABLE_APPEND_ONLY_FILE"

        mission, action = _seed_mission_and_action(
            ledger1, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error=TimeoutError("Ambiguous write timeout"),
        )

        assert log_file.exists()
        assert log_file.stat().st_size > 0

        # Simulate process restart by loading a fresh DurableFileLedger instance
        ledger2 = DurableFileLedger(log_file)
        assert ledger2.get_mission(mission.mission_id).mission_id == mission.mission_id
        assert ledger2.get_action(action.action_id).action_id == action.action_id
        evs = ledger2.get_evidence_for_action(action.action_id)
        assert len(evs) == 1
        assert evs[0].payload["attempt_number"] == 1
        assert evs[0].payload["classification"] == "AMBIGUOUS_TIMEOUT"

    def test_durable_ledger_fails_closed_on_duplicate_and_conflict(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        mission, _ = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        m_rec = ledger.get_mission(mission.mission_id)
        with pytest.raises(DuplicateRecordError):
            ledger.append_mission(m_rec)

        # Conflict: different state with same ID
        conflict_rec = MissionRecord(
            mission_id=m_rec.mission_id,
            contract=m_rec.contract,
            state=MissionState.FAILED,
            created_at=m_rec.created_at,
            updated_at=m_rec.updated_at,
        )
        with pytest.raises(RecordConflictError):
            ledger.append_mission(conflict_rec)


class TestProcessRestartContinuity:
    """Verifies state reconstruction following crash or restart."""

    def test_attempt_count_never_resets_across_restart(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger1, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error=TimeoutError("Timeout 1"),
        )
        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=2,
            error=503,
        )

        # Drop ledger1 to simulate crash
        del ledger1

        # Process restart
        ledger_resumed = DurableFileLedger(log_file)
        state: ActionRecoveryState = reconstruct_action_recovery_state(
            action=action,
            ledger=ledger_resumed,
        )

        # Invariant: attempt count is 2; NEVER reset to 0!
        assert state.prior_attempt_count == 2
        assert state.remaining_attempt_budget == 1  # 3 - 2 = 1

    def test_intended_mutation_identity_survives_restart_identically(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger1, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        ident_before = derive_intended_mutation_identity(action)
        key_before = derive_idempotency_key(action, 1)

        del ledger1
        ledger_resumed = DurableFileLedger(log_file)
        state = reconstruct_action_recovery_state(action=action, ledger=ledger_resumed)

        assert state.intended_mutation.mutation_id == ident_before.mutation_id
        assert state.intended_mutation.idempotency_key == ident_before.idempotency_key
        assert state.stable_idempotency_key == key_before

    def test_ambiguous_outcome_preserved_never_converted_to_success(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger1, ActionType.CALENDAR_UPDATE, CAL_TARGET, {"summary": "Briefing"}
        )

        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error=TimeoutError("Ambiguous gateway timeout"),
        )

        del ledger1
        ledger_resumed = DurableFileLedger(log_file)
        state = reconstruct_action_recovery_state(action=action, ledger=ledger_resumed)

        assert state.is_ambiguous_outcome is True
        assert state.requires_verification_before_retry is True
        # Resumption decision must require verification; never assumes success!
        assert state.resumption_decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION

    def test_task_create_requires_read_before_retry_on_restart(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger1, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        # In-flight timeout
        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error=TimeoutError("Timeout after create write"),
        )

        del ledger1
        ledger_resumed = DurableFileLedger(log_file)
        state = reconstruct_action_recovery_state(action=action, ledger=ledger_resumed)

        # Never blindly retries; requires verification!
        assert state.requires_verification_before_retry is True
        assert state.resumption_decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION
        assert state.resumption_decision.delay_seconds == 0.0

    def test_attempt_ceiling_survives_restart_no_budget_reset(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger1, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        # Exhaust 3 attempts
        for att in range(1, 4):
            record_execution_attempt(
                ledger=ledger1,
                action=action,
                attempt_number=att,
                error=503,
            )

        del ledger1
        ledger_resumed = DurableFileLedger(log_file)
        state = reconstruct_action_recovery_state(
            action=action,
            ledger=ledger_resumed,
            policy=RetryPolicy(max_attempts=3),
        )

        # Attempt budget exhausted; cannot retry
        assert state.prior_attempt_count == 3
        assert state.remaining_attempt_budget == 0
        assert state.resumption_decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert "ceiling reached" in state.resumption_decision.reason.lower()

    def test_restart_with_persisted_duplicate_evidence(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger1, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        # Attempt 1 had timeout
        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error=TimeoutError("Timeout"),
        )

        # Duplicate check observed intended effect exists
        dup_ev = DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS,
            intended_mutation=derive_intended_mutation_identity(action),
            match_count=1,
        )
        record_duplicate_determination(ledger=ledger1, duplicate_evidence=dup_ev)

        del ledger1
        # Process restart
        ledger_resumed = DurableFileLedger(log_file)
        state = reconstruct_action_recovery_state(action=action, ledger=ledger_resumed)

        assert state.duplicate_evidence is not None
        assert (
            state.duplicate_evidence.status == DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS
        )
        # Resumption decision proves intended effect already exists; no second mutation!
        assert state.resumption_decision.action_type == RecoveryActionType.EFFECT_ALREADY_EXISTS


class TestContinuityModelRejection:
    """Verifies that model / planner proposals cannot inject or rewrite recovery truth."""

    def test_planner_proposal_rejected_in_state_reconstruction(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        planner_input = PlannerInput(mission_id=MissionId.generate(), intent="rewrite state")

        with pytest.raises(PlannerRecoveryAuthorityError):
            reconstruct_action_recovery_state(
                action=planner_input,  # type: ignore[arg-type]
                ledger=ledger,
            )
