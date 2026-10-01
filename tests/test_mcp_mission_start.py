"""Tests for StillDone mission_start MCP tool and typed projection contracts.

Phase P-05.04 Verification:
1. tools/list returns exactly 2 StillDone tools.
2. Exact names are: mission_status, mission_start.
3. No create_mission/start_mission/execute_mission alias exists.
4. mission_start input schema contains only 'intent'.
5. intent is required string.
6. additionalProperties is false.
7. Caller cannot supply mission_id.
8. Caller cannot supply state.
9. Extra key fails JSON Schema validation.
10. Extra key fails real runtime validation.
11. Extra sensitive value is redacted from error.
12. mission_start readOnlyHint is false.
13. destructiveHint is false.
14. idempotentHint is false.
15. openWorldHint is false.
16. mission_status retains its existing read-only annotations unchanged.
17. Successful call generates canonical MissionId.
18. Exact input text is preserved in stored MissionRecord.contract.intent.text.
19. Initial stored state is exactly MissionState.DRAFT.
20. captured_at / contract.created_at / record.created_at / record.updated_at
    use same initial UTC instant.
21. MissionRecord is appended exactly once.
22. Zero ActionRecord is created.
23. Zero EvidenceRecord is created.
24. Zero ApprovalGrant is created.
25. Zero ExecutionAttempt is created.
26. Response contains only bounded start fields.
27. Response does not contain raw intent.
28. Response does not contain contract repr.
29. Response does not contain provider/action/evidence/approval fields.
30. Output state is exactly DRAFT.
31. Real mission_start returns mission ID.
32. Immediate real mission_status on same server/ledger finds it.
33. mission_status returns exact DRAFT.
34. mission_status timestamps match canonical ledger record.
35. Cross-tool read does not cause further mutation.
36. Blank intent fails.
37. Whitespace-only intent fails.
38. Non-string intent fails.
39. Extra property fails.
40. All rejected calls leave mission count unchanged.
41. Rejected call creates no action/evidence.
42. Sensitive rejected intent/extra value is not echoed in bounded error text.
43. Two accepted identical-intent calls produce two distinct MissionIds.
44. Both records retain the same exact intent text independently.
45. Tool does NOT advertise idempotency.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
import uuid
from collections.abc import Generator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import jsonschema  # type: ignore[import-untyped]
import pytest

from stilldone.application.ports.ledger_port import (
    InMemoryNonDurableLedger,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import (
    MissionId,
)


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


# ===========================================================================
# 1. Discovery, Tool List & Schema Tests (Items 1-11)
# ===========================================================================


class TestMissionStartDiscoveryAndSchema:
    """Verify tool discovery, schema strictness, and input contract."""

    @pytest.mark.anyio
    async def test_01_02_03_tool_discovery_and_no_aliases(self) -> None:
        """1, 2, 3: Exactly 2 tools discovered (mission_status, mission_start); no aliases."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
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

                    # 1. Exactly 2 StillDone business tools
                    assert len(tools_result.tools) == 2, (
                        f"Expected exactly 2 tools, got: {[t.name for t in tools_result.tools]}"
                    )

                    tool_names = [t.name for t in tools_result.tools]

                    # 2. Exact names
                    assert MISSION_STATUS_TOOL_NAME in tool_names
                    assert MISSION_START_TOOL_NAME in tool_names
                    assert set(tool_names) == {"mission_status", "mission_start"}

                    # 3. No aliases
                    assert "start_mission" not in tool_names
                    assert "create_mission" not in tool_names
                    assert "execute_mission" not in tool_names

    @pytest.mark.anyio
    async def test_04_05_06_input_schema_intent_only(self) -> None:
        """4, 5, 6: Input schema contains only 'intent', required string,
        additionalProperties=False."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
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

                    tool = next(t for t in tools_result.tools if t.name == MISSION_START_TOOL_NAME)
                    schema = tool.input_schema

                    # 4. Schema type is object, properties contains only 'intent'
                    assert schema.get("type") == "object"
                    props = schema.get("properties", {})
                    assert list(props.keys()) == ["intent"]

                    # 5. intent is required string
                    assert props["intent"].get("type") == "string"
                    assert schema.get("required") == ["intent"]

                    # 6. additionalProperties is explicitly False
                    assert schema.get("additionalProperties") is False

    @pytest.mark.anyio
    async def test_07_08_09_caller_cannot_supply_mission_id_or_state(self) -> None:
        """7, 8, 9: Caller cannot supply mission_id or state; extra keys fail JSON schema."""
        from stilldone.mcp import MISSION_START_TOOL_NAME, create_mcp_server

        server = create_mcp_server()
        tools = await server.list_tools()
        tool = next(t for t in tools if t.name == MISSION_START_TOOL_NAME)
        schema = tool.input_schema

        # Valid input passes
        jsonschema.validate({"intent": "Get my family ready for tomorrow morning."}, schema)

        # 7. Supplying mission_id fails schema
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {
                    "intent": "Get my family ready",
                    "mission_id": str(uuid.uuid4()),
                },
                schema,
            )

        # 8. Supplying state fails schema
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {
                    "intent": "Get my family ready",
                    "state": "READY",
                },
                schema,
            )

        # 9. Arbitrary extra keys fail schema
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {
                    "intent": "Get my family ready",
                    "actions": ["calendar.read"],
                },
                schema,
            )

    @pytest.mark.anyio
    async def test_10_11_runtime_validation_fails_closed_and_redacts(self) -> None:
        """10, 11: Extra key fails runtime validation; sensitive extra value is redacted."""
        from mcp.server.mcpserver.exceptions import ToolError

        from stilldone.mcp import MISSION_START_TOOL_NAME, create_mcp_server

        secret_extra = "SUPER_SECRET_TOKEN_DO_NOT_LEAK"
        server = create_mcp_server()

        with pytest.raises(ToolError) as exc_info:
            await server.call_tool(
                MISSION_START_TOOL_NAME,
                {
                    "intent": "Get my family ready",
                    "forbidden_extra_key": secret_extra,
                },
            )

        err_msg = str(exc_info.value)
        # 10. Failed runtime validation
        assert "forbidden_extra_key" in err_msg
        # 11. Sensitive value redacted
        assert secret_extra not in err_msg
        assert "[REDACTED]" in err_msg


# ===========================================================================
# 2. Tool Annotations Tests (Items 12-16)
# ===========================================================================


class TestMissionStartAnnotations:
    """Verify truthful tool annotations."""

    @pytest.mark.anyio
    async def test_12_13_14_15_start_annotations_truthful(self) -> None:
        """12-15: mission_start has read_only=False, destructive=False,
        idempotent=False, open_world=False."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
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

                    tool = next(t for t in tools_result.tools if t.name == MISSION_START_TOOL_NAME)
                    ann = tool.annotations
                    assert ann is not None

                    # 12. read_only_hint is False
                    assert ann.read_only_hint is False
                    # 13. destructive_hint is False
                    assert ann.destructive_hint is False
                    # 14. idempotent_hint is False
                    assert ann.idempotent_hint is False
                    # 15. open_world_hint is False
                    assert ann.open_world_hint is False

    @pytest.mark.anyio
    async def test_16_mission_status_annotations_unchanged(self) -> None:
        """16: mission_status retains its read-only annotations unchanged."""
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

                    tool = next(t for t in tools_result.tools if t.name == MISSION_STATUS_TOOL_NAME)
                    ann = tool.annotations
                    assert ann is not None

                    assert ann.read_only_hint is True
                    assert ann.destructive_hint is False
                    assert ann.idempotent_hint is True
                    assert ann.open_world_hint is False


