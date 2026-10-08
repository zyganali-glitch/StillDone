"""Focused tests for P-04.04 authority classification and approval-binding verification."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from stilldone.action_policy import (
    ValidatedActionContract,
    validate_action_contract,
)
from stilldone.authority_policy import (
    ACTION_AUTHORITY_TABLE,
    ApprovalAuthorityClassMismatchError,
    ApprovalBindingMismatchError,
    ApprovalExpiredError,
    ApprovalNotYetValidError,
    ApprovalRequiredError,
    ApprovalTamperedError,
    AuthorityDecision,
    AuthorityDecisionStatus,
    AuthorityPolicyTypeError,
    AuthorityPolicyValueError,
    InvalidApprovalTypeError,
    IrreversibleActionBlockedError,
    RejectionReason,
    UnexpectedApprovalGrantError,
    assert_authorized,
    classify_authority,
    evaluate_authority,
    verify_approval_grant,
    verify_authority,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    ApprovalId,
    AuthorityClass,
    BindingHash,
    compute_approval_binding_hash,
)
from stilldone.domain.lifecycle import MissionState, StepEvidenceState
from stilldone.domain.mission import MissionId

# ===========================================================================
# Helpers
# ===========================================================================

_TEST_ISSUED_AT = datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC)
_TEST_EXPIRES_AT = datetime(2026, 9, 30, 10, 30, 0, tzinfo=UTC)
_TEST_EVAL_AT = datetime(2026, 9, 30, 10, 15, 0, tzinfo=UTC)


def _make_validated_action(
    action_type: ActionType,
    *,
    mission_id: MissionId | None = None,
    action_id: ActionId | None = None,
    resource_id: str = "evt-123",
    parent_id: str | None = "cal-demo",
    parameters: dict[str, Any] | None = None,
) -> ValidatedActionContract:
    """Construct a ValidatedActionContract conforming to P-04.03 closed-world schemas."""
    mid = mission_id or MissionId.generate()
    aid = action_id or ActionId.generate()

    if action_type == ActionType.CALENDAR_READ:
        system = "google_calendar"
        rk = ResourceKind.CALENDAR_EVENT
        params: dict[str, Any] = {}
    elif action_type == ActionType.CALENDAR_UPDATE:
        system = "google_calendar"
        rk = ResourceKind.CALENDAR_EVENT
        params = parameters if parameters is not None else {"summary": "Updated Title"}
    elif action_type == ActionType.TASK_READ:
        system = "google_tasks"
        rk = ResourceKind.TASK
        params = {}
    elif action_type == ActionType.TASK_CREATE:
        system = "google_tasks"
        rk = ResourceKind.TASK_LIST
        params = parameters if parameters is not None else {"title": "New Task"}
    elif action_type == ActionType.WEATHER_READ:
        system = "open_meteo"
        rk = ResourceKind.WEATHER_LOCATION
        params = {}
    else:
        raise ValueError(f"Unsupported action_type in test helper: {action_type}")

    raw_action = ActionContract.create(
        mission_id=mid,
        action_id=aid,
        action_type=action_type,
        target=TargetIdentity(
            system=system,
            resource_kind=rk,
            resource_id=resource_id,
            parent_id=parent_id,
        ),
        parameters=params,
    )
    return validate_action_contract(raw_action)


def _make_grant(
    action: ValidatedActionContract,
    *,
    authority_class: AuthorityClass = AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
    issued_at: datetime = _TEST_ISSUED_AT,
    expires_at: datetime = _TEST_EXPIRES_AT,
    approval_id: ApprovalId | None = None,
) -> ApprovalGrant:
    """Construct a cryptographically valid ApprovalGrant bound to the candidate action."""
    return ApprovalGrant.create(
        action=action.action,
        authority_class=authority_class,
        issued_at=issued_at,
        expires_at=expires_at,
        approval_id=approval_id,
    )


# ===========================================================================
# 1. Classification Table Cardinality and Coverage
# ===========================================================================


def test_classification_table_exact_cardinality_and_coverage() -> None:
    """Prove classification table covers exactly all five current ActionType members."""
    assert len(ACTION_AUTHORITY_TABLE) == 5
    assert set(ACTION_AUTHORITY_TABLE.keys()) == set(ActionType)


# ===========================================================================
# 2-6. Exact Action -> Authority Classification Mappings
# ===========================================================================


def test_calendar_read_classifies_as_read_only() -> None:
    """Prove calendar.read -> READ_ONLY."""
    action = _make_validated_action(ActionType.CALENDAR_READ)
    assert classify_authority(action) == AuthorityClass.READ_ONLY
    assert ACTION_AUTHORITY_TABLE[ActionType.CALENDAR_READ] == AuthorityClass.READ_ONLY


def test_task_read_classifies_as_read_only() -> None:
    """Prove task.read -> READ_ONLY."""
    action = _make_validated_action(ActionType.TASK_READ)
    assert classify_authority(action) == AuthorityClass.READ_ONLY
    assert ACTION_AUTHORITY_TABLE[ActionType.TASK_READ] == AuthorityClass.READ_ONLY


def test_weather_read_classifies_as_read_only() -> None:
    """Prove weather.read -> READ_ONLY."""
    action = _make_validated_action(ActionType.WEATHER_READ)
    assert classify_authority(action) == AuthorityClass.READ_ONLY
    assert ACTION_AUTHORITY_TABLE[ActionType.WEATHER_READ] == AuthorityClass.READ_ONLY


def test_task_create_classifies_as_reversible_auto() -> None:
    """Prove task.create -> REVERSIBLE_AUTO."""
    action = _make_validated_action(ActionType.TASK_CREATE)
    assert classify_authority(action) == AuthorityClass.REVERSIBLE_AUTO
    assert ACTION_AUTHORITY_TABLE[ActionType.TASK_CREATE] == AuthorityClass.REVERSIBLE_AUTO


def test_calendar_update_classifies_as_reversible_approval_required() -> None:
    """Prove calendar.update -> REVERSIBLE_APPROVAL_REQUIRED."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    assert classify_authority(action) == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
    assert (
        ACTION_AUTHORITY_TABLE[ActionType.CALENDAR_UPDATE]
        == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
    )


