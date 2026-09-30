"""Deterministic evidence identity and content-addressed hashing primitive.

Defines the strongly typed EvidenceId backed by SHA-256 and domain-separated
canonical hashing. Enforces strict separation between evidence provenance and
result/verification semantics.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from stilldone.serialization import canonical_serialize, to_canonical_primitive

EVIDENCE_ID_DOMAIN_SEPARATOR: str = "stilldone:evidence:v1"


@dataclass(frozen=True)
class EvidenceId:
    """Immutable content-addressed evidence identifier backed by SHA-256."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError(f"EvidenceId value must be a string, got {type(self.value).__name__}")
        if len(self.value) != 64:
            raise ValueError(
                f"EvidenceId must be exactly 64 hexadecimal characters, got {len(self.value)}"
            )
        for char in self.value:
            if char not in "0123456789abcdef":
                raise ValueError(f"EvidenceId must be lowercase hexadecimal: {self.value!r}")

    @classmethod
    def compute(cls, content: Any, *, domain: str = EVIDENCE_ID_DOMAIN_SEPARATOR) -> EvidenceId:
        """Compute an EvidenceId from arbitrary evidence content using canonical serialization."""
        return compute_evidence_id(content, domain=domain)

    def to_canonical(self) -> str:
        """Return the canonical string representation for serialization."""
        return self.value

    def __str__(self) -> str:
        return self.value


def compute_evidence_id(content: Any, *, domain: str = EVIDENCE_ID_DOMAIN_SEPARATOR) -> EvidenceId:
    """Compute a deterministic, domain-separated SHA-256 EvidenceId for given content.

    Binds:
    - Domain separator / version string (default: 'stilldone:evidence:v1')
    - Canonical serialized content

    NOTE: EvidenceId is purely a content address. It does NOT assert that the
    evidence is verified, ready, or passing. Provenance and result semantics are
    strictly separate from evidence identity.
    """
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError("domain must be a non-empty string")

    envelope: dict[str, Any] = {
        "_domain": domain,
        "content": to_canonical_primitive(content),
    }

    serialized_bytes = canonical_serialize(envelope)
    digest = hashlib.sha256(serialized_bytes).hexdigest()
    return EvidenceId(digest)
