"""Partial-failure preservation and per-step execution states.

Phase P-08.03:
Defines the deterministic per-action execution-state vocabulary and state tracking.

Laws:
- EXECUTION_SUCCEEDED != VERIFIED (verification predicate truth belongs to P-09).
- EXECUTION_SUCCEEDED != READY (readiness computation belongs to P-09).
- Preserves completed earlier results when a later step fails.
- Preserves exact failed step with its attempt and error.
- Later dependency-blocked steps remain explicitly NOT_RUN / BLOCKED.
- Never collapses multi-step execution to simple overall boolean success/failure.
- Independent later actions continue deterministically if prerequisites are satisfied.
- No silent exception swallowing.
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.domain.action import ActionContract, ActionId, ActionType
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.mission import MissionId
from stilldone.execution.contracts import (
    ExecutionContractTypeError,
    ExecutionContractValueError,
    ExecutionDependencyError,
    ExecutionLineageError,
    ExecutionTransitionError,
    MissionExecutionContract,
    UnknownActionIdError,
)
from stilldone.execution.scheduler import ExecutionSchedule
from stilldone.redaction import redact_text

# ===========================================================================
# Deterministic Execution State Vocabulary
# ===========================================================================


class ActionExecutionStatus(StrEnum):
    """Deterministic per-action execution state vocabulary.

    Distinguishes execution-level outcomes:
    - NOT_RUN: Action has not been attempted.
    - IN_PROGRESS: Action is actively executing.
    - EXECUTION_SUCCEEDED: Tool / provider execution succeeded at execution level.
      (NOTE: Does NOT imply VERIFIED or READY).
    - EXECUTION_FAILED: Tool / provider execution failed at execution level.
    - BLOCKED: Action cannot execute because a prerequisite action failed.
    """

    NOT_RUN = "NOT_RUN"
    IN_PROGRESS = "IN_PROGRESS"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    BLOCKED = "BLOCKED"


# ===========================================================================
# Provider Result (Execution-level facts, separate from EvidenceRecord)
# ===========================================================================


@dataclass(frozen=True)
class ProviderExecutionResult:
    """Bounded execution-level provider facts.

    Records what the provider returned at the API/tool layer.
    Separated from EvidenceRecord and verification predicates.
    """

    action_type: ActionType
    success: bool
    status_name: str
    writes_performed: int = 0
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: Mapping[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_type, ActionType):
            raise ExecutionContractTypeError(
                f"action_type must be an ActionType, got {type(self.action_type).__name__}"
            )
        if not isinstance(self.success, bool):
            raise ExecutionContractTypeError("success must be a bool")
        if not isinstance(self.status_name, str) or not self.status_name.strip():
            raise ExecutionContractValueError("status_name must be a non-empty string")
        if not isinstance(self.writes_performed, int) or isinstance(self.writes_performed, bool):
            raise ExecutionContractTypeError("writes_performed must be an int")
        if self.writes_performed < 0:
            raise ExecutionContractValueError("writes_performed cannot be negative")
        if not isinstance(self.captured_at, datetime):
            raise ExecutionContractTypeError("captured_at must be a datetime")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ExecutionContractValueError("captured_at must be timezone-aware")
        if self.captured_at.tzinfo != UTC:
            object.__setattr__(self, "captured_at", self.captured_at.astimezone(UTC))

        # Sanitize error_message if provided
        if self.error_message is not None:
            if not isinstance(self.error_message, str):
                raise ExecutionContractTypeError("error_message must be a string or None")
            object.__setattr__(self, "error_message", redact_text(self.error_message))

        if not isinstance(self.details, Mapping):
            raise ExecutionContractTypeError("details must be a Mapping")
        object.__setattr__(self, "details", types.MappingProxyType(dict(self.details)))


# ===========================================================================
# Step Execution Record
# ===========================================================================


@dataclass(frozen=True)
class StepExecutionRecord:
    """Immutable record of the execution outcome of a single action step."""

    action_id: ActionId
    status: ActionExecutionStatus
    attempt: ExecutionAttempt | None = None
    provider_result: ProviderExecutionResult | None = None
    error_message: str | None = None
    blocked_by: ActionId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, ActionId):
            raise ExecutionContractTypeError(
                f"action_id must be an ActionId, got {type(self.action_id).__name__}"
            )
        if not isinstance(self.status, ActionExecutionStatus):
            raise ExecutionContractTypeError(
                f"status must be an ActionExecutionStatus, got {type(self.status).__name__}"
            )

        if self.attempt is not None:
            if not isinstance(self.attempt, ExecutionAttempt):
                raise ExecutionContractTypeError(
                    f"attempt must be an ExecutionAttempt or None, "
                    f"got {type(self.attempt).__name__}"
                )
            if self.attempt.action_id != self.action_id:
                raise ExecutionLineageError(
                    f"ExecutionAttempt action_id {self.attempt.action_id} does not match "
                    f"StepExecutionRecord action_id {self.action_id}"
                )

        if self.provider_result is not None and not isinstance(
            self.provider_result, ProviderExecutionResult
        ):
            raise ExecutionContractTypeError(
                f"provider_result must be a ProviderExecutionResult or None, "
                f"got {type(self.provider_result).__name__}"
            )

        if self.blocked_by is not None and not isinstance(self.blocked_by, ActionId):
            raise ExecutionContractTypeError(
                f"blocked_by must be an ActionId or None, got {type(self.blocked_by).__name__}"
            )

        if self.status == ActionExecutionStatus.NOT_RUN:
            if self.attempt is not None:
                raise ExecutionContractValueError("NOT_RUN step cannot have an attempt")
            if self.provider_result is not None:
                raise ExecutionContractValueError("NOT_RUN step cannot have a provider_result")
            if self.blocked_by is not None:
                raise ExecutionContractValueError("NOT_RUN step cannot have blocked_by")

        elif self.status == ActionExecutionStatus.IN_PROGRESS:
            if self.provider_result is not None:
                raise ExecutionContractValueError("IN_PROGRESS step cannot have a provider_result")
            if self.blocked_by is not None:
                raise ExecutionContractValueError("IN_PROGRESS step cannot have blocked_by")

        elif self.status == ActionExecutionStatus.BLOCKED:
            if self.attempt is not None:
                raise ExecutionContractValueError("BLOCKED step cannot have an attempt")
            if self.provider_result is not None:
                raise ExecutionContractValueError("BLOCKED step cannot have a provider_result")
            if self.blocked_by is None:
                raise ExecutionContractValueError("BLOCKED step must have blocked_by")

        elif self.status == ActionExecutionStatus.EXECUTION_SUCCEEDED:
            if self.attempt is None:
                raise ExecutionContractValueError("EXECUTION_SUCCEEDED step requires an attempt")
            if self.provider_result is None:
                raise ExecutionContractValueError(
                    "EXECUTION_SUCCEEDED step requires a provider_result"
                )
            if not self.provider_result.success:
                raise ExecutionContractValueError(
                    "EXECUTION_SUCCEEDED step cannot have provider_result with success=False"
                )
            if self.blocked_by is not None:
                raise ExecutionContractValueError("EXECUTION_SUCCEEDED step cannot have blocked_by")

        elif self.status == ActionExecutionStatus.EXECUTION_FAILED:
            if self.provider_result is not None and self.provider_result.success:
                raise ExecutionContractValueError(
                    "EXECUTION_FAILED step cannot have provider_result with success=True"
                )
            if self.blocked_by is not None:
                raise ExecutionContractValueError("EXECUTION_FAILED step cannot have blocked_by")

        if self.error_message is not None:
            if not isinstance(self.error_message, str):
                raise ExecutionContractTypeError("error_message must be a string or None")
            object.__setattr__(self, "error_message", redact_text(self.error_message))


# ===========================================================================
# Mission Execution Record Aggregate
# ===========================================================================


@dataclass(frozen=True)
class MissionExecutionRecord:
    """Immutable aggregate preserving complete mission execution state across all steps.

    Preserves partial-failure truth:
    - completed earlier results remain preserved;
    - exact failed step is recorded;
    - later blocked steps remain explicitly NOT_RUN / BLOCKED;
    - never collapses multi-step execution to simple overall boolean.
    """

    mission_id: MissionId
    ordered_action_ids: tuple[ActionId, ...]
    step_records: Mapping[ActionId, StepExecutionRecord]

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise ExecutionContractTypeError(
                f"mission_id must be a MissionId, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.ordered_action_ids, tuple):
            raise ExecutionContractTypeError("ordered_action_ids must be a tuple")
        if not isinstance(self.step_records, Mapping):
            raise ExecutionContractTypeError("step_records must be a Mapping")

        frozen: dict[ActionId, StepExecutionRecord] = {}
        for aid, rec in self.step_records.items():
            if not isinstance(aid, ActionId):
                raise ExecutionContractTypeError("step_records key must be ActionId")
            if not isinstance(rec, StepExecutionRecord):
                raise ExecutionContractTypeError("step_records value must be StepExecutionRecord")
            if rec.action_id != aid:
                raise ExecutionContractValueError(
                    f"Step record action_id {rec.action_id} does not match key {aid}"
                )
            frozen[aid] = rec

        object.__setattr__(self, "step_records", types.MappingProxyType(frozen))

    @property
    def has_failures(self) -> bool:
        """Return True if any step failed at execution level."""
        return any(
            r.status == ActionExecutionStatus.EXECUTION_FAILED for r in self.step_records.values()
        )

    @property
    def has_blocked(self) -> bool:
        """Return True if any step was blocked by a failed prerequisite."""
        return any(r.status == ActionExecutionStatus.BLOCKED for r in self.step_records.values())

    @property
    def is_all_succeeded(self) -> bool:
        """Return True if every step reached EXECUTION_SUCCEEDED."""
        return len(self.step_records) > 0 and all(
            r.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
            for r in self.step_records.values()
        )

    def get_status(self, action_id: ActionId) -> ActionExecutionStatus:
        """Get status of a specific action."""
        if not isinstance(action_id, ActionId):
            raise ExecutionContractTypeError(
                f"action_id must be an ActionId, got {type(action_id).__name__}"
            )
        if action_id not in self.step_records:
            raise UnknownActionIdError(f"Action {action_id} not in execution record")
        return self.step_records[action_id].status


# ===========================================================================
# Deterministic Execution State Tracker
# ===========================================================================


class ExecutionStateTracker:
    """State tracker managing step execution transitions and partial-failure preservation.

    Enforces:
    - Initial state: all actions are NOT_RUN.
    - All queries and mutations validate that ActionId belongs to the contract/schedule.
    - Unknown ActionId fails closed with UnknownActionIdError.
    - Action can only execute if all its prerequisites succeeded.
    - Transitions are strictly monotonic and validated against legal transition matrix:
        NOT_RUN -> IN_PROGRESS
        IN_PROGRESS -> EXECUTION_SUCCEEDED
        IN_PROGRESS -> EXECUTION_FAILED
        NOT_RUN -> BLOCKED
    - Terminal states (EXECUTION_SUCCEEDED, EXECUTION_FAILED, BLOCKED) cannot transition.
    - Repeated same-terminal writes fail closed.
    - If a prerequisite fails, downstream dependents are marked BLOCKED.
    - Independent actions remain eligible to run.
    - Lineage: ExecutionAttempt.action_id must match target ActionId.
    - Lineage: ProviderExecutionResult.action_type must match target ActionType.
    """

    def __init__(
        self,
        contract: MissionExecutionContract,
        schedule: ExecutionSchedule,
    ) -> None:
        if not isinstance(contract, MissionExecutionContract):
            raise ExecutionContractTypeError("contract must be a MissionExecutionContract")
        if not isinstance(schedule, ExecutionSchedule):
            raise ExecutionContractTypeError("schedule must be an ExecutionSchedule")
        if contract.mission_id != schedule.mission_id:
            raise ExecutionContractValueError("Contract and schedule mission_ids must match")

        contract_aids = frozenset(act.action_id for act in contract.actions)
        schedule_aids = frozenset(schedule.ordered_action_ids)
        if schedule_aids != contract_aids:
            raise ExecutionContractValueError(
                "Schedule action IDs must exactly match contract action IDs"
            )

        self._contract = contract
        self._schedule = schedule
        self._actions_by_id: dict[ActionId, ActionContract] = {
            act.action_id: act for act in contract.actions
        }
        self._records: dict[ActionId, StepExecutionRecord] = {
            aid: StepExecutionRecord(
                action_id=aid,
                status=ActionExecutionStatus.NOT_RUN,
            )
            for aid in schedule.ordered_action_ids
        }

    def _require_known_action_id(self, action_id: ActionId) -> None:
        """Validate that action_id is an ActionId and belongs to the contract."""
        if not isinstance(action_id, ActionId):
            raise ExecutionContractTypeError(
                f"action_id must be an ActionId, got {type(action_id).__name__}"
            )
        if action_id not in self._records:
            raise UnknownActionIdError(
                f"ActionId {action_id} does not belong to mission contract "
                f"{self._contract.mission_id}"
            )

    def can_execute(self, action_id: ActionId) -> tuple[bool, ActionId | None]:
        """Check if action is safe to execute based on prerequisite statuses.

        Returns:
            (True, None) if all prerequisites succeeded (EXECUTION_SUCCEEDED).
            (False, unsatisfied_prereq) if any prerequisite has not reached
            EXECUTION_SUCCEEDED.

        Raises:
            ExecutionContractTypeError: If action_id is not an ActionId.
            UnknownActionIdError: If action_id is not in contract.
        """
        self._require_known_action_id(action_id)
        prereqs = self._contract.dependencies.get(action_id, frozenset())
        for prereq in self._schedule.ordered_action_ids:
            if prereq in prereqs:
                if self._records[prereq].status != ActionExecutionStatus.EXECUTION_SUCCEEDED:
                    return False, prereq
        return True, None

    def mark_in_progress(self, action_id: ActionId) -> None:
        """Mark action as currently in progress.

        Enforces:
        - action_id belongs to the contract/schedule.
        - action is currently in NOT_RUN state.
        - every prerequisite action has reached EXECUTION_SUCCEEDED.

        Raises:
            ExecutionContractTypeError: If action_id is not an ActionId.
            UnknownActionIdError: If action_id is not in contract.
            ExecutionTransitionError: If action is not in NOT_RUN state.
            ExecutionDependencyError: If any prerequisite is not in EXECUTION_SUCCEEDED.
        """
        self._require_known_action_id(action_id)
        current = self._records[action_id].status
        if current != ActionExecutionStatus.NOT_RUN:
            raise ExecutionTransitionError(
                f"Cannot transition action {action_id} from {current.value} to IN_PROGRESS: "
                f"only NOT_RUN actions can transition to IN_PROGRESS"
            )
        can_run, unsatisfied_prereq = self.can_execute(action_id)
        if not can_run:
            assert unsatisfied_prereq is not None
            prereq_status = self._records[unsatisfied_prereq].status
            raise ExecutionDependencyError(
                f"Cannot transition action {action_id} to IN_PROGRESS: "
                f"prerequisite action {unsatisfied_prereq} is in state {prereq_status.value} "
                f"(must be EXECUTION_SUCCEEDED)"
            )
        self._records[action_id] = StepExecutionRecord(
            action_id=action_id,
            status=ActionExecutionStatus.IN_PROGRESS,
        )

    def record_success(
        self,
        action_id: ActionId,
        attempt: ExecutionAttempt,
        provider_result: ProviderExecutionResult,
    ) -> None:
        """Record successful execution of an action.

        Raises:
            ExecutionContractTypeError: If arguments are of invalid types.
            UnknownActionIdError: If action_id is not in contract.
            ExecutionTransitionError: If action is not in IN_PROGRESS state.
            ExecutionLineageError: If attempt or provider_result does not match action.
            ExecutionContractValueError: If provider_result.success is not True.
        """
        self._require_known_action_id(action_id)
        current = self._records[action_id].status
        if current != ActionExecutionStatus.IN_PROGRESS:
            raise ExecutionTransitionError(
                f"Cannot transition action {action_id} from {current.value} to "
                f"EXECUTION_SUCCEEDED: action must be in IN_PROGRESS state"
            )
        if not isinstance(attempt, ExecutionAttempt):
            raise ExecutionContractTypeError(
                f"attempt must be an ExecutionAttempt, got {type(attempt).__name__}"
            )
        if attempt.action_id != action_id:
            raise ExecutionLineageError(
                f"attempt.action_id {attempt.action_id} does not match action_id {action_id}"
            )
        if not isinstance(provider_result, ProviderExecutionResult):
            raise ExecutionContractTypeError(
                f"provider_result must be a ProviderExecutionResult, "
                f"got {type(provider_result).__name__}"
            )
        expected_action_type = self._actions_by_id[action_id].action_type
        if provider_result.action_type != expected_action_type:
            raise ExecutionLineageError(
                f"provider_result action_type {provider_result.action_type.value} does not match "
                f"expected action_type {expected_action_type.value}"
            )
        if not provider_result.success:
            raise ExecutionContractValueError(
                "record_success requires provider_result.success to be True"
            )

        self._records[action_id] = StepExecutionRecord(
            action_id=action_id,
            status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
            attempt=attempt,
            provider_result=provider_result,
        )

    def record_failure(
        self,
        action_id: ActionId,
        attempt: ExecutionAttempt,
        provider_result: ProviderExecutionResult | None,
        error_message: str,
    ) -> None:
        """Record failed execution of an action and block its dependents.

        Raises:
            ExecutionContractTypeError: If arguments are of invalid types.
            UnknownActionIdError: If action_id is not in contract.
            ExecutionTransitionError: If action is not in IN_PROGRESS state.
            ExecutionLineageError: If attempt or provider_result does not match action.
            ExecutionContractValueError: If provider_result.success is True or
                error_message is invalid.
        """
        self._require_known_action_id(action_id)
        current = self._records[action_id].status
        if current != ActionExecutionStatus.IN_PROGRESS:
            raise ExecutionTransitionError(
                f"Cannot transition action {action_id} from {current.value} to "
                f"EXECUTION_FAILED: action must be in IN_PROGRESS state"
            )
        if not isinstance(attempt, ExecutionAttempt):
            raise ExecutionContractTypeError(
                f"attempt must be an ExecutionAttempt, got {type(attempt).__name__}"
            )
        if attempt.action_id != action_id:
            raise ExecutionLineageError(
                f"attempt.action_id {attempt.action_id} does not match action_id {action_id}"
            )
        expected_action_type = self._actions_by_id[action_id].action_type
        if provider_result is not None:
            if not isinstance(provider_result, ProviderExecutionResult):
                raise ExecutionContractTypeError(
                    f"provider_result must be a ProviderExecutionResult or None, "
                    f"got {type(provider_result).__name__}"
                )
            if provider_result.action_type != expected_action_type:
                raise ExecutionLineageError(
                    f"provider_result action_type {provider_result.action_type.value} "
                    f"does not match expected action_type {expected_action_type.value}"
                )
            if provider_result.success:
                raise ExecutionContractValueError(
                    "record_failure requires provider_result.success to be False when provided"
                )
        if not isinstance(error_message, str) or not error_message.strip():
            raise ExecutionContractValueError("error_message must be a non-empty string")

        self._records[action_id] = StepExecutionRecord(
            action_id=action_id,
            status=ActionExecutionStatus.EXECUTION_FAILED,
            attempt=attempt,
            provider_result=provider_result,
            error_message=error_message,
        )
        # Transitively block downstream dependents of this failed action
        self._block_downstream_dependents(action_id)

    def record_blocked(
        self,
        action_id: ActionId,
        blocked_by: ActionId,
        reason: str | None = None,
    ) -> None:
        """Explicitly record action as blocked by a failed prerequisite.

        Raises:
            ExecutionContractTypeError: If action_id or blocked_by is not an ActionId.
            UnknownActionIdError: If action_id or blocked_by is not in contract.
            ExecutionTransitionError: If action is not in NOT_RUN state.
        """
        self._require_known_action_id(action_id)
        if not isinstance(blocked_by, ActionId):
            raise ExecutionContractTypeError(
                f"blocked_by must be an ActionId, got {type(blocked_by).__name__}"
            )
        if blocked_by not in self._records:
            raise UnknownActionIdError(
                f"blocked_by ActionId {blocked_by} does not belong to mission contract "
                f"{self._contract.mission_id}"
            )
        current = self._records[action_id].status
        if current != ActionExecutionStatus.NOT_RUN:
            raise ExecutionTransitionError(
                f"Cannot transition action {action_id} from {current.value} to BLOCKED: "
                f"only NOT_RUN actions can transition to BLOCKED"
            )
        msg = reason or f"Blocked by failed prerequisite action {blocked_by}"
        self._records[action_id] = StepExecutionRecord(
            action_id=action_id,
            status=ActionExecutionStatus.BLOCKED,
            blocked_by=blocked_by,
            error_message=msg,
        )

    def record_not_run(
        self,
        action_id: ActionId,
        *,
        reason: str | None = None,
    ) -> None:
        """Explicitly record that an action remains NOT_RUN (e.g. unapproved mutation).

        Raises:
            ExecutionContractTypeError: If action_id is not an ActionId.
            UnknownActionIdError: If action_id is not in contract.
            ExecutionTransitionError: If action is not in NOT_RUN state.
        """
        self._require_known_action_id(action_id)
        current = self._records[action_id].status
        if current != ActionExecutionStatus.NOT_RUN:
            raise ExecutionTransitionError(
                f"Cannot record NOT_RUN for action {action_id} from state {current.value}: "
                f"only NOT_RUN actions can remain NOT_RUN"
            )
        self._records[action_id] = StepExecutionRecord(
            action_id=action_id,
            status=ActionExecutionStatus.NOT_RUN,
            error_message=reason,
        )

    def get_status(self, action_id: ActionId) -> ActionExecutionStatus:
        """Get execution status of a specific action."""
        self._require_known_action_id(action_id)
        return self._records[action_id].status

    def get_record(self, action_id: ActionId) -> StepExecutionRecord:
        """Get execution record of a specific action."""
        self._require_known_action_id(action_id)
        return self._records[action_id]

    def _block_downstream_dependents(self, failed_action_id: ActionId) -> None:
        """Find all downstream actions depending on failed_action_id and mark BLOCKED."""
        to_block: list[ActionId] = []
        for aid in self._schedule.ordered_action_ids:
            if self._records[aid].status == ActionExecutionStatus.NOT_RUN:
                deps = self._contract.dependencies.get(aid, frozenset())
                if failed_action_id in deps or any(d in to_block for d in deps):
                    to_block.append(aid)
                    self.record_blocked(aid, blocked_by=failed_action_id)

    def snapshot(self) -> MissionExecutionRecord:
        """Produce an immutable MissionExecutionRecord snapshot."""
        return MissionExecutionRecord(
            mission_id=self._contract.mission_id,
            ordered_action_ids=self._schedule.ordered_action_ids,
            step_records=dict(self._records),
        )
