"""Deterministic pending-approval object and one-decision UX contract for StillDone.

Represents:
"This exact currently proposed mutation is waiting for one human decision."

P-11.02 boundary rules:
- Derives authority facts strictly from P-11.01 frozen policy (ACTION_AUTHORITY_POLICY_TABLE).
- Accepts ONLY ValidatedActionContract (cannot bypass P-04.03 validation).
- Rejects planner / model proposal objects with zero authority fail-closed.
- Fails closed for actions whose policy does not require human approval
  (e.g. TASK_CREATE, READ_ONLY).
- Immutable, strongly typed PendingApproval domain contract.
- Pure content-addressed deterministic identity (PendingApprovalId) with domain separation.
- Exposes exactly one bounded human decision surface: APPROVE or REJECT.
- Rejects arbitrary / free-form model or conversational decision strings.
- Pending != Approved: A PendingApproval is NOT an ApprovalGrant, does NOT authorize execution,
  and does NOT mutate external state.
- Privacy-safe: sensitive parameter plaintext and credentials are never echoed
  in human summary or repr.
- No execution, provider calls, approval consumption, or replay registration.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.action_policy import ValidatedActionContract
from stilldone.authority_policy import (
    ActionAuthorityPolicy,
    assert_not_planner_for_authority,
    get_action_authority_policy,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    AuthorityClass,
)
from stilldone.domain.mission import MissionId
from stilldone.redaction import redact_text
from stilldone.serialization import canonical_serialize, to_canonical_primitive

PENDING_APPROVAL_DOMAIN_SEPARATOR: str = "stilldone:pending-approval:v1"


# ===========================================================================
# Decision and Status Enums
# ===========================================================================


class ApprovalDecision(StrEnum):
    """Closed-world human approval decision options.

    Represents the exact single decision a human operator can make.
    Arbitrary strings, conversational prose, and model proposals cannot become decisions.
    """

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class PendingApprovalStatus(StrEnum):
    """Closed-world status for a pending approval object.

    A pending approval object can only be PENDING. It is NEVER approved,
    granted, executed, or ready.
    """

    PENDING = "PENDING"


# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class PendingApprovalError(Exception):
    """Base exception for all StillDone pending approval operations."""


class PendingApprovalTypeError(PendingApprovalError, TypeError):
    """Raised when an argument has an invalid type."""


class PendingApprovalValueError(PendingApprovalError, ValueError):
    """Raised when an argument has an invalid value."""


class ApprovalNotRequiredError(PendingApprovalError, ValueError):
    """Raised when attempting to create a pending approval for an unapproved action."""


class InvalidDecisionError(PendingApprovalError, ValueError):
    """Raised when an approval decision is invalid or not in the closed-world enum."""


class PendingApprovalTamperedError(PendingApprovalError, ValueError):
    """Raised when a PendingApproval ID or fields fail cryptographic verification."""


class SmuggledGrantError(PendingApprovalError, TypeError):
    """Raised when an attempt is made to smuggle an ApprovalGrant into pending approval."""


# ===========================================================================
# Content-Addressed Identity
# ===========================================================================


@dataclass(frozen=True)
class PendingApprovalId:
    """Immutable content-addressed pending approval identifier backed by SHA-256."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise PendingApprovalTypeError(
                f"PendingApprovalId value must be a string, got {type(self.value).__name__}"
            )
        if len(self.value) != 64:
            raise PendingApprovalValueError(
                f"PendingApprovalId must be exactly 64 hex characters, got {len(self.value)}"
            )
        for char in self.value:
            if char not in "0123456789abcdef":
                raise PendingApprovalValueError(
                    f"PendingApprovalId must be lowercase hexadecimal: {self.value!r}"
                )

    def __str__(self) -> str:
        return self.value

    def to_canonical(self) -> str:
        """Return the canonical string representation for serialization."""
        return self.value