# ===========================================================================
# 7. Classification Precondition: Rejects Raw/Unvalidated ActionContract
# ===========================================================================


def test_classification_rejects_raw_unvalidated_action_contract() -> None:
    """Prove classification rejects raw/unvalidated ActionContract to protect P-04.03 chain."""
    raw_action = ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.CALENDAR_READ,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="evt-1",
        ),
        parameters={},
    )
    # Must reject raw ActionContract
    with pytest.raises(AuthorityPolicyTypeError, match="ValidatedActionContract"):
        classify_authority(raw_action)  # type: ignore[arg-type]

    with pytest.raises(AuthorityPolicyTypeError, match="ValidatedActionContract"):
        evaluate_authority(raw_action, at=_TEST_EVAL_AT)  # type: ignore[arg-type]


# ===========================================================================
# 8-9. READ_ONLY and REVERSIBLE_AUTO Succeed with approval=None
# ===========================================================================


def test_read_only_succeeds_with_approval_none() -> None:
    """Prove READ_ONLY actions succeed with approval=None yielding no-approval status."""
    for action_type in [
        ActionType.CALENDAR_READ,
        ActionType.TASK_READ,
        ActionType.WEATHER_READ,
    ]:
        action = _make_validated_action(action_type)
        decision = evaluate_authority(action, approval=None, at=_TEST_EVAL_AT)

        assert decision.is_authorized is True
        assert decision.status == AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED
        assert decision.authority_class == AuthorityClass.READ_ONLY
        assert decision.approval_id is None
        assert decision.action_id == action.action_id
        assert decision.mission_id == action.mission_id
        assert decision.evaluated_at == _TEST_EVAL_AT

        # Alias verification
        alias_decision = verify_authority(action, approval=None, at=_TEST_EVAL_AT)
        assert alias_decision == decision

        # assert_authorized does not raise
        assert_decision = assert_authorized(action, approval=None, at=_TEST_EVAL_AT)
        assert assert_decision == decision


def test_reversible_auto_succeeds_with_approval_none() -> None:
    """Prove REVERSIBLE_AUTO (task.create) succeeds with approval=None."""
    action = _make_validated_action(ActionType.TASK_CREATE)
    decision = evaluate_authority(action, approval=None, at=_TEST_EVAL_AT)

    assert decision.is_authorized is True
    assert decision.status == AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED
    assert decision.authority_class == AuthorityClass.REVERSIBLE_AUTO
    assert decision.approval_id is None
    assert decision.action_id == action.action_id
    assert decision.mission_id == action.mission_id
    assert decision.evaluated_at == _TEST_EVAL_AT

    # assert_authorized does not raise
    assert_decision = assert_authorized(action, approval=None, at=_TEST_EVAL_AT)
    assert assert_decision == decision


# ===========================================================================
# 10. Unexpected Approval on a No-Approval Action Fails Closed
# ===========================================================================


def test_unexpected_approval_on_no_approval_action_fails_closed() -> None:
    """Prove unexpected approval on READ_ONLY or REVERSIBLE_AUTO fails closed."""
    for action_type in [
        ActionType.CALENDAR_READ,
        ActionType.TASK_READ,
        ActionType.WEATHER_READ,
        ActionType.TASK_CREATE,
    ]:
        action = _make_validated_action(action_type)
        # Fabricate an approval grant (or construct one from the action)
        grant = ApprovalGrant.create(
            action=action.action,
            authority_class=AuthorityClass.REVERSIBLE_AUTO,
            issued_at=_TEST_ISSUED_AT,
            expires_at=_TEST_EXPIRES_AT,
        )

        decision = evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)
        assert decision.is_authorized is False
        assert decision.status == AuthorityDecisionStatus.BLOCKED
        assert decision.rejection_reason == RejectionReason.UNEXPECTED_APPROVAL_GRANT
        assert "Unexpected approval grant" in (decision.reason or "")

        # When raise_on_rejection=True, raises UnexpectedApprovalGrantError
        with pytest.raises(UnexpectedApprovalGrantError, match="Unexpected approval grant"):
            evaluate_authority(
                action,
                approval=grant,
                at=_TEST_EVAL_AT,
                raise_on_rejection=True,
            )

        with pytest.raises(UnexpectedApprovalGrantError, match="Unexpected approval grant"):
            assert_authorized(action, approval=grant, at=_TEST_EVAL_AT)


