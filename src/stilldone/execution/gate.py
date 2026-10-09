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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stilldone.action_policy import ValidatedActionContract, validate_action_contract
from stilldone.adapters.calendar import (
    CalendarReadbackResult,
    CalendarReadbackStatus,
    CalendarReadResult,
    CalendarReadStatus,
    ExpectedCalendarState,
    GoogleCalendarReadAdapter,
    GoogleCalendarReadbackVerifier,
)
from stilldone.approval_binding import verify_approval_binding
from stilldone.approval_consumption import (
    APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
    ApprovalAlreadyUsedError,
    ApprovalConsumptionRecord,
    ApprovalLedger,
    ApprovalRevokedError,
    ApprovalUsageStatus,
)
from stilldone.authority_policy import (
    ActionAuthorityPolicy,
    AuthorityPolicyTypeError,
    AuthorityPolicyValueError,
    PlannerAuthorityError,
    assert_not_planner_for_authority,
    get_action_authority_policy,
)
from stilldone.domain.action import ActionContract, ActionId, ActionType
from stilldone.domain.authority import (
    ApprovalGrant,
    ApprovalId,
    AuthorityClass,
    BindingHash,
)
from stilldone.domain.desired_state import DesiredStatePredicate
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.execution.attempts import (
    create_execution_attempt,
    record_provider_exception,
)
from stilldone.execution.router import AdapterRouter
from stilldone.execution.state import (
    ActionExecutionStatus,
    ExecutionStateTracker,
    MissionExecutionRecord,
    ProviderExecutionResult,
)
from stilldone.ledger import EvidenceRecord, MissionLedgerPort, RecordNotFoundError
from stilldone.pending_approval import (
    PendingApproval,
    PendingApprovalId,
    PendingApprovalStatus,
    compute_parameters_digest,
    compute_pending_approval_id,
)
from stilldone.redaction import redact_text
from stilldone.serialization import to_canonical_primitive

if TYPE_CHECKING:
    from stilldone.verifier.predicates import (
        PredicateEvaluationResult,
        PredicateTruth,
    )
    from stilldone.verifier.readiness import (
        MissionReadinessDetermination,
    )

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


class ApprovedExecutionPersistenceError(ExecutionGateError):
    """Raised when provider mutation succeeded but durable evidence persistence failed.

    Crucial Truth Invariant:
    - Provider mutation was ALREADY executed (external state changed).
    - Provider writes cannot be rolled back or undone internally.
    - Preserves provider execution result, attempt, and writes performed.
    - Enforces recoverable uncertainty and read-before-retry law.
    """

    def __init__(
        self,
        message: str,
        *,
        provider_result: ProviderExecutionResult,
        attempt: ExecutionAttempt,
        gate_decision: ExecutionGateDecision,
    ) -> None:
        super().__init__(message)
        self.provider_result = provider_result
        self.attempt = attempt
        self.gate_decision = gate_decision


class ConflictingReadbackObservationError(ExecutionGateError):
    """Raised when successive post-execution reads observe contradictory external states."""


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


def _validate_mapping_keys(mapping: Mapping[Any, Any], field_name: str) -> None:
    """Recursively validate that all mapping keys are strings."""
    for k, v in mapping.items():
        if not isinstance(k, str):
            raise ExecutionGateTypeError(
                f"{field_name} keys must be strings, got {type(k).__name__}"
            )
        if isinstance(v, Mapping):
            _validate_mapping_keys(v, field_name)


def _sanitize_key(key: Any) -> str:
    """Validate and sanitize mapping keys for privacy-safe serialization.

    Rejects non-string keys fail-closed without raw value reflection.
    Redacts sensitive text (emails, bearer tokens, etc.) from string keys.
    """
    if not isinstance(key, str):
        raise ExecutionGateTypeError(f"Mapping key must be a string, got {type(key).__name__}")
    return redact_text(key)


def _sanitize_value(val: Any) -> Any:
    """Recursively sanitize arbitrary nested structures for privacy-safe serialization.

    Rejects unsupported types fail-closed without raw value reflection.
    Redacts sensitive text from strings.
    Recursively validates and sanitizes nested mappings and sequences.
    """
    if isinstance(val, str):
        return redact_text(val)
    if isinstance(val, Mapping):
        return {_sanitize_key(k): _sanitize_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set, frozenset)):
        return [_sanitize_value(item) for item in val]
    try:
        return to_canonical_primitive(val)
    except (TypeError, ValueError):
        raise ExecutionGateTypeError(
            f"Unsupported value type for receipt serialization: {type(val).__name__}"
        ) from None


def _sanitize_summary_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively sanitize mapping keys and values for privacy-safe serialization."""
    if not isinstance(mapping, Mapping):
        return {}
    return {_sanitize_key(k): _sanitize_value(v) for k, v in mapping.items()}


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
# Provider Mutation Instrumentation Models & Spy
# ===========================================================================


@dataclass(frozen=True)
class ProviderMutationObservation:
    """Immutable observation of mutation entry points across router, handler, and transport.

    Captures in-memory runtime instrumentation (LOCAL_EXECUTION / FIXTURE)
    measuring whether mutation methods were entered or completed writes occurred.
    This instrumentation represents local runtime observation, not cryptographic or hardware proof.

    Distinguishes method invocation count from successful-write count:
    - router_mutation_invocations: number of router execution dispatches for mutation.
    - handler_mutation_invocations: number of CalendarUpdateHandler.execute calls.
    - transport_mutation_invocations: number of transport.update_event method invocations.
    - transport_writes: number of completed transport mutation writes.
    """

    router_mutation_invocations: int = 0
    handler_mutation_invocations: int = 0
    transport_mutation_invocations: int = 0
    transport_writes: int = 0
    fixture_writes_count: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "router_mutation_invocations",
            "handler_mutation_invocations",
            "transport_mutation_invocations",
            "transport_writes",
        ):
            val = getattr(self, field_name)
            if isinstance(val, bool) or not isinstance(val, int):
                raise ExecutionGateTypeError(
                    f"{field_name} must be an integer, got {type(val).__name__}"
                )
            if val < 0:
                raise ExecutionGateValueError(f"{field_name} must be a non-negative integer")
        if self.transport_writes > self.transport_mutation_invocations:
            raise ExecutionGateValueError(
                "transport_writes cannot exceed transport_mutation_invocations"
            )
        if self.fixture_writes_count is not None:
            if isinstance(self.fixture_writes_count, bool) or not isinstance(
                self.fixture_writes_count, int
            ):
                fwc_type = type(self.fixture_writes_count).__name__
                raise ExecutionGateTypeError(
                    f"fixture_writes_count must be an integer or None, got {fwc_type}"
                )
            if self.fixture_writes_count < 0:
                raise ExecutionGateValueError("fixture_writes_count must be a non-negative integer")

    @property
    def is_fixture_counter_available(self) -> bool:
        """True if the underlying transport exposed a fixture writes counter."""
        return self.fixture_writes_count is not None

    @property
    def total_mutation_invocations(self) -> int:
        """Total number of mutation entry-point method invocations."""
        return (
            self.router_mutation_invocations
            + self.handler_mutation_invocations
            + self.transport_mutation_invocations
        )

    @property
    def is_zero_mutation(self) -> bool:
        """True if zero mutation method invocations occurred and zero writes took place."""
        return self.total_mutation_invocations == 0 and self.transport_writes == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert observation to a serializable dictionary."""
        return {
            "router_mutation_invocations": self.router_mutation_invocations,
            "handler_mutation_invocations": self.handler_mutation_invocations,
            "transport_mutation_invocations": self.transport_mutation_invocations,
            "transport_writes": self.transport_writes,
            "fixture_writes_count": self.fixture_writes_count,
            "total_mutation_invocations": self.total_mutation_invocations,
        }


