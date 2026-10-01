"""Real Model Context Protocol (MCP) server spine for StillDone.

Provides deterministic construction of the StillDone MCP server over
the official Streamable HTTP transport required for the Alexa+ competition path.

Phase P-05.05 boundary:
- Real MCP Server and real Streamable HTTP transport via the official MCP SDK.
- Bound to loopback only (127.0.0.1) for LOCAL default profile.
- Exactly 2 business tools: mission_status (P-05.03) and mission_start (P-05.04).
- Protected OAuth 2.0 Resource Server boundary (P-05.05):
  - Token verification delegated to external TokenVerifier.
  - RFC 9728 Protected Resource Metadata (PRM) endpoint exposed.
  - Alexa+ 401 compatibility (WWW-Authenticate suppressed on 401).
- Atomic persistent rate limiting via stdlib SQLite (P-05.05):
  - Check-and-consume in single atomic transaction (zero race window).
  - Evaluated using pure P-04.06 evaluate_endpoint_admission.
  - Exceeded quota returns HTTP 429 without ledger mutation.

Phase P-05.06 AgentCore deployment profile:
- Explicit deployment_profile="agentcore" enables non-loopback binding (0.0.0.0).
- Default profile (deployment_profile=None) remains strictly loopback-only.
- AgentCore IAM/SigV4 protects the remote runtime boundary.
- P-05.05 OAuth RS exists for the proven OAuth profile but is NOT
  the AgentCore IAM mechanism. The two are separate, documented layers.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.routing import Route

from stilldone import __version__

if TYPE_CHECKING:
    from mcp.server.auth.provider import TokenVerifier

    from stilldone.application.ports.ledger_port import MissionLedgerPort
    from stilldone.endpoint_protection import EndpointProtectionPolicy
    from stilldone.mcp.auth import MCPAuthConfig
    from stilldone.mcp.rate_limit import SqliteRateLimitStore

CANONICAL_MCP_HOST: Final[str] = "127.0.0.1"
CANONICAL_MCP_PATH: Final[str] = "/mcp"
DEFAULT_SERVER_NAME: Final[str] = "StillDone"
DEFAULT_SERVER_VERSION: Final[str] = __version__

# Deployment profiles — explicit selection required for non-loopback binding
DEPLOYMENT_PROFILE_AGENTCORE: Final[str] = "agentcore"
_VALID_DEPLOYMENT_PROFILES: Final[frozenset[str]] = frozenset({DEPLOYMENT_PROFILE_AGENTCORE})


@dataclass(frozen=True)
class MCPServerConfig:
    """Deterministic configuration for StillDone MCP server spine.

    Profile behaviour:
    - deployment_profile=None (default): Enforces loopback-only binding.
      This is the LOCAL execution boundary for tests and local development.
    - deployment_profile="agentcore": Allows non-loopback binding (e.g. 0.0.0.0)
      required for AgentCore container deployment. Must be selected explicitly.
      This does NOT silently widen bind address via environment variables.
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
    ping_path: str = "/ping"
    transport_ready: bool = True

    # Deployment profile — explicit non-loopback gate
    deployment_profile: str | None = None

    # P-05.05 Auth & Rate Limit boundaries
    auth_config: MCPAuthConfig | None = None
    rate_limit_policy: EndpointProtectionPolicy | None = None
    rate_limit_db_path: str | Path | None = None
    rate_limit_window_seconds: int = 60
    alexa_profile: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("host must be a non-empty string")

        # Validate deployment profile
        if self.deployment_profile is not None:
            if not isinstance(self.deployment_profile, str):
                raise TypeError("deployment_profile must be a string or None")
            if self.deployment_profile not in _VALID_DEPLOYMENT_PROFILES:
                raise ValueError(
                    f"Unknown deployment_profile: {self.deployment_profile!r}. "
                    f"Valid profiles: {sorted(_VALID_DEPLOYMENT_PROFILES)}"
                )

        stripped_host = self.host.strip().lower()
        if stripped_host != "localhost":
            try:
                ip = ipaddress.ip_address(stripped_host)
            except ValueError as err:
                raise ValueError(f"Invalid host address: {self.host}") from err
            if not ip.is_loopback and self.deployment_profile is None:
                raise ValueError(
                    "host must be a loopback address for local execution boundary, "
                    f"got: {self.host}. Use deployment_profile='agentcore' for "
                    "non-loopback binding in container deployment."
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

        if not isinstance(self.ping_path, str) or not self.ping_path.startswith("/"):
            raise ValueError("ping_path must be a string starting with '/'")
        if len(self.ping_path.strip()) <= 1:
            raise ValueError("ping_path must be a non-root path starting with '/'")

        if self.health_path == self.path:
            raise ValueError("health_path cannot clash with mcp path")
        if self.ready_path == self.path:
            raise ValueError("ready_path cannot clash with mcp path")
        if self.ping_path == self.path:
            raise ValueError("ping_path cannot clash with mcp path")
        if self.health_path == self.ready_path:
            raise ValueError("health_path and ready_path cannot be identical")
        if self.ping_path == self.ready_path:
            raise ValueError("ping_path and ready_path cannot be identical")
        if self.ping_path == self.health_path and self.health_path != "/ping":
            raise ValueError("ping_path and health_path cannot be identical")

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

        if self.auth_config is not None:
            from stilldone.mcp.auth import MCPAuthConfig

            if not (
                isinstance(self.auth_config, MCPAuthConfig)
                or type(self.auth_config).__name__ == "MCPAuthConfig"
            ):
                raise TypeError("auth_config must be an MCPAuthConfig instance")

        if self.rate_limit_policy is not None:
            from stilldone.endpoint_protection import EndpointProtectionPolicy

            if not (
                isinstance(self.rate_limit_policy, EndpointProtectionPolicy)
                or type(self.rate_limit_policy).__name__ == "EndpointProtectionPolicy"
            ):
                raise TypeError("rate_limit_policy must be an EndpointProtectionPolicy instance")

        if self.rate_limit_db_path is not None:
            if not isinstance(self.rate_limit_db_path, (str, Path)):
                raise TypeError("rate_limit_db_path must be a string or Path")

        if self.rate_limit_policy is None and self.rate_limit_db_path is not None:
            raise ValueError(
                "rate_limit_db_path cannot be configured when rate_limit_policy is None. "
                "Partial rate limiting configuration is forbidden."
            )

        if isinstance(self.rate_limit_window_seconds, bool) or not isinstance(
            self.rate_limit_window_seconds, int
        ):
            raise TypeError("rate_limit_window_seconds must be an integer, not bool")
        if self.rate_limit_window_seconds <= 0:
            raise ValueError("rate_limit_window_seconds must be strictly positive")

        if not isinstance(self.alexa_profile, bool):
            raise TypeError("alexa_profile must be a boolean")


def find_free_loopback_port(host: str = CANONICAL_MCP_HOST) -> int:
    """Find an available ephemeral port on the specified loopback host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def create_mcp_server(
    config: MCPServerConfig | None = None,
    ledger: MissionLedgerPort | None = None,
    token_verifier: TokenVerifier | None = None,
) -> MCPServer:
    """Create a StillDone MCP server instance using the official MCP SDK.

    Guarantees:
    - Stable StillDone identity (name and version from config).
    - Exactly 2 StillDone business tools: mission_status (P-05.03) and mission_start (P-05.04).
    - Bound to canonical MissionLedgerPort; defaults to an isolated InMemoryNonDurableLedger.
    - Both tools share the exact same effective MissionLedgerPort instance.
    - Zero prompts, zero resources.
    - Injects OAuth resource-server settings when configured.
    - Fails closed if auth_config is provided without a valid TokenVerifier.
    """
    from stilldone.application.ports.ledger_port import InMemoryNonDurableLedger, MissionLedgerPort
    from stilldone.mcp.mission_start import register_mission_start_tool
    from stilldone.mcp.mission_status import register_mission_status_tool

    cfg = config or MCPServerConfig()

    if cfg.auth_config is not None and token_verifier is None:
        raise ValueError(
            "Authentication is configured (auth_config is not None) but token_verifier is None. "
            "Server construction fails closed before serving to prevent unauthenticated access."
        )

    auth_settings = cfg.auth_config.to_sdk_auth_settings() if cfg.auth_config is not None else None

    server = MCPServer(
        name=cfg.server_name,
        version=cfg.server_version,
        auth=auth_settings,
        token_verifier=token_verifier,
    )
    effective_ledger = ledger if ledger is not None else InMemoryNonDurableLedger()
    if not (
        isinstance(effective_ledger, MissionLedgerPort)
        or type(effective_ledger).__name__ in ("InMemoryNonDurableLedger", "MissionLedgerPort")
    ):
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
    token_verifier: TokenVerifier | None = None,
    rate_limit_store: SqliteRateLimitStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Starlette:
    """Create the Starlette ASGI application for the StillDone MCP server.

    Mounts:
    - Streamable HTTP transport at cfg.path (/mcp) with auth and rate-limit middleware.
    - Process liveness probe at cfg.health_path (/health).
    - Transport-only readiness probe at cfg.ready_path (/ready).
    - RFC 9728 Protected Resource Metadata at SDK-generated well-known path.

    Fail-closed construction rules:
    - Auth fail-closed: If auth_config is provided, an effective token_verifier is required.
    - Rate fail-closed:
      - If rate_limit_policy is provided, exactly one of rate_limit_store or
        rate_limit_db_path must be provided.
      - If rate_limit_store or rate_limit_db_path is provided without policy, fails closed.
      - If both rate_limit_store and rate_limit_db_path are provided, fails closed
        (ambiguity guard).
    """
    from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware

    from stilldone.mcp.health import (
        create_readiness_endpoint,
        health_endpoint,
        ping_endpoint,
    )

    cfg = config or MCPServerConfig()

    # 1. Auth Fail-Closed Verification
    effective_verifier = token_verifier
    if effective_verifier is None and server is not None:
        effective_verifier = getattr(server, "_token_verifier", None)

    if cfg.auth_config is not None and effective_verifier is None:
        raise ValueError(
            "Authentication is configured (auth_config is not None) but token_verifier is None. "
            "App construction fails closed before serving /mcp to prevent unauthenticated access."
        )

    if (
        server is not None
        and getattr(getattr(server, "settings", None), "auth", None) is not None
        and effective_verifier is None
    ):
        raise ValueError(
            "Server has auth settings configured but no effective token_verifier was provided. "
            "App construction fails closed before serving /mcp to prevent unauthenticated access."
        )

    # 2. Rate-Limiting Fail-Closed Verification
    has_policy = cfg.rate_limit_policy is not None
    has_injected_store = rate_limit_store is not None
    has_db_path = cfg.rate_limit_db_path is not None

    if has_injected_store and has_db_path:
        raise ValueError(
            "Both rate_limit_store and rate_limit_db_path were provided simultaneously. "
            "Construction fails closed to prevent ambiguous rate-limiting store configuration."
        )

    if not has_policy and (has_injected_store or has_db_path):
        raise ValueError(
            "Rate limit store or db_path was provided without rate_limit_policy. "
            "Construction fails closed to prevent unconfigured rate limiting."
        )

    if has_policy and not (has_injected_store or has_db_path):
        raise ValueError(
            "rate_limit_policy is configured, but neither rate_limit_store nor rate_limit_db_path "
            "was provided. Construction fails closed to prevent silently unmetered traffic."
        )

    # 3. Create or wrap MCP server
    mcp_srv = (
        server
        if server is not None
        else create_mcp_server(cfg, ledger=ledger, token_verifier=effective_verifier)
    )
    app = mcp_srv.streamable_http_app(
        streamable_http_path=cfg.path,
        json_response=cfg.json_response,
        stateless_http=cfg.stateless_http,
        host=cfg.host,
    )
    app.add_route(cfg.health_path, health_endpoint, methods=["GET"])
    readiness_handler = create_readiness_endpoint(is_ready=cfg.transport_ready)
    app.add_route(cfg.ready_path, readiness_handler, methods=["GET"])
    app.add_route(cfg.ping_path, ping_endpoint, methods=["GET"])

    # Locate canonical /mcp route for auth & rate limiting boundaries
    mcp_route = next((r for r in app.routes if getattr(r, "path", None) == cfg.path), None)
    if not isinstance(mcp_route, Route):
        raise RuntimeError(f"Canonical route {cfg.path} was not found on Starlette application")

    # Verify RequireAuthMiddleware was installed when auth is configured
    if cfg.auth_config is not None:
        if not (
            isinstance(mcp_route.endpoint, RequireAuthMiddleware)
            or type(mcp_route.endpoint).__name__ == "RequireAuthMiddleware"
        ):
            raise RuntimeError(
                "auth_config was provided, but /mcp endpoint was not wrapped in "
                "RequireAuthMiddleware. Construction fails closed."
            )

    # Install RateLimitMiddleware when rate protection is configured (Mode B)
    if cfg.rate_limit_policy is not None:
        effective_store = rate_limit_store
        if effective_store is None and cfg.rate_limit_db_path is not None:
            from stilldone.mcp.rate_limit import SqliteRateLimitStore

            effective_store = SqliteRateLimitStore(
                cfg.rate_limit_db_path,
                window_duration_seconds=cfg.rate_limit_window_seconds,
            )

        if effective_store is None:
            raise RuntimeError("Unexpected failure to obtain effective rate limit store")

        from stilldone.mcp.rate_limit import RateLimitMiddleware

        if (
            isinstance(mcp_route.endpoint, RequireAuthMiddleware)
            or type(mcp_route.endpoint).__name__ == "RequireAuthMiddleware"
        ):
            auth_endpoint = cast(Any, mcp_route.endpoint)
            underlying_app = auth_endpoint.app
            rate_limited_app = RateLimitMiddleware(
                underlying_app,
                store=effective_store,
                policy=cfg.rate_limit_policy,
                clock=clock,
            )
            auth_endpoint.app = rate_limited_app
        else:
            rate_limited_app = RateLimitMiddleware(
                mcp_route.app,
                store=effective_store,
                policy=cfg.rate_limit_policy,
                clock=clock,
            )
            mcp_route.app = rate_limited_app
            mcp_route.endpoint = rate_limited_app

    alexa_compat_enabled = (
        cfg.auth_config.alexa_profile if cfg.auth_config is not None else cfg.alexa_profile
    )
    if cfg.auth_config is not None and alexa_compat_enabled:
        from stilldone.mcp.auth import Alexa401CompatibilityMiddleware

        mcp_route.app = Alexa401CompatibilityMiddleware(mcp_route.app, enabled=True)
        mcp_route.endpoint = Alexa401CompatibilityMiddleware(mcp_route.endpoint, enabled=True)

    return app


@asynccontextmanager
async def run_loopback_mcp_server(
    config: MCPServerConfig | None = None,
    server: MCPServer | None = None,
    ledger: MissionLedgerPort | None = None,
    token_verifier: TokenVerifier | None = None,
    rate_limit_store: SqliteRateLimitStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> AsyncGenerator[tuple[uvicorn.Server, str], None]:
    """Run the StillDone MCP server locally on loopback inside an async context manager.

    Yields (uvicorn_server, endpoint_url).
    Guarantees clean shutdown and port release on exit.
    Fails closed before port binding if configuration is invalid or partial.
    """
    cfg = config or MCPServerConfig()
    app = create_mcp_app(
        cfg,
        server=server,
        ledger=ledger,
        token_verifier=token_verifier,
        rate_limit_store=rate_limit_store,
        clock=clock,
    )
    port = cfg.port if cfg.port != 0 else find_free_loopback_port(cfg.host)

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


def create_agentcore_config(
    *,
    port: int = 8000,
    rate_limit_policy: EndpointProtectionPolicy | None = None,
    rate_limit_db_path: str | Path | None = None,
    rate_limit_window_seconds: int = 60,
    max_requests_per_window: int = 10,
) -> MCPServerConfig:
    """Create explicit MCPServerConfig for AgentCore container deployment.

    Enforces:
    - host = "0.0.0.0" (required for container ingress)
    - port = 8000 (AgentCore MCP container port)
    - path = "/mcp" (canonical MCP endpoint)
    - stateless_http = False (stateful session affinity for mission_start -> mission_status)
    - deployment_profile = "agentcore" (explicit non-loopback gate)
    - ping_path = "/ping"
    - health_path = "/health"
    - ready_path = "/ready"
    - rate_limit_policy: EndpointProtectionPolicy active on /mcp
    - rate_limit_db_path: runtime-local SQLite store
    - auth_config = None (IAM / SigV4 ingress terminates at AgentCore boundary)
    """
    if rate_limit_policy is None:
        from decimal import Decimal

        from stilldone.endpoint_protection import EndpointProtectionPolicy

        rate_limit_policy = EndpointProtectionPolicy(
            max_requests_per_window=max_requests_per_window,
            max_paid_live_requests_per_window=1,
            internal_gross_ceiling=Decimal("0.05"),
            live_paid_path_enabled=False,
        )

    if rate_limit_db_path is None:
        import tempfile

        rate_limit_db_path = Path(tempfile.gettempdir()) / "stilldone_rate_limit.db"

    return MCPServerConfig(
        host="0.0.0.0",
        port=port,
        path=CANONICAL_MCP_PATH,
        stateless_http=False,
        deployment_profile=DEPLOYMENT_PROFILE_AGENTCORE,
        ping_path="/ping",
        health_path="/health",
        ready_path="/ready",
        rate_limit_policy=rate_limit_policy,
        rate_limit_db_path=rate_limit_db_path,
        rate_limit_window_seconds=rate_limit_window_seconds,
    )
