"""mcp-verify: Deterministic verification middleware for Model Context Protocol tools."""

from __future__ import annotations

from mcp_verify.contracts import (
    PredicateExtractor,
    PredicateOperator,
    ReadbackHandler,
    ToolExecutionResult,
    VerifiableOutcome,
    VerificationPredicate,
    VerificationResult,
    VerificationStatus,
)
from mcp_verify.middleware import (
    ToolRegistrationError,
    VerifiableToolMiddleware,
)
from mcp_verify.verifier import Verifier

__version__ = "0.1.0"

__all__ = [
    "PredicateExtractor",
    "PredicateOperator",
    "ReadbackHandler",
    "ToolExecutionResult",
    "ToolRegistrationError",
    "VerifiableOutcome",
    "VerifiableToolMiddleware",
    "VerificationPredicate",
    "VerificationResult",
    "VerificationStatus",
    "Verifier",
]