class CalendarMutationSpy:
    """Minimal P-11.05 spy instrumenting router, handler, and transport mutation paths.

    Separates method entry invocation counting from successful-write counting,
    ensuring attempts that raise before write increment are observed.
    """

    def __init__(
        self,
        *,
        router: AdapterRouter | None = None,
        handler: Any | None = None,
        transport: Any | None = None,
    ) -> None:
        self.router_invocations: int = 0
        self.handler_invocations: int = 0
        self.transport_invocations: int = 0
        self.transport_completed_invocations: int = 0
        self._router = router
        self._handler = handler
        self._transport = transport
        if (
            self._router is not None
            and hasattr(self._router, "_routes")
            and isinstance(self._router._routes, Mapping)
        ):
            if self._handler is None:
                self._handler = self._router._routes.get(ActionType.CALENDAR_UPDATE)
            if self._transport is None and self._handler is not None:
                self._transport = getattr(self._handler, "_transport", None)
                if self._transport is None and hasattr(self._handler, "_adapter"):
                    self._transport = getattr(self._handler._adapter, "_transport", None)
        elif self._handler is not None and self._transport is None:
            self._transport = getattr(self._handler, "_transport", None)
            if self._transport is None and hasattr(self._handler, "_adapter"):
                self._transport = getattr(self._handler._adapter, "_transport", None)

        self._initial_writes_count: int | None = None
        self._has_fixture_counter: bool = False
        if self._transport is not None and hasattr(self._transport, "writes_count"):
            init_c = self._transport.writes_count
            if isinstance(init_c, bool) or not isinstance(init_c, int) or init_c < 0:
                raise ExecutionGateValueError(
                    "Transport writes_count must be a non-negative integer"
                )
            self._has_fixture_counter = True
            self._initial_writes_count = init_c
        self._installed = False
        self._orig_router_execute: Any = None
        self._orig_handler_execute: Any = None
        self._orig_transport_update: Any = None
        self.install()

    def install(self) -> None:
        """Install instrumentation hooks on target objects."""
        if self._installed:
            return

        self._initial_writes_count = None
        self._has_fixture_counter = False
        if self._transport is not None and hasattr(self._transport, "writes_count"):
            init_c = self._transport.writes_count
            if isinstance(init_c, bool) or not isinstance(init_c, int) or init_c < 0:
                raise ExecutionGateValueError(
                    "Transport writes_count must be a non-negative integer"
                )
            self._has_fixture_counter = True
            self._initial_writes_count = init_c

        if self._router is not None and hasattr(self._router, "execute"):
            self._orig_router_execute = self._router.execute

            def _spy_router_execute(action: Any, *args: Any, **kwargs: Any) -> Any:
                act = getattr(action, "action", action)
                act_type = getattr(act, "action_type", None)
                if act_type == ActionType.CALENDAR_UPDATE:
                    self.router_invocations += 1
                return self._orig_router_execute(action, *args, **kwargs)

            self._router.execute = _spy_router_execute  # type: ignore[method-assign]

        if self._handler is not None and hasattr(self._handler, "execute"):
            self._orig_handler_execute = self._handler.execute

            def _spy_handler_execute(*args: Any, **kwargs: Any) -> Any:
                self.handler_invocations += 1
                return self._orig_handler_execute(*args, **kwargs)

            self._handler.execute = _spy_handler_execute

        if self._transport is not None and hasattr(self._transport, "update_event"):
            self._orig_transport_update = self._transport.update_event

            def _spy_transport_update(*args: Any, **kwargs: Any) -> Any:
                self.transport_invocations += 1
                res = self._orig_transport_update(*args, **kwargs)
                self.transport_completed_invocations += 1
                return res

            self._transport.update_event = _spy_transport_update

        self._installed = True

    def uninstall(self) -> None:
        """Restore original methods."""
        if not self._installed:
            return
        if self._router is not None and self._orig_router_execute is not None:
            self._router.execute = self._orig_router_execute  # type: ignore[method-assign]
        if self._handler is not None and self._orig_handler_execute is not None:
            self._handler.execute = self._orig_handler_execute
        if self._transport is not None and self._orig_transport_update is not None:
            self._transport.update_event = self._orig_transport_update
        self._installed = False

    def observe(self) -> ProviderMutationObservation:
        """Capture current observation snapshot."""
        if self._has_fixture_counter and self._transport is not None:
            current_writes = getattr(self._transport, "writes_count", None)
            if (
                isinstance(current_writes, bool)
                or not isinstance(current_writes, int)
                or current_writes < 0
            ):
                raise ExecutionGateValueError(
                    "Transport writes_count must be a non-negative integer"
                )
            if (
                self._initial_writes_count is not None
                and current_writes < self._initial_writes_count
            ):
                raise ExecutionGateValueError(
                    "Observed transport write counter decreased or reset: "
                    f"current ({current_writes}) < initial ({self._initial_writes_count})"
                )
            initial = self._initial_writes_count if self._initial_writes_count is not None else 0
            delta: int = current_writes - initial
            fixture_delta: int | None = delta
            writes = delta
        else:
            fixture_delta = None
            writes = self.transport_completed_invocations

        return ProviderMutationObservation(
            router_mutation_invocations=self.router_invocations,
            handler_mutation_invocations=self.handler_invocations,
            transport_mutation_invocations=self.transport_invocations,
            transport_writes=writes,
            fixture_writes_count=fixture_delta,
        )


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
    - recorded timestamp;
    - optional ProviderMutationObservation.
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
    mutation_observation: ProviderMutationObservation

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
        if self.action_type != ActionType.CALENDAR_UPDATE:
            raise ExecutionGateValueError(
                "UnapprovedActionReceipt strictly applies to CALENDAR_UPDATE, "
                f"got {self.action_type.value}"
            )
        if not isinstance(self.authority_class, AuthorityClass):
            ac_name = type(self.authority_class).__name__
            msg = f"authority_class must be an AuthorityClass, got {ac_name}"
            raise ExecutionGateTypeError(msg)
        if self.authority_class != AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED:
            raise ExecutionGateValueError(
                "UnapprovedActionReceipt strictly requires "
                "authority_class=REVERSIBLE_APPROVAL_REQUIRED, "
                f"got {self.authority_class.value}"
            )
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
        _validate_mapping_keys(self.before_state_summary, "before_state_summary")
        _validate_mapping_keys(self.after_state_summary, "after_state_summary")
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

        if not isinstance(self.mutation_observation, ProviderMutationObservation):
            raise ExecutionGateTypeError(
                "mutation_observation must be a ProviderMutationObservation instance, "
                f"got {type(self.mutation_observation).__name__}"
            )
        if not self.mutation_observation.is_zero_mutation:
            raise ExecutionGateValueError(
                "P-11.05 receipt requires mutation_observation to record zero mutations"
            )

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
        d: dict[str, Any] = {
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
            "mutation_observation": self.mutation_observation.to_dict(),
        }
        return d


# ===========================================================================
# Core Execution Gate Evaluation Function
# ===========================================================================


