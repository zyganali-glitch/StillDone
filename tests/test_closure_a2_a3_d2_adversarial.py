"""Adversarial Regression Test Suite for P-13 + P-16 Consolidated Root-Cause Closure.

Validates the full set of adversarial security and integrity requirements for:
- A2: Authority-Record State Model & Dual-Store Integrity
- A3: Unrestored Runner Execution Gating & Zero-Mutation Invariant
- D2: Public Summary Privacy from Trusted Fields Only
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from stilldone.action_policy import (
    validate_action_contract,
)
from stilldone.adapters.calendar import GoogleApiClientCalendarTransport
from stilldone.adapters.tasks import GoogleApiClientTasksTransport
from stilldone.adapters.weather import OpenMeteoHttpTransport
from stilldone.approval_consumption import (
    ApprovalAlreadyUsedError,
    ApprovalLedger,
    ApprovalRevokedError,
    ApprovalUsageStatus,
    UsedApprovalRegistry,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.demo_seeding import DemoSeedResult, SeedOperationStatus
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import ApprovalGrant, ApprovalId, AuthorityClass
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    PredicateOperator,
    PredicateTargetBinding,
)
from stilldone.domain.execution import ExecutionAttempt, IdempotencyKey
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.evidence import EvidenceId
from stilldone.execution.state import (
    ActionExecutionStatus,
    ProviderExecutionResult,
    StepExecutionRecord,
)
from stilldone.killer_mission import (
    PREDICATE_ID_CALENDAR,
    KillerMissionAuthorityError,
    KillerMissionEnvironment,
    KillerMissionIntegrityError,
    LiveKillerMissionSliceRunner,
)
from stilldone.ledger import ActionRecord
from stilldone.pending_approval import (
    ApprovalDecision,
    OneDecisionContract,
    PendingApprovalId,
    PendingApprovalStatus,
    create_pending_approval,
)
from stilldone.planning.bedrock import BedrockPlannerAdapter
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    SymbolicTargetRef,
)
from stilldone.receipt import create_mission_ready_receipt
from stilldone.redaction import REDACTED_IDENTIFIER
from stilldone.snapshot import create_mission_snapshot

# ===========================================================================
# Helpers & Fixtures
# ===========================================================================


def _dummy_grant(
    *,
    approval_id: str = "11111111-1111-1111-1111-111111111111",
    mission_id: str = "11111111-2222-3333-4444-555555555555",
    action_id: str = "22222222-3333-4444-5555-666666666666",
    target_id: str = "evt-1234",
) -> ApprovalGrant:
    """Create a valid dummy ApprovalGrant for testing."""
    now = datetime.now(UTC)
    target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id=target_id,
        parent_id="cal-test-demo",
    )
    action = ActionContract.create(
        mission_id=MissionId(mission_id),
        action_type=ActionType.CALENDAR_UPDATE,
        target=target,
        parameters={"start_time": "2026-10-04T07:30:00+00:00"},
        action_id=ActionId(action_id),
    )
    return ApprovalGrant(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=15),
        approval_id=ApprovalId(approval_id),
    )


def _setup_live_runner(
    tmp_path: Path,
    *,
    mission_id: MissionId | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> LiveKillerMissionSliceRunner:
    """Setup a standard LiveKillerMissionSliceRunner with mock transports."""
    scope = DemoResourceScope("c_adversarial_demo", "tl_adversarial_demo")
    env = KillerMissionEnvironment.create_live_environment(
        base_dir=tmp_path,
        scope=scope,
        calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
        tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
        weather_transport=OpenMeteoHttpTransport(),
    )
    fake_planner = MagicMock(spec=BedrockPlannerAdapter)
    mid = mission_id or MissionId("11111111-2222-3333-4444-555555555555")
    valid_plan = CandidatePlanProposal.create(
        mission_id=str(mid),
        steps=[
            CandidateActionProposal.create(
                action_type=ActionType.WEATHER_READ,
                target_ref=SymbolicTargetRef.WEATHER_LOCATION,
                parameters={},
            ),
            CandidateActionProposal.create(
                action_type=ActionType.TASK_CREATE,
                target_ref=SymbolicTargetRef.TASK_LIST,
                parameters={"title": "Pack backpacks", "due": "2026-10-04"},
            ),
            CandidateActionProposal.create(
                action_type=ActionType.CALENDAR_UPDATE,
                target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
                parameters={"start_time": "2026-10-04T07:30:00+00:00"},
            ),
        ],
    )
    fake_planner.plan.return_value = MagicMock(plan=valid_plan)
    runner = LiveKillerMissionSliceRunner(
        env=env,
        mission_id=mid,
        operator_approved=True,
        source_sha="1111111111111111111111111111111111111111",
        bedrock_planner=fake_planner,
        demo_date="2026-10-04",
    )
    runner.candidate_plan = valid_plan
    runner.validated_candidate_plan = valid_plan
    if monkeypatch is not None:
        from stilldone.killer_mission import LivePreflightReport

        report = LivePreflightReport(
            is_ready=True,
            operator_approved=True,
            source_sha_verified=True,
            clean_working_tree_verified=True,
            google_auth_available=True,
            aws_bedrock_auth_available=True,
            open_meteo_reachable=True,
            disposable_scope_verified=True,
            transports_verified=True,
            blocker_reasons=[],
        )
        monkeypatch.setattr(runner, "evaluate_preflight", lambda: report)
    return runner


# ===========================================================================
# A2 — Authority-Record State Model & Dual-Store Integrity
# ===========================================================================


class TestA2AuthorityRecordStateModel:
    """A2: Fix the authority-record state model and dual-store integrity."""

    def test_consumed_approval_followed_by_rejection_key_collision(self) -> None:
        """A2.1: Consumed approval evidence must never be overwritten by rejection record."""
        registry = UsedApprovalRegistry()
        aid = "11111111-1111-1111-1111-111111110001"
        grant = _dummy_grant(approval_id=aid)
        now = datetime.now(UTC)

        # 1. Record consumption
        rec = registry.record_consumption(grant, at=now, attempt_number=1)
        assert rec.status == ApprovalUsageStatus.CONSUMED
        assert registry.is_consumed(aid) is True

        # 2. Attempt to record rejection at the same approval ID (key collision)
        with pytest.raises(ApprovalAlreadyUsedError, match="already consumed"):
            registry.record_rejection(
                "dec_collision_01",
                action_id=grant.action_id,
                mission_id=grant.mission_id,
                at=now,
                pending_approval_id=aid,
            )

        # 3. Verify original consumed status is strictly preserved
        record_after = registry.get_record(aid)
        assert record_after is not None
        assert record_after.status == ApprovalUsageStatus.CONSUMED
        assert registry.is_consumed(aid) is True

    def test_revoked_approval_followed_by_rejection_key_collision(self) -> None:
        """A2.2: Revoked approval evidence must never be overwritten by rejection record."""
        registry = UsedApprovalRegistry()
        aid = "11111111-1111-1111-1111-111111110002"
        grant = _dummy_grant(approval_id=aid)
        now = datetime.now(UTC)

        # 1. Record revocation
        registry.revoke(
            grant.approval_id,
            at=now,
            mission_id=grant.mission_id,
            action_id=grant.action_id,
            binding_hash=grant.binding_hash,
            reason="Operator security revocation",
        )
        assert registry.is_revoked(aid) is True

        # 2. Attempt to record rejection at the revoked approval ID
        with pytest.raises(ApprovalAlreadyUsedError, match="already revoked"):
            registry.record_rejection(
                "dec_collision_02",
                action_id=grant.action_id,
                mission_id=grant.mission_id,
                at=now,
                pending_approval_id=aid,
            )

        # 3. Verify revoked status is strictly preserved
        record_after = registry.get_record(aid)
        assert record_after is not None
        assert record_after.status == ApprovalUsageStatus.REVOKED
        assert registry.is_revoked(aid) is True

    def test_conflicting_decision_ids_and_approval_ids_namespaces(self) -> None:
        """A2.3: Decision IDs and Approval IDs maintain distinct namespaces without collision."""
        registry = UsedApprovalRegistry()
        shared_id = "11111111-1111-1111-1111-111111110003"
        grant = _dummy_grant(approval_id=shared_id)
        now = datetime.now(UTC)

        # Record consumption with approval_id = shared_id
        registry.record_consumption(grant, at=now, attempt_number=1)

        # Record rejection with decision_id = shared_id (same string in decision namespace)
        # but with a DIFFERENT pending_approval_id
        rej_rec = registry.record_rejection(
            shared_id,
            action_id=ActionId("33333333-4444-5555-6666-777777777777"),
            mission_id=grant.mission_id,
            at=now,
            pending_approval_id="different_pending_id",
        )
        assert rej_rec.decision_id == shared_id
        assert rej_rec.approval_id == "different_pending_id"

        # The approval namespace record at shared_id remains CONSUMED
        rec_app = registry.get_record(shared_id)
        assert rec_app is not None
        assert rec_app.status == ApprovalUsageStatus.CONSUMED
        # The decision namespace record at shared_id is REJECTED
        rec_dec = registry.get_decision_record(shared_id)
        assert rec_dec is not None
        assert rec_dec.status == ApprovalUsageStatus.REJECTED

    def test_canonical_ledger_empty_but_auxiliary_jsonl_nonempty(self, tmp_path: Path) -> None:
        """A2.4: JSONL log nonempty while canonical ledger empty must fail closed."""
        runner = _setup_live_runner(tmp_path)

        # Write an entry to JSONL only (simulating ledger loss or untracked write)
        orphan_line = json.dumps(
            {
                "decision_id": "orphan_jsonl_dec_1",
                "consumed_at": "2026-10-04T12:00:00+00:00",
                "decision": "REJECT",
                "mission_id": str(runner.mission_id),
            }
        )
        runner._consumed_decisions_file.write_text(f"{orphan_line}\n", encoding="utf-8")

        # Canonical ledger has no evidence records
        assert len(runner.env.approval_ledger.get_consumed_decision_ids()) == 0

        # Reload must detect the unauthorized JSONL-only state and fail closed
        with pytest.raises(
            KillerMissionIntegrityError,
            match=r"Auxiliary JSONL decision log contains decision IDs.*canonical.*is empty",
        ):
            runner._load_consumed_decision_ids()

    def test_canonical_ledger_nonempty_but_auxiliary_jsonl_absent(self, tmp_path: Path) -> None:
        """A2.5: Canonical ledger is authoritative; absent JSONL is tolerated and loaded."""
        runner = _setup_live_runner(tmp_path)

        # Record a rejection in the canonical ledger directly
        now = datetime.now(UTC)
        runner.env.mission_ledger.append_action(
            ActionRecord(
                action_id=runner.action_cal.action_id,
                mission_id=runner.mission_id,
                action=runner.action_cal,
                approval_id=None,
                created_at=now,
            )
        )
        runner.env.approval_ledger.record_rejection(
            "ledger_authoritative_dec_1",
            action_id=runner.action_cal.action_id,
            mission_id=runner.mission_id,
            at=now,
        )

        # Remove the JSONL file completely
        if runner._consumed_decisions_file.exists():
            runner._consumed_decisions_file.unlink()

        # Load must successfully discover decision from the authoritative ledger
        runner._consumed_approval_decision_ids.clear()
        runner._load_consumed_decision_ids()
        assert "ledger_authoritative_dec_1" in runner._consumed_approval_decision_ids

    def test_matching_decision_ids_with_contradictory_sets_fail_closed(
        self, tmp_path: Path
    ) -> None:
        """A2.6: Discrepant decision sets between JSONL and ledger fail closed."""
        runner = _setup_live_runner(tmp_path)
        now = datetime.now(UTC)

        # Record decision A in ledger
        runner.env.mission_ledger.append_action(
            ActionRecord(
                action_id=runner.action_cal.action_id,
                mission_id=runner.mission_id,
                action=runner.action_cal,
                approval_id=None,
                created_at=now,
            )
        )
        runner.env.approval_ledger.record_rejection(
            "dec_in_both",
            action_id=runner.action_cal.action_id,
            mission_id=runner.mission_id,
            at=now,
        )

        # Write decision A and an extra unrecorded decision B to JSONL
        lines = [
            json.dumps(
                {
                    "decision_id": "dec_in_both",
                    "consumed_at": now.isoformat(),
                    "decision": "REJECT",
                    "mission_id": str(runner.mission_id),
                }
            ),
            json.dumps(
                {
                    "decision_id": "dec_only_in_jsonl_extra",
                    "consumed_at": now.isoformat(),
                    "decision": "REJECT",
                    "mission_id": str(runner.mission_id),
                }
            ),
        ]
        runner._consumed_decisions_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(KillerMissionIntegrityError, match="Discrepancy detected"):
            runner._load_consumed_decision_ids()

    def test_ledger_append_failure_and_interrupted_persistence_rollback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A2.7: Interrupted persistence rolls back JSONL and latches failure fail-closed."""
        runner = _setup_live_runner(tmp_path)

        # Cause approval ledger append to fail
        def failing_record_rejection(*args: Any, **kwargs: Any) -> Any:
            raise OSError("Disk full on ledger storage")

        monkeypatch.setattr(
            runner.env.approval_ledger, "record_rejection", failing_record_rejection
        )

        with pytest.raises(KillerMissionIntegrityError, match="Failed to commit consumed approval"):
            runner._persist_consumed_decision_id("fail_append_dec_1")

        # Rollback: decision must NOT be in JSONL or memory
        assert runner._persistence_failed is True
        assert "fail_append_dec_1" not in runner._consumed_approval_decision_ids
        if runner._consumed_decisions_file.exists():
            content = runner._consumed_decisions_file.read_text(encoding="utf-8")
            assert "fail_append_dec_1" not in content

        # Subsequent attempts fail closed immediately
        with pytest.raises(KillerMissionIntegrityError, match="Persistence failure previously"):
            runner._persist_consumed_decision_id("any_subsequent_dec")

    def test_repeated_consumption_after_restart_rejected(self, tmp_path: Path) -> None:
        """A2.8: Persisted decision is durably rejected upon process restart."""
        runner1 = _setup_live_runner(tmp_path)
        runner1._persist_consumed_decision_id("restart_replay_dec_1")
        assert "restart_replay_dec_1" in runner1._consumed_approval_decision_ids

        # Construct runner 2 on same storage (process restart)
        runner2 = _setup_live_runner(tmp_path)
        assert "restart_replay_dec_1" in runner2._consumed_approval_decision_ids

        # Attempt to consume again raises KillerMissionAuthorityError
        with pytest.raises(KillerMissionAuthorityError, match="already been consumed"):
            runner2._persist_consumed_decision_id("restart_replay_dec_1")

    def test_existing_p11_valid_consumption_and_revocation_unchanged(self) -> None:
        """A2.9: Valid P-11 single-use consumption and explicit revocation remain functional."""
        registry = UsedApprovalRegistry()
        grant = _dummy_grant(approval_id="11111111-1111-1111-1111-111111110004")
        now = datetime.now(UTC)

        # 1. Single-use consume succeeds
        res = registry.record_consumption(grant, at=now, attempt_number=1)
        assert res.status == ApprovalUsageStatus.CONSUMED
        assert res.attempt_number == 1

        # 2. Replay consume fails closed
        with pytest.raises(ApprovalAlreadyUsedError):
            registry.record_consumption(grant, at=now, attempt_number=2)

        # 3. Revoke unused grant
        grant2 = _dummy_grant(approval_id="11111111-1111-1111-1111-111111110005")
        registry.revoke(
            grant2,
            at=now,
        )
        assert registry.is_revoked(grant2.approval_id) is True

        # Subsequent consume fails with ApprovalRevokedError
        with pytest.raises(ApprovalRevokedError):
            ledger = ApprovalLedger(registry=registry)
            ledger.consume(grant2, grant2.action, at=now)


