"""Deterministic approval binding and grant creation for StillDone.

Phase P-11.03:
Turns one valid human APPROVE decision for one exact PendingApproval into
one exact canonical ApprovalGrant cryptographically bound to the intended mutation.

Core Architectural Laws:
- Canonical inputs: PendingApproval + closed-world ApprovalDecision.APPROVE.
- Model / planner has ZERO authority to create, alter, or revive approval grants.
- Cryptographically bound to:
  * mission ID;
  * action ID;
  * action type;
  * exact TargetIdentity (system, resource_kind, resource_id, parent_id);
  * exact normalized parameters;
  * authority class;
  * issued_at (timezone-aware UTC);
  * expires_at (timezone-aware UTC, strictly > issued_at).
- Reject must NOT create a grant, authorization fact, or execution permission.
  Produces a deterministic PendingApprovalRejection typed result.
- Pending lineage: PendingApproval must self-validate and match frozen P-11.01 policy.
- Zero execution: Creates authority facts only; performs 0 provider calls and 0 mutations.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.action_policy import ValidatedActionContract, validate_action_contract
from stilldone.authority_policy import (
    PlannerAuthorityError,
    assert_not_planner_for_authority,
    get_action_authority_policy,
    verify_approval_grant,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    ApprovalId,
    compute_approval_binding_hash,
)
from stilldone.domain.mission import MissionId
from stilldone.pending_approval import (
    ApprovalDecision,
    PendingApproval,
    PendingApprovalId,
    PendingApprovalStatus,
    compute_parameters_digest,
    compute_pending_approval_id,
    validate_approval_decision,
)
from stilldone.redaction import redact_text

# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class ApprovalBindingError(Exception):
    """Base exception for all StillDone approval-binding operations."""


class ApprovalBindingTypeError(ApprovalBindingError, TypeError):
    """Raised when an argument has an invalid type."""


class ApprovalBindingValueError(ApprovalBindingError, ValueError):
    """Raised when an argument has an invalid value."""


class PlannerApprovalBindingError(ApprovalBindingTypeError, PlannerAuthorityError):
    """Raised when a model/planner proposal object is passed into approval binding."""


class ApprovalRejectedError(ApprovalBindingError):
    """Raised when an approval binding operation fails because the human decision was REJECT."""

    def __init__(self, message: str, *, rejection: PendingApprovalRejection | None = None) -> None:
        super().__init__(message)
        self.rejection = rejection


class PendingApprovalInvalidError(ApprovalBindingError, ValueError):
    """Raised when a PendingApproval object fails integrity, cryptographic, or lineage checks."""


class ApprovalExpiryError(ApprovalBindingValueError):
    """Raised when an approval validity window is invalid (e.g. expires_at <= issued_at)."""


# ===========================================================================
# Canonical Status and Result Models
# ===========================================================================


class ApprovalBindingStatus(StrEnum):
    """Closed-world status outcome for an approval resolution."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class PendingApprovalRejection:
    """Immutable typed record of a rejected PendingApproval.

    Ensures REJECT produces a deterministic typed state and NEVER an ApprovalGrant.
    """

    pending_approval_id: PendingApprovalId
    mission_id: MissionId
    action_id: ActionId
    decision: ApprovalDecision
    rejected_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.pending_approval_id, PendingApprovalId):
            raise ApprovalBindingTypeError(
                "pending_approval_id must be a PendingApprovalId instance, "
                f"got {type(self.pending_approval_id).__name__}"
            )
        if not isinstance(self.mission_id, MissionId):
            raise ApprovalBindingTypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.action_id, ActionId):
            raise ApprovalBindingTypeError(
                f"action_id must be an ActionId instance, got {type(self.action_id).__name__}"
            )
        if not isinstance(self.decision, ApprovalDecision):
            raise ApprovalBindingTypeError(
                f"decision must be an ApprovalDecision instance, got {type(self.decision).__name__}"
            )
        if self.decision != ApprovalDecision.REJECT:
            raise ApprovalBindingValueError("PendingApprovalRejection decision must be REJECT")
        if not isinstance(self.rejected_at, datetime):
            raise ApprovalBindingTypeError(
                f"rejected_at must be a datetime instance, got {type(self.rejected_at).__name__}"
            )
        if self.rejected_at.tzinfo is None or self.rejected_at.utcoffset() is None:
            raise ApprovalBindingValueError("rejected_at must be timezone-aware")
        if self.rejected_at.tzinfo != UTC:
            object.__setattr__(self, "rejected_at", self.rejected_at.astimezone(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert rejection record to a serializable, privacy-safe dictionary."""
        return {
            "pending_approval_id": self.pending_approval_id.value,
            "mission_id": str(self.mission_id),
            "action_id": str(self.action_id),
            "decision": self.decision.value,
            "rejected_at": self.rejected_at.isoformat(),
            "reason": redact_text(self.reason) if self.reason is not None else None,
        }


@dataclass(frozen=True)
class ApprovalBindingResult:
    """Immutable outcome of resolving a human decision on a PendingApproval.

    Carries either:
    - status=APPROVED: grant is an ApprovalGrant, rejection is None.
    - status=REJECTED: grant is None, rejection is a PendingApprovalRejection.
    """

    status: ApprovalBindingStatus
    pending_approval_id: PendingApprovalId
    grant: ApprovalGrant | None = None
    rejection: PendingApprovalRejection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ApprovalBindingStatus):
            raise ApprovalBindingTypeError(
                "status must be an ApprovalBindingStatus instance, "
                f"got {type(self.status).__name__}"
            )
        if not isinstance(self.pending_approval_id, PendingApprovalId):
            raise ApprovalBindingTypeError(
                "pending_approval_id must be a PendingApprovalId instance, "
                f"got {type(self.pending_approval_id).__name__}"
            )

        if self.status == ApprovalBindingStatus.APPROVED:
            if not isinstance(self.grant, ApprovalGrant):
                raise ApprovalBindingValueError(
                    "ApprovalBindingResult with status APPROVED must contain an ApprovalGrant"
                )
            if self.rejection is not None:
                raise ApprovalBindingValueError(
                    "ApprovalBindingResult with status APPROVED must not contain a rejection record"
                )
        elif self.status == ApprovalBindingStatus.REJECTED:
            if self.grant is not None:
                raise ApprovalBindingValueError(
                    "ApprovalBindingResult with status REJECTED must not contain an ApprovalGrant"
                )
            if not isinstance(self.rejection, PendingApprovalRejection):
                raise ApprovalBindingValueError(
                    "ApprovalBindingResult with status REJECTED "
                    "must contain a PendingApprovalRejection"
                )

    @property
    def is_approved(self) -> bool:
        """True if the decision resulted in a valid ApprovalGrant."""
        return self.status == ApprovalBindingStatus.APPROVED

    @property
    def is_rejected(self) -> bool:
        """True if the decision was rejected."""
        return self.status == ApprovalBindingStatus.REJECTED


# ===========================================================================
# Internal Lineage Verification Helper
# ===========================================================================


def _validate_pending_approval_lineage(pending: PendingApproval) -> None:
    """Perform fail-closed cryptographic and policy self-validation on a PendingApproval."""
    if not isinstance(pending, PendingApproval):
        raise ApprovalBindingTypeError(
            f"pending must be a PendingApproval instance, got {type(pending).__name__}"
        )

    # Status must be PENDING
    if pending.status != PendingApprovalStatus.PENDING:
        raise PendingApprovalInvalidError(
            f"PendingApproval status must be PENDING, got {pending.status!r}"
        )

    # 1. Parameters digest self-validation
    expected_param_digest = compute_parameters_digest(pending.parameters)
    if not hmac.compare_digest(pending.parameters_digest, expected_param_digest):
        raise PendingApprovalInvalidError("PendingApproval parameters_digest verification failed")

    # 2. Content-addressed identity recomputation
    expected_id = compute_pending_approval_id(
        mission_id=pending.mission_id,
        action_id=pending.action_id,
        action_type=pending.action_type,
        authority_class=pending.authority_class,
        target=pending.target,
        parameters=pending.parameters,
    )
    if not hmac.compare_digest(pending.pending_approval_id.value, expected_id.value):
        raise PendingApprovalInvalidError(
            "PendingApproval content-addressed identity verification failed"
        )

    # 3. P-11.01 Frozen policy lineage check
    policy = get_action_authority_policy(pending.action_type)
    if pending.authority_class != policy.authority_class:
        raise PendingApprovalInvalidError(
            f"PendingApproval authority class '{pending.authority_class.value}' does not match "
            f"frozen policy authority class '{policy.authority_class.value}'"
        )
    if not policy.requires_bound_approval or not policy.requires_human_approval:
        raise PendingApprovalInvalidError(
            f"Action '{pending.action_type.value}' does not require human approval "
            "under frozen policy"
        )

    # 4. Action contract lineage check
    act = pending.action
    if act.mission_id != pending.mission_id:
        raise PendingApprovalInvalidError("pending.action.mission_id mismatch")
    if act.action_id != pending.action_id:
        raise PendingApprovalInvalidError("pending.action.action_id mismatch")
    if act.action_type != pending.action_type:
        raise PendingApprovalInvalidError("pending.action.action_type mismatch")
    if act.target != pending.target:
        raise PendingApprovalInvalidError("pending.action.target mismatch")
    if act.parameters != pending.parameters:
        raise PendingApprovalInvalidError("pending.action.parameters mismatch")


def _normalize_and_validate_window(
    issued_at: datetime,
    expires_at: datetime,
) -> tuple[datetime, datetime]:
    """Validate and normalize explicit validity window timestamps to UTC."""
    if not isinstance(issued_at, datetime):
        raise ApprovalBindingTypeError(
            f"issued_at must be a datetime instance, got {type(issued_at).__name__}"
        )
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ApprovalExpiryError("issued_at must be timezone-aware")

    if not isinstance(expires_at, datetime):
        raise ApprovalBindingTypeError(
            f"expires_at must be a datetime instance, got {type(expires_at).__name__}"
        )
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ApprovalExpiryError("expires_at must be timezone-aware")

    norm_issued = issued_at if issued_at.tzinfo == UTC else issued_at.astimezone(UTC)
    norm_expires = expires_at if expires_at.tzinfo == UTC else expires_at.astimezone(UTC)

    if norm_expires <= norm_issued:
        raise ApprovalExpiryError(
            f"expires_at ({norm_expires.isoformat()}) must be strictly later than "
            f"issued_at ({norm_issued.isoformat()})"
        )

    return norm_issued, norm_expires


# ===========================================================================
# Core Resolution and Binding Functions
# ===========================================================================


def resolve_pending_approval(
    pending: PendingApproval,
    decision: ApprovalDecision | str,
    *,
    issued_at: datetime,
    expires_at: datetime,
    approval_id: ApprovalId | None = None,
    rejection_reason: str | None = None,
) -> ApprovalBindingResult:
    """Resolve a PendingApproval with a closed-world human decision.

    Guarantees:
    - If decision is APPROVE: creates one exact ApprovalGrant cryptographically
      bound to the PendingApproval's action, target, parameters, and validity window.
    - If decision is REJECT: creates a typed PendingApprovalRejection and ZERO ApprovalGrant.
    - Planner/model proposals have ZERO authority and fail closed.
    - Caller cannot provide alternative targets, parameters, or authority classes.
    - PendingApproval object remains completely unmodified.

    Args:
        pending: Self-validating canonical PendingApproval.
        decision: Closed-world ApprovalDecision (APPROVE or REJECT).
        issued_at: Explicit timezone-aware UTC datetime.
        expires_at: Explicit timezone-aware UTC datetime strictly later than issued_at.
        approval_id: Optional explicit ApprovalId (generated deterministically if None).
        rejection_reason: Optional human operator explanation if rejected.

    Returns:
        ApprovalBindingResult with status APPROVED or REJECTED.
    """
    # 1. Zero authority for model / planner proposals
    assert_not_planner_for_authority(pending, parameter_name="pending")
    assert_not_planner_for_authority(decision, parameter_name="decision")

    # 2. Type validation and self-validation of PendingApproval
    _validate_pending_approval_lineage(pending)

    # 3. Validate decision against closed-world enum
    valid_decision: ApprovalDecision | None = None
    try:
        valid_decision = validate_approval_decision(decision)
    except Exception:
        valid_decision = None

    if valid_decision is None:
        raise ApprovalBindingValueError(
            "Invalid approval decision; must be exactly APPROVE or REJECT"
        )

    # 4. Validate and normalize validity window timestamps
    norm_issued, norm_expires = _normalize_and_validate_window(issued_at, expires_at)

    # 5. Handle REJECT branch
    if valid_decision == ApprovalDecision.REJECT:
        rejection = PendingApprovalRejection(
            pending_approval_id=pending.pending_approval_id,
            mission_id=pending.mission_id,
            action_id=pending.action_id,
            decision=ApprovalDecision.REJECT,
            rejected_at=norm_issued,
            reason=rejection_reason,
        )
        return ApprovalBindingResult(
            status=ApprovalBindingStatus.REJECTED,
            pending_approval_id=pending.pending_approval_id,
            grant=None,
            rejection=rejection,
        )

    # 6. Handle APPROVE branch: construct canonical ApprovalGrant
    aid = approval_id if approval_id is not None else ApprovalId.generate()
    if not isinstance(aid, ApprovalId):
        raise ApprovalBindingTypeError(
            f"approval_id must be an ApprovalId instance, got {type(aid).__name__}"
        )

    grant = ApprovalGrant.create(
        action=pending.action,
        authority_class=pending.authority_class,
        issued_at=norm_issued,
        expires_at=norm_expires,
        approval_id=aid,
    )

    return ApprovalBindingResult(
        status=ApprovalBindingStatus.APPROVED,
        pending_approval_id=pending.pending_approval_id,
        grant=grant,
        rejection=None,
    )


# Canonical alias for resolve_pending_approval
bind_approval = resolve_pending_approval


def bind_approval_grant(
    pending: PendingApproval,
    decision: ApprovalDecision | str = ApprovalDecision.APPROVE,
    *,
    issued_at: datetime,
    expires_at: datetime,
    approval_id: ApprovalId | None = None,
) -> ApprovalGrant:
    """Convenience function returning the bound ApprovalGrant directly upon human approval.

    Fails closed if the human decision was REJECT by raising ApprovalRejectedError,
    guaranteeing that REJECT never returns an ApprovalGrant.

    Args:
        pending: Self-validating canonical PendingApproval.
        decision: Closed-world ApprovalDecision (must be APPROVE to return grant).
        issued_at: Explicit timezone-aware UTC datetime.
        expires_at: Explicit timezone-aware UTC datetime strictly later than issued_at.
        approval_id: Optional explicit ApprovalId.

    Returns:
        Canonical ApprovalGrant cryptographically bound to the intended mutation.

    Raises:
        ApprovalRejectedError: If the decision was REJECT.
        ApprovalBindingError: On any invalid argument, tampering, or validation error.
    """
    result = resolve_pending_approval(
        pending,
        decision,
        issued_at=issued_at,
        expires_at=expires_at,
        approval_id=approval_id,
    )
    if not result.is_approved or result.grant is None:
        raise ApprovalRejectedError(
            f"Pending approval '{pending.pending_approval_id}' was rejected by human operator",
            rejection=result.rejection,
        )
    return result.grant


# ===========================================================================
# Approval Verification Function
# ===========================================================================


def verify_approval_binding(
    action: ValidatedActionContract | ActionContract | PendingApproval,
    grant: ApprovalGrant,
    *,
    at: datetime,
) -> None:
    """Verify that an ApprovalGrant cryptographically binds and authorizes a target action.

    Accepts ValidatedActionContract, ActionContract, or PendingApproval.
    Reuses canonical authority verification semantics from stilldone.authority_policy.

    Args:
        action: The candidate action or pending approval to verify against.
        grant: The ApprovalGrant to verify.
        at: Explicit timezone-aware observation datetime.

    Raises:
        ApprovalBindingTypeError: If action, grant, or at has invalid type.
        ApprovalBindingValueError: If at is naive (not timezone-aware).
        AuthorityPolicyError: On any binding mismatch, expired grant, or tampered hash.
    """
    assert_not_planner_for_authority(action, parameter_name="action")
    assert_not_planner_for_authority(grant, parameter_name="grant")

    if isinstance(action, PendingApproval):
        actual_contract = action.action
    elif isinstance(action, ValidatedActionContract):
        actual_contract = action.action
    elif isinstance(action, ActionContract):
        actual_contract = action
    else:
        raise ApprovalBindingTypeError(
            "action must be a ValidatedActionContract, ActionContract, "
            f"or PendingApproval instance, got {type(action).__name__}"
        )

    if not isinstance(grant, ApprovalGrant):
        raise ApprovalBindingTypeError(
            f"grant must be an ApprovalGrant instance, got {type(grant).__name__}"
        )

    # Validate action contract under action policy
    validated_action = validate_action_contract(actual_contract)

    # Retrieve expected authority class from frozen P-11.01 policy
    policy = get_action_authority_policy(validated_action.action_type)

    # Delegate to canonical verification engine
    verify_approval_grant(
        validated_action,
        grant,
        expected_authority_class=policy.authority_class,
        at=at,
    )


__all__ = [
    "ApprovalBindingError",
    "ApprovalBindingResult",
    "ApprovalBindingStatus",
    "ApprovalBindingTypeError",
    "ApprovalBindingValueError",
    "ApprovalExpiryError",
    "ApprovalRejectedError",
    "PendingApprovalInvalidError",
    "PendingApprovalRejection",
    "PlannerApprovalBindingError",
    "bind_approval",
    "bind_approval_grant",
    "compute_approval_binding_hash",
    "resolve_pending_approval",
    "verify_approval_binding",
]
