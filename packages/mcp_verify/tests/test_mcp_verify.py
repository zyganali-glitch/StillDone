"""Test suite for mcp-verify standalone package."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure mcp_verify is importable
pkg_src = Path(__file__).resolve().parent.parent / "src"
if str(pkg_src) not in sys.path:
    sys.path.insert(0, str(pkg_src))

from mcp_verify import (
    PredicateOperator,
    ToolExecutionResult,
    VerifiableOutcome,
    VerifiableToolMiddleware,
    VerificationPredicate,
    VerificationResult,
    VerificationStatus,
    Verifier,
)


def test_predicate_evaluation_operators() -> None:
    # EQUALS
    p1 = VerificationPredicate("t1", "status", PredicateOperator.EQUALS, "done")
    assert p1.evaluate({"status": "done"}) is True
    assert p1.evaluate({"status": "pending"}) is False
    assert p1.evaluate({}) is False

    # NOT_EQUALS
    p2 = VerificationPredicate("t1", "status", PredicateOperator.NOT_EQUALS, "pending")
    assert p2.evaluate({"status": "done"}) is True
    assert p2.evaluate({"status": "pending"}) is False

    # CONTAINS
    p3 = VerificationPredicate("t1", "items", PredicateOperator.CONTAINS, "backpack")
    assert p3.evaluate({"items": ["lunchbox", "backpack"]}) is True
    assert p3.evaluate({"items": ["lunchbox"]}) is False

    # EXISTS
    p4 = VerificationPredicate("t1", "etag", PredicateOperator.EXISTS, None)
    assert p4.evaluate({"etag": "12345"}) is True
    assert p4.evaluate({"title": "foo"}) is False

    # GREATER_THAN / LESS_THAN
    p5 = VerificationPredicate("t1", "count", PredicateOperator.GREATER_THAN, 5)
    assert p5.evaluate({"count": 10}) is True
    assert p5.evaluate({"count": 3}) is False


def test_verifier_verify_observation() -> None:
    pred = VerificationPredicate("t1", "state", PredicateOperator.EQUALS, "READY")

    # Satisfied
    res1 = Verifier.verify_observation(pred, {"state": "READY"}, "read_state", 12.0)
    assert res1.is_verified is True
    assert res1.status == VerificationStatus.VERIFIED
    assert res1.observed_value == "READY"
    assert res1.readback_latency_ms == 12.0

    # Contradicted
    res2 = Verifier.verify_observation(pred, {"state": "DRIFTED"}, "read_state", 15.0)
    assert res2.is_verified is False
    assert res2.status == VerificationStatus.CONTRADICTED
    assert res2.observed_value == "DRIFTED"

    # Missing / None observation
    res3 = Verifier.verify_observation(pred, None, "read_state")
    assert res3.is_verified is False
    assert res3.status == VerificationStatus.READ_BACK_FAILED


def test_middleware_successful_execution_and_verification() -> None:
    mw = VerifiableToolMiddleware()

    db = {"item_1": {"name": "Test Item", "completed": True}}

    @mw.register_verifiable_tool("update_item", "get_item")
    def extract_pred(args: dict, output: dict) -> VerificationPredicate:
        return VerificationPredicate(
            target_id=args["id"],
            attribute="completed",
            operator=PredicateOperator.EQUALS,
            expected_value=args["completed"],
        )

    @mw.register_readback_handler("get_item")
    def read_item(target_id: str) -> dict:
        return db.get(target_id, {})

    outcome = mw.execute_and_verify(
        tool_name="update_item",
        tool_args={"id": "item_1", "completed": True},
        tool_executor=lambda a: {"status": "ok"},
    )

    assert outcome.is_verified is True
    assert outcome.status == VerificationStatus.VERIFIED
    assert outcome.execution.is_success is True
    assert outcome.verification.observed_value is True


def test_middleware_catches_readback_contradiction() -> None:
    """Core StillDone Invariant: execute success != verification."""
    mw = VerifiableToolMiddleware()

    # DB state contradicts expected mutation
    db = {"item_1": {"completed": False}}

    @mw.register_verifiable_tool("update_item", "get_item")
    def extract_pred(args: dict, output: dict) -> VerificationPredicate:
        return VerificationPredicate(
            target_id=args["id"],
            attribute="completed",
            operator=PredicateOperator.EQUALS,
            expected_value=True,
        )

    @mw.register_readback_handler("get_item")
    def read_item(target_id: str) -> dict:
        return db[target_id]

    outcome = mw.execute_and_verify(
        tool_name="update_item",
        tool_args={"id": "item_1", "completed": True},
        # Tool executor pretends it succeeded!
        tool_executor=lambda a: {"status": "ok", "http_code": 200},
    )

    # Tool returned success, but mcp-verify catches the contradiction!
    assert outcome.execution.is_success is True
    assert outcome.is_verified is False
    assert outcome.status == VerificationStatus.CONTRADICTED


def test_middleware_handles_tool_execution_failure() -> None:
    mw = VerifiableToolMiddleware()

    def failing_executor(args: dict) -> dict:
        raise RuntimeError("External network connection reset")

    outcome = mw.execute_and_verify(
        tool_name="update_item",
        tool_args={"id": "item_1"},
        tool_executor=failing_executor,
    )

    assert outcome.execution.is_success is False
    assert outcome.is_verified is False
    assert outcome.status == VerificationStatus.EXECUTION_FAILED
    assert "network connection reset" in (outcome.execution.error_message or "")


def test_middleware_handles_readback_handler_failure() -> None:
    mw = VerifiableToolMiddleware()

    @mw.register_verifiable_tool("update_item", "get_item")
    def extract_pred(args: dict, output: dict) -> VerificationPredicate:
        return VerificationPredicate("item_1", "status", PredicateOperator.EQUALS, "done")

    @mw.register_readback_handler("get_item")
    def failing_read(target_id: str) -> dict:
        raise TimeoutError("Readback timeout")

    outcome = mw.execute_and_verify(
        tool_name="update_item",
        tool_args={"id": "item_1"},
        tool_executor=lambda a: {"status": "ok"},
    )

    assert outcome.execution.is_success is True
    assert outcome.is_verified is False
    assert outcome.status == VerificationStatus.READ_BACK_FAILED
