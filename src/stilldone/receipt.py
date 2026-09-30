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
