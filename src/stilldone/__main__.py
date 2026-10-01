"""StillDone execution entrypoint for local execution and AgentCore container deployment.

Usage:
    # Default local execution profile (strictly loopback only):
    python -m stilldone

    # Explicit AgentCore deployment profile (0.0.0.0:8000, /mcp, /ping, rate-limited):
    python -m stilldone --profile agentcore

Governing law:
- Default profile remains strictly bound to loopback (127.0.0.1).
- Non-loopback binding (0.0.0.0) is permitted ONLY when --profile agentcore is explicitly given.
- Never silently widens bind address via arbitrary environment variables.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="StillDone Model Context Protocol (MCP) server",
        prog="python -m stilldone",
    )
    parser.add_argument(
        "--profile",
        choices=["local", "agentcore"],
        default="local",
        help=(
            "Server profile: 'local' (default, 127.0.0.1 loopback only) "
            "or 'agentcore' (0.0.0.0:8000 container deployment)"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host address to bind to (must be loopback unless --profile agentcore is specified)",
    )
    parser.add_argument(
        "--rate-limit-max",
        type=int,
        default=10,
        help="Maximum requests per rate-limit window (default: 10)",
    )
    parser.add_argument(
        "--rate-limit-db",
        type=str,
        default=None,
        help="Path to SQLite rate limit store (default: runtime-local temp db)",
    )
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    import uvicorn

    from stilldone.mcp.server import (
        CANONICAL_MCP_HOST,
        DEPLOYMENT_PROFILE_AGENTCORE,
        MCPServerConfig,
        create_agentcore_config,
        create_mcp_app,
    )

    parsed = parse_args(args)

    if parsed.profile == DEPLOYMENT_PROFILE_AGENTCORE:
        # Explicit AgentCore deployment profile
        config = create_agentcore_config(
            port=parsed.port,
            rate_limit_db_path=Path(parsed.rate_limit_db) if parsed.rate_limit_db else None,
            max_requests_per_window=parsed.rate_limit_max,
        )
        # If caller explicitly provided --host with agentcore profile, allow overriding 0.0.0.0
        if parsed.host is not None:
            config = MCPServerConfig(
                host=parsed.host,
                port=parsed.port,
                path=config.path,
                stateless_http=config.stateless_http,
                deployment_profile=DEPLOYMENT_PROFILE_AGENTCORE,
                ping_path=config.ping_path,
                health_path=config.health_path,
                ready_path=config.ready_path,
                rate_limit_policy=config.rate_limit_policy,
                rate_limit_db_path=config.rate_limit_db_path,
                rate_limit_window_seconds=config.rate_limit_window_seconds,
            )
    else:
        # Default local profile: loopback only
        effective_host = parsed.host if parsed.host is not None else CANONICAL_MCP_HOST
        config = MCPServerConfig(
            host=effective_host,
            port=parsed.port,
            # deployment_profile is None -> loopback check strictly enforced in post_init
        )

    app = create_mcp_app(config)
    print(
        f"Starting StillDone MCP server (profile={config.deployment_profile or 'local'}, "
        f"host={config.host}, port={config.port}, path={config.path})"
    )
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main(sys.argv[1:])
