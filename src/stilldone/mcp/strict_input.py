"""Strict input validation helper for StillDone MCP tools.

Enforces:
- extra='forbid' on Pydantic argument model.
- additionalProperties=False in published JSON schema.
- Safe redaction of unexpected extra keys so rejected values are not leaked in errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def enforce_strict_input_contract(server: MCPServer, tool_name: str) -> None:
    """Tighten tool argument validation to extra='forbid' and additionalProperties=False."""
    from pydantic import ConfigDict, model_validator
    from pydantic_core import ValidationError

    tool = server._tool_manager.get_tool(tool_name)
    if tool is None:
        raise ValueError(f"Tool {tool_name} not found on server")

    orig_model = tool.fn_metadata.arg_model
    allowed_keys = set(orig_model.model_fields.keys())

    class StrictArgModel(orig_model):  # type: ignore[valid-type,misc]
        model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

        @model_validator(mode="before")
        @classmethod
        def _check_extra_and_redact(cls, data: Any) -> Any:
            if isinstance(data, dict):
                extra_keys = [k for k in data.keys() if k not in allowed_keys]
                if extra_keys:
                    raise ValidationError.from_exception_data(
                        cls.__name__,
                        [
                            {
                                "type": "extra_forbidden",
                                "loc": (str(k),),
                                "input": "[REDACTED]",
                            }
                            for k in sorted(extra_keys, key=lambda x: str(x))
                        ],
                    )
            return data

    StrictArgModel.__name__ = orig_model.__name__
    tool.fn_metadata.arg_model = StrictArgModel
    tool.parameters = StrictArgModel.model_json_schema(by_alias=True)