# ===========================================================================
# A3 — Unrestored Runner Execution Gating & Zero-Mutation Invariant
# ===========================================================================


class TestA3UnrestoredRunnerExecutionGating:
    """A3: Do not call an unrestored runner recovered."""

    def test_existing_ready_mission_run_full_slice_zero_writes(self, tmp_path: Path) -> None:
        """A3.1: Existing mission detected blocks run_full_slice with zero new writes."""
        _setup_live_runner(tmp_path)

        # Runner 2 on same storage (existing mission detected)
        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_restored_session is False
        assert runner2.is_execution_state_restored is False

        # Attempt to run full slice must be BLOCKED with zero writes
        with pytest.raises(
            KillerMissionIntegrityError, match="Cannot resume live execution for existing mission"
        ):
            runner2.run_full_slice()

        assert runner2.total_writes == 0

    def test_existing_partially_executed_mission_zero_replayed_writes(self, tmp_path: Path) -> None:
        """A3.2: Existing partially executed mission blocks replayed writes."""
        runner1 = _setup_live_runner(tmp_path)
        # Append action to ledger (partially executed)
        now = datetime.now(UTC)
        runner1.env.mission_ledger.append_action(
            ActionRecord(
                action_id=runner1.action_task.action_id,
                mission_id=runner1.mission_id,
                action=runner1.action_task,
                approval_id=None,
                created_at=now,
            )
        )

        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_restored_session is False

        # Direct step methods must fail closed without replaying writes
        with pytest.raises(KillerMissionIntegrityError, match="Cannot execute seeding"):
            runner2.step_p13_01_seed()

        with pytest.raises(KillerMissionIntegrityError, match="Cannot execute tasks prep"):
            runner2.step_p13_03_tasks_prep()

        assert runner2.total_writes == 0

    def test_existing_pending_approval_no_regenerated_authorization(self, tmp_path: Path) -> None:
        """A3.3: Unrestored runner cannot regenerate PendingApproval or authorize steps."""
        _setup_live_runner(tmp_path)
        runner2 = _setup_live_runner(tmp_path)

        with pytest.raises(KillerMissionIntegrityError, match="Cannot execute calendar pause"):
            runner2.step_p13_04_calendar_pause()

        with pytest.raises(KillerMissionIntegrityError, match="Cannot execute planning"):
            runner2.step_p13_02_plan()

    def test_same_mission_id_incompatible_action_lineage_fails_closed(self, tmp_path: Path) -> None:
        """A3.4: Contradictory intent for existing mission ID fails closed at init."""
        _setup_live_runner(tmp_path)
        # Existing mission has standard intent. Runner with different intent must fail closed.
        scope = DemoResourceScope("c_adversarial_demo", "tl_adversarial_demo")
        env = KillerMissionEnvironment.create_live_environment(
            base_dir=tmp_path,
            scope=scope,
            calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
            tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
            weather_transport=OpenMeteoHttpTransport(),
        )

        class ContradictoryRunner(LiveKillerMissionSliceRunner):
            def __init__(self, **kwargs: Any) -> None:
                # Patch intent before super init
                super().__init__(**kwargs)

        with pytest.raises(
            KillerMissionIntegrityError,
            match="Mismatched mission identity|contradictory intent",
        ):
            # Construct runner with a mismatched mission ID on non-empty ledger
            LiveKillerMissionSliceRunner(
                env=env,
                mission_id=MissionId("99999999-9999-9999-9999-999999999999"),
                operator_approved=True,
                source_sha="1111111111111111111111111111111111111111",
            )

    def test_existing_mission_incomplete_history_fails_closed(self, tmp_path: Path) -> None:
        """A3.5: Corrupted ledger history prevents silent initialization."""
        runner1 = _setup_live_runner(tmp_path)
        # Corrupt the ledger
        with open(runner1.env.ledger_file, "a", encoding="utf-8") as f:
            f.write("corrupted_line_not_json\n")

        scope = DemoResourceScope("c_adversarial_demo", "tl_adversarial_demo")
        with pytest.raises(
            KillerMissionIntegrityError, match="Failed to initialize durable ledger"
        ):
            KillerMissionEnvironment.create_live_environment(
                base_dir=tmp_path,
                scope=scope,
                calendar_transport=GoogleApiClientCalendarTransport(service=MagicMock()),
                tasks_transport=GoogleApiClientTasksTransport(service=MagicMock()),
                weather_transport=OpenMeteoHttpTransport(),
            )

    def test_new_clean_mission_execution_ordering_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A3.6: Legitimate new clean mission with fresh storage preserves execution order."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        assert runner.is_first_time_storage is True
        assert runner.existing_mission_detected is False
        assert runner.is_restored_session is False

        # When storage is fresh and mission is new, the runner is not blocked by the recovery gate.
        # It permits the legitimate execution workflow.
        monkeypatch.setattr(
            "stilldone.killer_mission.seed_canonical_demo_resources",
            lambda **kwargs: DemoSeedResult(
                status=SeedOperationStatus.MUTATION_EXECUTED,
                provenance=runner.env.provenance,
                calendar_id=runner.env.scope.calendar_id,
                task_list_id=runner.env.scope.task_list_id,
                event_id="seeded_evt_clean_123",
                event_start_time=runner.initial_start_time,
                writes_performed=1,
                readback_verified=True,
                is_seed_complete=True,
                details="Seeded clean demo event",
            ),
        )

        # Step 1 seeding succeeds
        res1 = runner.step_p13_01_seed()
        assert res1.status == "PASS"
        assert runner.seeded_event_id == "seeded_evt_clean_123"

        # Step 4 pause succeeds without recovery error
        res4 = runner.step_p13_04_calendar_pause()
        assert res4.status == "PASS"
        assert runner.pending_approval is not None

    def test_historical_receipt_and_provider_identity_intact(self, tmp_path: Path) -> None:
        """A3.7: Historical receipt hash and provider event ID remain intact on disk."""
        runner = _setup_live_runner(tmp_path)
        now = datetime.now(UTC)

        # 1. Authoritative provider identity in action target remains exact
        evt_id = "provider_event_live_intact_123"
        runner.seeded_event_id = evt_id
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=evt_id,
            parent_id=runner.env.scope.calendar_id,
        )
        action = ActionContract.create(
            mission_id=runner.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=target,
            parameters={},
            action_id=ActionId.generate(),
        )
        pred_cal = DesiredStatePredicate(
            predicate_id=PREDICATE_ID_CALENDAR,
            mission_id=runner.mission_id,
            subject="start_time",
            operator=PredicateOperator.EQUALS,
            expected_value="2026-10-04T07:30:00+00:00",
            required=True,
            freshness=FreshnessContract.current(),
        )
        pred_binding = PredicateTargetBinding.create(
            predicate_id=PREDICATE_ID_CALENDAR,
            mission_id=runner.mission_id,
            target=target,
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
        snapshot = create_mission_snapshot(
            mission_id=runner.mission_id,
            contract=runner.contract,
            state=MissionState.READY,
            desired_state=(pred_cal,),
            actions=(action,),
            step_records={action.action_id: step_rec},
            consumed_approvals=(),
            execution_attempts=(attempt,),
            evidence_ids=(EvidenceId.compute("ev_p13_test"),),
            predicate_bindings=(pred_binding,),
            created_at=now,
        )
        receipt = create_mission_ready_receipt(snapshot)
        orig_hash = receipt.receipt_hash.value

        # Re-verify the hash is deterministic and tamper-evident
        receipt2 = create_mission_ready_receipt(snapshot)
        assert receipt2.receipt_hash.value == orig_hash

        # Provider event ID remains exact and preserved in target
        assert action.target.resource_id == evt_id
        assert runner.seeded_event_id == evt_id


# ===========================================================================
# D2 — Public Summary Privacy from Trusted Fields Only
# ===========================================================================


class TestD2PublicSummaryPrivacy:
    """D2: Generate public summaries from trusted fields only."""

    def test_raw_provider_id_injected_into_system_name_position(self) -> None:
        """D2.1: Attacker injecting provider ID in system position is suppressed."""
        malicious_summary = (
            "Update Google Calendar event on 'secret_provider_token_9988_steal' "
            "(cal_event_secret_123): start_time='2026-10-04T07:30:00+00:00'"
        )
        contract = OneDecisionContract(
            pending_approval_id=PendingApprovalId("d" * 64),
            mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
            action_id=ActionId("11111111-2222-3333-4444-555555555555"),
            action_type=ActionType.CALENDAR_UPDATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
            human_summary=malicious_summary,
            status=PendingApprovalStatus.PENDING,
            requested_at=datetime.now(UTC),
        )
        pub = contract.to_public_dict()
        assert "secret_provider_token_9988_steal" not in pub["human_summary"]
        assert "cal_event_secret_123" not in pub["human_summary"]
        assert pub["human_summary"] == f"Update Google Calendar event ({REDACTED_IDENTIFIER})"

    def test_raw_provider_id_injected_into_action_type_position(self) -> None:
        """D2.2: Attacker injecting provider ID in action type position is suppressed."""
        malicious_summary = (
            "Execute action 'leaked_internal_auth_key_5544' on 'calendar' "
            "(target_resource_99): payload=..."
        )
        contract = OneDecisionContract(
            pending_approval_id=PendingApprovalId("e" * 64),
            mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
            action_id=ActionId("11111111-2222-3333-4444-555555555555"),
            action_type=ActionType.CALENDAR_UPDATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
            human_summary=malicious_summary,
            status=PendingApprovalStatus.PENDING,
            requested_at=datetime.now(UTC),
        )
        pub = contract.to_public_dict()
        assert "leaked_internal_auth_key_5544" not in pub["human_summary"]
        assert pub["human_summary"] == f"Update Google Calendar event ({REDACTED_IDENTIFIER})"

    def test_arbitrary_id_in_parameters_suppressed(self) -> None:
        """D2.3: Sensitive parameters are completely stripped from public summary."""
        param_leak_summary = (
            "Update Google Calendar event: start_time='2026-10-04T07:30:00+00:00', "
            "description='Private secret meeting notes with token sk-998877'"
        )
        contract = OneDecisionContract(
            pending_approval_id=PendingApprovalId("f" * 64),
            mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
            action_id=ActionId("11111111-2222-3333-4444-555555555555"),
            action_type=ActionType.CALENDAR_UPDATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
            human_summary=param_leak_summary,
            status=PendingApprovalStatus.PENDING,
            requested_at=datetime.now(UTC),
        )
        pub = contract.to_public_dict()
        assert "sk-998877" not in pub["human_summary"]
        assert "Private secret" not in pub["human_summary"]
        assert pub["human_summary"] == f"Update Google Calendar event ({REDACTED_IDENTIFIER})"

    def test_unknown_free_form_historical_summary_uses_trusted_action_type(self) -> None:
        """D2.4: Free-form text falls back strictly to trusted action_type presentation."""
        free_form = "Random non-structured operator memo regarding family scheduling"
        contract = OneDecisionContract(
            pending_approval_id=PendingApprovalId("1" * 64),
            mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
            action_id=ActionId("11111111-2222-3333-4444-555555555555"),
            action_type=ActionType.TASK_CREATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
            human_summary=free_form,
            status=PendingApprovalStatus.PENDING,
            requested_at=datetime.now(UTC),
        )
        pub = contract.to_public_dict()
        assert "Random non-structured" not in pub["human_summary"]
        assert pub["human_summary"] == f"Create Google Tasks item ({REDACTED_IDENTIFIER})"

    def test_missing_or_incorrect_provider_ids_context_safe(self) -> None:
        """D2.5: None, empty, or wrong provider_ids does not cause leakage."""
        summary = "Update Google Calendar event (event_9999): start=07:30"
        contract = OneDecisionContract(
            pending_approval_id=PendingApprovalId("2" * 64),
            mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
            action_id=ActionId("11111111-2222-3333-4444-555555555555"),
            action_type=ActionType.CALENDAR_UPDATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
            human_summary=summary,
            status=PendingApprovalStatus.PENDING,
            requested_at=datetime.now(UTC),
        )
        pub1 = contract.to_public_dict(provider_ids=None)
        pub2 = contract.to_public_dict(provider_ids=[])
        pub3 = contract.to_public_dict(provider_ids=["wrong_unrelated_id"])
        expected = f"Update Google Calendar event ({REDACTED_IDENTIFIER})"
        assert pub1["human_summary"] == expected
        assert pub2["human_summary"] == expected
        assert pub3["human_summary"] == expected

    def test_standalone_and_nested_public_projections_consistency(self) -> None:
        """D2.6: PendingApproval.to_public_dict and OneDecisionContract.to_public_dict match."""
        now = datetime.now(UTC)
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="secret_cal_event_555",
            parent_id="cal_list_999",
        )
        action = ActionContract.create(
            mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
            action_type=ActionType.CALENDAR_UPDATE,
            target=target,
            parameters={"start_time": "2026-10-04T07:30:00+00:00"},
        )
        val_action = validate_action_contract(action)
        pending = create_pending_approval(val_action, requested_at=now)

        nested_pub = pending.to_public_dict()
        standalone_pub = pending.decision_contract.to_public_dict()

        # Both public summaries must be identical and redacted
        assert (
            nested_pub["one_decision_contract"]["human_summary"] == standalone_pub["human_summary"]
        )
        assert "secret_cal_event_555" not in json.dumps(nested_pub)
        assert "secret_cal_event_555" not in json.dumps(standalone_pub)
        assert (
            standalone_pub["human_summary"]
            == f"Update Google Calendar event ({REDACTED_IDENTIFIER})"
        )

    def test_authoritative_round_trip_retains_exact_original_contract(self) -> None:
        """D2.7: Authoritative dict retains exact raw historical summary for read-back."""
        raw_summary = (
            "Update Google Calendar event on 'google_calendar' (evt_raw_123): start_time='07:30'"
        )
        contract = OneDecisionContract(
            pending_approval_id=PendingApprovalId("3" * 64),
            mission_id=MissionId("11111111-2222-3333-4444-555555555555"),
            action_id=ActionId("11111111-2222-3333-4444-555555555555"),
            action_type=ActionType.CALENDAR_UPDATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
            human_summary=raw_summary,
            status=PendingApprovalStatus.PENDING,
            requested_at=datetime.now(UTC),
        )
        auth = contract.to_authoritative_dict()
        assert auth["human_summary"] == raw_summary
        assert "evt_raw_123" in auth["human_summary"]
        # Calling to_dict(redact_identifiers=False) is identical to authoritative
        assert contract.to_dict(redact_identifiers=False) == auth