def compute_pending_approval_id(
    *,
    mission_id: MissionId | str,
    action_id: ActionId | str,
    action_type: ActionType | str,
    authority_class: AuthorityClass | str,
    target: TargetIdentity,
    parameters: NormalizedParameters,
    domain: str = PENDING_APPROVAL_DOMAIN_SEPARATOR,
) -> PendingApprovalId:
    """Compute a deterministic, domain-separated SHA-256 PendingApprovalId.

    Binds:
    - Domain separator ("stilldone:pending-approval:v1")
    - Mission ID
    - Action ID
    - Action Type
    - Authority Class
    - Complete TargetIdentity (system, resource_kind, resource_id, parent_id)
    - Normalized parameters (sorted, canonical)
    """
    if not isinstance(target, TargetIdentity):
        raise PendingApprovalTypeError(
            f"target must be a TargetIdentity instance, got {type(target).__name__}"
        )
    if not isinstance(parameters, NormalizedParameters):
        raise PendingApprovalTypeError(
            f"parameters must be a NormalizedParameters instance, got {type(parameters).__name__}"
        )

    act_type = action_type if isinstance(action_type, ActionType) else ActionType(action_type)
    auth_class = (
        authority_class
        if isinstance(authority_class, AuthorityClass)
        else AuthorityClass(authority_class)
    )

    envelope: dict[str, Any] = {
        "_domain": domain,
        "action_id": str(action_id),
        "action_type": str(act_type.value),
        "authority_class": str(auth_class.value),
        "mission_id": str(mission_id),
        "parameters": to_canonical_primitive(parameters.to_dict()),
        "target": {
            "parent_id": target.parent_id,
            "resource_id": target.resource_id,
            "resource_kind": str(target.resource_kind.value),
            "system": target.system,
        },
    }

    serialized_bytes = canonical_serialize(envelope)
    digest = hashlib.sha256(serialized_bytes).hexdigest()
    return PendingApprovalId(digest)


# ===========================================================================
# One-Decision UX Presentation Contract
# ===========================================================================


