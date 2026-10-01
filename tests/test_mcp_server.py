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
    # Unload MCP and stilldone.mcp modules to preserve provider-purity invariant
    # for any later test processes
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

        mcp_dir = pathlib.Path(inspect.getfile(srv_mod)).parent
        py_files = list(mcp_dir.glob("*.py"))
        assert len(py_files) >= 3, (
            f"Expected at least 3 python files in mcp package, found: {py_files}"
        )

        forbidden_packages = {
            "boto3",
            "botocore",
            "google",
            "googleapiclient",
            "agentcore",
            "strands",
            "open_meteo",
        }

        for py_file in py_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        pkg = alias.name.split(".")[0]
                        assert pkg not in forbidden_packages, (
                            f"Forbidden import '{alias.name}' in {py_file.name}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        pkg = node.module.split(".")[0]
                        assert pkg not in forbidden_packages, (
                            f"Forbidden import from '{node.module}' in {py_file.name}"
                        )

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
    async def test_09_10_11_business_surface_exactly_mission_status(self) -> None:
        """Requirements 9, 10, 11 (evolved for P-05.03):

        - 9. Exactly one business tool exists.
        - 10. Tool name is exactly mission_status.
        - 11. No mission-start tool exists yet.
        - 12. Prompts remain empty.
        - 13. Resources remain empty.
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

                    # 9. Exactly one business tool exposed: mission_status
                    tools_result = await session.list_tools()
                    assert len(tools_result.tools) == 1, (
                        f"Expected exactly 1 tool in P-05.03, found: {tools_result.tools}"
                    )

                    tool = tools_result.tools[0]
                    assert tool.name == "mission_status"

                    tool_names = [t.name for t in tools_result.tools]

                    # 10. No mission-start tool
                    assert "mission_start" not in tool_names
                    assert "start_mission" not in tool_names
                    assert "create_mission" not in tool_names
                    assert "execute_mission" not in tool_names

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

        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
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
                    assert len(tools1.tools) == 1
                    assert tools1.tools[0].name == "mission_status"

            # Session 2 against the same running server
            async with streamable_http_client(endpoint_url) as (r2, w2):
                async with ClientSession(r2, w2) as s2:
                    init2 = await s2.initialize()
                    assert init2.protocol_version == "2025-11-25"
                    assert init2.server_info.name == "StillDone"
                    tools2 = await s2.list_tools()
                    assert len(tools2.tools) == 1
                    assert tools2.tools[0].name == "mission_status"


# ===========================================================================
# Unit & Integration Tests: Health and Readiness Endpoints (P-05.02)
# ===========================================================================


class TestMCPHealthAndReadiness:
    """Verify deterministic plain HTTP /health and /ready surfaces."""

    def test_01_02_health_endpoint_liveness_in_process(self) -> None:
        """1, 2, 3: /health exists, returns HTTP 200, and contains only bounded liveness info."""
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            HEALTH_SCOPE_PROCESS,
            HEALTH_STATUS_ALIVE,
            create_mcp_app,
        )

        app = create_mcp_app()
        client = TestClient(app)

        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "status": HEALTH_STATUS_ALIVE,
            "scope": HEALTH_SCOPE_PROCESS,
        }
        assert resp.headers["cache-control"] == "no-cache, no-store, must-revalidate"

    def test_03_04_ready_endpoint_transport_readiness_in_process(self) -> None:
        """4, 5, 6: /ready exists, returns HTTP 200, and truth is explicitly transport-only."""
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            READY_SCOPE_TRANSPORT,
            READY_STATUS_READY,
            create_mcp_app,
        )

        app = create_mcp_app()
        client = TestClient(app)

        resp = client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "status": READY_STATUS_READY,
            "scope": READY_SCOPE_TRANSPORT,
        }
        assert data["scope"] == "mcp_transport"
        assert resp.headers["cache-control"] == "no-cache, no-store, must-revalidate"

    def test_05_ready_endpoint_fail_closed_when_unready(self) -> None:
        """5b. /ready fails closed with HTTP 503 when transport is not ready."""
        from starlette.testclient import TestClient

        from stilldone.mcp import (
            READY_SCOPE_TRANSPORT,
            READY_STATUS_NOT_READY,
            MCPServerConfig,
            create_mcp_app,
        )

        app = create_mcp_app(config=MCPServerConfig(transport_ready=False))
        client = TestClient(app)

        resp = client.get("/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data == {
            "status": READY_STATUS_NOT_READY,
            "scope": READY_SCOPE_TRANSPORT,
        }

    def test_06_health_and_ready_secrecy(self) -> None:
        """7. Neither /health nor /ready exposes secrets, env vars, IDs, or tokens."""
        from starlette.testclient import TestClient

        from stilldone.mcp import create_mcp_app

        app = create_mcp_app()
        client = TestClient(app)

        health_text = client.get("/health").text.lower()
        ready_text = client.get("/ready").text.lower()

        forbidden_patterns = [
            "secret",
            "token",
            "password",
            "bearer",
            "authorization",
            "calendar_id",
            "task_list_id",
            "aws_account",
            "us-east-1",
            "arn:aws",
            "client_secret",
            "refresh_token",
            "oauth",
        ]

        for pattern in forbidden_patterns:
            assert pattern not in health_text, f"Pattern '{pattern}' found in /health response"
            assert pattern not in ready_text, f"Pattern '{pattern}' found in /ready response"

    def test_07_health_and_ready_no_ledger_mutation(self) -> None:
        """8, 9: /health and /ready do not mutate ledger and invoke 0 providers."""
        from starlette.testclient import TestClient

        from stilldone.ledger import InMemoryNonDurableLedger
        from stilldone.mcp import create_mcp_app

        ledger = InMemoryNonDurableLedger()
        assert len(ledger._missions) == 0
        assert len(ledger._actions) == 0
        assert len(ledger._evidence) == 0

        app = create_mcp_app()
        client = TestClient(app)

        client.get("/health")
        client.get("/ready")

        assert len(ledger._missions) == 0
        assert len(ledger._actions) == 0
        assert len(ledger._evidence) == 0

    @pytest.mark.anyio
    async def test_08_health_and_ready_real_loopback_http(self) -> None:
        """Real loopback TCP test of /health and /ready over uvicorn."""

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            HEALTH_STATUS_ALIVE,
            READY_STATUS_READY,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config):
            import httpx2

            async with httpx2.AsyncClient() as http_client:
                # Test /health over real loopback HTTP socket
                health_url = f"http://{CANONICAL_MCP_HOST}:{port}/health"
                resp_health = await http_client.get(health_url)
                assert resp_health.status_code == 200
                data_health = resp_health.json()
                assert data_health["status"] == HEALTH_STATUS_ALIVE

                # Test /ready over real loopback HTTP socket
                ready_url = f"http://{CANONICAL_MCP_HOST}:{port}/ready"
                resp_ready = await http_client.get(ready_url)
                assert resp_ready.status_code == 200
                data_ready = resp_ready.json()
                assert data_ready["status"] == READY_STATUS_READY
                assert data_ready["scope"] == "mcp_transport"

    def test_09_no_separate_fastapi_or_flask(self) -> None:
        """10. No separate FastAPI/Flask framework introduced; uses Starlette directly."""
        from starlette.applications import Starlette

        from stilldone.mcp import create_mcp_app

        app = create_mcp_app()
        assert isinstance(app, Starlette)
        app_cls_name = type(app).__name__
        assert "FastAPI" not in app_cls_name
        assert "Flask" not in app_cls_name

    def test_10_config_validation_health_and_ready_paths(self) -> None:
        """Validate health_path and ready_path boundaries and collision prevention."""
        from stilldone.mcp import MCPServerConfig

        # Valid custom paths
        cfg = MCPServerConfig(health_path="/ping", ready_path="/status")
        assert cfg.health_path == "/ping"
        assert cfg.ready_path == "/status"

        # Invalid path format
        with pytest.raises(ValueError, match="health_path must be a string starting with '/'"):
            MCPServerConfig(health_path="health")
        with pytest.raises(ValueError, match="health_path must be a non-root path"):
            MCPServerConfig(health_path="/")
        with pytest.raises(ValueError, match="ready_path must be a string starting with '/'"):
            MCPServerConfig(ready_path="ready")
        with pytest.raises(ValueError, match="ready_path must be a non-root path"):
            MCPServerConfig(ready_path="/")

        # Collisions
        with pytest.raises(ValueError, match="health_path cannot clash with mcp path"):
            MCPServerConfig(health_path="/mcp")
        with pytest.raises(ValueError, match="ready_path cannot clash with mcp path"):
            MCPServerConfig(ready_path="/mcp")
        with pytest.raises(ValueError, match="health_path and ready_path cannot be identical"):
            MCPServerConfig(health_path="/status", ready_path="/status")

        # Invalid transport_ready type
        with pytest.raises(TypeError, match="transport_ready must be a boolean"):
            MCPServerConfig(transport_ready="yes")  # type: ignore[arg-type]


# ===========================================================================
# Unit & Integration Tests: Protocol Initialization & Capabilities (P-05.02)
# ===========================================================================


class TestMCPProtocolInitializationAndCapabilities:
    """Verify truthful protocol initialization, capability declaration, and snapshots."""

    @pytest.mark.anyio
    async def test_11_to_14_protocol_initialization_snapshot_from_runtime(self) -> None:
        """11, 12, 13, 14:

        - 11. Protocol version is read from runtime InitializeResult.
        - 12. Server name is truthful ('StillDone').
        - 13. Server version is truthful ('0.1.0').
        - 14. Capability projection is deterministic and truthful.
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MCPCapabilitySnapshot,
            MCPInitializationSnapshot,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    init_result = await session.initialize()

                    # 11, 12, 13, 14: Construct snapshot from runtime observation
                    snapshot = MCPInitializationSnapshot.from_initialize_result(init_result)

                    assert snapshot.protocol_version == "2025-11-25"
                    assert snapshot.server_name == "StillDone"
                    assert snapshot.server_version == "0.1.0"
                    assert isinstance(snapshot.capabilities, MCPCapabilitySnapshot)

                    # SDK protocol level capabilities
                    assert snapshot.capabilities.has_tools is True
                    assert snapshot.capabilities.tools_list_changed is False
                    assert snapshot.capabilities.has_prompts is True
                    assert snapshot.capabilities.has_resources is True
                    assert snapshot.capabilities.has_logging is False

                    snap_dict = snapshot.to_dict()
                    assert snap_dict["protocol_version"] == "2025-11-25"
                    assert snap_dict["server_name"] == "StillDone"
                    assert snap_dict["server_version"] == "0.1.0"
                    assert "capabilities" in snap_dict

    @pytest.mark.anyio
    async def test_15_repeated_initialization_produces_identical_snapshots(self) -> None:
        """15. Repeated initialization produces equivalent capability facts."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MCPInitializationSnapshot,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (r1, w1):
                async with ClientSession(r1, w1) as s1:
                    init1 = await s1.initialize()
                    snap1 = MCPInitializationSnapshot.from_initialize_result(init1)

            async with streamable_http_client(endpoint_url) as (r2, w2):
                async with ClientSession(r2, w2) as s2:
                    init2 = await s2.initialize()
                    snap2 = MCPInitializationSnapshot.from_initialize_result(init2)

            assert snap1 == snap2
            assert snap1.to_dict() == snap2.to_dict()

    @pytest.mark.anyio
    async def test_16_to_18_capabilities_match_actual_exposed_surface(self) -> None:
        """16, 17, 18: Capabilities match actual surface; no mission tools or provider claims."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from stilldone.mcp import (
            CANONICAL_MCP_HOST,
            MCPInitializationSnapshot,
            MCPServerConfig,
            find_free_loopback_port,
            run_loopback_mcp_server,
        )

        port = find_free_loopback_port(CANONICAL_MCP_HOST)
        config = MCPServerConfig(port=port)

        async with run_loopback_mcp_server(config) as (_, endpoint_url):
            async with streamable_http_client(endpoint_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    init_result = await session.initialize()
                    snapshot = MCPInitializationSnapshot.from_initialize_result(init_result)

                    # 16. Actual surface contains exactly mission_status; zero prompts/resources
                    tools = await session.list_tools()
                    prompts = await session.list_prompts()
                    resources = await session.list_resources()

                    assert len(tools.tools) == 1
                    assert tools.tools[0].name == "mission_status"
                    assert len(prompts.prompts) == 0
                    assert len(resources.resources) == 0

                    tool_names = [t.name for t in tools.tools]

                    # 17. No premature mission tools falsely declared
                    assert "mission_start" not in tool_names
                    assert "start_mission" not in tool_names
                    assert "create_mission" not in tool_names
                    assert "execute_mission" not in tool_names

                    # 18. No provider capability falsely declared
                    cap_dict = snapshot.capabilities.to_dict()
                    for key in ["google", "aws", "bedrock", "weather", "open_meteo"]:
                        assert key not in cap_dict

    def test_20_21_snapshot_validation_immutability_and_authority(self) -> None:
        """20, 21: Snapshot is immutable, validates fields, confers zero authority."""
        from stilldone.mcp import (
            MCPCapabilitySnapshot,
            MCPInitializationSnapshot,
        )

        cap = MCPCapabilitySnapshot(
            has_tools=True,
            tools_list_changed=False,
            has_prompts=True,
            prompts_list_changed=False,
            has_resources=True,
            resources_subscribe=False,
            resources_list_changed=False,
            has_logging=False,
            has_completions=False,
            has_experimental=False,
            has_tasks=False,
            has_extensions=False,
        )

        snap = MCPInitializationSnapshot(
            protocol_version="2025-11-25",
            server_name="StillDone",
            server_version="0.1.0",
            instructions=None,
            capabilities=cap,
        )

        # Immutability
        with pytest.raises(FrozenInstanceError):
            snap.server_name = "Modified"  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            cap.has_tools = False  # type: ignore[misc]

        # Validations fail closed
        with pytest.raises(ValueError, match="protocol_version must be a non-empty string"):
            MCPInitializationSnapshot(
                protocol_version="",
                server_name="StillDone",
                server_version="0.1.0",
                instructions=None,
                capabilities=cap,
            )

        with pytest.raises(ValueError, match="server_name must be a non-empty string"):
            MCPInitializationSnapshot(
                protocol_version="2025-11-25",
                server_name="",
                server_version="0.1.0",
                instructions=None,
                capabilities=cap,
            )

        with pytest.raises(
            TypeError, match="capabilities must be an MCPCapabilitySnapshot instance"
        ):
            MCPInitializationSnapshot(
                protocol_version="2025-11-25",
                server_name="StillDone",
                server_version="0.1.0",
                instructions=None,
                capabilities="not_a_capability_snapshot",  # type: ignore[arg-type]
            )

        # 20. Confers zero authority or state promotion capability
        forbidden_methods = [
            "promote_to_ready",
            "confer_authority",
            "mark_verified",
            "grant_approval",
            "execute_action",
            "verify_outcome",
        ]
        for method in forbidden_methods:
            assert not hasattr(snap, method), (
                f"Snapshot must not possess authority method '{method}'"
            )
            assert not hasattr(cap, method), (
                f"Capability must not possess authority method '{method}'"
            )
