"""Deterministic runtime authority boundary and approval-binding verification.

Enforces StillDone's fail-closed authority classification and approval verification:
- Accepts only P-04.03 ValidatedActionContract (cannot bypass action validation).
- Closed-world authority classification table mapping all 5 canonical ActionType members.
- Strict approval requirement enforcement:
  - READ_ONLY (calendar.read, task.read, weather.read) requires approval=None.
  - REVERSIBLE_AUTO (task.create) requires approval=None.
  - REVERSIBLE_APPROVAL_REQUIRED (calendar.update) requires a cryptographically bound ApprovalGrant.
  - Unexpected approval grants on no-approval actions fail closed.
  - IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED is never auto-authorized, even with an ApprovalGrant.
  - EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED requires exact bound approval.
- Exact cryptographic approval binding verification:
  - Action identity, mission ID, action ID, action type, parameters, and TargetIdentity.
  - AuthorityClass matching.
  - Freshly recomputed SHA-256 binding hash compared with constant-time equality
    (hmac.compare_digest).
  - Explicit timezone-aware validity window: issued_at <= at < expires_at.
- Error safety: Sensitive parameter plaintext, external target identifiers (resource_id,
  parent_id), and full grant reprs are never echoed.
- Replay boundary: P-04.04 verifies static binding and validity only. It does not
  implement durable single-use approval consumption, revocation registries, or replay
  ledgers. A valid grant may verify repeatedly in this pure layer.
- Purity: Pure verification only. No provider SDKs, no network calls, no execution attempts,
  no ledger mutations, and no mission/step state promotion.
"""

from __future__ import annotations

import hmac
import types
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.action_policy import ValidatedActionContract
from stilldone.domain.action import ActionContract, ActionId, ActionType
from stilldone.domain.authority import (
    ApprovalGrant,
    ApprovalId,
    AuthorityClass,
    compute_approval_binding_hash,
)
from stilldone.domain.mission import MissionId

# Detect planner/model classes if available to reject model authority injections
try:
    from stilldone.planning.contracts import (
        CandidateActionProposal,
        CandidatePlanProposal,
        PlannerInput,
    )

    _PLANNER_TYPES: tuple[type, ...] = (
        CandidatePlanProposal,
        CandidateActionProposal,
        PlannerInput,
    )
except ImportError:
    _PLANNER_TYPES = ()

# ===========================================================================
# Decision Status and Rejection Reason Enums
# ===========================================================================


class AuthorityDecisionStatus(StrEnum):
    """Canonical authority decision statuses."""

    AUTHORIZED_NO_APPROVAL_REQUIRED = "AUTHORIZED_NO_APPROVAL_REQUIRED"
    AUTHORIZED_BY_BOUND_APPROVAL = "AUTHORIZED_BY_BOUND_APPROVAL"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BLOCKED = "BLOCKED"


AuthorityDecisionCode = AuthorityDecisionStatus


class RejectionReason(StrEnum):
    """Specific rejection categories for non-authorized authority evaluations."""

    UNEXPECTED_APPROVAL_GRANT = "UNEXPECTED_APPROVAL_GRANT"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    IRREVERSIBLE_ACTION_BLOCKED = "IRREVERSIBLE_ACTION_BLOCKED"
    MISSION_MISMATCH = "MISSION_MISMATCH"
    ACTION_ID_MISMATCH = "ACTION_ID_MISMATCH"
    ACTION_TYPE_MISMATCH = "ACTION_TYPE_MISMATCH"
    AUTHORITY_CLASS_MISMATCH = "AUTHORITY_CLASS_MISMATCH"
    PARAMETERS_MISMATCH = "PARAMETERS_MISMATCH"
    TARGET_SYSTEM_MISMATCH = "TARGET_SYSTEM_MISMATCH"
    TARGET_RESOURCE_KIND_MISMATCH = "TARGET_RESOURCE_KIND_MISMATCH"
    TARGET_RESOURCE_ID_MISMATCH = "TARGET_RESOURCE_ID_MISMATCH"
    TARGET_PARENT_ID_MISMATCH = "TARGET_PARENT_ID_MISMATCH"
    APPROVAL_NOT_YET_VALID = "APPROVAL_NOT_YET_VALID"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    BINDING_HASH_MISMATCH = "BINDING_HASH_MISMATCH"


# ===========================================================================
# Authority Policy Exception Hierarchy
# ===========================================================================


class AuthorityPolicyError(Exception):
    """Base exception for all StillDone authority policy and verification errors."""


class AuthorityPolicyTypeError(AuthorityPolicyError, TypeError):
    """Raised when an object or argument has an invalid type."""


class PlannerAuthorityError(AuthorityPolicyTypeError):
    """Raised when a model/planner proposal object is passed as authority input."""


def assert_not_planner_for_authority(obj: Any, *, parameter_name: str = "argument") -> None:
    """Reject planner/model proposals fail-closed in authority policy operations."""
    for pt in _PLANNER_TYPES:
        if isinstance(obj, pt):
            raise PlannerAuthorityError(
                f"Model/planner proposal {type(obj).__name__} has ZERO authority "
                f"and cannot act as authority input ({parameter_name})"
            )


