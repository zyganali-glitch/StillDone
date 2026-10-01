"""StillDone Model Context Protocol (MCP) server package.

Phase P-05.01: Streamable HTTP transport spine over loopback.
Phase P-05.02: Protocol initialization, capability declaration, and health/readiness.
Phase P-05.03: Expose read-only mission-status tool over typed contracts.
Phase P-05.04: Expose mission-start tool without live mutation yet.
Phase P-05.05: Add auth/rate-limit boundary appropriate to the proven judge path.
"""

from stilldone.mcp.auth import (
    AUTHORIZATION_SERVER_LIVE_COMPATIBILITY,
    Alexa401CompatibilityMiddleware,
    MCPAuthConfig,
    SyntheticTokenVerifier,
    get_expected_prm_path,
)
from stilldone.mcp.health import (
    CANONICAL_HEALTH_PATH,
    CANONICAL_PING_PATH,
    CANONICAL_READY_PATH,
    HEALTH_SCOPE_PROCESS,
    HEALTH_STATUS_ALIVE,
    PING_STATUS_HEALTHY,
    READY_SCOPE_TRANSPORT,
    READY_STATUS_NOT_READY,
    READY_STATUS_READY,
    create_readiness_endpoint,
    health_endpoint,
    ping_endpoint,
    readiness_endpoint,
)
from stilldone.mcp.mission_start import (
    MISSION_START_ANNOTATIONS,
    MISSION_START_TOOL_DESCRIPTION,
    MISSION_START_TOOL_NAME,
    MissionStartPayload,
    MissionStartView,
    create_mission_start_handler,
    register_mission_start_tool,
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
from stilldone.mcp.rate_limit import (
    DEFAULT_WINDOW_SECONDS,
    RateLimitMiddleware,
    RateLimitStoreError,
    SqliteRateLimitStore,
)
from stilldone.mcp.server import (
    CANONICAL_MCP_HOST,
    CANONICAL_MCP_PATH,
    DEFAULT_SERVER_NAME,
    DEFAULT_SERVER_VERSION,
    DEPLOYMENT_PROFILE_AGENTCORE,
    MCPServerConfig,
    create_agentcore_config,
    create_mcp_app,
    create_mcp_server,
    find_free_loopback_port,
    run_loopback_mcp_server,
)
from stilldone.mcp.strict_input import (
    enforce_strict_input_contract,
)

__all__ = [
    "AUTHORIZATION_SERVER_LIVE_COMPATIBILITY",
    "Alexa401CompatibilityMiddleware",
    "CANONICAL_HEALTH_PATH",
    "CANONICAL_MCP_HOST",
    "CANONICAL_MCP_PATH",
    "CANONICAL_PING_PATH",
    "CANONICAL_READY_PATH",
    "DEFAULT_SERVER_NAME",
    "DEFAULT_SERVER_VERSION",
    "DEFAULT_WINDOW_SECONDS",
    "DEPLOYMENT_PROFILE_AGENTCORE",
    "HEALTH_SCOPE_PROCESS",
    "HEALTH_STATUS_ALIVE",
    "MCPAuthConfig",
    "MCPCapabilitySnapshot",
    "MCPInitializationSnapshot",
    "MCPServerConfig",
    "MISSION_START_ANNOTATIONS",
    "MISSION_START_TOOL_DESCRIPTION",
    "MISSION_START_TOOL_NAME",
    "MISSION_STATUS_ANNOTATIONS",
    "MISSION_STATUS_TOOL_DESCRIPTION",
    "MISSION_STATUS_TOOL_NAME",
    "MissionStartPayload",
    "MissionStartView",
    "MissionStatusPayload",
    "MissionStatusView",
    "PING_STATUS_HEALTHY",
    "READY_SCOPE_TRANSPORT",
    "READY_STATUS_NOT_READY",
    "READY_STATUS_READY",
    "RateLimitMiddleware",
    "RateLimitStoreError",
    "SqliteRateLimitStore",
    "SyntheticTokenVerifier",
    "create_agentcore_config",
    "create_mcp_app",
    "create_mcp_server",
    "create_mission_start_handler",
    "create_mission_status_handler",
    "create_readiness_endpoint",
    "enforce_strict_input_contract",
    "find_free_loopback_port",
    "get_expected_prm_path",
    "health_endpoint",
    "ping_endpoint",
    "readiness_endpoint",
    "register_mission_start_tool",
    "register_mission_status_tool",
    "run_loopback_mcp_server",
]
