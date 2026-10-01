"""Read-only mission-status MCP tool and typed projection contracts for StillDone.

Phase P-05.03:
- Exposes StillDone's first business MCP tool: 'mission_status'.
- Bounded, typed, read-only projection over canonical MissionLedgerPort.
- Canonical truth source is MissionLedgerPort.get_mission(MissionId) -> MissionRecord.
- MCP layer is strictly a read projection and does NOT create a second mission-state truth.
- Zero mission mutation, zero provider calls, zero model calls.
- Privacy minimization: returns only mission_id, state, created_at, updated_at.
  Excludes user intent, action parameters, target IDs, evidence payloads, secrets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from stilldone.application.ports.ledger_port import (
    MissionLedgerPort,
    MissionRecord,
    RecordNotFoundError,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionId

MISSION_STATUS_TOOL_NAME: Final[str] = "mission_status"
MISSION_STATUS_TOOL_DESCRIPTION: Final[str] = (
    "Return the current locally recorded StillDone mission state without "
    "executing, mutating, approving, reconciling, verifying, or refreshing anything."
)
MISSION_STATUS_ANNOTATIONS: Final[ToolAnnotations] = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _normalize_utc(dt: datetime, name: str) -> datetime:
    """Validate and normalize a datetime to timezone-aware UTC."""
    if not isinstance(dt, datetime):
        raise TypeError(f"{name} must be a datetime instance, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware (UTC required)")
    return dt if dt.tzinfo == UTC else dt.astimezone(UTC)


@dataclass(frozen=True)
class MissionStatusPayload:
    """Bounded primitive wire representation of mission status.

    Derives typed MCP output schema from dataclass fields.
    """

    mission_id: str
    state: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, str):
            raise TypeError("mission_id must be a string")
        if not isinstance(self.state, str):
            raise TypeError("state must be a string")
        if not isinstance(self.created_at, str):
            raise TypeError("created_at must be a string")
        if not isinstance(self.updated_at, str):
            raise TypeError("updated_at must be a string")

    def to_dict(self) -> dict[str, str]:
        """Convert payload to a dictionary."""
        return {
            "mission_id": self.mission_id,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class MissionStatusView:
    """Immutable read-only status projection for a StillDone mission.

    Exposes the minimum bounded mission status record without disclosing
    user intent text, action contracts, target resource IDs, approval grants,
    evidence payloads, or provider captures.
    """

    mission_id: MissionId
    state: MissionState
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(self.mission_id).__name__}")
        if not isinstance(self.state, MissionState):
            raise TypeError(f"state must be MissionState, got {type(self.state).__name__}")
        norm_created = _normalize_utc(self.created_at, "created_at")
        norm_updated = _normalize_utc(self.updated_at, "updated_at")
        object.__setattr__(self, "created_at", norm_created)
        object.__setattr__(self, "updated_at", norm_updated)

    @classmethod
    def from_record(cls, record: MissionRecord) -> MissionStatusView:
        """Create a status projection from a canonical MissionRecord."""
        if not isinstance(record, MissionRecord):
            raise TypeError(f"record must be MissionRecord, got {type(record).__name__}")
        return cls(
            mission_id=record.mission_id,
            state=record.state,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def to_dict(self) -> dict[str, str]:
        """Serialize to bounded primitive wire representation."""
        return {
            "mission_id": str(self.mission_id),
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def serialize(self) -> dict[str, str]:
        """Alias for to_dict() for canonical serialization interface."""
        return self.to_dict()

    def to_payload(self) -> MissionStatusPayload:
        """Project into bounded wire dataclass."""
        return MissionStatusPayload(
            mission_id=str(self.mission_id),
            state=self.state.value,
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
        )


def create_mission_status_handler(
    ledger: MissionLedgerPort,
) -> Callable[[str], MissionStatusPayload]:
    """Create a bounded read-only mission_status MCP tool handler bound to an explicit ledger."""
    if not isinstance(ledger, MissionLedgerPort):
        raise TypeError(f"ledger must implement MissionLedgerPort, got {type(ledger).__name__}")

    def mission_status(mission_id: str) -> MissionStatusPayload:
        """Return current locally recorded mission state without mutation or execution."""
        if not isinstance(mission_id, str):
            raise ToolError("Invalid mission ID: must be a string")

        try:
            canonical_id = MissionId(mission_id)
        except (ValueError, TypeError):
            # Fail closed with bounded safe tool error without echoing malformed plaintext
            raise ToolError("Invalid mission ID: malformed UUID format") from None

        try:
            record = ledger.get_mission(canonical_id)
        except RecordNotFoundError:
            raise ToolError(f"Mission not found: {canonical_id}") from None

        view = MissionStatusView.from_record(record)
        return view.to_payload()

    return mission_status


def register_mission_status_tool(server: MCPServer, ledger: MissionLedgerPort) -> None:
    """Register the single canonical mission_status tool on the official MCPServer."""
    if not isinstance(server, MCPServer):
        raise TypeError(f"server must be MCPServer, got {type(server).__name__}")
    if not isinstance(ledger, MissionLedgerPort):
        raise TypeError(f"ledger must implement MissionLedgerPort, got {type(ledger).__name__}")

    handler = create_mission_status_handler(ledger)
    server.add_tool(
        handler,
        name=MISSION_STATUS_TOOL_NAME,
        description=MISSION_STATUS_TOOL_DESCRIPTION,
        annotations=MISSION_STATUS_ANNOTATIONS,
    )