class AuthorityPolicyValueError(AuthorityPolicyError, ValueError):
    """Raised when an argument has an invalid value (e.g. naive evaluation datetime)."""


class UnsupportedActionTypeError(AuthorityPolicyError, ValueError):
    """Raised when an action type is not supported by StillDone's authority policy."""


class UnexpectedApprovalGrantError(AuthorityPolicyError, ValueError):
    """Raised when an ApprovalGrant is supplied for an action requiring no approval."""


class ApprovalRequiredError(AuthorityPolicyError):
    """Raised when an action requires an ApprovalGrant but none was provided."""


class InvalidApprovalTypeError(AuthorityPolicyError, TypeError):
    """Raised when an approval argument is neither None nor an ApprovalGrant instance."""


class ApprovalBindingMismatchError(AuthorityPolicyError, ValueError):
    """Raised when an ApprovalGrant does not match the candidate action contract."""

    def __init__(
        self,
        message: str,
        *,
        rejection_reason: RejectionReason | None = None,
    ) -> None:
        super().__init__(message)
        self.rejection_reason = rejection_reason


class ApprovalAuthorityClassMismatchError(AuthorityPolicyError, ValueError):
    """Raised when an ApprovalGrant authority class does not match the expected authority class."""


class ApprovalNotYetValidError(AuthorityPolicyError, ValueError):
    """Raised when an ApprovalGrant evaluation timestamp is prior to its issued_at timestamp."""


class ApprovalExpiredError(AuthorityPolicyError, ValueError):
    """Raised when an ApprovalGrant evaluation timestamp is at or past its expires_at timestamp."""


class ApprovalTamperedError(AuthorityPolicyError, ValueError):
    """Raised when an ApprovalGrant binding hash does not match the recomputed hash."""


class IrreversibleActionBlockedError(AuthorityPolicyError):
    """Raised when attempting to authorize an IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED action."""


class AuthorityBlockedError(AuthorityPolicyError):
    """Raised when an action is blocked by authority policy."""


# ===========================================================================
# Canonical Action Authority Policy Model & Frozen Tables
# ===========================================================================

DEFAULT_AUTHORITY_DECISION_COMPONENT: str = "stilldone.authority_policy.evaluate_authority"


@dataclass(frozen=True)
class ActionAuthorityPolicy:
    """Immutable canonical authority policy for a supported ActionType.

    Answers deterministically:
    - action_type: Canonical ActionType member.
    - authority_class: Canonical AuthorityClass required.
    - is_mutating: Whether action mutates external state (True) or observes it (False).
    - requires_human_approval: Whether human approval is required before execution.
    - requires_bound_approval: Whether a bound ApprovalGrant must exist before execution.
    - permit_execution_without_grant: Whether execution is permitted without an ApprovalGrant.
    - owning_runtime_component: The exact runtime component owning the authority decision.
    """

    action_type: ActionType
    authority_class: AuthorityClass
    is_mutating: bool
    requires_human_approval: bool
    requires_bound_approval: bool
    permit_execution_without_grant: bool
    owning_runtime_component: str = DEFAULT_AUTHORITY_DECISION_COMPONENT

    def __post_init__(self) -> None:
        if not isinstance(self.action_type, ActionType):
            raise TypeError(
                f"action_type must be an ActionType instance, got {type(self.action_type).__name__}"
            )
        if not isinstance(self.authority_class, AuthorityClass):
            ac_type = type(self.authority_class).__name__
            raise TypeError(f"authority_class must be an AuthorityClass instance, got {ac_type}")
        if type(self.is_mutating) is not bool:
            raise TypeError(f"is_mutating must be a bool, got {type(self.is_mutating).__name__}")
        if type(self.requires_human_approval) is not bool:
            rha_type = type(self.requires_human_approval).__name__
            raise TypeError(f"requires_human_approval must be a bool, got {rha_type}")
        if type(self.requires_bound_approval) is not bool:
            rba_type = type(self.requires_bound_approval).__name__
            raise TypeError(f"requires_bound_approval must be a bool, got {rba_type}")
        if type(self.permit_execution_without_grant) is not bool:
            pe_type = type(self.permit_execution_without_grant).__name__
            raise TypeError(f"permit_execution_without_grant must be a bool, got {pe_type}")
        if (
            not isinstance(self.owning_runtime_component, str)
            or not self.owning_runtime_component.strip()
        ):
            raise ValueError("owning_runtime_component must be a non-empty string")

        # Invariant: requires_human_approval must match authority_class.requires_human_approval
        expected_approval = self.authority_class.requires_human_approval
        if self.requires_human_approval != expected_approval:
            raise ValueError(
                f"requires_human_approval ({self.requires_human_approval}) must match "
                f"authority_class.requires_human_approval ({expected_approval})"
            )

        # Invariant: if requires_bound_approval is True, permit_execution_without_grant is False
        if self.requires_bound_approval and self.permit_execution_without_grant:
            raise ValueError(
                "Action requiring bound approval cannot permit execution without a grant"
            )

        # Invariant: if permit_execution_without_grant is True, requires_bound_approval is False
        if self.permit_execution_without_grant and self.requires_bound_approval:
            raise ValueError(
                "Action permitting execution without a grant cannot require bound approval"
            )

        # Invariant: read-only actions must not mutate and must not require approval
        if not self.is_mutating:
            if self.authority_class != AuthorityClass.READ_ONLY:
                raise ValueError("Read-only actions must have AuthorityClass.READ_ONLY")
            if self.requires_human_approval:
                raise ValueError("Read-only actions cannot require human approval")
            if self.requires_bound_approval:
                raise ValueError("Read-only actions cannot require bound approval")
            if not self.permit_execution_without_grant:
                raise ValueError("Read-only actions must permit execution without a grant")

    @property
    def is_read_only(self) -> bool:
        """True if the action is read-only (non-mutating)."""
        return not self.is_mutating

    @property
    def execution_permitted_without_grant(self) -> bool:
        """Alias for permit_execution_without_grant."""
        return self.permit_execution_without_grant

    @property
    def requires_bound_approval_for_execution(self) -> bool:
        """Alias for requires_bound_approval."""
        return self.requires_bound_approval

    def to_dict(self) -> dict[str, Any]:
        """Convert policy to a serializable dictionary."""
        return {
            "action_type": self.action_type.value,
            "authority_class": self.authority_class.value,
            "is_mutating": self.is_mutating,
            "is_read_only": self.is_read_only,
            "requires_human_approval": self.requires_human_approval,
            "requires_bound_approval": self.requires_bound_approval,
            "requires_bound_approval_for_execution": self.requires_bound_approval_for_execution,
            "permit_execution_without_grant": self.permit_execution_without_grant,
            "execution_permitted_without_grant": self.execution_permitted_without_grant,
            "owning_runtime_component": self.owning_runtime_component,
        }


