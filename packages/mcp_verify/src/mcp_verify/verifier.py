"""Deterministic predicate verifier for mcp-verify."""

from __future__ import annotations

import time
from typing import Any

from mcp_verify.contracts import (
    PredicateOperator,
    VerificationPredicate,
    VerificationResult,
    VerificationStatus,
)


class Verifier:
    """Deterministic verifier evaluating independent observations against predicates."""

    @staticmethod
    def verify_observation(
        predicate: VerificationPredicate,
        observed_properties: dict[str, Any] | None,
        readback_tool_name: str,
        readback_latency_ms: float = 0.0,
    ) -> VerificationResult:
        """Evaluate observed properties against the verification predicate."""
        if observed_properties is None:
            return VerificationResult(
                status=VerificationStatus.READ_BACK_FAILED,
                is_verified=False,
                readback_tool_name=readback_tool_name,
                observed_value=None,
                expected_value=predicate.expected_value,
                readback_latency_ms=readback_latency_ms,
                details=f"Readback tool '{readback_tool_name}' returned empty or null observation.",
            )

        observed_val = observed_properties.get(predicate.attribute)
        is_satisfied = predicate.evaluate(observed_properties)

        if is_satisfied:
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                is_verified=True,
                readback_tool_name=readback_tool_name,
                observed_value=observed_val,
                expected_value=predicate.expected_value,
                readback_latency_ms=readback_latency_ms,
                details=f"Verified attribute '{predicate.attribute}' satisfies predicate.",
            )
        else:
            return VerificationResult(
                status=VerificationStatus.CONTRADICTED,
                is_verified=False,
                readback_tool_name=readback_tool_name,
                observed_value=observed_val,
                expected_value=predicate.expected_value,
                readback_latency_ms=readback_latency_ms,
                details=(
                    f"Contradiction: attribute '{predicate.attribute}' observed as '{observed_val}', "
                    f"expected '{predicate.expected_value}' ({predicate.operator.value})."
                ),
            )
