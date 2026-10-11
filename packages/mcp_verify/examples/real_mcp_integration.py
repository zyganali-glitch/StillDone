"""[REAL MCP INTEGRATION EXAMPLE] Verifiable MCP tools across real stdio transport.

Demonstrates genuine Model Context Protocol (MCP) tool integration:
1. Spawns an official MCPServer process with tools:
   - Mutation tool: `create_task_item`
   - Faulty mutation tool: `create_faulty_task_item`
   - Read-back query tool: `get_task_item`
2. Connects via official MCP ClientSession over stdio transport.
3. Uses `mcp-verify` middleware to wrap tool calls crossing the actual MCP transport boundary.
4. Proves:
   - Part 1: Real MCP Mutation -> Real MCP Read-back -> Predicate Match -> VERIFIED.
   - Part 2: Real MCP Mutation (200 OK) -> Real MCP Read-back Mismatch -> CONTRADICTED.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure local source is importable when executed directly
_src_dir = Path(__file__).resolve().parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

import anyio  # noqa: E402
from mcp import ClientSession, StdioServerParameters, types  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp_verify import (  # noqa: E402
    PredicateOperator,
    VerifiableOutcome,
    VerifiableToolMiddleware,
    VerificationPredicate,
)


def run_mcp_server() -> None:
    """Runs official MCPServer over stdio transport with stateful in-memory storage."""
    server = MCPServer(name="StillDoneTaskServer")
    tasks_storage: dict[str, dict[str, Any]] = {}

    @server.tool(name="create_task_item")
    def create_task_item(task_id: str, title: str) -> dict[str, Any]:
        """MCP Tool: Create a task in backend."""
        record = {
            "task_id": task_id,
            "title": title,
            "status": "NEEDS_ACTION",
        }
        tasks_storage[task_id] = record
        return {"status": "SUCCESS", "task_id": task_id, "title": title}

    @server.tool(name="create_faulty_task_item")
    def create_faulty_task_item(task_id: str, title: str) -> dict[str, Any]:
        """MCP Tool: Simulates silent backend divergence / corruption."""
        tasks_storage[task_id] = {
            "task_id": task_id,
            "title": "STALE_OR_CORRUPTED_TITLE",
            "status": "NEEDS_ACTION",
        }
        return {"status": "SUCCESS", "task_id": task_id, "title": title}

    @server.tool(name="get_task_item")
    def get_task_item(task_id: str) -> dict[str, Any]:
        """MCP Tool: Retrieve task state independently."""
        item = tasks_storage.get(task_id)
        if item is None:
            return {"found": False}
        return {"found": True, **item}

    server.run(transport="stdio")


async def _run_real_mcp_client() -> dict[str, VerifiableOutcome]:
    """Client connecting across stdio transport to local MCP server subprocess."""
    script_path = str(Path(__file__).resolve())
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[script_path, "--server"],
        env=os.environ.copy(),
    )

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

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Read-back handler crosses stdio transport to server subprocess
            @middleware.register_readback_handler("get_task_item")
            def handle_mcp_readback(target_id: str) -> dict[str, Any]:
                async def _read() -> types.CallToolResult:
                    res = await session.call_tool("get_task_item", {"task_id": target_id})
                    if isinstance(res, types.CallToolResult):
                        return res
                    raise RuntimeError(f"Unexpected tool call result: {res}")

                call_res = anyio.from_thread.run(_read)
                content_text = call_res.content[0].text if call_res.content else "{}"
                return json.loads(content_text)

            def make_mcp_tool_executor(tool_name: str) -> Any:
                def _executor(tool_args: dict[str, Any]) -> dict[str, Any]:
                    async def _call() -> types.CallToolResult:
                        res = await session.call_tool(tool_name, tool_args)
                        if isinstance(res, types.CallToolResult):
                            return res
                        raise RuntimeError(f"Unexpected tool call result: {res}")

                    call_res = anyio.from_thread.run(_call)
                    content_text = call_res.content[0].text if call_res.content else "{}"
                    return json.loads(content_text)

                return _executor

            def run_sync_verification() -> tuple[VerifiableOutcome, VerifiableOutcome]:
                # Part 1: Real MCP Tool Mutation & Independent Read-back
                out_normal = middleware.execute_and_verify(
                    tool_name="create_task_item",
                    tool_args={"task_id": "task_rain_gear", "title": "Pack rain gear"},
                    tool_executor=make_mcp_tool_executor("create_task_item"),
                )

                # Part 2: Silent Backend Divergence -> Contradiction Caught
                out_contradicted = middleware.execute_and_verify(
                    tool_name="create_faulty_task_item",
                    tool_args={"task_id": "task_school_prep", "title": "Prepare lunchboxes"},
                    tool_executor=make_mcp_tool_executor("create_faulty_task_item"),
                )
                return out_normal, out_contradicted

            normal_res, contradicted_res = await anyio.to_thread.run_sync(run_sync_verification)

    return {
        "normal": normal_res,
        "contradicted": contradicted_res,
    }


def run_real_mcp_example() -> dict[str, VerifiableOutcome]:
    """Runs genuine MCP tool execution demonstrating VERIFIED and CONTRADICTED states.

    Crosses real stdio client/server process transport.
    """
    results = anyio.run(_run_real_mcp_client)

    out_normal = results["normal"]
    print("--- Part 1: Real MCP Tool Mutation & Independent Read-back (stdio transport) ---")
    print(f"Tool Execution Success: {out_normal.execution.is_success}")
    print(f"Verification Status:    {out_normal.verification.status.value}")
    print(f"Is Verified:            {out_normal.is_verified}")

    out_contradicted = results["contradicted"]
    print("\n--- Part 2: Silent Backend Divergence -> Contradiction Caught (stdio transport) ---")
    print(f"Tool Execution Success: {out_contradicted.execution.is_success} (API returned 200 OK)")
    print(f"Verification Status:    {out_contradicted.verification.status.value}")
    print(f"Is Verified:            {out_contradicted.is_verified}")
    print(f"Contradiction Details:  {out_contradicted.verification.details}")

    return results


if __name__ == "__main__":
    if "--server" in sys.argv:
        run_mcp_server()
    else:
        run_real_mcp_example()