_CANONICAL_ACTION_AUTHORITY_POLICIES: tuple[ActionAuthorityPolicy, ...] = (
    ActionAuthorityPolicy(
        action_type=ActionType.CALENDAR_READ,
        authority_class=AuthorityClass.READ_ONLY,
        is_mutating=False,
        requires_human_approval=False,
        requires_bound_approval=False,
        permit_execution_without_grant=True,
        owning_runtime_component=DEFAULT_AUTHORITY_DECISION_COMPONENT,
    ),
    ActionAuthorityPolicy(
        action_type=ActionType.CALENDAR_UPDATE,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        is_mutating=True,
        requires_human_approval=True,
        requires_bound_approval=True,
        permit_execution_without_grant=False,
        owning_runtime_component=DEFAULT_AUTHORITY_DECISION_COMPONENT,
    ),
    ActionAuthorityPolicy(
        action_type=ActionType.TASK_READ,
        authority_class=AuthorityClass.READ_ONLY,
        is_mutating=False,
        requires_human_approval=False,
        requires_bound_approval=False,
        permit_execution_without_grant=True,
        owning_runtime_component=DEFAULT_AUTHORITY_DECISION_COMPONENT,
    ),
    ActionAuthorityPolicy(
        action_type=ActionType.TASK_CREATE,
        authority_class=AuthorityClass.REVERSIBLE_AUTO,
        is_mutating=True,
        requires_human_approval=False,
        requires_bound_approval=False,
        permit_execution_without_grant=True,
        owning_runtime_component=DEFAULT_AUTHORITY_DECISION_COMPONENT,
    ),
    ActionAuthorityPolicy(
        action_type=ActionType.WEATHER_READ,
        authority_class=AuthorityClass.READ_ONLY,
        is_mutating=False,
        requires_human_approval=False,
        requires_bound_approval=False,
        permit_execution_without_grant=True,
        owning_runtime_component=DEFAULT_AUTHORITY_DECISION_COMPONENT,
    ),
)

_raw_policy_store: dict[ActionType, ActionAuthorityPolicy] = {
    p.action_type: p for p in _CANONICAL_ACTION_AUTHORITY_POLICIES
}

# Module-level invariants: exact 1:1 mapping with ActionType
assert set(_raw_policy_store.keys()) == set(ActionType), (
    "ACTION_AUTHORITY_POLICY_TABLE must cover all canonical ActionType members"
)
assert len(_raw_policy_store) == len(ActionType) == 5, (
    "ACTION_AUTHORITY_POLICY_TABLE must have exactly 5 entries"
)

ACTION_AUTHORITY_POLICY_TABLE: Mapping[ActionType, ActionAuthorityPolicy] = types.MappingProxyType(
    _raw_policy_store
)

del _raw_policy_store


class _ActionAuthorityMapping(Mapping[ActionType, AuthorityClass]):
    """Immutable mapping projecting AuthorityClass directly from ACTION_AUTHORITY_POLICY_TABLE.

    Ensures zero split-brain: cannot drift from the canonical policy source.
    """

    def __getitem__(self, key: ActionType) -> AuthorityClass:
        return ACTION_AUTHORITY_POLICY_TABLE[key].authority_class

    def __iter__(self) -> Iterator[ActionType]:
        return iter(ACTION_AUTHORITY_POLICY_TABLE)

    def __len__(self) -> int:
        return len(ACTION_AUTHORITY_POLICY_TABLE)

    def __contains__(self, key: object) -> bool:
        return key in ACTION_AUTHORITY_POLICY_TABLE

    def __repr__(self) -> str:
        return repr({k: self[k] for k in self})


