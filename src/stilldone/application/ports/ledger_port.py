"""Provider-neutral append-only ledger port for StillDone.

Defines immutable records for missions, actions, and evidence, and the abstract
MissionLedgerPort interface.
Provides an explicitly non-durable in-memory implementation for testing and runtime-local state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, SupportsIndex

from stilldone.domain.action import ActionContract, ActionId
from stilldone.domain.authority import ApprovalId
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.domain.provenance import EvidenceOrigin
from stilldone.evidence import EvidenceId, compute_evidence_id
from stilldone.serialization import canonical_serialize, to_canonical_primitive


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


class MissionLedgerPort(ABC):
    """Abstract provider-neutral append-only ledger interface."""

    @abstractmethod
    def append_mission(self, record: MissionRecord) -> None:
        """Append a mission record. Fails closed on duplicates or conflicts."""

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