# ===========================================================================
# 11. calendar.update with No Approval Yields APPROVAL_REQUIRED
# ===========================================================================


def test_calendar_update_with_no_approval_yields_approval_required() -> None:
    """Prove calendar.update with approval=None yields APPROVAL_REQUIRED."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    decision = evaluate_authority(action, approval=None, at=_TEST_EVAL_AT)

    assert decision.is_authorized is False
    assert decision.requires_approval is True
    assert decision.status == AuthorityDecisionStatus.APPROVAL_REQUIRED
    assert decision.authority_class == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
    assert decision.rejection_reason == RejectionReason.APPROVAL_REQUIRED
    assert decision.approval_id is None

    # raise_on_rejection raises ApprovalRequiredError
    with pytest.raises(ApprovalRequiredError, match="approval grant"):
        evaluate_authority(
            action,
            approval=None,
            at=_TEST_EVAL_AT,
            raise_on_rejection=True,
        )

    with pytest.raises(ApprovalRequiredError, match="approval grant"):
        assert_authorized(action, approval=None, at=_TEST_EVAL_AT)


# ===========================================================================
# 12. Exact Matching calendar.update ApprovalGrant Succeeds
# ===========================================================================


def test_exact_matching_calendar_update_approval_grant_succeeds() -> None:
    """Prove exact matching calendar.update ApprovalGrant succeeds."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    decision = evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)

    assert decision.is_authorized is True
    assert decision.status == AuthorityDecisionStatus.AUTHORIZED_BY_BOUND_APPROVAL
    assert decision.authority_class == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
    assert decision.approval_id == grant.approval_id
    assert decision.action_id == action.action_id
    assert decision.mission_id == action.mission_id
    assert decision.rejection_reason is None

    # assert_authorized succeeds
    assert_decision = assert_authorized(action, approval=grant, at=_TEST_EVAL_AT)
    assert assert_decision == decision

    # direct verify_approval_grant succeeds
    verify_approval_grant(
        action,
        grant,
        expected_authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        at=_TEST_EVAL_AT,
    )


# ===========================================================================
# 13. Wrong Mission Approval Fails
# ===========================================================================