ACTION_AUTHORITY_TABLE: Mapping[ActionType, AuthorityClass] = _ActionAuthorityMapping()


def get_action_authority_policy(
    action: ValidatedActionContract | ActionContract | ActionType,
) -> ActionAuthorityPolicy:
    """Resolve the immutable canonical authority policy for an action or ActionType.

    Fails closed on unsupported action types, unvalidated model prose,
    or planner proposal injections.
    Does NOT manufacture, imply, or verify an ApprovalGrant.

    Args:
        action: A canonical ValidatedActionContract, ActionContract, or ActionType.

    Returns:
        The frozen ActionAuthorityPolicy for the corresponding action type.

    Raises:
        PlannerAuthorityError: If action is a model/planner proposal object.
        AuthorityPolicyTypeError: If action is a raw string or unsupported type.
        UnsupportedActionTypeError: If action type is not present in the policy table.
    """
    assert_not_planner_for_authority(action, parameter_name="action")

    if isinstance(action, ValidatedActionContract):
        act_type = action.action_type
    elif isinstance(action, ActionContract):
        act_type = action.action_type
    elif isinstance(action, ActionType):
        act_type = action
    elif isinstance(action, str):
        # Plain strings (including model prose) cannot bypass canonical typed enum
        raise AuthorityPolicyTypeError(
            f"String input {action!r} cannot act as authority policy input; "
            "must be a canonical ActionType, ActionContract, or ValidatedActionContract"
        )
    else:
        raise AuthorityPolicyTypeError(
            "action must be a ValidatedActionContract, ActionContract, or ActionType instance, "
            f"got {type(action).__name__}"
        )

    policy = ACTION_AUTHORITY_POLICY_TABLE.get(act_type)
    if policy is None:
        raise UnsupportedActionTypeError(
            f"No frozen authority policy registered for action type: {act_type!r}"
        )
    return policy


def get_action_authority_class(
    action: ValidatedActionContract | ActionContract | ActionType,
) -> AuthorityClass:
    """Resolve the canonical AuthorityClass for an action or ActionType."""
    return get_action_authority_policy(action).authority_class


get_authority_policy = get_action_authority_policy


# ===========================================================================
# Authority Decision Model
# ===========================================================================


@dataclass(frozen=True)
class AuthorityDecision:
    """Immutable result of an authority evaluation for a validated action.

    Captures the deterministic evaluation status, classified authority class,
    action/mission identifiers, timestamp, optional approval ID, and reason.
    Does NOT indicate execution success, provider authentication, or verification.
    """

    status: AuthorityDecisionStatus
    authority_class: AuthorityClass
    action_id: ActionId
    mission_id: MissionId
    action_type: ActionType
    evaluated_at: datetime
    approval_id: ApprovalId | None = None
    reason: str | None = None
    rejection_reason: RejectionReason | None = None

    @property
    def is_authorized(self) -> bool:
        """True if the action is authorized to proceed to future execution."""
        return self.status in {
            AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED,
            AuthorityDecisionStatus.AUTHORIZED_BY_BOUND_APPROVAL,
        }

    @property
    def requires_approval(self) -> bool:
        """True if the action requires an approval grant before proceeding."""
        return self.status == AuthorityDecisionStatus.APPROVAL_REQUIRED

    @property
    def is_blocked(self) -> bool:
        """True if the action is blocked by authority policy."""
        return self.status == AuthorityDecisionStatus.BLOCKED

    def raise_for_status(self) -> None:
        """Raise an appropriate typed AuthorityPolicyError if not authorized."""
        if self.is_authorized:
            return
        if self.status == AuthorityDecisionStatus.APPROVAL_REQUIRED:
            raise ApprovalRequiredError(
                self.reason or f"Action '{self.action_type.value}' requires an approval grant"
            )
        if self.status == AuthorityDecisionStatus.BLOCKED:
            if self.rejection_reason == RejectionReason.UNEXPECTED_APPROVAL_GRANT:
                raise UnexpectedApprovalGrantError(
                    self.reason
                    or f"Unexpected approval grant for action '{self.action_type.value}'"
                )
            if self.rejection_reason == RejectionReason.IRREVERSIBLE_ACTION_BLOCKED:
                raise IrreversibleActionBlockedError(
                    self.reason
                    or f"Action '{self.action_type.value}' requires irreversible authority"
                )
            if self.rejection_reason == RejectionReason.APPROVAL_NOT_YET_VALID:
                raise ApprovalNotYetValidError(self.reason or "Approval grant is not yet valid")
            if self.rejection_reason == RejectionReason.APPROVAL_EXPIRED:
                raise ApprovalExpiredError(self.reason or "Approval grant has expired")
            if self.rejection_reason == RejectionReason.BINDING_HASH_MISMATCH:
                raise ApprovalTamperedError(self.reason or "Approval grant binding hash mismatch")
            if self.rejection_reason == RejectionReason.AUTHORITY_CLASS_MISMATCH:
                raise ApprovalAuthorityClassMismatchError(
                    self.reason or "Approval grant authority class mismatch"
                )
            if self.rejection_reason in {
                RejectionReason.MISSION_MISMATCH,
                RejectionReason.ACTION_ID_MISMATCH,
                RejectionReason.ACTION_TYPE_MISMATCH,
                RejectionReason.PARAMETERS_MISMATCH,
                RejectionReason.TARGET_SYSTEM_MISMATCH,
                RejectionReason.TARGET_RESOURCE_KIND_MISMATCH,
                RejectionReason.TARGET_RESOURCE_ID_MISMATCH,
                RejectionReason.TARGET_PARENT_ID_MISMATCH,
            }:
                raise ApprovalBindingMismatchError(
                    self.reason or "Approval grant binding mismatch",
                    rejection_reason=self.rejection_reason,
                )
            raise AuthorityBlockedError(
                self.reason or f"Action '{self.action_type.value}' is blocked by authority policy"
            )


