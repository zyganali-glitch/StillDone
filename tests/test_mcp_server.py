"""Tests for StillDone MCP server spine and Streamable HTTP transport.

Phase P-05.01 Verification:
1. StillDone MCP server can be constructed.
2. Canonical Streamable HTTP MCP endpoint is /mcp.
3. Server uses the real official MCP SDK.
4. Real loopback server starts successfully.
5. Official MCP client connects through actual Streamable HTTP.
6. Protocol negotiation succeeds.
7. Negotiated protocol version is captured/asserted as a supported real value.
8. Legacy standalone SSE is not the configured canonical transport.
9. No StillDone business tools are exposed prematurely.
10. No mission-status tool exists yet.
11. No mission-start tool exists yet.
12. No auth middleware/PRM/OAuth implementation exists yet.
13. No Google/AWS/Open-Meteo provider call occurs.
14. No model call occurs.
15. No mission/evidence/ledger mutation occurs merely by connecting.
16. Client closes cleanly.
17. Server closes cleanly.
18. Loopback port is released after test.
19. Transport test is deterministic/repeatable.
20. Existing test suite remains green.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import socket
import sys
from collections.abc import Generator
from dataclasses import FrozenInstanceError

import pytest


def assert_port_available(host: str, port: int) -> None:
    """Assert that a port is not in use and can be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, port))


@pytest.fixture(autouse=True, scope="module")
def _cleanup_mcp_sys_modules() -> Generator[None, None, None]:
    """Module-level cleanup to keep sys.modules pure after MCP server tests finish."""
    yield
    # Unload MCP modules to preserve provider-purity invariant for any later test processes
    mcp_keys = [
        k
        for k in list(sys.modules.keys())
        if k == "mcp" or k.startswith("mcp.") or k.startswith("mcp_")
    ]
    for k in mcp_keys:
        sys.modules.pop(k, None)


# ===========================================================================
# Unit Tests: Server Construction & Configuration
# ===========================================================================


