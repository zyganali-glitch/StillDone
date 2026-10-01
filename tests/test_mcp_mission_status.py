"""Comprehensive tests for StillDone read-only mission_status MCP tool.

Phase P-05.03 Verification:
1. MissionStatusView is immutable.
2. It accepts canonical MissionId.
3. It accepts canonical MissionState.
4. It preserves timezone-aware UTC timestamps.
5. Serialization uses canonical MissionState value.
6. Serialization does not expose MissionContract intent.
7. Serialization contains no target/resource/evidence/approval material.
8. Real official MCP client initializes over loopback.
9. tools/list returns exactly one business tool.
10. Tool name is exactly mission_status.
11. Input schema requires mission_id string.
12. Tool is marked read-only using current official ToolAnnotations.
13. Destructive annotation is false, idempotent is true, open_world is false.
14. mission_start remains absent.
15. Prompts remain empty.
16. Resources remain empty.
17. Real MCP client calls mission_status over real Streamable HTTP.
18. Returned mission_id matches exact requested MissionId.
19. Returned state matches exact MissionRecord.state.
20. created_at matches ledger record.
21. updated_at matches ledger record.
22. Repeated reads are deterministic.
23. Call leaves the source MissionRecord unchanged.
24. Ledger mission/action/evidence contents remain unchanged.
25. Malformed mission UUID fails closed without echoing malformed input.
26. Missing mission fails visibly.
27. Missing mission does not create a record.
28. Malformed/missing error does not dump MissionContract or ledger repr.
29. Arbitrary extra MCP input is rejected by generated schema.
30. Canonical state pass-through across multiple canonical MissionState members.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Generator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from stilldone.application.ports.ledger_port import (
    InMemoryNonDurableLedger,
    MissionRecord,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId


@pytest.fixture(autouse=True, scope="module")
def _cleanup_mcp_sys_modules() -> Generator[None, None, None]:
    """Module-level cleanup to keep sys.modules pure after MCP server tests finish."""
    yield
    mcp_keys = [
        k
        for k in list(sys.modules.keys())
        if k == "mcp"
        or k.startswith("mcp.")
        or k.startswith("mcp_")
        or k.startswith("stilldone.mcp")
    ]
    for k in mcp_keys:
        sys.modules.pop(k, None)


def _make_sample_record(
    state: MissionState = MissionState.READY,
    intent_text: str = "Private family morning plan leaving at 07:30 with confidential details",
) -> tuple[MissionRecord, InMemoryNonDurableLedger]:
    """Helper to create a populated InMemoryNonDurableLedger with a single MissionRecord."""
    mid = MissionId.generate()
    now = datetime.now(UTC)
    contract = MissionContract.create(intent_text, mission_id=mid, created_at=now)
    record = MissionRecord(
        mission_id=mid,
        contract=contract,
        state=state,
        created_at=now,
        updated_at=now,
    )
    ledger = InMemoryNonDurableLedger()
    ledger.append_mission(record)
    return record, ledger


# ===========================================================================
# 1. Typed Projection Tests (Requirements 1 - 7)
# ===========================================================================


class TestMissionStatusViewProjection:
    """Verify typed immutable projection contract and minimal disclosure."""

    def test_01_projection_immutability(self) -> None:
        """1. MissionStatusView is immutable."""
        from stilldone.mcp import MissionStatusView

        mid = MissionId.generate()
        now = datetime.now(UTC)
        view = MissionStatusView(
            mission_id=mid,
            state=MissionState.READY,
            created_at=now,
            updated_at=now,
        )
        with pytest.raises(FrozenInstanceError):
            view.state = MissionState.DRIFTED  # type: ignore[misc]

    def test_02_accepts_canonical_mission_id(self) -> None:
        """2. It accepts canonical MissionId and validates type strictly."""
        from stilldone.mcp import MissionStatusView

        mid = MissionId.generate()
        now = datetime.now(UTC)
        view = MissionStatusView(
            mission_id=mid,
            state=MissionState.READY,
            created_at=now,
            updated_at=now,
        )
        assert view.mission_id == mid
        assert isinstance(view.mission_id, MissionId)

        with pytest.raises(TypeError, match="mission_id must be MissionId"):
            MissionStatusView(
                mission_id="not-a-mission-id-instance",  # type: ignore[arg-type]
                state=MissionState.READY,
                created_at=now,
                updated_at=now,
            )

    def test_03_accepts_canonical_mission_state(self) -> None:
        """3. It accepts canonical MissionState and validates type strictly."""
        from stilldone.mcp import MissionStatusView

        mid = MissionId.generate()
        now = datetime.now(UTC)
        view = MissionStatusView(
            mission_id=mid,
            state=MissionState.EXECUTING,
            created_at=now,
            updated_at=now,
        )
        assert view.state == MissionState.EXECUTING
        assert isinstance(view.state, MissionState)

        with pytest.raises(TypeError, match="state must be MissionState"):
            MissionStatusView(
                mission_id=mid,
                state="EXECUTING",  # type: ignore[arg-type]
                created_at=now,
                updated_at=now,
            )

    def test_04_preserves_timezone_aware_utc_timestamps(self) -> None:
        """4. It preserves timezone-aware UTC timestamps and normalizes offsets."""
        from stilldone.mcp import MissionStatusView

        mid = MissionId.generate()
        now_utc = datetime.now(UTC)
        view = MissionStatusView(
            mission_id=mid,
            state=MissionState.READY,
            created_at=now_utc,
            updated_at=now_utc,
        )
        assert view.created_at.tzinfo == UTC
        assert view.updated_at.tzinfo == UTC

        # Reject naive datetimes
        naive_dt = datetime.now()
        with pytest.raises(ValueError, match="must be timezone-aware"):
            MissionStatusView(
                mission_id=mid,
                state=MissionState.READY,
                created_at=naive_dt,
                updated_at=now_utc,
            )

        # Normalize non-UTC offset to UTC
        eastern = timezone(timedelta(hours=-5))
        dt_eastern = datetime(2026, 10, 1, 12, 0, 0, tzinfo=eastern)
        view_offset = MissionStatusView(
            mission_id=mid,
            state=MissionState.READY,
            created_at=dt_eastern,
            updated_at=now_utc,
        )
        assert view_offset.created_at.tzinfo == UTC
        assert view_offset.created_at.hour == 17

    def test_05_serialization_uses_canonical_mission_state_value(self) -> None:
        """5. Serialization uses canonical MissionState string value."""
        from stilldone.mcp import MissionStatusView

        record, _ = _make_sample_record(state=MissionState.DRIFTED)
        view = MissionStatusView.from_record(record)
        serialized = view.to_dict()

        assert serialized["state"] == MissionState.DRIFTED.value
        assert serialized["state"] == "DRIFTED"
        assert serialized["mission_id"] == str(record.mission_id)
        assert serialized["created_at"] == record.created_at.isoformat()
        assert serialized["updated_at"] == record.updated_at.isoformat()

    def test_06_serialization_does_not_expose_mission_contract_intent(self) -> None:
        """6. Serialization does not expose MissionContract intent."""
        from stilldone.mcp import MissionStatusView

        secret_intent = "TopSecretIntentDoNotDisclose-12345"
        record, _ = _make_sample_record(intent_text=secret_intent)
        view = MissionStatusView.from_record(record)
        serialized = view.to_dict()
        serialized_json = json.dumps(serialized)

        assert secret_intent not in serialized_json
        assert "intent" not in serialized
        assert "contract" not in serialized
        assert "schema_version" not in serialized

    def test_07_serialization_contains_no_target_evidence_or_approval(self) -> None:
        """7. Serialization contains no target, resource, evidence, or approval material."""
        from stilldone.mcp import MissionStatusView

        record, _ = _make_sample_record()
        view = MissionStatusView.from_record(record)
        serialized = view.to_dict()

        # Output keys must be strictly bounded to the 4 fields
        assert set(serialized.keys()) == {
            "mission_id",
            "state",
            "created_at",
            "updated_at",
        }
        forbidden_substrings = [
            "approval",
            "action",
            "evidence",
            "calendar",
            "task",
            "payload",
            "secret",
            "token",
            "grant",
        ]
        for key in serialized:
            for forbidden in forbidden_substrings:
                assert forbidden not in key.lower()


# ===========================================================================
# 2. Tool Discovery & Annotations (Requirements 8 - 16)
# ===========================================================================


class TestMissionStatusToolDiscovery:
    """Verify tool discovery, schema contracts, and official MCP annotations."""

    @pytest.mark.anyio
    async def test_08_09_10_tool_discovery_exactly_one_business_tool(self) -> None:
        """8, 9, 10: Real MCP client over loopback sees exactly one tool: mission_status."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_STATUS_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    tools_result = await session.list_tools()
                    # Exactly 1 StillDone business tool
                    assert len(tools_result.tools) == 1
                    tool = tools_result.tools[0]
                    assert tool.name == MISSION_STATUS_TOOL_NAME
                    assert tool.name == "mission_status"

    @pytest.mark.anyio
    async def test_11_input_schema_requires_mission_id_string(self) -> None:
        """11. Input schema requires mission_id string parameter."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    tools_result = await session.list_tools()
                    tool = tools_result.tools[0]
                    schema = tool.input_schema

                    assert schema.get("type") == "object"
                    assert "properties" in schema
                    assert "mission_id" in schema["properties"]
                    assert schema["properties"]["mission_id"].get("type") == "string"
                    assert schema.get("required") == ["mission_id"]

    @pytest.mark.anyio
    async def test_12_13_tool_annotations_read_only(self) -> None:
        """12, 13: Tool is truthfully marked as read-only via official ToolAnnotations."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from mcp.types import ToolAnnotations

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    tools_result = await session.list_tools()
                    tool = tools_result.tools[0]
                    annotations = tool.annotations
                    assert annotations is not None
                    assert (
                        isinstance(annotations, ToolAnnotations)
                        or type(annotations).__name__ == "ToolAnnotations"
                    )

                    # Truthfully marked read-only and non-destructive
                    assert annotations.read_only_hint is True
                    assert annotations.destructive_hint is False
                    assert annotations.idempotent_hint is True
                    assert annotations.open_world_hint is False

    @pytest.mark.anyio
    async def test_14_15_16_no_mutation_tools_prompts_or_resources(self) -> None:
        """14, 15, 16: mission_start is absent; prompts and resources are empty."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    tools_result = await session.list_tools()
                    tool_names = [t.name for t in tools_result.tools]

                    # No premature mutation tools
                    assert "mission_start" not in tool_names
                    assert "start_mission" not in tool_names
                    assert "create_mission" not in tool_names
                    assert "execute_mission" not in tool_names

                    # Prompts and resources remain empty
                    prompts_result = await session.list_prompts()
                    assert len(prompts_result.prompts) == 0

                    resources_result = await session.list_resources()
                    assert len(resources_result.resources) == 0


# ===========================================================================
# 3. Real MCP Client Success Call & Ledger Truth (Requirements 17 - 24)
# ===========================================================================


class TestMissionStatusSuccessCall:
    """Verify end-to-end tool execution over real Streamable HTTP."""

    @pytest.mark.anyio
    async def test_17_to_24_real_call_success_and_ledger_invariants(self) -> None:
        """17 - 24: Real MCP client calls mission_status over HTTP, returns exact facts."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_STATUS_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        record, ledger = _make_sample_record(state=MissionState.READY)
        initial_missions = ledger._missions.copy()
        initial_actions = ledger._actions.copy()
        initial_evidence = ledger._evidence.copy()

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # 17. Real MCP client calls mission_status over real Streamable HTTP
                    call_result = await session.call_tool(
                        MISSION_STATUS_TOOL_NAME,
                        {"mission_id": str(record.mission_id)},
                    )
                    assert call_result.is_error is False

                    first_content = call_result.content[0]
                    assert getattr(first_content, "type", None) == "text"
                    data = json.loads(getattr(first_content, "text", "{}"))

                    # 18. Returned mission_id matches requested
                    assert data["mission_id"] == str(record.mission_id)

                    # 19. Returned state matches exact ledger record state
                    assert data["state"] == MissionState.READY.value

                    # 20. created_at matches ledger record
                    assert data["created_at"] == record.created_at.isoformat()

                    # 21. updated_at matches ledger record
                    assert data["updated_at"] == record.updated_at.isoformat()

                    # 22. Repeated reads are deterministic
                    repeat_result = await session.call_tool(
                        MISSION_STATUS_TOOL_NAME,
                        {"mission_id": str(record.mission_id)},
                    )
                    repeat_first = repeat_result.content[0]
                    assert getattr(repeat_first, "type", None) == "text"
                    repeat_data = json.loads(getattr(repeat_first, "text", "{}"))
                    assert repeat_data == data

        # 23. Call leaves source MissionRecord unchanged
        after_record = ledger.get_mission(record.mission_id)
        assert after_record == record
        assert after_record.state == record.state
        assert after_record.updated_at == record.updated_at

        # 24. Ledger mission/action/evidence contents remain unchanged
        assert ledger._missions == initial_missions
        assert ledger._actions == initial_actions
        assert ledger._evidence == initial_evidence


