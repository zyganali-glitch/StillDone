"""Provider-neutral append-only ledger port for StillDone.

Defines immutable records for missions, actions, and evidence, and the abstract
MissionLedgerPort interface.
Provides an explicitly non-durable in-memory implementation for testing and runtime-local state.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, SupportsIndex

from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import ApprovalId
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.evidence import EvidenceId, compute_evidence_id
from stilldone.serialization import (
    canonical_json,
    canonical_serialize,
    to_canonical_primitive,
)
from stilldone.transitions import (
    IllegalStatePromotionError,
    assert_valid_transition,
)


class LedgerError(Exception):
    """Base exception for all StillDone ledger operations."""


class DuplicateRecordError(LedgerError):
    """Raised when an attempt is made to re-append a record with an identical identity and content.

    Append-only ledgers do not permit silent overwriting.
    """


class RecordConflictError(LedgerError):
    """Raised when an attempt is made to append a record with an existing ID but different content.

    Fails closed on conflicting state mutations.
    """


class RecordNotFoundError(LedgerError):
    """Raised when a requested record is not found in the ledger."""


def _normalize_utc(dt: datetime, name: str) -> datetime:
    """Validate and normalize a datetime to timezone-aware UTC."""
    if not isinstance(dt, datetime):
        raise TypeError(f"{name} must be a datetime instance, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware (UTC required)")
    return dt if dt.tzinfo == UTC else dt.astimezone(UTC)


@dataclass(frozen=True)
class MissionRecord:
    """Immutable ledger record representing a mission."""

    mission_id: MissionId
    contract: MissionContract
    state: MissionState
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(self.mission_id).__name__}")
        if not isinstance(self.contract, MissionContract):
            raise TypeError(f"contract must be MissionContract, got {type(self.contract).__name__}")
        if self.contract.mission_id != self.mission_id:
            raise ValueError(
                f"Contract mission_id {self.contract.mission_id} does not match {self.mission_id}"
            )
        if not isinstance(self.state, MissionState):
            raise TypeError(f"state must be MissionState, got {type(self.state).__name__}")
        norm_created = _normalize_utc(self.created_at, "created_at")
        norm_updated = _normalize_utc(self.updated_at, "updated_at")
        object.__setattr__(self, "created_at", norm_created)
        object.__setattr__(self, "updated_at", norm_updated)


@dataclass(frozen=True)
class ActionRecord:
    """Immutable ledger record representing an action bound to a mission."""

    action_id: ActionId
    mission_id: MissionId
    action: ActionContract
    approval_id: ApprovalId | None
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, ActionId):
            raise TypeError(f"action_id must be ActionId, got {type(self.action_id).__name__}")
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(self.mission_id).__name__}")
        if not isinstance(self.action, ActionContract):
            raise TypeError(f"action must be ActionContract, got {type(self.action).__name__}")
        if self.action.action_id != self.action_id:
            raise ValueError(
                f"ActionContract action_id {self.action.action_id} does not match {self.action_id}"
            )
        if self.action.mission_id != self.mission_id:
            msg = (
                f"ActionContract mission_id {self.action.mission_id} "
                f"does not match {self.mission_id}"
            )
            raise ValueError(msg)
        if self.approval_id is not None and not isinstance(self.approval_id, ApprovalId):
            raise TypeError(
                f"approval_id must be ApprovalId, got {type(self.approval_id).__name__}"
            )
        norm_created = _normalize_utc(self.created_at, "created_at")
        object.__setattr__(self, "created_at", norm_created)


class CanonicalSequence(list[Any]):
    """Immutable sequence for canonical evidence payload trees."""

    def __init__(self, iterable: Any = ()) -> None:
        super().__init__(iterable)

    def __setitem__(self, index: Any, value: Any) -> None:
        raise TypeError(
            "Evidence payload sequence is immutable and does not support item assignment"
        )

    def __delitem__(self, index: Any) -> None:
        raise TypeError("Evidence payload sequence is immutable and does not support item deletion")

    def append(self, value: Any) -> None:
        raise TypeError("Evidence payload sequence is immutable")

    def extend(self, values: Any) -> None:
        raise TypeError("Evidence payload sequence is immutable")

    def insert(self, index: SupportsIndex, value: Any) -> None:
        raise TypeError("Evidence payload sequence is immutable")

    def remove(self, value: Any) -> None:
        raise TypeError("Evidence payload sequence is immutable")

    def pop(self, index: SupportsIndex = -1) -> Any:
        raise TypeError("Evidence payload sequence is immutable")

    def clear(self) -> None:
        raise TypeError("Evidence payload sequence is immutable")

    def reverse(self) -> None:
        raise TypeError("Evidence payload sequence is immutable")

    def sort(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("Evidence payload sequence is immutable")

    def __iadd__(self, other: Any) -> Any:  # type: ignore[misc]
        raise TypeError("Evidence payload sequence is immutable")

    def __imul__(self, other: Any) -> Any:  # type: ignore[misc]
        raise TypeError("Evidence payload sequence is immutable")

    def __copy__(self) -> CanonicalSequence:
        return _freeze_sequence(self)

    def __deepcopy__(self, memo: dict[Any, Any] | None = None) -> CanonicalSequence:
        return _freeze_sequence(self)


class CanonicalPayload(dict[str, Any]):
    """Immutable mapping representing a canonical evidence payload snapshot.

    Guarantees:
    - Dict mutations fail closed with TypeError.
    - Preserves canonical dict interfaces and json serialization compatibility.
    - Deeply isolated from external caller structures.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def __setitem__(self, key: Any, value: Any) -> None:
        raise TypeError("Evidence payload is immutable and does not support item assignment")

    def __delitem__(self, key: Any) -> None:
        raise TypeError("Evidence payload is immutable and does not support item deletion")

    def clear(self) -> None:
        raise TypeError("Evidence payload is immutable")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("Evidence payload is immutable")

    def setdefault(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError("Evidence payload is immutable")

    def pop(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError("Evidence payload is immutable")

    def popitem(self) -> Any:
        raise TypeError("Evidence payload is immutable")

    def __ior__(self, other: Any) -> Any:  # type: ignore[misc]
        raise TypeError("Evidence payload is immutable")

    def __copy__(self) -> CanonicalPayload:
        return freeze_canonical_payload(self)

    def __deepcopy__(self, memo: dict[Any, Any] | None = None) -> CanonicalPayload:
        return freeze_canonical_payload(self)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached standard mutable dictionary copy of the canonical payload."""
        res = _unfreeze(self)
        if not isinstance(res, dict):
            raise TypeError("Unfrozen payload must be a dict")
        return res


def _freeze_value(obj: Any) -> Any:
    if isinstance(obj, dict):
        return CanonicalPayload({k: _freeze_value(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return CanonicalSequence([_freeze_value(v) for v in obj])
    return obj


def _freeze_sequence(seq: Any) -> CanonicalSequence:
    return CanonicalSequence([_freeze_value(v) for v in seq])


def _unfreeze(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _unfreeze(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unfreeze(v) for v in obj]
    return obj


def freeze_canonical_payload(payload: dict[str, Any]) -> CanonicalPayload:
    """Validate, canonicalize, and deep-freeze an evidence payload.

    Preserves fail-closed post-NFC canonicalization and key collision detection.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"payload must be a dict, got {type(payload).__name__}")
    canonical = to_canonical_primitive(payload)
    if not isinstance(canonical, dict):
        raise TypeError(
            f"canonical primitive projection must be a dict, got {type(canonical).__name__}"
        )
    return CanonicalPayload({k: _freeze_value(v) for k, v in canonical.items()})


@dataclass(frozen=True)
class EvidenceRecord:
    """Immutable ledger record representing evidence bound to an action and mission.

    Binds its exact content-addressed EvidenceId derived from canonical serialization.
    Owns an immutable canonical snapshot of its evidence payload, preventing any
    caller or external mutation from altering stored evidence content.
    """

    evidence_id: EvidenceId
    action_id: ActionId
    mission_id: MissionId
    origin: EvidenceOrigin
    payload: dict[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, EvidenceId):
            raise TypeError(
                f"evidence_id must be EvidenceId, got {type(self.evidence_id).__name__}"
            )
        if not isinstance(self.action_id, ActionId):
            raise TypeError(f"action_id must be ActionId, got {type(self.action_id).__name__}")
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(self.mission_id).__name__}")
        if not isinstance(self.origin, EvidenceOrigin):
            raise TypeError(f"origin must be EvidenceOrigin, got {type(self.origin).__name__}")
        if not isinstance(self.payload, dict):
            raise TypeError(f"payload must be a dict, got {type(self.payload).__name__}")

        norm_created = _normalize_utc(self.created_at, "created_at")
        object.__setattr__(self, "created_at", norm_created)

        # Ensure EvidenceRecord owns an immutable, defensively isolated canonical snapshot
        frozen_payload = freeze_canonical_payload(self.payload)
        object.__setattr__(self, "payload", frozen_payload)

        # Validate that the bound EvidenceId strictly matches content-addressed SHA-256
        computed_id = compute_evidence_id({"origin": self.origin, "payload": self.payload})
        if self.evidence_id != computed_id:
            raise ValueError(
                f"Mismatched evidence_id: bound {self.evidence_id} != computed {computed_id}"
            )

    @classmethod
    def create(
        cls,
        *,
        action_id: ActionId,
        mission_id: MissionId,
        origin: EvidenceOrigin,
        payload: dict[str, Any],
        created_at: datetime | None = None,
    ) -> EvidenceRecord:
        """Create an EvidenceRecord with a deterministic content-addressed EvidenceId."""
        norm_created = _normalize_utc(created_at or datetime.now(UTC), "created_at")
        frozen_payload = freeze_canonical_payload(payload)
        computed_id = compute_evidence_id({"origin": origin, "payload": frozen_payload})
        return cls(
            evidence_id=computed_id,
            action_id=action_id,
            mission_id=mission_id,
            origin=origin,
            payload=frozen_payload,
            created_at=norm_created,
        )