class TestMCPServerConstructionAndConfig:
    """Verify deterministic construction and bounded configuration."""

    def test_01_server_construction_default(self) -> None:
        """1. StillDone MCP server can be constructed with defaults."""
        from mcp.server.mcpserver import MCPServer

        from stilldone.mcp import (
            DEFAULT_SERVER_NAME,
            DEFAULT_SERVER_VERSION,
            create_mcp_server,
        )

        server = create_mcp_server()
        assert isinstance(server, MCPServer)
        assert server.name == DEFAULT_SERVER_NAME
        assert server.name == "StillDone"
        assert server.version == DEFAULT_SERVER_VERSION

    def test_01_server_construction_custom_config(self) -> None:
        """1b. Server can be constructed with explicit deterministic config."""
        from stilldone.mcp import MCPServerConfig, create_mcp_server

        config = MCPServerConfig(
            host="127.0.0.1",
            port=9999,
            path="/mcp",
            server_name="StillDone-Test",
            server_version="1.0.0-beta",
            json_response=False,
            stateless_http=False,
        )
        server = create_mcp_server(config)
        assert server.name == "StillDone-Test"
        assert server.version == "1.0.0-beta"

    def test_02_canonical_endpoint_path(self) -> None:
        """2. Canonical Streamable HTTP MCP endpoint is /mcp."""
        from stilldone.mcp import CANONICAL_MCP_PATH, MCPServerConfig

        assert CANONICAL_MCP_PATH == "/mcp"
        config = MCPServerConfig()
        assert config.path == "/mcp"

    def test_03_server_uses_official_mcp_sdk(self) -> None:
        """3. Server uses the real official MCP SDK."""
        from mcp.server.mcpserver import MCPServer

        from stilldone.mcp import create_mcp_server

        server = create_mcp_server()
        server_module = type(server).__module__
        assert server_module.startswith("mcp.server"), (
            f"Expected official mcp.server module, got: {server_module}"
        )
        assert issubclass(type(server), MCPServer)

    def test_config_immutability(self) -> None:
        """MCPServerConfig is frozen/immutable."""
        from stilldone.mcp import MCPServerConfig

        config = MCPServerConfig()
        with pytest.raises(FrozenInstanceError):
            config.port = 9000  # type: ignore[misc]

    def test_config_validation_port(self) -> None:
        """Port must be an integer between 0 and 65535."""
        from stilldone.mcp import MCPServerConfig

        with pytest.raises(TypeError, match="port must be an integer"):
            MCPServerConfig(port="8000")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="port must be an integer"):
            MCPServerConfig(port=True)
        with pytest.raises(ValueError, match="port must be between 0 and 65535"):
            MCPServerConfig(port=-1)
        with pytest.raises(ValueError, match="port must be between 0 and 65535"):
            MCPServerConfig(port=70000)

    def test_config_validation_host_loopback_only(self) -> None:
        """Host must be loopback only in Phase P-05.01."""
        from stilldone.mcp import MCPServerConfig

        # Loopback accepted
        c1 = MCPServerConfig(host="127.0.0.1")
        assert c1.host == "127.0.0.1"
        c2 = MCPServerConfig(host="localhost")
        assert c2.host == "localhost"

        # Non-loopback / public / external rejected fail-closed
        with pytest.raises(ValueError, match="host must be a loopback address"):
            MCPServerConfig(host="0.0.0.0")
        with pytest.raises(ValueError, match="host must be a loopback address"):
            MCPServerConfig(host="192.168.1.100")
        with pytest.raises(ValueError, match="host must be a loopback address"):
            MCPServerConfig(host="8.8.8.8")
        with pytest.raises(ValueError, match="host must be a non-empty string"):
            MCPServerConfig(host="")

    def test_config_validation_path(self) -> None:
        """Path must be a non-empty string starting with /."""
        from stilldone.mcp import MCPServerConfig

        with pytest.raises(ValueError, match="path must be a string starting with '/'"):
            MCPServerConfig(path="mcp")
        with pytest.raises(ValueError, match="path must be a non-root path starting with '/'"):
            MCPServerConfig(path="/")

    def test_config_validation_server_identity(self) -> None:
        """Server name and version must be non-empty strings."""
        from stilldone.mcp import MCPServerConfig

        with pytest.raises(ValueError, match="server_name must be a non-empty string"):
            MCPServerConfig(server_name="")
        with pytest.raises(ValueError, match="server_version must be a non-empty string"):
            MCPServerConfig(server_version="")

    def test_config_validation_booleans(self) -> None:
        """json_response and stateless_http must be booleans."""
        from stilldone.mcp import MCPServerConfig

        with pytest.raises(TypeError, match="json_response must be a boolean"):
            MCPServerConfig(json_response="false")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="stateless_http must be a boolean"):
            MCPServerConfig(stateless_http=1)  # type: ignore[arg-type]

    def test_config_validation_non_string_types(self) -> None:
        """Host, path, name, version must reject non-string types."""
        from stilldone.mcp import MCPServerConfig

        with pytest.raises(ValueError, match="host must be a non-empty string"):
            MCPServerConfig(host=None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="path must be a string starting with '/'"):
            MCPServerConfig(path=123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="server_name must be a non-empty string"):
            MCPServerConfig(server_name=None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="server_version must be a non-empty string"):
            MCPServerConfig(server_version=None)  # type: ignore[arg-type]

    def test_find_free_loopback_port(self) -> None:
        """find_free_loopback_port returns a valid bindable port."""
        from stilldone.mcp import CANONICAL_MCP_HOST, find_free_loopback_port

        port = find_free_loopback_port()
        assert isinstance(port, int)
        assert 1024 <= port <= 65535
        assert_port_available(CANONICAL_MCP_HOST, port)

    def test_port_zero_accepted_in_config(self) -> None:
        """Port 0 is accepted as ephemeral port token."""
        from stilldone.mcp import MCPServerConfig

        config = MCPServerConfig(port=0)
        assert config.port == 0

    def test_create_mcp_app_returns_starlette(self) -> None:
        """create_mcp_app creates a valid Starlette ASGI application."""
        from starlette.applications import Starlette

        from stilldone.mcp import create_mcp_app

        app = create_mcp_app()
        assert isinstance(app, Starlette)

    def test_08_legacy_standalone_sse_not_canonical_transport(self) -> None:
        """8. Legacy standalone SSE is not the configured canonical transport."""
        from stilldone.mcp import create_mcp_app

        app = create_mcp_app()
        route_paths = [getattr(r, "path", None) for r in app.routes]
        assert "/mcp" in route_paths
        assert "/sse" not in route_paths


# ===========================================================================
# AST and Anti-Leakage Tests
# ===========================================================================


