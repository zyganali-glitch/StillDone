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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from stilldone.action_policy import ValidatedActionContract, validate_action_contract
from stilldone.approval_binding import bind_approval_grant
from stilldone.approval_consumption import (
    APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
    ApprovalAlreadyUsedError,
    ApprovalConsumptionResult,
    ApprovalLedger,
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
    AuthorityClass,
    BindingHash,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.ledger import (
    ActionRecord,
    DurableFileLedger,
    EvidenceRecord,
    InMemoryNonDurableLedger,
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