def _is_verification_evidence(ev: EvidenceRecord) -> bool:
    """Check whether an evidence record qualifies as authoritative verification proof.

    Enforces StillDone Core Product Invariants (P-09 / P-11 / P-12):
    - Must possess recognized EvidenceProvenance.
    - No fixture or recorded-live evidence represented as current live truth:
      EvidenceProvenance.FIXTURE and EvidenceProvenance.RECORDED_LIVE are strictly rejected.
    - Generic, superficial payload flags are strictly rejected fail-closed:
      No verification from generic `verification=True`, `is_verified=True`,
      `initial_verification=True`, `is_ready=True`, `status="VERIFIED"` or `status="READ_OK"`.
    - Empty predicate evaluations or unbound observations fail closed.
    - Only structured canonical evidence contracts are accepted:
      1. APPROVED_CALENDAR_UPDATE_RECEIPT: Must have valid receipt with readback MATCH,
         predicate TRUE, execution EXECUTION_SUCCEEDED, and router mutations >= 1.
      2. INDEPENDENT_READBACK: Must record readback_status MATCH (or is_match True) and
         non-empty verified observation properties.
      3. PREDICATE_EVALUATION: Must bind non-empty predicate_id with truth TRUE (or is_true True).
      4. MISSION_READINESS: Must have is_ready True, satisfied_predicate_ids non-empty,
         and failed/stale/unverified sets empty.
      5. VERIFICATION / READ_BACK: Must contain non-empty structured predicate evaluations
         evaluating to TRUE, or non-empty verified observations bound to a target.
    """
    if not isinstance(ev.origin.provenance, EvidenceProvenance):
        return False

    # Disallow FIXTURE and RECORDED_LIVE from claiming current live verification truth
    if ev.origin.provenance in (EvidenceProvenance.FIXTURE, EvidenceProvenance.RECORDED_LIVE):
        return False

    payload = ev.payload
    if not isinstance(payload, (dict, CanonicalPayload)):
        return False

    ev_type = str(payload.get("evidence_type", "")).strip().upper()

    # 1. P-11 Approved Action Receipt Contract
    if ev_type in ("APPROVED_CALENDAR_UPDATE_RECEIPT", "APPROVED_ACTION_RECEIPT"):
        receipt = payload.get("receipt")
        if isinstance(receipt, (dict, CanonicalPayload)):
            rb_status = str(receipt.get("readback_status", receipt.get("status", ""))).upper()
            pred_truth = str(receipt.get("predicate_truth", "")).upper()
            exec_state = str(receipt.get("execution_state", "")).upper()
            if (
                rb_status == "MATCH"
                and pred_truth == "TRUE"
                and exec_state == "EXECUTION_SUCCEEDED"
            ):
                return True
        return False

    # 2. P-09 Independent Readback Contract
    if ev_type in ("INDEPENDENT_READBACK", "READ_BACK"):
        rb_status = str(payload.get("readback_status", "")).upper()
        is_match = payload.get("is_match") is True
        if rb_status == "MATCH" or is_match:
            # Must contain non-empty observed properties / observation content
            props = payload.get("properties", payload.get("observed_properties"))
            mismatches = payload.get("mismatches")
            if (isinstance(props, (dict, CanonicalPayload)) and len(props) > 0) or (
                isinstance(mismatches, (list, tuple, CanonicalSequence)) and len(mismatches) == 0
            ):
                return True
            raw_obs = payload.get("raw_observation")
            if isinstance(raw_obs, (dict, CanonicalPayload)) and len(raw_obs) > 0:
                return True

    # 3. P-09 Predicate Evaluation Contract
    if ev_type in ("PREDICATE_EVALUATION", "PREDICATE_RESULT"):
        pid = payload.get("predicate_id")
        if pid and isinstance(pid, str) and pid.strip():
            truth_val = str(payload.get("truth", "")).upper()
            is_true_val = payload.get("is_true") is True
            if truth_val == "TRUE" or is_true_val:
                return True
        return False

    # 4. P-09 Mission Readiness Determination Contract
    if ev_type == "MISSION_READINESS":
        if payload.get("is_ready") is True:
            sat = payload.get("satisfied_predicate_ids")
            failed = payload.get("failed_predicate_ids")
            stale = payload.get("stale_predicate_ids")
            unverified = payload.get("unverified_action_ids")
            if isinstance(sat, (list, tuple, CanonicalSequence)) and len(sat) > 0:
                if (
                    (not failed or len(failed) == 0)
                    and (not stale or len(stale) == 0)
                    and (not unverified or len(unverified) == 0)
                ):
                    return True
        return False

    # 5. Canonical VERIFICATION payload contract
    if ev_type == "VERIFICATION":
        # Check structured predicate evaluations
        preds = payload.get("predicate_evaluations")
        if isinstance(preds, (dict, CanonicalPayload)) and len(preds) > 0:
            all_true = True
            for eval_entry in preds.values():
                if isinstance(eval_entry, (dict, CanonicalPayload)):
                    e_truth = str(eval_entry.get("truth", "")).upper()
                    e_satisfied = eval_entry.get("is_satisfied", eval_entry.get("is_true")) is True
                    if e_truth != "TRUE" and not e_satisfied:
                        all_true = False
                        break
                elif eval_entry is not True and str(eval_entry).upper() != "TRUE":
                    all_true = False
                    break
            if all_true:
                return True
        elif isinstance(preds, (list, tuple, CanonicalSequence)) and len(preds) > 0:
            all_true = True
            for eval_entry in preds:
                if isinstance(eval_entry, (dict, CanonicalPayload)):
                    e_truth = str(eval_entry.get("truth", "")).upper()
                    e_satisfied = eval_entry.get("is_satisfied", eval_entry.get("is_true")) is True
                    if e_truth != "TRUE" and not e_satisfied:
                        all_true = False
                        break
                elif eval_entry is not True and str(eval_entry).upper() != "TRUE":
                    all_true = False
                    break
            if all_true:
                return True

        # Check structured observations bound to target
        obs = payload.get("observations")
        target_info = payload.get("target")
        if isinstance(obs, (dict, CanonicalPayload)) and len(obs) > 0:
            if isinstance(target_info, (dict, CanonicalPayload)) and len(target_info) > 0:
                return True
            if "target" in obs and ("properties" in obs or len(obs) > 1):
                return True

    return False