# ===========================================================================
# Classification Function
# ===========================================================================


def classify_authority(action: ValidatedActionContract) -> AuthorityClass:
    """Classify the exact AuthorityClass required by a ValidatedActionContract.

    Accepts ONLY a ValidatedActionContract from P-04.03.
    Rejects raw ActionContract or any unvalidated object to ensure P-04.03 cannot be bypassed.

    Args:
        action: The validated action contract to classify.

    Returns:
        The canonical AuthorityClass required for this action.

    Raises:
        AuthorityPolicyTypeError: If action is not a ValidatedActionContract instance.
        UnsupportedActionTypeError: If action type is not present in the classification table.
    """
    assert_not_planner_for_authority(action, parameter_name="action")
    if not isinstance(action, ValidatedActionContract):
        raise AuthorityPolicyTypeError(
            f"action must be a ValidatedActionContract instance, got {type(action).__name__}"
        )

    auth_class = ACTION_AUTHORITY_TABLE.get(action.action_type)
    if auth_class is None:
        raise UnsupportedActionTypeError(
            f"No authority class registered for action type: {action.action_type!r}"
        )
    return auth_class


# ===========================================================================
# Approval Grant Verification Function
# ===========================================================================


def verify_approval_grant(
    action: ValidatedActionContract,
    grant: ApprovalGrant,
    *,
    expected_authority_class: AuthorityClass,
    at: datetime,
) -> None:
    """Verify that an ApprovalGrant cryptographically authorizes a ValidatedActionContract.

    Enforces all 9 canonical verification rules:
    1. approval.action matches the candidate action;
    2. approval.mission_id matches candidate mission_id;
    3. approval.action_id matches candidate action_id;
    4. approval.authority_class matches expected_authority_class;
    5. complete action semantics match (action_type, parameters, complete target identity);
    6. freshly recomputed binding hash matches stored grant.binding_hash;
    7. binding hash compared via constant-time hmac.compare_digest;
    8. validity window check: issued_at <= at < expires_at;
    9. evaluation timestamp 'at' is explicit and timezone-aware.

    Args:
        action: Candidate ValidatedActionContract.
        grant: ApprovalGrant to verify.
        expected_authority_class: The AuthorityClass required by policy.
        at: Explicit timezone-aware evaluation datetime.

    Raises:
        AuthorityPolicyTypeError: If action or at has invalid type.
        InvalidApprovalTypeError: If grant is not an ApprovalGrant instance.
        AuthorityPolicyValueError: If at is naive (not timezone-aware).
        ApprovalAuthorityClassMismatchError: If grant.authority_class != expected_authority_class.
        ApprovalBindingMismatchError: If grant action fields do not match candidate action.
        ApprovalNotYetValidError: If at < grant.issued_at.
        ApprovalExpiredError: If at >= grant.expires_at.
        ApprovalTamperedError: If constant-time hash comparison fails.
    """
    if not isinstance(action, ValidatedActionContract):
        raise AuthorityPolicyTypeError(
            f"action must be a ValidatedActionContract instance, got {type(action).__name__}"
        )
    if not isinstance(grant, ApprovalGrant):
        raise InvalidApprovalTypeError(
            f"grant must be an ApprovalGrant instance, got {type(grant).__name__}"
        )
    if not isinstance(expected_authority_class, AuthorityClass):
        raise AuthorityPolicyTypeError(
            "expected_authority_class must be an AuthorityClass instance, "
            f"got {type(expected_authority_class).__name__}"
        )
    if not isinstance(at, datetime):
        raise AuthorityPolicyTypeError(
            f"Evaluation timestamp 'at' must be a datetime instance, got {type(at).__name__}"
        )
    if at.tzinfo is None or at.utcoffset() is None:
        raise AuthorityPolicyValueError("Evaluation timestamp 'at' must be timezone-aware")

    norm_at = at if at.tzinfo == UTC else at.astimezone(UTC)

    # 1. Authority class match
    if grant.authority_class != expected_authority_class:
        raise ApprovalAuthorityClassMismatchError(
            f"Approval grant '{grant.approval_id}' authority class '{grant.authority_class.value}' "
            f"does not match expected authority class '{expected_authority_class.value}'"
        )

    # 2. Mission ID match
    if grant.mission_id != action.mission_id:
        raise ApprovalBindingMismatchError(
            f"Approval grant '{grant.approval_id}' mission_id '{grant.mission_id}' "
            f"does not match candidate action mission_id '{action.mission_id}'",
            rejection_reason=RejectionReason.MISSION_MISMATCH,
        )

    # 3. Action ID match
    if grant.action_id != action.action_id:
        raise ApprovalBindingMismatchError(
            f"Approval grant '{grant.approval_id}' action_id '{grant.action_id}' "
            f"does not match candidate action action_id '{action.action_id}'",
            rejection_reason=RejectionReason.ACTION_ID_MISMATCH,
        )

    # 4. Action Type match
    if grant.action.action_type != action.action_type:
        raise ApprovalBindingMismatchError(
            f"Approval grant '{grant.approval_id}' action_type '{grant.action.action_type.value}' "
            f"does not match candidate action action_type '{action.action_type.value}'",
            rejection_reason=RejectionReason.ACTION_TYPE_MISMATCH,
        )

    # 5. Parameters match (never echoing parameter values)
    if grant.action.parameters != action.parameters:
        raise ApprovalBindingMismatchError(
            f"Approval grant '{grant.approval_id}' parameters do not match action parameters",
            rejection_reason=RejectionReason.PARAMETERS_MISMATCH,
        )

    # 6. TargetIdentity match (safe structural facts only; never echo raw target identifiers)
    if grant.action.target.system != action.target.system:
        raise ApprovalBindingMismatchError(
            f"Approval grant '{grant.approval_id}' target system does not match "
            "candidate action target system",
            rejection_reason=RejectionReason.TARGET_SYSTEM_MISMATCH,
        )
    if grant.action.target.resource_kind != action.target.resource_kind:
        raise ApprovalBindingMismatchError(
            f"Approval grant '{grant.approval_id}' target resource_kind does not match "
            "candidate action target resource_kind",
            rejection_reason=RejectionReason.TARGET_RESOURCE_KIND_MISMATCH,
        )
    if grant.action.target.resource_id != action.target.resource_id:
        raise ApprovalBindingMismatchError(
            f"Approval grant '{grant.approval_id}' target resource_id does not match "
            "candidate action target resource_id",
            rejection_reason=RejectionReason.TARGET_RESOURCE_ID_MISMATCH,
        )
    if grant.action.target.parent_id != action.target.parent_id:
        raise ApprovalBindingMismatchError(
            f"Approval grant '{grant.approval_id}' target parent_id does not match "
            "candidate action target parent_id",
            rejection_reason=RejectionReason.TARGET_PARENT_ID_MISMATCH,
        )

    # 7. Exact ActionContract identity match
    if grant.action != action.action:
        raise ApprovalBindingMismatchError(
            f"Approval grant '{grant.approval_id}' bound action does not match candidate action",
            rejection_reason=RejectionReason.MISSION_MISMATCH,
        )

    # 8. Validity window checks: issued_at <= at < expires_at
    if norm_at < grant.issued_at:
        raise ApprovalNotYetValidError(
            f"Approval grant '{grant.approval_id}' is not yet valid: "
            f"issued_at={grant.issued_at.isoformat()} > evaluated_at={norm_at.isoformat()}"
        )
    if norm_at >= grant.expires_at:
        raise ApprovalExpiredError(
            f"Approval grant '{grant.approval_id}' has expired: "
            f"expires_at={grant.expires_at.isoformat()} <= evaluated_at={norm_at.isoformat()}"
        )

    # 9. Freshly recompute binding hash from candidate action + expected class + grant timestamps
    expected_hash = compute_approval_binding_hash(
        action=action.action,
        authority_class=expected_authority_class,
        issued_at=grant.issued_at,
        expires_at=grant.expires_at,
    )

    # Constant-time comparison
    if not hmac.compare_digest(grant.binding_hash.value, expected_hash.value):
        raise ApprovalTamperedError(
            f"Approval grant '{grant.approval_id}' binding hash verification failed"
        )


