"""Domain contracts and models for mcp-verify."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class PredicateOperator(str, Enum):
    """Supported operators for independent predicate evaluation."""

    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    CONTAINS = "CONTAINS"
    EXISTS = "EXISTS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"


class VerificationStatus(str, Enum):
    """Outcome status of the verification pipeline."""

    VERIFIED = "VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    READ_BACK_FAILED = "READ_BACK_FAILED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    UNVERIFIED_MUTATION = "UNVERIFIED_MUTATION"


@dataclass(frozen=True)
class VerificationPredicate:
    """Deterministic predicate evaluated against independent read-back state."""

    target_id: str
    attribute: str
    operator: PredicateOperator
    expected_value: Any
    max_age_seconds: float = 300.0

    def evaluate(self, observed_properties: dict[str, Any]) -> bool:
        """Evaluate predicate against observed properties dictionary."""
        if self.operator == PredicateOperator.EXISTS:
            return self.attribute in observed_properties

        if self.attribute not in observed_properties:
            return False

        observed_val = observed_properties[self.attribute]

        if self.operator == PredicateOperator.EQUALS:
            return observed_val == self.expected_value
        elif self.operator == PredicateOperator.NOT_EQUALS:
            return observed_val != self.expected_value
        elif self.operator == PredicateOperator.CONTAINS:
            if isinstance(observed_val, (list, tuple, set, str)):
                return self.expected_value in observed_val
            return False
        elif self.operator == PredicateOperator.GREATER_THAN:
            return observed_val > self.expected_value
        elif self.operator == PredicateOperator.LESS_THAN:
            return observed_val < self.expected_value

        return False


@dataclass(frozen=True)
class ToolExecutionResult:
    """Result of executing the underlying mutation tool."""

    tool_name: str
    is_success: bool
    output_payload: dict[str, Any]
    writes_performed: int = 1
    execution_latency_ms: float = 0.0
    error_message: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    """Result of independent read-back and predicate verification."""

    status: VerificationStatus
    is_verified: bool
    readback_tool_name: str
    observed_value: Any
    expected_value: Any
    readback_latency_ms: float = 0.0
    timestamp_epoch_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    details: str = ""


@dataclass(frozen=True)
class VerifiableOutcome:
    """Combined outcome binding tool execution to independent verification proof."""

    tool_name: str
    execution: ToolExecutionResult
    verification: VerificationResult

    @property
    def is_verified(self) -> bool:
        """True if and only if both tool execution succeeded and read-back verified expected state."""
        return self.execution.is_success and self.verification.is_verified

    @property
    def status(self) -> VerificationStatus:
        return self.verification.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "is_verified": self.is_verified,
            "status": self.status.value,
            "execution": {
                "is_success": self.execution.is_success,
                "writes_performed": self.execution.writes_performed,
                "latency_ms": self.execution.execution_latency_ms,
                "error": self.execution.error_message,
            },
            "verification": {
                "status": self.verification.status.value,
                "is_verified": self.verification.is_verified,
                "readback_tool_name": self.verification.readback_tool_name,
                "observed_value": self.verification.observed_value,
                "expected_value": self.verification.expected_value,
                "latency_ms": self.verification.readback_latency_ms,
                "details": self.verification.details,
            },
        }


# Type alias for predicate extractor function
PredicateExtractor = Callable[[dict[str, Any], dict[str, Any]], VerificationPredicate]

# Type alias for readback handler function
ReadbackHandler = Callable[[str], dict[str, Any]]
