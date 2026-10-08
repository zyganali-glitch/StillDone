"""Deterministic execution authority gate and unapproved mutation prevention.

Phase P-11.05:
Proves that a canonical existing-event CALENDAR_UPDATE that requires approval
MUST remain NOT_RUN before valid approval is granted and consumed.

Core Architectural Laws:
- NO APPROVAL != FAILED EXECUTION. It means: NOT_RUN.
- The provider mutation must not be attempted (provider update invocation count == 0).
- Model / planner proposals have ZERO authority to bypass or alter the approval gate.
- Arbitrary "user approved" prose or conversational strings cannot act as authority.
- No execution attempt evidence is fabricated for unattempted actions (attempt is None).
- No retry budget is consumed by NOT_RUN actions.
- PendingApproval remains PENDING.
- Mission does NOT become READY.
- P-11.06 approved execution path remains strictly unexercised and unimplemented in P-11.05.
"""

from __future__ import annotations

import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from stilldone.action_policy import ValidatedActionContract, validate_action_contract
from stilldone.adapters.calendar import (
    CalendarReadResult,
    CalendarReadStatus,
)
from stilldone.approval_consumption import ApprovalLedger
from stilldone.authority_policy import (
    ActionAuthorityPolicy,
    AuthorityPolicyTypeError,
    AuthorityPolicyValueError,
    PlannerAuthorityError,
    assert_not_planner_for_authority,
    get_action_authority_policy,
)
from stilldone.domain.action import ActionContract, ActionId, ActionType
from stilldone.domain.authority import ApprovalGrant, AuthorityClass
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.attempts import create_execution_attempt
from stilldone.execution.router import AdapterRouter
from stilldone.execution.state import (
    ActionExecutionStatus,
    ExecutionStateTracker,
    ProviderExecutionResult,
)
from stilldone.pending_approval import (
    PendingApproval,
    PendingApprovalId,
    PendingApprovalStatus,
    compute_parameters_digest,
    compute_pending_approval_id,
)
from stilldone.redaction import redact_text
from stilldone.serialization import to_canonical_primitive

# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class ExecutionGateError(Exception):
    """Base exception for execution authority gate operations."""


class ExecutionGateTypeError(ExecutionGateError, TypeError):
    """Raised when an argument has an invalid type."""


class ExecutionGateValueError(ExecutionGateError, ValueError):
    """Raised when an argument has an invalid value."""


class PlannerGateAuthorityError(ExecutionGateTypeError, PlannerAuthorityError):
    """Raised when a model/planner proposal object is passed into the execution gate."""


class UnapprovedMutationBlockedError(ExecutionGateError):
    """Raised when an assertive gate rejects an unapproved mutation action."""


class UnexpectedApprovalGrantError(ExecutionGateValueError):
    """Raised when an ApprovalGrant is supplied for an action that does not require approval."""


class PendingApprovalBindingMismatchError(ExecutionGateValueError):
    """Raised when a PendingApproval does not match the candidate action binding."""


# ===========================================================================
# Deep Immutability & Sanitization Helpers
# ===========================================================================


def _deep_freeze_mapping(val: Any) -> Any:
    """Recursively freeze mappings, sequences, and sets to ensure deep immutability."""
    if isinstance(val, Mapping):
        return types.MappingProxyType({k: _deep_freeze_mapping(v) for k, v in val.items()})
    if isinstance(val, (list, tuple)):
        return tuple(_deep_freeze_mapping(v) for v in val)
    if isinstance(val, set):
        return frozenset(_deep_freeze_mapping(v) for v in val)
    return val


