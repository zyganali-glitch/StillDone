"""Focused tests for P-02.05 authority classes, approval grants, and binding hashes."""

from __future__ import annotations

import sys
import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    APPROVAL_BINDING_DOMAIN_SEPARATOR,
    ApprovalGrant,
    ApprovalId,
    AuthorityClass,
    BindingHash,
    compute_approval_binding_hash,
)
from stilldone.domain.mission import MissionId


def _sample_action(
    *,
    mission_id: MissionId | None = None,
    action_id: ActionId | None = None,
    action_type: ActionType = ActionType.CALENDAR_UPDATE,
    parameters: dict[str, str | int] | None = None,
    system: str = "google_calendar",
    resource_kind: ResourceKind = ResourceKind.CALENDAR_EVENT,
    resource_id: str = "evt-123",
    parent_id: str | None = "cal-demo",
) -> ActionContract:
    mid = mission_id if mission_id is not None else MissionId.generate()
    aid = action_id if action_id is not None else ActionId.generate()
    params = parameters if parameters is not None else {"start_time": "07:30"}
    target = TargetIdentity(
        system=system,
        resource_kind=resource_kind,
        resource_id=resource_id,
        parent_id=parent_id,
    )
    return ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=action_type,
        target=target,
        parameters=params,
    )


def test_exact_authority_vocabulary_and_metadata() -> None:
    """A. Verify exactly five canonical authority classes and pure metadata."""
    expected = {
        "READ_ONLY": (AuthorityClass.READ_ONLY, False),
        "REVERSIBLE_AUTO": (AuthorityClass.REVERSIBLE_AUTO, False),
        "REVERSIBLE_APPROVAL_REQUIRED": (AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED, True),
        "EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED": (
            AuthorityClass.EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED,
            True,
        ),
        "IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED": (
            AuthorityClass.IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED,
            True,
        ),
    }

    assert len(AuthorityClass) == 5
    for name, (member, req_human) in expected.items():
        assert AuthorityClass(name) == member
        assert member.value == name
        assert member.requires_human_approval is req_human

    # Unsupported class rejected
    for bad_class in ["ADMIN", "AUTO", "OVERRIDE", "DANGEROUS"]:
        with pytest.raises(ValueError, match="is not a valid AuthorityClass"):
            AuthorityClass(bad_class)


def test_approval_id_semantics() -> None:
    """B. Verify ApprovalId generation and validation."""
    aid = ApprovalId.generate()
    assert isinstance(aid.value, str)
    parsed = uuid.UUID(aid.value)
    assert parsed.version == 4
    assert str(aid) == aid.value

    # Parse valid string and UUID
    raw = uuid.uuid4()
    assert ApprovalId(str(raw)) == ApprovalId(raw)  # type: ignore[arg-type]

    # Rejection of malformed values
    with pytest.raises(ValueError, match="Invalid ApprovalId format"):
        ApprovalId("yes")

    with pytest.raises(ValueError, match="Invalid ApprovalId format"):
        ApprovalId("")

    with pytest.raises(TypeError, match="ApprovalId value must be a string or UUID instance"):
        ApprovalId(12345)  # type: ignore[arg-type]


def test_immutability() -> None:
    """C. Verify ApprovalGrant and BindingHash objects cannot be mutated."""
    action = _sample_action()
    now = datetime.now(UTC)
    expiry = now + timedelta(minutes=15)
    grant = ApprovalGrant.create(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=now,
        expires_at=expiry,
    )

    with pytest.raises(FrozenInstanceError):
        grant.authority_class = AuthorityClass.READ_ONLY  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        grant.expires_at = expiry + timedelta(hours=1)  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        grant.binding_hash.value = "a" * 64  # type: ignore[misc]