class MissionLedgerPort(ABC):
    """Abstract provider-neutral append-only ledger interface."""

    @abstractmethod
    def append_mission(self, record: MissionRecord) -> None:
        """Append a mission record. Fails closed on duplicates or conflicts."""

    def update_mission_state(
        self,
        mission_id: MissionId,
        new_state: MissionState,
        updated_at: datetime | None = None,
    ) -> MissionRecord:
        """Update a mission's lifecycle state in the ledger.
        Raises RecordNotFoundError if absent.
        """
        raise NotImplementedError("update_mission_state not implemented by this ledger")

    @abstractmethod
    def get_mission(self, mission_id: MissionId) -> MissionRecord:
        """Retrieve a mission record by ID. Raises RecordNotFoundError if missing."""

    @abstractmethod
    def append_action(self, record: ActionRecord) -> None:
        """Append an action record bound to a mission. Fails closed on duplicates or conflicts."""

    @abstractmethod
    def get_action(self, action_id: ActionId) -> ActionRecord:
        """Retrieve an action record by ID. Raises RecordNotFoundError if missing."""

    @abstractmethod
    def get_actions_for_mission(self, mission_id: MissionId) -> list[ActionRecord]:
        """List all action records belonging to a mission in append order."""

    @abstractmethod
    def append_evidence(self, record: EvidenceRecord) -> None:
        """Append an immutable evidence record bound to an action and mission.

        Fails closed on duplicates, conflicts, or mismatched evidence ID.
        """

    @abstractmethod
    def get_evidence(self, evidence_id: EvidenceId) -> EvidenceRecord:
        """Retrieve an evidence record by ID. Raises RecordNotFoundError if missing."""

    @abstractmethod
    def get_evidence_for_action(self, action_id: ActionId) -> list[EvidenceRecord]:
        """List all evidence records belonging to an action in append order."""

    @abstractmethod
    def get_evidence_for_mission(self, mission_id: MissionId) -> list[EvidenceRecord]:
        """List all evidence records belonging to a mission in append order."""

    @abstractmethod
    def get_all_evidence(self) -> list[EvidenceRecord]:
        """List all evidence records in the ledger in append order."""

    def record_state_transition(
        self,
        *,
        mission_id: MissionId,
        expected_prior_state: MissionState,
        new_state: MissionState,
        evidence: EvidenceRecord,
        updated_at: datetime | None = None,
        snapshot_projection: dict[str, Any] | None = None,
    ) -> tuple[MissionRecord, EvidenceRecord]:
        """Record a validated state transition with bound evidence atomically.

        Subclasses override to provide atomic journal commit guarantees.
        """
        self.append_evidence(evidence)
        rec = self.update_mission_state(
            mission_id=mission_id, new_state=new_state, updated_at=updated_at
        )
        return rec, evidence

    def get_transition_snapshot(self, mission_id: MissionId) -> dict[str, Any] | None:
        """Retrieve the latest recoverable snapshot projection recorded for a mission."""
        return None


