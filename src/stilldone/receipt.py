"""Deterministic receipt projection primitives for StillDone.

Provides typed immutable receipt projections binding exact mission content hashes,
canonical evidence identity sequences, and domain-separated projection digests.
A receipt is a deterministic projection of already-owned facts, NEVER an authority
source, and NEVER promotes mission state.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from stilldone.application.ports.ledger_port import (
    CanonicalPayload,
    EvidenceRecord,
    freeze_canonical_payload,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.evidence import EvidenceId
from stilldone.serialization import (
    canonical_serialize,
    normalize_datetime,
    to_canonical_primitive,
)

MISSION_CONTENT_HASH_DOMAIN_SEPARATOR: str = "stilldone:mission-content:v1"
RECEIPT_HASH_DOMAIN_SEPARATOR: str = "stilldone:receipt-projection:v1"


class ReceiptError(Exception):
    """Base exception for all receipt projection operations."""


class MalformedHashError(ReceiptError):
    """Raised when a cryptographic hash format is invalid."""


class ReceiptMismatchError(ReceiptError):
    """Raised when mission or evidence bindings mismatch."""


class DuplicateEvidenceBindingError(ReceiptError):
    """Raised when duplicate evidence IDs are bound to a receipt projection."""


class EvidenceOrderError(ReceiptError):
    """Raised when evidence IDs are not canonically ordered."""


class ReceiptHashMismatchError(ReceiptError):
    """Raised when the bound receipt hash does not match computed projection hash."""


class ReceiptNotFoundError(ReceiptError, KeyError):
    """Raised when a requested receipt is not found."""


class PlannerCurrentStateAuthorityError(ReceiptError, TypeError):
    """Raised when a planner/model proposal object is passed as authority for current state."""


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


def assert_not_planner_for_current_state(obj: Any, *, parameter_name: str = "argument") -> None:
    """Reject planner/model proposals fail-closed."""
    for pt in _PLANNER_TYPES:
        if isinstance(obj, pt):
            raise PlannerCurrentStateAuthorityError(
                f"Model/planner proposal {type(obj).__name__} has ZERO authority "
                f"over current-state projections ({parameter_name})"
            )


def _validate_hex_digest(value: str, name: str) -> None:
    """Validate that a string is a 64-character lowercase hexadecimal digest."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")
    if len(value) != 64:
        raise MalformedHashError(f"{name} must be exactly 64 characters, got {len(value)}")
    for char in value:
        if char not in "0123456789abcdef":
            raise MalformedHashError(f"{name} must be lowercase hexadecimal: {value!r}")


def _normalize_utc_dt(dt: datetime, name: str) -> datetime:
    """Validate and normalize a datetime to timezone-aware UTC."""
    if not isinstance(dt, datetime):
        raise TypeError(f"{name} must be a datetime instance, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware (UTC required)")
    return dt if dt.tzinfo == UTC else dt.astimezone(UTC)


