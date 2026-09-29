"""Provider-neutral authority contracts, approval grants, and cryptographic binding hashes.

Defines the five canonical authority classes, immutable ApprovalId, ApprovalGrant,
and SHA-256 domain-separated binding hashes for bounded delegation.
Does not perform execution or runtime policy enforcement.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from stilldone.domain.action import ActionContract, ActionId
from stilldone.domain.mission import MissionId

APPROVAL_BINDING_DOMAIN_SEPARATOR = "stilldone:approval-binding:v1"


class AuthorityClass(StrEnum):
    """The five canonical authority classes for StillDone action operations.

    Controls human approval compression boundaries.
    """

    READ_ONLY = "READ_ONLY"
    REVERSIBLE_AUTO = "REVERSIBLE_AUTO"
    REVERSIBLE_APPROVAL_REQUIRED = "REVERSIBLE_APPROVAL_REQUIRED"
    EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED = "EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED"
    IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED = "IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED"

    @property
    def requires_human_approval(self) -> bool:
        """Pure contract metadata indicating whether human approval is required by default.

        NOTE: IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED requires human approval or stronger policy,
        and is never automatically authorized simply by the presence of an approval object.
        """
        return self in {
            AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            AuthorityClass.EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED,
            AuthorityClass.IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED,
        }


@dataclass(frozen=True)
class ApprovalId:
    """Opaque UUID-backed approval identifier created by deterministic runtime code."""

    value: str

    def __post_init__(self) -> None:
        if isinstance(self.value, uuid.UUID):
            object.__setattr__(self, "value", str(self.value))
        elif isinstance(self.value, str):
            try:
                parsed = uuid.UUID(self.value)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f"Invalid ApprovalId format: {self.value!r}") from exc
            object.__setattr__(self, "value", str(parsed))
        else:
            raise TypeError("ApprovalId value must be a string or UUID instance")

    @classmethod
    def generate(cls) -> ApprovalId:
        """Create a new random approval identifier via deterministic runtime code."""
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class BindingHash:
    """Immutable value type representing a 64-character lowercase SHA-256 hex digest."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError(f"BindingHash value must be a string, got {type(self.value).__name__}")
        if len(self.value) != 64:
            raise ValueError(
                f"BindingHash must be exactly 64 hexadecimal characters, got {len(self.value)}"
            )
        for char in self.value:
            if char not in "0123456789abcdef":
                raise ValueError(f"BindingHash must be lowercase hexadecimal: {self.value!r}")

    def __str__(self) -> str:
        return self.value


def compute_approval_binding_hash(
    *,
    action: ActionContract,
    authority_class: AuthorityClass | str,
    issued_at: datetime,
    expires_at: datetime,
) -> BindingHash:
    """Compute a deterministic domain-separated SHA-256 hash binding action and approval parameters.

    Binds:
    - Domain separator ("stilldone:approval-binding:v1")
    - Mission ID
    - Action ID
    - Action Type
    - Normalized parameters
    - Complete TargetIdentity (system, resource_kind, resource_id, parent_id)
    - Authority Class
    - Issued timestamp (canonical UTC ISO string)
    - Expiry timestamp (canonical UTC ISO string)
    """
    if not isinstance(action, ActionContract):
        raise TypeError(f"action must be an ActionContract instance, got {type(action).__name__}")

    if isinstance(authority_class, str) and not isinstance(authority_class, AuthorityClass):
        try:
            auth_class = AuthorityClass(authority_class)
        except ValueError as exc:
            raise ValueError(f"Unsupported authority class: {authority_class!r}") from exc
    elif isinstance(authority_class, AuthorityClass):
        auth_class = authority_class
    else:
        raise TypeError(
            f"authority_class must be an AuthorityClass, got {type(authority_class).__name__}"
        )

    if not isinstance(issued_at, datetime):
        raise TypeError("issued_at must be a datetime instance")
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("issued_at must be timezone-aware")
    norm_issued = issued_at if issued_at.tzinfo == UTC else issued_at.astimezone(UTC)

    if not isinstance(expires_at, datetime):
        raise TypeError("expires_at must be a datetime instance")
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("expires_at must be timezone-aware")
    norm_expires = expires_at if expires_at.tzinfo == UTC else expires_at.astimezone(UTC)

    if norm_expires <= norm_issued:
        raise ValueError(
            f"expires_at ({norm_expires.isoformat()}) must be strictly later than "
            f"issued_at ({norm_issued.isoformat()})"
        )

    payload: dict[str, Any] = {
        "_domain": APPROVAL_BINDING_DOMAIN_SEPARATOR,
        "action_id": str(action.action_id),
        "action_type": str(action.action_type),
        "authority_class": str(auth_class),
        "expires_at": norm_expires.isoformat(),
        "issued_at": norm_issued.isoformat(),
        "mission_id": str(action.mission_id),
        "parameters": action.parameters.to_dict(),
        "target": {
            "parent_id": action.target.parent_id,
            "resource_id": action.target.resource_id,
            "resource_kind": str(action.target.resource_kind),
            "system": action.target.system,
        },
    }

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return BindingHash(digest)