def test_timestamps_validation_and_canonicalization() -> None:
    """D. Verify timezone-awareness required, UTC normalized, and expires_at > issued_at."""
    action = _sample_action()
    now_utc = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    naive_dt = datetime(2026, 9, 29, 12, 0, 0)
    aware_plus3 = datetime(2026, 9, 29, 15, 30, 0, tzinfo=timezone(timedelta(hours=3)))

    # Naive timestamps rejected
    with pytest.raises(ValueError, match="issued_at must be timezone-aware"):
        ApprovalGrant.create(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=naive_dt,
            expires_at=now_utc + timedelta(minutes=10),
        )

    with pytest.raises(ValueError, match="expires_at must be timezone-aware"):
        ApprovalGrant.create(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now_utc,
            expires_at=naive_dt,
        )

    # expires_at <= issued_at rejected
    with pytest.raises(ValueError, match="must be strictly later than issued_at"):
        ApprovalGrant.create(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now_utc,
            expires_at=now_utc,
        )

    with pytest.raises(ValueError, match="must be strictly later than issued_at"):
        ApprovalGrant.create(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now_utc,
            expires_at=now_utc - timedelta(seconds=1),
        )

    # Aware timestamp canonicalized to UTC
    grant = ApprovalGrant.create(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=aware_plus3,
        expires_at=aware_plus3 + timedelta(minutes=10),
    )
    assert grant.issued_at.tzinfo == UTC
    assert grant.issued_at.hour == 12
    assert grant.issued_at.minute == 30
    assert grant.expires_at.tzinfo == UTC


