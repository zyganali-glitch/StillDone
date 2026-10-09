"""Deterministic approval consumption, single-use enforcement, and replay rejection.

Phase P-11.04:
A valid bound approval is not permanently reusable authority.
Enforces:
- ONE APPROVAL DECISION -> ONE EXACT APPROVAL -> AT MOST ONE AUTHORIZED MUTATION ATTEMPT.
- Rejects stale/expired, not-yet-valid, mismatched, tampered, or already-used approvals.
- Separates authority from execution: consumption authorizes at most one attempt,
  but does NOT execute mutations, assert execution success, or assert desired-state truth (READY).
- Consumption ordering: approval consumed BEFORE mutation attempt to eliminate replay holes.
- Durable restart resilience: when backed by MissionLedgerPort (e.g. DurableFileLedger),
  consumed approvals survive process restart and cannot be replayed.
- P-10 Idempotency / recovery isolation: recovery verification does not require approval replay.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.action_policy import ValidatedActionContract
from stilldone.approval_binding import verify_approval_binding
from stilldone.authority_policy import (
    assert_not_planner_for_authority,
)
from stilldone.domain.action import ActionContract, ActionId
from stilldone.domain.authority import (
    ApprovalGrant,
    ApprovalId,
    BindingHash,
)
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.ledger import EvidenceRecord, MissionLedgerPort
from stilldone.redaction import redact_text

APPROVAL_CONSUMPTION_EVIDENCE_TYPE: str = "APPROVAL_CONSUMPTION"
APPROVAL_REVOCATION_EVIDENCE_TYPE: str = "APPROVAL_REVOCATION"

# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class ApprovalConsumptionError(Exception):
    """Base exception for all StillDone approval consumption operations."""


class ApprovalConsumptionTypeError(ApprovalConsumptionError, TypeError):
    """Raised when an argument has an invalid type."""


class ApprovalConsumptionValueError(ApprovalConsumptionError, ValueError):
    """Raised when an argument has an invalid value."""


class ApprovalPersistenceError(ApprovalConsumptionError):
    """Base exception for approval durable persistence failures."""


class ApprovalConsumptionPersistenceError(ApprovalPersistenceError):
    """Raised when durably persisting approval consumption fails."""


class ApprovalRevocationPersistenceError(ApprovalPersistenceError):
    """Raised when durably persisting approval revocation fails."""


class ApprovalAlreadyUsedError(ApprovalConsumptionError, ValueError):
    """Raised when an approval grant has already been consumed (replay attempt)."""


class ApprovalRevokedError(ApprovalConsumptionError, ValueError):
    """Raised when an approval grant has been explicitly revoked."""


class UnknownApprovalIdError(ApprovalConsumptionError, KeyError):
    """Raised when an approval identifier is unknown to a strict registry."""


class MalformedApprovalStateError(ApprovalConsumptionError, ValueError):
    """Raised when approval use/consumption state fails integrity or schema checks."""


# ===========================================================================
# Status and Record Contracts
# ===========================================================================


class ApprovalUsageStatus(StrEnum):
    """Closed-world lifecycle status for an ApprovalGrant."""

    UNUSED = "UNUSED"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class ApprovalConsumptionRecord:
    """Immutable record of an approval consumption or revocation event."""

    approval_id: ApprovalId
    mission_id: MissionId
    action_id: ActionId
    binding_hash: BindingHash
    status: ApprovalUsageStatus
    consumed_at: datetime
    attempt_number: int = 1
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.approval_id, ApprovalId):
            raise ApprovalConsumptionTypeError(
                f"approval_id must be an ApprovalId instance, got {type(self.approval_id).__name__}"
            )
        if not isinstance(self.mission_id, MissionId):
            raise ApprovalConsumptionTypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.action_id, ActionId):
            raise ApprovalConsumptionTypeError(
                f"action_id must be an ActionId instance, got {type(self.action_id).__name__}"
            )
        if not isinstance(self.binding_hash, BindingHash):
            raise ApprovalConsumptionTypeError(
                "binding_hash must be a BindingHash instance, "
                f"got {type(self.binding_hash).__name__}"
            )
        if not isinstance(self.status, ApprovalUsageStatus):
            raise ApprovalConsumptionTypeError(
                f"status must be an ApprovalUsageStatus instance, got {type(self.status).__name__}"
            )
        if not isinstance(self.consumed_at, datetime):
            raise ApprovalConsumptionTypeError(
                f"consumed_at must be a datetime instance, got {type(self.consumed_at).__name__}"
            )
        if self.consumed_at.tzinfo is None or self.consumed_at.utcoffset() is None:
            raise ApprovalConsumptionValueError("consumed_at must be timezone-aware")
        if self.consumed_at.tzinfo != UTC:
            object.__setattr__(self, "consumed_at", self.consumed_at.astimezone(UTC))

        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int):
            raise ApprovalConsumptionTypeError("attempt_number must be an integer")
        if self.attempt_number < 1:
            raise ApprovalConsumptionValueError("attempt_number must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        """Convert record to a serializable, privacy-safe dictionary."""
        return {
            "approval_id": str(self.approval_id),
            "mission_id": str(self.mission_id),
            "action_id": str(self.action_id),
            "binding_hash": self.binding_hash.value,
            "status": self.status.value,
            "consumed_at": self.consumed_at.isoformat(),
            "attempt_number": self.attempt_number,
            "reason": redact_text(self.reason) if self.reason is not None else None,
        }


@dataclass(frozen=True)
class ApprovalConsumptionResult:
    """Immutable result of consuming an ApprovalGrant.

    Represents authority to execute AT MOST ONE mutation attempt.
    Crucial separation:
    - is_authorized = True (authority to attempt mutation).
    - execution_outcome is strictly None (execution has NOT yet occurred).
    - is_verified is strictly False (desired state is NOT yet proven).
    - is_ready is strictly False (mission is NOT yet READY).
    """

    approval_id: ApprovalId
    consumed_at: datetime
    attempt_number: int
    is_authorized: bool = True
    execution_outcome: Any = None
    is_verified: bool = False
    is_ready: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.approval_id, ApprovalId):
            raise ApprovalConsumptionTypeError(
                f"approval_id must be an ApprovalId instance, got {type(self.approval_id).__name__}"
            )
        if not isinstance(self.consumed_at, datetime):
            raise ApprovalConsumptionTypeError(
                f"consumed_at must be a datetime instance, got {type(self.consumed_at).__name__}"
            )
        if self.consumed_at.tzinfo is None or self.consumed_at.utcoffset() is None:
            raise ApprovalConsumptionValueError("consumed_at must be timezone-aware")
        if self.consumed_at.tzinfo != UTC:
            object.__setattr__(self, "consumed_at", self.consumed_at.astimezone(UTC))

        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int):
            raise ApprovalConsumptionTypeError("attempt_number must be an integer")
        if self.attempt_number < 1:
            raise ApprovalConsumptionValueError("attempt_number must be >= 1")

        if type(self.is_authorized) is not bool:
            raise ApprovalConsumptionTypeError("is_authorized must be a bool")
        if self.execution_outcome is not None:
            raise ApprovalConsumptionValueError(
                "Approval consumption cannot assert an execution outcome; "
                "execution must occur downstream"
            )
        if self.is_verified:
            raise ApprovalConsumptionValueError(
                "Approval consumption cannot assert verified state; "
                "verification requires independent read-back"
            )
        if self.is_ready:
            raise ApprovalConsumptionValueError(
                "Approval consumption cannot assert mission READY state"
            )


# ===========================================================================
# In-Memory Used Approval Registry
# ===========================================================================


class UsedApprovalRegistry:
    """Thread-safe process-local registry tracking consumed and revoked approvals."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, ApprovalConsumptionRecord] = {}

    def is_used(self, approval_id: ApprovalId | str) -> bool:
        """Check if an approval ID has been consumed or revoked."""
        key = str(approval_id)
        with self._lock:
            rec = self._records.get(key)
            return rec is not None and rec.status in {
                ApprovalUsageStatus.CONSUMED,
                ApprovalUsageStatus.REVOKED,
            }

    def is_consumed(self, approval_id: ApprovalId | str) -> bool:
        """Check if an approval ID has been consumed."""
        key = str(approval_id)
        with self._lock:
            rec = self._records.get(key)
            return rec is not None and rec.status == ApprovalUsageStatus.CONSUMED

    def is_revoked(self, approval_id: ApprovalId | str) -> bool:
        """Check if an approval ID has been revoked."""
        key = str(approval_id)
        with self._lock:
            rec = self._records.get(key)
            return rec is not None and rec.status == ApprovalUsageStatus.REVOKED

    def get_record(self, approval_id: ApprovalId | str) -> ApprovalConsumptionRecord | None:
        """Retrieve the consumption record for an approval ID if present."""
        key = str(approval_id)
        with self._lock:
            return self._records.get(key)

    def record_consumption(
        self,
        grant: ApprovalGrant,
        *,
        at: datetime,
        attempt_number: int = 1,
    ) -> ApprovalConsumptionRecord:
        """Record the consumption of an ApprovalGrant fail-closed against replays."""
        key = str(grant.approval_id)
        norm_at = at if at.tzinfo == UTC else at.astimezone(UTC)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing.status == ApprovalUsageStatus.CONSUMED:
                    raise ApprovalAlreadyUsedError(
                        f"Approval '{grant.approval_id}' was already consumed at "
                        f"{existing.consumed_at.isoformat()} for attempt {existing.attempt_number}"
                    )
                if existing.status == ApprovalUsageStatus.REVOKED:
                    raise ApprovalRevokedError(
                        f"Approval '{grant.approval_id}' was revoked and cannot be consumed"
                    )

            record = ApprovalConsumptionRecord(
                approval_id=grant.approval_id,
                mission_id=grant.mission_id,
                action_id=grant.action_id,
                binding_hash=grant.binding_hash,
                status=ApprovalUsageStatus.CONSUMED,
                consumed_at=norm_at,
                attempt_number=attempt_number,
            )
            self._records[key] = record
            return record

    def revoke(
        self,
        grant: ApprovalGrant | ApprovalId | str,
        *,
        at: datetime,
        mission_id: MissionId | None = None,
        action_id: ActionId | None = None,
        binding_hash: BindingHash | None = None,
        reason: str | None = None,
    ) -> ApprovalConsumptionRecord:
        """Explicitly revoke an ApprovalGrant."""
        norm_at = at if at.tzinfo == UTC else at.astimezone(UTC)
        if isinstance(grant, ApprovalGrant):
            aid = grant.approval_id
            mid = grant.mission_id
            act_id = grant.action_id
            b_hash = grant.binding_hash
        else:
            aid = grant if isinstance(grant, ApprovalId) else ApprovalId(str(grant))
            existing_rec = self._records.get(str(aid))
            if existing_rec is not None:
                mid = mission_id or existing_rec.mission_id
                act_id = action_id or existing_rec.action_id
                b_hash = binding_hash or existing_rec.binding_hash
            elif mission_id is not None and action_id is not None and binding_hash is not None:
                mid = mission_id
                act_id = action_id
                b_hash = binding_hash
            else:
                raise ApprovalConsumptionValueError(
                    f"Cannot revoke approval '{aid}': canonical lineage "
                    "(mission_id, action_id, binding_hash) must be provided"
                )

        key = str(aid)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if (
                    existing.mission_id != mid
                    or existing.action_id != act_id
                    or existing.binding_hash != b_hash
                ):
                    raise MalformedApprovalStateError(
                        f"Contradictory approval lineage during revocation of '{aid}'"
                    )
                if existing.status == ApprovalUsageStatus.REVOKED:
                    return existing

            record = ApprovalConsumptionRecord(
                approval_id=aid,
                mission_id=mid,
                action_id=act_id,
                binding_hash=b_hash,
                status=ApprovalUsageStatus.REVOKED,
                consumed_at=norm_at,
                attempt_number=1,
                reason=reason,
            )
            self._records[key] = record
            return record

    def reset(self) -> None:
        """Clear all records (intended for test suite isolation)."""
        with self._lock:
            self._records.clear()

    def has_consumed_approval_for_action(self, action_id: ActionId | str) -> bool:
        """Check if any approval has been consumed for the given action ID."""
        if not isinstance(action_id, (ActionId, str)):
            raise ApprovalConsumptionTypeError(
                f"action_id must be an ActionId or str, got {type(action_id).__name__}"
            )
        act_id = action_id if isinstance(action_id, ActionId) else ActionId(action_id)
        with self._lock:
            return any(
                rec.action_id == act_id and rec.status == ApprovalUsageStatus.CONSUMED
                for rec in self._records.values()
            )

    def get_consumed_records_for_action(
        self, action_id: ActionId | str
    ) -> tuple[ApprovalConsumptionRecord, ...]:
        """Retrieve all consumed approval records for the given action ID."""
        if not isinstance(action_id, (ActionId, str)):
            raise ApprovalConsumptionTypeError(
                f"action_id must be an ActionId or str, got {type(action_id).__name__}"
            )
        act_id = action_id if isinstance(action_id, ActionId) else ActionId(action_id)
        with self._lock:
            return tuple(
                rec
                for rec in self._records.values()
                if rec.action_id == act_id and rec.status == ApprovalUsageStatus.CONSUMED
            )