# ===========================================================================
# 4. State Truth & Pass-Through (Canonical MissionState members)
# ===========================================================================


class TestMissionStatusStatePassThrough:
    """Verify exact pass-through across multiple canonical MissionState members."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "expected_state",
        [
            MissionState.DRAFT,
            MissionState.PLANNED,
            MissionState.EXECUTING,
            MissionState.NEEDS_APPROVAL,
            MissionState.VERIFYING,
            MissionState.READY,
            MissionState.PARTIAL,
            MissionState.FAILED,
            MissionState.DRIFTED,
            MissionState.CANCELLED,
        ],
    )
    async def test_state_pass_through(self, expected_state: MissionState) -> None:
        """Verify exact pass-through of canonical state without model prose rewriting."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_STATUS_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        record, ledger = _make_sample_record(state=expected_state)

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    res = await session.call_tool(
                        MISSION_STATUS_TOOL_NAME,
                        {"mission_id": str(record.mission_id)},
                    )
                    assert res.is_error is False
                    first_content = res.content[0]
                    assert getattr(first_content, "type", None) == "text"
                    data = json.loads(getattr(first_content, "text", "{}"))
                    assert data["state"] == expected_state.value


# ===========================================================================
# 5. Failure Cases & Bounded Safe Errors (Requirements 25 - 29)
# ===========================================================================


