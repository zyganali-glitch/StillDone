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

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.evidence import compute_evidence_id
from stilldone.ledger import (
    ActionRecord,
    DuplicateRecordError,
    DurableFileLedger,
    EvidenceRecord,
    LedgerError,
    MissionRecord,
    RecordConflictError,
    RecordNotFoundError,
)
from stilldone.planning.contracts import PlannerInput
from stilldone.recovery.continuity import (
    ActionRecoveryState,
    RecoveryContinuityError,
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


class TestDurableFileLedgerReloadIntegrity:
    """Verifies that DurableFileLedger._load_from_file enforces append-only truth (Defect 6)."""

    def test_reload_conflicting_same_mission_id_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "conflicting_mission.jsonl"
        ledger = DurableFileLedger(log_file)
        m1, _ = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Task 1"}
        )
        del ledger

        # Tamper: append a conflicting mission record with same ID but different text
        m2 = MissionContract.create("Conflicting text")
        tampered_entry = {
            "record_type": "mission",
            "mission_id": str(m1.mission_id),
            "contract": {
                "mission_id": str(m1.mission_id),
                "intent": {
                    "text": "Completely different text",
                    "captured_at": m2.intent.captured_at.isoformat(),
                    "mission_id": str(m1.mission_id),
                },
                "created_at": m2.created_at.isoformat(),
                "schema_version": "v1",
            },
            "state": MissionState.FAILED.value,
            "created_at": m2.created_at.isoformat(),
            "updated_at": m2.created_at.isoformat(),
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(tampered_entry) + "\n")

        with pytest.raises(RecordConflictError, match="Conflicting record for mission"):
            DurableFileLedger(log_file)

    def test_reload_duplicate_identical_mission_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "dup_mission.jsonl"
        ledger = DurableFileLedger(log_file)
        _seed_mission_and_action(ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Task 1"})
        del ledger

        lines = log_file.read_text(encoding="utf-8").splitlines()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(lines[0] + "\n")

        with pytest.raises(DuplicateRecordError, match="Duplicate mission"):
            DurableFileLedger(log_file)

    def test_reload_conflicting_same_action_id_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "conflicting_action.jsonl"
        ledger = DurableFileLedger(log_file)
        m1, a1 = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Task 1"}
        )
        del ledger

        tampered_entry = {
            "record_type": "action",
            "action_id": str(a1.action_id),
            "mission_id": str(m1.mission_id),
            "action": {
                "action_id": str(a1.action_id),
                "mission_id": str(m1.mission_id),
                "action_type": ActionType.CALENDAR_UPDATE.value,
                "target": {
                    "system": "google_calendar",
                    "resource_kind": "calendar_event",
                    "resource_id": "other_event",
                },
                "parameters": {"summary": "Tampered"},
            },
            "created_at": m1.created_at.isoformat(),
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(tampered_entry) + "\n")

        with pytest.raises(RecordConflictError, match="Conflicting record for action"):
            DurableFileLedger(log_file)

    def test_reload_conflicting_forged_evidence_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "forged_evidence.jsonl"
        ledger = DurableFileLedger(log_file)
        m1, a1 = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Task 1"}
        )
        del ledger

        tampered_entry = {
            "record_type": "evidence",
            "evidence_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "action_id": str(a1.action_id),
            "mission_id": str(m1.mission_id),
            "origin": {
                "provenance": "LOCAL_EXECUTION",
                "observed_at": datetime.now(UTC).isoformat(),
            },
            "payload": {"tampered": True},
            "created_at": datetime.now(UTC).isoformat(),
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(tampered_entry) + "\n")

        with pytest.raises(RecordConflictError, match="failed content-address validation"):
            DurableFileLedger(log_file)

    def test_reload_action_referencing_absent_mission_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "absent_mission.jsonl"
        tampered_entry = {
            "record_type": "action",
            "action_id": str(ActionId.generate()),
            "mission_id": str(MissionId.generate()),
            "action": {
                "action_id": str(ActionId.generate()),
                "mission_id": str(MissionId.generate()),
                "action_type": ActionType.TASK_CREATE.value,
                "target": {
                    "system": "google_tasks",
                    "resource_kind": "task_list",
                    "resource_id": "demo",
                },
                "parameters": {"title": "Orphan"},
            },
            "created_at": datetime.now(UTC).isoformat(),
        }
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(tampered_entry) + "\n")

        with pytest.raises(RecordNotFoundError, match="references absent mission"):
            DurableFileLedger(log_file)

    def test_reload_evidence_referencing_absent_action_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "absent_action.jsonl"
        ledger = DurableFileLedger(log_file)
        m1, _ = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Task 1"}
        )
        del ledger

        absent_action_id = ActionId.generate()
        origin = EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=datetime.now(UTC)
        )
        payload = {"sample": "val"}
        eid = compute_evidence_id({"origin": origin, "payload": payload})

        tampered_entry = {
            "record_type": "evidence",
            "evidence_id": str(eid),
            "action_id": str(absent_action_id),
            "mission_id": str(m1.mission_id),
            "origin": {
                "provenance": "LOCAL_EXECUTION",
                "observed_at": origin.observed_at.isoformat(),
            },
            "payload": payload,
            "created_at": datetime.now(UTC).isoformat(),
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(tampered_entry) + "\n")

        with pytest.raises(RecordNotFoundError, match="references absent action"):
            DurableFileLedger(log_file)

    def test_reload_unknown_record_type_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "unknown_rec.jsonl"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"record_type": "unsupported_entity", "val": 123}) + "\n")

        with pytest.raises(LedgerError, match="Unknown record_type"):
            DurableFileLedger(log_file)

    def test_reload_malformed_truncated_final_record_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "truncated.jsonl"
        ledger = DurableFileLedger(log_file)
        _seed_mission_and_action(ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Task 1"})
        del ledger

        with open(log_file, "a", encoding="utf-8") as f:
            f.write('{"record_type": "mission", "mission_id": "half-wri' + "\n")

        with pytest.raises(LedgerError, match="Malformed or corrupt entry"):
            DurableFileLedger(log_file)


class TestLedgerReadFailureFailClosed:
    """Verifies that durable ledger read failures fail closed and never produce RETRY (Defect 2)."""

    def test_ledger_evidence_read_failure_raises_recovery_continuity_error(
        self, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        # Mock get_evidence_for_action to raise an unexpected read exception
        mock_ledger = MagicMock(spec=DurableFileLedger)
        mock_ledger.get_action.return_value = ledger.get_action(action.action_id)
        mock_ledger.get_evidence_for_action.side_effect = OSError("Disk read I/O error")

        with pytest.raises(
            RecoveryContinuityError, match="Unable to read durable recovery evidence"
        ):
            reconstruct_action_recovery_state(action=action, ledger=mock_ledger)

    def test_action_missing_from_ledger_raises_recovery_continuity_error(
        self, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        # Create action without seeding into ledger
        mission = MissionContract.create("Prepare family")
        action = ActionContract.create(
            mission_id=mission.mission_id,
            action_type=ActionType.TASK_CREATE,
            target=TASKS_TARGET,
            parameters={"title": "Unregistered task"},
        )

        with pytest.raises(RecoveryContinuityError, match="Unable to read canonical action"):
            reconstruct_action_recovery_state(action=action, ledger=ledger)


class TestDurableSuccessRestartSemantics:
    """Verifies that durable execution success survives restart without RETRY (Defect 3)."""

    def test_task_create_durable_success_restart_produces_no_second_create(
        self, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger1, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        # Durably record execution SUCCESS (error=None)
        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error=None,
        )

        # Process restart
        del ledger1
        ledger2 = DurableFileLedger(log_file)
        state = reconstruct_action_recovery_state(action=action, ledger=ledger2)

        assert state.prior_attempt_count == 1
        assert state.resumption_decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert "downstream verification remains required" in state.resumption_decision.reason

    def test_calendar_update_durable_success_restart_produces_no_second_update(
        self, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger1, ActionType.CALENDAR_UPDATE, CAL_TARGET, {"summary": "Updated meeting"}
        )

        # Durably record execution SUCCESS
        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error=None,
        )

        # Process restart
        del ledger1
        ledger2 = DurableFileLedger(log_file)
        state = reconstruct_action_recovery_state(action=action, ledger=ledger2)

        assert state.prior_attempt_count == 1
        assert state.resumption_decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert "downstream verification remains required" in state.resumption_decision.reason

    def test_read_only_action_durable_success_restart_no_transient_retry(
        self, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger1 = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(ledger1, ActionType.CALENDAR_READ, CAL_TARGET, {})

        # Durably record execution SUCCESS
        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error=None,
        )

        # Process restart
        del ledger1
        ledger2 = DurableFileLedger(log_file)
        state = reconstruct_action_recovery_state(action=action, ledger=ledger2)

        assert state.prior_attempt_count == 1
        assert state.resumption_decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert "no further execution required" in state.resumption_decision.reason


class TestAttemptHistoryIntegrity:
    """Verifies that gapped, duplicate, or corrupted attempt history fails closed (Defect 4)."""

    def test_gapped_attempt_numbers_fail_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        # Record attempt 1, then attempt 3 (attempt 2 missing)
        record_execution_attempt(
            ledger=ledger, action=action, attempt_number=1, error=TimeoutError()
        )
        record_execution_attempt(
            ledger=ledger, action=action, attempt_number=3, error=TimeoutError()
        )

        with pytest.raises(
            RecoveryContinuityError, match="Non-contiguous, duplicate, or out-of-order"
        ):
            reconstruct_action_recovery_state(action=action, ledger=ledger)

    def test_duplicate_conflicting_attempt_number_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        # Record attempt 1 twice with different errors
        record_execution_attempt(
            ledger=ledger, action=action, attempt_number=1, error=TimeoutError("First")
        )
        record_execution_attempt(
            ledger=ledger, action=action, attempt_number=1, error=ValueError("Second")
        )

        with pytest.raises(
            RecoveryContinuityError, match="Non-contiguous, duplicate, or out-of-order"
        ):
            reconstruct_action_recovery_state(action=action, ledger=ledger)

    def test_malformed_attempt_number_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        origin = EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=datetime.now(UTC)
        )
        bad_payload = {
            "evidence_type": "EXECUTION_ATTEMPT",
            "attempt_number": "not_an_int",  # Malformed
            "action_id": str(action.action_id),
            "mission_id": str(action.mission_id),
            "action_type": action.action_type.value,
            "success": False,
        }
        eid = compute_evidence_id({"origin": origin, "payload": bad_payload})
        ev = EvidenceRecord(
            evidence_id=eid,
            action_id=action.action_id,
            mission_id=action.mission_id,
            origin=origin,
            payload=bad_payload,
            created_at=datetime.now(UTC),
        )
        ledger.append_evidence(ev)

        with pytest.raises(RecoveryContinuityError, match="invalid attempt_number"):
            reconstruct_action_recovery_state(action=action, ledger=ledger)

    def test_wrong_action_lineage_in_attempt_evidence_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        # Inject attempt evidence with mismatched action_type in payload
        origin = EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=datetime.now(UTC)
        )
        bad_payload = {
            "evidence_type": "EXECUTION_ATTEMPT",
            "attempt_number": 1,
            "action_id": str(action.action_id),
            "mission_id": str(action.mission_id),
            "action_type": ActionType.CALENDAR_UPDATE.value,  # Wrong!
            "success": False,
        }
        eid = compute_evidence_id({"origin": origin, "payload": bad_payload})
        ev = EvidenceRecord(
            evidence_id=eid,
            action_id=action.action_id,
            mission_id=action.mission_id,
            origin=origin,
            payload=bad_payload,
            created_at=datetime.now(UTC),
        )
        ledger.append_evidence(ev)

        with pytest.raises(RecoveryContinuityError, match="payload action_type mismatch"):
            reconstruct_action_recovery_state(action=action, ledger=ledger)


