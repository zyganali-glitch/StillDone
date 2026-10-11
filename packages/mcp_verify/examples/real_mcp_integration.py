"""[REAL MCP INTEGRATION EXAMPLE] Verifiable MCP tools using official MCP Server.

Demonstrates genuine Model Context Protocol (MCP) tool integration:
1. Registers actual MCP tools on official MCPServer:
   - Mutation tool: `create_task_item`
   - Read-back query tool: `get_task_item`
2. Uses `mcp-verify` middleware to wrap tool calls through the MCP boundary.
3. Proves:
   - Part 1: MCP Mutation -> MCP Read-back -> Predicate Match -> VERIFIED.
   - Part 2: MCP Mutation (200 OK) -> MCP Read-back Mismatch -> CONTRADICTED.
"""

from __future__ import annotations

import json
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp_verify import (
    PredicateOperator,
    VerifiableOutcome,
    VerifiableToolMiddleware,
    VerificationPredicate,
)


def build_real_mcp_verifiable_system() -> tuple[
    MCPServer, VerifiableToolMiddleware, dict[str, dict[str, Any]]
]:
    """Sets up a real MCPServer and binds mcp-verify middleware across the MCP tool boundary."""
    server = MCPServer(name="StillDoneTaskServer")
    tasks_storage: dict[str, dict[str, Any]] = {}

    # 1. Official MCP Mutation Tool: create_task_item
    def create_task_item(task_id: str, title: str) -> dict[str, Any]:
        """MCP Tool: Create a task in the backend."""
        record = {
            "task_id": task_id,
            "title": title,
            "status": "NEEDS_ACTION",
        }
        tasks_storage[task_id] = record
        return {"status": "SUCCESS", "task_id": task_id, "title": title}

    server.add_tool(create_task_item, name="create_task_item")

    # 2. Official MCP Read-back Query Tool: get_task_item
    def get_task_item(task_id: str) -> dict[str, Any]:
        """MCP Tool: Retrieve task state independently."""
        item = tasks_storage.get(task_id)
        if item is None:
            return {"found": False}
        return {"found": True, **item}

    server.add_tool(get_task_item, name="get_task_item")

    # 3. Setup mcp-verify middleware
    middleware = VerifiableToolMiddleware()

    @middleware.register_verifiable_tool(
        tool_name="create_task_item",
        readback_tool_name="get_task_item",
    )
    def extract_task_predicate(
        tool_args: dict[str, Any], tool_result: dict[str, Any]
    ) -> VerificationPredicate:
        return VerificationPredicate(
            target_id=tool_args["task_id"],
            attribute="title",
            operator=PredicateOperator.EQUALS,
            expected_value=tool_args["title"],
        )

    # Read-back handler invokes the actual MCP tool on the server through anyio
    @middleware.register_readback_handler("get_task_item")
    def handle_mcp_readback(target_id: str) -> dict[str, Any]:
        async def _call_mcp() -> dict[str, Any]:
            call_res = await server.call_tool("get_task_item", {"task_id": target_id})
            content_text = call_res.content[0].text if call_res.content else "{}"
            return json.loads(content_text)

        return anyio.run(_call_mcp)

    return server, middleware, tasks_storage


def execute_mcp_verified_call(
    server: MCPServer,
    middleware: VerifiableToolMiddleware,
    tool_name: str,
    tool_args: dict[str, Any],
) -> VerifiableOutcome:
    """Executes a tool call across the MCP boundary wrapped by mcp-verify middleware."""

    def mcp_tool_executor(args: dict[str, Any]) -> dict[str, Any]:
        async def _invoke() -> dict[str, Any]:
            call_res = await server.call_tool(tool_name, args)
            content_text = call_res.content[0].text if call_res.content else "{}"
            return json.loads(content_text)

        return anyio.run(_invoke)

    return middleware.execute_and_verify(
        tool_name=tool_name,
        tool_args=tool_args,
        tool_executor=mcp_tool_executor,
    )


def run_real_mcp_example() -> dict[str, VerifiableOutcome]:
    """Runs genuine MCP tool execution demonstrating VERIFIED and CONTRADICTED states."""
    server, middleware, storage = build_real_mcp_verifiable_system()

    # Part 1: Normal Execution & Verification
    print("--- Part 1: Real MCP Tool Mutation & Independent Read-back ---")
    args_normal = {"task_id": "task_rain_gear", "title": "Pack rain gear"}
    outcome_normal = execute_mcp_verified_call(server, middleware, "create_task_item", args_normal)

    print(f"Tool Execution Success: {outcome_normal.execution.is_success}")
    print(f"Verification Status:    {outcome_normal.verification.status.value}")
    print(f"Is Verified:            {outcome_normal.is_verified}")

    # Part 2: Contradicted State (Simulating silent failure / state corruption)
    print("\n--- Part 2: Silent Backend Divergence -> Contradiction Caught ---")

    # Register an MCP tool that returns 200 SUCCESS but writes divergent data to store
    def create_faulty_task_item(task_id: str, title: str) -> dict[str, Any]:
        """Simulates eventual consistency failure or silent mutation corruption."""
        storage[task_id] = {
            "task_id": task_id,
            "title": "STALE_OR_CORRUPTED_TITLE",
            "status": "NEEDS_ACTION",
        }
        return {"status": "SUCCESS", "task_id": task_id, "title": title}

    server.add_tool(create_faulty_task_item, name="create_faulty_task_item")

    @middleware.register_verifiable_tool(
        tool_name="create_faulty_task_item",
        readback_tool_name="get_task_item",
    )
    def extract_faulty_predicate(
        tool_args: dict[str, Any], tool_result: dict[str, Any]
    ) -> VerificationPredicate:
        return VerificationPredicate(
            target_id=tool_args["task_id"],
            attribute="title",
            operator=PredicateOperator.EQUALS,
            expected_value=tool_args["title"],
        )

    args_corrupt = {"task_id": "task_school_prep", "title": "Prepare lunchboxes"}
    outcome_contradicted = execute_mcp_verified_call(
        server, middleware, "create_faulty_task_item", args_corrupt
    )

    print(
        f"Tool Execution Success: {outcome_contradicted.execution.is_success} (API returned 200 OK)"
    )
    print(f"Verification Status:    {outcome_contradicted.verification.status.value}")
    print(f"Is Verified:            {outcome_contradicted.is_verified}")
    print(f"Contradiction Details:  {outcome_contradicted.verification.details}")

    return {
        "normal": outcome_normal,
        "contradicted": outcome_contradicted,
    }


if __name__ == "__main__":
    run_real_mcp_example()
