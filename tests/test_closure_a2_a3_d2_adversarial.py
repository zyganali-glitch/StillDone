"""Adversarial Regression Test Suite for P-13 + P-16 Consolidated Root-Cause Closure.

Validates the full set of adversarial security and integrity requirements for:
- A2: Authority-Record State Model & Dual-Store Integrity
- A3: Unrestored Runner Execution Gating & Zero-Mutation Invariant
- D2: Public Summary Privacy from Trusted Fields Only
"""

from __future__ import annotations

import concurrent.futures
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
from stilldone.adapters.tasks import (
    GoogleApiClientTasksTransport,
    TaskCreateResult,
    TaskCreateStatus,
    TaskObservation,
    TaskReadResult,
    TaskReadStatus,
)
from stilldone.adapters.weather import OpenMeteoHttpTransport
from stilldone.approval_consumption import (
    ApprovalAlreadyUsedError,
    ApprovalLedger,
    ApprovalRevokedError,
    ApprovalUsageStatus,
    MalformedApprovalStateError,
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
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
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
    KillerMissionSequenceError,
    LiveKillerMissionSliceRunner,
    create_authorized_post_pending_decision,
)
from stilldone.ledger import ActionRecord, DurableFileLedger, EvidenceRecord
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
        monkeypatch.setattr(
            OpenMeteoHttpTransport,
            "fetch_current_weather",
            lambda *args, **kwargs: {
                "current": {
                    "time": f"{runner.demo_date}T07:00",
                    "temperature_2m": 18.5,
                    "precipitation": 0.0,
                    "weather_code": 0,
                    "wind_speed_10m": 5.0,
                },
                "current_units": {
                    "temperature_2m": "°C",
                    "precipitation": "mm",
                    "weather_code": "wmo code",
                    "wind_speed_10m": "km/h",
                },
            },
        )
    return runner