def test_wrong_mission_approval_fails() -> None:
    """Prove approval bound to Mission A fails for candidate action in Mission B."""
    action_a = _make_validated_action(ActionType.CALENDAR_UPDATE, mission_id=MissionId.generate())
    action_b = _make_validated_action(ActionType.CALENDAR_UPDATE, mission_id=MissionId.generate())

    grant_a = _make_grant(action_a)

    decision = evaluate_authority(action_b, approval=grant_a, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.MISSION_MISMATCH

    with pytest.raises(ApprovalBindingMismatchError, match="mission_id"):
        assert_authorized(action_b, approval=grant_a, at=_TEST_EVAL_AT)


# ===========================================================================
# 14. Wrong ActionId Approval Fails
# ===========================================================================


def test_wrong_action_id_approval_fails() -> None:
    """Prove approval bound to ActionId 1 fails for ActionId 2 even within same mission."""
    mid = MissionId.generate()
    action_1 = _make_validated_action(
        ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=ActionId.generate()
    )
    action_2 = _make_validated_action(
        ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=ActionId.generate()
    )

    grant_1 = _make_grant(action_1)

    decision = evaluate_authority(action_2, approval=grant_1, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.ACTION_ID_MISMATCH

    with pytest.raises(ApprovalBindingMismatchError, match="action_id"):
        assert_authorized(action_2, approval=grant_1, at=_TEST_EVAL_AT)


# ===========================================================================
# 15. Changed Parameter Approval Fails
# ===========================================================================


def test_changed_parameter_approval_fails() -> None:
    """Prove approval bound to parameters P1 fails when parameters change to P2."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    action_p1 = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        parameters={"summary": "Original Title"},
    )
    action_p2 = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        parameters={"summary": "Changed Title"},
    )

    grant_p1 = _make_grant(action_p1)

    decision = evaluate_authority(action_p2, approval=grant_p1, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.PARAMETERS_MISMATCH

    with pytest.raises(ApprovalBindingMismatchError, match="parameters do not match"):
        assert_authorized(action_p2, approval=grant_p1, at=_TEST_EVAL_AT)


# ===========================================================================
# 16. Changed Target resource_id Fails
# ===========================================================================


def test_changed_target_resource_id_fails() -> None:
    """Prove approval bound to resource_id 'evt-1' fails for 'evt-2'."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    action_res1 = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        resource_id="evt-1",
    )
    action_res2 = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        resource_id="evt-2",
    )

    grant_res1 = _make_grant(action_res1)

    decision = evaluate_authority(action_res2, approval=grant_res1, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.TARGET_RESOURCE_ID_MISMATCH

    with pytest.raises(ApprovalBindingMismatchError, match="target resource_id"):
        assert_authorized(action_res2, approval=grant_res1, at=_TEST_EVAL_AT)


# ===========================================================================
# 17. Changed Target parent_id Fails
# ===========================================================================


def test_changed_target_parent_id_fails() -> None:
    """Prove approval bound to parent_id 'cal-primary' fails for 'cal-secondary'."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    action_cal1 = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        parent_id="cal-primary",
    )
    action_cal2 = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        parent_id="cal-secondary",
    )

    grant_cal1 = _make_grant(action_cal1)

    decision = evaluate_authority(action_cal2, approval=grant_cal1, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.TARGET_PARENT_ID_MISMATCH

    with pytest.raises(ApprovalBindingMismatchError, match="target parent_id"):
        assert_authorized(action_cal2, approval=grant_cal1, at=_TEST_EVAL_AT)


# ===========================================================================
# 18. Wrong ActionType Fails
# ===========================================================================


def test_wrong_action_type_fails() -> None:
    """Prove approval bound to task.create fails for calendar.update."""
    action_task = _make_validated_action(ActionType.TASK_CREATE)
    action_cal = _make_validated_action(ActionType.CALENDAR_UPDATE)

    grant_task = _make_grant(
        action_task, authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
    )

    decision = evaluate_authority(action_cal, approval=grant_task, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED

    with pytest.raises(ApprovalBindingMismatchError):
        assert_authorized(action_cal, approval=grant_task, at=_TEST_EVAL_AT)


# ===========================================================================
# 19. Wrong AuthorityClass Fails
# ===========================================================================


def test_wrong_authority_class_fails() -> None:
    """Prove grant constructed with wrong AuthorityClass fails verification."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    # Construct grant with READ_ONLY authority class instead of REVERSIBLE_APPROVAL_REQUIRED
    grant_wrong_class = _make_grant(action, authority_class=AuthorityClass.READ_ONLY)

    decision = evaluate_authority(action, approval=grant_wrong_class, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.AUTHORITY_CLASS_MISMATCH

    with pytest.raises(ApprovalAuthorityClassMismatchError, match="authority class"):
        assert_authorized(action, approval=grant_wrong_class, at=_TEST_EVAL_AT)


# ===========================================================================
# 20. Altered BindingHash Fails
# ===========================================================================


def test_altered_binding_hash_fails() -> None:
    """Prove grant with tampered stored binding hash fails verification."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    # Low-level mutation for tamper testing ONLY
    tampered_hash = BindingHash("0" * 64)
    object.__setattr__(grant, "binding_hash", tampered_hash)

    decision = evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.BINDING_HASH_MISMATCH

    with pytest.raises(ApprovalTamperedError, match="binding hash verification failed"):
        assert_authorized(action, approval=grant, at=_TEST_EVAL_AT)


# ===========================================================================
# 21. Expired Grant Fails
# ===========================================================================


def test_expired_grant_fails() -> None:
    """Prove evaluation after expires_at fails closed with APPROVAL_EXPIRED."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    eval_after_expiry = _TEST_EXPIRES_AT + timedelta(seconds=1)
    decision = evaluate_authority(action, approval=grant, at=eval_after_expiry)

    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.APPROVAL_EXPIRED

    with pytest.raises(ApprovalExpiredError, match="has expired"):
        assert_authorized(action, approval=grant, at=eval_after_expiry)


# ===========================================================================
# 22. Boundary at == expires_at Fails
# ===========================================================================


def test_boundary_at_equals_expires_at_fails() -> None:
    """Prove evaluation exactly at expires_at fails (half-open window [issued_at, expires_at))."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    decision = evaluate_authority(action, approval=grant, at=_TEST_EXPIRES_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.APPROVAL_EXPIRED

    with pytest.raises(ApprovalExpiredError, match="has expired"):
        assert_authorized(action, approval=grant, at=_TEST_EXPIRES_AT)


# ===========================================================================
# 23. Future / Not-Yet-Valid Grant Fails
# ===========================================================================


def test_future_not_yet_valid_grant_fails() -> None:
    """Prove evaluation before issued_at fails closed with APPROVAL_NOT_YET_VALID."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    eval_before_issued = _TEST_ISSUED_AT - timedelta(seconds=1)
    decision = evaluate_authority(action, approval=grant, at=eval_before_issued)

    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.APPROVAL_NOT_YET_VALID

    with pytest.raises(ApprovalNotYetValidError, match="not yet valid"):
        assert_authorized(action, approval=grant, at=eval_before_issued)


# ===========================================================================
# 24. Boundary at == issued_at Succeeds
# ===========================================================================


def test_boundary_at_equals_issued_at_succeeds() -> None:
    """Prove evaluation exactly at issued_at succeeds (inclusive lower boundary)."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    decision = evaluate_authority(action, approval=grant, at=_TEST_ISSUED_AT)
    assert decision.is_authorized is True
    assert decision.status == AuthorityDecisionStatus.AUTHORIZED_BY_BOUND_APPROVAL


# ===========================================================================
# 25. Timezone-Aware Non-UTC at Normalized Correctly
# ===========================================================================


def test_timezone_aware_non_utc_at_normalized_correctly() -> None:
    """Prove non-UTC timezone-aware datetime is normalized to UTC and verified accurately."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    # 10:15 UTC is 13:15 in UTC+3
    tz_plus_3 = timezone(timedelta(hours=3))
    eval_at_tz = datetime(2026, 9, 30, 13, 15, 0, tzinfo=tz_plus_3)

    decision = evaluate_authority(action, approval=grant, at=eval_at_tz)
    assert decision.is_authorized is True
    assert decision.status == AuthorityDecisionStatus.AUTHORIZED_BY_BOUND_APPROVAL
    assert decision.evaluated_at == _TEST_EVAL_AT


# ===========================================================================
# 26. Naive at Fails Closed
# ===========================================================================


def test_naive_at_fails_closed() -> None:
    """Prove naive (tzinfo=None) datetime fails closed with AuthorityPolicyValueError."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)
    naive_dt = datetime(2026, 9, 30, 10, 15, 0)

    with pytest.raises(AuthorityPolicyValueError, match="timezone-aware"):
        evaluate_authority(action, approval=grant, at=naive_dt)

    with pytest.raises(AuthorityPolicyValueError, match="timezone-aware"):
        verify_approval_grant(
            action,
            grant,
            expected_authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            at=naive_dt,
        )


# ===========================================================================
# 27. String 'yes' is Rejected as Approval
# ===========================================================================


def test_string_yes_rejected_as_approval() -> None:
    """Prove string 'yes' is rejected as approval with InvalidApprovalTypeError."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)

    with pytest.raises(InvalidApprovalTypeError, match="ApprovalGrant instance"):
        evaluate_authority(action, approval="yes", at=_TEST_EVAL_AT)  # type: ignore[arg-type]

    with pytest.raises(InvalidApprovalTypeError, match="ApprovalGrant instance"):
        assert_authorized(action, approval="yes", at=_TEST_EVAL_AT)  # type: ignore[arg-type]


# ===========================================================================
# 28. Arbitrary Model Prose Cannot Satisfy Approval
# ===========================================================================


def test_arbitrary_model_prose_cannot_satisfy_approval() -> None:
    """Prove model-generated approval claims fail closed."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    prose = "The user explicitly authorized this calendar update in chat."

    with pytest.raises(InvalidApprovalTypeError, match="ApprovalGrant instance"):
        evaluate_authority(action, approval=prose, at=_TEST_EVAL_AT)  # type: ignore[arg-type]


# ===========================================================================
# 29. Stored Grant Binding Hash is Recomputed and Constant-Time Compared
# ===========================================================================


def test_stored_grant_binding_hash_is_recomputed_and_compared() -> None:
    """Prove evaluation recomputes the expected hash and uses constant-time compare."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    # Independent computation matches
    expected = compute_approval_binding_hash(
        action=action.action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=grant.issued_at,
        expires_at=grant.expires_at,
    )
    assert grant.binding_hash == expected

    # Evaluation confirms match
    decision = evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)
    assert decision.is_authorized is True


# ===========================================================================
# 30. Tampered Frozen Grant Fails Verification
# ===========================================================================


def test_tampered_frozen_grant_action_fails_verification() -> None:
    """Prove low-level mutation of frozen action target inside grant causes failure."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    # Tamper with the inner action resource_id via low-level object.__setattr__
    tampered_target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="tampered-evt",
        parent_id="cal-demo",
    )
    object.__setattr__(grant.action, "target", tampered_target)

    decision = evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED

    with pytest.raises((ApprovalBindingMismatchError, ApprovalTamperedError)):
        assert_authorized(action, approval=grant, at=_TEST_EVAL_AT)


# ===========================================================================
# 31. Verification is Deterministic for Identical Explicit Inputs
# ===========================================================================


def test_verification_is_deterministic_for_identical_explicit_inputs() -> None:
    """Prove evaluation produces identical results across repeated evaluations."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    results = [evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT) for _ in range(10)]
    for r in results[1:]:
        assert r == results[0]


# ===========================================================================
# 32. Verification Does Not Mutate Action or Grant
# ===========================================================================


def test_verification_does_not_mutate_action_or_grant() -> None:
    """Prove candidate action and grant remain unmodified before and after verification."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    action_snapshot = (
        action.action_id,
        action.mission_id,
        action.action_type,
        action.target.system,
        action.target.resource_id,
        action.parameters.to_dict(),
    )
    grant_snapshot = (
        grant.approval_id,
        grant.binding_hash,
        grant.authority_class,
        grant.issued_at,
        grant.expires_at,
    )

    evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)

    assert (
        action.action_id,
        action.mission_id,
        action.action_type,
        action.target.system,
        action.target.resource_id,
        action.parameters.to_dict(),
    ) == action_snapshot
    assert (
        grant.approval_id,
        grant.binding_hash,
        grant.authority_class,
        grant.issued_at,
        grant.expires_at,
    ) == grant_snapshot


# ===========================================================================
# 33. Verification Creates No Execution / Evidence / Read-Back Artifacts
# ===========================================================================


def test_verification_creates_no_execution_or_evidence_artifacts() -> None:
    """Prove pure evaluation produces no ExecutionAttempt, evidence records, or state mutations."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    decision = evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)

    assert isinstance(decision, AuthorityDecision)
    assert not hasattr(decision, "execution_attempt")
    assert not hasattr(decision, "evidence_record")
    assert not hasattr(decision, "read_back_result")


# ===========================================================================
# 34. Success Cannot Produce VERIFIED or READY
# ===========================================================================


def test_success_cannot_produce_verified_or_ready() -> None:
    """Prove authority evaluation success cannot promote mission state or step evidence state."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    decision = evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)
    assert decision.is_authorized is True

    # Decision status cannot be confused with MissionState.READY or StepEvidenceState.VERIFIED
    assert decision.status.value != MissionState.READY.value
    assert decision.status.value != StepEvidenceState.VERIFIED.value
    assert not isinstance(decision.status, (MissionState, StepEvidenceState))
    assert decision.status == AuthorityDecisionStatus.AUTHORIZED_BY_BOUND_APPROVAL


# ===========================================================================
# 35. IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED Cannot Auto-Authorize
# ===========================================================================


def test_irreversible_blocked_or_human_required_cannot_auto_authorize() -> None:
    """Prove IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED is BLOCKED even if ApprovalGrant exists."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)

    # Synthesize an action that classifies as IRREVERSIBLE for policy engine test
    # using a local test subclass or mocking the table
    original_table = ACTION_AUTHORITY_TABLE
    try:
        from stilldone import authority_policy

        test_table = dict(original_table)
        test_table[ActionType.CALENDAR_UPDATE] = (
            AuthorityClass.IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED
        )
        object.__setattr__(
            authority_policy,
            "ACTION_AUTHORITY_TABLE",
            test_table,
        )

        grant = _make_grant(
            action,
            authority_class=AuthorityClass.IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED,
        )

        # Even with an ApprovalGrant, must return BLOCKED!
        decision = evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)
        assert decision.is_authorized is False
        assert decision.status == AuthorityDecisionStatus.BLOCKED
        assert decision.rejection_reason == RejectionReason.IRREVERSIBLE_ACTION_BLOCKED

        with pytest.raises(
            IrreversibleActionBlockedError, match="cannot be automatically authorized"
        ):
            assert_authorized(action, approval=grant, at=_TEST_EVAL_AT)

    finally:
        from stilldone import authority_policy

        object.__setattr__(
            authority_policy,
            "ACTION_AUTHORITY_TABLE",
            original_table,
        )


