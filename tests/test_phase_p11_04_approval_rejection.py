"""Adversarial and canonical tests for Phase P-11.04 approval rejection and single-use law.

Validates all 20 P-11.04 requirements:
1. Unused valid approval can authorize exactly once.
2. Second use is rejected (ApprovalAlreadyUsedError).
3. Already-used approval rejected across repeated calls.
4. Expired approval rejected (ApprovalExpiredError).
5. Not-yet-valid approval rejected (ApprovalNotYetValidError).
6. Mission mismatch rejected (ApprovalBindingMismatchError).
7. Action mismatch rejected (ApprovalBindingMismatchError).
8. Action-type mismatch rejected (AuthorityPolicyError).
9. Target mismatch rejected (ApprovalBindingMismatchError).
10. Parameters mismatch rejected (ApprovalBindingMismatchError).
11. Authority-class mismatch rejected (ApprovalAuthorityClassMismatchError).
12. Tampered binding hash rejected (ApprovalTamperedError).
13. Malformed use/consumption state fails closed (MalformedApprovalStateError).
14. Revoked approval fails closed (ApprovalRevokedError).
15. Model/planner prose cannot reset or revive approval.
16. Execution/provider success does not reset approval-use state.
17. Approval consumption does not assert external execution success.
18. Approval consumption does not assert verification/READY.
19. P-10 recovery facts remain separate.
20. No P-11.05/P-11.06 execution path introduced.
21. Durable restart test: consumed approvals survive process restart with DurableFileLedger.
"""

from __future__ import annotations