@dataclass(frozen=True)
class MissionContentHash:
    """Dedicated domain-separated SHA-256 hash of a canonical mission snapshot.

    Distinct from EvidenceId semantics: hashes mission identity and intent contracts,
    and is structurally bound to the MissionId whose canonical snapshot produced it.
    """

    value: str
    mission_id: MissionId

    def __post_init__(self) -> None:
        _validate_hex_digest(self.value, "MissionContentHash")
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )

    def to_canonical(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


def compute_mission_content_hash(
    mission: MissionContract | dict[str, Any],
    *,
    mission_id: MissionId | None = None,
    domain: str = MISSION_CONTENT_HASH_DOMAIN_SEPARATOR,
) -> MissionContentHash:
    """Compute a deterministic domain-separated SHA-256 hash for a mission snapshot."""
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError("domain must be a non-empty string")

    if isinstance(mission, MissionContract):
        extracted_mid = mission.mission_id
        if mission_id is not None and mission_id != extracted_mid:
            raise ReceiptMismatchError(
                f"Supplied mission_id {mission_id} does not match "
                f"MissionContract mission_id {extracted_mid}"
            )
        content = {
            "created_at": normalize_datetime(mission.created_at),
            "intent": {
                "captured_at": normalize_datetime(mission.intent.captured_at),
                "mission_id": str(mission.intent.mission_id),
                "text": mission.intent.text,
            },
            "mission_id": str(mission.mission_id),
            "schema_version": mission.schema_version,
        }
    elif isinstance(mission, dict):
        if "mission_id" in mission:
            raw_mid = mission["mission_id"]
            extracted_mid = raw_mid if isinstance(raw_mid, MissionId) else MissionId(str(raw_mid))
            if mission_id is not None and mission_id != extracted_mid:
                raise ReceiptMismatchError(
                    f"Supplied mission_id {mission_id} does not match "
                    f"mission dict mission_id {extracted_mid}"
                )
        elif mission_id is not None:
            extracted_mid = mission_id
        else:
            raise ValueError(
                "mission_id is required when mission dict does not contain 'mission_id'"
            )
        content = to_canonical_primitive(mission)
    else:
        raise TypeError(f"Expected MissionContract or dict, got {type(mission).__name__}")

    envelope: dict[str, Any] = {
        "_domain": domain,
        "mission": content,
    }
    serialized_bytes = canonical_serialize(envelope)
    digest = hashlib.sha256(serialized_bytes).hexdigest()
    return MissionContentHash(value=digest, mission_id=extracted_mid)


@dataclass(frozen=True)
class ReceiptHash:
    """Immutable content-addressed hash of a receipt projection."""

    value: str

    def __post_init__(self) -> None:
        _validate_hex_digest(self.value, "ReceiptHash")

    def to_canonical(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


def compute_receipt_hash(
    *,
    mission_id: MissionId,
    mission_content_hash: MissionContentHash,
    evidence_ids: tuple[EvidenceId, ...],
    state_at_projection: MissionState,
    projected_at: datetime,
    metadata: CanonicalPayload | dict[str, Any] | None = None,
    domain: str = RECEIPT_HASH_DOMAIN_SEPARATOR,
) -> ReceiptHash:
    """Compute a deterministic SHA-256 receipt hash with domain separation."""
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError("domain must be a non-empty string")
    if not isinstance(mission_id, MissionId):
        raise TypeError(f"mission_id must be MissionId, got {type(mission_id).__name__}")
    if not isinstance(mission_content_hash, MissionContentHash):
        raise TypeError(
            f"mission_content_hash must be MissionContentHash, "
            f"got {type(mission_content_hash).__name__}"
        )
    if mission_content_hash.mission_id != mission_id:
        raise ReceiptMismatchError(
            f"MissionContentHash mission_id {mission_content_hash.mission_id} "
            f"does not match mission_id {mission_id}"
        )
    if not isinstance(evidence_ids, tuple):
        raise TypeError(f"evidence_ids must be a tuple, got {type(evidence_ids).__name__}")
    if not isinstance(state_at_projection, MissionState):
        raise TypeError(
            f"state_at_projection must be MissionState, got {type(state_at_projection).__name__}"
        )

    norm_projected_at = _normalize_utc_dt(projected_at, "projected_at")

    envelope: dict[str, Any] = {
        "_domain": domain,
        "evidence_ids": [eid.value for eid in evidence_ids],
        "metadata": to_canonical_primitive(metadata or {}),
        "mission_content_hash": mission_content_hash.value,
        "mission_id": str(mission_id),
        "projected_at": normalize_datetime(norm_projected_at),
        "state_at_projection": state_at_projection.value,
    }
    serialized_bytes = canonical_serialize(envelope)
    digest = hashlib.sha256(serialized_bytes).hexdigest()
    return ReceiptHash(digest)


def validate_evidence_records_for_mission(
    mission_id: MissionId,
    records: Sequence[EvidenceRecord],
) -> tuple[EvidenceId, ...]:
    """Validate that all evidence records belong to the given mission.

    Returns sorted unique EvidenceIds.
    Fails closed if:
    - Any record belongs to a different mission_id.
    - Duplicate evidence IDs are present.
    """
    if not isinstance(mission_id, MissionId):
        raise TypeError(f"mission_id must be MissionId, got {type(mission_id).__name__}")
    if not isinstance(records, (list, tuple)):
        raise TypeError(f"records must be a sequence, got {type(records).__name__}")

    seen_ids: set[str] = set()
    result_ids: list[EvidenceId] = []

    for rec in records:
        if not isinstance(rec, EvidenceRecord):
            raise TypeError(f"Expected EvidenceRecord, got {type(rec).__name__}")
        if rec.mission_id != mission_id:
            raise ReceiptMismatchError(
                f"EvidenceRecord {rec.evidence_id} belongs to mission "
                f"{rec.mission_id}, not expected {mission_id}"
            )
        if rec.evidence_id.value in seen_ids:
            raise DuplicateEvidenceBindingError(
                f"Duplicate evidence record ID: {rec.evidence_id.value}"
            )
        seen_ids.add(rec.evidence_id.value)
        result_ids.append(rec.evidence_id)

    # Sort lexicographically by EvidenceId value for canonical deterministic ordering
    result_ids.sort(key=lambda eid: eid.value)
    return tuple(result_ids)


@dataclass(frozen=True)
class ReceiptProjection:
    """Typed immutable receipt projection of recorded mission and evidence facts.

    Guarantees:
    - Binds exact MissionId and dedicated MissionContentHash (verifies identity attribution).
    - Binds canonically ordered, deduplicated EvidenceId sequence.
    - Binds state at the exact moment of projection.
    - Binds domain-separated SHA-256 ReceiptHash.
    - Stores metadata as a detached immutable CanonicalPayload snapshot.
    - Explicitly flagged as historical projection (`is_historical = True`).
    - Does NOT claim current-live truth or independent read-back beyond recorded facts.
    - Does NOT promote mission state or assert READY.
    """

    mission_id: MissionId
    mission_content_hash: MissionContentHash
    evidence_ids: tuple[EvidenceId, ...]
    state_at_projection: MissionState
    projected_at: datetime
    receipt_hash: ReceiptHash
    metadata: CanonicalPayload
    is_historical: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(self.mission_id).__name__}")
        if not isinstance(self.mission_content_hash, MissionContentHash):
            raise TypeError(
                f"mission_content_hash must be MissionContentHash, "
                f"got {type(self.mission_content_hash).__name__}"
            )
        if self.mission_content_hash.mission_id != self.mission_id:
            raise ReceiptMismatchError(
                f"MissionContentHash mission_id {self.mission_content_hash.mission_id} "
                f"does not match ReceiptProjection mission_id {self.mission_id}"
            )
        if not isinstance(self.evidence_ids, tuple):
            raise TypeError(f"evidence_ids must be a tuple, got {type(self.evidence_ids).__name__}")
        if not isinstance(self.state_at_projection, MissionState):
            raise TypeError(
                f"state_at_projection must be MissionState, "
                f"got {type(self.state_at_projection).__name__}"
            )
        if not isinstance(self.receipt_hash, ReceiptHash):
            raise TypeError(
                f"receipt_hash must be ReceiptHash, got {type(self.receipt_hash).__name__}"
            )
        if not isinstance(self.is_historical, bool) or not self.is_historical:
            raise ValueError("Receipt projections must always have is_historical=True")

        norm_projected = _normalize_utc_dt(self.projected_at, "projected_at")
        object.__setattr__(self, "projected_at", norm_projected)

        # Validate evidence IDs: must be EvidenceId instances, unique, and lexicographically sorted
        seen_eids: set[str] = set()
        prev_eid: str | None = None
        for eid in self.evidence_ids:
            if not isinstance(eid, EvidenceId):
                raise TypeError(
                    f"evidence_ids must contain EvidenceId instances, got {type(eid).__name__}"
                )
            if eid.value in seen_eids:
                raise DuplicateEvidenceBindingError(
                    f"Duplicate evidence ID in receipt: {eid.value}"
                )
            if prev_eid is not None and eid.value < prev_eid:
                raise EvidenceOrderError(
                    f"Evidence IDs are not canonically ordered: {prev_eid} followed by {eid.value}"
                )
            seen_eids.add(eid.value)
            prev_eid = eid.value

        # Freeze metadata as a detached immutable CanonicalPayload snapshot
        frozen_meta = freeze_canonical_payload(self.metadata or {})
        object.__setattr__(self, "metadata", frozen_meta)

        # Verify receipt hash against stored immutable metadata
        expected_hash = compute_receipt_hash(
            mission_id=self.mission_id,
            mission_content_hash=self.mission_content_hash,
            evidence_ids=self.evidence_ids,
            state_at_projection=self.state_at_projection,
            projected_at=self.projected_at,
            metadata=self.metadata,
        )
        if self.receipt_hash != expected_hash:
            raise ReceiptHashMismatchError(
                f"Receipt hash mismatch: bound {self.receipt_hash} != computed {expected_hash}"
            )

    @classmethod
    def create(
        cls,
        *,
        mission_id: MissionId,
        mission_content_hash: MissionContentHash,
        evidence_ids: Iterable[EvidenceId],
        state_at_projection: MissionState,
        projected_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReceiptProjection:
        """Create a ReceiptProjection with canonical ordering and computed ReceiptHash."""
        if not isinstance(mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(mission_id).__name__}")
        if not isinstance(mission_content_hash, MissionContentHash):
            raise TypeError(
                f"mission_content_hash must be MissionContentHash, "
                f"got {type(mission_content_hash).__name__}"
            )
        if mission_content_hash.mission_id != mission_id:
            raise ReceiptMismatchError(
                f"MissionContentHash mission_id {mission_content_hash.mission_id} "
                f"does not match ReceiptProjection mission_id {mission_id}"
            )

        norm_projected_at = _normalize_utc_dt(projected_at or datetime.now(UTC), "projected_at")

        # Canonicalize evidence IDs: check types, deduplicate, sort lexicographically
        seen: set[str] = set()
        eids_list: list[EvidenceId] = []
        for eid in evidence_ids:
            if not isinstance(eid, EvidenceId):
                raise TypeError(
                    f"All evidence_ids must be EvidenceId instances, got {type(eid).__name__}"
                )
            if eid.value in seen:
                raise DuplicateEvidenceBindingError(
                    f"Duplicate evidence ID in evidence_ids: {eid.value}"
                )
            seen.add(eid.value)
            eids_list.append(eid)

        eids_list.sort(key=lambda x: x.value)
        ordered_eids = tuple(eids_list)

        frozen_meta = freeze_canonical_payload(metadata or {})

        receipt_hash = compute_receipt_hash(
            mission_id=mission_id,
            mission_content_hash=mission_content_hash,
            evidence_ids=ordered_eids,
            state_at_projection=state_at_projection,
            projected_at=norm_projected_at,
            metadata=frozen_meta,
        )

        return cls(
            mission_id=mission_id,
            mission_content_hash=mission_content_hash,
            evidence_ids=ordered_eids,
            state_at_projection=state_at_projection,
            projected_at=norm_projected_at,
            receipt_hash=receipt_hash,
            metadata=frozen_meta,
            is_historical=True,
        )

    @classmethod
    def from_records(
        cls,
        *,
        mission_id: MissionId,
        mission_content_hash: MissionContentHash,
        evidence_records: Sequence[EvidenceRecord],
        state_at_projection: MissionState,
        projected_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReceiptProjection:
        """Create a ReceiptProjection from EvidenceRecord instances with mission validation."""
        if not isinstance(mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(mission_id).__name__}")
        if not isinstance(mission_content_hash, MissionContentHash):
            raise TypeError(
                f"mission_content_hash must be MissionContentHash, "
                f"got {type(mission_content_hash).__name__}"
            )
        if mission_content_hash.mission_id != mission_id:
            raise ReceiptMismatchError(
                f"MissionContentHash mission_id {mission_content_hash.mission_id} "
                f"does not match ReceiptProjection mission_id {mission_id}"
            )
        ordered_eids = validate_evidence_records_for_mission(mission_id, evidence_records)
        return cls.create(
            mission_id=mission_id,
            mission_content_hash=mission_content_hash,
            evidence_ids=ordered_eids,
            state_at_projection=state_at_projection,
            projected_at=projected_at,
            metadata=metadata,
        )

    def to_canonical(self) -> dict[str, Any]:
        """Project receipt to a canonical JSON-compatible dictionary."""
        return {
            "evidence_ids": [eid.to_canonical() for eid in self.evidence_ids],
            "is_historical": self.is_historical,
            "metadata": self.metadata.to_dict(),
            "mission_content_hash": self.mission_content_hash.to_canonical(),
            "mission_id": str(self.mission_id),
            "projected_at": normalize_datetime(self.projected_at),
            "receipt_hash": self.receipt_hash.to_canonical(),
            "state_at_projection": self.state_at_projection.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_canonical()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReceiptProjection:
        """Construct and validate a ReceiptProjection from a dictionary.

        Fails closed on missing keys, tampered hashes, or invalid types.
        """
        if not isinstance(data, dict):
            raise TypeError(f"Receipt data must be a dict, got {type(data).__name__}")
        for req in (
            "mission_id",
            "mission_content_hash",
            "evidence_ids",
            "state_at_projection",
            "projected_at",
            "receipt_hash",
        ):
            if req not in data:
                raise ReceiptMismatchError(f"Missing required receipt key: {req!r}")

        m_id = MissionId(str(data["mission_id"]))
        m_hash = MissionContentHash(
            value=str(data["mission_content_hash"]),
            mission_id=m_id,
        )
        raw_eids = data["evidence_ids"]
        if not isinstance(raw_eids, (list, tuple)):
            raise TypeError("evidence_ids must be a sequence")
        eids = tuple(EvidenceId(str(e)) for e in raw_eids)
        st = MissionState(str(data["state_at_projection"]))
        proj_at = datetime.fromisoformat(str(data["projected_at"]))
        r_hash = ReceiptHash(str(data["receipt_hash"]))
        meta = CanonicalPayload(data.get("metadata", {}))
        is_hist = data.get("is_historical", True)
        if not is_hist:
            raise ValueError("Receipt projections must always have is_historical=True")

        return cls(
            mission_id=m_id,
            mission_content_hash=m_hash,
            evidence_ids=eids,
            state_at_projection=st,
            projected_at=proj_at,
            receipt_hash=r_hash,
            metadata=meta,
            is_historical=True,
        )


def create_mission_ready_receipt(
    snapshot: Any,
    *,
    projected_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReceiptProjection:
    """Create an immutable ReceiptProjection from a verified READY snapshot.

    Fails closed if the snapshot is not in MissionState.READY.
    """
    assert_not_planner_for_current_state(snapshot, parameter_name="snapshot")
    from stilldone.snapshot import MissionSnapshot

    if not isinstance(snapshot, MissionSnapshot):
        raise TypeError(f"snapshot must be a MissionSnapshot, got {type(snapshot).__name__}")
    if snapshot.state != MissionState.READY:
        raise ReceiptMismatchError(
            f"Cannot create READY receipt for snapshot in non-READY state {snapshot.state.value}"
        )

    mission_content_hash = compute_mission_content_hash(snapshot.contract)
    meta = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        **(metadata or {}),
    }
    return ReceiptProjection.create(
        mission_id=snapshot.mission_id,
        mission_content_hash=mission_content_hash,
        evidence_ids=snapshot.evidence_ids,
        state_at_projection=MissionState.READY,
        projected_at=projected_at or snapshot.created_at,
        metadata=meta,
    )


CURRENT_STATE_HASH_DOMAIN_SEPARATOR: str = "stilldone:current-state-projection:v1"


@dataclass(frozen=True)
class CurrentStateHash:
    """Immutable content-addressed hash of an authoritative current-state projection."""

    value: str

    def __post_init__(self) -> None:
        _validate_hex_digest(self.value, "CurrentStateHash")

    def to_canonical(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


def compute_current_state_hash(
    *,
    mission_id: MissionId,
    state: MissionState,
    snapshot_id: str,
    evidence_ids: tuple[EvidenceId, ...],
    as_of: datetime,
    historical_receipt_hash: ReceiptHash | None = None,
    historical_state: MissionState | None = None,
    reconciliation_reason: str | None = None,
    domain: str = CURRENT_STATE_HASH_DOMAIN_SEPARATOR,
) -> CurrentStateHash:
    """Compute a deterministic domain-separated SHA-256 hash for a current-state projection."""
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError("domain must be a non-empty string")
    if not isinstance(mission_id, MissionId):
        raise TypeError(f"mission_id must be MissionId, got {type(mission_id).__name__}")
    if not isinstance(state, MissionState):
        raise TypeError(f"state must be MissionState, got {type(state).__name__}")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ValueError("snapshot_id must be a non-empty string")
    if not isinstance(evidence_ids, tuple):
        raise TypeError(f"evidence_ids must be a tuple, got {type(evidence_ids).__name__}")

    norm_as_of = _normalize_utc_dt(as_of, "as_of")

    envelope: dict[str, Any] = {
        "_domain": domain,
        "as_of": normalize_datetime(norm_as_of),
        "evidence_ids": [eid.value for eid in evidence_ids],
        "historical_receipt_hash": (
            historical_receipt_hash.value if historical_receipt_hash is not None else None
        ),
        "historical_state": historical_state.value if historical_state is not None else None,
        "is_historical": False,
        "mission_id": str(mission_id),
        "reconciliation_reason": reconciliation_reason,
        "snapshot_id": snapshot_id,
        "state": state.value,
    }
    serialized_bytes = canonical_serialize(envelope)
    digest = hashlib.sha256(serialized_bytes).hexdigest()
    return CurrentStateHash(digest)


@dataclass(frozen=True)
class CurrentStateProjection:
    """Typed immutable projection of current mission truth and lifecycle state.

    Guarantees:
    - is_historical is strictly False (historical completion != current completion).
    - state reflects current authoritative lifecycle state (e.g. READY, DRIFTED).
    - Tied to exact mission ID, canonical snapshot revision (snapshot_id), and evidence IDs.
    - Preserves immutable reference to historical receipt hash and state if previously verified.
    - Fails closed if tampered or if historical completion is conflated with current state.
    """

    mission_id: MissionId
    state: MissionState
    snapshot_id: str
    snapshot_version: str
    evidence_ids: tuple[EvidenceId, ...]
    as_of: datetime
    projection_hash: CurrentStateHash
    is_historical: bool = False
    historical_receipt_hash: ReceiptHash | None = None
    historical_state: MissionState | None = None
    reconciliation_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(self.mission_id).__name__}")
        if not isinstance(self.state, MissionState):
            raise TypeError(f"state must be MissionState, got {type(self.state).__name__}")
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id.strip():
            raise ValueError("snapshot_id must be a non-empty string")
        if not isinstance(self.snapshot_version, str) or not self.snapshot_version.strip():
            raise ValueError("snapshot_version must be a non-empty string")
        if not isinstance(self.evidence_ids, tuple):
            raise TypeError(f"evidence_ids must be a tuple, got {type(self.evidence_ids).__name__}")
        if self.is_historical is not False:
            raise ValueError("CurrentStateProjection must always have is_historical=False")

        norm_as_of = _normalize_utc_dt(self.as_of, "as_of")
        object.__setattr__(self, "as_of", norm_as_of)

        if self.historical_receipt_hash is not None and not isinstance(
            self.historical_receipt_hash, ReceiptHash
        ):
            raise TypeError("historical_receipt_hash must be ReceiptHash or None")
        if self.historical_state is not None and not isinstance(
            self.historical_state, MissionState
        ):
            raise TypeError("historical_state must be MissionState or None")

        # Validate evidence IDs: unique and canonically ordered
        seen_eids: set[str] = set()
        prev_eid: str | None = None
        for eid in self.evidence_ids:
            if not isinstance(eid, EvidenceId):
                raise TypeError(
                    f"evidence_ids must contain EvidenceId instances, got {type(eid).__name__}"
                )
            if eid.value in seen_eids:
                raise DuplicateEvidenceBindingError(
                    f"Duplicate evidence ID in current state: {eid.value}"
                )
            if prev_eid is not None and eid.value < prev_eid:
                raise EvidenceOrderError(
                    f"Evidence IDs are not canonically ordered: {prev_eid} followed by {eid.value}"
                )
            seen_eids.add(eid.value)
            prev_eid = eid.value

        expected_hash = compute_current_state_hash(
            mission_id=self.mission_id,
            state=self.state,
            snapshot_id=self.snapshot_id,
            evidence_ids=self.evidence_ids,
            as_of=self.as_of,
            historical_receipt_hash=self.historical_receipt_hash,
            historical_state=self.historical_state,
            reconciliation_reason=self.reconciliation_reason,
        )
        if self.projection_hash != expected_hash:
            raise ReceiptHashMismatchError(
                f"Current state projection hash mismatch: bound {self.projection_hash} "
                f"!= computed {expected_hash}"
            )

    @classmethod
    def create(
        cls,
        *,
        mission_id: MissionId,
        state: MissionState,
        snapshot_id: str,
        snapshot_version: str,
        evidence_ids: Iterable[EvidenceId],
        as_of: datetime | None = None,
        historical_receipt_hash: ReceiptHash | None = None,
        historical_state: MissionState | None = None,
        reconciliation_reason: str | None = None,
    ) -> CurrentStateProjection:
        """Create a CurrentStateProjection with canonical evidence ordering and computed hash."""
        if not isinstance(mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(mission_id).__name__}")
        if not isinstance(state, MissionState):
            raise TypeError(f"state must be MissionState, got {type(state).__name__}")

        norm_as_of = _normalize_utc_dt(as_of or datetime.now(UTC), "as_of")

        seen: set[str] = set()
        eids_list: list[EvidenceId] = []
        for eid in evidence_ids:
            if not isinstance(eid, EvidenceId):
                raise TypeError(
                    f"All evidence_ids must be EvidenceId instances, got {type(eid).__name__}"
                )
            if eid.value in seen:
                raise DuplicateEvidenceBindingError(
                    f"Duplicate evidence ID in evidence_ids: {eid.value}"
                )
            seen.add(eid.value)
            eids_list.append(eid)

        eids_list.sort(key=lambda x: x.value)
        ordered_eids = tuple(eids_list)

        proj_hash = compute_current_state_hash(
            mission_id=mission_id,
            state=state,
            snapshot_id=snapshot_id,
            evidence_ids=ordered_eids,
            as_of=norm_as_of,
            historical_receipt_hash=historical_receipt_hash,
            historical_state=historical_state,
            reconciliation_reason=reconciliation_reason,
        )

        return cls(
            mission_id=mission_id,
            state=state,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            evidence_ids=ordered_eids,
            as_of=norm_as_of,
            projection_hash=proj_hash,
            is_historical=False,
            historical_receipt_hash=historical_receipt_hash,
            historical_state=historical_state,
            reconciliation_reason=reconciliation_reason,
        )

    @property
    def is_ready(self) -> bool:
        """True if and only if current authoritative state is READY."""
        return self.state == MissionState.READY

    @property
    def is_drifted(self) -> bool:
        """True if and only if current authoritative state is DRIFTED."""
        return self.state == MissionState.DRIFTED

    def to_canonical(self) -> dict[str, Any]:
        """Project current state to a canonical JSON-compatible dictionary."""
        return {
            "as_of": normalize_datetime(self.as_of),
            "evidence_ids": [eid.to_canonical() for eid in self.evidence_ids],
            "historical_receipt_hash": (
                self.historical_receipt_hash.to_canonical()
                if self.historical_receipt_hash is not None
                else None
            ),
            "historical_state": self.historical_state.value if self.historical_state else None,
            "is_drifted": self.is_drifted,
            "is_historical": self.is_historical,
            "is_ready": self.is_ready,
            "mission_id": str(self.mission_id),
            "projection_hash": self.projection_hash.to_canonical(),
            "reconciliation_reason": self.reconciliation_reason,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "state": self.state.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_canonical()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurrentStateProjection:
        """Construct and validate a CurrentStateProjection from serialized dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Data must be a dict, got {type(data).__name__}")
        for req in (
            "mission_id",
            "state",
            "snapshot_id",
            "snapshot_version",
            "evidence_ids",
            "as_of",
            "projection_hash",
        ):
            if req not in data:
                raise ReceiptMismatchError(f"Missing required key: {req!r}")

        m_id = MissionId(str(data["mission_id"]))
        st = MissionState(str(data["state"]))
        raw_eids = data["evidence_ids"]
        if not isinstance(raw_eids, (list, tuple)):
            raise TypeError("evidence_ids must be a sequence")
        eids = tuple(EvidenceId(str(e)) for e in raw_eids)
        as_of = datetime.fromisoformat(str(data["as_of"]))
        p_hash = CurrentStateHash(str(data["projection_hash"]))
        hist_h = (
            ReceiptHash(str(data["historical_receipt_hash"]))
            if data.get("historical_receipt_hash")
            else None
        )
        hist_st = (
            MissionState(str(data["historical_state"])) if data.get("historical_state") else None
        )
        reason = data.get("reconciliation_reason")

        return cls(
            mission_id=m_id,
            state=st,
            snapshot_id=str(data["snapshot_id"]),
            snapshot_version=str(data["snapshot_version"]),
            evidence_ids=eids,
            as_of=as_of,
            projection_hash=p_hash,
            is_historical=False,
            historical_receipt_hash=hist_h,
            historical_state=hist_st,
            reconciliation_reason=reason,
        )


def project_current_state(
    snapshot: Any,
    *,
    historical_receipt: ReceiptProjection | None = None,
    historical_receipt_hash: ReceiptHash | None = None,
    historical_state: MissionState | None = None,
    as_of: datetime | None = None,
    reconciliation_reason: str | None = None,
    ledger: Any | None = None,
) -> CurrentStateProjection:
    """Project authoritative current truth from a mission snapshot.

    Guarantees:
    - Never lets model prose or execution response override current truth.
    - Preserves historical receipt immutability while publishing current state.
    - Historical completion (historical_state=READY) does not make current state READY if drifted.
    """
    assert_not_planner_for_current_state(snapshot, parameter_name="snapshot")
    from stilldone.snapshot import MissionSnapshot

    if not isinstance(snapshot, MissionSnapshot):
        raise TypeError(f"snapshot must be a MissionSnapshot, got {type(snapshot).__name__}")

    effective_hist_hash = historical_receipt_hash
    effective_hist_state = historical_state

    if historical_receipt is not None:
        assert_not_planner_for_current_state(
            historical_receipt, parameter_name="historical_receipt"
        )
        if not isinstance(historical_receipt, ReceiptProjection):
            raise TypeError("historical_receipt must be a ReceiptProjection")
        if historical_receipt.mission_id != snapshot.mission_id:
            raise ReceiptMismatchError(
                f"Historical receipt mission {historical_receipt.mission_id} does not "
                f"match snapshot mission {snapshot.mission_id}"
            )
        effective_hist_hash = historical_receipt.receipt_hash
        effective_hist_state = historical_receipt.state_at_projection

    if ledger is not None:
        from stilldone.ledger import MissionLedgerPort

        if not isinstance(ledger, MissionLedgerPort):
            raise TypeError("ledger must implement MissionLedgerPort")
        m_rec = ledger.get_mission(snapshot.mission_id)
        if m_rec.state != snapshot.state:
            raise ReceiptMismatchError(
                f"Snapshot state {snapshot.state.value} contradicts "
                f"ledger state {m_rec.state.value}"
            )

    norm_as_of = as_of or snapshot.created_at

    return CurrentStateProjection.create(
        mission_id=snapshot.mission_id,
        state=snapshot.state,
        snapshot_id=snapshot.snapshot_id,
        snapshot_version=snapshot.snapshot_version,
        evidence_ids=snapshot.evidence_ids,
        as_of=norm_as_of,
        historical_receipt_hash=effective_hist_hash,
        historical_state=effective_hist_state,
        reconciliation_reason=reconciliation_reason,
    )