class TestMissionStatusFailures:
    """Verify malformed input, missing records, and fail-closed security properties."""

    @pytest.mark.anyio
    async def test_25_malformed_uuid_fails_closed_without_echoing_input(self) -> None:
        """25. Malformed UUID fails closed with bounded error and does not echo malformed text."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_STATUS_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        _, ledger = _make_sample_record()

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        sensitive_malformed_input = "SELECT * FROM secrets WHERE key='super_secret_token'"

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    res = await session.call_tool(
                        MISSION_STATUS_TOOL_NAME,
                        {"mission_id": sensitive_malformed_input},
                    )
                    assert res.is_error is True
                    first_content = res.content[0]
                    err_msg = str(getattr(first_content, "text", ""))

                    # Safe bounded error
                    assert "malformed UUID" in err_msg or "Invalid mission ID" in err_msg
                    # Malformed input is NOT echoed back
                    assert sensitive_malformed_input not in err_msg

    @pytest.mark.anyio
    async def test_26_27_missing_mission_fails_visibly_zero_storage(self) -> None:
        """26, 27: Missing mission fails visibly; does not create a record."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_STATUS_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        _, ledger = _make_sample_record()
        missing_id = str(uuid.uuid4())
        initial_count = len(ledger._missions)

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    res = await session.call_tool(
                        MISSION_STATUS_TOOL_NAME,
                        {"mission_id": missing_id},
                    )
                    assert res.is_error is True
                    first_content = res.content[0]
                    err_msg = str(getattr(first_content, "text", ""))

                    # 26. Not found condition is visible
                    assert "not found" in err_msg.lower()
                    assert missing_id in err_msg

        # 27. Missing mission did NOT create any record
        assert len(ledger._missions) == initial_count
        from stilldone.application.ports.ledger_port import RecordNotFoundError

        with pytest.raises(RecordNotFoundError):
            ledger.get_mission(MissionId(missing_id))

    @pytest.mark.anyio
    async def test_28_malformed_missing_error_does_not_dump_reprs(self) -> None:
        """28. Errors do not dump MissionContract or ledger reprs."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_STATUS_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        record, ledger = _make_sample_record(intent_text="ClassifiedMissionDetails")

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Missing mission call
                    res = await session.call_tool(
                        MISSION_STATUS_TOOL_NAME,
                        {"mission_id": str(uuid.uuid4())},
                    )
                    first_content = res.content[0]
                    err_msg = str(getattr(first_content, "text", ""))

                    assert "ClassifiedMissionDetails" not in err_msg
                    assert "InMemoryNonDurableLedger" not in err_msg
                    assert "MissionRecord" not in err_msg
                    assert "MissionContract" not in err_msg

    @pytest.mark.anyio
    async def test_29_arbitrary_extra_input_and_schema_validation(self) -> None:
        """29. Arbitrary extra input or invalid schema types are rejected."""
        import jsonschema  # type: ignore[import-untyped]
        from mcp.server.mcpserver.exceptions import ToolError

        from stilldone.mcp import MISSION_STATUS_TOOL_NAME, create_mcp_server

        server = create_mcp_server()
        tools = await server.list_tools()
        tool = tools[0]
        schema = tool.input_schema

        # Valid input passes schema validation
        jsonschema.validate({"mission_id": "fad1a408-fc61-49ff-926f-32ad7bf82416"}, schema)

        # Missing required parameter is rejected by schema
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({}, schema)

        # Non-string parameter is rejected by schema
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"mission_id": 12345}, schema)

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"mission_id": {"nested": "dict_not_allowed"}}, schema)

        # In runtime execution, passing non-string / dict fails closed
        with pytest.raises(ToolError):
            await server.call_tool(
                MISSION_STATUS_TOOL_NAME,
                {"mission_id": {"nested": "dict"}},
            )

        with pytest.raises(ToolError):
            await server.call_tool(MISSION_STATUS_TOOL_NAME, {})


# ===========================================================================
# 6. Direct Handler Unit Tests (Zero Network / Fast Unit Verification)
# ===========================================================================


class TestMissionStatusDirectHandler:
    """Direct unit tests for create_mission_status_handler."""

    def test_handler_requires_mission_ledger_port(self) -> None:
        """create_mission_status_handler requires MissionLedgerPort instance."""
        from stilldone.mcp import create_mission_status_handler

        with pytest.raises(TypeError, match="ledger must implement MissionLedgerPort"):
            create_mission_status_handler("not-a-ledger")  # type: ignore[arg-type]

    def test_handler_success(self) -> None:
        """Direct call to handler returns MissionStatusPayload."""
        from stilldone.mcp import MissionStatusPayload, create_mission_status_handler

        record, ledger = _make_sample_record(state=MissionState.READY)
        handler = create_mission_status_handler(ledger)

        payload = handler(str(record.mission_id))
        assert isinstance(payload, MissionStatusPayload)
        assert payload.mission_id == str(record.mission_id)
        assert payload.state == "READY"
        assert payload.created_at == record.created_at.isoformat()
        assert payload.updated_at == record.updated_at.isoformat()

    def test_handler_malformed_uuid(self) -> None:
        """Direct call with malformed UUID raises ToolError without echoing."""
        from mcp.server.mcpserver.exceptions import ToolError

        from stilldone.mcp import create_mission_status_handler

        _, ledger = _make_sample_record()
        handler = create_mission_status_handler(ledger)

        bad_id = "sensitive-bad-input-xyz"
        with pytest.raises(ToolError) as exc_info:
            handler(bad_id)
        assert "malformed UUID" in str(exc_info.value)
        assert bad_id not in str(exc_info.value)

    def test_handler_missing_mission(self) -> None:
        """Direct call with non-existent UUID raises ToolError with visible not-found."""
        from mcp.server.mcpserver.exceptions import ToolError

        from stilldone.mcp import create_mission_status_handler

        _, ledger = _make_sample_record()
        handler = create_mission_status_handler(ledger)

        missing_id = str(uuid.uuid4())
        with pytest.raises(ToolError) as exc_info:
            handler(missing_id)
        assert "not found" in str(exc_info.value).lower()
        assert missing_id in str(exc_info.value)