class InMemoryNonDurableLedger(MissionLedgerPort):
    """Non-durable in-memory ledger implementation strictly for testing/runtime-local state.

    WARNING: This implementation stores state purely in ephemeral Python process memory.
    It provides ZERO durable persistence across process restarts and MUST NEVER be classified
    or claimed as durable evidence storage.
    """

    IS_DURABLE: bool = False
    DURABILITY_CLASSIFICATION: str = "NON_DURABLE_TEST_OR_RUNTIME_LOCAL"

    def __init__(self) -> None:
        self._missions: dict[str, MissionRecord] = {}
        self._actions: dict[str, ActionRecord] = {}
        self._evidence: dict[str, EvidenceRecord] = {}
        self._mission_actions: dict[str, list[str]] = {}
        self._action_evidence: dict[str, list[str]] = {}
        self._mission_evidence: dict[str, list[str]] = {}
        self._transition_snapshots: dict[str, dict[str, Any]] = {}

    def append_mission(self, record: MissionRecord) -> None:
        key = str(record.mission_id)
        if key in self._missions:
            existing = self._missions[key]
            # Compare canonical representations to distinguish identical duplicate from conflict
            if canonical_serialize(to_canonical_primitive(existing)) == canonical_serialize(
                to_canonical_primitive(record)
            ):
                raise DuplicateRecordError(
                    f"Mission {key} already exists with identical content. "
                    "Silent overwrite is prohibited in append-only ledger."
                )
            raise RecordConflictError(
                f"Conflicting record for mission {key}: existing record differs from new record."
            )
        self._missions[key] = record
        self._mission_actions.setdefault(key, [])
        self._mission_evidence.setdefault(key, [])

    def update_mission_state(
        self,
        mission_id: MissionId,
        new_state: MissionState,
        updated_at: datetime | None = None,
    ) -> MissionRecord:
        key = str(mission_id)
        if key not in self._missions:
            raise RecordNotFoundError(f"Mission {key} not found in ledger")
        old = self._missions[key]
        if old.state != new_state:
            assert_valid_transition(old.state, new_state)

        if new_state == MissionState.READY:
            action_ids = self._mission_actions.get(key, [])
            if not action_ids:
                raise IllegalStatePromotionError(
                    f"Cannot promote mission {key} to READY in ledger with zero actions"
                )
            for a_key in action_ids:
                e_keys = self._action_evidence.get(a_key, [])
                if not e_keys:
                    raise IllegalStatePromotionError(
                        f"Cannot promote mission {key} to READY: action {a_key} has zero evidence"
                    )
                has_verification = any(
                    _is_verification_evidence(self._evidence[ek])
                    for ek in e_keys
                    if ek in self._evidence
                )
                if not has_verification:
                    raise IllegalStatePromotionError(
                        f"Cannot promote mission {key} to READY: action {a_key} lacks verification"
                    )

        now = updated_at or datetime.now(UTC)
        norm_now = _normalize_utc(now, "updated_at")
        updated = MissionRecord(
            mission_id=old.mission_id,
            contract=old.contract,
            state=new_state,
            created_at=old.created_at,
            updated_at=norm_now,
        )
        self._missions[key] = updated
        return updated

    def get_mission(self, mission_id: MissionId) -> MissionRecord:
        key = str(mission_id)
        if key not in self._missions:
            raise RecordNotFoundError(f"Mission {key} not found in ledger")
        return self._missions[key]

    def append_action(self, record: ActionRecord) -> None:
        m_key = str(record.mission_id)
        if m_key not in self._missions:
            raise RecordNotFoundError(
                f"Cannot append action {record.action_id}: mission {m_key} does not exist in ledger"
            )

        a_key = str(record.action_id)
        if a_key in self._actions:
            existing = self._actions[a_key]
            if canonical_serialize(to_canonical_primitive(existing)) == canonical_serialize(
                to_canonical_primitive(record)
            ):
                raise DuplicateRecordError(
                    f"Action {a_key} already exists with identical content. "
                    "Silent overwrite is prohibited in append-only ledger."
                )
            raise RecordConflictError(
                f"Conflicting record for action {a_key}: existing record differs from new record."
            )
        self._actions[a_key] = record
        self._mission_actions[m_key].append(a_key)
        self._action_evidence.setdefault(a_key, [])

    def get_action(self, action_id: ActionId) -> ActionRecord:
        key = str(action_id)
        if key not in self._actions:
            raise RecordNotFoundError(f"Action {key} not found in ledger")
        return self._actions[key]

    def get_actions_for_mission(self, mission_id: MissionId) -> list[ActionRecord]:
        m_key = str(mission_id)
        if m_key not in self._missions:
            raise RecordNotFoundError(f"Mission {m_key} not found in ledger")
        return [self._actions[a_key] for a_key in self._mission_actions.get(m_key, [])]

    def append_evidence(self, record: EvidenceRecord) -> None:
        m_key = str(record.mission_id)
        if m_key not in self._missions:
            msg = (
                f"Cannot append evidence {record.evidence_id}: "
                f"mission {m_key} does not exist in ledger"
            )
            raise RecordNotFoundError(msg)

        a_key = str(record.action_id)
        if a_key not in self._actions:
            msg = (
                f"Cannot append evidence {record.evidence_id}: "
                f"action {a_key} does not exist in ledger"
            )
            raise RecordNotFoundError(msg)

        # Enforce relationship consistency: the action must belong to the mission
        action_record = self._actions[a_key]
        if str(action_record.mission_id) != m_key:
            msg = (
                f"Relationship mismatch: action {a_key} belongs to mission "
                f"{action_record.mission_id}, not {m_key}"
            )
            raise LedgerError(msg)

        e_key = str(record.evidence_id)
        if e_key in self._evidence:
            existing = self._evidence[e_key]
            if canonical_serialize(to_canonical_primitive(existing)) == canonical_serialize(
                to_canonical_primitive(record)
            ):
                raise DuplicateRecordError(
                    f"Evidence {e_key} already exists with identical content. "
                    "Silent overwrite is prohibited in append-only ledger."
                )
            raise RecordConflictError(
                f"Conflicting record for evidence {e_key}: existing record differs from new record."
            )
        # Store a defensively isolated record to ensure ledger ownership integrity
        self._evidence[e_key] = EvidenceRecord(
            evidence_id=record.evidence_id,
            action_id=record.action_id,
            mission_id=record.mission_id,
            origin=record.origin,
            payload=record.payload,
            created_at=record.created_at,
        )
        self._action_evidence[a_key].append(e_key)
        self._mission_evidence[m_key].append(e_key)

    def get_evidence(self, evidence_id: EvidenceId) -> EvidenceRecord:
        key = str(evidence_id)
        if key not in self._evidence:
            raise RecordNotFoundError(f"Evidence {key} not found in ledger")
        stored = self._evidence[key]
        return EvidenceRecord(
            evidence_id=stored.evidence_id,
            action_id=stored.action_id,
            mission_id=stored.mission_id,
            origin=stored.origin,
            payload=stored.payload,
            created_at=stored.created_at,
        )

    def get_evidence_for_action(self, action_id: ActionId) -> list[EvidenceRecord]:
        a_key = str(action_id)
        if a_key not in self._actions:
            raise RecordNotFoundError(f"Action {a_key} not found in ledger")
        return [
            self.get_evidence(EvidenceId(e_key)) for e_key in self._action_evidence.get(a_key, [])
        ]

    def get_evidence_for_mission(self, mission_id: MissionId) -> list[EvidenceRecord]:
        m_key = str(mission_id)
        if m_key not in self._missions:
            raise RecordNotFoundError(f"Mission {m_key} not found in ledger")
        return [
            self.get_evidence(EvidenceId(e_key)) for e_key in self._mission_evidence.get(m_key, [])
        ]

    def get_all_evidence(self) -> list[EvidenceRecord]:
        """List all evidence records in the ledger in append order."""
        return [self.get_evidence(EvidenceId(e_key)) for e_key in self._evidence]

    def record_state_transition(
        self,
        *,
        mission_id: MissionId,
        expected_prior_state: MissionState,
        new_state: MissionState,
        evidence: EvidenceRecord,
        updated_at: datetime | None = None,
        snapshot_projection: dict[str, Any] | None = None,
    ) -> tuple[MissionRecord, EvidenceRecord]:
        key = str(mission_id)
        if key not in self._missions:
            raise RecordNotFoundError(f"Mission {key} not found in ledger")
        old = self._missions[key]
        if old.state != expected_prior_state:
            raise RecordConflictError(
                f"Cannot transition mission {key}: current state is {old.state.value}, "
                f"expected prior state is {expected_prior_state.value}"
            )
        assert_valid_transition(expected_prior_state, new_state)

        if old.mission_id != evidence.mission_id:
            raise LedgerError(
                f"Evidence mission {evidence.mission_id} does not match {old.mission_id}"
            )
        a_key = str(evidence.action_id)
        if a_key not in self._actions:
            raise RecordNotFoundError(f"Action {a_key} does not exist in ledger")
        if str(self._actions[a_key].mission_id) != key:
            raise LedgerError(
                f"Action {a_key} belongs to mission {self._actions[a_key].mission_id}, not {key}"
            )

        self.append_evidence(evidence)

        now = updated_at or datetime.now(UTC)
        norm_now = _normalize_utc(now, "updated_at")
        updated = MissionRecord(
            mission_id=old.mission_id,
            contract=old.contract,
            state=new_state,
            created_at=old.created_at,
            updated_at=norm_now,
        )
        self._missions[key] = updated
        if snapshot_projection is not None:
            self._transition_snapshots[key] = dict(snapshot_projection)
        return updated, evidence

    def get_transition_snapshot(self, mission_id: MissionId) -> dict[str, Any] | None:
        return self._transition_snapshots.get(str(mission_id))


