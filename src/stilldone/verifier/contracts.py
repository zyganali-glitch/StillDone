"""Domain and dispatch contracts for independent verification.

Phase P-09.01:
Defines immutable verification requests, independent read-back observations,
and strict independence laws separating execution result payloads from verification facts.

Strict Independence Laws:
- execution result payload != verification observation.
- ProviderExecutionResult MUST NOT be accepted as proof of desired state.
- Verification is strictly read-only; zero mutation routes exist in verifier.
- Planner / model prose has ZERO verification authority.
- Observations must be fresh, bounded, and independently observed from canonical read ports.
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from stilldone.domain.action import (
    ActionContract,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.desired_state import DesiredStatePredicate
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.state import ProviderExecutionResult

# ===========================================================================
# Verifier Exception Hierarchy
# ===========================================================================


class VerifierError(Exception):
    """Base exception for all verifier errors."""


class ExecutionPayloadSubstitutionError(VerifierError, TypeError):
    """Raised when an execution result payload is illegally passed as verification input."""


class UnsupportedVerificationTargetError(VerifierError, ValueError):
    """Raised when a verification request targets an unsupported system or resource kind."""


class MissingVerifierRouteError(VerifierError, KeyError):
    """Raised when no verification read port is registered for a target system/resource."""


class VerifierTargetMismatchError(VerifierError, ValueError):
    """Raised when target identity does not match the action contract lineage."""


class MalformedObservationError(VerifierError, ValueError):
    """Raised when an external read-back observation is malformed or invalid."""


class VerifierReadError(VerifierError, RuntimeError):
    """Raised when an independent read-back operation fails at transport/provider level."""


# ===========================================================================
# Verification Request Contract
# ===========================================================================


@dataclass(frozen=True)
class VerificationRequest:
    """Immutable request for independent read-back verification.

    Binds a canonical ActionContract and concrete TargetIdentity to an independent
    read-back verification attempt.
    Optionally references a machine-checkable DesiredStatePredicate.

    Strictly forbids ProviderExecutionResult or ExecutionAttempt substitution.
    """

    mission_id: MissionId
    action: ActionContract
    target: TargetIdentity
    predicate: DesiredStatePredicate | None = None

    def __post_init__(self) -> None:
        # Strict type assertions
        if not isinstance(self.mission_id, MissionId):
            raise TypeError(
                f"mission_id must be a MissionId instance, got {type(self.mission_id).__name__}"
            )

        if not isinstance(self.action, ActionContract):
            # Check explicitly for illegal execution payload substitution
            if isinstance(self.action, (ProviderExecutionResult, ExecutionAttempt)):
                raise ExecutionPayloadSubstitutionError(
                    f"Execution payload {type(self.action).__name__} cannot substitute "
                    "for canonical ActionContract in VerificationRequest"
                )
            raise TypeError(
                f"action must be an ActionContract instance, got {type(self.action).__name__}"
            )

        if not isinstance(self.target, TargetIdentity):
            if isinstance(self.target, (ProviderExecutionResult, ExecutionAttempt)):
                raise ExecutionPayloadSubstitutionError(
                    f"Execution payload {type(self.target).__name__} cannot substitute "
                    "for TargetIdentity in VerificationRequest"
                )
            raise TypeError(
                f"target must be a TargetIdentity instance, got {type(self.target).__name__}"
            )

        if self.predicate is not None and not isinstance(self.predicate, DesiredStatePredicate):
            raise TypeError(
                f"predicate must be DesiredStatePredicate or None, "
                f"got {type(self.predicate).__name__}"
            )

        # Lineage assertion: action.mission_id must match request.mission_id
        if self.action.mission_id != self.mission_id:
            raise VerifierTargetMismatchError(
                f"ActionContract mission_id {self.action.mission_id} does not match "
                f"VerificationRequest mission_id {self.mission_id}"
            )

        # Predicate lineage assertion
        if self.predicate is not None and self.predicate.mission_id != self.mission_id:
            raise VerifierTargetMismatchError(
                f"DesiredStatePredicate mission_id {self.predicate.mission_id} does not match "
                f"VerificationRequest mission_id {self.mission_id}"
            )

    @classmethod
    def create(
        cls,
        *,
        action: ActionContract,
        target: TargetIdentity | None = None,
        predicate: DesiredStatePredicate | None = None,
    ) -> VerificationRequest:
        """Create a VerificationRequest derived from an ActionContract.

        If target is None, derives target from action.target (appropriate for read
        actions and in-place updates).
        """
        if isinstance(action, (ProviderExecutionResult, ExecutionAttempt)):
            raise ExecutionPayloadSubstitutionError(
                f"Execution payload {type(action).__name__} cannot be passed to "
                "VerificationRequest.create"
            )
        if not isinstance(action, ActionContract):
            raise TypeError(f"action must be an ActionContract, got {type(action).__name__}")

        effective_target = target if target is not None else action.target
        return cls(
            mission_id=action.mission_id,
            action=action,
            target=effective_target,
            predicate=predicate,
        )


# ===========================================================================
# Independent Verification Observation Contract
# ===========================================================================


@dataclass(frozen=True)
class VerificationObservation:
    """Normalized, bounded fact record independently observed from an external read port.

    Laws:
    - Never constructed from ProviderExecutionResult or mutation return payloads.
    - Captures deterministic properties observed directly from independent read adapter.
    - Timestamp is strictly timezone-aware UTC.
    - Does NOT assert or imply VERIFIED or READY on its own.
    """

    target: TargetIdentity
    observed_at: datetime
    exists: bool
    properties: Mapping[str, Any] = field(default_factory=dict)
    provenance: EvidenceProvenance = EvidenceProvenance.FIXTURE
    raw_observation: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, TargetIdentity):
            raise TypeError(f"target must be a TargetIdentity, got {type(self.target).__name__}")

        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime instance")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise MalformedObservationError("observed_at must be timezone-aware")
        if self.observed_at.tzinfo != UTC:
            object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))

        if not isinstance(self.exists, bool):
            raise TypeError(f"exists must be a bool, got {type(self.exists).__name__}")

        if not isinstance(self.provenance, EvidenceProvenance):
            raise TypeError(
                f"provenance must be an EvidenceProvenance instance, "
                f"got {type(self.provenance).__name__}"
            )

        # Disallow ProviderExecutionResult as raw_observation
        if isinstance(self.raw_observation, (ProviderExecutionResult, ExecutionAttempt)):
            raise ExecutionPayloadSubstitutionError(
                f"raw_observation cannot be an execution payload "
                f"({type(self.raw_observation).__name__})"
            )

        if not isinstance(self.properties, Mapping):
            raise TypeError(f"properties must be a Mapping, got {type(self.properties).__name__}")
        object.__setattr__(self, "properties", types.MappingProxyType(dict(self.properties)))

    @property
    def system(self) -> str:
        return self.target.system

    @property
    def resource_kind(self) -> ResourceKind:
        return self.target.resource_kind

    @property
    def resource_id(self) -> str:
        return self.target.resource_id

    @property
    def parent_id(self) -> str | None:
        return self.target.parent_id

    def get_property(self, key: str, default: Any = None) -> Any:
        """Safely retrieve a property from the observation."""
        return self.properties.get(key, default)