def _sanitize_summary_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively sanitize mapping values for privacy-safe serialization."""
    sanitized: dict[str, Any] = {}
    for k, v in mapping.items():
        if isinstance(v, str):
            sanitized[k] = redact_text(v)
        elif isinstance(v, Mapping):
            sanitized[k] = _sanitize_summary_mapping(v)
        elif isinstance(v, (list, tuple)):
            sanitized[k] = [
                redact_text(item)
                if isinstance(item, str)
                else _sanitize_summary_mapping(item)
                if isinstance(item, Mapping)
                else item
                for item in v
            ]
        else:
            sanitized[k] = to_canonical_primitive(v)
    return sanitized


# ===========================================================================
# Execution Gate Decision Model
# ===========================================================================


@dataclass(frozen=True)
class ExecutionGateDecision:
    """Immutable result of evaluating the execution authority gate for an action.

    Captures:
    - action_id: Identity of the target action.
    - action_type: Canonical ActionType.
    - authority_class: Required AuthorityClass from frozen policy.
    - status: Deterministic execution status (e.g. NOT_RUN when unapproved).
    - is_authorized: True only if the action is authorized to proceed to execution.
    - reason: Human-readable deterministic explanation of gate evaluation.
    - pending_approval_id: Optional ID of the associated PendingApproval object.
    - evaluated_at: Explicit timezone-aware UTC observation timestamp.
    - attempt: Optional ExecutionAttempt (strictly None for NOT_RUN).
    - provider_result: Optional ProviderExecutionResult (strictly None for NOT_RUN).
    """

    action_id: ActionId
    action_type: ActionType
    authority_class: AuthorityClass
    status: ActionExecutionStatus
    is_authorized: bool
    reason: str
    evaluated_at: datetime
    pending_approval_id: PendingApprovalId | None = None
    attempt: ExecutionAttempt | None = None
    provider_result: ProviderExecutionResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, ActionId):
            raise ExecutionGateTypeError(
                f"action_id must be an ActionId, got {type(self.action_id).__name__}"
            )
        if not isinstance(self.action_type, ActionType):
            raise ExecutionGateTypeError(
                f"action_type must be an ActionType, got {type(self.action_type).__name__}"
            )
        if not isinstance(self.authority_class, AuthorityClass):
            ac_name = type(self.authority_class).__name__
            msg = f"authority_class must be an AuthorityClass, got {ac_name}"
            raise ExecutionGateTypeError(msg)
        if not isinstance(self.status, ActionExecutionStatus):
            raise ExecutionGateTypeError(
                f"status must be an ActionExecutionStatus, got {type(self.status).__name__}"
            )
        if type(self.is_authorized) is not bool:
            raise ExecutionGateTypeError("is_authorized must be a bool")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ExecutionGateValueError("reason must be a non-empty string")
        if not isinstance(self.evaluated_at, datetime):
            raise ExecutionGateTypeError(
                f"evaluated_at must be a datetime, got {type(self.evaluated_at).__name__}"
            )
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ExecutionGateValueError("evaluated_at must be timezone-aware")
        if self.evaluated_at.tzinfo != UTC:
            object.__setattr__(self, "evaluated_at", self.evaluated_at.astimezone(UTC))

        if self.pending_approval_id is not None and not isinstance(
            self.pending_approval_id, PendingApprovalId
        ):
            raise ExecutionGateTypeError(
                "pending_approval_id must be a PendingApprovalId or None, "
                f"got {type(self.pending_approval_id).__name__}"
            )

        # Core StillDone Invariant:
        # When status is NOT_RUN:
        # - is_authorized MUST be False.
        # - attempt MUST be None (no attempt evidence fabricated).
        # - provider_result MUST be None (no provider call attempted).
        if self.status == ActionExecutionStatus.NOT_RUN:
            if self.is_authorized:
                raise ExecutionGateValueError("NOT_RUN action cannot have is_authorized=True")
            if self.attempt is not None:
                raise ExecutionGateValueError(
                    "NOT_RUN action cannot have an ExecutionAttempt (no attempt may be fabricated)"
                )
            if self.provider_result is not None:
                raise ExecutionGateValueError(
                    "NOT_RUN action cannot have a ProviderExecutionResult "
                    "(provider call was not run)"
                )

        if self.attempt is not None and not isinstance(self.attempt, ExecutionAttempt):
            raise ExecutionGateTypeError(
                f"attempt must be an ExecutionAttempt or None, got {type(self.attempt).__name__}"
            )
        if self.provider_result is not None and not isinstance(
            self.provider_result, ProviderExecutionResult
        ):
            raise ExecutionGateTypeError(
                "provider_result must be a ProviderExecutionResult or None, "
                f"got {type(self.provider_result).__name__}"
            )

    @property
    def is_not_run(self) -> bool:
        """True if the action remained in NOT_RUN state."""
        return self.status == ActionExecutionStatus.NOT_RUN

    def to_dict(self) -> dict[str, Any]:
        """Convert decision to a serializable dictionary."""
        return {
            "action_id": str(self.action_id),
            "action_type": self.action_type.value,
            "authority_class": self.authority_class.value,
            "status": self.status.value,
            "is_authorized": self.is_authorized,
            "reason": self.reason,
            "pending_approval_id": (
                self.pending_approval_id.value if self.pending_approval_id else None
            ),
            "evaluated_at": self.evaluated_at.isoformat(),
            "attempt_present": self.attempt is not None,
            "provider_result_present": self.provider_result is not None,
        }


# ===========================================================================
# Unapproved Action Receipt Model
# ===========================================================================


@dataclass(frozen=True)
class UnapprovedActionReceipt:
    """Immutable evidence receipt proving an unapproved mutation remained NOT_RUN.

    Captures complete deterministic authority facts and provider truth:
    - exact source SHA (40 hex characters);
    - mission ID;
    - action ID;
    - action type;
    - authority class;
    - target event identity in privacy-safe form;
    - pending approval ID;
    - approval status = PENDING;
    - grant absent;
    - consumption absent;
    - execution state = NOT_RUN;
    - provider mutation invocation count == 0;
    - before read provenance;
    - after read provenance;
    - relevant before/after state comparison proving unchanged external state;
    - no READY claim;
    - evidence provenance;
    - recorded timestamp.
    """

    source_sha: str
    mission_id: MissionId
    action_id: ActionId
    action_type: ActionType
    authority_class: AuthorityClass
    target_event_id: str
    pending_approval_id: PendingApprovalId
    approval_status: PendingApprovalStatus
    grant_present: bool
    consumption_present: bool
    execution_state: ActionExecutionStatus
    provider_mutation_invocations: int
    before_read_provenance: EvidenceProvenance
    after_read_provenance: EvidenceProvenance
    before_state_summary: Mapping[str, Any]
    after_state_summary: Mapping[str, Any]
    state_unchanged: bool
    is_ready_claimed: bool
    provenance: EvidenceProvenance
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.source_sha, str) or not self.source_sha.strip():
            raise ExecutionGateValueError("source_sha must be a non-empty string")
        sha_clean = self.source_sha.strip().lower()
        if len(sha_clean) != 40 or not all(c in "0123456789abcdef" for c in sha_clean):
            raise ExecutionGateValueError(
                "source_sha must be a 40-character hexadecimal git commit SHA"
            )
        object.__setattr__(self, "source_sha", sha_clean)

        if not isinstance(self.mission_id, MissionId):
            raise ExecutionGateTypeError(
                f"mission_id must be a MissionId, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.action_id, ActionId):
            raise ExecutionGateTypeError(
                f"action_id must be an ActionId, got {type(self.action_id).__name__}"
            )
        if not isinstance(self.action_type, ActionType):
            raise ExecutionGateTypeError(
                f"action_type must be an ActionType, got {type(self.action_type).__name__}"
            )
        if not isinstance(self.authority_class, AuthorityClass):
            ac_name = type(self.authority_class).__name__
            msg = f"authority_class must be an AuthorityClass, got {ac_name}"
            raise ExecutionGateTypeError(msg)
        if not isinstance(self.target_event_id, str) or not self.target_event_id.strip():
            raise ExecutionGateValueError("target_event_id must be a non-empty string")
        if not isinstance(self.pending_approval_id, PendingApprovalId):
            raise ExecutionGateTypeError(
                "pending_approval_id must be a PendingApprovalId, "
                f"got {type(self.pending_approval_id).__name__}"
            )
        if not isinstance(self.approval_status, PendingApprovalStatus):
            raise ExecutionGateTypeError(
                "approval_status must be a PendingApprovalStatus, "
                f"got {type(self.approval_status).__name__}"
            )
        if type(self.grant_present) is not bool:
            raise ExecutionGateTypeError("grant_present must be a bool")
        if type(self.consumption_present) is not bool:
            raise ExecutionGateTypeError("consumption_present must be a bool")
        if not isinstance(self.execution_state, ActionExecutionStatus):
            raise ExecutionGateTypeError(
                "execution_state must be an ActionExecutionStatus, "
                f"got {type(self.execution_state).__name__}"
            )
        if (
            isinstance(self.provider_mutation_invocations, bool)
            or not isinstance(self.provider_mutation_invocations, int)
            or self.provider_mutation_invocations < 0
        ):
            raise ExecutionGateValueError("provider_mutation_invocations must be non-negative int")
        if not isinstance(self.before_read_provenance, EvidenceProvenance):
            raise ExecutionGateTypeError(
                "before_read_provenance must be an EvidenceProvenance, "
                f"got {type(self.before_read_provenance).__name__}"
            )
        if not isinstance(self.after_read_provenance, EvidenceProvenance):
            raise ExecutionGateTypeError(
                "after_read_provenance must be an EvidenceProvenance, "
                f"got {type(self.after_read_provenance).__name__}"
            )
        if not isinstance(self.before_state_summary, Mapping):
            raise ExecutionGateTypeError("before_state_summary must be a Mapping")
        if not isinstance(self.after_state_summary, Mapping):
            raise ExecutionGateTypeError("after_state_summary must be a Mapping")
        if type(self.state_unchanged) is not bool:
            raise ExecutionGateTypeError("state_unchanged must be a bool")
        if type(self.is_ready_claimed) is not bool:
            raise ExecutionGateTypeError("is_ready_claimed must be a bool")
        if not isinstance(self.provenance, EvidenceProvenance):
            raise ExecutionGateTypeError(
                f"provenance must be an EvidenceProvenance, got {type(self.provenance).__name__}"
            )
        if not isinstance(self.recorded_at, datetime):
            raise ExecutionGateTypeError(
                f"recorded_at must be a datetime, got {type(self.recorded_at).__name__}"
            )
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ExecutionGateValueError("recorded_at must be timezone-aware")
        if self.recorded_at.tzinfo != UTC:
            object.__setattr__(self, "recorded_at", self.recorded_at.astimezone(UTC))

        # Deep freeze state summaries to guarantee complete immutability
        object.__setattr__(
            self, "before_state_summary", _deep_freeze_mapping(self.before_state_summary)
        )
        object.__setattr__(
            self, "after_state_summary", _deep_freeze_mapping(self.after_state_summary)
        )

        # Invariant validations for P-11.05 receipt:
        if self.approval_status != PendingApprovalStatus.PENDING:
            msg = (
                "P-11.05 receipt requires approval_status=PENDING, "
                f"got {self.approval_status.value}"
            )
            raise ExecutionGateValueError(msg)
        if self.grant_present:
            raise ExecutionGateValueError("P-11.05 receipt requires grant_present=False")
        if self.consumption_present:
            raise ExecutionGateValueError("P-11.05 receipt requires consumption_present=False")
        if self.execution_state != ActionExecutionStatus.NOT_RUN:
            msg = (
                "P-11.05 receipt requires execution_state=NOT_RUN, "
                f"got {self.execution_state.value}"
            )
            raise ExecutionGateValueError(msg)
        if self.provider_mutation_invocations != 0:
            raise ExecutionGateValueError(
                f"P-11.05 receipt requires provider_mutation_invocations=0, "
                f"got {self.provider_mutation_invocations}"
            )
        if not self.state_unchanged:
            raise ExecutionGateValueError("P-11.05 receipt requires state_unchanged=True")
        if self.is_ready_claimed:
            raise ExecutionGateValueError("P-11.05 receipt requires is_ready_claimed=False")

        # Zero false-live claims: Fixture proof must NOT claim LIVE_*
        live_provenances = (
            EvidenceProvenance.LIVE_AWS,
            EvidenceProvenance.LIVE_GOOGLE,
            EvidenceProvenance.LIVE_EXTERNAL,
        )
        if self.provenance in live_provenances:
            raise ExecutionGateValueError(
                f"P-11.05 fixture proof cannot claim live provenance '{self.provenance.value}'"
            )
        if self.before_read_provenance in live_provenances:
            raise ExecutionGateValueError(
                "before_read_provenance cannot claim live provenance without exercised live access"
            )
        if self.after_read_provenance in live_provenances:
            raise ExecutionGateValueError(
                "after_read_provenance cannot claim live provenance without exercised live access"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert receipt to a serializable, privacy-safe dictionary."""
        return {
            "source_sha": self.source_sha,
            "mission_id": str(self.mission_id),
            "action_id": str(self.action_id),
            "action_type": self.action_type.value,
            "authority_class": self.authority_class.value,
            "target_event_id": redact_text(self.target_event_id),
            "pending_approval_id": self.pending_approval_id.value,
            "approval_status": self.approval_status.value,
            "grant_present": self.grant_present,
            "consumption_present": self.consumption_present,
            "execution_state": self.execution_state.value,
            "provider_mutation_invocations": self.provider_mutation_invocations,
            "before_read_provenance": self.before_read_provenance.value,
            "after_read_provenance": self.after_read_provenance.value,
            "before_state_summary": _sanitize_summary_mapping(self.before_state_summary),
            "after_state_summary": _sanitize_summary_mapping(self.after_state_summary),
            "state_unchanged": self.state_unchanged,
            "is_ready_claimed": self.is_ready_claimed,
            "provenance": self.provenance.value,
            "recorded_at": self.recorded_at.isoformat(),
        }


