"""Strict input validation helper for StillDone MCP tools.

Enforces:
- extra='forbid' on Pydantic argument model.
- additionalProperties=False in published JSON schema.
- Safe redaction of unexpected extra keys so rejected values are not leaked in errors.
- Safe redaction of non-string inputs on canonical string fields so rejected values are
  never leaked in validation error text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def enforce_strict_input_contract(server: MCPServer, tool_name: str) -> None:
    """Tighten tool argument validation to extra='forbid' and additionalProperties=False."""
    from pydantic import ConfigDict, model_validator
    from pydantic_core import InitErrorDetails, ValidationError

    tool = server._tool_manager.get_tool(tool_name)
    if tool is None:
        raise ValueError(f"Tool {tool_name} not found on server")

    orig_model = tool.fn_metadata.arg_model
    allowed_keys = set(orig_model.model_fields.keys())
    string_fields = {
        field_name
        for field_name, field_info in orig_model.model_fields.items()
        if field_info.annotation is str
    }

    class StrictArgModel(orig_model):  # type: ignore[valid-type,misc]
        model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

        @model_validator(mode="before")
        @classmethod
        def _check_strict_inputs_and_redact(cls, data: Any) -> Any:
            if isinstance(data, dict):
                errors: list[InitErrorDetails] = []

                # 1. Unexpected extra keys: extra='forbid' with redacted value
                extra_keys = [k for k in data.keys() if k not in allowed_keys]
                for k in sorted(extra_keys, key=lambda x: str(x)):
                    errors.append(
                        {
                            "type": "extra_forbidden",
                            "loc": (str(k),),
                            "input": "[REDACTED]",
                        }
                    )

                # 2. Canonical string fields receiving non-string values: redact rejected input
                for field_name in sorted(string_fields):
                    if field_name in data:
                        val = data[field_name]
                        if not isinstance(val, str):
                            errors.append(
                                {
                                    "type": "string_type",
                                    "loc": (field_name,),
                                    "input": "[REDACTED]",
                                }
                            )

                if errors:
                    raise ValidationError.from_exception_data(
                        cls.__name__,
                        errors,
                    )
            return data

    StrictArgModel.__name__ = orig_model.__name__
    tool.fn_metadata.arg_model = StrictArgModel
    tool.parameters = StrictArgModel.model_json_schema(by_alias=True)
