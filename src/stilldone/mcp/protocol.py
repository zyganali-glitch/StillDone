"""Deterministic protocol initialization and capability declaration models.

Phase P-05.02: Captures observed protocol facts from the official MCP runtime
during client initialization, ensuring truthful capability projections and
preventing premature claims of future StillDone business surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MCPCapabilitySnapshot:
    """Immutable projection of declared server capabilities.

    Reflects the actual runtime capabilities advertised by the MCP server
    during protocol initialization. Does NOT assert or imply StillDone business
    tool or provider availability.
    """

    has_tools: bool
    tools_list_changed: bool
    has_prompts: bool
    prompts_list_changed: bool
    has_resources: bool
    resources_subscribe: bool
    resources_list_changed: bool
    has_logging: bool
    has_completions: bool
    has_experimental: bool
    has_tasks: bool
    has_extensions: bool

    @classmethod
    def from_server_capabilities(cls, capabilities: Any) -> MCPCapabilitySnapshot:
        """Create a capability snapshot from a raw ServerCapabilities object or None."""
        tools = getattr(capabilities, "tools", None)
        prompts = getattr(capabilities, "prompts", None)
        resources = getattr(capabilities, "resources", None)
        logging = getattr(capabilities, "logging", None)
        completions = getattr(capabilities, "completions", None)
        experimental = getattr(capabilities, "experimental", None)
        tasks = getattr(capabilities, "tasks", None)
        extensions = getattr(capabilities, "extensions", None)

        return cls(
            has_tools=tools is not None,
            tools_list_changed=bool(getattr(tools, "list_changed", False)) if tools else False,
            has_prompts=prompts is not None,
            prompts_list_changed=bool(getattr(prompts, "list_changed", False))
            if prompts
            else False,
            has_resources=resources is not None,
            resources_subscribe=bool(getattr(resources, "subscribe", False))
            if resources
            else False,
            resources_list_changed=bool(getattr(resources, "list_changed", False))
            if resources
            else False,
            has_logging=logging is not None,
            has_completions=completions is not None,
            has_experimental=bool(experimental) if experimental else False,
            has_tasks=tasks is not None,
            has_extensions=bool(extensions) if extensions else False,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert capability snapshot to a plain dictionary."""
        return {
            "has_tools": self.has_tools,
            "tools_list_changed": self.tools_list_changed,
            "has_prompts": self.has_prompts,
            "prompts_list_changed": self.prompts_list_changed,
            "has_resources": self.has_resources,
            "resources_subscribe": self.resources_subscribe,
            "resources_list_changed": self.resources_list_changed,
            "has_logging": self.has_logging,
            "has_completions": self.has_completions,
            "has_experimental": self.has_experimental,
            "has_tasks": self.has_tasks,
            "has_extensions": self.has_extensions,
        }


@dataclass(frozen=True)
class MCPInitializationSnapshot:
    """Immutable projection of deterministic facts observed from InitializeResult.

    Separates protocol transport facts from business and authority claims.
    Confers ZERO execution authority, ZERO approval grant, ZERO VERIFIED status,
    and ZERO READY state.
    """

    protocol_version: str
    server_name: str
    server_version: str
    instructions: str | None
    capabilities: MCPCapabilitySnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.protocol_version, str) or not self.protocol_version.strip():
            raise ValueError("protocol_version must be a non-empty string")
        if not isinstance(self.server_name, str) or not self.server_name.strip():
            raise ValueError("server_name must be a non-empty string")
        if not isinstance(self.server_version, str) or not self.server_version.strip():
            raise ValueError("server_version must be a non-empty string")
        if self.instructions is not None and not isinstance(self.instructions, str):
            raise TypeError("instructions must be a string or None")
        if not isinstance(self.capabilities, MCPCapabilitySnapshot):
            raise TypeError("capabilities must be an MCPCapabilitySnapshot instance")

    @classmethod
    def from_initialize_result(cls, result: Any) -> MCPInitializationSnapshot:
        """Construct an immutable projection from an official MCP InitializeResult."""
        protocol_version = getattr(result, "protocol_version", None)
        if not isinstance(protocol_version, str):
            raise TypeError("InitializeResult missing protocol_version")

        server_info = getattr(result, "server_info", None)
        server_name = getattr(server_info, "name", None) if server_info else None
        server_version = getattr(server_info, "version", None) if server_info else None

        if not isinstance(server_name, str) or not isinstance(server_version, str):
            raise TypeError("InitializeResult missing valid server_info")

        instructions = getattr(result, "instructions", None)
        capabilities_raw = getattr(result, "capabilities", None)
        cap_snapshot = MCPCapabilitySnapshot.from_server_capabilities(capabilities_raw)

        return cls(
            protocol_version=protocol_version,
            server_name=server_name,
            server_version=server_version,
            instructions=instructions,
            capabilities=cap_snapshot,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to a plain dictionary."""
        return {
            "protocol_version": self.protocol_version,
            "server_name": self.server_name,
            "server_version": self.server_version,
            "instructions": self.instructions,
            "capabilities": self.capabilities.to_dict(),
        }