# ===========================================================================
# 3. Domain Creation & Ledger State Tests (Items 17-25)
# ===========================================================================


class TestMissionStartDomainCreation:
    """Verify canonical domain creation path and ledger record mutation."""

    @pytest.mark.anyio
    async def test_17_to_25_canonical_creation_flow(self) -> None:
        """17-25: Canonical creation generates MissionId, exact intent, DRAFT,
        identical timestamps, exactly 1 MissionRecord, 0 action/evidence/approval."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        ledger = InMemoryNonDurableLedger()
        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        sentinel_intent = "Prepare backpacks and set alarm for 6:45 AM verbatim."

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    res = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {"intent": sentinel_intent},
                    )

                    assert res.is_error is False
                    payload_data = json.loads(str(getattr(res.content[0], "text", "")))

                    # 17. Valid canonical UUID MissionId generated
                    returned_id_str = payload_data["mission_id"]
                    mid = MissionId(returned_id_str)
                    assert str(mid) == returned_id_str

                    # 21. MissionRecord appended exactly once
                    assert len(ledger._missions) == 1
                    stored_record = ledger.get_mission(mid)
                    assert stored_record is not None

                    # 18. Exact input text preserved in contract.intent.text
                    assert stored_record.contract.intent.text == sentinel_intent
                    assert stored_record.contract.intent.mission_id == mid

                    # 19. Initial stored state is exactly MissionState.DRAFT
                    assert stored_record.state == MissionState.DRAFT

                    # 20. captured_at, contract.created_at, record.created_at,
                    # record.updated_at match
                    t_captured = stored_record.contract.intent.captured_at
                    t_contract = stored_record.contract.created_at
                    t_rec_created = stored_record.created_at
                    t_rec_updated = stored_record.updated_at

                    assert t_captured == t_contract == t_rec_created == t_rec_updated
                    assert t_captured.tzinfo == UTC

                    # 22. Zero ActionRecord created
                    assert len(ledger._actions) == 0
                    assert len(ledger.get_actions_for_mission(mid)) == 0

                    # 23. Zero EvidenceRecord created
                    assert len(ledger._evidence) == 0
                    assert len(ledger.get_evidence_for_mission(mid)) == 0

                    # 24, 25. Zero approval grant or execution attempt in ledger or record
                    assert not hasattr(stored_record, "approval_grant")
                    assert not hasattr(stored_record, "execution_attempt")


# ===========================================================================
# 4. Output Contract & Privacy Tests (Items 26-30)
# ===========================================================================


class TestMissionStartOutputPrivacy:
    """Verify output contract privacy minimization and schema bounds."""

    @pytest.mark.anyio
    async def test_26_to_30_output_privacy(self) -> None:
        """26-30: Response has only bounded fields; no raw intent, contract repr,
        provider/action fields; state is DRAFT."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        ledger = InMemoryNonDurableLedger()
        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        sensitive_intent = "PRIVATE_HEALTH_APPOINTMENT_SCHEDULE_2026_CONFIDENTIAL"

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    res = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {"intent": sensitive_intent},
                    )

                    assert res.is_error is False
                    raw_text = str(getattr(res.content[0], "text", ""))
                    data = json.loads(raw_text)

                    # 26. Response contains only bounded start fields: mission_id, state, created_at
                    assert set(data.keys()) == {"mission_id", "state", "created_at"}

                    # 27. Raw text does not contain sensitive intent
                    assert sensitive_intent not in raw_text

                    # 28. Does not contain contract repr
                    assert "MissionContract" not in raw_text
                    assert "UserIntentSnapshot" not in raw_text
                    assert "schema_version" not in raw_text

                    # 29. Does not contain provider/action/evidence/approval fields
                    for forbidden in [
                        "action",
                        "actions",
                        "evidence",
                        "approval",
                        "google",
                        "aws",
                        "tasks",
                        "calendar",
                        "provider",
                        "payload",
                    ]:
                        assert forbidden not in data

                    # 30. Output state is exactly DRAFT
                    assert data["state"] == "DRAFT"