def test_expiry_boundary_semantics() -> None:
    """E. Verify pure expiry checks: strictly before = valid, >= expires_at = expired."""
    action = _sample_action()
    issued_at = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    expires_at = datetime(2026, 9, 29, 12, 15, 0, tzinfo=UTC)
    grant = ApprovalGrant.create(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # Immediately before expiry is valid
    just_before = expires_at - timedelta(microseconds=1)
    assert not grant.is_expired(just_before)

    # Exactly at boundary is expired
    assert grant.is_expired(expires_at)

    # After boundary is expired
    just_after = expires_at + timedelta(seconds=1)
    assert grant.is_expired(just_after)

    # Naive timestamp in check is rejected
    with pytest.raises(ValueError, match="timezone-aware"):
        grant.is_expired(datetime(2026, 9, 29, 12, 10, 0))


def test_hash_determinism() -> None:
    """F. Verify same inputs produce identical SHA-256 binding hashes."""
    action = _sample_action()
    issued_at = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    expires_at = datetime(2026, 9, 29, 12, 15, 0, tzinfo=UTC)

    hash1 = compute_approval_binding_hash(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    hash2 = compute_approval_binding_hash(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    assert hash1 == hash2
    assert len(hash1.value) == 64
    assert str(hash1) == hash1.value


def test_parameter_order_independence() -> None:
    """G. Verify equivalent parameters in different orders yield identical binding hashes."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="demo-list",
    )
    issued_at = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    expires_at = datetime(2026, 9, 29, 12, 15, 0, tzinfo=UTC)

    action1 = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.TASK_CREATE,
        target=target,
        parameters={"zeta": 1, "alpha": "test", "beta": True},
    )
    action2 = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.TASK_CREATE,
        target=target,
        parameters={"alpha": "test", "beta": True, "zeta": 1},
    )

    hash1 = compute_approval_binding_hash(
        action=action1,
        authority_class=AuthorityClass.REVERSIBLE_AUTO,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    hash2 = compute_approval_binding_hash(
        action=action2,
        authority_class=AuthorityClass.REVERSIBLE_AUTO,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    assert hash1 == hash2


def test_tamper_sensitivity_across_all_fields() -> None:
    """H. Verify hash changes if any bound semantic field changes individually."""
    mid = MissionId.generate()
    aid = ActionId.generate()
    target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-1",
        parent_id="cal-1",
    )
    params = {"start_time": "07:30"}
    issued_at = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    expires_at = datetime(2026, 9, 29, 12, 15, 0, tzinfo=UTC)

    base_action = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=target,
        parameters=params,
    )
    base_hash = compute_approval_binding_hash(
        action=base_action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 1. mission_id changed
    a_diff_mission = ActionContract.create(
        action_id=aid,
        mission_id=MissionId.generate(),
        action_type=ActionType.CALENDAR_UPDATE,
        target=target,
        parameters=params,
    )
    assert base_hash != compute_approval_binding_hash(
        action=a_diff_mission,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 2. action_id changed
    a_diff_aid = ActionContract.create(
        action_id=ActionId.generate(),
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=target,
        parameters=params,
    )
    assert base_hash != compute_approval_binding_hash(
        action=a_diff_aid,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 3. action_type changed
    a_diff_type = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.CALENDAR_READ,
        target=target,
        parameters=params,
    )
    assert base_hash != compute_approval_binding_hash(
        action=a_diff_type,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 4. parameter value changed
    a_diff_val = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=target,
        parameters={"start_time": "08:00"},
    )
    assert base_hash != compute_approval_binding_hash(
        action=a_diff_val,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 5. parameter key set changed
    a_diff_keys = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=target,
        parameters={"start_time": "07:30", "extra": "param"},
    )
    assert base_hash != compute_approval_binding_hash(
        action=a_diff_keys,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 6. target system changed
    t_diff_sys = TargetIdentity(
        system="other_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-1",
        parent_id="cal-1",
    )
    a_diff_sys = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=t_diff_sys,
        parameters=params,
    )
    assert base_hash != compute_approval_binding_hash(
        action=a_diff_sys,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 7. target resource_kind changed
    t_diff_kind = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="evt-1",
        parent_id="cal-1",
    )
    a_diff_kind = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=t_diff_kind,
        parameters=params,
    )
    assert base_hash != compute_approval_binding_hash(
        action=a_diff_kind,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 8. target resource_id changed
    t_diff_rid = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-2",
        parent_id="cal-1",
    )
    a_diff_rid = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=t_diff_rid,
        parameters=params,
    )
    assert base_hash != compute_approval_binding_hash(
        action=a_diff_rid,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 9. target parent_id changed
    t_diff_parent = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-1",
        parent_id="cal-2",
    )
    a_diff_parent = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=t_diff_parent,
        parameters=params,
    )
    assert base_hash != compute_approval_binding_hash(
        action=a_diff_parent,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 10. authority_class changed
    assert base_hash != compute_approval_binding_hash(
        action=base_action,
        authority_class=AuthorityClass.REVERSIBLE_AUTO,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 11. expires_at changed
    assert base_hash != compute_approval_binding_hash(
        action=base_action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at + timedelta(seconds=1),
    )

    # 12. issued_at changed
    assert base_hash != compute_approval_binding_hash(
        action=base_action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at + timedelta(seconds=1),
        expires_at=expires_at,
    )


def test_no_free_form_approval_chat_string() -> None:
    """I. Verify a chat string 'yes' cannot satisfy the Approval contract."""
    with pytest.raises(TypeError, match="action must be an ActionContract instance"):
        ApprovalGrant.create(
            action="yes",  # type: ignore[arg-type]
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )


def test_binding_hash_validation() -> None:
    """Verify BindingHash enforces 64 lowercase hex characters."""
    valid_hex = "0123456789abcdef" * 4
    bh = BindingHash(valid_hex)
    assert bh.value == valid_hex

    # Uppercase rejected
    with pytest.raises(ValueError, match="lowercase hexadecimal"):
        BindingHash("A" * 64)

    # Wrong length rejected
    with pytest.raises(ValueError, match="exactly 64 hexadecimal characters"):
        BindingHash("abc")

    # Non-hex characters rejected
    with pytest.raises(ValueError, match="lowercase hexadecimal"):
        BindingHash("g" * 64)

    # Non-string rejected
    with pytest.raises(TypeError, match="must be a string"):
        BindingHash(12345)  # type: ignore[arg-type]


def test_killer_path_calendar_approval_binding() -> None:
    """Cross-contract test: Representative killer-path calendar update approval."""
    mission_id = MissionId.generate()
    action_id = ActionId.generate()
    event_target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_leave_for_school_123",
        parent_id="calendar_stilldone_demo",
    )
    action = ActionContract.create(
        action_id=action_id,
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_UPDATE,
        target=event_target,
        parameters={"start_time": "07:30"},
    )

    issued_at = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    expires_at = datetime(2026, 9, 29, 12, 30, 0, tzinfo=UTC)

    grant = ApprovalGrant.create(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    # 1. Binds exact existing event target and mission/action linkage
    assert grant.mission_id == mission_id
    assert grant.action_id == action_id
    assert grant.authority_class == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
    assert grant.authority_class.requires_human_approval is True
    assert isinstance(grant.approval_id, ApprovalId)
    assert isinstance(grant.binding_hash, BindingHash)

    # 2. Modifying target changes the binding hash
    tampered_target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt_unauthorized_target",
        parent_id="calendar_stilldone_demo",
    )
    tampered_action_target = ActionContract.create(
        action_id=action_id,
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_UPDATE,
        target=tampered_target,
        parameters={"start_time": "07:30"},
    )
    tampered_hash_target = compute_approval_binding_hash(
        action=tampered_action_target,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    assert grant.binding_hash != tampered_hash_target

    # 3. Modifying requested start_time changes the binding hash
    tampered_action_time = ActionContract.create(
        action_id=action_id,
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_UPDATE,
        target=event_target,
        parameters={"start_time": "08:15"},
    )
    tampered_hash_time = compute_approval_binding_hash(
        action=tampered_action_time,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    assert grant.binding_hash != tampered_hash_time

    # 4. Domain separator embedded
    assert APPROVAL_BINDING_DOMAIN_SEPARATOR == "stilldone:approval-binding:v1"


def test_direct_forgery_path_closed() -> None:
    """Verify ApprovalGrant constructor rejects arbitrary identities or omitted action."""
    action = _sample_action()
    now = datetime.now(UTC)
    expiry = now + timedelta(minutes=10)

    # Omitting action must fail
    with pytest.raises(TypeError):
        ApprovalGrant(  # type: ignore[call-arg]
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now,
            expires_at=expiry,
        )

    # Supplying arbitrary mission_id must fail
    with pytest.raises(TypeError):
        ApprovalGrant(  # type: ignore[call-arg]
            action=action,
            mission_id=MissionId.generate(),
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now,
            expires_at=expiry,
        )

    # Supplying arbitrary action_id must fail
    with pytest.raises(TypeError):
        ApprovalGrant(  # type: ignore[call-arg]
            action=action,
            action_id=ActionId.generate(),
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now,
            expires_at=expiry,
        )

    # Supplying arbitrary binding_hash must fail
    with pytest.raises(TypeError):
        ApprovalGrant(  # type: ignore[call-arg]
            action=action,
            binding_hash=BindingHash("a" * 64),
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now,
            expires_at=expiry,
        )


def test_derived_identities_and_hash_invariants() -> None:
    """Verify constructor automatically derives mission_id, action_id, and binding_hash."""
    action = _sample_action()
    issued_at = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    expires_at = datetime(2026, 9, 29, 12, 15, 0, tzinfo=UTC)

    grant = ApprovalGrant(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    assert grant.action == action
    assert grant.mission_id == action.mission_id
    assert grant.action_id == action.action_id
    expected_hash = compute_approval_binding_hash(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    assert grant.binding_hash == expected_hash
    assert isinstance(grant.approval_id, ApprovalId)


def test_arbitrary_binding_hash_injection_prevented() -> None:
    """Verify caller cannot supply arbitrary BindingHash to constructor to bypass action truth."""
    action = _sample_action()
    issued_at = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    expires_at = datetime(2026, 9, 29, 12, 15, 0, tzinfo=UTC)
    fake_hash = BindingHash("0" * 64)

    with pytest.raises(TypeError, match="unexpected keyword argument 'binding_hash'"):
        ApprovalGrant(  # type: ignore[call-arg]
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=issued_at,
            expires_at=expires_at,
            binding_hash=fake_hash,
        )


def test_no_provider_dependencies_imported() -> None:
    """J. Verify authority module does not import cloud or provider SDKs."""
    forbidden_modules = [
        "boto3",
        "botocore",
        "strands",
        "agentcore",
        "google",
        "mcp",
        "requests",
        "httpx",
        "urllib3",
    ]
    for mod in forbidden_modules:
        assert mod not in sys.modules, f"Forbidden module {mod} was imported!"
