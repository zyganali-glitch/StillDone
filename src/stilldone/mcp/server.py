"""Real Model Context Protocol (MCP) server spine for StillDone.

Provides deterministic construction of the StillDone MCP server over
the official Streamable HTTP transport required for the Alexa+ competition path.

Strict Phase P-05.01 boundary:
- Real MCP Server and real Streamable HTTP transport via the official MCP SDK.
- Bound to loopback only (127.0.0.1) for local execution tests.
- Zero business tools, zero provider calls, zero model calls, zero mission mutations.
- Zero authentication/PRM/rate limiting (belongs to P-05.05).
- Zero remote deployment or public tunnels (belongs to P-05.06).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from stilldone.application.ports.ledger_port import MissionLedgerPort

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette

from stilldone import __version__

CANONICAL_MCP_HOST: Final[str] = "127.0.0.1"
CANONICAL_MCP_PATH: Final[str] = "/mcp"
DEFAULT_SERVER_NAME: Final[str] = "StillDone"
DEFAULT_SERVER_VERSION: Final[str] = __version__


@dataclass(frozen=True)
class MCPServerConfig:
    """Deterministic configuration for StillDone MCP server spine.

    Enforces loopback-only binding for Phase P-05.01 local execution boundary.
    """

    host: str = CANONICAL_MCP_HOST
    port: int = 8000
    path: str = CANONICAL_MCP_PATH
    server_name: str = DEFAULT_SERVER_NAME
    server_version: str = DEFAULT_SERVER_VERSION
    json_response: bool = False
    stateless_http: bool = False

    health_path: str = "/health"
    ready_path: str = "/ready"
    transport_ready: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("host must be a non-empty string")

        stripped_host = self.host.strip().lower()
        if stripped_host != "localhost":
            try:
                ip = ipaddress.ip_address(stripped_host)
            except ValueError as err:
                raise ValueError(f"Invalid host address: {self.host}") from err
            if not ip.is_loopback:
                raise ValueError(
                    "host must be a loopback address for P-05.01 local execution boundary, "
                    f"got: {self.host}"
                )

        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise TypeError("port must be an integer")
        if not (0 <= self.port <= 65535):
            raise ValueError(f"port must be between 0 and 65535, got: {self.port}")

        if not isinstance(self.path, str) or not self.path.startswith("/"):
            raise ValueError("path must be a string starting with '/'")
        if len(self.path.strip()) <= 1:
            raise ValueError("path must be a non-root path starting with '/'")

        if not isinstance(self.health_path, str) or not self.health_path.startswith("/"):
            raise ValueError("health_path must be a string starting with '/'")
        if len(self.health_path.strip()) <= 1:
            raise ValueError("health_path must be a non-root path starting with '/'")

        if not isinstance(self.ready_path, str) or not self.ready_path.startswith("/"):
            raise ValueError("ready_path must be a string starting with '/'")
        if len(self.ready_path.strip()) <= 1:
            raise ValueError("ready_path must be a non-root path starting with '/'")

        if self.health_path == self.path:
            raise ValueError("health_path cannot clash with mcp path")
        if self.ready_path == self.path:
            raise ValueError("ready_path cannot clash with mcp path")
        if self.health_path == self.ready_path:
            raise ValueError("health_path and ready_path cannot be identical")

        if not isinstance(self.server_name, str) or not self.server_name.strip():
            raise ValueError("server_name must be a non-empty string")

        if not isinstance(self.server_version, str) or not self.server_version.strip():
            raise ValueError("server_version must be a non-empty string")

        if not isinstance(self.json_response, bool):
            raise TypeError("json_response must be a boolean")

        if not isinstance(self.stateless_http, bool):
            raise TypeError("stateless_http must be a boolean")

        if not isinstance(self.transport_ready, bool):
            raise TypeError("transport_ready must be a boolean")


def find_free_loopback_port(host: str = CANONICAL_MCP_HOST) -> int:
    """Find an available ephemeral port on the specified loopback host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def create_mcp_server(
    config: MCPServerConfig | None = None,
    ledger: MissionLedgerPort | None = None,
) -> MCPServer:
    """Create a StillDone MCP server instance using the official MCP SDK.

    Guarantees:
    - Stable StillDone identity (name and version from config).
    - Exactly 2 StillDone business tools: mission_status (P-05.03) and mission_start (P-05.04).
    - Bound to canonical MissionLedgerPort; defaults to an isolated InMemoryNonDurableLedger.
    - Both tools share the exact same effective MissionLedgerPort instance.
    - Zero prompts, zero resources.
    - Zero authentication/authorization middleware (deferred to P-05.05).
    """
    from stilldone.application.ports.ledger_port import InMemoryNonDurableLedger, MissionLedgerPort
    from stilldone.mcp.mission_start import register_mission_start_tool
    from stilldone.mcp.mission_status import register_mission_status_tool

    cfg = config or MCPServerConfig()
    server = MCPServer(
        name=cfg.server_name,
        version=cfg.server_version,
    )
    effective_ledger = ledger if ledger is not None else InMemoryNonDurableLedger()
    if not isinstance(effective_ledger, MissionLedgerPort):
        raise TypeError(
            f"ledger must implement MissionLedgerPort, got {type(effective_ledger).__name__}"
        )
    register_mission_status_tool(server, effective_ledger)
    register_mission_start_tool(server, effective_ledger)
    return server