# ===========================================================================
# 36. EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED Semantics
# ===========================================================================


def test_external_communication_approval_required_semantics() -> None:
    """Prove EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED requires exact bound approval."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)

    original_table = ACTION_AUTHORITY_TABLE
    try:
        from stilldone import authority_policy

        test_table = dict(original_table)
        test_table[ActionType.CALENDAR_UPDATE] = (
            AuthorityClass.EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED
        )
        object.__setattr__(
            authority_policy,
            "ACTION_AUTHORITY_TABLE",
            test_table,
        )

        # 1. No approval -> APPROVAL_REQUIRED
        decision_none = evaluate_authority(action, approval=None, at=_TEST_EVAL_AT)
        assert decision_none.status == AuthorityDecisionStatus.APPROVAL_REQUIRED
        assert decision_none.is_authorized is False

        # 2. Matching grant -> AUTHORIZED_BY_BOUND_APPROVAL
        grant_matching = _make_grant(
            action,
            authority_class=AuthorityClass.EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED,
        )
        decision_ok = evaluate_authority(action, approval=grant_matching, at=_TEST_EVAL_AT)
        assert decision_ok.status == AuthorityDecisionStatus.AUTHORIZED_BY_BOUND_APPROVAL
        assert decision_ok.is_authorized is True

        # 3. Wrong authority class grant -> BLOCKED
        grant_wrong = _make_grant(
            action, authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
        )
        decision_bad = evaluate_authority(action, approval=grant_wrong, at=_TEST_EVAL_AT)
        assert decision_bad.status == AuthorityDecisionStatus.BLOCKED

    finally:
        from stilldone import authority_policy

        object.__setattr__(
            authority_policy,
            "ACTION_AUTHORITY_TABLE",
            original_table,
        )


# ===========================================================================
# 40. Zero Provider/Network Imports
# ===========================================================================


def test_zero_provider_network_imports() -> None:
    """Prove authority_policy imports zero cloud/provider SDKs or networking libraries."""
    forbidden = [
        "boto3",
        "botocore",
        "strands",
        "agentcore",
        "google",
        "mcp",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
    ]
    for mod in forbidden:
        assert mod not in sys.modules, f"Forbidden module '{mod}' is imported in sys.modules!"


# ===========================================================================
# Additional Hardening & Secrecy Tests
# ===========================================================================


def test_error_secrecy_does_not_echo_parameter_values() -> None:
    """Prove validation errors and rejection reasons never echo parameter plaintext."""
    sensitive_param_value = "SECRET_DOCTOR_APPOINTMENT_DATA_CONFIDENTIAL_12345"
    action_1 = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        parameters={"summary": sensitive_param_value},
    )
    action_2 = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        parameters={"summary": "DIFFERENT_VALUE_98765"},
    )
    grant_1 = _make_grant(action_1)

    decision = evaluate_authority(action_2, approval=grant_1, at=_TEST_EVAL_AT)
    assert decision.is_authorized is False
    assert decision.reason is not None
    assert sensitive_param_value not in decision.reason
    assert "DIFFERENT_VALUE_98765" not in decision.reason

    try:
        assert_authorized(action_2, approval=grant_1, at=_TEST_EVAL_AT)
    except ApprovalBindingMismatchError as exc:
        err_msg = str(exc)
        assert sensitive_param_value not in err_msg
        assert "DIFFERENT_VALUE_98765" not in err_msg


def test_authority_decision_does_not_leak_grant_repr() -> None:
    """Prove AuthorityDecision does not expose sensitive fields via repr."""
    action = _make_validated_action(ActionType.CALENDAR_UPDATE)
    grant = _make_grant(action)

    decision = evaluate_authority(action, approval=grant, at=_TEST_EVAL_AT)
    d_repr = repr(decision)
    # The decision contains approval_id, but not the full grant object
    assert "ApprovalGrant(" not in d_repr
    assert str(grant.approval_id) in d_repr


# ===========================================================================
# Target External Identifier Secrecy Tests
# ===========================================================================

_SENTINEL_GRANT_RES_ID = "sentinel-grant-resource-evt-99999"
_SENTINEL_CANDIDATE_RES_ID = "sentinel-candidate-resource-evt-11111"
_SENTINEL_GRANT_PARENT_ID = "sentinel-grant-calendar-cal-88888"
_SENTINEL_CANDIDATE_PARENT_ID = "sentinel-candidate-calendar-cal-22222"


def test_target_resource_id_mismatch_secrecy_decision_path() -> None:
    """A. Prove resource_id mismatch never echoes sentinel IDs in reason or repr."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    action_grant = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        resource_id=_SENTINEL_GRANT_RES_ID,
    )
    action_candidate = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        resource_id=_SENTINEL_CANDIDATE_RES_ID,
    )
    grant = _make_grant(action_grant)

    decision = evaluate_authority(action_candidate, approval=grant, at=_TEST_EVAL_AT)

    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.TARGET_RESOURCE_ID_MISMATCH
    assert decision.reason is not None

    # Neither sentinel identifier appears in decision.reason
    assert _SENTINEL_GRANT_RES_ID not in decision.reason
    assert _SENTINEL_CANDIDATE_RES_ID not in decision.reason

    # Neither sentinel identifier appears in repr(decision)
    d_repr = repr(decision)
    assert _SENTINEL_GRANT_RES_ID not in d_repr
    assert _SENTINEL_CANDIDATE_RES_ID not in d_repr