# Default process-local registry instance
used_approval_registry: UsedApprovalRegistry = UsedApprovalRegistry()


# ===========================================================================
# Durable Approval Ledger
# ===========================================================================


class ApprovalLedger:
    """Manages approval consumption and single-use state.

    Supports dual modes:
    - Process-local in-memory registry (default).
    - Durable persistence backed by MissionLedgerPort (e.g. DurableFileLedger),
      ensuring consumed approvals survive process restarts.

    Concurrency & Durability Guarantee:
    - Process-local transaction-level thread-safety via internal re-entrant lock (RLock).
    - Durable across process restarts when backed by a canonical MissionLedgerPort.
    - Strictly process-local: NO distributed or cross-process multi-instance
      atomic locking is provided.
    """

    def __init__(
        self,
        *,
        ledger: MissionLedgerPort | None = None,
        registry: UsedApprovalRegistry | None = None,
    ) -> None:
        if ledger is not None and not isinstance(ledger, MissionLedgerPort):
            raise ApprovalConsumptionTypeError("ledger must implement MissionLedgerPort")
        if registry is not None and not isinstance(registry, UsedApprovalRegistry):
            raise ApprovalConsumptionTypeError("registry must be a UsedApprovalRegistry instance")

        self._lock = threading.RLock()
        self._ledger = ledger
        self._registry = registry or UsedApprovalRegistry()

        # If backed by a ledger, hydrate existing records under transaction lock
        if self._ledger is not None:
            with self._lock:
                self._hydrate_from_ledger()

    @classmethod
    def from_ledger(cls, ledger: MissionLedgerPort) -> ApprovalLedger:
        """Construct an ApprovalLedger hydrated from an existing MissionLedgerPort.

        Used across process restarts to reconstruct consumed approval state.
        """
        if not isinstance(ledger, MissionLedgerPort):
            raise ApprovalConsumptionTypeError("ledger must implement MissionLedgerPort")
        return cls(ledger=ledger)

    def _hydrate_from_ledger(self) -> None:
        """Reconstruct consumed and revoked approval state from ledger evidence records."""
        if self._ledger is None:
            return

        if not hasattr(self._ledger, "get_all_evidence") or not callable(
            getattr(self._ledger, "get_all_evidence", None)
        ):
            raise MalformedApprovalStateError(
                f"Ledger {type(self._ledger).__name__} does not implement get_all_evidence; "
                "cannot safely reconstruct durable approval history"
            )

        try:
            evidence_records = self._ledger.get_all_evidence()
        except Exception as exc:
            raise MalformedApprovalStateError(
                f"Failed to query evidence records from ledger: {exc}"
            ) from exc

        # Track history per approval_id during hydration to enforce closed-world transitions
        # and fail closed on contradictory lineage.
        hydrated_records: dict[str, ApprovalConsumptionRecord] = {}

        for ev in evidence_records:
            payload = ev.payload.to_dict() if hasattr(ev.payload, "to_dict") else dict(ev.payload)
            ev_type = payload.get("evidence_type")
            if ev_type not in {
                APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
                APPROVAL_REVOCATION_EVIDENCE_TYPE,
            }:
                continue

            try:
                raw_aid = payload.get("approval_id")
                if not raw_aid or not isinstance(raw_aid, str):
                    raise MalformedApprovalStateError(
                        "Missing or invalid approval_id in approval evidence"
                    )
                aid = ApprovalId(raw_aid)

                raw_mid = payload.get("mission_id")
                if not raw_mid or not isinstance(raw_mid, str):
                    raise MalformedApprovalStateError(
                        "Missing or invalid mission_id in approval evidence"
                    )
                mid = MissionId(raw_mid)

                raw_act_id = payload.get("action_id")
                if not raw_act_id or not isinstance(raw_act_id, str):
                    raise MalformedApprovalStateError(
                        "Missing or invalid action_id in approval evidence"
                    )
                act_id = ActionId(raw_act_id)

                raw_hash = payload.get("binding_hash")
                if not raw_hash or not isinstance(raw_hash, str):
                    raise MalformedApprovalStateError(
                        "Missing or invalid binding_hash in approval evidence"
                    )
                b_hash = BindingHash(raw_hash)

                # Header consistency: EvidenceRecord header must match payload
                if ev.action_id != act_id or ev.mission_id != mid:
                    raise MalformedApprovalStateError(
                        f"EvidenceRecord header (action={ev.action_id}, mission={ev.mission_id}) "
                        f"contradicts payload (action={act_id}, mission={mid})"
                    )

                status_val = (
                    ApprovalUsageStatus.CONSUMED
                    if ev_type == APPROVAL_CONSUMPTION_EVIDENCE_TYPE
                    else ApprovalUsageStatus.REVOKED
                )

                consumed_at_str = payload.get("consumed_at")
                if not consumed_at_str or not isinstance(consumed_at_str, str):
                    raise MalformedApprovalStateError(
                        "Missing or invalid consumed_at in approval evidence"
                    )
                consumed_at = datetime.fromisoformat(consumed_at_str)
                if consumed_at.tzinfo is None:
                    raise MalformedApprovalStateError("consumed_at must be timezone-aware")
                consumed_at_utc = (
                    consumed_at if consumed_at.tzinfo == UTC else consumed_at.astimezone(UTC)
                )

                attempt_num = payload.get("consumed_for_attempt", 1)
                if (
                    isinstance(attempt_num, bool)
                    or not isinstance(attempt_num, int)
                    or attempt_num < 1
                ):
                    raise MalformedApprovalStateError("Invalid attempt number in approval evidence")

                key = str(aid)
                if key in hydrated_records:
                    existing = hydrated_records[key]

                    # 1. Lineage consistency check:
                    # For the same approval_id, canonical immutable lineage MUST NOT change.
                    if existing.mission_id != mid:
                        raise MalformedApprovalStateError(
                            f"Contradictory approval history for '{aid}': mission_id "
                            f"changed from '{existing.mission_id}' to '{mid}'"
                        )
                    if existing.action_id != act_id:
                        raise MalformedApprovalStateError(
                            f"Contradictory approval history for '{aid}': action_id "
                            f"changed from '{existing.action_id}' to '{act_id}'"
                        )
                    if existing.binding_hash != b_hash:
                        raise MalformedApprovalStateError(
                            f"Contradictory approval history for '{aid}': binding_hash "
                            f"changed from '{existing.binding_hash}' to '{b_hash}'"
                        )

                    # 2. Closed-world status transition validation:
                    # Allowed:
                    # UNUSED -> CONSUMED
                    # UNUSED -> REVOKED
                    # CONSUMED -> REVOKED
                    # REVOKED -> REVOKED (idempotent duplicate revocation)
                    # Forbidden:
                    # REVOKED -> CONSUMED
                    # CONSUMED -> CONSUMED (duplicate/replay consumption in durable history)
                    if existing.status == ApprovalUsageStatus.REVOKED:
                        if status_val == ApprovalUsageStatus.CONSUMED:
                            raise MalformedApprovalStateError(
                                f"Forbidden approval status transition for '{aid}': "
                                "REVOKED -> CONSUMED is prohibited"
                            )
                        # REVOKED -> REVOKED retains REVOKED
                    elif existing.status == ApprovalUsageStatus.CONSUMED:
                        if status_val == ApprovalUsageStatus.CONSUMED:
                            raise MalformedApprovalStateError(
                                f"Duplicate or replay consumption in durable history for '{aid}': "
                                "approval cannot be consumed multiple times"
                            )
                        # CONSUMED -> REVOKED transitions to REVOKED

                rec = ApprovalConsumptionRecord(
                    approval_id=aid,
                    mission_id=mid,
                    action_id=act_id,
                    binding_hash=b_hash,
                    status=status_val,
                    consumed_at=consumed_at_utc,
                    attempt_number=attempt_num,
                    reason=payload.get("reason"),
                )
                hydrated_records[key] = rec
            except MalformedApprovalStateError:
                raise
            except Exception as exc:
                raise MalformedApprovalStateError(
                    f"Corrupt or malformed approval consumption evidence: {exc}"
                ) from exc

        # Commit validated hydrated records into the registry under registry lock
        with self._registry._lock:
            for key, rec in hydrated_records.items():
                self._registry._records[key] = rec

    def check_status(self, approval_id: ApprovalId | str) -> ApprovalUsageStatus:
        """Check the current usage status of an approval ID."""
        key = str(approval_id)
        with self._lock:
            rec = self._registry.get_record(key)
            if rec is None:
                return ApprovalUsageStatus.UNUSED
            return rec.status

    def is_used(self, approval_id: ApprovalId | str) -> bool:
        """Check if an approval ID has been consumed or revoked."""
        with self._lock:
            return self._registry.is_used(approval_id)

    def is_consumed(self, approval_id: ApprovalId | str) -> bool:
        """Check if an approval ID has been consumed."""
        with self._lock:
            return self._registry.is_consumed(approval_id)

    def is_revoked(self, approval_id: ApprovalId | str) -> bool:
        """Check if an approval ID has been revoked."""
        with self._lock:
            return self._registry.is_revoked(approval_id)

    def has_consumed_approval_for_action(self, action_id: ActionId | str) -> bool:
        """Check if any approval has been consumed for the given action ID.

        Thread-safe read-only query bounded to the target action.
        """
        if not isinstance(action_id, (ActionId, str)):
            raise ApprovalConsumptionTypeError(
                f"action_id must be an ActionId or str, got {type(action_id).__name__}"
            )
        with self._lock:
            return self._registry.has_consumed_approval_for_action(action_id)

    def get_consumed_records_for_action(
        self, action_id: ActionId | str
    ) -> tuple[ApprovalConsumptionRecord, ...]:
        """Retrieve all consumed approval records for the given action ID.

        Thread-safe read-only query returning an immutable tuple of records.
        """
        if not isinstance(action_id, (ActionId, str)):
            raise ApprovalConsumptionTypeError(
                f"action_id must be an ActionId or str, got {type(action_id).__name__}"
            )
        with self._lock:
            return self._registry.get_consumed_records_for_action(action_id)

    def get_record(self, approval_id: ApprovalId | str) -> ApprovalConsumptionRecord | None:
        """Retrieve the approval consumption/revocation record for an approval ID, if present.

        Thread-safe read-only query bounded to the target approval ID.
        """
        if not isinstance(approval_id, (ApprovalId, str)):
            raise ApprovalConsumptionTypeError(
                f"approval_id must be an ApprovalId or str, got {type(approval_id).__name__}"
            )
        with self._lock:
            return self._registry.get_record(approval_id)

    def consume(
        self,
        grant: ApprovalGrant,
        action: ValidatedActionContract | ActionContract,
        *,
        at: datetime,
        attempt_number: int = 1,
    ) -> ApprovalConsumptionResult:
        """Consume an ApprovalGrant for exactly one mutation attempt.

        Order of Operations:
        1. Model/planner check (fail-closed against planner input).
        2. Timestamp and argument validation.
        3. Cryptographic binding verification (checks match, expiry, not-yet-valid, tampering).
        4. Transaction synchronization: status check, durable persistence, in-memory recording,
           and authorization result creation are serialized under self._lock.
        5. Returns ApprovalConsumptionResult authorizing at most one execution attempt.

        Concurrency & Durability Guarantee:
        - Critical multi-step transaction (check -> durable append -> registry mutation) is
          strictly serialized via process-local self._lock (threading.RLock).
        - Guarantees two concurrent calls for the same approval cannot both append durable evidence.
        - Exactly one winning call returns authorized; the losing call fails closed with
          ApprovalAlreadyUsedError.
        - Strictly process-local: does NOT provide or claim multi-process/distributed atomicity.
        """
        assert_not_planner_for_authority(grant, parameter_name="grant")
        assert_not_planner_for_authority(action, parameter_name="action")

        if not isinstance(grant, ApprovalGrant):
            raise ApprovalConsumptionTypeError(
                f"grant must be an ApprovalGrant instance, got {type(grant).__name__}"
            )
        if not isinstance(at, datetime):
            raise ApprovalConsumptionTypeError(
                f"at must be a datetime instance, got {type(at).__name__}"
            )
        if at.tzinfo is None or at.utcoffset() is None:
            raise ApprovalConsumptionValueError("at must be timezone-aware")
        if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
            raise ApprovalConsumptionTypeError("attempt_number must be an integer")
        if attempt_number < 1:
            raise ApprovalConsumptionValueError("attempt_number must be >= 1")

        norm_at = at if at.tzinfo == UTC else at.astimezone(UTC)

        # 1. Cryptographic binding and validity verification
        verify_approval_binding(action, grant, at=norm_at)

        # Transaction-level lock serializes status check, durable persistence,
        # in-memory registry recording, and authorization creation.
        with self._lock:
            # 2. Check single-use / replay in registry under transaction lock
            if self._registry.is_consumed(grant.approval_id):
                existing_rec = self._registry.get_record(grant.approval_id)
                c_time = existing_rec.consumed_at.isoformat() if existing_rec else "previously"
                att = existing_rec.attempt_number if existing_rec else 1
                msg = (
                    f"Approval '{grant.approval_id}' was already consumed at "
                    f"{c_time} for attempt {att}"
                )
                raise ApprovalAlreadyUsedError(msg)
            if self._registry.is_revoked(grant.approval_id):
                raise ApprovalRevokedError(
                    f"Approval '{grant.approval_id}' has been revoked and cannot be consumed"
                )

            # 3. Durable persistence BEFORE execution (if backed by MissionLedgerPort)
            if self._ledger is not None:
                payload = {
                    "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
                    "approval_id": str(grant.approval_id),
                    "mission_id": str(grant.mission_id),
                    "action_id": str(grant.action_id),
                    "binding_hash": grant.binding_hash.value,
                    "consumed_at": norm_at.isoformat(),
                    "consumed_for_attempt": attempt_number,
                }
                ev_record = EvidenceRecord.create(
                    action_id=grant.action_id,
                    mission_id=grant.mission_id,
                    origin=EvidenceOrigin(
                        provenance=EvidenceProvenance.LOCAL_EXECUTION,
                        observed_at=norm_at,
                    ),
                    payload=payload,
                    created_at=norm_at,
                )
                persistence_failed = False
                try:
                    self._ledger.append_evidence(ev_record)
                except Exception:
                    persistence_failed = True

                if persistence_failed:
                    raise ApprovalConsumptionPersistenceError(
                        "Failed to durably persist approval consumption"
                    ) from None

            # 4. In-memory registry recording
            self._registry.record_consumption(
                grant,
                at=norm_at,
                attempt_number=attempt_number,
            )

            # 5. Return typed consumption result (strictly zero execution / verification claim)
            return ApprovalConsumptionResult(
                approval_id=grant.approval_id,
                consumed_at=norm_at,
                attempt_number=attempt_number,
                is_authorized=True,
                execution_outcome=None,
                is_verified=False,
                is_ready=False,
            )

    def revoke(
        self,
        grant: ApprovalGrant | ApprovalId,
        *,
        at: datetime,
        reason: str | None = None,
    ) -> None:
        """Revoke an ApprovalGrant so it can never authorize execution.

        Thread Safety & Concurrency:
        - Critical multi-step transaction (lineage check -> durable append -> memory record)
          is synchronized via self._lock.
        - Prevents concurrent consume/revoke races from generating invalid closed-world histories.
        """
        assert_not_planner_for_authority(grant, parameter_name="grant")
        if not isinstance(at, datetime):
            raise ApprovalConsumptionTypeError("at must be a datetime instance")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ApprovalConsumptionValueError("at must be timezone-aware")

        norm_at = at if at.tzinfo == UTC else at.astimezone(UTC)

        with self._lock:
            if isinstance(grant, ApprovalGrant):
                aid = grant.approval_id
                mid = grant.mission_id
                act_id = grant.action_id
                b_hash = grant.binding_hash
            elif isinstance(grant, ApprovalId):
                aid = grant
                existing_rec = self._registry.get_record(str(aid))
                if existing_rec is not None:
                    mid = existing_rec.mission_id
                    act_id = existing_rec.action_id
                    b_hash = existing_rec.binding_hash
                else:
                    raise ApprovalConsumptionValueError(
                        f"Cannot revoke approval '{aid}': canonical lineage "
                        "(mission_id, action_id, binding_hash) is unknown and cannot be resolved"
                    )
            else:
                raise ApprovalConsumptionTypeError("grant must be ApprovalGrant or ApprovalId")

            # Check if already revoked: idempotent duplicate revocation under transaction lock
            if self._registry.is_revoked(aid):
                return

            # 1. Record in durable ledger first (if configured)
            if self._ledger is not None:
                payload = {
                    "evidence_type": APPROVAL_REVOCATION_EVIDENCE_TYPE,
                    "approval_id": str(aid),
                    "mission_id": str(mid),
                    "action_id": str(act_id),
                    "binding_hash": b_hash.value,
                    "consumed_at": norm_at.isoformat(),
                    "consumed_for_attempt": 1,
                    "reason": redact_text(reason) if reason is not None else None,
                }
                ev_record = EvidenceRecord.create(
                    action_id=act_id,
                    mission_id=mid,
                    origin=EvidenceOrigin(
                        provenance=EvidenceProvenance.LOCAL_EXECUTION,
                        observed_at=norm_at,
                    ),
                    payload=payload,
                    created_at=norm_at,
                )
                persistence_failed = False
                try:
                    self._ledger.append_evidence(ev_record)
                except Exception:
                    persistence_failed = True

                if persistence_failed:
                    raise ApprovalRevocationPersistenceError(
                        "Failed to durably persist approval revocation"
                    ) from None

            # 2. Record in memory registry only after durable append succeeds
            self._registry.revoke(
                aid,
                at=norm_at,
                mission_id=mid,
                action_id=act_id,
                binding_hash=b_hash,
                reason=reason,
            )