# ===========================================================================
# Authority Evaluation Functions
# ===========================================================================


def evaluate_authority(
    action: ValidatedActionContract,
    *,
    approval: ApprovalGrant | None = None,
    at: datetime,
    raise_on_rejection: bool = False,
) -> AuthorityDecision:
    """Evaluate whether a ValidatedActionContract is authorized at an explicit observation time.

    Performs classification and approval verification without executing actions or
    mutating ledger state.

    Args:
        action: The candidate ValidatedActionContract.
        approval: Optional ApprovalGrant (required for REVERSIBLE_APPROVAL_REQUIRED).
        at: Explicit timezone-aware evaluation datetime.
        raise_on_rejection: If True, raises a typed AuthorityPolicyError instead of returning
            a BLOCKED or APPROVAL_REQUIRED AuthorityDecision.

    Returns:
        AuthorityDecision indicating authorization status, authority class, and reason.

    Raises:
        AuthorityPolicyTypeError: If action or at has invalid type.
        InvalidApprovalTypeError: If approval is neither None nor an ApprovalGrant instance.
        AuthorityPolicyValueError: If at is naive (not timezone-aware).
        AuthorityPolicyError: If raise_on_rejection is True and the action is not authorized.
    """
    if not isinstance(action, ValidatedActionContract):
        assert_not_planner_for_authority(action, parameter_name="action")
        raise AuthorityPolicyTypeError(
            f"action must be a ValidatedActionContract instance, got {type(action).__name__}"
        )
    if approval is not None:
        assert_not_planner_for_authority(approval, parameter_name="approval")
        if not isinstance(approval, ApprovalGrant):
            raise InvalidApprovalTypeError(
                f"approval must be an ApprovalGrant instance or None, got {type(approval).__name__}"
            )
    if not isinstance(at, datetime):
        raise AuthorityPolicyTypeError(
            f"Evaluation timestamp 'at' must be a datetime instance, got {type(at).__name__}"
        )
    if at.tzinfo is None or at.utcoffset() is None:
        raise AuthorityPolicyValueError("Evaluation timestamp 'at' must be timezone-aware")

    norm_at = at if at.tzinfo == UTC else at.astimezone(UTC)
    auth_class = classify_authority(action)

    # Rule 1: IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED is never auto-authorized
    if auth_class == AuthorityClass.IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED:
        decision = AuthorityDecision(
            status=AuthorityDecisionStatus.BLOCKED,
            authority_class=auth_class,
            action_id=action.action_id,
            mission_id=action.mission_id,
            action_type=action.action_type,
            evaluated_at=norm_at,
            approval_id=approval.approval_id if approval is not None else None,
            reason=(
                f"Action '{action.action_type.value}' requires authority class "
                f"'{auth_class.value}', which cannot be automatically authorized by grant"
            ),
            rejection_reason=RejectionReason.IRREVERSIBLE_ACTION_BLOCKED,
        )
        if raise_on_rejection:
            decision.raise_for_status()
        return decision

    # Rule 2: READ_ONLY and REVERSIBLE_AUTO require NO approval
    if auth_class in {AuthorityClass.READ_ONLY, AuthorityClass.REVERSIBLE_AUTO}:
        if approval is not None:
            # Unexpected approval grant fails closed
            decision = AuthorityDecision(
                status=AuthorityDecisionStatus.BLOCKED,
                authority_class=auth_class,
                action_id=action.action_id,
                mission_id=action.mission_id,
                action_type=action.action_type,
                evaluated_at=norm_at,
                approval_id=approval.approval_id,
                reason=(
                    f"Unexpected approval grant for action '{action.action_type.value}' "
                    f"requiring authority class '{auth_class.value}', which requires no approval"
                ),
                rejection_reason=RejectionReason.UNEXPECTED_APPROVAL_GRANT,
            )
            if raise_on_rejection:
                decision.raise_for_status()
            return decision

        return AuthorityDecision(
            status=AuthorityDecisionStatus.AUTHORIZED_NO_APPROVAL_REQUIRED,
            authority_class=auth_class,
            action_id=action.action_id,
            mission_id=action.mission_id,
            action_type=action.action_type,
            evaluated_at=norm_at,
            approval_id=None,
            reason=None,
            rejection_reason=None,
        )

    # Rule 3: REVERSIBLE_APPROVAL_REQUIRED and EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED
    # require exact bound approval
    if approval is None:
        decision = AuthorityDecision(
            status=AuthorityDecisionStatus.APPROVAL_REQUIRED,
            authority_class=auth_class,
            action_id=action.action_id,
            mission_id=action.mission_id,
            action_type=action.action_type,
            evaluated_at=norm_at,
            approval_id=None,
            reason=(
                f"Action '{action.action_type.value}' requires authority class "
                f"'{auth_class.value}', but no approval grant was supplied"
            ),
            rejection_reason=RejectionReason.APPROVAL_REQUIRED,
        )
        if raise_on_rejection:
            decision.raise_for_status()
        return decision

    # Approval was supplied: verify strictly
    try:
        verify_approval_grant(
            action=action,
            grant=approval,
            expected_authority_class=auth_class,
            at=norm_at,
        )
    except ApprovalAuthorityClassMismatchError as exc:
        decision = AuthorityDecision(
            status=AuthorityDecisionStatus.BLOCKED,
            authority_class=auth_class,
            action_id=action.action_id,
            mission_id=action.mission_id,
            action_type=action.action_type,
            evaluated_at=norm_at,
            approval_id=approval.approval_id,
            reason=str(exc),
            rejection_reason=RejectionReason.AUTHORITY_CLASS_MISMATCH,
        )
        if raise_on_rejection:
            raise
        return decision
    except ApprovalNotYetValidError as exc:
        decision = AuthorityDecision(
            status=AuthorityDecisionStatus.BLOCKED,
            authority_class=auth_class,
            action_id=action.action_id,
            mission_id=action.mission_id,
            action_type=action.action_type,
            evaluated_at=norm_at,
            approval_id=approval.approval_id,
            reason=str(exc),
            rejection_reason=RejectionReason.APPROVAL_NOT_YET_VALID,
        )
        if raise_on_rejection:
            raise
        return decision
    except ApprovalExpiredError as exc:
        decision = AuthorityDecision(
            status=AuthorityDecisionStatus.BLOCKED,
            authority_class=auth_class,
            action_id=action.action_id,
            mission_id=action.mission_id,
            action_type=action.action_type,
            evaluated_at=norm_at,
            approval_id=approval.approval_id,
            reason=str(exc),
            rejection_reason=RejectionReason.APPROVAL_EXPIRED,
        )
        if raise_on_rejection:
            raise
        return decision
    except ApprovalTamperedError as exc:
        decision = AuthorityDecision(
            status=AuthorityDecisionStatus.BLOCKED,
            authority_class=auth_class,
            action_id=action.action_id,
            mission_id=action.mission_id,
            action_type=action.action_type,
            evaluated_at=norm_at,
            approval_id=approval.approval_id,
            reason=str(exc),
            rejection_reason=RejectionReason.BINDING_HASH_MISMATCH,
        )
        if raise_on_rejection:
            raise
        return decision
    except ApprovalBindingMismatchError as exc:
        msg = str(exc)
        if exc.rejection_reason is not None:
            rej = exc.rejection_reason
        elif "mission_id" in msg:
            rej = RejectionReason.MISSION_MISMATCH
        elif "action_id" in msg:
            rej = RejectionReason.ACTION_ID_MISMATCH
        elif "action_type" in msg:
            rej = RejectionReason.ACTION_TYPE_MISMATCH
        elif "parameters" in msg:
            rej = RejectionReason.PARAMETERS_MISMATCH
        elif "target system" in msg:
            rej = RejectionReason.TARGET_SYSTEM_MISMATCH
        elif "target resource_kind" in msg:
            rej = RejectionReason.TARGET_RESOURCE_KIND_MISMATCH
        elif "target resource_id" in msg:
            rej = RejectionReason.TARGET_RESOURCE_ID_MISMATCH
        elif "target parent_id" in msg:
            rej = RejectionReason.TARGET_PARENT_ID_MISMATCH
        else:
            rej = RejectionReason.MISSION_MISMATCH

        decision = AuthorityDecision(
            status=AuthorityDecisionStatus.BLOCKED,
            authority_class=auth_class,
            action_id=action.action_id,
            mission_id=action.mission_id,
            action_type=action.action_type,
            evaluated_at=norm_at,
            approval_id=approval.approval_id,
            reason=msg,
            rejection_reason=rej,
        )
        if raise_on_rejection:
            raise
        return decision

    # All checks passed: authorized by bound approval
    return AuthorityDecision(
        status=AuthorityDecisionStatus.AUTHORIZED_BY_BOUND_APPROVAL,
        authority_class=auth_class,
        action_id=action.action_id,
        mission_id=action.mission_id,
        action_type=action.action_type,
        evaluated_at=norm_at,
        approval_id=approval.approval_id,
        reason=None,
        rejection_reason=None,
    )