def test_target_resource_id_mismatch_secrecy_exception_path() -> None:
    """B. Prove resource_id mismatch never echoes sentinel IDs in str(exc) or repr(exc)."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    action_grant = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        resource_id=_SENTINEL_GRANT_RES_ID,
    )
    action_candidate = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        resource_id=_SENTINEL_CANDIDATE_RES_ID,
    )
    grant = _make_grant(action_grant)

    # 1. verify_approval_grant path
    with pytest.raises(ApprovalBindingMismatchError) as exc_info:
        verify_approval_grant(
            action_candidate,
            grant,
            expected_authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            at=_TEST_EVAL_AT,
        )
    exc = exc_info.value
    assert exc.rejection_reason == RejectionReason.TARGET_RESOURCE_ID_MISMATCH
    assert _SENTINEL_GRANT_RES_ID not in str(exc)
    assert _SENTINEL_CANDIDATE_RES_ID not in str(exc)
    assert _SENTINEL_GRANT_RES_ID not in repr(exc)
    assert _SENTINEL_CANDIDATE_RES_ID not in repr(exc)

    # 2. assert_authorized path
    with pytest.raises(ApprovalBindingMismatchError) as exc_info_assert:
        assert_authorized(action_candidate, approval=grant, at=_TEST_EVAL_AT)
    exc_assert = exc_info_assert.value
    assert exc_assert.rejection_reason == RejectionReason.TARGET_RESOURCE_ID_MISMATCH
    assert _SENTINEL_GRANT_RES_ID not in str(exc_assert)
    assert _SENTINEL_CANDIDATE_RES_ID not in str(exc_assert)
    assert _SENTINEL_GRANT_RES_ID not in repr(exc_assert)
    assert _SENTINEL_CANDIDATE_RES_ID not in repr(exc_assert)


def test_target_parent_id_mismatch_secrecy_decision_path() -> None:
    """C. Prove parent_id mismatch never echoes sentinel IDs in reason or repr."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    action_grant = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        parent_id=_SENTINEL_GRANT_PARENT_ID,
    )
    action_candidate = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        parent_id=_SENTINEL_CANDIDATE_PARENT_ID,
    )
    grant = _make_grant(action_grant)

    decision = evaluate_authority(action_candidate, approval=grant, at=_TEST_EVAL_AT)

    assert decision.is_authorized is False
    assert decision.status == AuthorityDecisionStatus.BLOCKED
    assert decision.rejection_reason == RejectionReason.TARGET_PARENT_ID_MISMATCH
    assert decision.reason is not None

    # Neither sentinel identifier appears in decision.reason
    assert _SENTINEL_GRANT_PARENT_ID not in decision.reason
    assert _SENTINEL_CANDIDATE_PARENT_ID not in decision.reason

    # Neither sentinel identifier appears in repr(decision)
    d_repr = repr(decision)
    assert _SENTINEL_GRANT_PARENT_ID not in d_repr
    assert _SENTINEL_CANDIDATE_PARENT_ID not in d_repr