# ===========================================================================
# Standalone Functions
# ===========================================================================


def consume_approval(
    grant: ApprovalGrant,
    action: ValidatedActionContract | ActionContract,
    *,
    at: datetime,
    attempt_number: int = 1,
    ledger: ApprovalLedger | MissionLedgerPort | None = None,
    registry: UsedApprovalRegistry | None = None,
) -> ApprovalConsumptionResult:
    """Consume an ApprovalGrant for exactly one mutation attempt.

    Fails closed if:
    - approval has expired or is not yet valid;
    - action, target, parameters, or authority class do not match;
    - binding hash was tampered with;
    - approval has already been consumed or revoked;
    - planner/model attempts to manufacture approval usage.

    Args:
        grant: The bound ApprovalGrant.
        action: The candidate action to execute.
        at: Explicit timezone-aware evaluation datetime.
        attempt_number: Sequential attempt count (>= 1).
        ledger: Optional ApprovalLedger or MissionLedgerPort.
        registry: Optional UsedApprovalRegistry.

    Returns:
        ApprovalConsumptionResult authorizing execution.
    """
    assert_not_planner_for_authority(grant, parameter_name="grant")
    assert_not_planner_for_authority(action, parameter_name="action")

    if isinstance(ledger, ApprovalLedger):
        active_ledger = ledger
    elif isinstance(ledger, MissionLedgerPort):
        active_ledger = ApprovalLedger(ledger=ledger, registry=registry)
    else:
        active_ledger = ApprovalLedger(registry=registry or used_approval_registry)

    return active_ledger.consume(
        grant=grant,
        action=action,
        at=at,
        attempt_number=attempt_number,
    )