@dataclass(frozen=True)
class ApprovalGrant:
    """Immutable provider-neutral approval contract.

    Cryptographically binds an explicit pending ActionContract to an AuthorityClass,
    validity window, and domain-separated SHA-256 binding hash.
    Does NOT store conversational prose ('yes') as authority.
    """

    approval_id: ApprovalId
    mission_id: MissionId
    action_id: ActionId
    authority_class: AuthorityClass
    issued_at: datetime
    expires_at: datetime
    binding_hash: BindingHash

    def __post_init__(self) -> None:
        if not isinstance(self.approval_id, ApprovalId):
            raise TypeError("approval_id must be an ApprovalId instance")
        if not isinstance(self.mission_id, MissionId):
            raise TypeError("mission_id must be a MissionId instance")
        if not isinstance(self.action_id, ActionId):
            raise TypeError("action_id must be an ActionId instance")

        if isinstance(self.authority_class, str) and not isinstance(
            self.authority_class, AuthorityClass
        ):
            try:
                ac = AuthorityClass(self.authority_class)
                object.__setattr__(self, "authority_class", ac)
            except ValueError as exc:
                raise ValueError(f"Unsupported authority class: {self.authority_class!r}") from exc
        elif not isinstance(self.authority_class, AuthorityClass):
            raise TypeError("authority_class must be an AuthorityClass instance")

        if not isinstance(self.issued_at, datetime):
            raise TypeError("issued_at must be a datetime instance")
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() is None:
            raise ValueError("issued_at must be timezone-aware")
        if self.issued_at.tzinfo != UTC:
            object.__setattr__(self, "issued_at", self.issued_at.astimezone(UTC))

        if not isinstance(self.expires_at, datetime):
            raise TypeError("expires_at must be a datetime instance")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        if self.expires_at.tzinfo != UTC:
            object.__setattr__(self, "expires_at", self.expires_at.astimezone(UTC))

        if self.expires_at <= self.issued_at:
            raise ValueError(
                f"expires_at ({self.expires_at.isoformat()}) must be strictly later than "
                f"issued_at ({self.issued_at.isoformat()})"
            )

        if not isinstance(self.binding_hash, BindingHash):
            raise TypeError("binding_hash must be a BindingHash instance")

    def is_expired(self, at: datetime) -> bool:
        """Deterministic pure expiry check against an explicit observation timestamp.

        Returns True if at >= expires_at. Boundary equality counts as expired.
        Rejects naive datetimes.
        """
        if not isinstance(at, datetime):
            raise TypeError(f"at must be a datetime instance, got {type(at).__name__}")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("Evaluation timestamp 'at' must be timezone-aware")

        check_dt = at if at.tzinfo == UTC else at.astimezone(UTC)
        return check_dt >= self.expires_at

    @classmethod
    def create(
        cls,
        *,
        action: ActionContract,
        authority_class: AuthorityClass | str,
        issued_at: datetime,
        expires_at: datetime,
        approval_id: ApprovalId | None = None,
    ) -> ApprovalGrant:
        """Construct an immutable ApprovalGrant cryptographically bound to an ActionContract."""
        if not isinstance(action, ActionContract):
            raise TypeError(
                f"action must be an ActionContract instance, got {type(action).__name__}"
            )

        aid = approval_id if approval_id is not None else ApprovalId.generate()
        auth_class = (
            authority_class
            if isinstance(authority_class, AuthorityClass)
            else AuthorityClass(authority_class)
        )

        b_hash = compute_approval_binding_hash(
            action=action,
            authority_class=auth_class,
            issued_at=issued_at,
            expires_at=expires_at,
        )

        return cls(
            approval_id=aid,
            mission_id=action.mission_id,
            action_id=action.action_id,
            authority_class=auth_class,
            issued_at=issued_at,
            expires_at=expires_at,
            binding_hash=b_hash,
        )


# Canonical alias for ApprovalGrant
Approval = ApprovalGrant