def create_mcp_app(
    config: MCPServerConfig | None = None,
    server: MCPServer | None = None,
    ledger: MissionLedgerPort | None = None,
) -> Starlette:
    """Create the Starlette ASGI application for the StillDone MCP server.

    Mounts:
    - Streamable HTTP transport at cfg.path (/mcp)
    - Process liveness probe at cfg.health_path (/health)
    - Transport-only readiness probe at cfg.ready_path (/ready)
    """
    from stilldone.mcp.health import create_readiness_endpoint, health_endpoint

    cfg = config or MCPServerConfig()
    mcp_srv = server if server is not None else create_mcp_server(cfg, ledger=ledger)
    app = mcp_srv.streamable_http_app(
        streamable_http_path=cfg.path,
        json_response=cfg.json_response,
        stateless_http=cfg.stateless_http,
        host=cfg.host,
    )
    app.add_route(cfg.health_path, health_endpoint, methods=["GET"])
    readiness_handler = create_readiness_endpoint(is_ready=cfg.transport_ready)
    app.add_route(cfg.ready_path, readiness_handler, methods=["GET"])
    return app


@asynccontextmanager
async def run_loopback_mcp_server(
    config: MCPServerConfig | None = None,
    server: MCPServer | None = None,
    ledger: MissionLedgerPort | None = None,
) -> AsyncGenerator[tuple[uvicorn.Server, str], None]:
    """Run the StillDone MCP server locally on loopback inside an async context manager.

    Yields (uvicorn_server, endpoint_url).
    Guarantees clean shutdown and port release on exit.
    """
    cfg = config or MCPServerConfig()
    port = cfg.port if cfg.port != 0 else find_free_loopback_port(cfg.host)
    app = create_mcp_app(cfg, server=server, ledger=ledger)

    uvicorn_config = uvicorn.Config(
        app,
        host=cfg.host,
        port=port,
        log_level="error",
    )
    srv = uvicorn.Server(uvicorn_config)
    server_task = asyncio.create_task(srv.serve())

    try:
        while not srv.started and not server_task.done():
            await asyncio.sleep(0.01)
        if server_task.done():
            await server_task
            raise RuntimeError("Server failed to start")

        endpoint_url = f"http://{cfg.host}:{port}{cfg.path}"
        yield srv, endpoint_url
    finally:
        srv.should_exit = True
        await server_task
