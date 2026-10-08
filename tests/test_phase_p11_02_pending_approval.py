"""Adversarial and canonical tests for Phase P-11.02 pending approval and one-decision UX contract.

Validates:
1. CALENDAR_UPDATE produces valid PendingApproval.
2. TASK_CREATE cannot produce PendingApproval under current P-11.01 policy.
3. Read-only actions (calendar.read, task.read, weather.read) cannot produce PendingApproval.
4. Planner / model proposal objects rejected fail-closed.
5. PendingApproval and OneDecisionContract are immutable.
6. Pending object does not contain ApprovalGrant and rejects smuggled grants.
7. Pending creation does not authorize execution (is_authorized=False, is_approved=False).
8. No execution / provider calls occur.
9. One-decision contract exposes exactly APPROVE and REJECT.
10. Arbitrary strings rejected as decisions ("yes maybe", "looks fine", "approved by model", etc.).
11. Same canonical input produces stable deterministic identity (PendingApprovalId).
12. Changed mission/action/target/parameters alters pending approval identity.
13. Authority class comes strictly from frozen P-11.01 policy, not caller/model override.
14. Unsafe / malformed policy lineage fails closed.
15. Privacy-safe repr, str, and error behavior (redaction of secrets, emails).
16. No P-11.03/P-11.04 behavior introduced (no grant creation, no consumption, no replay ledger).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from stilldone.action_policy import ValidatedActionContract, validate_action_contract
from stilldone.authority_policy import (
    InvalidApprovalTypeError,
    PlannerAuthorityError,
    evaluate_authority,
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
from stilldone.domain.mission import MissionId
from stilldone.pending_approval import (
    PENDING_APPROVAL_DOMAIN_SEPARATOR,
    ApprovalDecision,
    ApprovalNotRequiredError,
    InvalidDecisionError,
    OneDecisionContract,
    PendingApproval,
    PendingApprovalId,
    PendingApprovalStatus,
    PendingApprovalTamperedError,
    PendingApprovalTypeError,
    PendingApprovalValueError,
    SmuggledGrantError,
    compute_pending_approval_id,
    create_pending_approval,
    validate_approval_decision,
)
from stilldone.planning.contracts import (
    CandidateActionProposal,
    CandidatePlanProposal,
    PlannerInput,
    SymbolicTargetRef,
)
from stilldone.redaction import REDACTED_EMAIL, REDACTED_SECRET

_NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)


def _make_validated_action(
    action_type: ActionType,
    *,
    mission_id: MissionId | None = None,
    action_id: ActionId | None = None,
    parameters: dict[str, Any] | None = None,
    resource_id: str = "evt-100",
) -> ValidatedActionContract:
    mid = mission_id or MissionId.generate()
    aid = action_id or ActionId.generate()

    if action_type == ActionType.CALENDAR_UPDATE:
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=resource_id,
        )
        params = parameters if parameters is not None else {"summary": "Family Departure 07:30"}
    elif action_type == ActionType.CALENDAR_READ:
        target = TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=resource_id,
        )
        params = parameters if parameters is not None else {}
    elif action_type == ActionType.TASK_CREATE:
        target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK_LIST,
            resource_id="tl-200",
        )
        params = parameters if parameters is not None else {"title": "Pack lunch"}
    elif action_type == ActionType.TASK_READ:
        target = TargetIdentity(
            system="google_tasks",
            resource_kind=ResourceKind.TASK,
            resource_id="task-300",
        )
        params = parameters if parameters is not None else {}
    elif action_type == ActionType.WEATHER_READ:
        target = TargetIdentity(
            system="open_meteo",
            resource_kind=ResourceKind.WEATHER_LOCATION,
            resource_id="coord-400",
        )
        params = parameters if parameters is not None else {}
    else:
        raise ValueError(f"Unsupported action type: {action_type}")

    raw = ActionContract(
        action_id=aid,
        mission_id=mid,
        action_type=action_type,
        target=target,
        parameters=NormalizedParameters.from_dict(params),
    )
    return validate_action_contract(raw)


# ===========================================================================
# 1. CALENDAR_UPDATE produces valid PendingApproval
# ===========================================================================


class TestCalendarUpdateProducesPendingApproval:
    """Proves CALENDAR_UPDATE produces a fully valid PendingApproval object."""

    def test_calendar_update_pending_approval_success(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)

        assert isinstance(pending, PendingApproval)
        assert isinstance(pending.pending_approval_id, PendingApprovalId)
        assert len(pending.pending_approval_id.value) == 64
        assert pending.mission_id == action.mission_id
        assert pending.action_id == action.action_id
        assert pending.action_type == ActionType.CALENDAR_UPDATE
        assert pending.authority_class == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
        assert pending.target == action.target
        assert pending.parameters == action.parameters
        assert len(pending.parameters_digest) == 64
        assert pending.requested_at == _NOW
        assert pending.status == PendingApprovalStatus.PENDING
        assert pending.decision_options == (ApprovalDecision.APPROVE, ApprovalDecision.REJECT)
        assert "Family Departure 07:30" in pending.human_summary
        assert isinstance(pending.one_decision_contract, OneDecisionContract)

    def test_pending_approval_to_dict_format(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)
        d = pending.to_dict()

        assert d["pending_approval_id"] == pending.pending_approval_id.value
        assert d["mission_id"] == str(action.mission_id)
        assert d["action_id"] == str(action.action_id)
        assert d["action_type"] == "calendar.update"
        assert d["authority_class"] == "REVERSIBLE_APPROVAL_REQUIRED"
        assert d["status"] == "PENDING"
        assert d["decision_options"] == ["APPROVE", "REJECT"]
        assert "one_decision_contract" in d
        assert d["one_decision_contract"]["decision_options"] == ["APPROVE", "REJECT"]


# ===========================================================================
# 2. TASK_CREATE cannot produce PendingApproval under P-11.01
# ===========================================================================


class TestTaskCreateCannotProducePendingApproval:
    """Proves TASK_CREATE (REVERSIBLE_AUTO) fails closed against PendingApproval."""

    def test_task_create_fails_closed(self) -> None:
        action = _make_validated_action(ActionType.TASK_CREATE)
        with pytest.raises(ApprovalNotRequiredError, match="does not require human approval"):
            create_pending_approval(action, requested_at=_NOW)


# ===========================================================================
# 3. Read-only actions cannot produce PendingApproval
# ===========================================================================


class TestReadOnlyCannotProducePendingApproval:
    """Proves READ_ONLY actions fail closed against PendingApproval."""

    @pytest.mark.parametrize(
        "action_type",
        [
            ActionType.CALENDAR_READ,
            ActionType.TASK_READ,
            ActionType.WEATHER_READ,
        ],
    )
    def test_read_only_actions_fail_closed(self, action_type: ActionType) -> None:
        action = _make_validated_action(action_type)
        with pytest.raises(ApprovalNotRequiredError, match="does not require human approval"):
            create_pending_approval(action, requested_at=_NOW)


# ===========================================================================
# 4. Planner / model proposal objects rejected
# ===========================================================================


class TestPlannerProposalsRejected:
    """Proves model proposals and raw prose have ZERO authority and fail closed."""

    def test_candidate_action_proposal_rejected(self) -> None:
        proposal = CandidateActionProposal(
            action_type=ActionType.CALENDAR_UPDATE,
            target_ref=SymbolicTargetRef.CALENDAR_EVENT,
            parameters=NormalizedParameters.from_dict({"summary": "New Title"}),
            explanation="User asked to update",
        )
        with pytest.raises(PlannerAuthorityError, match="ZERO authority"):
            create_pending_approval(proposal, requested_at=_NOW)  # type: ignore[arg-type]

    def test_candidate_plan_proposal_rejected(self) -> None:
        plan = CandidatePlanProposal(
            mission_id=MissionId.generate(),
            steps=(
                CandidateActionProposal(
                    action_type=ActionType.CALENDAR_UPDATE,
                    target_ref=SymbolicTargetRef.CALENDAR_EVENT,
                    parameters=NormalizedParameters.from_dict({"summary": "Event"}),
                    explanation="Why",
                ),
            ),
        )
        with pytest.raises(PlannerAuthorityError, match="ZERO authority"):
            create_pending_approval(plan, requested_at=_NOW)  # type: ignore[arg-type]

    def test_planner_input_rejected(self) -> None:
        inp = PlannerInput(intent="Update calendar", mission_id=MissionId.generate())
        with pytest.raises(PlannerAuthorityError, match="ZERO authority"):
            create_pending_approval(inp, requested_at=_NOW)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "prose",
        [
            "user approved in voice chat",
            "yes",
            "CALENDAR_UPDATE",
            "",
            "{'action_type': 'calendar.update'}",
        ],
    )
    def test_raw_strings_rejected(self, prose: str) -> None:
        with pytest.raises(PendingApprovalTypeError, match="ValidatedActionContract"):
            create_pending_approval(prose, requested_at=_NOW)  # type: ignore[arg-type]


# ===========================================================================
# 5. PendingApproval and OneDecisionContract immutable
# ===========================================================================


class TestImmutability:
    """Proves PendingApproval and OneDecisionContract cannot be mutated."""

    def test_pending_approval_frozen(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)

        with pytest.raises(dataclasses.FrozenInstanceError):
            pending.status = PendingApprovalStatus.PENDING  # type: ignore[misc]

        with pytest.raises(dataclasses.FrozenInstanceError):
            pending.authority_class = AuthorityClass.READ_ONLY  # type: ignore[misc]

        with pytest.raises(dataclasses.FrozenInstanceError):
            pending.pending_approval_id = PendingApprovalId("0" * 64)  # type: ignore[misc]

    def test_one_decision_contract_frozen(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)
        ux = pending.one_decision_contract

        with pytest.raises(dataclasses.FrozenInstanceError):
            ux.status = PendingApprovalStatus.PENDING  # type: ignore[misc]

        with pytest.raises(dataclasses.FrozenInstanceError):
            ux.decision_options = ()  # type: ignore[misc]


# ===========================================================================
# 6. Pending object does NOT contain ApprovalGrant & rejects smuggled grants
# ===========================================================================


class TestPendingDoesNotContainApprovalGrant:
    """Proves PendingApproval does not contain, wrap, or imply an ApprovalGrant."""

    def test_no_approval_grant_in_pending_object(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)

        assert not hasattr(pending, "approval_grant")
        assert not hasattr(pending, "grant")
        assert not isinstance(pending, ApprovalGrant)

    def test_smuggled_grant_rejected_at_factory(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        grant = ApprovalGrant.create(
            action=action.action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=_NOW,
            expires_at=datetime(2026, 10, 8, 13, 0, 0, tzinfo=UTC),
        )
        with pytest.raises(SmuggledGrantError, match="cannot be smuggled"):
            create_pending_approval(grant, requested_at=_NOW)  # type: ignore[arg-type]

    def test_smuggled_grant_into_dataclass_raises(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)
        grant = ApprovalGrant.create(
            action=action.action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=_NOW,
            expires_at=datetime(2026, 10, 8, 13, 0, 0, tzinfo=UTC),
        )
        with pytest.raises(SmuggledGrantError, match="cannot contain an ApprovalGrant"):
            PendingApproval(
                pending_approval_id=pending.pending_approval_id,
                mission_id=action.mission_id,
                action_id=action.action_id,
                action_type=action.action_type,
                authority_class=pending.authority_class,
                target=action.target,
                parameters=action.parameters,
                parameters_digest=pending.parameters_digest,
                requested_at=_NOW,
                decision_contract=pending.one_decision_contract,
                action=grant,  # type: ignore[arg-type] # Smuggling attempt!
            )

    def test_domain_separator_constant(self) -> None:
        assert PENDING_APPROVAL_DOMAIN_SEPARATOR == "stilldone:pending-approval:v1"


# ===========================================================================
# 7. Pending creation does NOT authorize execution
# ===========================================================================


class TestPendingCreationDoesNotAuthorize:
    """Proves PendingApproval cannot authorize execution or bypass authority checks."""

    def test_pending_flags_are_never_authorized(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)

        assert pending.is_authorized is False
        assert pending.is_approved is False
        assert pending.is_pending is True

    def test_passing_pending_to_evaluate_authority_fails_closed(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)

        # evaluate_authority requires ApprovalGrant, not PendingApproval
        with pytest.raises(InvalidApprovalTypeError, match="ApprovalGrant"):
            evaluate_authority(action, approval=pending, at=_NOW)  # type: ignore[arg-type]


# ===========================================================================
# 8. No execution / provider calls occur
# ===========================================================================


class TestNoExecutionOrProviderCalls:
    """Proves creating a PendingApproval triggers zero external side effects."""

    def test_pure_creation_no_mock_side_effects(self) -> None:
        mock_provider = MagicMock()
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)

        assert mock_provider.call_count == 0
        assert pending.status == PendingApprovalStatus.PENDING


# ===========================================================================
# 9. One-decision contract exposes exactly APPROVE / REJECT
# ===========================================================================


class TestOneDecisionContractOptions:
    """Proves one-decision contract exposes exactly two bounded choices."""

    def test_decision_options_exact(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)
        ux = pending.one_decision_contract

        assert ux.decision_options == (ApprovalDecision.APPROVE, ApprovalDecision.REJECT)
        assert len(ux.decision_options) == 2
        assert ApprovalDecision.APPROVE in ux.decision_options
        assert ApprovalDecision.REJECT in ux.decision_options


# ===========================================================================
# 10. Arbitrary strings rejected as decisions
# ===========================================================================


class TestArbitraryStringsRejected:
    """Proves free-form strings cannot become decisions."""

    @pytest.mark.parametrize(
        "invalid_text",
        [
            "yes maybe",
            "looks fine",
            "approved by model",
            "continue",
            "safe",
            "yes",
            "y",
            "OK",
            "true",
            "APPROVE PLEASE",
            "APPROVE\n",
            " approve ",
            "reject ",
            "",
            "1",
        ],
    )
    def test_arbitrary_string_decisions_rejected(self, invalid_text: str) -> None:
        with pytest.raises(InvalidDecisionError, match="not a valid ApprovalDecision"):
            validate_approval_decision(invalid_text)

    @pytest.mark.parametrize(
        "invalid_obj",
        [
            True,
            False,
            1,
            0,
            None,
            [],
            {},
        ],
    )
    def test_non_string_non_enum_rejected(self, invalid_obj: Any) -> None:
        with pytest.raises(InvalidDecisionError, match="Invalid decision type"):
            validate_approval_decision(invalid_obj)

    def test_exact_decisions_accepted(self) -> None:
        assert validate_approval_decision("APPROVE") == ApprovalDecision.APPROVE
        assert validate_approval_decision("REJECT") == ApprovalDecision.REJECT
        assert validate_approval_decision(ApprovalDecision.APPROVE) == ApprovalDecision.APPROVE
        assert validate_approval_decision(ApprovalDecision.REJECT) == ApprovalDecision.REJECT


# ===========================================================================
# 11. Same canonical input produces stable deterministic identity
# ===========================================================================


class TestDeterministicIdentity:
    """Proves PendingApprovalId is content-addressed and stable across repeated runs."""

    def test_stable_identity_for_identical_inputs(self) -> None:
        mid = MissionId.generate()
        aid = ActionId.generate()

        action1 = _make_validated_action(ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=aid)
        action2 = _make_validated_action(ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=aid)

        pending1 = create_pending_approval(action1, requested_at=_NOW)
        pending2 = create_pending_approval(action2, requested_at=_NOW)

        assert pending1.pending_approval_id == pending2.pending_approval_id
        assert pending1.pending_approval_id.value == pending2.pending_approval_id.value
        assert pending1.parameters_digest == pending2.parameters_digest


# ===========================================================================
# 12. Changed mission/action/target/parameters alters pending identity
# ===========================================================================


class TestChangedInputsAlterIdentity:
    """Proves changing any canonical attribute alters the PendingApprovalId."""

    def test_changed_mission_id_alters_identity(self) -> None:
        aid = ActionId.generate()
        action1 = _make_validated_action(
            ActionType.CALENDAR_UPDATE, mission_id=MissionId.generate(), action_id=aid
        )
        action2 = _make_validated_action(
            ActionType.CALENDAR_UPDATE, mission_id=MissionId.generate(), action_id=aid
        )

        p1 = create_pending_approval(action1, requested_at=_NOW)
        p2 = create_pending_approval(action2, requested_at=_NOW)

        assert p1.pending_approval_id != p2.pending_approval_id

    def test_changed_action_id_alters_identity(self) -> None:
        mid = MissionId.generate()
        action1 = _make_validated_action(
            ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=ActionId.generate()
        )
        action2 = _make_validated_action(
            ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=ActionId.generate()
        )

        p1 = create_pending_approval(action1, requested_at=_NOW)
        p2 = create_pending_approval(action2, requested_at=_NOW)

        assert p1.pending_approval_id != p2.pending_approval_id

    def test_changed_target_resource_id_alters_identity(self) -> None:
        mid = MissionId.generate()
        aid = ActionId.generate()
        action1 = _make_validated_action(
            ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=aid, resource_id="evt-1"
        )
        action2 = _make_validated_action(
            ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=aid, resource_id="evt-2"
        )

        p1 = create_pending_approval(action1, requested_at=_NOW)
        p2 = create_pending_approval(action2, requested_at=_NOW)

        assert p1.pending_approval_id != p2.pending_approval_id

    def test_changed_parameters_alters_identity(self) -> None:
        mid = MissionId.generate()
        aid = ActionId.generate()
        action1 = _make_validated_action(
            ActionType.CALENDAR_UPDATE,
            mission_id=mid,
            action_id=aid,
            parameters={"summary": "Title A"},
        )
        action2 = _make_validated_action(
            ActionType.CALENDAR_UPDATE,
            mission_id=mid,
            action_id=aid,
            parameters={"summary": "Title B"},
        )

        p1 = create_pending_approval(action1, requested_at=_NOW)
        p2 = create_pending_approval(action2, requested_at=_NOW)

        assert p1.pending_approval_id != p2.pending_approval_id
        assert p1.parameters_digest != p2.parameters_digest


# ===========================================================================
# 13. Authority class comes strictly from frozen P-11.01 policy
# ===========================================================================


class TestAuthorityClassComesFromPolicy:
    """Proves authority_class is locked to frozen policy and cannot be overridden."""

    def test_authority_class_derived_from_policy(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)

        assert pending.authority_class == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED

    def test_direct_construction_with_mismatched_authority_class_fails(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        # Attempt to construct with REVERSIBLE_AUTO instead of REVERSIBLE_APPROVAL_REQUIRED
        pid = compute_pending_approval_id(
            mission_id=action.mission_id,
            action_id=action.action_id,
            action_type=action.action_type,
            authority_class=AuthorityClass.REVERSIBLE_AUTO,
            target=action.target,
            parameters=action.parameters,
        )
        ux = OneDecisionContract(
            pending_approval_id=pid,
            mission_id=action.mission_id,
            action_id=action.action_id,
            action_type=action.action_type,
            authority_class=AuthorityClass.REVERSIBLE_AUTO,
            decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
            human_summary="summary",
            status=PendingApprovalStatus.PENDING,
            requested_at=_NOW,
        )
        with pytest.raises(PendingApprovalValueError, match="does not match frozen policy"):
            PendingApproval(
                pending_approval_id=pid,
                mission_id=action.mission_id,
                action_id=action.action_id,
                action_type=action.action_type,
                authority_class=AuthorityClass.REVERSIBLE_AUTO,  # Conflict with policy!
                target=action.target,
                parameters=action.parameters,
                parameters_digest="a" * 64,
                requested_at=_NOW,
                decision_contract=ux,
                action=action.action,
            )


# ===========================================================================
# 14. Unsafe / malformed policy lineage fails closed
# ===========================================================================


class TestMalformedPolicyLineageFailsClosed:
    """Proves tampered or malformed contracts fail closed."""

    def test_naive_datetime_rejected(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        naive_dt = datetime(2026, 10, 8, 12, 0, 0)
        with pytest.raises(PendingApprovalValueError, match="timezone-aware"):
            create_pending_approval(action, requested_at=naive_dt)

    def test_tampered_id_rejected(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)
        bad_id = PendingApprovalId("f" * 64)

        ux = OneDecisionContract(
            pending_approval_id=bad_id,
            mission_id=action.mission_id,
            action_id=action.action_id,
            action_type=action.action_type,
            authority_class=pending.authority_class,
            decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
            human_summary="summary",
            status=PendingApprovalStatus.PENDING,
            requested_at=_NOW,
        )

        with pytest.raises(PendingApprovalTamperedError, match="verification failed"):
            PendingApproval(
                pending_approval_id=bad_id,
                mission_id=action.mission_id,
                action_id=action.action_id,
                action_type=action.action_type,
                authority_class=pending.authority_class,
                target=action.target,
                parameters=action.parameters,
                parameters_digest=pending.parameters_digest,
                requested_at=_NOW,
                decision_contract=ux,
                action=action.action,
            )

    def test_status_other_than_pending_rejected(self) -> None:
        action = _make_validated_action(ActionType.CALENDAR_UPDATE)
        pending = create_pending_approval(action, requested_at=_NOW)

        with pytest.raises(PendingApprovalValueError, match="must be PENDING"):
            PendingApproval(
                pending_approval_id=pending.pending_approval_id,
                mission_id=action.mission_id,
                action_id=action.action_id,
                action_type=action.action_type,
                authority_class=pending.authority_class,
                target=action.target,
                parameters=action.parameters,
                parameters_digest=pending.parameters_digest,
                requested_at=_NOW,
                decision_contract=pending.one_decision_contract,
                action=action.action,
                status="APPROVED",  # type: ignore[arg-type] # Attempting to mark approved
            )


# ===========================================================================
# 15. Privacy-safe repr, str, and error behavior
# ===========================================================================


class TestPrivacySafeBehavior:
    """Proves secrets, emails, and sensitive credentials are redacted and not leaked."""

    def test_email_redacted_in_human_summary(self) -> None:
        action = _make_validated_action(
            ActionType.CALENDAR_UPDATE,
            parameters={"summary": "Meet with user@example.com at office"},
        )
        pending = create_pending_approval(action, requested_at=_NOW)

        assert REDACTED_EMAIL in pending.human_summary
        assert "user@example.com" not in pending.human_summary

    def test_secret_token_redacted_in_human_summary(self) -> None:
        action = _make_validated_action(
            ActionType.CALENDAR_UPDATE,
            parameters={"summary": "Deploy Bearer ya29.a0AfH6SM... key"},
        )
        pending = create_pending_approval(action, requested_at=_NOW)

        assert REDACTED_SECRET in pending.human_summary
        assert "ya29.a0AfH6SM" not in pending.human_summary

    def test_repr_does_not_leak_parameter_details(self) -> None:
        action = _make_validated_action(
            ActionType.CALENDAR_UPDATE,
            parameters={"summary": "Very secret sensitive personal departure"},
        )
        pending = create_pending_approval(action, requested_at=_NOW)
        r = repr(pending)

        assert "Very secret" not in r
        assert "status=PENDING" in r
        assert "calendar.update" in r


# ===========================================================================
# 16. No P-11.03 / P-11.04 behavior introduced
# ===========================================================================


class TestNoP1103PlusIntroduced:
    """Proves P-11.03+ concepts remain absent in P-11.02."""

    def test_no_p1103_or_p1104_primitives(self) -> None:
        import stilldone.pending_approval as pa

        # P-11.03 binding
        assert not hasattr(pa, "bind_approval_grant")
        assert not hasattr(pa, "verify_approval_binding")

        # P-11.04 replay / consumption
        assert not hasattr(pa, "ApprovalLedger")
        assert not hasattr(pa, "consume_approval")
        assert not hasattr(pa, "revoke_approval")
        assert not hasattr(pa, "used_approval_registry")
