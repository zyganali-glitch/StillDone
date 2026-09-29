"""Domain primitives for StillDone missions.

Defines provider-neutral mission identity, immutable mission contract,
and verbatim user-intent snapshot.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class MissionId:
    """Opaque UUID-backed mission identifier created by deterministic runtime code."""

    value: str

    def __post_init__(self) -> None:
        if isinstance(self.value, uuid.UUID):
            object.__setattr__(self, "value", str(self.value))
        elif isinstance(self.value, str):
            try:
                parsed = uuid.UUID(self.value)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f"Invalid MissionId format: {self.value!r}") from exc
            object.__setattr__(self, "value", str(parsed))
        else:
            raise TypeError("MissionId value must be a string or UUID instance")

    @classmethod
    def generate(cls) -> MissionId:
        """Create a new random mission identifier via deterministic runtime code."""
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class UserIntentSnapshot:
    """Immutable snapshot preserving user intent exactly as stated.

    Preserves user text verbatim with zero rewriting, summarization,
    normalization, or model corrections.
    """

    text: str
    captured_at: datetime
    mission_id: MissionId

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("UserIntentSnapshot text must be a string")
        if not self.text.strip():
            raise ValueError("UserIntentSnapshot text cannot be blank or whitespace-only")
        if not isinstance(self.captured_at, datetime):
            raise TypeError("captured_at must be a datetime instance")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at datetime must be timezone-aware (UTC required)")
        if self.captured_at.tzinfo != UTC:
            object.__setattr__(self, "captured_at", self.captured_at.astimezone(UTC))
        if not isinstance(self.mission_id, MissionId):
            raise TypeError("mission_id must be a MissionId instance")


@dataclass(frozen=True)
class MissionContract:
    """Immutable root contract for a StillDone mission at creation time.

    Binds runtime mission identity, verbatim user intent snapshot,
    creation timestamp, and schema version.
    """

    mission_id: MissionId
    intent: UserIntentSnapshot
    created_at: datetime
    schema_version: str = "v1"

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise TypeError("mission_id must be a MissionId instance")
        if not isinstance(self.intent, UserIntentSnapshot):
            raise TypeError("intent must be a UserIntentSnapshot instance")
        if self.intent.mission_id != self.mission_id:
            raise ValueError("Intent snapshot mission_id must match contract mission_id")
        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be a datetime instance")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at datetime must be timezone-aware (UTC required)")
        if self.created_at.tzinfo != UTC:
            object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise ValueError("schema_version must be a non-empty string")

    @classmethod
    def create(
        cls,
        text: str,
        *,
        mission_id: MissionId | None = None,
        created_at: datetime | None = None,
        schema_version: str = "v1",
    ) -> MissionContract:
        """Helper to construct an initial mission contract with a matching intent snapshot."""
        now = created_at if created_at is not None else datetime.now(UTC)
        mid = mission_id if mission_id is not None else MissionId.generate()
        intent = UserIntentSnapshot(text=text, captured_at=now, mission_id=mid)
        return cls(mission_id=mid, intent=intent, created_at=now, schema_version=schema_version)