class TestDuplicateEvidenceLineageValidation:
    """Verifies that forged or mismatched duplicate evidence lineage fails closed (Defect 5)."""

    def test_forged_mutation_id_in_duplicate_evidence_fails_closed(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        origin = EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=datetime.now(UTC)
        )
        bad_payload = {
            "evidence_type": "DUPLICATE_DETERMINATION",
            "status": DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS.value,
            "mutation_id": "forged_mutation_id_xyz_999",  # Forged!
            "idempotency_key": derive_idempotency_key(action, 1),
            "action_id": str(action.action_id),
            "mission_id": str(action.mission_id),
            "action_type": action.action_type.value,
            "match_count": 1,
        }
        eid = compute_evidence_id({"origin": origin, "payload": bad_payload})
        ev = EvidenceRecord(
            evidence_id=eid,
            action_id=action.action_id,
            mission_id=action.mission_id,
            origin=origin,
            payload=bad_payload,
            created_at=datetime.now(UTC),
        )
        ledger.append_evidence(ev)

        with pytest.raises(RecoveryContinuityError, match="mutation_id mismatch"):
            reconstruct_action_recovery_state(action=action, ledger=ledger)

    def test_forged_idempotency_key_in_duplicate_evidence_fails_closed(
        self, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "ledger.jsonl"
        ledger = DurableFileLedger(log_file)
        _, action = _seed_mission_and_action(
            ledger, ActionType.TASK_CREATE, TASKS_TARGET, {"title": "Pack lunch"}
        )

        intended_mutation = derive_intended_mutation_identity(action)
        origin = EvidenceOrigin(
            provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=datetime.now(UTC)
        )
        bad_payload = {
            "evidence_type": "DUPLICATE_DETERMINATION",
            "status": DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS.value,
            "mutation_id": intended_mutation.mutation_id,
            "idempotency_key": "forged_idempotency_key_123",  # Forged!
            "action_id": str(action.action_id),
            "mission_id": str(action.mission_id),
            "action_type": action.action_type.value,
            "match_count": 1,
        }
        eid = compute_evidence_id({"origin": origin, "payload": bad_payload})
        ev = EvidenceRecord(
            evidence_id=eid,
            action_id=action.action_id,
            mission_id=action.mission_id,
            origin=origin,
            payload=bad_payload,
            created_at=datetime.now(UTC),
        )
        ledger.append_evidence(ev)

        with pytest.raises(RecoveryContinuityError, match="idempotency_key mismatch"):
            reconstruct_action_recovery_state(action=action, ledger=ledger)