# ===========================================================================
# Core Execution Gate Evaluation Function
# ===========================================================================


def evaluate_execution_gate(
    action: ValidatedActionContract | ActionContract,
    *,
    approval: ApprovalGrant | None = None,
    pending_approval: PendingApproval | None = None,
    at: datetime | None = None,
) -> ExecutionGateDecision:
    """Evaluate whether an action is authorized to execute or must remain NOT_RUN.

    Enforces:
    1. Reject model/planner proposal objects fail-closed (PlannerGateAuthorityError).
    2. Reject arbitrary prose, conversational strings, or unvalidated inputs fail-closed
       with static, privacy-safe error messages (no raw value reflection).
    3. Self-validate action contract under action policy (ValidatedActionContract).
    4. Query frozen P-11.01 ActionAuthorityPolicy:
       - If action requires bound approval (CALENDAR_UPDATE):
         * If approval is None: returns ActionExecutionStatus.NOT_RUN with is_authorized=False.
           Crucially: Does NOT mark execution as FAILED. Does NOT attempt provider call.
         * If approval is provided: raises NotImplementedError because P-11.06 approved
           execution path is strictly pending authorization and NOT implemented here.
       - If action does not require bound approval (READ_ONLY, REVERSIBLE_AUTO):
         * If approval grant is unexpectedly provided: raises UnexpectedApprovalGrantError.
         * Returns is_authorized=True, eligible for execution.

    Args:
        action: ValidatedActionContract or ActionContract.
        approval: Optional ApprovalGrant (strictly None for P-11.05 unapproved proof).
        pending_approval: Optional PendingApproval object.
        at: Optional timezone-aware UTC datetime.

    Returns:
        ExecutionGateDecision capturing authorization status and deterministic reason.
    """
    # 1. Model / planner injection guards
    try:
        assert_not_planner_for_authority(action, parameter_name="action")
        if approval is not None:
            assert_not_planner_for_authority(approval, parameter_name="approval")
        if pending_approval is not None:
            assert_not_planner_for_authority(pending_approval, parameter_name="pending_approval")
    except PlannerAuthorityError as exc:
        raise PlannerGateAuthorityError(str(exc)) from None

    # 2. Reject arbitrary string/prose decisions with static, bounded, privacy-safe messages
    if isinstance(action, str):
        raise AuthorityPolicyTypeError(
            "String or conversational prose cannot act as authority gate action; "
            "must be a canonical ActionContract or ValidatedActionContract"
        ) from None
    if isinstance(approval, str):
        raise AuthorityPolicyTypeError(
            "String prose cannot act as an ApprovalGrant; "
            "model/conversational text has ZERO authority"
        ) from None

    # 3. Action validation
    if isinstance(action, ValidatedActionContract):
        validated = action
    elif isinstance(action, ActionContract):
        validated = validate_action_contract(action)
    else:
        raise ExecutionGateTypeError(
            f"action must be ActionContract or ValidatedActionContract, got {type(action).__name__}"
        ) from None

    # 4. Approval object type validation
    if approval is not None and not isinstance(approval, ApprovalGrant):
        raise ExecutionGateTypeError(
            f"approval must be an ApprovalGrant or None, got {type(approval).__name__}"
        ) from None

    # 5. Timestamp normalization
    now = at or datetime.now(UTC)
    if not isinstance(now, datetime):
        raise ExecutionGateTypeError("Evaluation timestamp 'at' must be a datetime") from None
    if now.tzinfo is None or now.utcoffset() is None:
        raise AuthorityPolicyValueError(
            "Evaluation timestamp 'at' must be timezone-aware"
        ) from None
    norm_at = now if now.tzinfo == UTC else now.astimezone(UTC)

    # 6. Resolve frozen authority policy from P-11.01
    policy: ActionAuthorityPolicy = get_action_authority_policy(validated.action_type)

    # 7. Validate pending_approval if supplied against complete exact action binding
    paid: PendingApprovalId | None = None
    if pending_approval is not None:
        if not isinstance(pending_approval, PendingApproval):
            raise ExecutionGateTypeError(
                "pending_approval must be a PendingApproval instance, "
                f"got {type(pending_approval).__name__}"
            ) from None
        if pending_approval.action_id != validated.action_id:
            raise PendingApprovalBindingMismatchError(
                "PendingApproval action_id does not match candidate action action_id"
            ) from None
        if pending_approval.mission_id != validated.mission_id:
            raise PendingApprovalBindingMismatchError(
                "PendingApproval mission_id does not match candidate action mission_id"
            ) from None
        if pending_approval.action_type != validated.action_type:
            raise PendingApprovalBindingMismatchError(
                "PendingApproval action_type does not match candidate action action_type"
            ) from None
        if pending_approval.authority_class != policy.authority_class:
            raise PendingApprovalBindingMismatchError(
                "PendingApproval authority_class does not match policy authority_class"
            ) from None
        if pending_approval.target != validated.target:
            raise PendingApprovalBindingMismatchError(
                "PendingApproval target does not match candidate action target"
            ) from None
        if pending_approval.parameters != validated.parameters:
            raise PendingApprovalBindingMismatchError(
                "PendingApproval parameters do not match candidate action parameters"
            ) from None
        if pending_approval.parameters_digest != compute_parameters_digest(validated.parameters):
            raise PendingApprovalBindingMismatchError(
                "PendingApproval parameters_digest does not match computed parameters digest"
            ) from None
        if pending_approval.status != PendingApprovalStatus.PENDING:
            raise PendingApprovalBindingMismatchError(
                "PendingApproval status must be PENDING"
            ) from None

        computed_paid = compute_pending_approval_id(
            mission_id=validated.mission_id,
            action_id=validated.action_id,
            action_type=validated.action_type,
            authority_class=policy.authority_class,
            target=validated.target,
            parameters=validated.parameters,
        )
        if pending_approval.pending_approval_id != computed_paid:
            raise PendingApprovalBindingMismatchError(
                "PendingApproval pending_approval_id does not match computed canonical identity"
            ) from None

        paid = pending_approval.pending_approval_id

    # 8. Evaluate approval requirement
    if policy.requires_bound_approval:
        if approval is None:
            # APPROVAL ABSENT: Action MUST remain NOT_RUN
            return ExecutionGateDecision(
                action_id=validated.action_id,
                action_type=validated.action_type,
                authority_class=policy.authority_class,
                status=ActionExecutionStatus.NOT_RUN,
                is_authorized=False,
                reason=(
                    f"Action '{validated.action_type.value}' requires bound human approval "
                    f"({policy.authority_class.value}); approval is absent or not granted. "
                    "Execution must remain NOT_RUN."
                ),
                pending_approval_id=paid,
                evaluated_at=norm_at,
                attempt=None,
                provider_result=None,
            )

        # Approval is present: Enforce Rule 12 / P-11.06 lock
        # P-11.06 approved execution path is NOT implemented here!
        raise NotImplementedError(
            "P-11.06 approved execution path is not implemented in P-11.05 "
            "(P-11.06 remains PENDING / NOT AUTHORIZED / NOT_RUN)"
        )

    # Action does not require bound approval (READ_ONLY or REVERSIBLE_AUTO)
    # Reject unexpected approval grant before any state change
    if approval is not None:
        raise UnexpectedApprovalGrantError(
            f"Unexpected ApprovalGrant provided for action that does not require approval "
            f"({validated.action_type.value} has authority class {policy.authority_class.value})"
        ) from None

    return ExecutionGateDecision(
        action_id=validated.action_id,
        action_type=validated.action_type,
        authority_class=policy.authority_class,
        status=ActionExecutionStatus.IN_PROGRESS,
        is_authorized=True,
        reason=(
            f"Action '{validated.action_type.value}' is authorized without human approval "
            f"({policy.authority_class.value})."
        ),
        pending_approval_id=paid,
        evaluated_at=norm_at,
        attempt=None,
        provider_result=None,
    )


