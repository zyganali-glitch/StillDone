"""Reusable middleware and interceptor for Model Context Protocol tools."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from mcp_verify.contracts import (
    PredicateExtractor,
    ReadbackHandler,
    ToolExecutionResult,
    VerifiableOutcome,
    VerificationPredicate,
    VerificationResult,
    VerificationStatus,
)
from mcp_verify.verifier import Verifier


class ToolRegistrationError(Exception):
    """Raised when registering an invalid or incomplete verifiable tool contract."""


class VerifiableToolMiddleware:
    """Interception middleware enforcing the Verifiable Tool Invariant on MCP tools.

    Invariant:
    MUTATION -> INDEPENDENT READ-BACK -> PREDICATE EVALUATION -> VERIFIED

    If read-back fails or contradicts expectations, tool outcome is flagged as CONTRADICTED
    even if the raw tool execution returned success.
    """

    def __init__(self) -> None:
        self._verifiable_tools: dict[str, dict[str, Any]] = {}
        self._readback_handlers: dict[str, ReadbackHandler] = {}

    def register_verifiable_tool(
        self,
        tool_name: str,
        readback_tool_name: str,
    ) -> Callable[[PredicateExtractor], PredicateExtractor]:
        """Decorator to register a verifiable mutation tool with its predicate extractor."""

        def decorator(extractor: PredicateExtractor) -> PredicateExtractor:
            self._verifiable_tools[tool_name] = {
                "readback_tool_name": readback_tool_name,
                "extractor": extractor,
            }
            return extractor

        return decorator

    def register_readback_handler(
        self,
        readback_tool_name: str,
    ) -> Callable[[ReadbackHandler], ReadbackHandler]:
        """Decorator to register a handler function for independent read-back."""

        def decorator(handler: ReadbackHandler) -> ReadbackHandler:
            self._readback_handlers[readback_tool_name] = handler
            return handler

        return decorator

    def execute_and_verify(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_executor: Callable[[dict[str, Any]], dict[str, Any]],
        writes_performed: int = 1,
    ) -> VerifiableOutcome:
        """Execute tool, intercept result, perform independent read-back, and verify predicate."""
        # 1. Execute underlying mutation tool
        exec_start = time.perf_counter()
        try:
            raw_output = tool_executor(tool_args)
            exec_duration_ms = (time.perf_counter() - exec_start) * 1000.0
            exec_result = ToolExecutionResult(
                tool_name=tool_name,
                is_success=True,
                output_payload=raw_output,
                writes_performed=writes_performed,
                execution_latency_ms=exec_duration_ms,
            )
        except Exception as e:
            exec_duration_ms = (time.perf_counter() - exec_start) * 1000.0
            exec_result = ToolExecutionResult(
                tool_name=tool_name,
                is_success=False,
                output_payload={},
                writes_performed=0,
                execution_latency_ms=exec_duration_ms,
                error_message=str(e),
            )
            # If execution fails, verification cannot proceed
            verif_result = VerificationResult(
                status=VerificationStatus.EXECUTION_FAILED,
                is_verified=False,
                readback_tool_name="",
                observed_value=None,
                expected_value=None,
                details=f"Tool execution raised exception: {e}",
            )
            return VerifiableOutcome(
                tool_name=tool_name,
                execution=exec_result,
                verification=verif_result,
            )

        # 2. Check if tool has registered verification contract
        if tool_name not in self._verifiable_tools:
            # Unregistered tools remain UNVERIFIED_MUTATION
            verif_result = VerificationResult(
                status=VerificationStatus.UNVERIFIED_MUTATION,
                is_verified=False,
                readback_tool_name="",
                observed_value=None,
                expected_value=None,
                details=(
                    "No verifiable contract registered for tool; "
                    "execution was not independently verified."
                ),
            )
            return VerifiableOutcome(
                tool_name=tool_name,
                execution=exec_result,
                verification=verif_result,
            )

        tool_spec = self._verifiable_tools[tool_name]
        readback_name = tool_spec["readback_tool_name"]
        extractor: PredicateExtractor = tool_spec["extractor"]

        if readback_name not in self._readback_handlers:
            verif_result = VerificationResult(
                status=VerificationStatus.READ_BACK_FAILED,
                is_verified=False,
                readback_tool_name=readback_name,
                observed_value=None,
                expected_value=None,
                details=f"Missing readback handler for registered tool '{readback_name}'.",
            )
            return VerifiableOutcome(
                tool_name=tool_name,
                execution=exec_result,
                verification=verif_result,
            )

        # 3. Extract expected predicate from arguments and execution output
        predicate: VerificationPredicate = extractor(tool_args, raw_output)

        # 4. Perform INDEPENDENT read-back query
        rb_start = time.perf_counter()
        rb_handler = self._readback_handlers[readback_name]
        try:
            observed_state = rb_handler(predicate.target_id)
            rb_duration_ms = (time.perf_counter() - rb_start) * 1000.0
        except Exception as rb_err:
            rb_duration_ms = (time.perf_counter() - rb_start) * 1000.0
            verif_result = VerificationResult(
                status=VerificationStatus.READ_BACK_FAILED,
                is_verified=False,
                readback_tool_name=readback_name,
                observed_value=None,
                expected_value=predicate.expected_value,
                readback_latency_ms=rb_duration_ms,
                details=f"Independent readback handler raised error: {rb_err}",
            )
            return VerifiableOutcome(
                tool_name=tool_name,
                execution=exec_result,
                verification=verif_result,
            )

        # 5. Evaluate predicate against observed state
        verif_result = Verifier.verify_observation(
            predicate=predicate,
            observed_properties=observed_state,
            readback_tool_name=readback_name,
            readback_latency_ms=rb_duration_ms,
        )

        return VerifiableOutcome(
            tool_name=tool_name,
            execution=exec_result,
            verification=verif_result,
        )