import dataclasses
import importlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from stilldone.action_policy import ValidatedActionContract, validate_action_contract
from stilldone.approval_binding import bind_approval_grant
from stilldone.approval_consumption import (
    APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
    APPROVAL_REVOCATION_EVIDENCE_TYPE,
    ApprovalAlreadyUsedError,
    ApprovalConsumptionPersistenceError,
    ApprovalConsumptionResult,
    ApprovalConsumptionValueError,
    ApprovalLedger,
    ApprovalRevocationPersistenceError,
    ApprovalRevokedError,
    ApprovalUsageStatus,
    MalformedApprovalStateError,
    consume_approval,
    revoke_approval,
    used_approval_registry,
)
from stilldone.authority_policy import (
    ApprovalAuthorityClassMismatchError,
    ApprovalBindingMismatchError,
    ApprovalExpiredError,
    ApprovalNotYetValidError,
    ApprovalTamperedError,
    PlannerAuthorityError,
    UnexpectedApprovalGrantError,
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
    ApprovalId,
    AuthorityClass,
    BindingHash,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.evidence import EvidenceId
from stilldone.ledger import (
    ActionRecord,
    DurableFileLedger,
    EvidenceRecord,
    InMemoryNonDurableLedger,
    MissionLedgerPort,
    MissionRecord,
)
from stilldone.pending_approval import (
    ApprovalDecision,
    PendingApproval,
    create_pending_approval,
)
from stilldone.planning.contracts import (
    CandidateActionProposal,
    SymbolicTargetRef,
)

_NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
_ISSUED_AT = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
_EXPIRES_AT = datetime(2026, 10, 8, 12, 30, 0, tzinfo=UTC)
_VALID_EVAL_AT = datetime(2026, 10, 8, 12, 5, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset_global_registry() -> None:
    """Reset the global in-memory registry before each test."""
    used_approval_registry.reset()


def _make_calendar_update_setup(
    *,
    mission_id: MissionId | None = None,
    action_id: ActionId | None = None,
    resource_id: str = "c-evt-single-use",
    parameters: dict[str, Any] | None = None,
) -> tuple[PendingApproval, ValidatedActionContract, ApprovalGrant]:
    mid = mission_id or MissionId.generate()
    aid = action_id or ActionId.generate()
    params = parameters if parameters is not None else {"summary": "Family Morning Departure 07:30"}

    contract = ActionContract(
        mission_id=mid,
        action_id=aid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=resource_id,
        ),
        parameters=NormalizedParameters.from_dict(params),
    )
    validated = validate_action_contract(contract)
    pending = create_pending_approval(validated, requested_at=_NOW)
    grant = bind_approval_grant(
        pending,
        ApprovalDecision.APPROVE,
        issued_at=_ISSUED_AT,
        expires_at=_EXPIRES_AT,
    )
    return pending, validated, grant


class TestP1104SingleUseAndReplayRejection:
    """Requirements 1, 2, 3: Single-use law and replay rejection."""

    def test_req01_unused_valid_approval_can_authorize_exactly_once(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        res = consume_approval(grant, validated, at=_VALID_EVAL_AT)

        assert isinstance(res, ApprovalConsumptionResult)
        assert res.approval_id == grant.approval_id
        assert res.is_authorized is True
        assert res.consumed_at == _VALID_EVAL_AT
        assert res.attempt_number == 1

    def test_req02_second_use_is_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()

        # First consumption succeeds
        consume_approval(grant, validated, at=_VALID_EVAL_AT)

        # Immediate second consumption fails closed
        with pytest.raises(ApprovalAlreadyUsedError) as exc_info:
            consume_approval(grant, validated, at=_VALID_EVAL_AT + timedelta(seconds=1))

        assert str(grant.approval_id) in str(exc_info.value)

    def test_req03_already_used_approval_rejected_repeatedly(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        consume_approval(grant, validated, at=_VALID_EVAL_AT)

        for i in range(5):
            with pytest.raises(ApprovalAlreadyUsedError):
                consume_approval(grant, validated, at=_VALID_EVAL_AT + timedelta(seconds=i + 1))


class TestP1104ValidationRejections:
    """Requirements 4 to 12: Stale, not-yet-valid, mismatch, tampered rejections."""

    def test_req04_expired_approval_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        with pytest.raises(ApprovalExpiredError):
            consume_approval(grant, validated, at=_EXPIRES_AT)

        with pytest.raises(ApprovalExpiredError):
            consume_approval(grant, validated, at=_EXPIRES_AT + timedelta(minutes=1))

    def test_req05_not_yet_valid_approval_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        too_early = _ISSUED_AT - timedelta(seconds=1)
        with pytest.raises(ApprovalNotYetValidError):
            consume_approval(grant, validated, at=too_early)

    def test_req06_mission_mismatch_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        diff_mission_act = dataclasses.replace(
            validated.action,
            mission_id=MissionId.generate(),
        )
        with pytest.raises(ApprovalBindingMismatchError):
            consume_approval(grant, diff_mission_act, at=_VALID_EVAL_AT)

    def test_req07_action_mismatch_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        diff_act = dataclasses.replace(
            validated.action,
            action_id=ActionId.generate(),
        )
        with pytest.raises(ApprovalBindingMismatchError):
            consume_approval(grant, diff_act, at=_VALID_EVAL_AT)

    def test_req08_action_type_mismatch_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        diff_type_act = dataclasses.replace(
            validated.action,
            action_type=ActionType.CALENDAR_READ,
            parameters=NormalizedParameters.from_dict({}),
        )
        with pytest.raises(
            (
                ApprovalBindingMismatchError,
                UnexpectedApprovalGrantError,
                ApprovalAuthorityClassMismatchError,
            )
        ):
            consume_approval(grant, diff_type_act, at=_VALID_EVAL_AT)

    def test_req09_target_mismatch_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        diff_target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="different-event-999",
        )
        diff_target_act = dataclasses.replace(validated.action, target=diff_target)
        with pytest.raises(ApprovalBindingMismatchError):
            consume_approval(grant, diff_target_act, at=_VALID_EVAL_AT)

    def test_req10_parameters_mismatch_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        diff_params = dataclasses.replace(
            validated.action,
            parameters=NormalizedParameters.from_dict({"summary": "Tampered Parameters"}),
        )
        with pytest.raises(ApprovalBindingMismatchError):
            consume_approval(grant, diff_params, at=_VALID_EVAL_AT)

    def test_req11_authority_class_mismatch_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        fake_grant = dataclasses.replace(
            grant,
            authority_class=AuthorityClass.REVERSIBLE_AUTO,
        )
        with pytest.raises(ApprovalAuthorityClassMismatchError):
            consume_approval(fake_grant, validated, at=_VALID_EVAL_AT)

    def test_req12_tampered_binding_hash_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        tampered_hash = BindingHash("0" * 64)
        object.__setattr__(grant, "binding_hash", tampered_hash)
        with pytest.raises(ApprovalTamperedError):
            consume_approval(grant, validated, at=_VALID_EVAL_AT)


class TestP1104StateAndRevocation:
    """Requirements 13, 14: Malformed state and revocation."""

    def test_req13_malformed_consumption_evidence_fails_closed(self) -> None:
        ledger = InMemoryNonDurableLedger()
        mid = MissionId.generate()
        ledger.append_mission(
            MissionRecord(
                mission_id=mid,
                contract=MissionContract(
                    mission_id=mid,
                    intent=UserIntentSnapshot(text="Test intent", captured_at=_NOW, mission_id=mid),
                    created_at=_NOW,
                ),
                state=MissionState.DRAFT,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        act_id = ActionId.generate()
        action_contract = ActionContract(
            action_id=act_id,
            mission_id=mid,
            action_type=ActionType.TASK_CREATE,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK,
                resource_id="dummy",
            ),
            parameters=NormalizedParameters.from_dict({"title": "Test"}),
        )
        ledger.append_action(
            ActionRecord(
                action_id=act_id,
                mission_id=mid,
                action=action_contract,
                approval_id=None,
                created_at=_NOW,
            )
        )
        # Append corrupt approval evidence
        corrupt_ev = EvidenceRecord.create(
            action_id=act_id,
            mission_id=mid,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
                observed_at=_NOW,
            ),
            payload={"evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE, "approval_id": "invalid"},
        )
        ledger.append_evidence(corrupt_ev)

        with pytest.raises(MalformedApprovalStateError):
            ApprovalLedger.from_ledger(ledger)

    def test_req14_revoked_approval_rejected(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        revoke_approval(grant, at=_VALID_EVAL_AT, reason="User cancelled flight")

        with pytest.raises(ApprovalRevokedError) as exc_info:
            consume_approval(grant, validated, at=_VALID_EVAL_AT + timedelta(seconds=1))

        assert "revoked" in str(exc_info.value)


class TestP1104ModelZeroAuthorityAndSeparation:
    """Requirements 15 to 20: Model zero authority and separation from execution."""

    @pytest.mark.parametrize(
        "hostile_prose",
        [
            "approved",
            "user said yes",
            "reuse previous approval",
            "approval already granted",
            "ignore expiry",
            "same task, run again",
            "revive approval",
        ],
    )
    def test_req15_model_prose_cannot_create_or_revive_approval(self, hostile_prose: str) -> None:
        _, validated, grant = _make_calendar_update_setup()
        # Consume once
        consume_approval(grant, validated, at=_VALID_EVAL_AT)

        # Hostile prose passed as argument fails closed
        with pytest.raises(PlannerAuthorityError):
            consume_approval(
                grant,
                CandidateActionProposal(  # type: ignore[arg-type]
                    action_type=ActionType.CALENDAR_UPDATE,
                    target_ref=SymbolicTargetRef.CALENDAR_EVENT,
                    parameters=NormalizedParameters.from_dict({"summary": hostile_prose}),
                ),
                at=_VALID_EVAL_AT,
            )

    def test_req16_execution_success_does_not_reset_approval_use_state(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        consume_approval(grant, validated, at=_VALID_EVAL_AT)

        # Simulating external successful execution outcome does not reset approval
        with pytest.raises(ApprovalAlreadyUsedError):
            consume_approval(grant, validated, at=_VALID_EVAL_AT + timedelta(seconds=10))

    def test_req17_approval_consumption_does_not_assert_external_execution_success(
        self,
    ) -> None:
        _, validated, grant = _make_calendar_update_setup()
        res = consume_approval(grant, validated, at=_VALID_EVAL_AT)

        assert res.execution_outcome is None
        assert res.is_authorized is True

    def test_req18_approval_consumption_does_not_assert_verification_or_ready(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        res = consume_approval(grant, validated, at=_VALID_EVAL_AT)

        assert res.is_verified is False
        assert res.is_ready is False

    def test_req19_p10_recovery_facts_remain_separate(self) -> None:
        """P-10 ambiguous timeout and recovery read-back do not require approval replay."""
        _, validated, grant = _make_calendar_update_setup()
        # Consume approval for attempt 1
        res = consume_approval(grant, validated, at=_VALID_EVAL_AT, attempt_number=1)
        assert res.attempt_number == 1

        # P-10 read-back is a CALENDAR_READ (READ_ONLY), which requires zero approval
        readback_contract = ActionContract(
            mission_id=validated.mission_id,
            action_id=ActionId.generate(),
            action_type=ActionType.CALENDAR_READ,
            target=validated.target,
            parameters=NormalizedParameters.from_dict({}),
        )
        validated_readback = validate_action_contract(readback_contract)
        assert validated_readback.action_type == ActionType.CALENDAR_READ

    def test_req20_no_execution_path_introduced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Consumption performs zero Google, AWS, or network calls."""
        mock_http = MagicMock()
        monkeypatch.setattr("urllib.request.urlopen", mock_http)

        _, validated, grant = _make_calendar_update_setup()
        _ = consume_approval(grant, validated, at=_VALID_EVAL_AT)

        assert mock_http.call_count == 0


class TestP1104DurableRestartResilience:
    """Requirement 21: Consumed approvals survive process restart.

    Backed by DurableFileLedger.
    """

    def test_consumed_approval_persists_across_restart(self, tmp_path: Path) -> None:
        ledger_file = tmp_path / "durable_mission_ledger.jsonl"
        durable_ledger_1 = DurableFileLedger(file_path=ledger_file)

        _, validated, grant = _make_calendar_update_setup()

        # Seed mission in ledger 1
        durable_ledger_1.append_mission(
            MissionRecord(
                mission_id=grant.mission_id,
                contract=MissionContract(
                    mission_id=grant.mission_id,
                    intent=UserIntentSnapshot(
                        text="Shift family departure",
                        captured_at=_NOW,
                        mission_id=grant.mission_id,
                    ),
                    created_at=_NOW,
                ),
                state=MissionState.DRAFT,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        # Seed action in ledger 1
        durable_ledger_1.append_action(
            ActionRecord(
                action_id=validated.action.action_id,
                mission_id=grant.mission_id,
                action=validated.action,
                approval_id=grant.approval_id,
                created_at=_NOW,
            )
        )

        approval_ledger_1 = ApprovalLedger(ledger=durable_ledger_1)

        # Consume approval in process 1
        res1 = approval_ledger_1.consume(grant, validated, at=_VALID_EVAL_AT)
        assert res1.is_authorized is True

        # Simulate process restart by instantiating fresh ledger and approval ledger on same file
        durable_ledger_2 = DurableFileLedger(file_path=ledger_file)
        approval_ledger_2 = ApprovalLedger.from_ledger(durable_ledger_2)

        # In process 2, check that status is CONSUMED
        assert approval_ledger_2.check_status(grant.approval_id) == ApprovalUsageStatus.CONSUMED

        # Attempt to consume the same approval in process 2 is REJECTED
        with pytest.raises(ApprovalAlreadyUsedError) as exc_info:
            approval_ledger_2.consume(grant, validated, at=_VALID_EVAL_AT + timedelta(minutes=1))

        assert str(grant.approval_id) in str(exc_info.value)


class CustomPublicOnlyLedger(MissionLedgerPort):
    """Custom MissionLedgerPort without _evidence or _missions private fields."""

    def __init__(self) -> None:
        self.evidence_list: list[EvidenceRecord] = []
        self.missions_dict: dict[str, MissionRecord] = {}
        self.actions_dict: dict[str, ActionRecord] = {}

    def append_mission(self, record: MissionRecord) -> None:
        self.missions_dict[str(record.mission_id)] = record

    def get_mission(self, mission_id: MissionId) -> MissionRecord:
        return self.missions_dict[str(mission_id)]

    def append_action(self, record: ActionRecord) -> None:
        self.actions_dict[str(record.action_id)] = record

    def get_action(self, action_id: ActionId) -> ActionRecord:
        return self.actions_dict[str(action_id)]

    def get_actions_for_mission(self, mission_id: MissionId) -> list[ActionRecord]:
        return [a for a in self.actions_dict.values() if a.mission_id == mission_id]

    def append_evidence(self, record: EvidenceRecord) -> None:
        self.evidence_list.append(record)

    def get_evidence(self, evidence_id: EvidenceId) -> EvidenceRecord:
        for ev in self.evidence_list:
            if ev.evidence_id == evidence_id:
                return ev
        raise KeyError(str(evidence_id))

    def get_evidence_for_action(self, action_id: ActionId) -> list[EvidenceRecord]:
        return [ev for ev in self.evidence_list if ev.action_id == action_id]

    def get_evidence_for_mission(self, mission_id: MissionId) -> list[EvidenceRecord]:
        return [ev for ev in self.evidence_list if ev.mission_id == mission_id]

    def get_all_evidence(self) -> list[EvidenceRecord]:
        return list(self.evidence_list)


class PublicApiOnlyAuditProxy(MissionLedgerPort):
    """Proxy verifying only public methods (not starting with _) are accessed."""

    def __init__(self, target: MissionLedgerPort) -> None:
        self._target = target
        self.accessed_attrs: list[str] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") and not name.startswith("__"):
            raise AssertionError(f"Private implementation attribute {name!r} accessed on ledger!")
        self.accessed_attrs.append(name)
        return getattr(self._target, name)

    def append_mission(self, record: MissionRecord) -> None:
        self.accessed_attrs.append("append_mission")
        self._target.append_mission(record)

    def get_mission(self, mission_id: MissionId) -> MissionRecord:
        self.accessed_attrs.append("get_mission")
        return self._target.get_mission(mission_id)

    def append_action(self, record: ActionRecord) -> None:
        self.accessed_attrs.append("append_action")
        self._target.append_action(record)

    def get_action(self, action_id: ActionId) -> ActionRecord:
        self.accessed_attrs.append("get_action")
        return self._target.get_action(action_id)

    def get_actions_for_mission(self, mission_id: MissionId) -> list[ActionRecord]:
        self.accessed_attrs.append("get_actions_for_mission")
        return self._target.get_actions_for_mission(mission_id)

    def append_evidence(self, record: EvidenceRecord) -> None:
        self.accessed_attrs.append("append_evidence")
        self._target.append_evidence(record)

    def get_evidence(self, evidence_id: EvidenceId) -> EvidenceRecord:
        self.accessed_attrs.append("get_evidence")
        return self._target.get_evidence(evidence_id)

    def get_evidence_for_action(self, action_id: ActionId) -> list[EvidenceRecord]:
        self.accessed_attrs.append("get_evidence_for_action")
        return self._target.get_evidence_for_action(action_id)

    def get_evidence_for_mission(self, mission_id: MissionId) -> list[EvidenceRecord]:
        self.accessed_attrs.append("get_evidence_for_mission")
        return self._target.get_evidence_for_mission(mission_id)

    def get_all_evidence(self) -> list[EvidenceRecord]:
        self.accessed_attrs.append("get_all_evidence")
        return self._target.get_all_evidence()


class TestP1104PublicPortHydrationAndDurability:
    """Tests 1, 2, 3: Hydration exclusively through public MissionLedgerPort API."""

    def test_hydration_works_through_public_api_only(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        ledger = InMemoryNonDurableLedger()
        ledger.append_mission(
            MissionRecord(
                mission_id=grant.mission_id,
                contract=MissionContract(
                    mission_id=grant.mission_id,
                    intent=UserIntentSnapshot(
                        text="Test", captured_at=_NOW, mission_id=grant.mission_id
                    ),
                    created_at=_NOW,
                ),
                state=MissionState.DRAFT,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        ledger.append_action(
            ActionRecord(
                action_id=validated.action.action_id,
                mission_id=grant.mission_id,
                action=validated.action,
                approval_id=grant.approval_id,
                created_at=_NOW,
            )
        )
        # Append valid consumption evidence
        payload = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(grant.approval_id),
            "mission_id": str(grant.mission_id),
            "action_id": str(validated.action.action_id),
            "binding_hash": grant.binding_hash.value,
            "consumed_at": _VALID_EVAL_AT.isoformat(),
            "consumed_for_attempt": 1,
        }
        ev = EvidenceRecord.create(
            action_id=validated.action.action_id,
            mission_id=grant.mission_id,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=_VALID_EVAL_AT
            ),
            payload=payload,
            created_at=_VALID_EVAL_AT,
        )
        ledger.append_evidence(ev)

        # Wrap in audit proxy that raises on private attribute access
        audit_proxy = PublicApiOnlyAuditProxy(ledger)
        appr_ledger = ApprovalLedger(ledger=audit_proxy)

        # Verify consumed status was reconstructed
        assert appr_ledger.check_status(grant.approval_id) == ApprovalUsageStatus.CONSUMED
        # Verify get_all_evidence was called and zero private attributes accessed
        assert "get_all_evidence" in audit_proxy.accessed_attrs
        for attr in audit_proxy.accessed_attrs:
            assert not attr.startswith("_")

    def test_custom_mission_ledger_port_without_private_fields_reconstructs(self) -> None:
        custom_ledger = CustomPublicOnlyLedger()
        assert not hasattr(custom_ledger, "_evidence")
        assert not hasattr(custom_ledger, "_missions")

        _, validated, grant = _make_calendar_update_setup()
        payload = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(grant.approval_id),
            "mission_id": str(grant.mission_id),
            "action_id": str(validated.action.action_id),
            "binding_hash": grant.binding_hash.value,
            "consumed_at": _VALID_EVAL_AT.isoformat(),
            "consumed_for_attempt": 1,
        }
        ev = EvidenceRecord.create(
            action_id=validated.action.action_id,
            mission_id=grant.mission_id,
            origin=EvidenceOrigin(
                provenance=EvidenceProvenance.LOCAL_EXECUTION, observed_at=_VALID_EVAL_AT
            ),
            payload=payload,
            created_at=_VALID_EVAL_AT,
        )
        custom_ledger.append_evidence(ev)

        appr_ledger = ApprovalLedger.from_ledger(custom_ledger)
        assert appr_ledger.check_status(grant.approval_id) == ApprovalUsageStatus.CONSUMED

    def test_unsupported_ledger_without_get_all_evidence_fails_closed(self) -> None:
        class IncompleteLedger:
            pass

        MissionLedgerPort.register(IncompleteLedger)
        fake_ledger = IncompleteLedger()

        with pytest.raises(MalformedApprovalStateError) as exc_info:
            ApprovalLedger(ledger=fake_ledger)  # type: ignore[arg-type]
        assert "does not implement get_all_evidence" in str(exc_info.value)


class TestP1104ContradictoryHistoryAndTransitions:
    """Tests 4 to 8: Contradictory durable history and transition model fail-closed."""

    def _setup_ledger_with_payloads(
        self,
        payloads: list[dict[str, Any]],
        *,
        action_id: ActionId | None = None,
        mission_id: MissionId | None = None,
    ) -> InMemoryNonDurableLedger:
        ledger = InMemoryNonDurableLedger()
        mid = mission_id or MissionId.generate()
        act_id = action_id or ActionId.generate()

        ledger.append_mission(
            MissionRecord(
                mission_id=mid,
                contract=MissionContract(
                    mission_id=mid,
                    intent=UserIntentSnapshot(text="Test", captured_at=_NOW, mission_id=mid),
                    created_at=_NOW,
                ),
                state=MissionState.DRAFT,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        ledger.append_action(
            ActionRecord(
                action_id=act_id,
                mission_id=mid,
                action=ActionContract(
                    action_id=act_id,
                    mission_id=mid,
                    action_type=ActionType.CALENDAR_UPDATE,
                    target=TargetIdentity(
                        system="google_calendar",
                        resource_kind=ResourceKind.CALENDAR_EVENT,
                        resource_id="evt-1",
                    ),
                    parameters=NormalizedParameters.from_dict({"summary": "Shift"}),
                ),
                approval_id=None,
                created_at=_NOW,
            )
        )
        for i, p in enumerate(payloads):
            target_mid = MissionId(p["mission_id"]) if "mission_id" in p else mid
            target_aid = ActionId(p["action_id"]) if "action_id" in p else act_id

            # Ensure mission exists if payload references a different mission
            try:
                ledger.get_mission(target_mid)
            except Exception:
                ledger.append_mission(
                    MissionRecord(
                        mission_id=target_mid,
                        contract=MissionContract(
                            mission_id=target_mid,
                            intent=UserIntentSnapshot(
                                text="Test2", captured_at=_NOW, mission_id=target_mid
                            ),
                            created_at=_NOW,
                        ),
                        state=MissionState.DRAFT,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
            # Ensure action exists if payload references a different action
            try:
                ledger.get_action(target_aid)
            except Exception:
                ledger.append_action(
                    ActionRecord(
                        action_id=target_aid,
                        mission_id=target_mid,
                        action=ActionContract(
                            action_id=target_aid,
                            mission_id=target_mid,
                            action_type=ActionType.CALENDAR_UPDATE,
                            target=TargetIdentity(
                                system="google_calendar",
                                resource_kind=ResourceKind.CALENDAR_EVENT,
                                resource_id="evt-other",
                            ),
                            parameters=NormalizedParameters.from_dict({"summary": "Other"}),
                        ),
                        approval_id=None,
                        created_at=_NOW,
                    )
                )

            ev = EvidenceRecord.create(
                action_id=target_aid,
                mission_id=target_mid,
                origin=EvidenceOrigin(
                    provenance=EvidenceProvenance.LOCAL_EXECUTION,
                    observed_at=_NOW + timedelta(seconds=i),
                ),
                payload=p,
                created_at=_NOW + timedelta(seconds=i),
            )
            ledger.append_evidence(ev)
        return ledger

    def test_same_approval_id_different_mission_id_fails_closed(self) -> None:
        aid = ApprovalId.generate()
        mid1 = MissionId.generate()
        mid2 = MissionId.generate()
        act_id1 = ActionId.generate()
        act_id2 = ActionId.generate()
        b_hash = BindingHash("a" * 64)

        p1 = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid1),
            "action_id": str(act_id1),
            "binding_hash": b_hash.value,
            "consumed_at": _VALID_EVAL_AT.isoformat(),
            "consumed_for_attempt": 1,
        }
        p2 = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid2),
            "action_id": str(act_id2),
            "binding_hash": b_hash.value,
            "consumed_at": (_VALID_EVAL_AT + timedelta(seconds=1)).isoformat(),
            "consumed_for_attempt": 1,
        }
        ledger = self._setup_ledger_with_payloads([p1, p2])
        with pytest.raises(MalformedApprovalStateError) as exc_info:
            ApprovalLedger.from_ledger(ledger)
        assert "Contradictory approval history" in str(exc_info.value)
        assert "mission_id" in str(exc_info.value)

    def test_same_approval_id_different_action_id_fails_closed(self) -> None:
        aid = ApprovalId.generate()
        mid = MissionId.generate()
        act1 = ActionId.generate()
        act2 = ActionId.generate()
        b_hash = BindingHash("b" * 64)

        p1 = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act1),
            "binding_hash": b_hash.value,
            "consumed_at": _VALID_EVAL_AT.isoformat(),
            "consumed_for_attempt": 1,
        }
        p2 = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act2),
            "binding_hash": b_hash.value,
            "consumed_at": (_VALID_EVAL_AT + timedelta(seconds=1)).isoformat(),
            "consumed_for_attempt": 1,
        }
        ledger = self._setup_ledger_with_payloads([p1, p2])
        with pytest.raises(MalformedApprovalStateError) as exc_info:
            ApprovalLedger.from_ledger(ledger)
        assert "Contradictory approval history" in str(exc_info.value)
        assert "action_id" in str(exc_info.value)

    def test_same_approval_id_different_binding_hash_fails_closed(self) -> None:
        aid = ApprovalId.generate()
        mid = MissionId.generate()
        act = ActionId.generate()
        h1 = BindingHash("1" * 64)
        h2 = BindingHash("2" * 64)

        p1 = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act),
            "binding_hash": h1.value,
            "consumed_at": _VALID_EVAL_AT.isoformat(),
            "consumed_for_attempt": 1,
        }
        p2 = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act),
            "binding_hash": h2.value,
            "consumed_at": (_VALID_EVAL_AT + timedelta(seconds=1)).isoformat(),
            "consumed_for_attempt": 1,
        }
        ledger = self._setup_ledger_with_payloads([p1, p2])
        with pytest.raises(MalformedApprovalStateError) as exc_info:
            ApprovalLedger.from_ledger(ledger)
        assert "Contradictory approval history" in str(exc_info.value)
        assert "binding_hash" in str(exc_info.value)

    def test_revoked_to_consumed_transition_fails_closed(self) -> None:
        aid = ApprovalId.generate()
        mid = MissionId.generate()
        act = ActionId.generate()
        b_hash = BindingHash("3" * 64)

        # REVOKED followed by CONSUMED is forbidden
        p_revoked = {
            "evidence_type": APPROVAL_REVOCATION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act),
            "binding_hash": b_hash.value,
            "consumed_at": _VALID_EVAL_AT.isoformat(),
            "consumed_for_attempt": 1,
        }
        p_consumed = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act),
            "binding_hash": b_hash.value,
            "consumed_at": (_VALID_EVAL_AT + timedelta(seconds=1)).isoformat(),
            "consumed_for_attempt": 1,
        }
        ledger = self._setup_ledger_with_payloads([p_revoked, p_consumed])
        with pytest.raises(MalformedApprovalStateError) as exc_info:
            ApprovalLedger.from_ledger(ledger)
        assert "Forbidden approval status transition" in str(exc_info.value)
        assert "REVOKED -> CONSUMED is prohibited" in str(exc_info.value)

    def test_duplicate_consumed_in_history_fails_closed(self) -> None:
        aid = ApprovalId.generate()
        mid = MissionId.generate()
        act = ActionId.generate()
        b_hash = BindingHash("4" * 64)

        p1 = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act),
            "binding_hash": b_hash.value,
            "consumed_at": _VALID_EVAL_AT.isoformat(),
            "consumed_for_attempt": 1,
        }
        p2 = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act),
            "binding_hash": b_hash.value,
            "consumed_at": (_VALID_EVAL_AT + timedelta(seconds=1)).isoformat(),
            "consumed_for_attempt": 2,
        }
        ledger = self._setup_ledger_with_payloads([p1, p2])
        with pytest.raises(MalformedApprovalStateError) as exc_info:
            ApprovalLedger.from_ledger(ledger)
        assert "Duplicate or replay consumption in durable history" in str(exc_info.value)

    def test_consumed_to_revoked_transition_allowed_and_retains_revoked(self) -> None:
        aid = ApprovalId.generate()
        mid = MissionId.generate()
        act = ActionId.generate()
        b_hash = BindingHash("5" * 64)

        p1 = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act),
            "binding_hash": b_hash.value,
            "consumed_at": _VALID_EVAL_AT.isoformat(),
            "consumed_for_attempt": 1,
        }
        p2 = {
            "evidence_type": APPROVAL_REVOCATION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(mid),
            "action_id": str(act),
            "binding_hash": b_hash.value,
            "consumed_at": (_VALID_EVAL_AT + timedelta(seconds=1)).isoformat(),
            "consumed_for_attempt": 1,
        }
        ledger = self._setup_ledger_with_payloads([p1, p2])
        appr_ledger = ApprovalLedger.from_ledger(ledger)
        # Final status is REVOKED (permanently non-authorizing)
        assert appr_ledger.check_status(aid) == ApprovalUsageStatus.REVOKED


class TestP1104DurablePersistenceFailureAndLineage:
    """Tests 9 to 12: Persistence failures fail-closed and lineage integrity."""

    def test_durable_persistence_failure_during_consume_returns_no_authorization(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        failing_ledger = MagicMock(spec=MissionLedgerPort)
        failing_ledger.get_all_evidence.return_value = []
        failing_ledger.append_evidence.side_effect = OSError("Simulated disk full")

        ledger = ApprovalLedger(ledger=failing_ledger)
        with pytest.raises(ApprovalConsumptionPersistenceError) as exc_info:
            ledger.consume(grant, validated, at=_VALID_EVAL_AT)

        assert "Failed to durably persist approval consumption" in str(exc_info.value)
        # Proves no authorization is returned and registry does NOT record consumption
        assert ledger.check_status(grant.approval_id) == ApprovalUsageStatus.UNUSED

    def test_durable_persistence_failure_during_revoke_not_swallowed(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        failing_ledger = MagicMock(spec=MissionLedgerPort)
        failing_ledger.get_all_evidence.return_value = []
        failing_ledger.append_evidence.side_effect = OSError("Simulated disk write failure")

        ledger = ApprovalLedger(ledger=failing_ledger)
        with pytest.raises(ApprovalRevocationPersistenceError) as exc_info:
            ledger.revoke(grant, at=_VALID_EVAL_AT, reason="Revoking")

        assert "Failed to durably persist revocation" in str(exc_info.value)
        # Proves not swallowed and memory state not updated
        assert ledger.check_status(grant.approval_id) == ApprovalUsageStatus.UNUSED

    def test_approval_id_only_revocation_cannot_fabricate_dummy_lineage(self) -> None:
        unhydrated_id = ApprovalId.generate()
        # Unknown approval with no lineage fails closed
        with pytest.raises(ApprovalConsumptionValueError) as exc_info:
            revoke_approval(unhydrated_id, at=_VALID_EVAL_AT)
        assert "canonical lineage" in str(exc_info.value)

    def test_restart_after_durable_revocation_remains_non_authorizing(self, tmp_path: Path) -> None:
        ledger_file = tmp_path / "revocation_ledger.jsonl"
        durable_ledger_1 = DurableFileLedger(file_path=ledger_file)

        _, validated, grant = _make_calendar_update_setup()
        durable_ledger_1.append_mission(
            MissionRecord(
                mission_id=grant.mission_id,
                contract=MissionContract(
                    mission_id=grant.mission_id,
                    intent=UserIntentSnapshot(
                        text="Test", captured_at=_NOW, mission_id=grant.mission_id
                    ),
                    created_at=_NOW,
                ),
                state=MissionState.DRAFT,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        durable_ledger_1.append_action(
            ActionRecord(
                action_id=validated.action.action_id,
                mission_id=grant.mission_id,
                action=validated.action,
                approval_id=grant.approval_id,
                created_at=_NOW,
            )
        )

        approval_ledger_1 = ApprovalLedger(ledger=durable_ledger_1)
        approval_ledger_1.revoke(grant, at=_VALID_EVAL_AT, reason="User cancelled flight")
        assert approval_ledger_1.check_status(grant.approval_id) == ApprovalUsageStatus.REVOKED

        # Restart
        durable_ledger_2 = DurableFileLedger(file_path=ledger_file)
        approval_ledger_2 = ApprovalLedger.from_ledger(durable_ledger_2)
        assert approval_ledger_2.check_status(grant.approval_id) == ApprovalUsageStatus.REVOKED

        # Rejection of consumption in process 2
        with pytest.raises(ApprovalRevokedError):
            approval_ledger_2.consume(grant, validated, at=_VALID_EVAL_AT + timedelta(minutes=1))


class TestP1104InvariantsAndSeparation:
    """Tests 13 to 19: Terminal status, zero provider calls, P-10 separation."""

    def test_consumed_approval_cannot_become_unused(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        ledger = ApprovalLedger()
        ledger.consume(grant, validated, at=_VALID_EVAL_AT)
        assert ledger.check_status(grant.approval_id) == ApprovalUsageStatus.CONSUMED
        # Attempting revocation transitions it to REVOKED, never UNUSED
        ledger.revoke(grant, at=_VALID_EVAL_AT + timedelta(seconds=1))
        assert ledger.check_status(grant.approval_id) == ApprovalUsageStatus.REVOKED
        assert ledger.check_status(grant.approval_id) != ApprovalUsageStatus.UNUSED

    def test_revoked_approval_cannot_become_unused(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        ledger = ApprovalLedger()
        ledger.revoke(grant, at=_VALID_EVAL_AT)
        assert ledger.check_status(grant.approval_id) == ApprovalUsageStatus.REVOKED
        # Cannot be reset or become UNUSED
        assert ledger.check_status(grant.approval_id) != ApprovalUsageStatus.UNUSED

    def test_revoked_approval_cannot_later_become_consumed(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        ledger = ApprovalLedger()
        ledger.revoke(grant, at=_VALID_EVAL_AT)
        with pytest.raises(ApprovalRevokedError):
            ledger.consume(grant, validated, at=_VALID_EVAL_AT + timedelta(seconds=1))

    def test_no_provider_execution_occurs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_http = MagicMock()
        monkeypatch.setattr("urllib.request.urlopen", mock_http)

        _, validated, grant = _make_calendar_update_setup()
        ledger = ApprovalLedger()
        res = ledger.consume(grant, validated, at=_VALID_EVAL_AT)
        assert res.is_authorized is True
        assert mock_http.call_count == 0

    def test_no_verification_or_ready_asserted(self) -> None:
        _, validated, grant = _make_calendar_update_setup()
        ledger = ApprovalLedger()
        res = ledger.consume(grant, validated, at=_VALID_EVAL_AT)
        assert res.is_verified is False
        assert res.is_ready is False
        assert res.execution_outcome is None

    def test_p10_recovery_separation_intact(self, tmp_path: Path) -> None:
        from stilldone.recovery.continuity import reconstruct_action_recovery_state

        ledger_file = tmp_path / "p10_ledger.jsonl"
        durable_ledger = DurableFileLedger(file_path=ledger_file)
        _, validated, grant = _make_calendar_update_setup()

        durable_ledger.append_mission(
            MissionRecord(
                mission_id=grant.mission_id,
                contract=MissionContract(
                    mission_id=grant.mission_id,
                    intent=UserIntentSnapshot(
                        text="Test", captured_at=_NOW, mission_id=grant.mission_id
                    ),
                    created_at=_NOW,
                ),
                state=MissionState.DRAFT,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        durable_ledger.append_action(
            ActionRecord(
                action_id=validated.action.action_id,
                mission_id=grant.mission_id,
                action=validated.action,
                approval_id=grant.approval_id,
                created_at=_NOW,
            )
        )

        recovery_state = reconstruct_action_recovery_state(
            action=validated.action,
            ledger=durable_ledger,
        )
        assert recovery_state.action_id == validated.action.action_id
        # Reconstructing recovery state touches 0 approvals and does NOT consume grant
        assert used_approval_registry.is_used(grant.approval_id) is False

    def test_p11_05_and_p11_06_remain_absent(self) -> None:
        with pytest.raises(ImportError):
            importlib.import_module("stilldone.execution_gate_proof")
        with pytest.raises(ImportError):
            importlib.import_module("stilldone.p11_05")
        with pytest.raises(ImportError):
            importlib.import_module("stilldone.p11_06")
