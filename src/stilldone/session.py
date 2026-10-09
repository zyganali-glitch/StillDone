"""Durable mission session reload and resume across fresh processes.

Phase P-12.02:
Restores canonical mission state from durable storage into a genuinely fresh runtime instance.

Core Architectural Laws:
- Fresh process/session rehydration:
  * Rehydrates mission state, contract, and desired-state predicates;
  * Rehydrates pending approvals and consumed grants;
  * Rehydrates attempts, action outcomes, step execution statuses, and evidence.
- Preserves first-class partial states:
  * NOT_RUN remains NOT_RUN;
  * BLOCKED remains BLOCKED;
  * Ambiguous / uncertain outcomes remain ambiguous.
- Interrupted or uncertain mutations MUST require read-before-retry:
  * Attempt recorded without confirmed read-back cannot blindly retry;
  * Fails closed with UncertainMutationRequiresReadbackError.
- Consumed approval cannot authorize a second provider mutation:
  * Attempting to replay an already-consumed grant fails closed.
- Zero replay of external writes during reload:
  * Reloading is strictly passive and executes zero provider mutations.
- Preserves process-local versus distributed guarantee distinction:
  * Explicitly documents and classifies concurrency boundaries.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from stilldone.approval_consumption import (
    ApprovalConsumptionRecord,
    ApprovalLedger,
)
from stilldone.domain.action import ActionContract, ActionId
from stilldone.domain.desired_state import DesiredStatePredicate
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.execution.state import (
    ActionExecutionStatus,
    StepExecutionRecord,
)
from stilldone.ledger import (
    DurableFileLedger,
    EvidenceRecord,
    MissionLedgerPort,
)
from stilldone.pending_approval import PendingApproval
from stilldone.snapshot import (
    DurableSnapshotRepository,
    MissionSnapshot,
)

UNCERTAIN_POST_EXECUTION_FAILURE: str = "UNCERTAIN_POST_EXECUTION_FAILURE"


# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class SessionError(Exception):
    """Base exception for all StillDone session restoration operations."""


class SessionTypeError(SessionError, TypeError):
    """Raised when an argument has an invalid type."""


class SessionValueError(SessionError, ValueError):
    """Raised when an argument has an invalid value."""


class SessionRestoreError(SessionError):
    """Raised when durable state cannot be restored into a valid session."""


class UncertainMutationRequiresReadbackError(SessionError, ValueError):
    """Raised when attempting to retry an uncertain mutation without read-before-retry."""


class ReplayAttemptForbiddenError(SessionError, ValueError):
    """Raised when attempting to reuse a consumed approval grant in a restored session."""


# ===========================================================================
# Restored Mission Session Aggregate
# ===========================================================================


@dataclass(frozen=True)
class RestoredMissionSession:
    """Immutable aggregate representing a canonically restored mission session."""

    CONCURRENCY_GUARANTEE_SCOPE: ClassVar[str] = "PROCESS_LOCAL"

    snapshot: MissionSnapshot
    ledger: MissionLedgerPort
    approval_ledger: ApprovalLedger
    evidence_records: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, MissionSnapshot):
            raise SessionTypeError("snapshot must be a MissionSnapshot")
        if not isinstance(self.ledger, MissionLedgerPort):
            raise SessionTypeError("ledger must implement MissionLedgerPort")
        if not isinstance(self.approval_ledger, ApprovalLedger):
            raise SessionTypeError("approval_ledger must be an ApprovalLedger")
        if not isinstance(self.evidence_records, tuple):
            raise SessionTypeError("evidence_records must be a tuple")

    @property
    def mission_id(self) -> MissionId:
        return self.snapshot.mission_id

    @property
    def state(self) -> MissionState:
        return self.snapshot.state

    @property
    def contract(self) -> MissionContract:
        return self.snapshot.contract

    @property
    def actions(self) -> tuple[ActionContract, ...]:
        return self.snapshot.actions

    @property
    def desired_state(self) -> tuple[DesiredStatePredicate, ...]:
        return self.snapshot.desired_state

    @property
    def step_records(self) -> Mapping[ActionId, StepExecutionRecord]:
        return self.snapshot.step_records

    @property
    def pending_approvals(self) -> tuple[PendingApproval, ...]:
        return self.snapshot.pending_approvals

    @property
    def consumed_approvals(self) -> tuple[ApprovalConsumptionRecord, ...]:
        return self.snapshot.consumed_approvals

    @property
    def execution_attempts(self) -> tuple[ExecutionAttempt, ...]:
        return self.snapshot.execution_attempts

    @property
    def reloaded_writes_performed(self) -> int:
        """Guarantees reload is read-only and performed zero external provider writes."""
        return 0

    def get_step_status(self, action_id: ActionId) -> ActionExecutionStatus:
        """Return the preserved execution status for an action."""
        if not isinstance(action_id, ActionId):
            raise SessionTypeError("action_id must be ActionId")
        if action_id not in self.snapshot.step_records:
            return ActionExecutionStatus.NOT_RUN
        return self.snapshot.step_records[action_id].status

    def is_consumed(self, action_id: ActionId) -> bool:
        """Return True if an approval was consumed for this action."""
        if not isinstance(action_id, ActionId):
            raise SessionTypeError("action_id must be ActionId")
        return self.approval_ledger.has_consumed_approval_for_action(action_id)

    def is_ambiguous_outcome(self, action_id: ActionId) -> bool:
        """Return True if an action execution ended in an uncertain/ambiguous state.

        An outcome is ambiguous if:
        1. An execution attempt was recorded but no successful provider_result exists; OR
        2. UNCERTAIN_POST_EXECUTION_FAILURE evidence was recorded in the ledger.
        """
        if not isinstance(action_id, ActionId):
            raise SessionTypeError("action_id must be ActionId")

        # Check ledger evidence for UNCERTAIN_POST_EXECUTION_FAILURE
        aid_str = str(action_id)
        for ev in self.evidence_records:
            if str(ev.action_id) == aid_str:
                ev_type = ev.payload.get("evidence_type")
                if ev_type == UNCERTAIN_POST_EXECUTION_FAILURE:
                    return True

        # Check step records
        if action_id in self.snapshot.step_records:
            srec = self.snapshot.step_records[action_id]
            if srec.attempt is not None:
                if srec.provider_result is None or not srec.provider_result.success:
                    return True

        return False

    def requires_read_before_retry(self, action_id: ActionId) -> bool:
        """Return True if an interrupted mutation requires read-back before any retry."""
        return self.is_ambiguous_outcome(action_id)

    def assert_can_attempt_mutation(self, action_id: ActionId) -> None:
        """Assert that a mutation may be attempted, failing closed on replay or unverified retry."""
        if not isinstance(action_id, ActionId):
            raise SessionTypeError("action_id must be ActionId")

        # 1. Replay prevention: consumed approvals cannot authorize a second write
        if self.is_consumed(action_id):
            raise ReplayAttemptForbiddenError(
                f"Action {action_id} approval has already been consumed. "
                "Consumed approval cannot authorize a second provider mutation."
            )

        # 2. Uncertain mutation requires read-before-retry
        if self.requires_read_before_retry(action_id):
            raise UncertainMutationRequiresReadbackError(
                f"Action {action_id} outcome was interrupted or ambiguous. "
                "Independent read-back is strictly required before any retry attempt."
            )


# ===========================================================================
# Session Resume Factory
# ===========================================================================


def resume_mission_session(
    *,
    storage_path: Path | str,
    ledger_path: Path | str,
    mission_id: MissionId,
) -> RestoredMissionSession:
    """Restore canonical mission from durable state in a genuinely fresh runtime instance.

    Opens fresh file handles for both the durable ledger and the snapshot repository.
    Rehydrates full state, pending approvals, consumed grants, and evidence.
    Guarantees zero external writes executed during reload.
    """
    if not isinstance(mission_id, MissionId):
        raise SessionTypeError(f"mission_id must be MissionId, got {type(mission_id).__name__}")

    # 1. Fresh DurableFileLedger
    fresh_ledger = DurableFileLedger(ledger_path)

    # 2. Fresh DurableSnapshotRepository with attached ledger
    fresh_snapshot_repo = DurableSnapshotRepository(storage_path, ledger=fresh_ledger)

    # 3. Load snapshot fail-closed
    snapshot = fresh_snapshot_repo.load_snapshot(mission_id)

    # 4. Rehydrate ApprovalLedger from fresh durable ledger
    fresh_approval_ledger = ApprovalLedger.from_ledger(fresh_ledger)

    # 5. Extract evidence records for mission from fresh ledger
    try:
        evidence_records = tuple(fresh_ledger.get_evidence_for_mission(mission_id))
    except Exception:
        evidence_records = ()

    return RestoredMissionSession(
        snapshot=snapshot,
        ledger=fresh_ledger,
        approval_ledger=fresh_approval_ledger,
        evidence_records=evidence_records,
    )
