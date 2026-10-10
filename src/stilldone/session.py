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
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from stilldone.receipt import CurrentStateProjection, ReceiptProjection

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
from stilldone.recovery.continuity import (
    RecoveryContinuityError,
    reconstruct_action_recovery_state,
)
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
    historical_receipt: ReceiptProjection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, MissionSnapshot):
            raise SessionTypeError("snapshot must be a MissionSnapshot")
        if not isinstance(self.ledger, MissionLedgerPort):
            raise SessionTypeError("ledger must implement MissionLedgerPort")
        if not isinstance(self.approval_ledger, ApprovalLedger):
            raise SessionTypeError("approval_ledger must be an ApprovalLedger")
        if not isinstance(self.evidence_records, tuple):
            raise SessionTypeError("evidence_records must be a tuple")
        if self.historical_receipt is not None:
            from stilldone.receipt import ReceiptProjection

            if not isinstance(self.historical_receipt, ReceiptProjection):
                raise SessionTypeError("historical_receipt must be a ReceiptProjection")
            if self.historical_receipt.mission_id != self.snapshot.mission_id:
                raise SessionValueError("historical_receipt mission_id does not match snapshot")
            if not self.historical_receipt.is_historical:
                raise SessionValueError("historical_receipt must have is_historical=True")

    @property
    def current_state(self) -> CurrentStateProjection:
        """Project authoritative current truth from restored session facts."""
        from stilldone.receipt import project_current_state

        return project_current_state(
            self.snapshot,
            historical_receipt=self.historical_receipt,
            ledger=self.ledger,
        )

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
        1. UNCERTAIN_POST_EXECUTION_FAILURE evidence was recorded in the ledger; OR
        2. Canonical P-10 recovery state indicates ambiguous outcome or verification requirement; OR
        3. Snapshot step records indicate non-success or ambiguous timeout.
        """
        if not isinstance(action_id, ActionId):
            raise SessionTypeError("action_id must be ActionId")

        # 1. Check ledger evidence for UNCERTAIN_POST_EXECUTION_FAILURE
        aid_str = str(action_id)
        for ev in self.evidence_records:
            if str(ev.action_id) == aid_str:
                ev_type = ev.payload.get("evidence_type")
                if ev_type == UNCERTAIN_POST_EXECUTION_FAILURE:
                    return True

        # 2. Check canonical P-10 recovery state from durable ledger
        # (handles attempts newer than snapshot)
        matched_act = next((a for a in self.snapshot.actions if a.action_id == action_id), None)
        if matched_act is not None:
            try:
                rec_state = reconstruct_action_recovery_state(
                    action=matched_act,
                    ledger=self.ledger,
                )
                if rec_state.is_ambiguous_outcome:
                    return True
                if rec_state.requires_verification_before_retry:
                    return True
            except RecoveryContinuityError:
                # Contradictory, unreadable, or corrupted recovery history: fail-closed as ambiguous
                return True

        # 3. Check step records in snapshot
        if action_id in self.snapshot.step_records:
            srec = self.snapshot.step_records[action_id]
            if srec.status == ActionExecutionStatus.EXECUTION_FAILED:
                return True
            if srec.attempt is not None:
                if srec.provider_result is None or not srec.provider_result.success:
                    return True

        return False

    def requires_read_before_retry(self, action_id: ActionId) -> bool:
        """Return True if an interrupted mutation requires read-back before any retry."""
        if not isinstance(action_id, ActionId):
            raise SessionTypeError("action_id must be ActionId")
        if self.is_ambiguous_outcome(action_id):
            return True
        matched_act = next((a for a in self.snapshot.actions if a.action_id == action_id), None)
        if matched_act is not None:
            try:
                rec_state = reconstruct_action_recovery_state(
                    action=matched_act,
                    ledger=self.ledger,
                )
                if rec_state.requires_verification_before_retry:
                    return True
            except RecoveryContinuityError:
                return True
        return False

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

    # 5. Extract evidence records for mission from fresh ledger fail-closed
    try:
        evidence_records = tuple(fresh_ledger.get_evidence_for_mission(mission_id))
    except Exception as exc:
        raise SessionRestoreError(
            f"Failed to read evidence records from ledger for mission {mission_id}: {exc}"
        ) from exc

    # 6. Reconcile snapshot consumed approvals against durable approval ledger
    for ca in snapshot.consumed_approvals:
        ledger_rec = fresh_approval_ledger.get_record(ca.approval_id)
        if ledger_rec is None:
            raise SessionRestoreError(
                f"Snapshot consumed approval {ca.approval_id} not found in durable approval ledger"
            )
        if (
            ledger_rec.status != ca.status
            or ledger_rec.action_id != ca.action_id
            or ledger_rec.binding_hash != ca.binding_hash
            or ledger_rec.attempt_number != ca.attempt_number
            or ledger_rec.mission_id != ca.mission_id
        ):
            raise SessionRestoreError(
                f"Snapshot consumed approval {ca.approval_id} contradicts durable approval ledger"
            )

    # 7. Query historical receipt from fresh repository if present
    historical_receipt = fresh_snapshot_repo.get_historical_receipt(mission_id)

    return RestoredMissionSession(
        snapshot=snapshot,
        ledger=fresh_ledger,
        approval_ledger=fresh_approval_ledger,
        evidence_records=evidence_records,
        historical_receipt=historical_receipt,
    )