def verify_authority(
    action: ValidatedActionContract,
    *,
    approval: ApprovalGrant | None = None,
    at: datetime,
    raise_on_rejection: bool = False,
) -> AuthorityDecision:
    """Canonical alias for evaluate_authority."""
    return evaluate_authority(
        action=action,
        approval=approval,
        at=at,
        raise_on_rejection=raise_on_rejection,
    )


def assert_authorized(
    action: ValidatedActionContract,
    *,
    approval: ApprovalGrant | None = None,
    at: datetime,
) -> AuthorityDecision:
    """Assert that a ValidatedActionContract is authorized, raising typed error if not."""
    return evaluate_authority(
        action=action,
        approval=approval,
        at=at,
        raise_on_rejection=True,
    )


__all__ = [
    "ACTION_AUTHORITY_POLICY_TABLE",
    "ACTION_AUTHORITY_TABLE",
    "ActionAuthorityPolicy",
    "ApprovalAuthorityClassMismatchError",
    "ApprovalBindingMismatchError",
    "ApprovalExpiredError",
    "ApprovalNotYetValidError",
    "ApprovalRequiredError",
    "ApprovalTamperedError",
    "AuthorityBlockedError",
    "AuthorityDecision",
    "AuthorityDecisionCode",
    "AuthorityDecisionStatus",
    "AuthorityPolicyError",
    "AuthorityPolicyTypeError",
    "AuthorityPolicyValueError",
    "DEFAULT_AUTHORITY_DECISION_COMPONENT",
    "InvalidApprovalTypeError",
    "IrreversibleActionBlockedError",
    "PlannerAuthorityError",
    "RejectionReason",
    "UnexpectedApprovalGrantError",
    "UnsupportedActionTypeError",
    "assert_authorized",
    "assert_not_planner_for_authority",
    "classify_authority",
    "evaluate_authority",
    "get_action_authority_policy",
    "get_authority_policy",
    "verify_approval_grant",
    "verify_authority",
]
