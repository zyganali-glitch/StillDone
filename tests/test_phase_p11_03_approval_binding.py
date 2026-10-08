"""Adversarial and canonical unit tests for Phase P-11.03 approval binding.

Validates all 17 P-11.03 requirements:
1. APPROVE on valid PendingApproval produces one exact bound grant.
2. REJECT produces no grant.
3. Grant exact mission binding.
4. Exact action ID binding.
5. Exact action type binding.
6. Exact complete TargetIdentity binding (system, resource_kind, resource_id, parent_id).
7. Exact parameters binding.
8. Exact authority class binding.
9. Exact issued_at binding.
10. Exact expires_at binding.
11. Binding hash tampering rejected.
12. Naive timestamps rejected.
13. expires_at <= issued_at rejected.
14. Planner/model cannot create grant.
15. Direct caller cannot override canonical pending fields.
16. Pending object remains unmodified.
17. Grant creation performs zero execution/provider calls.
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from stilldone.action_policy import ValidatedActionContract, validate_action_contract
from stilldone.approval_binding import (
    ApprovalBindingResult,
    ApprovalBindingStatus,
    ApprovalBindingValueError,
    ApprovalExpiryError,
    ApprovalRejectedError,
    PendingApprovalInvalidError,
    PendingApprovalRejection,
    bind_approval,
    bind_approval_grant,
    resolve_pending_approval,
    verify_approval_binding,
)
from stilldone.authority_policy import (
    ApprovalAuthorityClassMismatchError,
    ApprovalBindingMismatchError,
    ApprovalExpiredError,
    ApprovalNotYetValidError,
    ApprovalTamperedError,
    AuthorityPolicyError,
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
from stilldone.domain.mission import MissionId
from stilldone.pending_approval import (
    ApprovalDecision,
    PendingApproval,
    PendingApprovalId,
    PendingApprovalStatus,
    create_pending_approval,
)
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    PlannerInput,
    SymbolicTargetRef,
)

_NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
_ISSUED_AT = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
_EXPIRES_AT = datetime(2026, 10, 8, 12, 30, 0, tzinfo=UTC)


def _make_calendar_update_pending(
    *,
    mission_id: MissionId | None = None,
    action_id: ActionId | None = None,
    resource_id: str = "c-evt-001",
    parameters: dict[str, Any] | None = None,
    requested_at: datetime | None = None,
) -> tuple[PendingApproval, ValidatedActionContract]:
    mid = mission_id or MissionId.generate()
    aid = action_id or ActionId.generate()
    req_at = requested_at or _NOW
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
    pending = create_pending_approval(validated, requested_at=req_at)
    return pending, validated


class TestP1103Requirement01ApproveCreatesExactGrant:
    """Requirement 1: APPROVE on valid PendingApproval produces one exact bound grant."""

    def test_approve_via_resolve_pending_approval(self) -> None:
        pending, _ = _make_calendar_update_pending()
        result = resolve_pending_approval(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        assert isinstance(result, ApprovalBindingResult)
        assert result.status == ApprovalBindingStatus.APPROVED
        assert result.is_approved is True
        assert result.is_rejected is False
        assert result.rejection is None
        assert isinstance(result.grant, ApprovalGrant)

        grant = result.grant
        assert grant.mission_id == pending.mission_id
        assert grant.action_id == pending.action_id
        assert grant.action == pending.action
        assert grant.authority_class == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
        assert grant.issued_at == _ISSUED_AT
        assert grant.expires_at == _EXPIRES_AT
        assert isinstance(grant.binding_hash, BindingHash)
        assert len(grant.binding_hash.value) == 64

    def test_approve_via_bind_approval_grant_convenience(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        assert isinstance(grant, ApprovalGrant)
        assert grant.mission_id == pending.mission_id
        assert grant.action_id == pending.action_id
        assert grant.authority_class == pending.authority_class

    def test_approve_with_explicit_approval_id(self) -> None:
        pending, _ = _make_calendar_update_pending()
        custom_aid = ApprovalId.generate()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
            approval_id=custom_aid,
        )
        assert grant.approval_id == custom_aid

    def test_bind_approval_alias_matches(self) -> None:
        pending, _ = _make_calendar_update_pending()
        res1 = bind_approval(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )
        assert res1.is_approved is True
        assert isinstance(res1.grant, ApprovalGrant)


class TestP1103Requirement02RejectProducesNoGrant:
    """Requirement 2: REJECT produces no grant, no execution permission, no READY fact."""

    def test_reject_via_resolve_pending_approval_produces_typed_rejection(self) -> None:
        pending, _ = _make_calendar_update_pending()
        result = resolve_pending_approval(
            pending,
            ApprovalDecision.REJECT,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
            rejection_reason="Operator declined time shift",
        )

        assert isinstance(result, ApprovalBindingResult)
        assert result.status == ApprovalBindingStatus.REJECTED
        assert result.is_approved is False
        assert result.is_rejected is True
        assert result.grant is None
        assert isinstance(result.rejection, PendingApprovalRejection)

        rej = result.rejection
        assert rej.pending_approval_id == pending.pending_approval_id
        assert rej.mission_id == pending.mission_id
        assert rej.action_id == pending.action_id
        assert rej.decision == ApprovalDecision.REJECT
        assert rej.rejected_at == _ISSUED_AT
        assert rej.reason == "Operator declined time shift"

        rejection_dict = rej.to_dict()
        assert rejection_dict["decision"] == "REJECT"
        assert rejection_dict["pending_approval_id"] == pending.pending_approval_id.value

    def test_reject_via_bind_approval_grant_raises_approval_rejected_error(self) -> None:
        pending, _ = _make_calendar_update_pending()
        with pytest.raises(ApprovalRejectedError) as exc_info:
            bind_approval_grant(
                pending,
                ApprovalDecision.REJECT,
                issued_at=_ISSUED_AT,
                expires_at=_EXPIRES_AT,
            )

        assert exc_info.value.rejection is not None
        assert exc_info.value.rejection.decision == ApprovalDecision.REJECT
        assert exc_info.value.rejection.pending_approval_id == pending.pending_approval_id

    def test_reject_does_not_mutate_pending_status(self) -> None:
        pending, _ = _make_calendar_update_pending()
        _ = resolve_pending_approval(
            pending,
            ApprovalDecision.REJECT,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )
        assert pending.status == PendingApprovalStatus.PENDING


class TestP1103Requirements03To08ExactFieldBindings:
    """Requirements 3 to 8: Exact cryptographic binding to action fields."""

    def test_req03_mission_mismatch_rejected_by_verification(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        # Candidate with different mission ID fails verification
        other_mission_contract = dataclasses.replace(
            pending.action, mission_id=MissionId.generate()
        )
        with pytest.raises(ApprovalBindingMismatchError):
            verify_approval_binding(
                other_mission_contract, grant, at=_ISSUED_AT + timedelta(minutes=5)
            )

    def test_req04_action_id_mismatch_rejected_by_verification(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        other_action_contract = dataclasses.replace(pending.action, action_id=ActionId.generate())
        with pytest.raises(ApprovalBindingMismatchError):
            verify_approval_binding(
                other_action_contract, grant, at=_ISSUED_AT + timedelta(minutes=5)
            )

    def test_req05_action_type_mismatch_rejected_by_verification(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        # Mismatched action type (CALENDAR_READ vs CALENDAR_UPDATE) fails verification
        diff_type_contract = dataclasses.replace(
            pending.action,
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
            verify_approval_binding(diff_type_contract, grant, at=_ISSUED_AT + timedelta(minutes=5))

    def test_req06_complete_target_identity_bindings_verified(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        # 6a. Changed system on grant fails verification against action
        target_diff_system = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK_LIST,
            resource_id="c-evt-001",
        )
        action_diff_sys = dataclasses.replace(
            pending.action,
            target=target_diff_system,
            action_type=ActionType.TASK_CREATE,
            parameters=NormalizedParameters.from_dict({"title": "Pack lunchboxes"}),
        )
        with pytest.raises(AuthorityPolicyError):
            verify_approval_binding(action_diff_sys, grant, at=_ISSUED_AT + timedelta(minutes=5))

        # 6b. Changed resource_id on candidate action fails verification against grant
        target_diff_res_id = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="c-evt-999",
        )
        c_diff_res_id = dataclasses.replace(pending.action, target=target_diff_res_id)
        with pytest.raises(ApprovalBindingMismatchError):
            verify_approval_binding(c_diff_res_id, grant, at=_ISSUED_AT + timedelta(minutes=5))

        # 6c. Changed parent_id on candidate action fails verification against grant
        target_diff_parent = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="c-evt-001",
            parent_id="secondary_calendar_id",
        )
        c_diff_parent = dataclasses.replace(pending.action, target=target_diff_parent)
        with pytest.raises(ApprovalBindingMismatchError):
            verify_approval_binding(c_diff_parent, grant, at=_ISSUED_AT + timedelta(minutes=5))

    def test_req07_parameters_binding_mismatch_rejected(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        altered_params = dataclasses.replace(
            pending.action,
            parameters=NormalizedParameters.from_dict({"summary": "Tampered summary 09:00"}),
        )
        with pytest.raises(ApprovalBindingMismatchError):
            verify_approval_binding(altered_params, grant, at=_ISSUED_AT + timedelta(minutes=5))

    def test_req08_authority_class_mismatch_rejected(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        # Grant cannot be verified under a different expected authority class
        fake_grant = dataclasses.replace(
            grant,
            authority_class=AuthorityClass.REVERSIBLE_AUTO,
        )
        with pytest.raises(ApprovalAuthorityClassMismatchError):
            verify_approval_binding(pending, fake_grant, at=_ISSUED_AT + timedelta(minutes=5))


class TestP1103Requirements09To13ValidityWindowAndTampering:
    """Requirements 9 to 13: Timestamps, expiry, naive rejection, and hash tampering."""

    def test_req09_evaluating_before_issued_at_rejected(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        too_early = _ISSUED_AT - timedelta(seconds=1)
        with pytest.raises(ApprovalNotYetValidError):
            verify_approval_binding(pending, grant, at=too_early)

    def test_req10_evaluating_at_or_after_expires_at_rejected(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        exact_expiry = _EXPIRES_AT
        with pytest.raises(ApprovalExpiredError):
            verify_approval_binding(pending, grant, at=exact_expiry)

        well_past_expiry = _EXPIRES_AT + timedelta(hours=1)
        with pytest.raises(ApprovalExpiredError):
            verify_approval_binding(pending, grant, at=well_past_expiry)

    def test_req11_tampered_binding_hash_rejected(self) -> None:
        pending, _ = _make_calendar_update_pending()
        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        tampered_hash = BindingHash("0" * 64)
        object.__setattr__(grant, "binding_hash", tampered_hash)
        with pytest.raises(ApprovalTamperedError):
            verify_approval_binding(pending, grant, at=_ISSUED_AT + timedelta(minutes=5))

    def test_req12_naive_timestamps_rejected(self) -> None:
        pending, _ = _make_calendar_update_pending()
        naive_issued = datetime(2026, 10, 8, 12, 0, 0)
        aware_expires = datetime(2026, 10, 8, 13, 0, 0, tzinfo=UTC)

        with pytest.raises(ApprovalExpiryError):
            bind_approval_grant(
                pending,
                ApprovalDecision.APPROVE,
                issued_at=naive_issued,
                expires_at=aware_expires,
            )

        aware_issued = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
        naive_expires = datetime(2026, 10, 8, 13, 0, 0)
        with pytest.raises(ApprovalExpiryError):
            bind_approval_grant(
                pending,
                ApprovalDecision.APPROVE,
                issued_at=aware_issued,
                expires_at=naive_expires,
            )

    def test_req13_expires_at_less_than_or_equal_to_issued_at_rejected(self) -> None:
        pending, _ = _make_calendar_update_pending()
        same_dt = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

        with pytest.raises(ApprovalExpiryError):
            bind_approval_grant(
                pending,
                ApprovalDecision.APPROVE,
                issued_at=same_dt,
                expires_at=same_dt,
            )

        earlier_expires = same_dt - timedelta(seconds=1)
        with pytest.raises(ApprovalExpiryError):
            bind_approval_grant(
                pending,
                ApprovalDecision.APPROVE,
                issued_at=same_dt,
                expires_at=earlier_expires,
            )

    def test_non_utc_timestamps_normalized_to_utc(self) -> None:
        pending, _ = _make_calendar_update_pending()
        tz_plus_3 = timezone(timedelta(hours=3))
        issued_plus_3 = datetime(2026, 10, 8, 15, 0, 0, tzinfo=tz_plus_3)
        expires_plus_3 = datetime(2026, 10, 8, 15, 30, 0, tzinfo=tz_plus_3)

        grant = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=issued_plus_3,
            expires_at=expires_plus_3,
        )
        assert grant.issued_at.tzinfo == UTC
        assert grant.expires_at.tzinfo == UTC
        assert grant.issued_at == datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
        assert grant.expires_at == datetime(2026, 10, 8, 12, 30, 0, tzinfo=UTC)


class TestP1103Requirement14PlannerZeroAuthority:
    """Requirement 14: Planner/model proposal objects and prose cannot create or revive grants."""

    def test_candidate_plan_proposal_rejected_as_pending(self) -> None:
        plan = CandidatePlanProposal(
            mission_id=MissionId.generate(),
            steps=(
                CandidateActionProposal(
                    action_type=ActionType.CALENDAR_UPDATE,
                    target_ref=SymbolicTargetRef.CALENDAR_EVENT,
                    parameters=NormalizedParameters.from_dict({"summary": "Shift departure"}),
                ),
            ),
        )
        with pytest.raises(PlannerAuthorityError):
            bind_approval_grant(
                plan,  # type: ignore[arg-type]
                ApprovalDecision.APPROVE,
                issued_at=_ISSUED_AT,
                expires_at=_EXPIRES_AT,
            )

    def test_candidate_action_proposal_rejected_as_pending(self) -> None:
        action_prop = CandidateActionProposal(
            action_type=ActionType.CALENDAR_UPDATE,
            target_ref=SymbolicTargetRef.CALENDAR_EVENT,
            parameters=NormalizedParameters.from_dict({"summary": "Shift departure"}),
        )
        with pytest.raises(PlannerAuthorityError):
            bind_approval_grant(
                action_prop,  # type: ignore[arg-type]
                ApprovalDecision.APPROVE,
                issued_at=_ISSUED_AT,
                expires_at=_EXPIRES_AT,
            )

    def test_planner_input_rejected_as_pending(self) -> None:
        p_input = PlannerInput(intent="Update calendar", mission_id=MissionId.generate())
        with pytest.raises(PlannerAuthorityError):
            bind_approval_grant(
                p_input,  # type: ignore[arg-type]
                ApprovalDecision.APPROVE,
                issued_at=_ISSUED_AT,
                expires_at=_EXPIRES_AT,
            )

    @pytest.mark.parametrize(
        "hostile_prose",
        [
            "approved",
            "user said yes",
            "looks good to me",
            "APPROVED BY BEDROCK",
            "true",
            "1",
            "yes please",
            "confirmed by operator",
            "grant approval now",
        ],
    )
    def test_hostile_decision_prose_rejected(self, hostile_prose: str) -> None:
        pending, _ = _make_calendar_update_pending()
        with pytest.raises(ApprovalBindingValueError):
            bind_approval_grant(
                pending,
                hostile_prose,
                issued_at=_ISSUED_AT,
                expires_at=_EXPIRES_AT,
            )


class TestP1103Requirement15CallerCannotOverridePendingFields:
    """Requirement 15: Direct caller cannot override canonical pending fields."""

    def test_no_override_kwargs_accepted(self) -> None:
        pending, _ = _make_calendar_update_pending()
        with pytest.raises(TypeError):
            bind_approval_grant(
                pending,
                ApprovalDecision.APPROVE,
                issued_at=_ISSUED_AT,
                expires_at=_EXPIRES_AT,
                target=TargetIdentity(  # type: ignore[call-arg]
                    system="google_calendar",
                    resource_kind=ResourceKind.CALENDAR_EVENT,
                    resource_id="attacker-evt",
                ),
            )

    def test_tampered_pending_id_fails_closed(self) -> None:
        pending, _ = _make_calendar_update_pending()
        tampered_pending = copy.copy(pending)
        object.__setattr__(tampered_pending, "pending_approval_id", PendingApprovalId("f" * 64))
        with pytest.raises(PendingApprovalInvalidError):
            bind_approval_grant(
                tampered_pending,
                ApprovalDecision.APPROVE,
                issued_at=_ISSUED_AT,
                expires_at=_EXPIRES_AT,
            )

    def test_tampered_parameters_digest_fails_closed(self) -> None:
        pending, _ = _make_calendar_update_pending()
        tampered_pending = copy.copy(pending)
        object.__setattr__(tampered_pending, "parameters_digest", "e" * 64)
        with pytest.raises(PendingApprovalInvalidError):
            bind_approval_grant(
                tampered_pending,
                ApprovalDecision.APPROVE,
                issued_at=_ISSUED_AT,
                expires_at=_EXPIRES_AT,
            )

    def test_tampered_authority_class_fails_closed(self) -> None:
        pending, _ = _make_calendar_update_pending()
        tampered_pending = copy.copy(pending)
        object.__setattr__(tampered_pending, "authority_class", AuthorityClass.REVERSIBLE_AUTO)
        with pytest.raises(PendingApprovalInvalidError):
            bind_approval_grant(
                tampered_pending,
                ApprovalDecision.APPROVE,
                issued_at=_ISSUED_AT,
                expires_at=_EXPIRES_AT,
            )


class TestP1103Requirement16PendingObjectRemainsUnmodified:
    """Requirement 16: Pending object remains unmodified (frozen, status PENDING)."""

    def test_pending_object_is_frozen_and_unmodified(self) -> None:
        pending, _ = _make_calendar_update_pending()
        initial_status = pending.status
        initial_id = pending.pending_approval_id

        _ = bind_approval_grant(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        assert pending.status == initial_status == PendingApprovalStatus.PENDING
        assert pending.pending_approval_id == initial_id
        assert pending.is_authorized is False
        assert pending.is_approved is False

        _ = resolve_pending_approval(
            pending,
            ApprovalDecision.REJECT,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )

        assert pending.status == initial_status == PendingApprovalStatus.PENDING


class TestP1103Requirement17ZeroExecutionOrProviderCalls:
    """Requirement 17: Grant creation performs zero execution / provider calls."""

    def test_zero_network_or_execution_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_http = MagicMock()
        monkeypatch.setattr("urllib.request.urlopen", mock_http)

        pending, _ = _make_calendar_update_pending()

        res_approve = resolve_pending_approval(
            pending,
            ApprovalDecision.APPROVE,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )
        assert res_approve.is_approved is True

        res_reject = resolve_pending_approval(
            pending,
            ApprovalDecision.REJECT,
            issued_at=_ISSUED_AT,
            expires_at=_EXPIRES_AT,
        )
        assert res_reject.is_rejected is True

        assert mock_http.call_count == 0