# ===========================================================================
# Execution Coordination via Authority Gate
# ===========================================================================


def execute_gated_action(
    action: ValidatedActionContract | ActionContract,
    router: AdapterRouter,
    *,
    tracker: ExecutionStateTracker | None = None,
    attempt_generator: Callable[[ActionId], ExecutionAttempt] | None = None,
    approval: ApprovalGrant | None = None,
    pending_approval: PendingApproval | None = None,
    at: datetime | None = None,
) -> ExecutionGateDecision:
    """Coordinate the execution of an action through the authority gate.

    Enforces:
    1. If the authority gate determines NOT_RUN:
       - No ExecutionAttempt is created.
       - No provider call is made (router is NEVER called).
       - No retry budget is consumed.
       - If a tracker is supplied, records NOT_RUN with deterministic reason.
       - Crucially: action is NOT marked EXECUTION_FAILED or FAILED!
       - Returns ExecutionGateDecision with status=NOT_RUN.
    2. If the authority gate determines authorized:
       - Generates ExecutionAttempt FIRST (failing before tracker mutation if attempt fails).
       - Marks tracker in progress (if supplied).
       - Invokes router to execute action.
       - Records success or failure on tracker.
       - Returns ExecutionGateDecision with final execution status.

    Args:
        action: ValidatedActionContract or ActionContract.
        router: AdapterRouter with registered handlers.
        tracker: Optional ExecutionStateTracker.
        attempt_generator: Optional callable generating ExecutionAttempt.
        approval: Optional ApprovalGrant.
        pending_approval: Optional PendingApproval.
        at: Optional timezone-aware UTC datetime.

    Returns:
        ExecutionGateDecision capturing final state.
    """
    gate_decision = evaluate_execution_gate(
        action,
        approval=approval,
        pending_approval=pending_approval,
        at=at,
    )

    # Branch 1: Action is NOT_RUN (approval absent)
    if gate_decision.status == ActionExecutionStatus.NOT_RUN:
        if tracker is not None:
            tracker.record_not_run(action.action_id, reason=gate_decision.reason)
        # Router is NOT called; provider mutation count is strictly 0.
        return gate_decision

    # Branch 2: Action is authorized to proceed
    # Generate attempt FIRST to prevent premature IN_PROGRESS transition if attempt generation fails
    gen = attempt_generator or create_execution_attempt
    attempt = gen(action.action_id)

    if tracker is not None:
        tracker.mark_in_progress(action.action_id)

    actual_action = action.action if isinstance(action, ValidatedActionContract) else action
    provider_result = router.execute(
        actual_action,
        attempt=attempt,
        approval=approval,
        at=gate_decision.evaluated_at,
    )

    final_status: ActionExecutionStatus
    if provider_result.success:
        final_status = ActionExecutionStatus.EXECUTION_SUCCEEDED
        if tracker is not None:
            tracker.record_success(
                action.action_id,
                attempt=attempt,
                provider_result=provider_result,
            )
    else:
        final_status = ActionExecutionStatus.EXECUTION_FAILED
        if tracker is not None:
            tracker.record_failure(
                action.action_id,
                attempt=attempt,
                provider_result=provider_result,
                error_message=provider_result.error_message or "Provider execution failed",
            )

    return ExecutionGateDecision(
        action_id=action.action_id,
        action_type=action.action_type,
        authority_class=gate_decision.authority_class,
        status=final_status,
        is_authorized=True,
        reason=f"Execution completed with status {provider_result.status_name}",
        pending_approval_id=gate_decision.pending_approval_id,
        evaluated_at=gate_decision.evaluated_at,
        attempt=attempt,
        provider_result=provider_result,
    )