# ===========================================================================
# 5. Cross-Tool Truth & Shared Ledger Tests (Items 31-35)
# ===========================================================================


class TestMissionStartCrossToolTruth:
    """Verify shared ledger integration between mission_start and mission_status."""

    @pytest.mark.anyio
    async def test_31_to_35_mission_start_then_mission_status(self) -> None:
        """31-35: mission_start returns ID -> mission_status returns DRAFT with
        matching timestamps; no extra mutation."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
            MISSION_STATUS_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        ledger = InMemoryNonDurableLedger()
        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # 31. mission_start returns mission ID
                    start_res = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {"intent": "Prepare travel bag for weekend trip"},
                    )
                    assert start_res.is_error is False
                    start_data = json.loads(str(getattr(start_res.content[0], "text", "")))
                    mid_str = start_data["mission_id"]

                    # 32. Immediate mission_status call finds it on the same server/ledger
                    status_res = await session.call_tool(
                        MISSION_STATUS_TOOL_NAME,
                        {"mission_id": mid_str},
                    )
                    assert status_res.is_error is False
                    status_data = json.loads(str(getattr(status_res.content[0], "text", "")))

                    # 33. mission_status returns exact DRAFT
                    assert status_data["state"] == "DRAFT"
                    assert status_data["mission_id"] == mid_str

                    # 34. mission_status timestamps match canonical ledger record
                    record = ledger.get_mission(MissionId(mid_str))
                    assert status_data["created_at"] == record.created_at.isoformat()
                    assert status_data["updated_at"] == record.updated_at.isoformat()
                    assert start_data["created_at"] == record.created_at.isoformat()

                    # 35. Cross-tool read causes no further mutation
                    assert len(ledger._missions) == 1
                    assert len(ledger._actions) == 0
                    assert len(ledger._evidence) == 0


# ===========================================================================
# 6. Failure Semantics & Zero Mutation Tests (Items 36-42)
# ===========================================================================


class TestMissionStartFailures:
    """Verify fail-closed error semantics and zero mutation on rejection."""

    @pytest.mark.anyio
    async def test_36_37_blank_and_whitespace_intent_fails(self) -> None:
        """36, 37, 40: Blank and whitespace-only intent fail closed; 0 missions added."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        ledger = InMemoryNonDurableLedger()
        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # 36. Blank intent
                    res_blank = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {"intent": ""},
                    )
                    assert res_blank.is_error is True
                    assert "blank" in str(getattr(res_blank.content[0], "text", "")).lower()

                    # 37. Whitespace-only intent
                    res_ws = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {"intent": "   \n\t  "},
                    )
                    assert res_ws.is_error is True
                    assert "blank" in str(getattr(res_ws.content[0], "text", "")).lower()

                    # 40, 41. Zero missions/actions/evidence
                    assert len(ledger._missions) == 0
                    assert len(ledger._actions) == 0
                    assert len(ledger._evidence) == 0

    @pytest.mark.anyio
    async def test_38_non_string_intent_fails(self) -> None:
        """38: Non-string intent fails closed through schema/runtime validation with value
        redaction."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        ledger = InMemoryNonDurableLedger()
        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        sentinel_secret_dict = "SENTINEL_PRIVATE_INTENT_TOKEN_DICT_98765"
        sentinel_secret_list = "SENTINEL_PRIVATE_INTENT_TOKEN_LIST_43210"

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # 1, 2, 3, 4: dict containing secret sentinel is rejected without leak;
                    # [REDACTED] appears; field name 'intent' may remain visible
                    res_dict = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {"intent": {"secret": sentinel_secret_dict}},
                    )
                    assert res_dict.is_error is True
                    err_dict_text = str(getattr(res_dict.content[0], "text", ""))
                    assert sentinel_secret_dict not in err_dict_text
                    assert "[REDACTED]" in err_dict_text
                    assert "intent" in err_dict_text

                    # 5, 6: ledger mission, action, and evidence counts remain unchanged (0)
                    assert len(ledger._missions) == 0
                    assert len(ledger._actions) == 0
                    assert len(ledger._evidence) == 0

                    # 7: list containing secret sentinel is likewise rejected without leak
                    res_list = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {"intent": [sentinel_secret_list, "extra_item"]},
                    )
                    assert res_list.is_error is True
                    err_list_text = str(getattr(res_list.content[0], "text", ""))
                    assert sentinel_secret_list not in err_list_text
                    assert "[REDACTED]" in err_list_text
                    assert "intent" in err_list_text

                    # Integer intent fails closed without echoing raw value
                    res_num = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {"intent": 12345},
                    )
                    assert res_num.is_error is True
                    err_num_text = str(getattr(res_num.content[0], "text", ""))
                    assert "[REDACTED]" in err_num_text

                    # Ledger counts still 0
                    assert len(ledger._missions) == 0
                    assert len(ledger._actions) == 0
                    assert len(ledger._evidence) == 0

                    # 8, 9: valid string intent still succeeds and exact text is stored verbatim
                    valid_intent = "Prepare backpacks and set alarm for 6:45 AM verbatim."
                    res_valid = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {"intent": valid_intent},
                    )
                    assert res_valid.is_error is False
                    assert len(ledger._missions) == 1
                    stored_record = next(iter(ledger._missions.values()))
                    assert stored_record.contract.intent.text == valid_intent

    @pytest.mark.anyio
    async def test_39_42_extra_property_fails_and_redacts(self) -> None:
        """39, 42: Extra property fails closed; sensitive extra value is not echoed in error."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        ledger = InMemoryNonDurableLedger()
        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        sensitive_injected = "INJECTED_CONFIDENTIAL_EXTRA_VALUE_DO_NOT_PRINT"

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    res_extra = await session.call_tool(
                        MISSION_START_TOOL_NAME,
                        {
                            "intent": "Valid intent",
                            "secret_field": sensitive_injected,
                        },
                    )
                    assert res_extra.is_error is True
                    err_text = str(getattr(res_extra.content[0], "text", ""))

                    # 39. Fails closed
                    assert "secret_field" in err_text
                    # 42. Value not echoed, redacted
                    assert sensitive_injected not in err_text
                    assert "[REDACTED]" in err_text

                    assert len(ledger._missions) == 0


