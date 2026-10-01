"""Deterministic health and readiness endpoints for StillDone MCP server.

Phase P-05.02:
- /health: Plain HTTP liveness probe confirming process/app can answer HTTP.
  Contains bounded liveness facts only; zero external cloud provider checks.
- /ready: Transport-only readiness probe confirming the local MCP transport spine
  is configured and listening. Does NOT imply provider, mission, or auth readiness.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from starlette.requests import Request
from starlette.responses import JSONResponse

CANONICAL_HEALTH_PATH: Final[str] = "/health"
CANONICAL_READY_PATH: Final[str] = "/ready"
CANONICAL_PING_PATH: Final[str] = "/ping"

HEALTH_STATUS_ALIVE: Final[str] = "alive"
HEALTH_SCOPE_PROCESS: Final[str] = "process"

READY_STATUS_READY: Final[str] = "ready"
READY_STATUS_NOT_READY: Final[str] = "not_ready"
READY_SCOPE_TRANSPORT: Final[str] = "mcp_transport"

PING_STATUS_HEALTHY: Final[str] = "Healthy"

NO_CACHE_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
}


async def ping_endpoint(request: Request) -> JSONResponse:
    """AgentCore health check probe returning bounded Healthy status."""
    return JSONResponse(
        {"status": PING_STATUS_HEALTHY},
        status_code=200,
        headers=NO_CACHE_HEADERS,
    )


async def health_endpoint(request: Request) -> JSONResponse:
    """Liveness probe indicating the process is running and answering HTTP."""
    return JSONResponse(
        {
            "status": HEALTH_STATUS_ALIVE,
            "scope": HEALTH_SCOPE_PROCESS,
        },
        status_code=200,
        headers=NO_CACHE_HEADERS,
    )


def create_readiness_endpoint(
    is_ready: bool = True,
) -> Callable[[Request], Awaitable[JSONResponse]]:
    """Factory creating a readiness probe bound to transport-only readiness state."""

    async def endpoint(request: Request) -> JSONResponse:
        if is_ready:
            return JSONResponse(
                {
                    "status": READY_STATUS_READY,
                    "scope": READY_SCOPE_TRANSPORT,
                },
                status_code=200,
                headers=NO_CACHE_HEADERS,
            )
        return JSONResponse(
            {
                "status": READY_STATUS_NOT_READY,
                "scope": READY_SCOPE_TRANSPORT,
            },
            status_code=503,
            headers=NO_CACHE_HEADERS,
        )

    return endpoint


async def readiness_endpoint(request: Request) -> JSONResponse:
    """Default transport readiness probe returning ready status."""
    return await create_readiness_endpoint(is_ready=True)(request)