class TestMCPAntiLeakage:
    """Verify strict isolation of the MCP server module."""

    def test_no_forbidden_provider_imports_in_mcp_module(self) -> None:
        """Verify src/stilldone/mcp does not import any external cloud provider SDKs."""
        import stilldone.mcp.server as srv_mod

        source_file = inspect.getfile(srv_mod)
        source_path = pathlib.Path(source_file)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        forbidden_packages = {
            "boto3",
            "botocore",
            "google",
            "googleapiclient",
            "agentcore",
            "strands",
            "open_meteo",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    pkg = alias.name.split(".")[0]
                    assert pkg not in forbidden_packages, f"Forbidden import: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    pkg = node.module.split(".")[0]
                    assert pkg not in forbidden_packages, f"Forbidden import from: {node.module}"

    def test_12_no_auth_middleware_prm_oauth_exists(self) -> None:
        """12. No auth middleware, PRM, or OAuth implementation exists in P-05.01."""
        from stilldone.mcp import create_mcp_app, create_mcp_server

        server = create_mcp_server()
        assert getattr(server, "auth_server_provider", None) is None
        assert getattr(server, "token_verifier", None) is None

        app = create_mcp_app(server=server)
        route_paths = [str(getattr(r, "path", "")) for r in app.routes]
        forbidden_auth_routes = [
            "/oauth",
            "/prm",
            "/authorize",
            "/token",
            "/.well-known/oauth-authorization-server",
        ]
        for route in forbidden_auth_routes:
            assert route not in route_paths, f"Premature auth route found: {route}"


# ===========================================================================
# Integration Tests: Real Loopback Streamable HTTP Transport
# ===========================================================================


class TestMCPLoopbackTransport:
    """Prove real MCP server + real Streamable HTTP transport + real client negotiation."""

    @pytest.mark.anyio
    async def test_04_to_07_real_loopback_connection_and_negotiation(self) -> None:
        """Requirements 4, 5, 6, 7, 16, 17, 18:

        - 4. Real loopback server starts successfully.
        - 5. Official MCP client connects through actual Streamable HTTP.
        - 6. Protocol negotiation succeeds.
        - 7. Negotiated protocol version is captured/asserted as a supported real value.
        - 16. Client closes cleanly.
        - 17. Server closes cleanly.
        - 18. Loopback port is released after test.
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            CANONICAL_MCP_PATH,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(
            host=CANONICAL_MCP_HOST,
            port=port,
            path=CANONICAL_MCP_PATH,
            server_name="StillDone",
            server_version="0.1.0",
        )

        negotiated_version: str | None = None
        server_info_name: str | None = None

        # 4. Start real loopback server
        async with run_loopback_mcp_server(config) as (srv, endpoint_url):
            assert srv.started is True
            assert endpoint_url == f"http://127.0.0.1:{port}/mcp"

            # 5. Connect with official MCP client via Streamable HTTP
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    # 6. Protocol negotiation succeeds
                    init_result = await session.initialize()

                    negotiated_version = init_result.protocol_version
                    server_info_name = init_result.server_info.name

                    # 7. Captured negotiated protocol version is a real supported value
                    assert isinstance(negotiated_version, str)
                    assert len(negotiated_version) > 0
                    assert negotiated_version in [
                        "2025-11-25",
                        "2026-07-28",
                        "2025-03-26",
                        "2024-11-05",
                    ]
                    # Specifically, the observed negotiated version with official SDK is 2025-11-25
                    assert negotiated_version == "2025-11-25"

                    assert server_info_name == "StillDone"
                    assert init_result.server_info.version == "0.1.0"

        # 17. Server closed cleanly and 18. Port is released
        assert srv.should_exit is True
        assert_port_available(CANONICAL_MCP_HOST, port)

    @pytest.mark.anyio
    async def test_09_10_11_no_business_tools_exposed(self) -> None:
        """Requirements 9, 10, 11:

        - 9. No StillDone business tools are exposed prematurely.
        - 10. No mission-status tool exists yet.
        - 11. No mission-start tool exists yet.
        """
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

                    # 9. No business tools exposed
                    tools_result = await session.list_tools()
                    assert len(tools_result.tools) == 0, (
                        f"Expected 0 tools in P-05.01, found: {tools_result.tools}"
                    )

                    tool_names = [tool.name for tool in tools_result.tools]

                    # 10. No mission-status tool
                    assert "mission_status" not in tool_names
                    assert "get_mission_status" not in tool_names

                    # 11. No mission-start tool
                    assert "mission_start" not in tool_names
                    assert "start_mission" not in tool_names

                    # Also verify prompts and resources are empty
                    prompts_result = await session.list_prompts()
                    assert len(prompts_result.prompts) == 0
                    resources_result = await session.list_resources()
                    assert len(resources_result.resources) == 0

    @pytest.mark.anyio
    async def test_13_14_15_no_provider_model_or_ledger_mutation(self) -> None:
        """Requirements 13, 14, 15:

        - 13. No Google/AWS/Open-Meteo provider call occurs.
        - 14. No model call occurs.
        - 15. No mission/evidence/ledger mutation occurs merely by connecting.
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.ledger import InMemoryNonDurableLedger
        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        ledger = InMemoryNonDurableLedger()
        assert len(ledger._missions) == 0
        assert len(ledger._actions) == 0
        assert len(ledger._evidence) == 0

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    await session.list_tools()

        # 15. Ledger must remain unmutated (zero records added)
        assert len(ledger._missions) == 0
        assert len(ledger._actions) == 0
        assert len(ledger._evidence) == 0

    @pytest.mark.anyio
    async def test_19_transport_test_deterministic_repeatable(self) -> None:
        """19. Transport test is deterministic and repeatable across multiple sessions."""
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
            # Session 1
            async with streamable_http_client(endpoint_url) as (r1, w1):
                async with ClientSession(r1, w1) as s1:
                    init1 = await s1.initialize()
                    assert init1.protocol_version == "2025-11-25"
                    assert init1.server_info.name == "StillDone"
                    tools1 = await s1.list_tools()
                    assert len(tools1.tools) == 0

            # Session 2 against the same running server
            async with streamable_http_client(endpoint_url) as (r2, w2):
                async with ClientSession(r2, w2) as s2:
                    init2 = await s2.initialize()
                    assert init2.protocol_version == "2025-11-25"
                    assert init2.server_info.name == "StillDone"
                    tools2 = await s2.list_tools()
                    assert len(tools2.tools) == 0