def revoke_approval(
    grant: ApprovalGrant | ApprovalId,
    *,
    at: datetime,
    reason: str | None = None,
    ledger: ApprovalLedger | MissionLedgerPort | None = None,
    registry: UsedApprovalRegistry | None = None,
) -> None:
    """Revoke an ApprovalGrant so it can never be consumed."""
    assert_not_planner_for_authority(grant, parameter_name="grant")

    if isinstance(ledger, ApprovalLedger):
        active_ledger = ledger
    elif isinstance(ledger, MissionLedgerPort):
        active_ledger = ApprovalLedger(ledger=ledger, registry=registry)
    else:
        active_ledger = ApprovalLedger(registry=registry or used_approval_registry)

    active_ledger.revoke(grant, at=at, reason=reason)


__all__ = [
    "APPROVAL_CONSUMPTION_EVIDENCE_TYPE",
    "APPROVAL_REVOCATION_EVIDENCE_TYPE",
    "ApprovalAlreadyUsedError",
    "ApprovalConsumptionError",
    "ApprovalConsumptionPersistenceError",
    "ApprovalConsumptionRecord",
    "ApprovalConsumptionResult",
    "ApprovalConsumptionTypeError",
    "ApprovalConsumptionValueError",
    "ApprovalLedger",
    "ApprovalPersistenceError",
    "ApprovalRevocationPersistenceError",
    "ApprovalRevokedError",
    "ApprovalUsageStatus",
    "MalformedApprovalStateError",
    "UnknownApprovalIdError",
    "UsedApprovalRegistry",
    "consume_approval",
    "revoke_approval",
    "used_approval_registry",
]