def evaluate_execution_gate(
    action: ValidatedActionContract | ActionContract,
    *,
    approval: ApprovalGrant | None = None,
    pending_approval: PendingApproval | None = None,
    at: datetime | None = None,
    ledger: ApprovalLedger | None = None,
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
         * If approval is provided:
           - Requires ApprovalLedger (fails closed if None).
           - Validates exact action binding, temporal validity, and cryptographic binding hash.
           - Checks single-use and revocation status against ledger (rejects replay/revocation).
           - Returns is_authorized=True (IN_PROGRESS).
       - If action does not require bound approval (READ_ONLY, REVERSIBLE_AUTO):
         * If approval grant is unexpectedly provided: raises UnexpectedApprovalGrantError.
         * Returns is_authorized=True, eligible for execution.

    Args:
        action: ValidatedActionContract or ActionContract.
        approval: Optional ApprovalGrant (strictly None for unapproved proof).
        pending_approval: Optional PendingApproval object.
        at: Optional timezone-aware UTC datetime.
        ledger: Optional ApprovalLedger for verifying usage and revocation status.

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
        if ledger is not None:
            assert_not_planner_for_authority(ledger, parameter_name="ledger")
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

        # Approval is present
        if ledger is None:
            raise NotImplementedError(
                "P-11.06 approved execution path is not implemented in P-11.05 "
                "without ApprovalLedger"
            )

        if not isinstance(ledger, ApprovalLedger):
            raise ExecutionGateTypeError(
                f"ledger must be an ApprovalLedger instance, got {type(ledger).__name__}"
            )

        if approval.authority_class != policy.authority_class:
            raise ExecutionGateValueError(
                f"ApprovalGrant authority_class '{approval.authority_class.value}' does not match "
                f"policy authority_class '{policy.authority_class.value}'"
            )

        # Verify cryptographic binding and temporal validity
        verify_approval_binding(validated, approval, at=norm_at)

        # Verify usage status in ledger (check for replay / revocation)
        if ledger.is_consumed(approval.approval_id):
            raise ApprovalAlreadyUsedError(
                f"Approval '{approval.approval_id}' was already consumed in ledger"
            )
        if ledger.is_revoked(approval.approval_id):
            raise ApprovalRevokedError(f"Approval '{approval.approval_id}' was revoked in ledger")

        return ExecutionGateDecision(
            action_id=validated.action_id,
            action_type=validated.action_type,
            authority_class=policy.authority_class,
            status=ActionExecutionStatus.IN_PROGRESS,
            is_authorized=True,
            reason=(
                f"Action '{validated.action_type.value}' is authorized by valid bound "
                f"ApprovalGrant '{approval.approval_id}'."
            ),
            pending_approval_id=paid,
            evaluated_at=norm_at,
            attempt=None,
            provider_result=None,
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
    ledger: ApprovalLedger | None = None,
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
       - If action requires bound approval, atomically consumes grant through ApprovalLedger FIRST
         (failing closed with zero mutation if durable persistence fails or already used).
       - Generates ExecutionAttempt (failing before tracker mutation if attempt fails).
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
        ledger: Optional ApprovalLedger for consuming approval grant.

    Returns:
        ExecutionGateDecision capturing final state.
    """
    gate_decision = evaluate_execution_gate(
        action,
        approval=approval,
        pending_approval=pending_approval,
        at=at,
        ledger=ledger,
    )

    # Branch 1: Action is NOT_RUN (approval absent)
    if gate_decision.status == ActionExecutionStatus.NOT_RUN:
        if tracker is not None:
            tracker.record_not_run(action.action_id, reason=gate_decision.reason)
        # Router is NOT called; provider mutation count is strictly 0.
        return gate_decision

    # Branch 2: Action is authorized to proceed
    # Step 1: Generate and validate attempt FIRST to prevent premature IN_PROGRESS
    # transition or burning the grant if attempt preparation fails.
    gen = attempt_generator or create_execution_attempt
    attempt = gen(action.action_id)
    if not isinstance(attempt, ExecutionAttempt):
        raise ExecutionGateTypeError(
            f"attempt_generator must produce ExecutionAttempt, got {type(attempt).__name__}"
        )
    if attempt.attempt_number != 1:
        raise ExecutionGateValueError("P-11.06 execution gate strictly requires attempt_number=1")
    if attempt.action_id != action.action_id:
        raise ExecutionGateValueError("ExecutionAttempt action_id must match action.action_id")

    # Step 2: If action requires bound approval, atomically consume through ApprovalLedger
    # strictly BEFORE provider mutation!
    if gate_decision.authority_class == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED:
        if approval is None:
            raise ExecutionGateValueError("ApprovalGrant required for execution")
        if ledger is None:
            raise ExecutionGateValueError("ApprovalLedger required for atomic consumption")
        # Atomically consume through existing P-11.04 ApprovalLedger before provider mutation.
        # Fails closed if durable consumption cannot be persisted
        # (raises ApprovalConsumptionPersistenceError).
        ledger.consume(
            approval,
            action,
            at=gate_decision.evaluated_at,
            attempt_number=attempt.attempt_number,
        )

    # Step 3: Mark in-progress
    if tracker is not None:
        tracker.mark_in_progress(action.action_id)

    actual_action = action.action if isinstance(action, ValidatedActionContract) else action
    try:
        provider_result = router.execute(
            actual_action,
            attempt=attempt,
            approval=approval,
            at=gate_decision.evaluated_at,
        )
    except Exception as exc:
        if tracker is not None:
            prov_res = record_provider_exception(actual_action.action_type, exc)
            err_msg = (
                prov_res.error_message or f"Synchronous execution failed: {type(exc).__name__}"
            )
            tracker.record_failure(
                actual_action.action_id,
                attempt=attempt,
                provider_result=prov_res,
                error_message=err_msg,
            )
        raise

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
    source_sha: str,
    ledger: ApprovalLedger,
    measured_provider_mutations: int,
    mutation_observation: ProviderMutationObservation,
    before_read_provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    after_read_provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    recorded_at: datetime | None = None,
) -> UnapprovedActionReceipt:
    """Create an immutable UnapprovedActionReceipt proving an unapproved action remained NOT_RUN.

    Enforces all P-11.05 invariants and derives facts from observed reality:
    - Binds strictly to the canonical gate decision, action, and pending approval.
    - Rejects contradictory action identity, pending identity, authority class, or gate decision.
    - Requires measured_provider_mutations == 0 and validates explicit
      ProviderMutationObservation instrumenting router, handler, and transport.
    - Eliminates unverified defaults and optional observation bypasses.
    - Verifies zero approval consumption operations occurred in ledger for this action
      using public ApprovalLedger query methods.
    - Rejects absent ledger evidence (ledger=None fails closed).
    - Enforces chronological ordering: before_read -> gate_decision -> independent after_read.
    - Validates timezone-aware read_at and observed_at consistency.
    - Rejects reversed, stale, same-operation, or pre-gate after-read evidence.
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
    if ledger is None:
        raise ExecutionGateValueError(
            "ledger evidence is required to verify absence of approval consumption; "
            "absent ledger evidence cannot be accepted"
        )
    if not isinstance(ledger, ApprovalLedger):
        raise ExecutionGateTypeError(
            f"ledger must be an ApprovalLedger instance, got {type(ledger).__name__}"
        )
    if mutation_observation is None:
        raise ExecutionGateValueError(
            "mutation_observation is required; unverified observation bypass is prohibited"
        )
    if not isinstance(mutation_observation, ProviderMutationObservation):
        raise ExecutionGateTypeError(
            "mutation_observation must be a ProviderMutationObservation instance, "
            f"got {type(mutation_observation).__name__}"
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

    # Authority consistency against canonical P-11.01 policy
    canonical_policy = get_action_authority_policy(ActionType.CALENDAR_UPDATE)
    expected_authority_class = canonical_policy.authority_class

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
    if gate_decision.action_type != ActionType.CALENDAR_UPDATE:
        raise ExecutionGateValueError(
            "gate_decision action_type must be CALENDAR_UPDATE, "
            f"got {gate_decision.action_type.value}"
        )
    if gate_decision.authority_class != expected_authority_class:
        raise ExecutionGateValueError(
            f"gate_decision authority_class must match canonical policy "
            f"({expected_authority_class.value}), got {gate_decision.authority_class.value}"
        )

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
    if pending_approval.action_type != ActionType.CALENDAR_UPDATE:
        raise ExecutionGateValueError(
            "pending_approval action_type must be CALENDAR_UPDATE, "
            f"got {pending_approval.action_type.value}"
        )
    if pending_approval.authority_class != expected_authority_class:
        raise ExecutionGateValueError(
            f"pending_approval authority_class must match canonical policy "
            f"({expected_authority_class.value}), got {pending_approval.authority_class.value}"
        )
    if pending_approval.action_id != actual_action.action_id:
        raise ExecutionGateValueError("pending_approval action_id does not match action action_id")
    if pending_approval.mission_id != actual_action.mission_id:
        raise ExecutionGateValueError(
            "pending_approval mission_id does not match action mission_id"
        )
    if pending_approval.target != actual_action.target:
        raise ExecutionGateValueError("pending_approval target does not match action target")
    if pending_approval.parameters != actual_action.parameters:
        raise ExecutionGateValueError("pending_approval parameters do not match action parameters")

    expected_paid = compute_pending_approval_id(
        mission_id=actual_action.mission_id,
        action_id=actual_action.action_id,
        action_type=actual_action.action_type,
        authority_class=expected_authority_class,
        target=actual_action.target,
        parameters=actual_action.parameters,
    )
    if pending_approval.pending_approval_id != expected_paid:
        raise ExecutionGateValueError(
            "pending_approval pending_approval_id does not match canonical computed identity"
        )
    if gate_decision.pending_approval_id != pending_approval.pending_approval_id:
        raise ExecutionGateValueError(
            "gate_decision pending_approval_id does not match pending_approval"
        )

    # Scoped negative proof: query public ApprovalLedger API for target action
    if ledger.has_consumed_approval_for_action(actual_action.action_id):
        raise ExecutionGateValueError(
            f"Approval has already been consumed for action '{actual_action.action_id}' "
            "in ledger; cannot create receipt"
        )

    # Measured provider mutations must come from instrumentation and be 0
    if measured_provider_mutations != 0:
        raise ExecutionGateValueError("Measured provider mutations must be 0 for NOT_RUN action")

    # Validate ProviderMutationObservation
    if mutation_observation.router_mutation_invocations != 0:
        raise ExecutionGateValueError("Router mutation invocations must be 0 for NOT_RUN action")
    if mutation_observation.handler_mutation_invocations != 0:
        raise ExecutionGateValueError("Handler mutation invocations must be 0 for NOT_RUN action")
    if mutation_observation.transport_mutation_invocations != 0:
        raise ExecutionGateValueError("Transport mutation invocations must be 0 for NOT_RUN action")
    if mutation_observation.transport_writes != 0:
        raise ExecutionGateValueError("Transport writes must be 0 for NOT_RUN action")
    if measured_provider_mutations != mutation_observation.transport_writes:
        raise ExecutionGateValueError(
            "measured_provider_mutations contradicts mutation_observation.transport_writes"
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

    # Defect 1: Validate distinct operations
    if before_read is after_read:
        raise ExecutionGateValueError(
            "before_read and after_read must be separate, independent read results"
        )
    if before_obs is after_obs:
        raise ExecutionGateValueError(
            "before_read and after_read observations must be separate instances"
        )

    # Timezone-awareness checks
    if before_read.read_at.tzinfo is None or before_read.read_at.utcoffset() is None:
        raise ExecutionGateValueError("before_read.read_at must be timezone-aware")
    if before_obs.observed_at.tzinfo is None or before_obs.observed_at.utcoffset() is None:
        raise ExecutionGateValueError("before_read.observation.observed_at must be timezone-aware")
    if after_read.read_at.tzinfo is None or after_read.read_at.utcoffset() is None:
        raise ExecutionGateValueError("after_read.read_at must be timezone-aware")
    if after_obs.observed_at.tzinfo is None or after_obs.observed_at.utcoffset() is None:
        raise ExecutionGateValueError("after_read.observation.observed_at must be timezone-aware")
    if gate_decision.evaluated_at.tzinfo is None or gate_decision.evaluated_at.utcoffset() is None:
        raise ExecutionGateValueError("gate_decision.evaluated_at must be timezone-aware")

    b_read_at = (
        before_read.read_at
        if before_read.read_at.tzinfo == UTC
        else before_read.read_at.astimezone(UTC)
    )
    b_obs_at = (
        before_obs.observed_at
        if before_obs.observed_at.tzinfo == UTC
        else before_obs.observed_at.astimezone(UTC)
    )
    a_read_at = (
        after_read.read_at
        if after_read.read_at.tzinfo == UTC
        else after_read.read_at.astimezone(UTC)
    )
    a_obs_at = (
        after_obs.observed_at
        if after_obs.observed_at.tzinfo == UTC
        else after_obs.observed_at.astimezone(UTC)
    )
    g_eval_at = (
        gate_decision.evaluated_at
        if gate_decision.evaluated_at.tzinfo == UTC
        else gate_decision.evaluated_at.astimezone(UTC)
    )

    # Reject identical same-operation timestamps
    if b_read_at == a_read_at and b_obs_at == a_obs_at:
        raise ExecutionGateValueError(
            "before_read and after_read have identical timestamps; "
            "two separate read operations are required"
        )

    # Chronological ordering checks:
    # before observation -> gate evaluation -> independent after observation
    if a_read_at < b_read_at or a_obs_at < b_obs_at:
        raise ExecutionGateValueError(
            "after_read occurred before before_read (reversed observation chronology)"
        )
    if b_read_at > g_eval_at or b_obs_at > g_eval_at:
        raise ExecutionGateValueError("before_read occurred after gate evaluation")
    if a_read_at < g_eval_at or a_obs_at < g_eval_at:
        raise ExecutionGateValueError(
            "after_read occurred before gate evaluation (pre-gate after-read evidence is invalid)"
        )

    # Freshness / Staleness check: before_read cannot be stale
    if g_eval_at - b_read_at > timedelta(hours=24):
        raise ExecutionGateValueError(
            "before_read observation is stale (>24h prior to gate evaluation)"
        )

    # Recorded at timestamp
    now = recorded_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ExecutionGateValueError("recorded_at must be timezone-aware")
    norm_now = now if now.tzinfo == UTC else now.astimezone(UTC)

    if norm_now < a_read_at or norm_now < a_obs_at:
        raise ExecutionGateValueError("recorded_at cannot precede after_read observation timestamp")

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
        mutation_observation=mutation_observation,
    )


# ===========================================================================
# Approved Action Receipt Model
# ===========================================================================


@dataclass(frozen=True)
class ApprovedActionReceipt:
    """Immutable evidence receipt proving an approved Calendar update executed and verified.

    Captures complete deterministic authority facts and provider truth:
    - exact source SHA (40 hex characters);
    - mission ID;
    - action ID;
    - action type (ActionType.CALENDAR_UPDATE);
    - authority class (AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED);
    - target event identity in privacy-safe form;
    - approval ID;
    - binding hash;
    - consumed at timestamp;
    - attempt number;
    - execution status;
    - provider mutation invocations;
    - provider writes;
    - before read provenance;
    - after read provenance;
    - before state summary (deep frozen);
    - after state summary (deep frozen);
    - readback status;
    - predicate truth;
    - is_verified;
    - is_ready_claimed;
    - provenance;
    - recorded at timestamp;
    - mutation observation (ProviderMutationObservation).
    """

    source_sha: str
    mission_id: MissionId
    action_id: ActionId
    action_type: ActionType
    authority_class: AuthorityClass
    target_event_id: str
    approval_id: ApprovalId
    binding_hash: BindingHash
    consumed_at: datetime
    attempt_number: int
    execution_status: ActionExecutionStatus
    provider_mutation_invocations: int
    provider_writes: int
    before_read_provenance: EvidenceProvenance
    after_read_provenance: EvidenceProvenance
    before_state_summary: Mapping[str, Any]
    after_state_summary: Mapping[str, Any]
    readback_status: CalendarReadbackStatus
    predicate_truth: PredicateTruth
    is_verified: bool
    is_ready_claimed: bool
    provenance: EvidenceProvenance
    recorded_at: datetime
    mutation_observation: ProviderMutationObservation

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
        if self.action_type != ActionType.CALENDAR_UPDATE:
            raise ExecutionGateValueError(
                "ApprovedActionReceipt strictly applies to CALENDAR_UPDATE, "
                f"got {self.action_type.value}"
            )
        if not isinstance(self.authority_class, AuthorityClass):
            ac_name = type(self.authority_class).__name__
            msg = f"authority_class must be an AuthorityClass, got {ac_name}"
            raise ExecutionGateTypeError(msg)
        if self.authority_class != AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED:
            raise ExecutionGateValueError(
                "ApprovedActionReceipt strictly requires "
                "authority_class=REVERSIBLE_APPROVAL_REQUIRED, "
                f"got {self.authority_class.value}"
            )
        if not isinstance(self.target_event_id, str) or not self.target_event_id.strip():
            raise ExecutionGateValueError("target_event_id must be a non-empty string")
        if not isinstance(self.approval_id, ApprovalId):
            raise ExecutionGateTypeError(
                f"approval_id must be an ApprovalId, got {type(self.approval_id).__name__}"
            )
        if not isinstance(self.binding_hash, BindingHash):
            raise ExecutionGateTypeError(
                f"binding_hash must be a BindingHash, got {type(self.binding_hash).__name__}"
            )
        if not isinstance(self.consumed_at, datetime):
            raise ExecutionGateTypeError(
                f"consumed_at must be a datetime, got {type(self.consumed_at).__name__}"
            )
        if self.consumed_at.tzinfo is None or self.consumed_at.utcoffset() is None:
            raise ExecutionGateValueError("consumed_at must be timezone-aware")
        if self.consumed_at.tzinfo != UTC:
            object.__setattr__(self, "consumed_at", self.consumed_at.astimezone(UTC))

        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int):
            raise ExecutionGateTypeError("attempt_number must be an integer")
        if self.attempt_number < 1:
            raise ExecutionGateValueError("attempt_number must be >= 1")

        if not isinstance(self.execution_status, ActionExecutionStatus):
            raise ExecutionGateTypeError(
                f"execution_status must be an ActionExecutionStatus, "
                f"got {type(self.execution_status).__name__}"
            )
        if (
            isinstance(self.provider_mutation_invocations, bool)
            or not isinstance(self.provider_mutation_invocations, int)
            or self.provider_mutation_invocations < 0
        ):
            raise ExecutionGateValueError("provider_mutation_invocations must be non-negative int")
        if (
            isinstance(self.provider_writes, bool)
            or not isinstance(self.provider_writes, int)
            or self.provider_writes < 0
        ):
            raise ExecutionGateValueError("provider_writes must be non-negative int")

        if not isinstance(self.before_read_provenance, EvidenceProvenance):
            raise ExecutionGateTypeError(
                f"before_read_provenance must be an EvidenceProvenance, "
                f"got {type(self.before_read_provenance).__name__}"
            )
        if not isinstance(self.after_read_provenance, EvidenceProvenance):
            raise ExecutionGateTypeError(
                f"after_read_provenance must be an EvidenceProvenance, "
                f"got {type(self.after_read_provenance).__name__}"
            )
        if not isinstance(self.before_state_summary, Mapping):
            raise ExecutionGateTypeError("before_state_summary must be a Mapping")
        if not isinstance(self.after_state_summary, Mapping):
            raise ExecutionGateTypeError("after_state_summary must be a Mapping")
        _validate_mapping_keys(self.before_state_summary, "before_state_summary")
        _validate_mapping_keys(self.after_state_summary, "after_state_summary")

        if not isinstance(self.readback_status, CalendarReadbackStatus):
            raise ExecutionGateTypeError(
                f"readback_status must be a CalendarReadbackStatus, "
                f"got {type(self.readback_status).__name__}"
            )
        from stilldone.verifier.predicates import PredicateTruth

        if not isinstance(self.predicate_truth, PredicateTruth):
            raise ExecutionGateTypeError(
                f"predicate_truth must be a PredicateTruth, "
                f"got {type(self.predicate_truth).__name__}"
            )
        if type(self.is_verified) is not bool:
            raise ExecutionGateTypeError("is_verified must be a bool")
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

        if not isinstance(self.mutation_observation, ProviderMutationObservation):
            raise ExecutionGateTypeError(
                f"mutation_observation must be a ProviderMutationObservation instance, "
                f"got {type(self.mutation_observation).__name__}"
            )
        if self.mutation_observation.transport_writes != self.provider_writes:
            raise ExecutionGateValueError(
                "provider_writes contradicts mutation_observation.transport_writes"
            )

        # Deep freeze state summaries to guarantee complete immutability
        object.__setattr__(
            self, "before_state_summary", _deep_freeze_mapping(self.before_state_summary)
        )
        object.__setattr__(
            self, "after_state_summary", _deep_freeze_mapping(self.after_state_summary)
        )

        # Core StillDone Invariant: Verification Truth
        if self.is_verified:
            if self.execution_status != ActionExecutionStatus.EXECUTION_SUCCEEDED:
                raise ExecutionGateValueError(
                    "Verified receipt requires execution_status=EXECUTION_SUCCEEDED"
                )
            if self.readback_status != CalendarReadbackStatus.MATCH:
                raise ExecutionGateValueError(
                    f"Verified receipt requires readback_status=MATCH, "
                    f"got {self.readback_status.value}"
                )
            if self.predicate_truth != PredicateTruth.TRUE:
                raise ExecutionGateValueError(
                    f"Verified receipt requires predicate_truth=TRUE, "
                    f"got {self.predicate_truth.value}"
                )
        else:
            if self.is_ready_claimed:
                raise ExecutionGateValueError(
                    "Unverified receipt cannot claim is_ready_claimed=True"
                )

        if self.is_ready_claimed and not self.is_verified:
            raise ExecutionGateValueError(
                "Receipt cannot claim is_ready_claimed=True when is_verified is False"
            )

        # Zero false-live claims: Fixture proof must NOT claim LIVE_*
        live_provenances = (
            EvidenceProvenance.LIVE_AWS,
            EvidenceProvenance.LIVE_GOOGLE,
            EvidenceProvenance.LIVE_EXTERNAL,
        )
        if self.provenance in live_provenances:
            raise ExecutionGateValueError(
                f"P-11.06 deterministic proof cannot claim live provenance "
                f"'{self.provenance.value}'"
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
            "approval_id": str(self.approval_id),
            "binding_hash": self.binding_hash.value,
            "consumed_at": self.consumed_at.isoformat(),
            "attempt_number": self.attempt_number,
            "execution_status": self.execution_status.value,
            "provider_mutation_invocations": self.provider_mutation_invocations,
            "provider_writes": self.provider_writes,
            "before_read_provenance": self.before_read_provenance.value,
            "after_read_provenance": self.after_read_provenance.value,
            "before_state_summary": _sanitize_summary_mapping(self.before_state_summary),
            "after_state_summary": _sanitize_summary_mapping(self.after_state_summary),
            "readback_status": self.readback_status.value,
            "predicate_truth": self.predicate_truth.value,
            "is_verified": self.is_verified,
            "is_ready_claimed": self.is_ready_claimed,
            "provenance": self.provenance.value,
            "recorded_at": self.recorded_at.isoformat(),
            "mutation_observation": self.mutation_observation.to_dict(),
        }


# ===========================================================================
# Approved Action Receipt Factory Function
# ===========================================================================


def create_approved_action_receipt(
    *,
    gate_decision: ExecutionGateDecision,
    action: ValidatedActionContract | ActionContract,
    approval: ApprovalGrant,
    consumption_record: ApprovalConsumptionRecord,
    before_read: CalendarReadResult,
    after_read: CalendarReadResult,
    readback_result: CalendarReadbackResult,
    predicate_result: PredicateEvaluationResult,
    source_sha: str,
    ledger: ApprovalLedger,
    mutation_observation: ProviderMutationObservation,
    predicate: DesiredStatePredicate | None = None,
    before_read_provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    after_read_provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    recorded_at: datetime | None = None,
    is_ready_claimed: bool | None = None,
) -> ApprovedActionReceipt:
    """Create an immutable ApprovedActionReceipt proving an approved Calendar update.

    Derives facts deterministically from real components:
    - Binds strictly to the canonical gate decision, action, and ApprovalGrant.
    - Requires consumption_record proving single-use consumption in ApprovalLedger.
    - Enforces chronological ordering:
      before_read -> consumed_at -> gate_eval -> provider_executed -> after_read.
    - Derives before and after states directly from separate CalendarReadResults.
    - Derives read-back status directly from CalendarReadbackResult (never provider response).
    - Derives predicate truth directly from PredicateEvaluationResult.
    - Computes verified truth deterministically:
      execution success + read-back match + predicate true.
    """
    from stilldone.verifier.predicates import (
        PredicateEvaluationResult,
        PredicateTruth,
    )

    if not isinstance(gate_decision, ExecutionGateDecision):
        raise ExecutionGateTypeError(
            f"gate_decision must be an ExecutionGateDecision, got {type(gate_decision).__name__}"
        )
    if not isinstance(action, (ValidatedActionContract, ActionContract)):
        raise ExecutionGateTypeError(
            f"action must be ActionContract or ValidatedActionContract, got {type(action).__name__}"
        )
    if not isinstance(approval, ApprovalGrant):
        raise ExecutionGateTypeError(
            f"approval must be an ApprovalGrant, got {type(approval).__name__}"
        )
    if not isinstance(consumption_record, ApprovalConsumptionRecord):
        raise ExecutionGateTypeError(
            "consumption_record must be an ApprovalConsumptionRecord, "
            f"got {type(consumption_record).__name__}"
        )
    if not isinstance(before_read, CalendarReadResult):
        raise ExecutionGateTypeError(
            f"before_read must be a CalendarReadResult, got {type(before_read).__name__}"
        )
    if not isinstance(after_read, CalendarReadResult):
        raise ExecutionGateTypeError(
            f"after_read must be a CalendarReadResult, got {type(after_read).__name__}"
        )
    if not isinstance(readback_result, CalendarReadbackResult):
        raise ExecutionGateTypeError(
            "readback_result must be a CalendarReadbackResult, "
            f"got {type(readback_result).__name__}"
        )
    if not isinstance(predicate_result, PredicateEvaluationResult):
        raise ExecutionGateTypeError(
            "predicate_result must be a PredicateEvaluationResult, "
            f"got {type(predicate_result).__name__}"
        )
    if not isinstance(ledger, ApprovalLedger):
        raise ExecutionGateTypeError(
            f"ledger must be an ApprovalLedger, got {type(ledger).__name__}"
        )
    if not isinstance(mutation_observation, ProviderMutationObservation):
        raise ExecutionGateTypeError(
            "mutation_observation must be a ProviderMutationObservation, "
            f"got {type(mutation_observation).__name__}"
        )
    if not isinstance(source_sha, str):
        raise ExecutionGateTypeError("source_sha must be a string")

    # Canonical policy binding
    canonical_policy = get_action_authority_policy(ActionType.CALENDAR_UPDATE)
    expected_authority_class = canonical_policy.authority_class

    if gate_decision.action_type != ActionType.CALENDAR_UPDATE:
        raise ExecutionGateValueError(
            "gate_decision action_type must be CALENDAR_UPDATE, "
            f"got {gate_decision.action_type.value}"
        )
    if gate_decision.authority_class != expected_authority_class:
        raise ExecutionGateValueError(
            f"gate_decision authority_class must be {expected_authority_class.value}, "
            f"got {gate_decision.authority_class.value}"
        )

    actual_action = action.action if isinstance(action, ValidatedActionContract) else action
    if actual_action.action_id != gate_decision.action_id:
        raise ExecutionGateValueError("action action_id does not match gate decision action_id")
    if actual_action.action_id != approval.action_id:
        raise ExecutionGateValueError("action action_id does not match approval action_id")
    if actual_action.action_id != consumption_record.action_id:
        raise ExecutionGateValueError(
            "action action_id does not match consumption record action_id"
        )
    if actual_action.mission_id != approval.mission_id:
        raise ExecutionGateValueError("action mission_id does not match approval mission_id")
    if actual_action.mission_id != consumption_record.mission_id:
        raise ExecutionGateValueError(
            "action mission_id does not match consumption record mission_id"
        )
    if approval.approval_id != consumption_record.approval_id:
        raise ExecutionGateValueError("approval_id does not match consumption record approval_id")
    if approval.binding_hash != consumption_record.binding_hash:
        raise ExecutionGateValueError("binding_hash does not match consumption record binding_hash")

    # Ledger check: verify exact consumption record identity and lineage from public API
    rec = ledger.get_record(approval.approval_id)
    if rec is None:
        raise ExecutionGateValueError(
            f"Approval '{approval.approval_id}' has not been consumed in ledger"
        )
    if rec.status != ApprovalUsageStatus.CONSUMED:
        raise ExecutionGateValueError(
            f"Approval record status must be CONSUMED, got {rec.status.value}"
        )
    if rec.mission_id != actual_action.mission_id:
        raise ExecutionGateValueError(
            f"Approval record mission_id '{rec.mission_id}' does not match action mission_id"
        )
    if rec.action_id != actual_action.action_id:
        raise ExecutionGateValueError(
            f"Approval record action_id '{rec.action_id}' does not match action action_id"
        )
    if rec.binding_hash != approval.binding_hash:
        raise ExecutionGateValueError(
            "Approval record binding_hash does not match approval grant binding_hash"
        )
    if rec.attempt_number != consumption_record.attempt_number:
        raise ExecutionGateValueError(
            "Approval record attempt_number does not match consumption record"
        )

    # Observations validation
    if before_read.status != CalendarReadStatus.SUCCESS or before_read.observation is None:
        raise ExecutionGateValueError(
            "before_read must have status SUCCESS with non-None observation"
        )
    if after_read.status != CalendarReadStatus.SUCCESS or after_read.observation is None:
        raise ExecutionGateValueError(
            "after_read must have status SUCCESS with non-None observation"
        )

    before_obs = before_read.observation
    after_obs = after_read.observation

    if before_read is after_read:
        raise ExecutionGateValueError("before_read and after_read must be separate read results")
    if before_obs is after_obs:
        raise ExecutionGateValueError(
            "before_read and after_read observations must be separate instances"
        )

    # Timezone awareness
    if before_read.read_at.tzinfo is None or before_read.read_at.utcoffset() is None:
        raise ExecutionGateValueError("before_read.read_at must be timezone-aware")
    if after_read.read_at.tzinfo is None or after_read.read_at.utcoffset() is None:
        raise ExecutionGateValueError("after_read.read_at must be timezone-aware")
    if (
        consumption_record.consumed_at.tzinfo is None
        or consumption_record.consumed_at.utcoffset() is None
    ):
        raise ExecutionGateValueError("consumption_record.consumed_at must be timezone-aware")
    if gate_decision.evaluated_at.tzinfo is None or gate_decision.evaluated_at.utcoffset() is None:
        raise ExecutionGateValueError("gate_decision.evaluated_at must be timezone-aware")
    if (
        predicate_result.evaluated_at.tzinfo is None
        or predicate_result.evaluated_at.utcoffset() is None
    ):
        raise ExecutionGateValueError("predicate_result.evaluated_at must be timezone-aware")
    if (
        readback_result.verified_at.tzinfo is None
        or readback_result.verified_at.utcoffset() is None
    ):
        raise ExecutionGateValueError("readback_result.verified_at must be timezone-aware")

    b_read_at = (
        before_read.read_at
        if before_read.read_at.tzinfo == UTC
        else before_read.read_at.astimezone(UTC)
    )
    a_read_at = (
        after_read.read_at
        if after_read.read_at.tzinfo == UTC
        else after_read.read_at.astimezone(UTC)
    )
    c_consumed_at = (
        consumption_record.consumed_at
        if consumption_record.consumed_at.tzinfo == UTC
        else consumption_record.consumed_at.astimezone(UTC)
    )
    g_eval_at = (
        gate_decision.evaluated_at
        if gate_decision.evaluated_at.tzinfo == UTC
        else gate_decision.evaluated_at.astimezone(UTC)
    )
    p_eval_at = (
        predicate_result.evaluated_at
        if predicate_result.evaluated_at.tzinfo == UTC
        else predicate_result.evaluated_at.astimezone(UTC)
    )
    r_ver_at = (
        readback_result.verified_at
        if readback_result.verified_at.tzinfo == UTC
        else readback_result.verified_at.astimezone(UTC)
    )

    if b_read_at == a_read_at:
        raise ExecutionGateValueError(
            "before_read and after_read have identical timestamps; "
            "two separate read operations are required"
        )
    if a_read_at < b_read_at:
        raise ExecutionGateValueError(
            "after_read occurred before before_read (reversed observation chronology)"
        )
    if b_read_at > g_eval_at:
        raise ExecutionGateValueError("before_read occurred after gate evaluation")
    if a_read_at < g_eval_at:
        raise ExecutionGateValueError("after_read occurred before gate evaluation")
    if p_eval_at < r_ver_at:
        raise ExecutionGateValueError(
            "predicate_result evaluated_at cannot precede readback_result verified_at"
        )

    # Readback target resource matches
    if readback_result.event_id != actual_action.target.resource_id:
        raise ExecutionGateValueError(
            "readback_result event_id does not match action target resource_id"
        )
    if readback_result.observation is not None:
        if readback_result.observation.event_id != actual_action.target.resource_id:
            raise ExecutionGateValueError(
                "readback_result observation event_id does not match action target resource_id"
            )
        if readback_result.observation.calendar_id != actual_action.target.parent_id:
            raise ExecutionGateValueError(
                "readback_result observation calendar_id does not match action target parent_id"
            )

    # Forged MATCH checks and readback status consistency
    if readback_result.status == CalendarReadbackStatus.MATCH:
        if not readback_result.is_match:
            raise ExecutionGateValueError("Forged MATCH: readback_result.is_match is False")
        if len(readback_result.mismatches) > 0:
            raise ExecutionGateValueError("Forged MATCH: readback_result contains mismatches")
        if readback_result.observation is None:
            raise ExecutionGateValueError("Forged MATCH: readback_result observation is None")
    else:
        if readback_result.is_match:
            raise ExecutionGateValueError(
                "Contradictory readback result: is_match is True but status is not MATCH"
            )

    # Observation consistency check: after_read and readback_result must not contradict each other
    if readback_result.observation is not None:
        r_obs = readback_result.observation
        if (
            after_obs.summary != r_obs.summary
            or after_obs.start_time != r_obs.start_time
            or after_obs.end_time != r_obs.end_time
            or after_obs.all_day != r_obs.all_day
            or after_obs.etag != r_obs.etag
            or after_obs.status != r_obs.status
        ):
            raise ExecutionGateValueError(
                "after_read observation contradicts readback_result observation"
            )

    # Predicate lineage and result checks
    if predicate is not None:
        if not isinstance(predicate, DesiredStatePredicate):
            raise ExecutionGateTypeError(
                f"predicate must be DesiredStatePredicate, got {type(predicate).__name__}"
            )
        if predicate.mission_id != actual_action.mission_id:
            raise ExecutionGateValueError("predicate mission_id does not match action mission_id")
        if predicate_result.predicate_id != predicate.predicate_id:
            raise ExecutionGateValueError(
                "predicate_result predicate_id does not match predicate predicate_id"
            )
        if predicate_result.operator != predicate.operator:
            raise ExecutionGateValueError(
                "predicate_result operator does not match predicate operator"
            )
        if predicate_result.expected_value != predicate.expected_value:
            raise ExecutionGateValueError(
                "predicate_result expected_value does not match predicate expected_value"
            )
        if predicate_result.subject != predicate.subject:
            raise ExecutionGateValueError(
                "predicate_result subject does not match predicate subject"
            )

    # Predicate truth internal consistency
    if predicate_result.truth == PredicateTruth.TRUE:
        if not predicate_result.is_true:
            raise ExecutionGateValueError(
                "Contradictory predicate truth: truth is TRUE but is_true is False"
            )
    else:
        if predicate_result.is_true:
            raise ExecutionGateValueError(
                "Contradictory predicate truth: is_true is True but truth is not TRUE"
            )

    # Authoritative observation consistency:
    # predicate observed_value must match readback observation
    if predicate is not None and readback_result.observation is not None:
        prop_name = predicate.subject.split(".")[-1]
        if hasattr(readback_result.observation, prop_name):
            obs_val = getattr(readback_result.observation, prop_name)
            if predicate_result.observed_value is not None and str(obs_val) != str(
                predicate_result.observed_value
            ):
                raise ExecutionGateValueError(
                    f"Predicate observed_value '{predicate_result.observed_value}' contradicts "
                    f"readback observation {prop_name} '{obs_val}'"
                )
            if (
                predicate_result.truth == PredicateTruth.TRUE
                and str(predicate.operator) in ("EQUALS", "PredicateOperator.EQUALS")
                and str(obs_val) != str(predicate.expected_value)
            ):
                raise ExecutionGateValueError(
                    f"Contradictory observation: readback observation {prop_name} '{obs_val}' "
                    f"contradicts predicate expected_value '{predicate.expected_value}'"
                )

    # Resource matches
    if (
        before_obs.event_id != actual_action.target.resource_id
        or after_obs.event_id != actual_action.target.resource_id
    ):
        raise ExecutionGateValueError("Read observations must match action target resource_id")
    if (
        before_obs.calendar_id != actual_action.target.parent_id
        or after_obs.calendar_id != actual_action.target.parent_id
    ):
        raise ExecutionGateValueError("Read observations must match action target parent_id")

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

    # Measurement consistency checks
    if gate_decision.is_authorized:
        if mutation_observation.router_mutation_invocations < 1:
            raise ExecutionGateValueError(
                "Authorized gate decision requires router_mutation_invocations >= 1"
            )
    if mutation_observation.transport_writes > mutation_observation.transport_mutation_invocations:
        raise ExecutionGateValueError(
            "transport_writes cannot exceed transport_mutation_invocations"
        )
    if gate_decision.provider_result is not None:
        if gate_decision.provider_result.writes_performed != mutation_observation.transport_writes:
            raise ExecutionGateValueError(
                "provider_result.writes_performed contradicts mutation_observation.transport_writes"
            )

    # Deterministic verification computation (action-level verification)
    is_verified = (
        gate_decision.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        and readback_result.status == CalendarReadbackStatus.MATCH
        and predicate_result.truth == PredicateTruth.TRUE
    )

    # Unpersisted READY check: cannot claim READY without persisted transition
    if is_ready_claimed is True:
        raise ExecutionGateValueError(
            "Unpersisted READY: cannot claim mission READY without a persisted READY "
            "transition in canonical ledger"
        )
    computed_ready = False

    now = recorded_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ExecutionGateValueError("recorded_at must be timezone-aware")
    norm_now = now if now.tzinfo == UTC else now.astimezone(UTC)
    if norm_now < a_read_at:
        raise ExecutionGateValueError("recorded_at cannot precede after_read timestamp")
    if norm_now < p_eval_at:
        raise ExecutionGateValueError("recorded_at cannot precede predicate_result evaluated_at")

    return ApprovedActionReceipt(
        source_sha=source_sha,
        mission_id=actual_action.mission_id,
        action_id=actual_action.action_id,
        action_type=actual_action.action_type,
        authority_class=gate_decision.authority_class,
        target_event_id=actual_action.target.resource_id,
        approval_id=approval.approval_id,
        binding_hash=approval.binding_hash,
        consumed_at=c_consumed_at,
        attempt_number=consumption_record.attempt_number,
        execution_status=gate_decision.status,
        provider_mutation_invocations=mutation_observation.total_mutation_invocations,
        provider_writes=mutation_observation.transport_writes,
        before_read_provenance=before_read_provenance,
        after_read_provenance=after_read_provenance,
        before_state_summary=before_summary,
        after_state_summary=after_summary,
        readback_status=readback_result.status,
        predicate_truth=predicate_result.truth,
        is_verified=is_verified,
        is_ready_claimed=computed_ready,
        provenance=provenance,
        recorded_at=norm_now,
        mutation_observation=mutation_observation,
    )


# ===========================================================================
# Approved Calendar Update Execution & Verification Coordinator
# ===========================================================================


@dataclass(frozen=True)
class ApprovedCalendarUpdateOutcome:
    """Immutable result of executing and independently verifying an approved Calendar update."""

    gate_decision: ExecutionGateDecision
    consumption_record: ApprovalConsumptionRecord
    attempt: ExecutionAttempt
    provider_result: ProviderExecutionResult
    before_read: CalendarReadResult
    after_read: CalendarReadResult
    readback_result: CalendarReadbackResult
    predicate_result: PredicateEvaluationResult
    is_verified: bool
    is_ready: bool
    receipt: ApprovedActionReceipt
    mutation_observation: ProviderMutationObservation
    readiness_determination: MissionReadinessDetermination | None = None
    is_durable: bool = False
    mission_ready_status: str = "NOT_ESTABLISHED"


def execute_approved_calendar_update(
    action: ValidatedActionContract | ActionContract,
    router: AdapterRouter,
    approval: ApprovalGrant,
    ledger: ApprovalLedger,
    read_adapter: GoogleCalendarReadAdapter,
    predicate: DesiredStatePredicate,
    source_sha: str,
    *,
    tracker: ExecutionStateTracker | None = None,
    pending_approval: PendingApproval | None = None,
    spy: CalendarMutationSpy | None = None,
    before_read: CalendarReadResult | None = None,
    after_read: CalendarReadResult | None = None,
    mission_ledger: MissionLedgerPort | None = None,
    at: datetime | None = None,
    before_read_provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    after_read_provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    mission_state: MissionState | str | None = None,
    mission_predicates: Sequence[DesiredStatePredicate] | None = None,
    mission_execution_record: MissionExecutionRecord | None = None,
) -> ApprovedCalendarUpdateOutcome:
    """Execute an approved Calendar update once, verify independently, and compute readiness.

    Enforces the complete 12-step sequence:
    1. Validate canonical action, exact target and frozen authority policy.
    2. Require a human-originated, exact-action-bound ApprovalGrant.
    3. Validate mission ID, action ID, action type, parameters, target,
       binding hash, expiry, revocation and replay status.
    4. Atomically consume the grant through ApprovalLedger before provider mutation.
    5. Fail closed if durable consumption cannot be persisted.
    6. Generate one canonical execution attempt.
    7. Dispatch exactly once through authorized Calendar update adapter.
    8. Preserve actual provider result and external identifiers without fabrication.
    9. Perform a fresh, separate Google Calendar read-back.
    10. Evaluate the exact desired-state predicate using deterministic verification.
    11. Record provenance, read-back, predicate and final execution truth durably.
    12. Promote to VERIFIED/READY only if all lifecycle, evidence and freshness rules are satisfied.
    """
    # 1. Action contract validation
    if isinstance(action, ValidatedActionContract):
        validated = action
    elif isinstance(action, ActionContract):
        validated = validate_action_contract(action)
    else:
        raise ExecutionGateTypeError(
            f"action must be ActionContract or ValidatedActionContract, got {type(action).__name__}"
        )

    actual_action = validated.action
    if actual_action.action_type != ActionType.CALENDAR_UPDATE:
        raise ExecutionGateValueError(
            "execute_approved_calendar_update strictly handles CALENDAR_UPDATE, "
            f"got {actual_action.action_type.value}"
        )

    # 2. Assert not planner
    assert_not_planner_for_authority(approval, parameter_name="approval")
    assert_not_planner_for_authority(ledger, parameter_name="ledger")
    assert_not_planner_for_authority(predicate, parameter_name="predicate")

    if not isinstance(approval, ApprovalGrant):
        raise ExecutionGateTypeError(
            f"approval must be ApprovalGrant, got {type(approval).__name__}"
        )
    if not isinstance(ledger, ApprovalLedger):
        raise ExecutionGateTypeError(f"ledger must be ApprovalLedger, got {type(ledger).__name__}")
    if not isinstance(read_adapter, GoogleCalendarReadAdapter):
        raise ExecutionGateTypeError(
            f"read_adapter must be GoogleCalendarReadAdapter, got {type(read_adapter).__name__}"
        )
    if not isinstance(predicate, DesiredStatePredicate):
        raise ExecutionGateTypeError(
            f"predicate must be DesiredStatePredicate, got {type(predicate).__name__}"
        )

    # 3. Bind approval durability to mission evidence durability
    if mission_ledger is not None and ledger.ledger is not None:
        if hasattr(ledger.ledger, "file_path") and hasattr(mission_ledger, "file_path"):
            if Path(ledger.ledger.file_path).resolve() != Path(mission_ledger.file_path).resolve():
                raise ExecutionGateValueError(
                    "ApprovalLedger backing ledger does not match mission_ledger"
                )
        elif ledger.ledger is not mission_ledger:
            raise ExecutionGateValueError(
                "ApprovalLedger backing ledger does not match mission_ledger"
            )

    # 4. Canonical persisted mission context authority checks
    if mission_state is not None:
        norm_supplied_state = (
            MissionState(mission_state) if isinstance(mission_state, str) else mission_state
        )
        if norm_supplied_state == MissionState.READY:
            raise ExecutionGateValueError(
                "Unpersisted READY: cannot supply mission_state=READY during action execution"
            )

    if mission_predicates is not None:
        if len(mission_predicates) == 0:
            raise ExecutionGateValueError("Caller-supplied mission_predicates cannot be empty")
        pred_ids = {p.predicate_id for p in mission_predicates}
        if predicate.predicate_id not in pred_ids:
            raise ExecutionGateValueError(
                "Caller-supplied mission_predicates does not contain "
                "the required predicate for this action"
            )

    if mission_ledger is not None:
        try:
            persisted_mission = mission_ledger.get_mission(actual_action.mission_id)
        except RecordNotFoundError:
            persisted_mission = None

        if mission_state is not None:
            if persisted_mission is None:
                raise ExecutionGateValueError(
                    f"Mission '{actual_action.mission_id}' not found in canonical mission ledger"
                )
            if persisted_mission.state != norm_supplied_state:
                raise ExecutionGateValueError(
                    f"Persisted mission state '{persisted_mission.state.value}' contradicts "
                    f"caller-supplied mission_state '{norm_supplied_state.value}'"
                )

        if persisted_mission is not None:
            # Check terminal / unexecutable states
            if persisted_mission.state in (MissionState.CANCELLED, MissionState.FAILED):
                raise ExecutionGateValueError(
                    f"Unsupported lifecycle transition: cannot execute action on mission in "
                    f"'{persisted_mission.state.value}' state"
                )

    if mission_execution_record is not None:
        if mission_execution_record.mission_id != actual_action.mission_id:
            raise ExecutionGateValueError(
                f"mission_execution_record mission_id '{mission_execution_record.mission_id}' "
                f"does not match action mission_id '{actual_action.mission_id}'"
            )

    # 5. Establish before-state read if not supplied
    if before_read is None:
        before_action = ActionContract.create(
            mission_id=actual_action.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=actual_action.target,
            parameters={},
        )
        before_read = read_adapter.read_event(before_action)

    if before_read.status != CalendarReadStatus.SUCCESS or before_read.observation is None:
        raise ExecutionGateValueError(
            "before_read must have status SUCCESS with non-None observation"
        )

    # Timestamps
    eval_time = at or datetime.now(UTC)
    if eval_time.tzinfo is None or eval_time.utcoffset() is None:
        raise ExecutionGateValueError("Evaluation timestamp 'at' must be timezone-aware")
    norm_eval_at = eval_time if eval_time.tzinfo == UTC else eval_time.astimezone(UTC)
    if norm_eval_at < before_read.read_at:
        norm_eval_at = before_read.read_at

    # 6. Explicit real instrumentation (no synthetic fallback)
    installed_spy_locally = False
    active_spy = spy
    if active_spy is None:
        handler = None
        transport = None
        if hasattr(router, "_routes") and isinstance(router._routes, Mapping):
            handler = router._routes.get(actual_action.action_type)
            if handler is not None:
                transport = getattr(handler, "_transport", None)
                if transport is None and hasattr(handler, "_adapter"):
                    transport = getattr(handler._adapter, "_transport", None)
        active_spy = CalendarMutationSpy(router=router, handler=handler, transport=transport)
        installed_spy_locally = True

    # 7. Gated execution: gate evaluation, attempt prep, consumption, dispatch
    try:
        gate_decision = execute_gated_action(
            validated,
            router,
            tracker=tracker,
            approval=approval,
            pending_approval=pending_approval,
            at=norm_eval_at,
            ledger=ledger,
        )
    finally:
        if installed_spy_locally:
            active_spy.uninstall()

    if gate_decision.attempt is None:
        raise ExecutionGateValueError("Execution attempt was not created during gated execution")
    attempt = gate_decision.attempt

    if gate_decision.provider_result is None:
        raise ExecutionGateValueError("Provider execution result was not recorded")
    provider_result = gate_decision.provider_result

    consumption_record = ledger.get_record(approval.approval_id)
    if consumption_record is None:
        raise ExecutionGateValueError("Approval consumption record missing from ledger")

    # 8. Durable consumption evidence verification in canonical mission ledger
    if mission_ledger is not None and ledger.ledger is not None:
        actions_evidence = mission_ledger.get_evidence_for_action(actual_action.action_id)
        matching_consumption = False
        for ev in actions_evidence:
            p = ev.payload.to_dict() if hasattr(ev.payload, "to_dict") else dict(ev.payload)
            if (
                p.get("evidence_type") == APPROVAL_CONSUMPTION_EVIDENCE_TYPE
                and p.get("approval_id") == str(approval.approval_id)
                and p.get("action_id") == str(actual_action.action_id)
                and p.get("mission_id") == str(actual_action.mission_id)
                and p.get("binding_hash") == approval.binding_hash.value
                and p.get("consumed_for_attempt") == consumption_record.attempt_number
                and ev.action_id == actual_action.action_id
                and ev.mission_id == actual_action.mission_id
            ):
                matching_consumption = True
                break
        if not matching_consumption:
            raise ExecutionGateValueError(
                f"Approval consumption evidence for approval '{approval.approval_id}' "
                "is missing from canonical mission ledger"
            )

    if mission_ledger is not None:
        # Persist execution attempt immediately to durably preserve dispatch and write facts
        ev_attempt = EvidenceRecord.create(
            action_id=actual_action.action_id,
            mission_id=actual_action.mission_id,
            origin=EvidenceOrigin(provenance=provenance, observed_at=norm_eval_at),
            payload={
                "evidence_type": "EXECUTION_ATTEMPT",
                "attempt_id": str(attempt.attempt_id),
                "attempt_number": attempt.attempt_number,
                "status": gate_decision.status.value,
                "writes_performed": provider_result.writes_performed,
            },
            created_at=norm_eval_at,
        )
        try:
            mission_ledger.append_evidence(ev_attempt)
        except Exception as exc:
            msg = (
                f"Provider mutation executed successfully "
                f"({provider_result.writes_performed} write), "
                f"but durable mission ledger persistence failed: {type(exc).__name__}"
            )
            raise ApprovedExecutionPersistenceError(
                msg,
                provider_result=provider_result,
                attempt=attempt,
                gate_decision=gate_decision,
            ) from exc

    # 9. Post-dispatch sequence protected by honest failure recovery
    try:
        mutation_obs = active_spy.observe()
        if gate_decision.is_authorized:
            if mutation_obs.router_mutation_invocations < 1:
                raise ExecutionGateValueError(
                    "Authorized gate decision requires router_mutation_invocations >= 1"
                )
        if active_spy._handler is not None:
            if (
                mutation_obs.handler_mutation_invocations
                != mutation_obs.router_mutation_invocations
            ):
                raise ExecutionGateValueError(
                    "Handler mutation invocations contradict router invocations"
                )
        if mutation_obs.transport_writes > mutation_obs.transport_mutation_invocations:
            raise ExecutionGateValueError(
                "transport_writes cannot exceed transport_mutation_invocations"
            )
        if provider_result.writes_performed != mutation_obs.transport_writes:
            raise ExecutionGateValueError(
                f"provider_result.writes_performed ({provider_result.writes_performed}) "
                f"contradicts mutation_obs.transport_writes ({mutation_obs.transport_writes})"
            )

        # Independent read-back & conflicting observation detection
        if after_read is None:
            after_action = ActionContract.create(
                mission_id=actual_action.mission_id,
                action_type=ActionType.CALENDAR_READ,
                target=actual_action.target,
                parameters={},
            )
            first_read = read_adapter.read_event(after_action)
        else:
            first_read = after_read

        params = actual_action.parameters.to_dict()
        summary_val = params.get("summary")
        start_time_val = params.get("start_time")
        all_day_val = params.get("all_day")
        expected = ExpectedCalendarState(
            summary=summary_val if isinstance(summary_val, str) else None,
            start_time=start_time_val if isinstance(start_time_val, str) else None,
            all_day=all_day_val if isinstance(all_day_val, bool) else None,
        )
        verifier = GoogleCalendarReadbackVerifier(read_adapter)
        readback_result = verifier.verify(actual_action, expected)

        # Detect conflicting successive post-execution reads
        if (
            first_read.observation is not None
            and readback_result.observation is not None
            and (
                first_read.observation.summary != readback_result.observation.summary
                or first_read.observation.start_time != readback_result.observation.start_time
                or first_read.observation.end_time != readback_result.observation.end_time
                or first_read.observation.all_day != readback_result.observation.all_day
                or first_read.observation.etag != readback_result.observation.etag
                or first_read.observation.status != readback_result.observation.status
            )
        ):
            raise ConflictingReadbackObservationError(
                "Conflicting post-execution observations detected: "
                "event state changed between successive post-execution reads"
            )

        # Authoritative observation for predicate evaluation and receipt
        # is the verifier's observation
        authoritative_obs = readback_result.observation

        # Predicate evaluation
        from stilldone.verifier.contracts import (
            VerificationObservation,
            VerificationRequest,
        )
        from stilldone.verifier.predicates import (
            PredicateTruth,
            evaluate_predicate,
        )
        from stilldone.verifier.readiness import (
            compute_mission_readiness,
        )

        obs_props: dict[str, Any] = {}
        if authoritative_obs is not None:
            obs_props = {
                "summary": authoritative_obs.summary,
                "start_time": authoritative_obs.start_time,
                "end_time": authoritative_obs.end_time,
                "all_day": authoritative_obs.all_day,
                "etag": authoritative_obs.etag,
                "status": authoritative_obs.status,
            }

        verification_obs = VerificationObservation(
            target=actual_action.target,
            observed_at=readback_result.verified_at,
            exists=(
                readback_result.status != CalendarReadbackStatus.NOT_FOUND
                and authoritative_obs is not None
            ),
            properties=obs_props,
            provenance=after_read_provenance,
            raw_observation=authoritative_obs,
        )
        predicate_result = evaluate_predicate(
            predicate,
            verification_obs,
            expected_target=actual_action.target,
            at=readback_result.verified_at,
        )

        # Deterministic action-level verification truth
        is_verified = (
            gate_decision.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
            and provider_result.success
            and readback_result.status == CalendarReadbackStatus.MATCH
            and predicate_result.truth == PredicateTruth.TRUE
        )

        # Mission-level readiness truth (decoupled from action verification)
        readiness_determination: MissionReadinessDetermination | None = None
        is_durable = (
            getattr(mission_ledger, "IS_DURABLE", False)
            and ledger.ledger is not None
            and getattr(ledger.ledger, "IS_DURABLE", False)
            if mission_ledger is not None
            else False
        )

        # Compute readiness determination using P-09 compute_mission_readiness if context supplied
        if is_verified and mission_state is not None:
            req = VerificationRequest.create(
                action=actual_action,
                predicate=predicate,
            )
            preds = list(mission_predicates) if mission_predicates is not None else [predicate]
            readiness_eval_at = max(norm_eval_at, readback_result.verified_at)
            readiness_determination = compute_mission_readiness(
                mission_id=actual_action.mission_id,
                predicates=preds,
                verification_requests={predicate.predicate_id: req},
                predicate_evaluations={predicate.predicate_id: predicate_result},
                observations={predicate.predicate_id: verification_obs},
                execution_record=mission_execution_record,
                current_state=mission_state,
                at=readiness_eval_at,
            )

        # Mission READY is unpersisted in P-11.06 (deferred to P-12).
        # Action-level is_verified is True, but mission is_ready is False and NOT_ESTABLISHED.
        is_ready = False
        mission_ready_status = "NOT_ESTABLISHED"

        # Durable receipt creation (strictly is_ready_claimed=False)
        receipt = create_approved_action_receipt(
            gate_decision=gate_decision,
            action=validated,
            approval=approval,
            consumption_record=consumption_record,
            before_read=before_read,
            after_read=first_read,
            readback_result=readback_result,
            predicate_result=predicate_result,
            predicate=predicate,
            source_sha=source_sha,
            ledger=ledger,
            mutation_observation=mutation_obs,
            before_read_provenance=before_read_provenance,
            after_read_provenance=after_read_provenance,
            provenance=provenance,
            is_ready_claimed=False,
        )

        # Durable ledger persistence for readback, predicate, and receipt
        if mission_ledger is not None:
            try:
                ev_readback = EvidenceRecord.create(
                    action_id=actual_action.action_id,
                    mission_id=actual_action.mission_id,
                    origin=EvidenceOrigin(
                        provenance=after_read_provenance,
                        observed_at=readback_result.verified_at,
                    ),
                    payload={
                        "evidence_type": "INDEPENDENT_READBACK",
                        "readback_status": readback_result.status.value,
                        "is_match": readback_result.is_match,
                        "mismatches": list(readback_result.mismatches),
                    },
                    created_at=readback_result.verified_at,
                )
                mission_ledger.append_evidence(ev_readback)

                ev_predicate = EvidenceRecord.create(
                    action_id=actual_action.action_id,
                    mission_id=actual_action.mission_id,
                    origin=EvidenceOrigin(
                        provenance=provenance,
                        observed_at=predicate_result.evaluated_at,
                    ),
                    payload={
                        "evidence_type": "PREDICATE_EVALUATION",
                        "predicate_id": str(predicate.predicate_id),
                        "truth": predicate_result.truth.value,
                        "is_true": predicate_result.is_true,
                    },
                    created_at=predicate_result.evaluated_at,
                )
                mission_ledger.append_evidence(ev_predicate)

                ev_receipt = EvidenceRecord.create(
                    action_id=actual_action.action_id,
                    mission_id=actual_action.mission_id,
                    origin=EvidenceOrigin(
                        provenance=provenance,
                        observed_at=receipt.recorded_at,
                    ),
                    payload={
                        "evidence_type": "APPROVED_CALENDAR_UPDATE_RECEIPT",
                        "receipt": receipt.to_dict(),
                    },
                    created_at=receipt.recorded_at,
                )
                mission_ledger.append_evidence(ev_receipt)
            except Exception as exc:
                msg = (
                    f"Provider mutation executed successfully "
                    f"({provider_result.writes_performed} write), "
                    f"but durable mission ledger persistence failed: {type(exc).__name__}"
                )
                raise ApprovedExecutionPersistenceError(
                    msg,
                    provider_result=provider_result,
                    attempt=attempt,
                    gate_decision=gate_decision,
                ) from exc
    except Exception as exc:
        if mission_ledger is not None and not isinstance(exc, ApprovedExecutionPersistenceError):
            try:
                ev_failure = EvidenceRecord.create(
                    action_id=actual_action.action_id,
                    mission_id=actual_action.mission_id,
                    origin=EvidenceOrigin(
                        provenance=provenance,
                        observed_at=datetime.now(UTC),
                    ),
                    payload={
                        "evidence_type": "UNCERTAIN_POST_EXECUTION_FAILURE",
                        "attempt_id": str(attempt.attempt_id),
                        "attempt_number": attempt.attempt_number,
                        "status": gate_decision.status.value,
                        "writes_performed": provider_result.writes_performed,
                        "error_type": type(exc).__name__,
                        "error_message": redact_text(str(exc)),
                    },
                    created_at=datetime.now(UTC),
                )
                mission_ledger.append_evidence(ev_failure)
            except Exception:
                pass
        raise

    return ApprovedCalendarUpdateOutcome(
        gate_decision=gate_decision,
        consumption_record=consumption_record,
        attempt=attempt,
        provider_result=provider_result,
        before_read=before_read,
        after_read=first_read,
        readback_result=readback_result,
        predicate_result=predicate_result,
        is_verified=is_verified,
        is_ready=is_ready,
        receipt=receipt,
        mutation_observation=mutation_obs,
        readiness_determination=readiness_determination,
        is_durable=is_durable,
        mission_ready_status=mission_ready_status,
    )


__all__ = [
    "ApprovedActionReceipt",
    "ApprovedCalendarUpdateOutcome",
    "ApprovedExecutionPersistenceError",
    "CalendarMutationSpy",
    "ConflictingReadbackObservationError",
    "ExecutionGateDecision",
    "ExecutionGateError",
    "ExecutionGateTypeError",
    "ExecutionGateValueError",
    "PendingApprovalBindingMismatchError",
    "PlannerGateAuthorityError",
    "ProviderMutationObservation",
    "UnapprovedActionReceipt",
    "UnapprovedMutationBlockedError",
    "UnexpectedApprovalGrantError",
    "create_approved_action_receipt",
    "create_unapproved_action_receipt",
    "evaluate_execution_gate",
    "execute_approved_calendar_update",
    "execute_gated_action",
]
