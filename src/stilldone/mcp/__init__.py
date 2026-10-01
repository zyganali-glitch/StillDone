"""StillDone Model Context Protocol (MCP) server package.

Phase P-05.01: Streamable HTTP transport spine over loopback.
"""

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
    "CANONICAL_MCP_HOST",
    "CANONICAL_MCP_PATH",
    "DEFAULT_SERVER_NAME",
    "DEFAULT_SERVER_VERSION",
    "MCPServerConfig",
    "create_mcp_app",
    "create_mcp_server",
    "find_free_loopback_port",
    "run_loopback_mcp_server",
]