@dataclass(frozen=True)
class OneDecisionContract:
    """Immutable one-decision human UX presentation and data contract.

    Exposes exactly the single bounded human decision surface required:
    one human decision (APPROVE or REJECT) for this exact bounded mutation.
    Free-form model text and conversational strings cannot become decisions.
    """

    pending_approval_id: PendingApprovalId
    mission_id: MissionId
    action_id: ActionId
    action_type: ActionType
    authority_class: AuthorityClass
    decision_options: tuple[ApprovalDecision, ...]
    human_summary: str
    status: PendingApprovalStatus
    requested_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.pending_approval_id, PendingApprovalId):
            raise PendingApprovalTypeError(
                "pending_approval_id must be a PendingApprovalId instance, "
                f"got {type(self.pending_approval_id).__name__}"
            )
        if not isinstance(self.mission_id, MissionId):
            raise PendingApprovalTypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.action_id, ActionId):
            raise PendingApprovalTypeError(
                f"action_id must be an ActionId instance, got {type(self.action_id).__name__}"
            )
        if not isinstance(self.action_type, ActionType):
            raise PendingApprovalTypeError(
                f"action_type must be an ActionType instance, got {type(self.action_type).__name__}"
            )
        if not isinstance(self.authority_class, AuthorityClass):
            raise PendingApprovalTypeError(
                "authority_class must be an AuthorityClass instance, "
                f"got {type(self.authority_class).__name__}"
            )
        if not isinstance(self.decision_options, tuple):
            raise PendingApprovalTypeError(
                f"decision_options must be a tuple, got {type(self.decision_options).__name__}"
            )
        if self.decision_options != (ApprovalDecision.APPROVE, ApprovalDecision.REJECT):
            raise PendingApprovalValueError(
                f"decision_options must be exactly (APPROVE, REJECT), got {self.decision_options!r}"
            )
        if not isinstance(self.human_summary, str) or not self.human_summary.strip():
            raise PendingApprovalValueError("human_summary must be a non-empty string")
        if self.status != PendingApprovalStatus.PENDING:
            raise PendingApprovalValueError(f"status must be PENDING, got {self.status!r}")
        if not isinstance(self.requested_at, datetime):
            raise PendingApprovalTypeError(
                f"requested_at must be a datetime instance, got {type(self.requested_at).__name__}"
            )
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise PendingApprovalValueError("requested_at must be timezone-aware")

    def __repr__(self) -> str:
        return (
            f"OneDecisionContract(pending_approval_id={self.pending_approval_id.value[:12]}..., "
            f"action_type={self.action_type.value}, authority_class={self.authority_class.value}, "
            f"options={[o.value for o in self.decision_options]}, status={self.status.value})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert presentation contract to a serializable dictionary."""
        return {
            "pending_approval_id": self.pending_approval_id.value,
            "mission_id": str(self.mission_id),
            "action_id": str(self.action_id),
            "action_type": self.action_type.value,
            "authority_class": self.authority_class.value,
            "decision_options": [d.value for d in self.decision_options],
            "human_summary": self.human_summary,
            "status": self.status.value,
            "requested_at": self.requested_at.isoformat(),
        }


# ===========================================================================
# Decision Validator
# ===========================================================================


def validate_approval_decision(decision: Any) -> ApprovalDecision:
    """Validate a human decision value against the closed-world ApprovalDecision enum.

    Fails closed on arbitrary strings, model prose, conversational text, booleans, or numbers.
    Only explicit APPROVE or REJECT values are accepted.
    """
    if isinstance(decision, ApprovalDecision):
        return decision
    if isinstance(decision, str):
        if decision == ApprovalDecision.APPROVE.value:
            return ApprovalDecision.APPROVE
        if decision == ApprovalDecision.REJECT.value:
            return ApprovalDecision.REJECT
        raise InvalidDecisionError(
            f"Arbitrary decision text {decision!r} is not a valid ApprovalDecision; "
            "must be exactly APPROVE or REJECT"
        )
    raise InvalidDecisionError(
        f"Invalid decision type {type(decision).__name__}; "
        "must be an ApprovalDecision instance or exact string 'APPROVE' / 'REJECT'"
    )


# ===========================================================================
# Pending Approval Domain Entity
# ===========================================================================


@dataclass(frozen=True)
class PendingApproval:
    """Immutable deterministic pending approval object.

    Represents:
    "This exact currently proposed mutation is waiting for one human decision."

    Invariants:
    1. A PendingApproval is NOT an ApprovalGrant.
    2. Does NOT authorize execution (is_authorized is always False).
    3. Status is strictly PENDING.
    4. Derived deterministically from canonical ValidatedActionContract and P-11.01 policy.
    5. Exposes the one-decision UX contract via one_decision_contract.
    6. Does not duplicate full raw sensitive provider payloads.
    7. Fails closed against planner objects, unsupported actions, or non-approval policies.
    """

    pending_approval_id: PendingApprovalId
    mission_id: MissionId
    action_id: ActionId
    action_type: ActionType
    authority_class: AuthorityClass
    target: TargetIdentity
    parameters: NormalizedParameters
    parameters_digest: str
    requested_at: datetime
    decision_contract: OneDecisionContract
    action: ActionContract
    status: PendingApprovalStatus = PendingApprovalStatus.PENDING
    decision_options: tuple[ApprovalDecision, ...] = (
        ApprovalDecision.APPROVE,
        ApprovalDecision.REJECT,
    )

    def __post_init__(self) -> None:
        # Invariant: Smuggled grant protection
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, ApprovalGrant):
                raise SmuggledGrantError(
                    f"Field '{f.name}' cannot contain an ApprovalGrant in a PendingApproval object"
                )

        # Reject planner injection
        assert_not_planner_for_authority(self.action, parameter_name="action")

        # Type validations
        if not isinstance(self.pending_approval_id, PendingApprovalId):
            raise PendingApprovalTypeError(
                "pending_approval_id must be a PendingApprovalId instance, "
                f"got {type(self.pending_approval_id).__name__}"
            )
        if not isinstance(self.mission_id, MissionId):
            raise PendingApprovalTypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.action_id, ActionId):
            raise PendingApprovalTypeError(
                f"action_id must be an ActionId instance, got {type(self.action_id).__name__}"
            )
        if not isinstance(self.action_type, ActionType):
            raise PendingApprovalTypeError(
                f"action_type must be an ActionType instance, got {type(self.action_type).__name__}"
            )
        if not isinstance(self.authority_class, AuthorityClass):
            raise PendingApprovalTypeError(
                "authority_class must be an AuthorityClass instance, "
                f"got {type(self.authority_class).__name__}"
            )
        if not isinstance(self.target, TargetIdentity):
            raise PendingApprovalTypeError(
                f"target must be a TargetIdentity instance, got {type(self.target).__name__}"
            )
        if not isinstance(self.parameters, NormalizedParameters):
            raise PendingApprovalTypeError(
                "parameters must be a NormalizedParameters instance, "
                f"got {type(self.parameters).__name__}"
            )
        if not isinstance(self.parameters_digest, str) or len(self.parameters_digest) != 64:
            raise PendingApprovalValueError("parameters_digest must be a 64-character hex digest")
        if not isinstance(self.requested_at, datetime):
            raise PendingApprovalTypeError(
                f"requested_at must be a datetime instance, got {type(self.requested_at).__name__}"
            )
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise PendingApprovalValueError("requested_at must be timezone-aware")
        if self.status != PendingApprovalStatus.PENDING:
            raise PendingApprovalValueError(
                f"PendingApproval status must be PENDING, got {self.status!r}. "
                "A PendingApproval cannot be constructed in an approved or granted state."
            )
        if not isinstance(self.decision_contract, OneDecisionContract):
            raise PendingApprovalTypeError(
                "decision_contract must be a OneDecisionContract instance, "
                f"got {type(self.decision_contract).__name__}"
            )
        if not isinstance(self.action, ActionContract):
            raise PendingApprovalTypeError(
                f"action must be an ActionContract instance, got {type(self.action).__name__}"
            )
        if self.decision_options != (ApprovalDecision.APPROVE, ApprovalDecision.REJECT):
            raise PendingApprovalValueError(
                f"decision_options must be (APPROVE, REJECT), got {self.decision_options!r}"
            )

        # Invariant: Action lineage consistency
        if self.action.mission_id != self.mission_id:
            raise PendingApprovalValueError(
                "action.mission_id must match pending approval mission_id"
            )
        if self.action.action_id != self.action_id:
            raise PendingApprovalValueError(
                "action.action_id must match pending approval action_id"
            )
        if self.action.action_type != self.action_type:
            raise PendingApprovalValueError(
                "action.action_type must match pending approval action_type"
            )
        if self.action.target != self.target:
            raise PendingApprovalValueError("action.target must match pending approval target")
        if self.action.parameters != self.parameters:
            raise PendingApprovalValueError(
                "action.parameters must match pending approval parameters"
            )

        # Invariant: P-11.01 frozen policy check
        policy = get_action_authority_policy(self.action_type)
        if self.authority_class != policy.authority_class:
            raise PendingApprovalValueError(
                f"authority_class '{self.authority_class.value}' does not match "
                f"frozen policy authority_class '{policy.authority_class.value}'"
            )
        if not policy.requires_bound_approval or not policy.requires_human_approval:
            raise ApprovalNotRequiredError(
                f"Action '{self.action_type.value}' has authority class "
                f"'{policy.authority_class.value}' and does not require human approval"
            )

        # Invariant: Smuggled grant protection
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, ApprovalGrant):
                raise SmuggledGrantError(
                    f"Field '{f.name}' cannot contain an ApprovalGrant in a PendingApproval object"
                )

        # Invariant: Decision contract consistency
        if self.decision_contract.pending_approval_id != self.pending_approval_id:
            raise PendingApprovalValueError("decision_contract.pending_approval_id mismatch")
        if self.decision_contract.mission_id != self.mission_id:
            raise PendingApprovalValueError("decision_contract.mission_id mismatch")
        if self.decision_contract.action_id != self.action_id:
            raise PendingApprovalValueError("decision_contract.action_id mismatch")
        if self.decision_contract.action_type != self.action_type:
            raise PendingApprovalValueError("decision_contract.action_type mismatch")
        if self.decision_contract.authority_class != self.authority_class:
            raise PendingApprovalValueError("decision_contract.authority_class mismatch")

        # Invariant: Recompute and verify content-addressed pending approval ID
        expected_id = compute_pending_approval_id(
            mission_id=self.mission_id,
            action_id=self.action_id,
            action_type=self.action_type,
            authority_class=self.authority_class,
            target=self.target,
            parameters=self.parameters,
        )
        if not hmac.compare_digest(self.pending_approval_id.value, expected_id.value):
            raise PendingApprovalTamperedError(
                f"Pending approval ID verification failed: {self.pending_approval_id.value!r} "
                f"!= expected {expected_id.value!r}"
            )

    @property
    def is_authorized(self) -> bool:
        """Always False. A PendingApproval does not authorize execution."""
        return False

    @property
    def is_approved(self) -> bool:
        """Always False. A PendingApproval is not an ApprovalGrant."""
        return False

    @property
    def is_pending(self) -> bool:
        """Always True. A human decision is required and not yet supplied."""
        return True

    @property
    def human_summary(self) -> str:
        """Sanitized human-facing summary from the decision contract."""
        return self.decision_contract.human_summary

    @property
    def one_decision_contract(self) -> OneDecisionContract:
        """Alias for decision_contract."""
        return self.decision_contract

    def validate_decision(self, decision: Any) -> ApprovalDecision:
        """Validate a human decision against this pending approval's closed-world options.

        Does NOT create an ApprovalGrant, authorize execution, or mutate state.
        """
        return validate_approval_decision(decision)

    def __repr__(self) -> str:
        return (
            f"PendingApproval(id={self.pending_approval_id.value[:12]}..., "
            f"mission_id={self.mission_id}, action_id={self.action_id}, "
            f"action_type={self.action_type.value}, authority_class={self.authority_class.value}, "
            f"status={self.status.value})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert pending approval object to a serializable dictionary."""
        return {
            "pending_approval_id": self.pending_approval_id.value,
            "mission_id": str(self.mission_id),
            "action_id": str(self.action_id),
            "action_type": self.action_type.value,
            "authority_class": self.authority_class.value,
            "target": {
                "parent_id": self.target.parent_id,
                "resource_id": self.target.resource_id,
                "resource_kind": self.target.resource_kind.value,
                "system": self.target.system,
            },
            "parameters": self.parameters.to_dict(),
            "parameters_digest": self.parameters_digest,
            "requested_at": self.requested_at.isoformat(),
            "status": self.status.value,
            "decision_options": [d.value for d in self.decision_options],
            "human_summary": self.human_summary,
            "one_decision_contract": self.decision_contract.to_dict(),
        }


# ===========================================================================
# Privacy-Safe Summary Helper
# ===========================================================================


def _build_human_summary(action: ValidatedActionContract) -> str:
    """Build a privacy-safe, sanitized, human-readable summary for a pending action.

    Applies deterministic redaction for secrets and emails, and never echoes
    raw provider responses, hidden metadata, or tokens.
    """
    params = action.parameters
    if action.action_type == ActionType.CALENDAR_UPDATE:
        parts: list[str] = []
        if "summary" in params:
            parts.append(f"summary={str(params['summary'])!r}")
        if "start_time" in params:
            parts.append(f"start_time={str(params['start_time'])!r}")
        if "all_day" in params:
            parts.append(f"all_day={params['all_day']}")
        param_desc = ", ".join(parts) if parts else "parameters updated"
        raw_text = (
            f"Update Google Calendar event on '{action.target.system}' "
            f"({action.target.resource_id}): {param_desc}"
        )
    else:
        raw_text = (
            f"Execute action '{action.action_type.value}' on '{action.target.system}' "
            f"target '{action.target.resource_id}'"
        )

    return redact_text(raw_text)


# ===========================================================================
# Factory Function
# ===========================================================================


def create_pending_approval(
    action: ValidatedActionContract,
    *,
    requested_at: datetime,
) -> PendingApproval:
    """Create an immutable PendingApproval object from a ValidatedActionContract.

    Derives all authority facts strictly from P-11.01 frozen policy.
    Fails closed if:
    - action is a model/planner proposal;
    - action is not a ValidatedActionContract;
    - action type does not require human approval under frozen policy;
    - requested_at is missing or naive;
    - any attempt is made to smuggle an ApprovalGrant.

    Args:
        action: Canonical ValidatedActionContract from P-04.03.
        requested_at: Explicit timezone-aware UTC datetime.

    Returns:
        Immutable PendingApproval carrying the one-decision UX contract.
    """
    # 1. Smuggling guard
    if isinstance(action, ApprovalGrant) or hasattr(action, "approval_grant"):
        raise SmuggledGrantError("ApprovalGrant cannot be smuggled into pending approval creation")

    # 2. Reject planner/model proposals fail-closed
    assert_not_planner_for_authority(action, parameter_name="action")
    if not isinstance(action, ValidatedActionContract):
        raise PendingApprovalTypeError(
            f"action must be a ValidatedActionContract instance, got {type(action).__name__}"
        )

    # 3. Validate requested_at timestamp
    if not isinstance(requested_at, datetime):
        raise PendingApprovalTypeError(
            f"requested_at must be a datetime instance, got {type(requested_at).__name__}"
        )
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise PendingApprovalValueError("requested_at must be timezone-aware")
    norm_requested_at = requested_at if requested_at.tzinfo == UTC else requested_at.astimezone(UTC)

    # 4. Resolve frozen authority policy from P-11.01
    policy: ActionAuthorityPolicy = get_action_authority_policy(action.action_type)

    # Invariant: policy lineage check
    if policy.action_type != action.action_type:
        raise PendingApprovalValueError("Policy action_type does not match candidate action_type")

    # 5. Check approval requirement: fail closed if approval is NOT required
    if not policy.requires_bound_approval or not policy.requires_human_approval:
        raise ApprovalNotRequiredError(
            f"Action '{action.action_type.value}' has authority class "
            f"'{policy.authority_class.value}' and does not require human approval"
        )

    # 6. Extract authority class strictly from policy
    auth_class: AuthorityClass = policy.authority_class

    # 7. Compute deterministic content-addressed pending approval ID
    pending_id = compute_pending_approval_id(
        mission_id=action.mission_id,
        action_id=action.action_id,
        action_type=action.action_type,
        authority_class=auth_class,
        target=action.target,
        parameters=action.parameters,
    )

    # 8. Compute parameters digest
    param_bytes = canonical_serialize(to_canonical_primitive(action.parameters.to_dict()))
    param_digest = hashlib.sha256(param_bytes).hexdigest()

    # 9. Build privacy-safe human summary
    summary = _build_human_summary(action)

    # 10. Build OneDecisionContract
    decision_contract = OneDecisionContract(
        pending_approval_id=pending_id,
        mission_id=action.mission_id,
        action_id=action.action_id,
        action_type=action.action_type,
        authority_class=auth_class,
        decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
        human_summary=summary,
        status=PendingApprovalStatus.PENDING,
        requested_at=norm_requested_at,
    )

    # 11. Construct immutable PendingApproval
    return PendingApproval(
        pending_approval_id=pending_id,
        mission_id=action.mission_id,
        action_id=action.action_id,
        action_type=action.action_type,
        authority_class=auth_class,
        target=action.target,
        parameters=action.parameters,
        parameters_digest=param_digest,
        requested_at=norm_requested_at,
        decision_contract=decision_contract,
        action=action.action,
        status=PendingApprovalStatus.PENDING,
        decision_options=(ApprovalDecision.APPROVE, ApprovalDecision.REJECT),
    )


__all__ = [
    "PENDING_APPROVAL_DOMAIN_SEPARATOR",
    "ApprovalDecision",
    "ApprovalNotRequiredError",
    "InvalidDecisionError",
    "OneDecisionContract",
    "PendingApproval",
    "PendingApprovalError",
    "PendingApprovalId",
    "PendingApprovalStatus",
    "PendingApprovalTamperedError",
    "PendingApprovalTypeError",
    "PendingApprovalValueError",
    "SmuggledGrantError",
    "compute_pending_approval_id",
    "create_pending_approval",
    "validate_approval_decision",
]