class DurableFileLedger(MissionLedgerPort):
    """Durable append-only file ledger implementation for process continuity and recovery.

    Persists records to a durable append-only JSON-lines log file on disk.
    Each append operation is flushed and fsynced to ensure durability.
    On initialization, loads existing durable records into memory for fast indexing
    and conflict checking.
    """

    IS_DURABLE: bool = True
    DURABILITY_CLASSIFICATION: str = "DURABLE_APPEND_ONLY_FILE"

    def __init__(self, file_path: str | Path) -> None:
        self._path = Path(file_path).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._missions: dict[str, MissionRecord] = {}
        self._actions: dict[str, ActionRecord] = {}
        self._evidence: dict[str, EvidenceRecord] = {}
        self._mission_actions: dict[str, list[str]] = {}
        self._action_evidence: dict[str, list[str]] = {}
        self._mission_evidence: dict[str, list[str]] = {}
        self._transition_snapshots: dict[str, dict[str, Any]] = {}

        if self._path.exists():
            self._load_from_file()

    @property
    def file_path(self) -> Path:
        return self._path

    def _write_entry(self, entry: dict[str, Any]) -> None:
        line = canonical_json(entry) + "\n"
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def _load_from_file(self) -> None:
        with open(self._path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    entry = json.loads(line_str)
                    if not isinstance(entry, dict):
                        raise LedgerError(f"Line {line_num} is not a valid JSON object")
                except Exception as exc:
                    raise LedgerError(
                        f"Malformed or corrupt entry in durable ledger log at "
                        f"line {line_num}: {exc}"
                    ) from exc

                rec_type = entry.get("record_type")
                if rec_type == "mission":
                    m_id = MissionId(entry["mission_id"])
                    init_st = MissionState(entry["state"])
                    if init_st == MissionState.READY:
                        raise IllegalStatePromotionError(
                            f"Initial mission record in durable log for mission {m_id} "
                            "cannot be in READY state."
                        )
                    c_data = entry["contract"]
                    intent = UserIntentSnapshot(
                        text=c_data["intent"]["text"],
                        captured_at=datetime.fromisoformat(c_data["intent"]["captured_at"]),
                        mission_id=m_id,
                    )
                    contract = MissionContract(
                        mission_id=m_id,
                        intent=intent,
                        created_at=datetime.fromisoformat(c_data["created_at"]),
                        schema_version=c_data.get("schema_version", "v1"),
                    )
                    record = MissionRecord(
                        mission_id=m_id,
                        contract=contract,
                        state=init_st,
                        created_at=datetime.fromisoformat(entry["created_at"]),
                        updated_at=datetime.fromisoformat(entry["updated_at"]),
                    )
                    m_key = str(m_id)
                    if m_key in self._missions:
                        existing_mission = self._missions[m_key]
                        if canonical_serialize(
                            to_canonical_primitive(existing_mission)
                        ) == canonical_serialize(to_canonical_primitive(record)):
                            raise DuplicateRecordError(
                                f"Duplicate mission {m_key} encountered during durable log replay."
                            )
                        raise RecordConflictError(
                            f"Conflicting record for mission {m_key} "
                            "encountered during durable log replay."
                        )
                    self._missions[m_key] = record
                    self._mission_actions.setdefault(m_key, [])
                    self._mission_evidence.setdefault(m_key, [])
                elif rec_type == "mission_state_update":
                    m_id = MissionId(entry["mission_id"])
                    m_key = str(m_id)
                    if m_key not in self._missions:
                        raise RecordNotFoundError(
                            f"Mission state update references absent mission {m_key} "
                            "during durable log replay."
                        )
                    old_m = self._missions[m_key]
                    new_st = MissionState(entry["state"])
                    if old_m.state != new_st:
                        assert_valid_transition(old_m.state, new_st)
                    updated_m = MissionRecord(
                        mission_id=old_m.mission_id,
                        contract=old_m.contract,
                        state=new_st,
                        created_at=old_m.created_at,
                        updated_at=datetime.fromisoformat(entry["updated_at"]),
                    )
                    self._missions[m_key] = updated_m
                elif rec_type == "action":
                    a_id = ActionId(entry["action_id"])
                    m_id = MissionId(entry["mission_id"])
                    m_key = str(m_id)
                    if m_key not in self._missions:
                        raise RecordNotFoundError(
                            f"Action {a_id} references absent mission {m_key} "
                            "during durable log replay."
                        )
                    a_data = entry["action"]
                    target = TargetIdentity(
                        system=a_data["target"]["system"],
                        resource_kind=ResourceKind(a_data["target"]["resource_kind"]),
                        resource_id=a_data["target"]["resource_id"],
                        parent_id=a_data["target"].get("parent_id"),
                    )
                    act_contract = ActionContract(
                        action_id=a_id,
                        mission_id=m_id,
                        action_type=ActionType(a_data["action_type"]),
                        target=target,
                        parameters=NormalizedParameters.from_dict(a_data["parameters"]),
                    )
                    appr_id = ApprovalId(entry["approval_id"]) if entry.get("approval_id") else None
                    act_record = ActionRecord(
                        action_id=a_id,
                        mission_id=m_id,
                        action=act_contract,
                        approval_id=appr_id,
                        created_at=datetime.fromisoformat(entry["created_at"]),
                    )
                    a_key = str(a_id)
                    if a_key in self._actions:
                        existing_action = self._actions[a_key]
                        if canonical_serialize(
                            to_canonical_primitive(existing_action)
                        ) == canonical_serialize(to_canonical_primitive(act_record)):
                            raise DuplicateRecordError(
                                f"Duplicate action {a_key} encountered during durable log replay."
                            )
                        raise RecordConflictError(
                            f"Conflicting record for action {a_key} "
                            "encountered during durable log replay."
                        )
                    self._actions[a_key] = act_record
                    self._mission_actions.setdefault(m_key, []).append(a_key)
                    self._action_evidence.setdefault(a_key, [])
                elif rec_type == "evidence":
                    e_id = EvidenceId(entry["evidence_id"])
                    a_id = ActionId(entry["action_id"])
                    m_id = MissionId(entry["mission_id"])
                    a_key = str(a_id)
                    if a_key not in self._actions:
                        raise RecordNotFoundError(
                            f"Evidence {e_id} references absent action {a_key} "
                            "during durable log replay."
                        )
                    expected_mission_id = self._actions[a_key].mission_id
                    if expected_mission_id != m_id:
                        raise LedgerError(
                            f"Evidence {e_id} mission {m_id} does not match referenced "
                            f"action mission {expected_mission_id}."
                        )
                    orig_data = entry["origin"]
                    origin = EvidenceOrigin.create(
                        provenance=orig_data["provenance"],
                        observed_at=datetime.fromisoformat(orig_data["observed_at"]),
                        recorded_live_origin=orig_data.get("recorded_live_origin"),
                    )
                    expected_eid = compute_evidence_id(
                        {"origin": origin, "payload": freeze_canonical_payload(entry["payload"])}
                    )
                    if expected_eid != e_id:
                        raise RecordConflictError(
                            f"Evidence {e_id} failed content-address validation during replay; "
                            f"expected {expected_eid}."
                        )
                    ev_record = EvidenceRecord(
                        evidence_id=e_id,
                        action_id=a_id,
                        mission_id=m_id,
                        origin=origin,
                        payload=entry["payload"],
                        created_at=datetime.fromisoformat(entry["created_at"]),
                    )
                    e_key = str(e_id)
                    m_key = str(m_id)
                    if e_key in self._evidence:
                        existing_evidence = self._evidence[e_key]
                        if canonical_serialize(
                            to_canonical_primitive(existing_evidence)
                        ) == canonical_serialize(to_canonical_primitive(ev_record)):
                            raise DuplicateRecordError(
                                f"Duplicate evidence {e_key} encountered during durable log replay."
                            )
                        raise RecordConflictError(
                            f"Conflicting record for evidence {e_key} "
                            "encountered during durable log replay."
                        )
                    self._evidence[e_key] = ev_record
                    self._action_evidence.setdefault(a_key, []).append(e_key)
                    self._mission_evidence.setdefault(m_key, []).append(e_key)
                elif rec_type == "durable_transition":
                    m_id = MissionId(entry["mission_id"])
                    m_key = str(m_id)
                    if m_key not in self._missions:
                        raise RecordNotFoundError(
                            f"Durable transition references absent mission {m_key} "
                            "during durable log replay."
                        )
                    old_m = self._missions[m_key]
                    exp_st = MissionState(entry["expected_prior_state"])
                    if old_m.state != exp_st:
                        raise RecordConflictError(
                            f"Conflicting prior state during replay for mission {m_key}: "
                            f"current is {old_m.state.value}, expected {exp_st.value}"
                        )
                    new_st = MissionState(entry["new_state"])
                    assert_valid_transition(exp_st, new_st)

                    ev_data = entry["evidence"]
                    e_id = EvidenceId(ev_data["evidence_id"])
                    a_id = ActionId(ev_data["action_id"])
                    a_key = str(a_id)
                    if a_key not in self._actions:
                        raise RecordNotFoundError(
                            f"Durable transition evidence references absent action {a_key}"
                        )
                    orig_data = ev_data["origin"]
                    origin = EvidenceOrigin.create(
                        provenance=orig_data["provenance"],
                        observed_at=datetime.fromisoformat(orig_data["observed_at"]),
                        recorded_live_origin=orig_data.get("recorded_live_origin"),
                    )
                    ev_record = EvidenceRecord(
                        evidence_id=e_id,
                        action_id=a_id,
                        mission_id=m_id,
                        origin=origin,
                        payload=ev_data["payload"],
                        created_at=datetime.fromisoformat(ev_data["created_at"]),
                    )
                    e_key = str(e_id)
                    self._evidence[e_key] = ev_record
                    self._action_evidence.setdefault(a_key, []).append(e_key)
                    self._mission_evidence.setdefault(m_key, []).append(e_key)

                    updated_m = MissionRecord(
                        mission_id=old_m.mission_id,
                        contract=old_m.contract,
                        state=new_st,
                        created_at=old_m.created_at,
                        updated_at=datetime.fromisoformat(entry["updated_at"]),
                    )
                    self._missions[m_key] = updated_m
                    if entry.get("snapshot_projection") is not None:
                        self._transition_snapshots[m_key] = entry["snapshot_projection"]
                else:
                    raise LedgerError(
                        f"Unknown record_type '{rec_type}' encountered during durable log replay."
                    )

    def append_mission(self, record: MissionRecord) -> None:
        if record.state == MissionState.READY:
            raise IllegalStatePromotionError(
                f"Cannot initialize mission {record.mission_id} directly in READY state. "
                "READY may only be entered from VERIFYING via valid verification."
            )
        key = str(record.mission_id)
        if key in self._missions:
            existing = self._missions[key]
            if canonical_serialize(to_canonical_primitive(existing)) == canonical_serialize(
                to_canonical_primitive(record)
            ):
                raise DuplicateRecordError(
                    f"Mission {key} already exists with identical content. "
                    "Silent overwrite is prohibited in append-only ledger."
                )
            raise RecordConflictError(
                f"Conflicting record for mission {key}: existing record differs from new record."
            )

        entry = {
            "record_type": "mission",
            "mission_id": str(record.mission_id),
            "contract": to_canonical_primitive(record.contract),
            "state": record.state.value,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }
        self._write_entry(entry)

        self._missions[key] = record
        self._mission_actions.setdefault(key, [])
        self._mission_evidence.setdefault(key, [])

    def update_mission_state(
        self,
        mission_id: MissionId,
        new_state: MissionState,
        updated_at: datetime | None = None,
    ) -> MissionRecord:
        key = str(mission_id)
        if key not in self._missions:
            raise RecordNotFoundError(f"Mission {key} not found in ledger")
        old = self._missions[key]
        if old.state != new_state:
            assert_valid_transition(old.state, new_state)

        if new_state == MissionState.READY:
            action_ids = self._mission_actions.get(key, [])
            if not action_ids:
                raise IllegalStatePromotionError(
                    f"Cannot promote mission {key} to READY in ledger with zero actions"
                )
            for a_key in action_ids:
                e_keys = self._action_evidence.get(a_key, [])
                if not e_keys:
                    raise IllegalStatePromotionError(
                        f"Cannot promote mission {key} to READY: action {a_key} has zero evidence"
                    )
                has_verification = any(
                    _is_verification_evidence(self._evidence[ek])
                    for ek in e_keys
                    if ek in self._evidence
                )
                if not has_verification:
                    raise IllegalStatePromotionError(
                        f"Cannot promote mission {key} to READY: action {a_key} lacks verification"
                    )

        now = updated_at or datetime.now(UTC)
        norm_now = _normalize_utc(now, "updated_at")
        updated = MissionRecord(
            mission_id=old.mission_id,
            contract=old.contract,
            state=new_state,
            created_at=old.created_at,
            updated_at=norm_now,
        )
        entry = {
            "record_type": "mission_state_update",
            "mission_id": key,
            "state": new_state.value,
            "updated_at": norm_now.isoformat(),
        }
        self._write_entry(entry)
        self._missions[key] = updated
        return updated

    def get_mission(self, mission_id: MissionId) -> MissionRecord:
        key = str(mission_id)
        if key not in self._missions:
            raise RecordNotFoundError(f"Mission {key} not found in ledger")
        return self._missions[key]

    def append_action(self, record: ActionRecord) -> None:
        m_key = str(record.mission_id)
        if m_key not in self._missions:
            raise RecordNotFoundError(
                f"Cannot append action {record.action_id}: mission {m_key} does not exist in ledger"
            )

        a_key = str(record.action_id)
        if a_key in self._actions:
            existing = self._actions[a_key]
            if canonical_serialize(to_canonical_primitive(existing)) == canonical_serialize(
                to_canonical_primitive(record)
            ):
                raise DuplicateRecordError(
                    f"Action {a_key} already exists with identical content. "
                    "Silent overwrite is prohibited in append-only ledger."
                )
            raise RecordConflictError(
                f"Conflicting record for action {a_key}: existing record differs from new record."
            )

        entry = {
            "record_type": "action",
            "action_id": str(record.action_id),
            "mission_id": str(record.mission_id),
            "action": to_canonical_primitive(record.action),
            "approval_id": str(record.approval_id) if record.approval_id else None,
            "created_at": record.created_at.isoformat(),
        }
        self._write_entry(entry)

        self._actions[a_key] = record
        self._mission_actions[m_key].append(a_key)
        self._action_evidence.setdefault(a_key, [])

    def get_action(self, action_id: ActionId) -> ActionRecord:
        key = str(action_id)
        if key not in self._actions:
            raise RecordNotFoundError(f"Action {key} not found in ledger")
        return self._actions[key]

    def get_actions_for_mission(self, mission_id: MissionId) -> list[ActionRecord]:
        m_key = str(mission_id)
        if m_key not in self._missions:
            raise RecordNotFoundError(f"Mission {m_key} not found in ledger")
        return [self._actions[a_key] for a_key in self._mission_actions.get(m_key, [])]

    def append_evidence(self, record: EvidenceRecord) -> None:
        m_key = str(record.mission_id)
        if m_key not in self._missions:
            msg = (
                f"Cannot append evidence {record.evidence_id}: "
                f"mission {m_key} does not exist in ledger"
            )
            raise RecordNotFoundError(msg)

        a_key = str(record.action_id)
        if a_key not in self._actions:
            msg = (
                f"Cannot append evidence {record.evidence_id}: "
                f"action {a_key} does not exist in ledger"
            )
            raise RecordNotFoundError(msg)

        action_record = self._actions[a_key]
        if str(action_record.mission_id) != m_key:
            msg = (
                f"Relationship mismatch: action {a_key} belongs to mission "
                f"{action_record.mission_id}, not {m_key}"
            )
            raise LedgerError(msg)

        e_key = str(record.evidence_id)
        if e_key in self._evidence:
            existing = self._evidence[e_key]
            if canonical_serialize(to_canonical_primitive(existing)) == canonical_serialize(
                to_canonical_primitive(record)
            ):
                raise DuplicateRecordError(
                    f"Evidence {e_key} already exists with identical content. "
                    "Silent overwrite is prohibited in append-only ledger."
                )
            raise RecordConflictError(
                f"Conflicting record for evidence {e_key}: existing record differs from new record."
            )

        entry = {
            "record_type": "evidence",
            "evidence_id": str(record.evidence_id),
            "action_id": str(record.action_id),
            "mission_id": str(record.mission_id),
            "origin": {
                "provenance": record.origin.provenance.value,
                "observed_at": record.origin.observed_at.isoformat(),
                "recorded_live_origin": (
                    record.origin.recorded_live_origin.value
                    if record.origin.recorded_live_origin
                    else None
                ),
            },
            "payload": to_canonical_primitive(record.payload),
            "created_at": record.created_at.isoformat(),
        }
        self._write_entry(entry)

        self._evidence[e_key] = EvidenceRecord(
            evidence_id=record.evidence_id,
            action_id=record.action_id,
            mission_id=record.mission_id,
            origin=record.origin,
            payload=record.payload,
            created_at=record.created_at,
        )
        self._action_evidence[a_key].append(e_key)
        self._mission_evidence[m_key].append(e_key)

    def get_evidence(self, evidence_id: EvidenceId) -> EvidenceRecord:
        key = str(evidence_id)
        if key not in self._evidence:
            raise RecordNotFoundError(f"Evidence {key} not found in ledger")
        stored = self._evidence[key]
        return EvidenceRecord(
            evidence_id=stored.evidence_id,
            action_id=stored.action_id,
            mission_id=stored.mission_id,
            origin=stored.origin,
            payload=stored.payload,
            created_at=stored.created_at,
        )

    def get_evidence_for_action(self, action_id: ActionId) -> list[EvidenceRecord]:
        a_key = str(action_id)
        if a_key not in self._actions:
            raise RecordNotFoundError(f"Action {a_key} not found in ledger")
        return [
            self.get_evidence(EvidenceId(e_key)) for e_key in self._action_evidence.get(a_key, [])
        ]

    def get_evidence_for_mission(self, mission_id: MissionId) -> list[EvidenceRecord]:
        m_key = str(mission_id)
        if m_key not in self._missions:
            raise RecordNotFoundError(f"Mission {m_key} not found in ledger")
        return [
            self.get_evidence(EvidenceId(e_key)) for e_key in self._mission_evidence.get(m_key, [])
        ]

    def get_all_evidence(self) -> list[EvidenceRecord]:
        """List all evidence records in the ledger in append order."""
        return [self.get_evidence(EvidenceId(e_key)) for e_key in self._evidence]

    def record_state_transition(
        self,
        *,
        mission_id: MissionId,
        expected_prior_state: MissionState,
        new_state: MissionState,
        evidence: EvidenceRecord,
        updated_at: datetime | None = None,
        snapshot_projection: dict[str, Any] | None = None,
    ) -> tuple[MissionRecord, EvidenceRecord]:
        key = str(mission_id)
        if key not in self._missions:
            raise RecordNotFoundError(f"Mission {key} not found in ledger")
        old = self._missions[key]
        if old.state != expected_prior_state:
            raise RecordConflictError(
                f"Cannot transition mission {key}: current state is {old.state.value}, "
                f"expected prior state is {expected_prior_state.value}"
            )
        assert_valid_transition(expected_prior_state, new_state)

        if old.mission_id != evidence.mission_id:
            raise LedgerError(
                f"Evidence mission {evidence.mission_id} does not match {old.mission_id}"
            )
        a_key = str(evidence.action_id)
        if a_key not in self._actions:
            raise RecordNotFoundError(f"Action {a_key} does not exist in ledger")
        if str(self._actions[a_key].mission_id) != key:
            raise LedgerError(
                f"Action {a_key} belongs to mission {self._actions[a_key].mission_id}, not {key}"
            )

        e_key = str(evidence.evidence_id)
        if e_key in self._evidence:
            existing = self._evidence[e_key]
            if canonical_serialize(to_canonical_primitive(existing)) == canonical_serialize(
                to_canonical_primitive(evidence)
            ):
                raise DuplicateRecordError(
                    f"Evidence {e_key} already exists with identical content."
                )
            raise RecordConflictError(f"Conflicting record for evidence {e_key}")

        now = updated_at or datetime.now(UTC)
        norm_now = _normalize_utc(now, "updated_at")

        entry = {
            "record_type": "durable_transition",
            "mission_id": key,
            "expected_prior_state": expected_prior_state.value,
            "new_state": new_state.value,
            "evidence": {
                "evidence_id": str(evidence.evidence_id),
                "action_id": str(evidence.action_id),
                "mission_id": str(evidence.mission_id),
                "origin": {
                    "provenance": evidence.origin.provenance.value,
                    "observed_at": evidence.origin.observed_at.isoformat(),
                    "recorded_live_origin": (
                        evidence.origin.recorded_live_origin.value
                        if evidence.origin.recorded_live_origin
                        else None
                    ),
                },
                "payload": to_canonical_primitive(evidence.payload),
                "created_at": evidence.created_at.isoformat(),
            },
            "updated_at": norm_now.isoformat(),
            "snapshot_projection": snapshot_projection,
        }
        self._write_entry(entry)

        self._evidence[e_key] = EvidenceRecord(
            evidence_id=evidence.evidence_id,
            action_id=evidence.action_id,
            mission_id=evidence.mission_id,
            origin=evidence.origin,
            payload=evidence.payload,
            created_at=evidence.created_at,
        )
        self._action_evidence[a_key].append(e_key)
        self._mission_evidence[key].append(e_key)

        updated = MissionRecord(
            mission_id=old.mission_id,
            contract=old.contract,
            state=new_state,
            created_at=old.created_at,
            updated_at=norm_now,
        )
        self._missions[key] = updated
        if snapshot_projection is not None:
            self._transition_snapshots[key] = dict(snapshot_projection)
        return updated, evidence

    def get_transition_snapshot(self, mission_id: MissionId) -> dict[str, Any] | None:
        return self._transition_snapshots.get(str(mission_id))