# ===========================================================================
# 7. Duplicate Call Truth & Non-Idempotency Tests (Items 43-45)
# ===========================================================================


class TestMissionStartDuplicateTruth:
    """Verify distinct mission creation and non-idempotency truth."""

    @pytest.mark.anyio
    async def test_43_44_45_duplicate_intent_creates_distinct_missions(self) -> None:
        """43, 44, 45: Two calls with identical intent produce 2 distinct MissionIds,
        same verbatim text; not idempotent."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MISSION_START_TOOL_NAME,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        ledger = InMemoryNonDurableLedger()
        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        same_intent = "Prepare weekly briefing notes for Monday"

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    res1 = await session.call_tool(MISSION_START_TOOL_NAME, {"intent": same_intent})
                    res2 = await session.call_tool(MISSION_START_TOOL_NAME, {"intent": same_intent})

                    assert res1.is_error is False
                    assert res2.is_error is False

                    d1 = json.loads(str(getattr(res1.content[0], "text", "")))
                    d2 = json.loads(str(getattr(res2.content[0], "text", "")))

                    # 43. Two distinct MissionIds
                    id1 = d1["mission_id"]
                    id2 = d2["mission_id"]
                    assert id1 != id2
                    assert len(ledger._missions) == 2

                    # 44. Both records retain the exact same intent text independently
                    r1 = ledger.get_mission(MissionId(id1))
                    r2 = ledger.get_mission(MissionId(id2))
                    assert r1.contract.intent.text == same_intent
                    assert r2.contract.intent.text == same_intent
                    assert r1.mission_id != r2.mission_id

                    # 45. Tool does NOT advertise idempotency
                    tools = await session.list_tools()
                    start_tool = next(t for t in tools.tools if t.name == MISSION_START_TOOL_NAME)
                    assert start_tool.annotations is not None
                    assert start_tool.annotations.idempotent_hint is False


# ===========================================================================
# 8. Direct Handler Unit Tests (Zero Network / Fast Unit Verification)
# ===========================================================================


class TestMissionStartDirectHandler:
    """Direct unit tests for create_mission_start_handler and dataclasses."""

    def test_handler_requires_mission_ledger_port(self) -> None:
        """create_mission_start_handler requires MissionLedgerPort instance."""
        from stilldone.mcp import create_mission_start_handler

        with pytest.raises(TypeError, match="ledger must implement MissionLedgerPort"):
            create_mission_start_handler("not_a_ledger")  # type: ignore[arg-type]

    def test_handler_deterministic_clock_injection(self) -> None:
        """Handler supports optional clock injection for deterministic testing."""
        from stilldone.mcp import create_mission_start_handler

        ledger = InMemoryNonDurableLedger()
        fixed_dt = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        handler = create_mission_start_handler(ledger, clock=lambda: fixed_dt)

        payload = handler("Sample intent for deterministic clock test")
        assert payload.created_at == fixed_dt.isoformat()
        assert payload.state == "DRAFT"

        record = ledger.get_mission(MissionId(payload.mission_id))
        assert record.created_at == fixed_dt
        assert record.updated_at == fixed_dt
        assert record.contract.created_at == fixed_dt
        assert record.contract.intent.captured_at == fixed_dt

    def test_handler_rejects_blank_intent(self) -> None:
        """Direct handler call rejects blank or whitespace-only intent."""
        from mcp.server.mcpserver.exceptions import ToolError

        from stilldone.mcp import create_mission_start_handler

        ledger = InMemoryNonDurableLedger()
        handler = create_mission_start_handler(ledger)

        with pytest.raises(ToolError, match="cannot be blank"):
            handler("")

        with pytest.raises(ToolError, match="cannot be blank"):
            handler("   \t  ")

        with pytest.raises(ToolError, match="must be a string"):
            handler(None)  # type: ignore[arg-type]

    def test_register_mission_start_tool_validations(self) -> None:
        """register_mission_start_tool validates server and ledger types."""
        from mcp.server.mcpserver import MCPServer

        from stilldone.mcp import register_mission_start_tool

        ledger = InMemoryNonDurableLedger()
        server = MCPServer("test", "0.1.0")

        with pytest.raises(TypeError, match="server must be MCPServer"):
            register_mission_start_tool("not_a_server", ledger)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="ledger must implement MissionLedgerPort"):
            register_mission_start_tool(server, "not_a_ledger")  # type: ignore[arg-type]

    def test_mission_start_view_and_payload_immutability(self) -> None:
        """MissionStartView and MissionStartPayload are frozen and enforce UTC."""
        from stilldone.mcp import MissionStartPayload, MissionStartView

        fixed_dt = datetime(2026, 10, 1, 15, 30, 0, tzinfo=UTC)
        mid = MissionId.generate()
        view = MissionStartView(
            mission_id=mid,
            state=MissionState.DRAFT,
            created_at=fixed_dt,
        )

        with pytest.raises(FrozenInstanceError):
            view.state = MissionState.READY  # type: ignore[misc]

        payload = view.to_payload()
        assert isinstance(payload, MissionStartPayload)
        assert payload.mission_id == str(mid)
        assert payload.state == "DRAFT"
        assert payload.created_at == fixed_dt.isoformat()

        d = payload.to_dict()
        assert d == {
            "mission_id": str(mid),
            "state": "DRAFT",
            "created_at": fixed_dt.isoformat(),
        }

        # Naive datetime raises ValueError in view
        naive_dt = datetime(2026, 10, 1, 15, 30, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            MissionStartView(
                mission_id=mid,
                state=MissionState.DRAFT,
                created_at=naive_dt,
            )


# ===========================================================================
# 9. Purity & Anti-Leakage Tests
# ===========================================================================


class TestMissionStartPurityAndAntiLeakage:
    """Verify that mission_start does not import provider SDKs or make external calls."""

    def test_mission_start_no_forbidden_provider_imports(self) -> None:
        """src/stilldone/mcp/mission_start.py has 0 provider/model SDK imports."""
        source_path = (
            pathlib.Path(__file__).parent.parent / "src" / "stilldone" / "mcp" / "mission_start.py"
        )
        assert source_path.exists(), f"Source file missing: {source_path}"

        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden_modules = {
            "boto3",
            "botocore",
            "google",
            "google.oauth2",
            "googleapiclient",
            "open_meteo",
            "httpx",
            "requests",
            "urllib3",
            "aiohttp",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    assert root_mod not in forbidden_modules, (
                        f"Forbidden import '{alias.name}' in mission_start.py"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    assert root_mod not in forbidden_modules, (
                        f"Forbidden from-import '{node.module}' in mission_start.py"
                    )