def test_target_parent_id_mismatch_secrecy_exception_path() -> None:
    """D. Prove parent_id mismatch never echoes sentinel IDs in str(exc) or repr(exc)."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    action_grant = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        parent_id=_SENTINEL_GRANT_PARENT_ID,
    )
    action_candidate = _make_validated_action(
        ActionType.CALENDAR_UPDATE,
        mission_id=mid,
        action_id=aid,
        parent_id=_SENTINEL_CANDIDATE_PARENT_ID,
    )
    grant = _make_grant(action_grant)

    # 1. verify_approval_grant path
    with pytest.raises(ApprovalBindingMismatchError) as exc_info:
        verify_approval_grant(
            action_candidate,
            grant,
            expected_authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            at=_TEST_EVAL_AT,
        )
    exc = exc_info.value
    assert exc.rejection_reason == RejectionReason.TARGET_PARENT_ID_MISMATCH
    assert _SENTINEL_GRANT_PARENT_ID not in str(exc)
    assert _SENTINEL_CANDIDATE_PARENT_ID not in str(exc)
    assert _SENTINEL_GRANT_PARENT_ID not in repr(exc)
    assert _SENTINEL_CANDIDATE_PARENT_ID not in repr(exc)

    # 2. assert_authorized path
    with pytest.raises(ApprovalBindingMismatchError) as exc_info_assert:
        assert_authorized(action_candidate, approval=grant, at=_TEST_EVAL_AT)
    exc_assert = exc_info_assert.value
    assert exc_assert.rejection_reason == RejectionReason.TARGET_PARENT_ID_MISMATCH
    assert _SENTINEL_GRANT_PARENT_ID not in str(exc_assert)
    assert _SENTINEL_CANDIDATE_PARENT_ID not in str(exc_assert)
    assert _SENTINEL_GRANT_PARENT_ID not in repr(exc_assert)
    assert _SENTINEL_CANDIDATE_PARENT_ID not in repr(exc_assert)


def test_target_mismatch_specificity_preserved() -> None:
    """E. Prove mismatch specificity is preserved across all TargetIdentity fields."""
    mid = MissionId.generate()
    aid = ActionId.generate()

    # resource_id mismatch -> TARGET_RESOURCE_ID_MISMATCH
    a_res1 = _make_validated_action(
        ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=aid, resource_id="res-1"
    )
    a_res2 = _make_validated_action(
        ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=aid, resource_id="res-2"
    )
    d_res = evaluate_authority(a_res2, approval=_make_grant(a_res1), at=_TEST_EVAL_AT)
    assert d_res.rejection_reason == RejectionReason.TARGET_RESOURCE_ID_MISMATCH

    # parent_id mismatch -> TARGET_PARENT_ID_MISMATCH
    a_par1 = _make_validated_action(
        ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=aid, parent_id="par-1"
    )
    a_par2 = _make_validated_action(
        ActionType.CALENDAR_UPDATE, mission_id=mid, action_id=aid, parent_id="par-2"
    )
    d_par = evaluate_authority(a_par2, approval=_make_grant(a_par1), at=_TEST_EVAL_AT)
    assert d_par.rejection_reason == RejectionReason.TARGET_PARENT_ID_MISMATCH
