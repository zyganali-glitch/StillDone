"""Mission-start MCP tool and typed projection contracts for StillDone.

Phase P-05.04:
- Exposes StillDone's second business MCP tool: 'mission_start'.
- Bounded, typed projection creating a new mission in local DRAFT state.
- Canonical creation flow:
    verbatim intent -> runtime MissionId -> UserIntentSnapshot -> MissionContract ->
    MissionRecord(state=DRAFT) -> MissionLedgerPort.append_mission()
- Mutates local runtime ledger ONLY by appending exactly one MissionRecord.
- Zero live/external mutation: no Google, no Tasks, no AWS, no Bedrock/model, no provider calls.
- Privacy minimization: response returns only mission_id, state, created_at.
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
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import (
    MissionContract,
    MissionId,
    UserIntentSnapshot,
)
from stilldone.mcp.strict_input import enforce_strict_input_contract

MISSION_START_TOOL_NAME: Final[str] = "mission_start"
MISSION_START_TOOL_DESCRIPTION: Final[str] = (
    "Create and start a new StillDone mission in local DRAFT state from bounded "
    "user intent, without executing, planning, or mutating external systems."
)
MISSION_START_ANNOTATIONS: Final[ToolAnnotations] = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
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
class MissionStartPayload:
    """Bounded primitive wire representation of mission start response.

    Derives typed MCP output schema from dataclass fields.
    """

    mission_id: str
    state: str
    created_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, str):
            raise TypeError("mission_id must be a string")
        if not isinstance(self.state, str):
            raise TypeError("state must be a string")
        if not isinstance(self.created_at, str):
            raise TypeError("created_at must be a string")

    def to_dict(self) -> dict[str, str]:
        """Convert payload to a dictionary."""
        return {
            "mission_id": self.mission_id,
            "state": self.state,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class MissionStartView:
    """Immutable view of a newly started StillDone mission.

    Exposes the minimum bounded start projection without disclosing
    user intent text, action contracts, target resource IDs, approval grants,
    evidence payloads, or provider captures.
    """

    mission_id: MissionId
    state: MissionState
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(f"mission_id must be MissionId, got {type(self.mission_id).__name__}")
        if not isinstance(self.state, MissionState):
            raise TypeError(f"state must be MissionState, got {type(self.state).__name__}")
        norm_created = _normalize_utc(self.created_at, "created_at")
        object.__setattr__(self, "created_at", norm_created)

    @classmethod
    def from_record(cls, record: MissionRecord) -> MissionStartView:
        """Create a start projection from a canonical MissionRecord."""
        if not isinstance(record, MissionRecord):
            raise TypeError(f"record must be MissionRecord, got {type(record).__name__}")
        return cls(
            mission_id=record.mission_id,
            state=record.state,
            created_at=record.created_at,
        )

    def to_dict(self) -> dict[str, str]:
        """Serialize to bounded primitive wire representation."""
        return {
            "mission_id": str(self.mission_id),
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
        }

    def serialize(self) -> dict[str, str]:
        """Alias for to_dict() for canonical serialization interface."""
        return self.to_dict()

    def to_payload(self) -> MissionStartPayload:
        """Project into bounded wire dataclass."""
        return MissionStartPayload(
            mission_id=str(self.mission_id),
            state=self.state.value,
            created_at=self.created_at.isoformat(),
        )


def create_mission_start_handler(
    ledger: MissionLedgerPort,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Callable[[str], MissionStartPayload]:
    """Create a mission_start MCP tool handler bound to an explicit ledger."""
    if not isinstance(ledger, MissionLedgerPort):
        raise TypeError(f"ledger must implement MissionLedgerPort, got {type(ledger).__name__}")

    def mission_start(intent: str) -> MissionStartPayload:
        """Start a new StillDone mission in DRAFT state from user intent."""
        if not isinstance(intent, str):
            raise ToolError("Invalid intent: must be a string")
        if not intent.strip():
            raise ToolError("Invalid intent: cannot be blank or whitespace-only")

        raw_now = clock() if clock is not None else datetime.now(UTC)
        now = _normalize_utc(raw_now, "created_at")
        mid = MissionId.generate()

        try:
            intent_snapshot = UserIntentSnapshot(text=intent, captured_at=now, mission_id=mid)
            contract = MissionContract(
                mission_id=mid,
                intent=intent_snapshot,
                created_at=now,
                schema_version="v1",
            )
            record = MissionRecord(
                mission_id=mid,
                contract=contract,
                state=MissionState.DRAFT,
                created_at=now,
                updated_at=now,
            )
            ledger.append_mission(record)
        except (ValueError, TypeError):
            # Fail closed with safe tool error without leaking sensitive user text
            raise ToolError("Failed to initialize mission contract") from None

        view = MissionStartView.from_record(record)
        return view.to_payload()

    return mission_start


def register_mission_start_tool(
    server: MCPServer,
    ledger: MissionLedgerPort,
    *,
    clock: Callable[[], datetime] | None = None,
) -> None:
    """Register the canonical mission_start tool on the official MCPServer."""
    if not (isinstance(server, MCPServer) or type(server).__name__ == "MCPServer"):
        raise TypeError(f"server must be MCPServer, got {type(server).__name__}")
    if not isinstance(ledger, MissionLedgerPort):
        raise TypeError(f"ledger must implement MissionLedgerPort, got {type(ledger).__name__}")

    annotations_dict = {
        "read_only_hint": MISSION_START_ANNOTATIONS.read_only_hint,
        "destructive_hint": MISSION_START_ANNOTATIONS.destructive_hint,
        "idempotent_hint": MISSION_START_ANNOTATIONS.idempotent_hint,
        "open_world_hint": MISSION_START_ANNOTATIONS.open_world_hint,
    }
    handler = create_mission_start_handler(ledger, clock=clock)
    server.add_tool(
        handler,
        name=MISSION_START_TOOL_NAME,
        description=MISSION_START_TOOL_DESCRIPTION,
        annotations=annotations_dict,  # type: ignore[arg-type]
    )
    enforce_strict_input_contract(server, MISSION_START_TOOL_NAME)
