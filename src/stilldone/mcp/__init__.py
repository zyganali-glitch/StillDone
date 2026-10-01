"""StillDone Model Context Protocol (MCP) server package.

Phase P-05.01: Streamable HTTP transport spine over loopback.
Phase P-05.02: Protocol initialization, capability declaration, and health/readiness.
Phase P-05.03: Expose read-only mission-status tool over typed contracts.
"""

from stilldone.mcp.health import (
    CANONICAL_HEALTH_PATH,
    CANONICAL_READY_PATH,
    HEALTH_SCOPE_PROCESS,
    HEALTH_STATUS_ALIVE,
    READY_SCOPE_TRANSPORT,
    READY_STATUS_NOT_READY,
    READY_STATUS_READY,
    create_readiness_endpoint,
    health_endpoint,
    readiness_endpoint,
)
from stilldone.mcp.mission_status import (
    MISSION_STATUS_ANNOTATIONS,
    MISSION_STATUS_TOOL_DESCRIPTION,
    MISSION_STATUS_TOOL_NAME,
    MissionStatusPayload,
    MissionStatusView,
    create_mission_status_handler,
    register_mission_status_tool,
)
from stilldone.mcp.protocol import (
    MCPCapabilitySnapshot,
    MCPInitializationSnapshot,
)
from stilldone.mcp.server import (
    CANONICAL_MCP_HOST,
    CANONICAL_MCP_PATH,
    DEFAULT_SERVER_NAME,
    DEFAULT_SERVER_VERSION,
    MCPServerConfig,
    create_mcp_app,
    create_mcp_server,
    find_free_loopback_port,
    run_loopback_mcp_server,
)

__all__ = [
    "CANONICAL_HEALTH_PATH",
    "CANONICAL_MCP_HOST",
    "CANONICAL_MCP_PATH",
    "CANONICAL_READY_PATH",
    "DEFAULT_SERVER_NAME",
    "DEFAULT_SERVER_VERSION",
    "HEALTH_SCOPE_PROCESS",
    "HEALTH_STATUS_ALIVE",
    "MCPCapabilitySnapshot",
    "MCPInitializationSnapshot",
    "MCPServerConfig",
    "MISSION_STATUS_ANNOTATIONS",
    "MISSION_STATUS_TOOL_DESCRIPTION",
    "MISSION_STATUS_TOOL_NAME",
    "MissionStatusPayload",
    "MissionStatusView",
    "READY_SCOPE_TRANSPORT",
    "READY_STATUS_NOT_READY",
    "READY_STATUS_READY",
    "create_mcp_app",
    "create_mcp_server",
    "create_mission_status_handler",
    "create_readiness_endpoint",
    "find_free_loopback_port",
    "health_endpoint",
    "readiness_endpoint",
    "register_mission_status_tool",
    "run_loopback_mcp_server",
]
