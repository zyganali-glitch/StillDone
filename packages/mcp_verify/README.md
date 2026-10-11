# mcp-verify

> **Deterministic Execute $\to$ Read-back $\to$ Verification middleware for Model Context Protocol (MCP) tools.**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)

---

## The Invariant

> **A tool execution response (`200 OK`) is NOT proof that an outcome was achieved.**

In AI agent architectures using the Model Context Protocol (MCP), LLMs invoke tools to modify real-world systems (databases, APIs, calendars, tasks). Traditional MCP servers return the raw write response to the agent. This introduces a critical safety vulnerability:
- The API may return `200 OK` while the resource state was silently corrupted or ignored.
- The mutation may fail to take effect due to eventual consistency or background job failures.
- The agent hallucinatorily assumes success because the tool didn't raise an exception.

`mcp-verify` enforces the **Verifiable Tool Invariant**:

$$\text{INTENT} \to \text{MUTATION} \to \textbf{INDEPENDENT READ-BACK} \to \textbf{PREDICATE EVALUATION} \to \text{VERIFIED}$$

If the independent read-back query cannot observe the expected state, `mcp-verify` flags the outcome as `CONTRADICTED` or `READ_BACK_FAILED`, preventing the agent from receiving false confirmation.

---

## Installation

Install locally from source or from built wheel:

```bash
# From local repository checkout
pip install ./packages/mcp_verify

# Or from built wheel package
pip install dist/mcp_verify-0.1.0-py3-none-any.whl
```

---

## Quickstart

Wrap any MCP tool mutation with an independent read-back handler:

```python
from mcp_verify import (
    VerifiableToolMiddleware,
    VerificationPredicate,
    PredicateOperator,
    ToolExecutionResult,
)

middleware = VerifiableToolMiddleware()


# 1. Register a verifiable tool contract
@middleware.register_verifiable_tool(
    tool_name="create_reminder",
    readback_tool_name="get_reminder",
)
def extract_verification_predicate(tool_args: dict, tool_result: dict) -> VerificationPredicate:
    # Build expected predicate based on mutation arguments
    return VerificationPredicate(
        target_id=tool_result.get("created_id", ""),
        attribute="title",
        operator=PredicateOperator.EQUALS,
        expected_value=tool_args["title"],
    )


# 2. Register readback handler
@middleware.register_readback_handler("get_reminder")
def handle_readback(target_id: str) -> dict:
    # Query your backend independently
    return fetch_reminder_from_database(target_id)


# 3. Execute tool through verification middleware
result = middleware.execute_and_verify(
    tool_name="create_reminder",
    tool_args={"title": "Pack backpacks"},
    tool_executor=lambda args: {"created_id": "rem_123", "title": "Pack backpacks"},
)

print(result.status)  # VerificationStatus.VERIFIED
print(result.is_verified)  # True
```

If the readback returned a different title, `result.status` would evaluate to `VerificationStatus.CONTRADICTED` with `is_verified=False`.

---

## License

Apache License 2.0. Clean-room implementation created as part of the StillDone project for the Amazon Developer Hackathon (Open Source Mini Challenge).