def _attach_pending_approval(runner: LiveKillerMissionSliceRunner) -> str:
    """Attach a valid PendingApproval and action to runner without running preflight steps."""
    now = datetime.now(UTC)
    pending = create_pending_approval(
        validate_action_contract(runner.action_cal),
        requested_at=now,
    )
    runner.pending_approval = pending
    act_id_str = str(runner.action_cal.action_id)
    ledger_actions = getattr(runner.env.mission_ledger, "_actions", {})
    if act_id_str not in ledger_actions:
        runner.env.mission_ledger.append_action(
            ActionRecord(
                action_id=runner.action_cal.action_id,
                mission_id=runner.mission_id,
                action=runner.action_cal,
                approval_id=None,
                created_at=now,
            )
        )
    return str(pending.pending_approval_id)


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

        # 4. Direct negative check: ApprovalLedger.consume fails closed (cannot become usable again)
        app_ledger = ApprovalLedger(registry=registry)
        with pytest.raises(ApprovalAlreadyUsedError, match="already consumed"):
            app_ledger.consume(grant, grant.action, at=now)

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

        # 4. Direct negative check: ApprovalLedger.consume fails closed
        app_ledger = ApprovalLedger(registry=registry)
        with pytest.raises(ApprovalRevokedError, match="revoked and cannot be consumed"):
            app_ledger.consume(grant, grant.action, at=now)

    def test_consumed_approval_cannot_become_usable_after_rejection_collision_including_hydration(
        self, tmp_path: Path
    ) -> None:
        """A2.7 direct negative test: Consumed approval cannot become usable after
        rejection collision or hydration.
        """
        runner = _setup_live_runner(tmp_path)
        aid = "11111111-1111-1111-1111-111111110077"
        grant = _dummy_grant(
            approval_id=aid,
            mission_id=str(runner.mission_id),
            action_id=str(runner.action_cal.action_id),
        )
        now = datetime.now(UTC)

        runner.env.mission_ledger.append_action(
            ActionRecord(
                action_id=grant.action_id,
                mission_id=grant.mission_id,
                action=grant.action,
                approval_id=None,
                created_at=now,
            )
        )

        app_ledger = runner.env.approval_ledger
        # 1. Consume approval
        res = app_ledger.consume(grant, grant.action, at=now)
        assert res.is_authorized is True
        assert app_ledger.is_consumed(aid) is True

        # 2. Rejection collision attempt fails closed
        with pytest.raises(ApprovalAlreadyUsedError, match="already consumed"):
            app_ledger.record_rejection(
                "dec_collision_hydr_01",
                action_id=grant.action_id,
                mission_id=grant.mission_id,
                at=now,
                pending_approval_id=aid,
            )

        # 3. Direct negative proof: cannot be consumed again
        with pytest.raises(ApprovalAlreadyUsedError, match="already consumed"):
            app_ledger.consume(grant, grant.action, at=now)

        # 4. Process restart & hydration from disk
        hydrated_ledger = ApprovalLedger.from_ledger(DurableFileLedger(runner.env.ledger_file))
        assert hydrated_ledger.is_consumed(aid) is True

        # 5. Direct negative proof across restart: still cannot be consumed
        with pytest.raises(ApprovalAlreadyUsedError, match="already consumed"):
            hydrated_ledger.consume(grant, grant.action, at=now)

        # 6. Negative proof of hydration integrity: if a corrupt ledger injects
        # rejection at consumed key
        from stilldone.approval_consumption import APPROVAL_REJECTION_EVIDENCE_TYPE

        corrupt_ev = EvidenceRecord.create(
            action_id=grant.action_id,
            mission_id=grant.mission_id,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
                observed_at=now,
            ),
            payload={
                "evidence_type": APPROVAL_REJECTION_EVIDENCE_TYPE,
                "decision_id": "dec_injected_evil",
                "mission_id": str(grant.mission_id),
                "action_id": str(grant.action_id),
                "decision": "REJECT",
                "status": "REJECTED",
                "consumed_at": now.isoformat(),
                "pending_approval_id": aid,
            },
            created_at=now,
        )
        runner.env.mission_ledger.append_evidence(corrupt_ev)

        # Hydrating the corrupted ledger must fail closed with MalformedApprovalStateError
        with pytest.raises(
            MalformedApprovalStateError, match="rejection evidence cannot overwrite"
        ):
            ApprovalLedger.from_ledger(DurableFileLedger(runner.env.ledger_file))

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

    def test_matching_decision_ids_with_contradictory_mission_action_decision_data(
        self, tmp_path: Path
    ) -> None:
        """A2.6: Matching decision IDs with contradictory mission/action/decision
        data fail closed.
        """
        runner = _setup_live_runner(tmp_path)
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
            "dec_matched_common",
            action_id=runner.action_cal.action_id,
            mission_id=runner.mission_id,
            at=now,
            pending_approval_id="pa_canonical_real",
        )

        # Case 1: Contradictory mission_id
        line_bad_mission = json.dumps(
            {
                "decision_id": "dec_matched_common",
                "consumed_at": now.isoformat(),
                "decision": "REJECT",
                "mission_id": "00000000-0000-0000-0000-000000000000",
            }
        )
        runner._consumed_decisions_file.write_text(f"{line_bad_mission}\n", encoding="utf-8")
        with pytest.raises(KillerMissionIntegrityError, match="Contradictory mission_id"):
            runner._load_consumed_decision_ids()

        # Case 2: Contradictory decision value (APPROVE vs REJECT)
        line_bad_decision = json.dumps(
            {
                "decision_id": "dec_matched_common",
                "consumed_at": now.isoformat(),
                "decision": "APPROVE",
                "mission_id": str(runner.mission_id),
            }
        )
        runner._consumed_decisions_file.write_text(f"{line_bad_decision}\n", encoding="utf-8")
        with pytest.raises(KillerMissionIntegrityError, match="Contradictory decision value"):
            runner._load_consumed_decision_ids()

        # Case 3: Contradictory action_id
        line_bad_action = json.dumps(
            {
                "decision_id": "dec_matched_common",
                "consumed_at": now.isoformat(),
                "decision": "REJECT",
                "mission_id": str(runner.mission_id),
                "action_id": "00000000-0000-0000-0000-000000000000",
            }
        )
        runner._consumed_decisions_file.write_text(f"{line_bad_action}\n", encoding="utf-8")
        with pytest.raises(KillerMissionIntegrityError, match="Contradictory action_id"):
            runner._load_consumed_decision_ids()

        # Case 4: Contradictory pending_approval_id
        line_bad_pa = json.dumps(
            {
                "decision_id": "dec_matched_common",
                "consumed_at": now.isoformat(),
                "decision": "REJECT",
                "mission_id": str(runner.mission_id),
                "action_id": str(runner.action_cal.action_id),
                "pending_approval_id": "pa_contradictory_fake",
            }
        )
        runner._consumed_decisions_file.write_text(f"{line_bad_pa}\n", encoding="utf-8")
        with pytest.raises(KillerMissionIntegrityError, match="Contradictory pending_approval_id"):
            runner._load_consumed_decision_ids()

    def test_ledger_append_failure_and_interrupted_persistence_rollback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A2.7: Interrupted persistence rolls back JSONL and latches failure fail-closed."""
        runner = _setup_live_runner(tmp_path)
        pa_id = _attach_pending_approval(runner)

        # Cause approval ledger append to fail
        def failing_record_rejection(*args: Any, **kwargs: Any) -> Any:
            raise OSError("Disk full on ledger storage")

        monkeypatch.setattr(
            runner.env.approval_ledger, "record_rejection", failing_record_rejection
        )

        with pytest.raises(KillerMissionIntegrityError, match="Failed to commit consumed approval"):
            runner._persist_consumed_decision_id(
                "fail_append_dec_1",
                pending_approval_id=pa_id,
                action_id=str(runner.action_cal.action_id),
            )

        # Rollback: decision must NOT be in JSONL or memory
        assert runner._persistence_failed is True
        assert "fail_append_dec_1" not in runner._consumed_approval_decision_ids
        if runner._consumed_decisions_file.exists():
            content = runner._consumed_decisions_file.read_text(encoding="utf-8")
            assert "fail_append_dec_1" not in content

        # Subsequent attempts fail closed immediately
        with pytest.raises(KillerMissionIntegrityError, match="Persistence failure previously"):
            runner._persist_consumed_decision_id(
                "any_subsequent_dec",
                pending_approval_id=pa_id,
                action_id=str(runner.action_cal.action_id),
            )

    def test_repeated_consumption_after_restart_rejected(self, tmp_path: Path) -> None:
        """A2.8: Persisted decision is durably rejected upon process restart."""
        runner1 = _setup_live_runner(tmp_path)
        pa_id = _attach_pending_approval(runner1)
        runner1._persist_consumed_decision_id(
            "restart_replay_dec_1",
            pending_approval_id=pa_id,
            action_id=str(runner1.action_cal.action_id),
        )
        assert "restart_replay_dec_1" in runner1._consumed_approval_decision_ids

        # Construct runner 2 on same storage (process restart)
        runner2 = _setup_live_runner(tmp_path)
        runner2.pending_approval = runner1.pending_approval
        assert "restart_replay_dec_1" in runner2._consumed_approval_decision_ids

        # Attempt to consume again raises KillerMissionAuthorityError
        with pytest.raises(KillerMissionAuthorityError, match="already been consumed"):
            runner2._persist_consumed_decision_id(
                "restart_replay_dec_1",
                pending_approval_id=pa_id,
                action_id=str(runner2.action_cal.action_id),
            )

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

    def test_rejection_persists_exact_pending_approval_binding(self, tmp_path: Path) -> None:
        """A2.1: Rejection persists exact PendingApproval binding to ledger and JSONL."""
        runner = _setup_live_runner(tmp_path)
        pa_id = _attach_pending_approval(runner)
        runner._persist_consumed_decision_id(
            "dec_rejection_binding_1",
            pending_approval_id=pa_id,
            action_id=str(runner.action_cal.action_id),
        )

        # 1. Verify canonical ApprovalLedger recorded rejection with exact pending_approval_id
        ledger_rec = runner.env.approval_ledger.get_record(pa_id)
        assert ledger_rec is not None
        assert ledger_rec.status == ApprovalUsageStatus.REJECTED
        assert ledger_rec.approval_id == pa_id
        assert ledger_rec.decision_id == "dec_rejection_binding_1"
        assert runner.env.approval_ledger.is_rejected(pa_id) is True

        # 2. Verify JSONL contains both action_id and pending_approval_id
        assert runner._consumed_decisions_file.exists()
        line = json.loads(runner._consumed_decisions_file.read_text(encoding="utf-8").strip())
        assert line["decision_id"] == "dec_rejection_binding_1"
        assert line["pending_approval_id"] == pa_id
        assert line["action_id"] == str(runner.action_cal.action_id)
        assert line["decision"] == "REJECT"

    def test_two_distinct_decision_ids_cannot_independently_reject_same_pending_approval(
        self, tmp_path: Path
    ) -> None:
        """A2.2: Two distinct decision IDs cannot independently reject the same PendingApproval."""
        runner = _setup_live_runner(tmp_path)
        pa_id = _attach_pending_approval(runner)

        # First rejection succeeds
        runner._persist_consumed_decision_id(
            "dec_rej_alpha",
            pending_approval_id=pa_id,
            action_id=str(runner.action_cal.action_id),
        )
        assert "dec_rej_alpha" in runner._consumed_approval_decision_ids
        assert runner.env.approval_ledger.is_rejected(pa_id) is True

        # Second decision attempting to reject the same pending approval must fail closed
        with pytest.raises(
            (KillerMissionAuthorityError, ApprovalAlreadyUsedError),
            match="already rejected",
        ):
            runner._persist_consumed_decision_id(
                "dec_rej_beta",
                pending_approval_id=pa_id,
                action_id=str(runner.action_cal.action_id),
            )

        # Second decision was NOT added to in-memory set, JSONL, or ledger
        assert "dec_rej_beta" not in runner._consumed_approval_decision_ids
        assert runner.env.approval_ledger.is_decision_consumed("dec_rej_beta") is False

    def test_synthetic_approve_passed_to_rejection_persistence_prohibited(
        self, tmp_path: Path
    ) -> None:
        """A2.3: Synthetic APPROVE passed to rejection persistence is prohibited."""
        runner = _setup_live_runner(tmp_path)
        pa_id = _attach_pending_approval(runner)

        with pytest.raises(
            KillerMissionAuthorityError, match="Prohibited decision value 'APPROVE'"
        ):
            runner._persist_consumed_decision_id(
                "synth_approve_dec_1",
                decision=ApprovalDecision.APPROVE,
                pending_approval_id=pa_id,
                action_id=str(runner.action_cal.action_id),
            )

        with pytest.raises(
            KillerMissionAuthorityError, match="Prohibited decision value 'APPROVE'"
        ):
            runner._persist_consumed_decision_id(
                "synth_approve_dec_2",
                decision="APPROVE",
                pending_approval_id=pa_id,
                action_id=str(runner.action_cal.action_id),
            )

        # Must not be recorded
        assert "synth_approve_dec_1" not in runner._consumed_approval_decision_ids
        assert "synth_approve_dec_2" not in runner._consumed_approval_decision_ids

    def test_canonical_only_history_followed_by_new_decision_reloads_safely(
        self, tmp_path: Path
    ) -> None:
        """A2.4: Canonical-only history A followed by new decision B reloads safely
        without false discrepancy.
        """
        runner = _setup_live_runner(tmp_path)
        now = datetime.now(UTC)

        # 1. Add canonical-only decision A directly to ledger (no JSONL)
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
            "canonical_dec_a",
            action_id=runner.action_cal.action_id,
            mission_id=runner.mission_id,
            at=now,
            pending_approval_id="pa_historical_a",
        )
        assert runner._consumed_decisions_file.exists() is False

        # 2. Add new decision B via live helper (persists to JSONL and ledger)
        runner._consumed_approval_decision_ids.clear()
        runner._load_consumed_decision_ids()
        assert "canonical_dec_a" in runner._consumed_approval_decision_ids

        pa_id = _attach_pending_approval(runner)
        runner._persist_consumed_decision_id(
            "new_dec_b",
            action_id=str(runner.action_cal.action_id),
            pending_approval_id=pa_id,
        )
        assert "new_dec_b" in runner._consumed_approval_decision_ids

        # 3. Simulate process restart / reload
        runner._consumed_approval_decision_ids.clear()
        runner._load_consumed_decision_ids()

        # Both canonical decision A and new decision B must be loaded cleanly without
        # false discrepancy
        assert "canonical_dec_a" in runner._consumed_approval_decision_ids
        assert "new_dec_b" in runner._consumed_approval_decision_ids

    def test_concurrent_duplicate_decisions_cannot_both_succeed(self, tmp_path: Path) -> None:
        """A2.8: Concurrent duplicate decisions cannot both succeed."""
        runner = _setup_live_runner(tmp_path)
        pa_id = _attach_pending_approval(runner)
        success_count = 0
        authority_error_count = 0

        def _persist_same() -> None:
            nonlocal success_count, authority_error_count
            try:
                runner._persist_consumed_decision_id(
                    "concurrent_dup_decision_id",
                    pending_approval_id=pa_id,
                    action_id=str(runner.action_cal.action_id),
                )
                success_count += 1
            except KillerMissionAuthorityError:
                authority_error_count += 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(_persist_same)
            f2 = executor.submit(_persist_same)
            f1.result()
            f2.result()

        assert success_count == 1
        assert authority_error_count == 1
        assert "concurrent_dup_decision_id" in runner._consumed_approval_decision_ids

    def test_direct_persistence_helper_before_p13_04_cannot_create_bound_rejection(
        self, tmp_path: Path
    ) -> None:
        """A2: Direct persistence helper before P-13.04 cannot create a bound rejection."""
        runner = _setup_live_runner(tmp_path)
        assert getattr(runner, "pending_approval", None) is None
        with pytest.raises(
            KillerMissionSequenceError,
            match="Cannot persist consumed rejection before P-13.04 establishes PendingApproval",
        ):
            runner._persist_consumed_decision_id(
                "early_dec_1",
                pending_approval_id="pa_fake_early",
                action_id=str(runner.action_cal.action_id),
            )

    def test_missing_forged_or_mismatched_pending_approval_no_canonical_evidence(
        self, tmp_path: Path
    ) -> None:
        """A2: Missing, empty, or mismatched pending_approval_id fails closed."""
        runner = _setup_live_runner(tmp_path)
        pa_id = _attach_pending_approval(runner)

        # Missing pending_approval_id
        with pytest.raises(
            KillerMissionAuthorityError,
            match="Cannot persist consumed rejection without exact pending_approval_id binding",
        ):
            runner._persist_consumed_decision_id(
                "dec_missing_pa",
                pending_approval_id=None,
                action_id=str(runner.action_cal.action_id),
            )

        # Empty pending_approval_id
        with pytest.raises(
            KillerMissionAuthorityError,
            match="Cannot persist consumed rejection without exact pending_approval_id binding",
        ):
            runner._persist_consumed_decision_id(
                "dec_empty_pa",
                pending_approval_id="   ",
                action_id=str(runner.action_cal.action_id),
            )

        # Mismatched pending_approval_id
        with pytest.raises(
            KillerMissionAuthorityError,
            match="Mismatched pending_approval_id",
        ):
            runner._persist_consumed_decision_id(
                "dec_mismatched_pa",
                pending_approval_id="pa_forged_different_123",
                action_id=str(runner.action_cal.action_id),
            )
        assert runner.env.approval_ledger.is_rejected("pa_forged_different_123") is False
        assert runner.env.approval_ledger.is_rejected(pa_id) is False

    def test_raw_reject_parameter_zero_writes_and_no_durable_terminal_claim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A2: Raw REJECT parameter safely halts mutation with 0 writes and no durable claim."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _attach_pending_approval(runner)
        pa_id = str(runner.pending_approval.pending_approval_id)

        res = runner.step_p13_05_calendar_approve(decision=ApprovalDecision.REJECT)
        assert res.status == "BLOCKED_APPROVAL_CHANNEL"
        assert res.writes_performed == 0
        assert res.is_verified is False
        assert res.extra_metadata["raw_negative_instruction"] is True
        assert res.extra_metadata["durable_terminal_rejection"] is False
        assert runner.env.approval_ledger.is_rejected(pa_id) is False
        assert runner.total_writes == 0

    def test_callback_raw_reject_zero_writes_and_no_durable_terminal_claim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A2: Callback returning raw REJECT halts mutation with 0 writes and no durable claim."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _attach_pending_approval(runner)
        pa_id = str(runner.pending_approval.pending_approval_id)
        runner.post_pending_decision_callback = lambda pa: ApprovalDecision.REJECT

        res = runner.step_p13_05_calendar_approve(decision=None)
        assert res.status == "BLOCKED_APPROVAL_CHANNEL"
        assert res.writes_performed == 0
        assert res.is_verified is False
        assert res.extra_metadata["raw_negative_instruction"] is True
        assert res.extra_metadata["durable_terminal_rejection"] is False
        assert runner.env.approval_ledger.is_rejected(pa_id) is False
        assert runner.total_writes == 0

    def test_typed_reject_self_constructed_zero_durable_human_decision_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2: Self-constructed typed REJECT with matching IDs cannot create durable
        human-decision records (zero records in ApprovalLedger, zero writes).
        """
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _attach_pending_approval(runner)
        pa_id = str(runner.pending_approval.pending_approval_id)

        typed_reject = create_authorized_post_pending_decision(
            runner.pending_approval,
            target_event_id=runner.seeded_event_id,
            action_parameters=runner.action_cal.parameters.to_dict(),
            decision=ApprovalDecision.REJECT,
        )

        res = runner.step_p13_05_calendar_approve(decision=typed_reject)
        assert res.status == "BLOCKED_APPROVAL_CHANNEL"
        assert res.writes_performed == 0
        assert res.is_verified is False
        assert runner.env.approval_ledger.is_rejected(pa_id) is False
        assert runner.env.approval_ledger.is_decision_consumed(typed_reject.decision_id) is False
        assert typed_reject.decision_id not in runner._consumed_approval_decision_ids
        assert runner.total_writes == 0

    def test_typed_reject_with_forged_authority_source_zero_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2: Typed REJECT with forged authority_source creates zero records."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _attach_pending_approval(runner)
        pa_id = str(runner.pending_approval.pending_approval_id)

        forged_reject = create_authorized_post_pending_decision(
            runner.pending_approval,
            target_event_id=runner.seeded_event_id,
            action_parameters=runner.action_cal.parameters.to_dict(),
            decision=ApprovalDecision.REJECT,
            authority_source="FORGED_ROOT_OPERATOR_TOKEN",
        )

        res = runner.step_p13_05_calendar_approve(decision=forged_reject)
        assert res.status == "BLOCKED_APPROVAL_CHANNEL"
        assert res.writes_performed == 0
        assert runner.env.approval_ledger.is_rejected(pa_id) is False
        assert runner.env.approval_ledger.is_decision_consumed(forged_reject.decision_id) is False
        assert forged_reject.decision_id not in runner._consumed_approval_decision_ids
        assert runner.total_writes == 0

    def test_unauthenticated_callback_returning_typed_reject_zero_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2: Unauthenticated callback returning typed REJECT creates zero records."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _attach_pending_approval(runner)
        pa_id = str(runner.pending_approval.pending_approval_id)

        typed_reject = create_authorized_post_pending_decision(
            runner.pending_approval,
            target_event_id=runner.seeded_event_id,
            action_parameters=runner.action_cal.parameters.to_dict(),
            decision=ApprovalDecision.REJECT,
        )
        runner.post_pending_decision_callback = lambda pa: typed_reject

        res = runner.step_p13_05_calendar_approve(decision=None)
        assert res.status == "BLOCKED_APPROVAL_CHANNEL"
        assert res.writes_performed == 0
        assert runner.env.approval_ledger.is_rejected(pa_id) is False
        assert runner.env.approval_ledger.is_decision_consumed(typed_reject.decision_id) is False
        assert typed_reject.decision_id not in runner._consumed_approval_decision_ids
        assert runner.total_writes == 0

    def test_fake_verifier_returning_true_cannot_establish_production_consent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2: Fake verifier returning True cannot establish production consent."""
        from unittest.mock import MagicMock

        from stilldone.killer_mission import AuthenticatedHumanApprovalChannel

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _attach_pending_approval(runner)
        pa_id = str(runner.pending_approval.pending_approval_id)

        fake_channel = MagicMock(spec=AuthenticatedHumanApprovalChannel)
        fake_channel.verify_decision.return_value = True
        runner.approval_channel = fake_channel

        typed_reject = create_authorized_post_pending_decision(
            runner.pending_approval,
            target_event_id=runner.seeded_event_id,
            action_parameters=runner.action_cal.parameters.to_dict(),
            decision=ApprovalDecision.REJECT,
        )

        res = runner.step_p13_05_calendar_approve(decision=typed_reject)
        assert res.status == "BLOCKED_APPROVAL_CHANNEL"
        assert res.writes_performed == 0
        assert runner.env.approval_ledger.is_rejected(pa_id) is False
        assert runner.env.approval_ledger.is_decision_consumed(typed_reject.decision_id) is False
        assert typed_reject.decision_id not in runner._consumed_approval_decision_ids
        assert runner.total_writes == 0

    def test_missing_verifier_blocked_with_zero_writes_and_zero_consumed_approvals(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2: Missing verifier blocks with zero writes and zero consumed approvals."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _attach_pending_approval(runner)
        pa_id = str(runner.pending_approval.pending_approval_id)
        runner.approval_channel = None

        typed_reject = create_authorized_post_pending_decision(
            runner.pending_approval,
            target_event_id=runner.seeded_event_id,
            action_parameters=runner.action_cal.parameters.to_dict(),
            decision=ApprovalDecision.REJECT,
        )

        res = runner.step_p13_05_calendar_approve(decision=typed_reject)
        assert res.status == "BLOCKED_APPROVAL_CHANNEL"
        assert res.writes_performed == 0
        assert runner.env.approval_ledger.is_rejected(pa_id) is False
        assert typed_reject.decision_id not in runner._consumed_approval_decision_ids

    def test_invalid_binding_typed_reject_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2: Invalid mission/action/target/parameter binding is blocked fail-closed."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _attach_pending_approval(runner)

        # Mismatched target_event_id
        mismatched_target = create_authorized_post_pending_decision(
            runner.pending_approval,
            target_event_id="forged_event_id_mismatch",
            action_parameters=runner.action_cal.parameters.to_dict(),
            decision=ApprovalDecision.REJECT,
        )
        with pytest.raises(KillerMissionAuthorityError, match="target_event_id mismatch"):
            runner.step_p13_05_calendar_approve(decision=mismatched_target)

        # Mismatched parameters
        mismatched_params = create_authorized_post_pending_decision(
            runner.pending_approval,
            target_event_id=runner.seeded_event_id,
            action_parameters={"start_time": "2026-10-04T09:00:00+00:00"},
            decision=ApprovalDecision.REJECT,
        )
        with pytest.raises(
            KillerMissionAuthorityError,
            match="action_parameter_fingerprint mismatch",
        ):
            runner.step_p13_05_calendar_approve(decision=mismatched_params)

    def test_replay_of_previously_durable_decision_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2: Replay of previously consumed decision ID is blocked fail-closed."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _attach_pending_approval(runner)

        typed_reject = create_authorized_post_pending_decision(
            runner.pending_approval,
            target_event_id=runner.seeded_event_id,
            action_parameters=runner.action_cal.parameters.to_dict(),
            decision=ApprovalDecision.REJECT,
        )
        # Mark decision as already consumed
        runner._consumed_approval_decision_ids.add(typed_reject.decision_id)

        with pytest.raises(KillerMissionAuthorityError, match="already been consumed"):
            runner.step_p13_05_calendar_approve(decision=typed_reject)

    def test_legacy_valid_history_interpreted_cleanly_and_corrupt_history_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """A2.10: Legacy valid history with minimal fields loads cleanly;
        corrupt file fails closed.
        """
        runner = _setup_live_runner(tmp_path)
        now = datetime.now(UTC)

        # 1. Canonical ledger has decision
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
            "legacy_dec_1",
            action_id=runner.action_cal.action_id,
            mission_id=runner.mission_id,
            at=now,
        )

        # Legacy JSONL without action_id or pending_approval_id
        legacy_line = json.dumps(
            {
                "decision_id": "legacy_dec_1",
                "consumed_at": now.isoformat(),
                "decision": "REJECT",
                "mission_id": str(runner.mission_id),
            }
        )
        runner._consumed_decisions_file.write_text(f"{legacy_line}\n", encoding="utf-8")

        runner._consumed_approval_decision_ids.clear()
        runner._load_consumed_decision_ids()
        assert "legacy_dec_1" in runner._consumed_approval_decision_ids

        # 2. Corrupt history (non-UTC offset) fails closed with trustworthy reason
        corrupt_line = json.dumps(
            {
                "decision_id": "corrupt_dec_2",
                "consumed_at": "2026-10-04T12:00:00+05:00",
            }
        )
        runner._consumed_decisions_file.write_text(f"{corrupt_line}\n", encoding="utf-8")
        runner._consumed_approval_decision_ids.clear()
        with pytest.raises(KillerMissionIntegrityError, match="consumed_at timestamp must be UTC"):
            runner._load_consumed_decision_ids()


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

        monkeypatch.setattr(
            runner.tasks_create_adapter,
            "create_task",
            lambda act, **kw: TaskCreateResult(
                status=TaskCreateStatus.CREATED,
                task_id="t_clean_123",
                task_list_id=runner.env.scope.task_list_id,
                title="Pack backpacks",
                due="2026-10-04",
                writes_performed=1,
            ),
        )
        monkeypatch.setattr(
            runner.tasks_read_adapter,
            "read_task",
            lambda act: TaskReadResult(
                status=TaskReadStatus.MATCH,
                observation=TaskObservation(
                    task_id=act.target.resource_id,
                    task_list_id=runner.env.scope.task_list_id,
                    title="Pack backpacks",
                    due="2026-10-04",
                    status="needsAction",
                    deleted=False,
                    hidden=False,
                    etag="etag_clean_123",
                    observed_at=datetime.now(UTC),
                ),
            ),
        )

        # Step 1 seeding succeeds
        res1 = runner.step_p13_01_seed()
        assert res1.status == "PASS"
        assert runner.seeded_event_id == "seeded_evt_clean_123"

        # Step 2 planning succeeds
        res2 = runner.step_p13_02_plan()
        assert res2.status == "PASS"

        # Step 3 tasks prep succeeds
        res3 = runner.step_p13_03_tasks_prep()
        assert res3.status == "PASS"

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

    def test_unrestored_runner_blocks_step_p13_06_and_07(self, tmp_path: Path) -> None:
        """A3: Unrestored runner blocks direct entry to step_p13_06_ready_receipt
        and step_p13_07_mutate_and_drift.
        """
        _setup_live_runner(tmp_path)
        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_execution_state_restored is False

        with pytest.raises(KillerMissionIntegrityError, match="Cannot produce ready receipt"):
            runner2.step_p13_06_ready_receipt()

        with pytest.raises(KillerMissionIntegrityError, match="Cannot execute drift"):
            runner2.step_p13_07_mutate_and_drift()

    def test_unrestored_runner_raw_reject_cannot_change_durable_approval_record(
        self, tmp_path: Path
    ) -> None:
        """A3 adversarial 1: On detected-but-unrestored runner, raw REJECT cannot
        change durable approval records.
        """
        _setup_live_runner(tmp_path)
        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_execution_state_restored is False

        initial_records = len(runner2.env.approval_ledger.get_decision_records())
        assert runner2.total_writes == 0

        with pytest.raises(
            KillerMissionIntegrityError,
            match="Cannot execute calendar mutation approval for existing mission",
        ):
            runner2.step_p13_05_calendar_approve(decision=ApprovalDecision.REJECT)

        # Verify no durable records changed
        assert len(runner2.env.approval_ledger.get_decision_records()) == initial_records
        assert runner2.total_writes == 0
        if runner2._consumed_decisions_file.exists():
            content = runner2._consumed_decisions_file.read_text(encoding="utf-8").strip()
            assert content == ""

    def test_unrestored_runner_callback_reject_cannot_change_durable_approval_record(
        self, tmp_path: Path
    ) -> None:
        """A3 adversarial 2: On detected-but-unrestored runner, callback REJECT is
        blocked before invocation.
        """
        _setup_live_runner(tmp_path)
        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_execution_state_restored is False

        callback_invoked = False

        def cb(pa: Any) -> Any:
            nonlocal callback_invoked
            callback_invoked = True
            return ApprovalDecision.REJECT

        runner2.post_pending_decision_callback = cb
        initial_records = len(runner2.env.approval_ledger.get_decision_records())

        with pytest.raises(
            KillerMissionIntegrityError,
            match="Cannot execute calendar mutation approval for existing mission",
        ):
            runner2.step_p13_05_calendar_approve(decision=None)

        # Gate triggered before callback invocation
        assert callback_invoked is False
        assert len(runner2.env.approval_ledger.get_decision_records()) == initial_records
        assert runner2.total_writes == 0

    def test_unrestored_runner_bound_typed_reject_cannot_change_durable_approval_record(
        self, tmp_path: Path
    ) -> None:
        """A3 adversarial 3: On detected-but-unrestored runner, bound typed REJECT
        cannot change durable records.
        """
        _setup_live_runner(tmp_path)
        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_execution_state_restored is False

        pending = create_pending_approval(
            validate_action_contract(runner2.action_cal),
            requested_at=datetime.now(UTC),
        )
        typed_reject = create_authorized_post_pending_decision(
            pending,
            target_event_id="seeded_evt_123",
            action_parameters={"start_time": "2026-10-04T07:30:00+00:00"},
            decision=ApprovalDecision.REJECT,
        )

        initial_records = len(runner2.env.approval_ledger.get_decision_records())

        with pytest.raises(
            KillerMissionIntegrityError,
            match="Cannot execute calendar mutation approval for existing mission",
        ):
            runner2.step_p13_05_calendar_approve(decision=typed_reject)

        assert runner2.env.approval_ledger.is_decision_consumed(typed_reject.decision_id) is False
        assert len(runner2.env.approval_ledger.get_decision_records()) == initial_records
        assert runner2.total_writes == 0

    def test_unrestored_runner_approve_cannot_authorize_mutation(self, tmp_path: Path) -> None:
        """A3 adversarial 4: On detected-but-unrestored runner, raw or typed APPROVE
        cannot authorize mutation.
        """
        _setup_live_runner(tmp_path)
        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_execution_state_restored is False

        pending = create_pending_approval(
            validate_action_contract(runner2.action_cal),
            requested_at=datetime.now(UTC),
        )
        typed_approve = create_authorized_post_pending_decision(
            pending,
            target_event_id="seeded_evt_123",
            action_parameters={"start_time": "2026-10-04T07:30:00+00:00"},
            decision=ApprovalDecision.APPROVE,
        )

        # Raw APPROVE fails closed under recovery gate
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Cannot execute calendar mutation approval for existing mission",
        ):
            runner2.step_p13_05_calendar_approve(decision=ApprovalDecision.APPROVE)

        # Typed APPROVE fails closed under recovery gate
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Cannot execute calendar mutation approval for existing mission",
        ):
            runner2.step_p13_05_calendar_approve(decision=typed_approve)

        assert runner2.total_writes == 0

    def test_unrestored_runner_none_decision_cannot_bypass_recovery_gate(
        self, tmp_path: Path
    ) -> None:
        """A3 adversarial 5: On detected-but-unrestored runner, None decision
        cannot bypass recovery gate.
        """
        _setup_live_runner(tmp_path)
        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_execution_state_restored is False

        with pytest.raises(
            KillerMissionIntegrityError,
            match="Cannot execute calendar mutation approval for existing mission",
        ):
            runner2.step_p13_05_calendar_approve(decision=None)

        assert runner2.total_writes == 0

    def test_unrestored_runner_direct_consumption_helper_cannot_create_authoritative_state(
        self, tmp_path: Path
    ) -> None:
        """A3 adversarial 6: On detected-but-unrestored runner, direct helper
        cannot create state.
        """
        _setup_live_runner(tmp_path)
        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_execution_state_restored is False

        initial_records = len(runner2.env.approval_ledger.get_decision_records())

        with pytest.raises(
            KillerMissionIntegrityError,
            match="Cannot persist consumed decision for existing mission",
        ):
            runner2._persist_consumed_decision_id(
                "unrestored_helper_attempt",
                action_id=str(runner2.action_cal.action_id),
            )

        assert len(runner2.env.approval_ledger.get_decision_records()) == initial_records
        assert "unrestored_helper_attempt" not in runner2._consumed_approval_decision_ids
        assert runner2.total_writes == 0

    def test_unrestored_runner_zero_provider_writes_across_all_paths(self, tmp_path: Path) -> None:
        """A3 adversarial 7: Detected-but-unrestored runner guarantees zero provider
        writes across all step paths.
        """
        _setup_live_runner(tmp_path)
        runner2 = _setup_live_runner(tmp_path)
        assert runner2.existing_mission_detected is True
        assert runner2.is_execution_state_restored is False

        with pytest.raises(KillerMissionIntegrityError):
            runner2.step_p13_01_seed()
        with pytest.raises(KillerMissionIntegrityError):
            runner2.step_p13_02_plan()
        with pytest.raises(KillerMissionIntegrityError):
            runner2.step_p13_03_tasks_prep()
        with pytest.raises(KillerMissionIntegrityError):
            runner2.step_p13_04_calendar_pause()
        with pytest.raises(KillerMissionIntegrityError):
            runner2.step_p13_05_calendar_approve(decision=ApprovalDecision.REJECT)
        with pytest.raises(KillerMissionIntegrityError):
            runner2.step_p13_05_calendar_approve(decision=ApprovalDecision.APPROVE)
        with pytest.raises(KillerMissionIntegrityError):
            runner2.step_p13_05_calendar_approve(decision=None)
        with pytest.raises(KillerMissionIntegrityError):
            runner2.step_p13_06_ready_receipt()
        with pytest.raises(KillerMissionIntegrityError):
            runner2.step_p13_07_mutate_and_drift()
        with pytest.raises(KillerMissionIntegrityError):
            runner2.run_full_slice()

        assert runner2.total_writes == 0

    def test_first_time_runner_execution_ordering_and_negative_approval_boundaries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A3 adversarial 8: First-time runner retains legitimate P-13 ordering
        and negative approval boundaries.
        """
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        assert runner.is_first_time_storage is True
        assert runner.existing_mission_detected is False

        # 1. Sequence error: calling step 5 before step 4 establishes pending approval
        with pytest.raises(
            KillerMissionSequenceError, match="Cannot approve calendar update before P-13.04"
        ):
            runner.step_p13_05_calendar_approve()

        # Mock seed for Step 1
        monkeypatch.setattr(
            "stilldone.killer_mission.seed_canonical_demo_resources",
            lambda **kwargs: DemoSeedResult(
                status=SeedOperationStatus.MUTATION_EXECUTED,
                provenance=runner.env.provenance,
                calendar_id=runner.env.scope.calendar_id,
                task_list_id=runner.env.scope.task_list_id,
                event_id="seeded_clean_evt_456",
                event_start_time=runner.initial_start_time,
                writes_performed=1,
                readback_verified=True,
                is_seed_complete=True,
                details="Clean seed",
            ),
        )
        monkeypatch.setattr(
            runner.tasks_create_adapter,
            "create_task",
            lambda act, **kw: TaskCreateResult(
                status=TaskCreateStatus.CREATED,
                task_id="t_clean_456",
                task_list_id=runner.env.scope.task_list_id,
                title="Pack backpacks",
                due="2026-10-04",
                writes_performed=1,
            ),
        )
        monkeypatch.setattr(
            runner.tasks_read_adapter,
            "read_task",
            lambda act: TaskReadResult(
                status=TaskReadStatus.MATCH,
                observation=TaskObservation(
                    task_id=act.target.resource_id,
                    task_list_id=runner.env.scope.task_list_id,
                    title="Pack backpacks",
                    due="2026-10-04",
                    status="needsAction",
                    deleted=False,
                    hidden=False,
                    etag="etag_clean_456",
                    observed_at=datetime.now(UTC),
                ),
            ),
        )

        res1 = runner.step_p13_01_seed()
        assert res1.status == "PASS"

        res2 = runner.step_p13_02_plan()
        assert res2.status == "PASS"

        res3 = runner.step_p13_03_tasks_prep()
        assert res3.status == "PASS"

        # Step 4 pause establishes pending approval
        res4 = runner.step_p13_04_calendar_pause()
        assert res4.status == "PASS"
        assert runner.pending_approval is not None
        pa_id = str(runner.pending_approval.pending_approval_id)

        # 2. Negative approval boundary: raw APPROVE parameter is rejected
        with pytest.raises(
            KillerMissionAuthorityError, match="Direct live approval bypass prohibited: raw APPROVE"
        ):
            runner.step_p13_05_calendar_approve(decision=ApprovalDecision.APPROVE)

        # 3. Negative approval boundary: unauthenticated callback returning raw APPROVE
        runner.post_pending_decision_callback = lambda pa: ApprovalDecision.APPROVE
        res_cb = runner.step_p13_05_calendar_approve(decision=None)
        assert res_cb.status == "BLOCKED_APPROVAL_CHANNEL"
        assert res_cb.writes_performed == 0
        assert res_cb.is_verified is False

        # 4. Typed REJECT without genuine authenticated channel halts safely
        # as BLOCKED_APPROVAL_CHANNEL with zero durable records and zero writes
        runner.post_pending_decision_callback = None
        auth_dec_rej = create_authorized_post_pending_decision(
            runner.pending_approval,
            target_event_id=runner.seeded_event_id,
            action_parameters=runner.action_cal.parameters.to_dict(),
            decision=ApprovalDecision.REJECT,
        )
        res_rej = runner.step_p13_05_calendar_approve(decision=auth_dec_rej)
        assert res_rej.status == "BLOCKED_APPROVAL_CHANNEL"
        assert res_rej.writes_performed == 0
        assert runner.env.approval_ledger.is_rejected(pa_id) is False
        assert runner.env.approval_ledger.is_decision_consumed(auth_dec_rej.decision_id) is False
        assert auth_dec_rej.decision_id not in runner._consumed_approval_decision_ids

        # 5. Replay attempt of consumed decision fails closed
        runner._consumed_approval_decision_ids.add(auth_dec_rej.decision_id)
        with pytest.raises(KillerMissionAuthorityError, match="already been consumed"):
            runner.step_p13_05_calendar_approve(decision=auth_dec_rej)

    def test_base_class_invocation_shared_mutation_boundary_bypass_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A3: Explicit invocation of base-class methods cannot bypass live recovery guards.

        Using a real LiveKillerMissionSliceRunner instance, invoke base-class methods:
        - KillerMissionSliceRunner.step_p13_01_seed(live_runner)
        - KillerMissionSliceRunner.step_p13_03_tasks_prep(live_runner)
        - KillerMissionSliceRunner.step_p13_04_calendar_pause(live_runner)
        Prove:
        - Existing-but-unrestored mission: zero seeding writes.
        - Existing-but-unrestored mission: zero Tasks writes.
        - Existing-but-unrestored mission: zero new PendingApproval.
        """
        from stilldone.killer_mission import KillerMissionSliceRunner

        _ = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        runner2 = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        assert runner2.existing_mission_detected is True
        assert runner2.is_execution_state_restored is False

        # 1. Base seeding on unrestored runner: zero seeding writes
        with pytest.raises(
            KillerMissionIntegrityError, match="Cannot execute seeding for existing mission"
        ):
            KillerMissionSliceRunner.step_p13_01_seed(runner2)
        assert runner2.total_writes == 0

        # 2. Base tasks prep on unrestored runner: zero Tasks writes
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Cannot execute tasks preparation for existing mission",
        ):
            KillerMissionSliceRunner.step_p13_03_tasks_prep(runner2)
        assert runner2.total_writes == 0

        # 3. Base calendar pause on unrestored runner: zero new PendingApproval
        with pytest.raises(
            KillerMissionIntegrityError, match="Cannot execute calendar pause for existing mission"
        ):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner2)
        assert getattr(runner2, "pending_approval", None) is None
        assert runner2.total_writes == 0

    def test_base_class_invocation_live_seeding_without_validated_plan_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A3: Base seeding on live runner without validated candidate plan is blocked."""
        from stilldone.killer_mission import (
            CanonicalKillerPlanValidationError,
            KillerMissionSliceRunner,
        )

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        runner.candidate_plan = None
        runner.validated_candidate_plan = None

        with pytest.raises(
            CanonicalKillerPlanValidationError,
            match="Live seeding cannot proceed without an independently validated",
        ):
            KillerMissionSliceRunner.step_p13_01_seed(runner)
        assert runner.total_writes == 0

    def test_base_class_invocation_live_without_satisfactory_preflight_blocked(
        self, tmp_path: Path
    ) -> None:
        """A3: Base methods on live runner without satisfactory preflight are blocked."""
        from stilldone.killer_mission import (
            KillerMissionSliceRunner,
            LivePreflightBlockedError,
        )

        runner = _setup_live_runner(tmp_path)

        with pytest.raises(LivePreflightBlockedError, match="Live execution gate failed preflight"):
            KillerMissionSliceRunner.step_p13_01_seed(runner)
        assert runner.total_writes == 0

        with pytest.raises(LivePreflightBlockedError, match="Live execution gate failed preflight"):
            KillerMissionSliceRunner.step_p13_03_tasks_prep(runner)
        assert runner.total_writes == 0

        with pytest.raises(LivePreflightBlockedError, match="Live execution gate failed preflight"):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)
        assert runner.total_writes == 0

    def test_base_methods_new_live_runner_preflight_passing_candidate_plan_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 1: Explicit base methods on live runner without candidate plan are blocked."""
        from stilldone.killer_mission import (
            CanonicalKillerPlanValidationError,
            KillerMissionSliceRunner,
        )

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        runner.candidate_plan = None
        runner.validated_candidate_plan = None

        with pytest.raises(
            CanonicalKillerPlanValidationError,
            match="Live seeding cannot proceed without an independently validated",
        ):
            KillerMissionSliceRunner.step_p13_01_seed(runner)
        assert runner.total_writes == 0

        with pytest.raises(
            CanonicalKillerPlanValidationError,
            match="Live tasks creation cannot proceed without an independently validated",
        ):
            KillerMissionSliceRunner.step_p13_03_tasks_prep(runner)
        assert runner.total_writes == 0

        with pytest.raises(
            CanonicalKillerPlanValidationError,
            match="Live calendar pause cannot proceed without an independently validated",
        ):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)
        assert getattr(runner, "pending_approval", None) is None
        assert runner.total_writes == 0

    def test_base_methods_new_live_runner_plan_present_but_invalid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 1: Explicit base methods on live runner with invalid plan are blocked."""
        from stilldone.killer_mission import (
            CanonicalKillerPlanValidationError,
            KillerMissionSliceRunner,
        )
        from stilldone.planning.contracts import CandidateActionProposal, CandidatePlanProposal

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        # Create an invalid candidate plan (only 1 step instead of canonical 3 steps)
        bad_action = CandidateActionProposal.create(
            action_type=ActionType.WEATHER_READ,
            target_ref=SymbolicTargetRef.WEATHER_LOCATION,
            parameters={},
            explanation="Invalid 1-step plan",
        )
        bad_plan = CandidatePlanProposal.create(
            mission_id=runner.mission_id,
            steps=[bad_action],
            explanation="Invalid proposal with missing tasks and calendar actions",
        )
        runner.candidate_plan = bad_plan
        runner.validated_candidate_plan = bad_plan

        with pytest.raises(CanonicalKillerPlanValidationError):
            KillerMissionSliceRunner.step_p13_01_seed(runner)
        assert runner.total_writes == 0

        with pytest.raises(CanonicalKillerPlanValidationError):
            KillerMissionSliceRunner.step_p13_03_tasks_prep(runner)
        assert runner.total_writes == 0

        with pytest.raises(CanonicalKillerPlanValidationError):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)
        assert getattr(runner, "pending_approval", None) is None
        assert runner.total_writes == 0

    def test_base_methods_new_live_runner_valid_plan_prior_steps_not_executed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 1: Tasks and pause methods on live runner without prior step execution
        fail closed.
        """
        from stilldone.killer_mission import (
            KillerMissionSequenceError,
            KillerMissionSliceRunner,
        )

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        plan = runner._create_deterministic_proposal()
        runner.candidate_plan = plan
        runner.validated_candidate_plan = plan
        runner.seeded_event_id = "seeded_provider_evt_7766"
        runner.step_results.clear()

        # Tasks prep fails closed because P-13.01 and P-13.02 have not executed
        with pytest.raises(
            KillerMissionSequenceError,
            match="Live tasks creation requires proven preceding seeding step",
        ):
            KillerMissionSliceRunner.step_p13_03_tasks_prep(runner)
        assert runner.total_writes == 0

        # Calendar pause fails closed because P-13.01, P-13.02, P-13.03 have not executed
        with pytest.raises(
            KillerMissionSequenceError,
            match="Live calendar pause requires proven preceding seeding step",
        ):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)
        assert getattr(runner, "pending_approval", None) is None
        assert runner.total_writes == 0

    def test_base_methods_new_live_runner_no_established_event_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 1: Tasks and pause methods on live runner without established event ID
        fail closed.
        """
        from stilldone.killer_mission import (
            KillerMissionSequenceError,
            KillerMissionSliceRunner,
        )

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        plan = runner._create_deterministic_proposal()
        runner.candidate_plan = plan
        runner.validated_candidate_plan = plan
        runner.seeded_event_id = ""

        with pytest.raises(
            KillerMissionSequenceError,
            match="Live tasks creation requires an established authoritative provider event ID",
        ):
            KillerMissionSliceRunner.step_p13_03_tasks_prep(runner)
        assert runner.total_writes == 0

        with pytest.raises(
            KillerMissionSequenceError,
            match="Live calendar pause requires an established authoritative provider event ID",
        ):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)
        assert getattr(runner, "pending_approval", None) is None
        assert runner.total_writes == 0

    def test_base_methods_live_capable_runner_without_require_preflight(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 1: Live-capable runner without _require_preflight fails closed on all steps."""
        from stilldone.killer_mission import (
            KillerMissionSliceRunner,
            LivePreflightBlockedError,
        )

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        # Delete _require_preflight method from class
        monkeypatch.delattr(LiveKillerMissionSliceRunner, "_require_preflight")

        with pytest.raises(
            LivePreflightBlockedError,
            match="Live execution boundary requires a mandatory '_require_preflight'",
        ):
            KillerMissionSliceRunner.step_p13_01_seed(runner)
        assert runner.total_writes == 0

        with pytest.raises(
            LivePreflightBlockedError,
            match="Live execution boundary requires a mandatory '_require_preflight'",
        ):
            KillerMissionSliceRunner.step_p13_03_tasks_prep(runner)
        assert runner.total_writes == 0

        with pytest.raises(
            LivePreflightBlockedError,
            match="Live execution boundary requires a mandatory '_require_preflight'",
        ):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)
        assert getattr(runner, "pending_approval", None) is None
        assert runner.total_writes == 0

    def test_normal_first_time_valid_p13_ordering_remains_functional(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 1: Normal first-time valid P-13 execution ordering executes cleanly."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        plan = runner._create_deterministic_proposal()
        runner.candidate_plan = plan
        runner.validated_candidate_plan = plan

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
        monkeypatch.setattr(
            runner.tasks_create_adapter,
            "create_task",
            lambda act, **kw: TaskCreateResult(
                status=TaskCreateStatus.CREATED,
                task_id="t_clean_123",
                task_list_id=runner.env.scope.task_list_id,
                title="Pack backpacks",
                due="2026-10-04",
                writes_performed=1,
            ),
        )
        monkeypatch.setattr(
            runner.tasks_read_adapter,
            "read_task",
            lambda act: TaskReadResult(
                status=TaskReadStatus.MATCH,
                observation=TaskObservation(
                    task_id=act.target.resource_id,
                    task_list_id=runner.env.scope.task_list_id,
                    title="Pack backpacks",
                    due="2026-10-04",
                    status="needsAction",
                    deleted=False,
                    hidden=False,
                    etag="etag_clean_123",
                    observed_at=datetime.now(UTC),
                ),
            ),
        )

        # Step 1: Seeding
        s1 = runner.step_p13_01_seed()
        assert s1.status == "PASS"
        assert s1.is_verified is True
        assert runner.seeded_event_id != ""

        # Step 2: Planning & weather read
        s2 = runner.step_p13_02_plan()
        assert s2.status == "PASS"
        assert s2.is_verified is True
        assert runner.weather_observation is not None

        # Step 3: Tasks preparation
        s3 = runner.step_p13_03_tasks_prep()
        assert s3.status == "PASS"
        assert s3.is_verified is True
        assert runner.task_observation is not None

        # Step 4: Calendar pause
        s4 = runner.step_p13_04_calendar_pause()
        assert s4.status == "PASS"
        assert runner.pending_approval is not None


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


# ===========================================================================
# Execution Action Contract Parity & Anti-Drift Boundary
# ===========================================================================


def _advance_runner_through_steps_1_and_2(
    runner: LiveKillerMissionSliceRunner,
    monkeypatch: pytest.MonkeyPatch,
    *,
    event_id: str = "seeded_evt_clean_123",
) -> None:
    monkeypatch.setattr(
        "stilldone.killer_mission.seed_canonical_demo_resources",
        lambda **kwargs: DemoSeedResult(
            status=SeedOperationStatus.MUTATION_EXECUTED,
            provenance=runner.env.provenance,
            calendar_id=runner.env.scope.calendar_id,
            task_list_id=runner.env.scope.task_list_id,
            event_id=event_id,
            event_start_time=runner.initial_start_time,
            writes_performed=1,
            readback_verified=True,
            is_seed_complete=True,
            details="Seeded clean demo event",
        ),
    )
    s1 = runner.step_p13_01_seed()
    assert s1.status == "PASS"
    s2 = runner.step_p13_02_plan()
    assert s2.status == "PASS"


def _advance_runner_through_step_3(
    runner: LiveKillerMissionSliceRunner,
    monkeypatch: pytest.MonkeyPatch,
    *,
    task_id: str = "t_clean_123",
) -> None:
    monkeypatch.setattr(
        runner.tasks_create_adapter,
        "create_task",
        lambda act, **kw: TaskCreateResult(
            status=TaskCreateStatus.CREATED,
            task_id=task_id,
            task_list_id=runner.env.scope.task_list_id,
            title="Pack backpacks",
            due=runner.demo_date,
            writes_performed=1,
        ),
    )
    monkeypatch.setattr(
        runner.tasks_read_adapter,
        "read_task",
        lambda act: TaskReadResult(
            status=TaskReadStatus.MATCH,
            observation=TaskObservation(
                task_id=act.target.resource_id,
                task_list_id=runner.env.scope.task_list_id,
                title="Pack backpacks",
                due=runner.demo_date,
                status="needsAction",
                deleted=False,
                hidden=False,
                etag="etag_clean_123",
                observed_at=datetime.now(UTC),
            ),
        ),
    )
    s3 = runner.step_p13_03_tasks_prep()
    assert s3.status == "PASS"


class TestExecutionActionContractParityAdversarial:
    """Validate execution action parity against validated plan and anti-rebinding."""

    def test_valid_plan_altered_tasks_due_date_zero_tasks_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Altered compiled Tasks due date must fail closed before any Tasks write."""
        from stilldone.killer_mission import KillerMissionSliceRunner

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _advance_runner_through_steps_1_and_2(runner, monkeypatch)

        # Alter compiled Tasks due date away from canonical plan
        bad_task = ActionContract.create(
            mission_id=runner.mission_id,
            action_type=ActionType.TASK_CREATE,
            target=runner.action_task.target,
            parameters={"title": "Pack backpacks", "due": "2099-01-01"},
            action_id=runner.action_task.action_id,
        )
        runner.action_task = bad_task

        tasks_spy = MagicMock()
        monkeypatch.setattr(runner.tasks_create_adapter, "create_task", tasks_spy)

        # Ordinary live-runner step invocation fails closed
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Tasks action due date '2099-01-01' does not match validated plan",
        ):
            runner.step_p13_03_tasks_prep()
        tasks_spy.assert_not_called()
        assert runner.total_writes == 1  # Only preceding seeding write performed

        # Direct base-class method invocation also fails closed
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Tasks action due date '2099-01-01' does not match validated plan",
        ):
            KillerMissionSliceRunner.step_p13_03_tasks_prep(runner)
        tasks_spy.assert_not_called()
        assert runner.total_writes == 1

    def test_valid_plan_altered_tasks_target_or_title_zero_tasks_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Altered Tasks target or title fails closed before any provider write."""
        from stilldone.killer_mission import KillerMissionSliceRunner

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _advance_runner_through_steps_1_and_2(runner, monkeypatch)

        tasks_spy = MagicMock()
        monkeypatch.setattr(runner.tasks_create_adapter, "create_task", tasks_spy)

        # Case A: Altered title
        runner.action_task = ActionContract.create(
            mission_id=runner.mission_id,
            action_type=ActionType.TASK_CREATE,
            target=runner.action_task.target,
            parameters={"title": "Pack altered backpacks", "due": runner.demo_date},
            action_id=runner.action_task.action_id,
        )
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Tasks action title 'Pack altered backpacks' does not match",
        ):
            runner.step_p13_03_tasks_prep()
        tasks_spy.assert_not_called()

        # Case B: Altered target list ID
        bad_target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK_LIST,
            resource_id="wrong_task_list_container_999",
            parent_id=None,
        )
        runner.action_task = ActionContract.create(
            mission_id=runner.mission_id,
            action_type=ActionType.TASK_CREATE,
            target=bad_target,
            parameters={"title": "Pack backpacks", "due": runner.demo_date},
            action_id=runner.action_task.action_id,
        )
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Tasks action target list ID 'wrong_task_list_container_999' does not match",
        ):
            KillerMissionSliceRunner.step_p13_03_tasks_prep(runner)
        tasks_spy.assert_not_called()
        assert runner.total_writes == 1

    def test_valid_plan_altered_calendar_start_time_zero_pending_approval(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Altered Calendar start time fails closed before creating PendingApproval."""
        from stilldone.killer_mission import KillerMissionSliceRunner

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _advance_runner_through_steps_1_and_2(runner, monkeypatch)
        _advance_runner_through_step_3(runner, monkeypatch)

        # Alter Calendar start time away from canonical plan
        bad_cal = ActionContract.create(
            mission_id=runner.mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=runner.action_cal.target,
            parameters={"start_time": "2026-10-04T09:00:00+00:00"},
            action_id=runner.action_cal.action_id,
        )
        runner.action_cal = bad_cal
        runner.validated_action_cal = validate_action_contract(bad_cal)

        # Live method invocation fails closed
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Calendar action start_time '2026-10-04T09:00:00\\+00:00' does not match",
        ):
            runner.step_p13_04_calendar_pause()
        assert getattr(runner, "pending_approval", None) is None

        # Direct base method invocation also fails closed
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Calendar action start_time '2026-10-04T09:00:00\\+00:00' does not match",
        ):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)
        assert getattr(runner, "pending_approval", None) is None

    def test_calendar_action_wrong_provider_event_no_silent_rebinding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calendar action targeting wrong event must fail closed without silent rebinding."""
        from stilldone.killer_mission import KillerMissionSliceRunner

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _advance_runner_through_steps_1_and_2(runner, monkeypatch)
        _advance_runner_through_step_3(runner, monkeypatch)

        seeded_evt = runner.seeded_event_id
        bad_evt = "wrong_provider_event_tampered_999"

        # Point action_cal at wrong provider event
        tampered_cal = ActionContract.create(
            mission_id=runner.mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id=bad_evt,
                parent_id=runner.env.scope.calendar_id,
            ),
            parameters=runner.action_cal.parameters,
            action_id=runner.action_cal.action_id,
        )
        runner.action_cal = tampered_cal
        runner.validated_action_cal = validate_action_contract(tampered_cal)

        with pytest.raises(
            KillerMissionIntegrityError,
            match="Silent target rebinding is strictly prohibited",
        ):
            runner.step_p13_04_calendar_pause()

        # Target MUST NOT have been silently repaired/rebound
        assert runner.action_cal.target.resource_id == bad_evt
        assert runner.action_cal.target.resource_id != seeded_evt
        assert getattr(runner, "pending_approval", None) is None

        # Direct base-method call also fails closed without silent repair
        with pytest.raises(
            KillerMissionIntegrityError,
            match="Silent target rebinding is strictly prohibited",
        ):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)
        assert runner.action_cal.target.resource_id == bad_evt

    def test_calendar_parent_container_mismatch_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calendar parent container mismatch fails closed before creating PendingApproval."""
        from stilldone.killer_mission import KillerMissionSliceRunner

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _advance_runner_through_steps_1_and_2(runner, monkeypatch)
        _advance_runner_through_step_3(runner, monkeypatch)

        mismatched_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=runner.seeded_event_id,
            parent_id="wrong_calendar_scope_id",
        )
        mismatched_cal = ActionContract.create(
            mission_id=runner.mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=mismatched_target,
            parameters=runner.action_cal.parameters,
            action_id=runner.action_cal.action_id,
        )
        runner.action_cal = mismatched_cal
        runner.validated_action_cal = validate_action_contract(mismatched_cal)

        with pytest.raises(
            KillerMissionIntegrityError,
            match="does not match scope calendar ID",
        ):
            runner.step_p13_04_calendar_pause()
        assert getattr(runner, "pending_approval", None) is None

        with pytest.raises(
            KillerMissionIntegrityError,
            match="does not match scope calendar ID",
        ):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)

    def test_mismatch_between_action_cal_and_validated_action_cal_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mismatch between action_cal and validated_action_cal fails closed."""
        from stilldone.killer_mission import KillerMissionSliceRunner

        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _advance_runner_through_steps_1_and_2(runner, monkeypatch)
        _advance_runner_through_step_3(runner, monkeypatch)

        # Create a differing validated contract
        differing_action = ActionContract.create(
            mission_id=runner.mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=runner.action_cal.target,
            parameters={"start_time": runner.initial_start_time},
            action_id=runner.action_cal.action_id,
        )
        runner.validated_action_cal = validate_action_contract(differing_action)

        with pytest.raises(
            KillerMissionIntegrityError,
            match="Mismatch between self.action_cal and self.validated_action_cal",
        ):
            runner.step_p13_04_calendar_pause()
        assert getattr(runner, "pending_approval", None) is None

        with pytest.raises(
            KillerMissionIntegrityError,
            match="Mismatch between self.action_cal and self.validated_action_cal",
        ):
            KillerMissionSliceRunner.step_p13_04_calendar_pause(runner)

    def test_missing_or_inconsistent_execution_identity_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing or inconsistent mission or action identity fails closed."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        _advance_runner_through_steps_1_and_2(runner, monkeypatch)

        # 1. Tasks action with wrong mission ID
        foreign_task = ActionContract.create(
            mission_id=MissionId("99999999-9999-9999-9999-999999999999"),
            action_type=ActionType.TASK_CREATE,
            target=runner.action_task.target,
            parameters=runner.action_task.parameters,
            action_id=runner.action_task.action_id,
        )
        runner.action_task = foreign_task
        with pytest.raises(KillerMissionIntegrityError, match="does not match active mission ID"):
            runner.step_p13_03_tasks_prep()

        # Restore valid task action and complete step 3
        runner.action_task = runner.execution_contract.actions[1]
        _advance_runner_through_step_3(runner, monkeypatch)

        # 2. Calendar action with wrong mission ID
        foreign_cal = ActionContract.create(
            mission_id=MissionId("99999999-9999-9999-9999-999999999999"),
            action_type=ActionType.CALENDAR_UPDATE,
            target=runner.action_cal.target,
            parameters=runner.action_cal.parameters,
            action_id=runner.action_cal.action_id,
        )
        runner.action_cal = foreign_cal
        runner.validated_action_cal = validate_action_contract(foreign_cal)
        with pytest.raises(KillerMissionIntegrityError, match="does not match active mission ID"):
            runner.step_p13_04_calendar_pause()
        assert getattr(runner, "pending_approval", None) is None

    def test_legitimate_seeded_provider_event_id_preserved_through_compilation_and_pending_approval(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Legitimate seeded provider event ID is preserved end-to-end without rebinding."""
        runner = _setup_live_runner(tmp_path, monkeypatch=monkeypatch)
        sentinel_id = "provider_sentinel_evt_xyz_777"
        _advance_runner_through_steps_1_and_2(runner, monkeypatch, event_id=sentinel_id)

        assert runner.seeded_event_id == sentinel_id
        assert runner.action_cal.target.resource_id == sentinel_id

        _advance_runner_through_step_3(runner, monkeypatch)
        s4 = runner.step_p13_04_calendar_pause()
        assert s4.status == "PASS"

        assert runner.pending_approval is not None
        assert runner.pending_approval.target.resource_id == sentinel_id
        assert runner.action_cal.target.resource_id == sentinel_id