# ===========================================================================
# Unapproved Action Receipt Factory Function
# ===========================================================================


def create_unapproved_action_receipt(
    *,
    gate_decision: ExecutionGateDecision,
    action: ValidatedActionContract | ActionContract,
    pending_approval: PendingApproval,
    before_read: CalendarReadResult,
    after_read: CalendarReadResult,
    measured_provider_mutations: int,
    source_sha: str,
    ledger: ApprovalLedger | None = None,
    before_read_provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    after_read_provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    recorded_at: datetime | None = None,
) -> UnapprovedActionReceipt:
    """Create an immutable UnapprovedActionReceipt proving an unapproved action remained NOT_RUN.

    Enforces all P-11.05 invariants and derives facts from observed reality:
    - Binds strictly to the canonical gate decision, action, and pending approval.
    - Rejects contradictory action identity, pending identity, or gate decision.
    - Requires measured_provider_mutations == 0 from actual instrumentation.
    - Derives before and after states directly from CalendarReadResult observations.
    - Rejects mismatched before vs after states (state_unchanged must be True).
    - Verifies external state does NOT reflect the proposed mutation parameters.
    - Rejects loose unverified dictionaries or absent observations.
    - Rejects false LIVE_* provenance claims for fixture/local executions.
    - Deeply freezes all nested state payloads against post-creation mutation.
    """
    if not isinstance(gate_decision, ExecutionGateDecision):
        raise ExecutionGateTypeError(
            f"gate_decision must be an ExecutionGateDecision, got {type(gate_decision).__name__}"
        )
    if not isinstance(action, (ValidatedActionContract, ActionContract)):
        raise ExecutionGateTypeError(
            f"action must be ActionContract or ValidatedActionContract, got {type(action).__name__}"
        )
    if not isinstance(pending_approval, PendingApproval):
        raise ExecutionGateTypeError(
            f"pending_approval must be a PendingApproval, got {type(pending_approval).__name__}"
        )
    if not isinstance(before_read, CalendarReadResult):
        raise ExecutionGateTypeError(
            f"before_read must be a CalendarReadResult, got {type(before_read).__name__}"
        )
    if not isinstance(after_read, CalendarReadResult):
        raise ExecutionGateTypeError(
            f"after_read must be a CalendarReadResult, got {type(after_read).__name__}"
        )
    if isinstance(measured_provider_mutations, bool) or not isinstance(
        measured_provider_mutations, int
    ):
        mpm_name = type(measured_provider_mutations).__name__
        raise ExecutionGateTypeError(f"measured_provider_mutations must be an int, got {mpm_name}")
    if not isinstance(source_sha, str):
        raise ExecutionGateTypeError(
            f"source_sha must be a string, got {type(source_sha).__name__}"
        )

    # Gate decision validations
    if gate_decision.status != ActionExecutionStatus.NOT_RUN:
        raise ExecutionGateValueError(
            f"Receipt requires gate decision status NOT_RUN, got {gate_decision.status.value}"
        )
    if gate_decision.is_authorized:
        raise ExecutionGateValueError("Receipt requires gate decision is_authorized=False")
    if gate_decision.attempt is not None:
        raise ExecutionGateValueError("Receipt requires gate decision attempt=None")
    if gate_decision.provider_result is not None:
        raise ExecutionGateValueError("Receipt requires gate decision provider_result=None")

    # Action binding
    actual_action = action.action if isinstance(action, ValidatedActionContract) else action
    if actual_action.action_id != gate_decision.action_id:
        raise ExecutionGateValueError("Action action_id does not match gate decision action_id")
    if actual_action.action_type != gate_decision.action_type:
        raise ExecutionGateValueError("Action action_type does not match gate decision action_type")
    if actual_action.action_type != ActionType.CALENDAR_UPDATE:
        act_val = actual_action.action_type.value
        raise ExecutionGateValueError(
            f"Unapproved action receipt applies to CALENDAR_UPDATE, got {act_val}"
        )

    # Pending approval binding
    if pending_approval.status != PendingApprovalStatus.PENDING:
        raise ExecutionGateValueError(
            f"pending_approval status must be PENDING, got {pending_approval.status.value}"
        )
    if pending_approval.action_id != actual_action.action_id:
        raise ExecutionGateValueError("pending_approval action_id does not match action action_id")
    if pending_approval.mission_id != actual_action.mission_id:
        raise ExecutionGateValueError(
            "pending_approval mission_id does not match action mission_id"
        )
    if pending_approval.action_type != actual_action.action_type:
        raise ExecutionGateValueError(
            "pending_approval action_type does not match action action_type"
        )
    if pending_approval.target != actual_action.target:
        raise ExecutionGateValueError("pending_approval target does not match action target")
    if pending_approval.parameters != actual_action.parameters:
        raise ExecutionGateValueError("pending_approval parameters do not match action parameters")
    if gate_decision.pending_approval_id != pending_approval.pending_approval_id:
        raise ExecutionGateValueError(
            "gate_decision pending_approval_id does not match pending_approval"
        )

    # Measured provider mutations must come from instrumentation and be 0
    if measured_provider_mutations != 0:
        raise ExecutionGateValueError(
            f"Measured provider mutations must be 0 for NOT_RUN action, "
            f"got {measured_provider_mutations}"
        )

    # Ledger consumption verification
    if ledger is not None:
        if ledger.is_used(pending_approval.pending_approval_id.value):
            raise ExecutionGateValueError("Approval was marked used in ledger; must be unused")
        if ledger.is_consumed(pending_approval.pending_approval_id.value):
            raise ExecutionGateValueError(
                "Approval was marked consumed in ledger; must be unconsumed"
            )

    # Read observations verification
    if before_read.status != CalendarReadStatus.SUCCESS or before_read.observation is None:
        raise ExecutionGateValueError(
            f"before_read must have status SUCCESS with non-None observation, "
            f"got {before_read.status.value}"
        )
    if after_read.status != CalendarReadStatus.SUCCESS or after_read.observation is None:
        raise ExecutionGateValueError(
            f"after_read must have status SUCCESS with non-None observation, "
            f"got {after_read.status.value}"
        )

    before_obs = before_read.observation
    after_obs = after_read.observation

    if (
        before_obs.event_id != actual_action.target.resource_id
        or after_obs.event_id != actual_action.target.resource_id
    ):
        raise ExecutionGateValueError(
            "Read observations must match action target resource_id (event_id)"
        )
    if (
        before_obs.calendar_id != actual_action.target.parent_id
        or after_obs.calendar_id != actual_action.target.parent_id
    ):
        raise ExecutionGateValueError(
            "Read observations must match action target parent_id (calendar_id)"
        )

    before_summary: dict[str, Any] = {
        "summary": before_obs.summary,
        "start_time": before_obs.start_time,
        "end_time": before_obs.end_time,
        "all_day": before_obs.all_day,
        "etag": before_obs.etag,
        "status": before_obs.status,
    }
    after_summary: dict[str, Any] = {
        "summary": after_obs.summary,
        "start_time": after_obs.start_time,
        "end_time": after_obs.end_time,
        "all_day": after_obs.all_day,
        "etag": after_obs.etag,
        "status": after_obs.status,
    }

    # Verify state equality
    if before_summary != after_summary:
        raise ExecutionGateValueError(
            "Observed external event state differs between before and after reads; "
            "unapproved action must leave state unchanged"
        )

    # Verify external state does NOT reflect proposed mutation parameters
    params = actual_action.parameters.to_dict()
    if "start_time" in params and params["start_time"] != before_obs.start_time:
        if after_obs.start_time == params["start_time"]:
            raise ExecutionGateValueError(
                "External event state reflects proposed mutation start_time; mutation was executed!"
            )
    if "summary" in params and params["summary"] != before_obs.summary:
        if after_obs.summary == params["summary"]:
            raise ExecutionGateValueError(
                "External event state reflects proposed mutation summary; mutation was executed!"
            )

    now = recorded_at or datetime.now(UTC)
    norm_now = now if now.tzinfo == UTC else now.astimezone(UTC)

    return UnapprovedActionReceipt(
        source_sha=source_sha,
        mission_id=actual_action.mission_id,
        action_id=actual_action.action_id,
        action_type=actual_action.action_type,
        authority_class=gate_decision.authority_class,
        target_event_id=actual_action.target.resource_id,
        pending_approval_id=pending_approval.pending_approval_id,
        approval_status=PendingApprovalStatus.PENDING,
        grant_present=False,
        consumption_present=False,
        execution_state=ActionExecutionStatus.NOT_RUN,
        provider_mutation_invocations=0,
        before_read_provenance=before_read_provenance,
        after_read_provenance=after_read_provenance,
        before_state_summary=before_summary,
        after_state_summary=after_summary,
        state_unchanged=True,
        is_ready_claimed=False,
        provenance=provenance,
        recorded_at=norm_now,
    )


__all__ = [
    "ExecutionGateDecision",
    "ExecutionGateError",
    "ExecutionGateTypeError",
    "ExecutionGateValueError",
    "PendingApprovalBindingMismatchError",
    "PlannerGateAuthorityError",
    "UnapprovedActionReceipt",
    "UnapprovedMutationBlockedError",
    "UnexpectedApprovalGrantError",
    "create_unapproved_action_receipt",
    "evaluate_execution_gate",
    "execute_gated_action",
]
