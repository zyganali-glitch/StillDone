"""Provider-neutral deterministic duplicate detection and duplicate evidence state.

Phase P-10.04:
Implements deterministic duplicate detection and immutable duplicate evidence contracts.

Core Architectural Laws:
- Distinguishes four canonical external states:
  * EFFECT_ABSENT (no duplicate; intended effect does not exist)
  * INTENDED_EFFECT_EXISTS (intended effect already exists; 1 matching instance)
  * DUPLICATE_DETECTED (duplicate effect detected; >= 2 matching instances)
  * DETERMINATION_INCONCLUSIVE (inconclusive / provider error / scan limit exceeded)
- Duplicate determination must be evidence-backed from independent external observation.
- Do NOT infer duplicate truth from executor success prose.
- Do NOT infer duplicate truth solely from an idempotency key.
- Binds duplicate evidence to canonical mission, action, target, and IntendedMutationIdentity.
- For TASK_CREATE: bounded independent read-back facts verify whether intended creation occurred.
- Privacy minimization:
  * Zero raw provider payloads or personal details persisted.
  * Sanitized deterministic evidence payload only.
- When duplicates exist, preserves truth explicitly (DUPLICATE_DETECTED); never claims clean success.
- Model / planner output has ZERO authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from stilldone.adapters.calendar import (
    CalendarReadStatus,
    ExpectedCalendarState,
    GoogleCalendarReadAdapter,
    GoogleCalendarReadbackVerifier,
)
from stilldone.adapters.tasks import (
    DuplicateDetectionResult,
    DuplicateDetectionStatus,
    ExpectedTaskState,
    GoogleTasksDuplicateDetector,
    TaskTransport,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.evidence import EvidenceId, compute_evidence_id
from stilldone.ledger import EvidenceRecord
from stilldone.recovery.idempotency import (
    assert_not_planner_for_recovery,
    derive_idempotency_key,
)
from stilldone.recovery.orchestrator import (
    ReadbackOutcome,
    ReadbackVerificationResult,
)
from stilldone.redaction import redact_text
from stilldone.serialization import canonical_serialize, to_canonical_primitive

# ===========================================================================
# Duplicate Determination Status Enum
# ===========================================================================


class DuplicateDeterminationStatus(StrEnum):
    """Canonical classification of mutation effect and duplicate observation."""

    EFFECT_ABSENT = "EFFECT_ABSENT"
    INTENDED_EFFECT_EXISTS = "INTENDED_EFFECT_EXISTS"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    DETERMINATION_INCONCLUSIVE = "DETERMINATION_INCONCLUSIVE"


# ===========================================================================
# Intended Mutation Identity Contract
# ===========================================================================


@dataclass(frozen=True)
class IntendedMutationIdentity:
    """Immutable identity binding an intended mutation to its canonical action and target.

    Ensures duplicate detection and recovery bind strictly to the intended effect
    identity without generating new mutation identities across retries or restarts.
    """

    mission_id: MissionId
    action_id: ActionId
    action_type: ActionType
    target: TargetIdentity
    parameters_digest: str
    idempotency_key: str
    mutation_id: str

    def __post_init__(self) -> None:
        assert_not_planner_for_recovery(self.mission_id, parameter_name="mission_id")
        if not isinstance(self.mission_id, MissionId):
            raise TypeError("mission_id must be MissionId")
        if not isinstance(self.action_id, ActionId):
            raise TypeError("action_id must be ActionId")
        if not isinstance(self.action_type, ActionType):
            raise TypeError("action_type must be ActionType")
        if not isinstance(self.target, TargetIdentity):
            raise TypeError("target must be TargetIdentity")
        if not isinstance(self.parameters_digest, str) or not self.parameters_digest:
            raise ValueError("parameters_digest must be non-empty str")
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key:
            raise ValueError("idempotency_key must be non-empty str")
        if not isinstance(self.mutation_id, str) or not self.mutation_id:
            raise ValueError("mutation_id must be non-empty str")

    def to_dict(self) -> dict[str, Any]:
        """Convert mutation identity to a serializable dictionary."""
        return {
            "mission_id": str(self.mission_id),
            "action_id": str(self.action_id),
            "action_type": self.action_type.value,
            "target": {
                "system": self.target.system,
                "resource_kind": self.target.resource_kind.value,
                "resource_id": self.target.resource_id,
                "parent_id": self.target.parent_id,
            },
            "parameters_digest": self.parameters_digest,
            "idempotency_key": self.idempotency_key,
            "mutation_id": self.mutation_id,
        }


def derive_intended_mutation_identity(action: ActionContract) -> IntendedMutationIdentity:
    """Deterministically derive the immutable IntendedMutationIdentity for an action.

    Guarantees:
    - Same action contract always produces identical IntendedMutationIdentity.
    - Model/planner proposals rejected fail-closed.
    - Stable across retries and restarts.
    """
    assert_not_planner_for_recovery(action, parameter_name="action")
    if not isinstance(action, ActionContract):
        raise TypeError(f"action must be ActionContract, got {type(action).__name__}")

    # Canonical parameters digest
    canon_params = to_canonical_primitive(action.parameters.to_dict())
    params_serialized = canonical_serialize(canon_params)
    params_digest = hashlib.sha256(params_serialized).hexdigest()

    # Stable idempotency key
    idempotency_key = derive_idempotency_key(action, attempt_number=1)

    # Content-addressed mutation_id
    target = action.target
    target_digest = hashlib.sha256(
        f"{target.system}:{target.resource_kind.value}:{target.resource_id}:{target.parent_id}".encode()
    ).hexdigest()

    mutation_seed = (
        f"{action.mission_id}:{action.action_id}:{action.action_type.value}:"
        f"{target_digest}:{params_digest}"
    )
    mutation_id = hashlib.sha256(mutation_seed.encode("utf-8")).hexdigest()

    return IntendedMutationIdentity(
        mission_id=action.mission_id,
        action_id=action.action_id,
        action_type=action.action_type,
        target=action.target,
        parameters_digest=params_digest,
        idempotency_key=idempotency_key,
        mutation_id=mutation_id,
    )


# ===========================================================================
# Duplicate Evidence Record Contract
# ===========================================================================


@dataclass(frozen=True)
class DuplicateEvidenceRecord:
    """Immutable evidence-backed duplicate determination record.

    Privacy & Integrity Laws:
    - Persists zero raw provider body payloads or unrelated records.
    - Captures deterministic counts, timestamps, and sanitized diagnostics.
    - Enforces invariant:
      * INTENDED_EFFECT_EXISTS -> match_count == 1
      * DUPLICATE_DETECTED -> match_count >= 2
      * EFFECT_ABSENT -> match_count == 0
      * DETERMINATION_INCONCLUSIVE -> match_count >= 0
    - Converts directly into canonical EvidenceRecord for ledger append.
    """

    status: DuplicateDeterminationStatus
    intended_mutation: IntendedMutationIdentity
    match_count: int
    scanned_items: int = 0
    scanned_pages: int = 0
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    matched_resource_id: str | None = None
    error_message: str | None = None
    provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION

    def __post_init__(self) -> None:
        assert_not_planner_for_recovery(self.status, parameter_name="status")
        if not isinstance(self.status, DuplicateDeterminationStatus):
            raise TypeError("status must be DuplicateDeterminationStatus")
        if not isinstance(self.intended_mutation, IntendedMutationIdentity):
            raise TypeError("intended_mutation must be IntendedMutationIdentity")
        if isinstance(self.match_count, bool) or not isinstance(self.match_count, int):
            raise TypeError("match_count must be an integer")
        if self.match_count < 0:
            raise ValueError("match_count cannot be negative")
        if isinstance(self.scanned_items, bool) or not isinstance(self.scanned_items, int):
            raise TypeError("scanned_items must be an integer")
        if self.scanned_items < 0:
            raise ValueError("scanned_items cannot be negative")
        if isinstance(self.scanned_pages, bool) or not isinstance(self.scanned_pages, int):
            raise TypeError("scanned_pages must be an integer")
        if self.scanned_pages < 0:
            raise ValueError("scanned_pages cannot be negative")
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware (UTC required)")
        if self.observed_at.tzinfo != UTC:
            object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        if not isinstance(self.provenance, EvidenceProvenance):
            raise TypeError("provenance must be EvidenceProvenance")

        if self.matched_resource_id is not None:
            if not isinstance(self.matched_resource_id, str):
                raise TypeError("matched_resource_id must be a string or None")

        if self.error_message is not None:
            if not isinstance(self.error_message, str):
                raise TypeError("error_message must be a string or None")
            object.__setattr__(self, "error_message", redact_text(self.error_message))

        # Status <-> match_count invariants
        if self.status == DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS:
            if self.match_count != 1:
                raise ValueError(
                    f"INTENDED_EFFECT_EXISTS requires match_count == 1, got {self.match_count}"
                )
        elif self.status == DuplicateDeterminationStatus.DUPLICATE_DETECTED:
            if self.match_count < 2:
                raise ValueError(
                    f"DUPLICATE_DETECTED requires match_count >= 2, got {self.match_count}"
                )
        elif self.status == DuplicateDeterminationStatus.EFFECT_ABSENT:
            if self.match_count != 0:
                raise ValueError(
                    f"EFFECT_ABSENT requires match_count == 0, got {self.match_count}"
                )

    def to_canonical_payload(self) -> dict[str, Any]:
        """Convert to sanitized deterministic dictionary for evidence ledger persistence.

        Does not leak raw provider payload contents.
        """
        payload: dict[str, Any] = {
            "evidence_type": "DUPLICATE_DETERMINATION",
            "status": self.status.value,
            "mutation_id": self.intended_mutation.mutation_id,
            "idempotency_key": self.intended_mutation.idempotency_key,
            "action_id": str(self.intended_mutation.action_id),
            "mission_id": str(self.intended_mutation.mission_id),
            "action_type": self.intended_mutation.action_type.value,
            "target_system": self.intended_mutation.target.system,
            "target_resource_kind": self.intended_mutation.target.resource_kind.value,
            "match_count": self.match_count,
            "scanned_items": self.scanned_items,
            "scanned_pages": self.scanned_pages,
            "observed_at": self.observed_at.isoformat(),
        }
        if self.matched_resource_id:
            payload["matched_resource_id"] = self.matched_resource_id
        if self.error_message:
            payload["error_message"] = self.error_message
        return payload

    def to_evidence_record(self) -> EvidenceRecord:
        """Create a canonical EvidenceRecord bound to the action and mission."""
        origin = EvidenceOrigin(
            provenance=self.provenance,
            observed_at=self.observed_at,
        )
        return EvidenceRecord.create(
            action_id=self.intended_mutation.action_id,
            mission_id=self.intended_mutation.mission_id,
            origin=origin,
            payload=self.to_canonical_payload(),
            created_at=self.observed_at,
        )

    def to_readback_result(self) -> ReadbackVerificationResult:
        """Bridge duplicate evidence to RecoveryOrchestrator ReadbackVerificationResult."""
        outcome_map = {
            DuplicateDeterminationStatus.EFFECT_ABSENT: ReadbackOutcome.EFFECT_ABSENT,
            DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS: ReadbackOutcome.INTENDED_EFFECT_EXISTS,
            DuplicateDeterminationStatus.DUPLICATE_DETECTED: ReadbackOutcome.DUPLICATE_DETECTED,
            DuplicateDeterminationStatus.DETERMINATION_INCONCLUSIVE: ReadbackOutcome.INCONCLUSIVE,
        }
        return ReadbackVerificationResult(
            outcome=outcome_map[self.status],
            action_id=self.intended_mutation.action_id,
            observed_at=self.observed_at,
            match_count=self.match_count,
            details=self.to_canonical_payload(),
            error_message=self.error_message,
        )


# ===========================================================================
# Duplicate Detector Port Protocol
# ===========================================================================


@runtime_checkable
class DuplicateDetectorPort(Protocol):
    """Protocol for provider-neutral duplicate inspection."""

    def detect(self, action: ActionContract) -> DuplicateEvidenceRecord:
        """Inspect external reality and return evidence-backed DuplicateEvidenceRecord."""
        ...


# ===========================================================================
# Canonical Detector Adapters
# ===========================================================================


class GoogleTasksDuplicateDetectorAdapter:
    """Adapts GoogleTasksDuplicateDetector to the provider-neutral DuplicateDetectorPort."""

    def __init__(
        self,
        *,
        detector: GoogleTasksDuplicateDetector,
        provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    ) -> None:
        if not isinstance(detector, GoogleTasksDuplicateDetector):
            raise TypeError("detector must be GoogleTasksDuplicateDetector")
        self._detector = detector
        self._provenance = provenance

    def detect(self, action: ActionContract) -> DuplicateEvidenceRecord:
        assert_not_planner_for_recovery(action, parameter_name="action")
        if action.action_type != ActionType.TASK_CREATE:
            raise ValueError(
                f"GoogleTasksDuplicateDetectorAdapter supports TASK_CREATE only, "
                f"got {action.action_type.value}"
            )

        mutation_identity = derive_intended_mutation_identity(action)
        title = action.parameters.get("title", "")
        due = action.parameters.get("due")

        try:
            expected = ExpectedTaskState(title=title, due=due)
            result: DuplicateDetectionResult = self._detector.detect_duplicates(expected)
        except Exception as exc:
            return DuplicateEvidenceRecord(
                status=DuplicateDeterminationStatus.DETERMINATION_INCONCLUSIVE,
                intended_mutation=mutation_identity,
                match_count=0,
                scanned_items=0,
                scanned_pages=0,
                error_message=f"Tasks scan failed: {exc}",
                provenance=self._provenance,
            )

        status_map = {
            DuplicateDetectionStatus.UNIQUE_MATCH: DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS,
            DuplicateDetectionStatus.DUPLICATE_DETECTED: DuplicateDeterminationStatus.DUPLICATE_DETECTED,
            DuplicateDetectionStatus.NO_MATCH: DuplicateDeterminationStatus.EFFECT_ABSENT,
            DuplicateDetectionStatus.SCAN_LIMIT_EXCEEDED: DuplicateDeterminationStatus.DETERMINATION_INCONCLUSIVE,
            DuplicateDetectionStatus.PROVIDER_ERROR: DuplicateDeterminationStatus.DETERMINATION_INCONCLUSIVE,
        }

        return DuplicateEvidenceRecord(
            status=status_map[result.status],
            intended_mutation=mutation_identity,
            match_count=result.match_count,
            scanned_items=result.scanned_tasks,
            scanned_pages=result.scanned_pages,
            error_message=result.error_message,
            observed_at=result.evaluated_at,
            provenance=self._provenance,
        )


class GoogleCalendarEffectDetectorAdapter:
    """Adapts Google Calendar read adapter for CALENDAR_UPDATE effect verification."""

    def __init__(
        self,
        *,
        read_adapter: GoogleCalendarReadAdapter,
        provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    ) -> None:
        if not isinstance(read_adapter, GoogleCalendarReadAdapter):
            raise TypeError("read_adapter must be GoogleCalendarReadAdapter")
        self._read_adapter = read_adapter
        self._provenance = provenance

    def detect(self, action: ActionContract) -> DuplicateEvidenceRecord:
        assert_not_planner_for_recovery(action, parameter_name="action")
        if action.action_type != ActionType.CALENDAR_UPDATE:
            raise ValueError(
                f"GoogleCalendarEffectDetectorAdapter supports CALENDAR_UPDATE only, "
                f"got {action.action_type.value}"
            )

        mutation_identity = derive_intended_mutation_identity(action)

        # Build read action for the target event
        read_action = ActionContract.create(
            mission_id=action.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=action.target,
            parameters={},
        )

        try:
            read_result = self._read_adapter.read_event(read_action)
        except Exception as exc:
            return DuplicateEvidenceRecord(
                status=DuplicateDeterminationStatus.DETERMINATION_INCONCLUSIVE,
                intended_mutation=mutation_identity,
                match_count=0,
                scanned_items=0,
                error_message=f"Calendar read failed: {exc}",
                provenance=self._provenance,
            )

        if read_result.status == CalendarReadStatus.SUCCESS and read_result.observation is not None:
            obs = read_result.observation
            # Check if all updated fields match the intended mutation parameters
            matches_all = True
            for k, expected_v in action.parameters.to_dict().items():
                actual_v = getattr(obs, k, None)
                if actual_v != expected_v:
                    matches_all = False
                    break

            if matches_all:
                return DuplicateEvidenceRecord(
                    status=DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS,
                    intended_mutation=mutation_identity,
                    match_count=1,
                    scanned_items=1,
                    matched_resource_id=obs.event_id,
                    observed_at=obs.observed_at,
                    provenance=self._provenance,
                )
            else:
                return DuplicateEvidenceRecord(
                    status=DuplicateDeterminationStatus.EFFECT_ABSENT,
                    intended_mutation=mutation_identity,
                    match_count=0,
                    scanned_items=1,
                    observed_at=obs.observed_at,
                    provenance=self._provenance,
                )

        # If not found or error, inconclusive
        return DuplicateEvidenceRecord(
            status=DuplicateDeterminationStatus.DETERMINATION_INCONCLUSIVE,
            intended_mutation=mutation_identity,
            match_count=0,
            scanned_items=0,
            error_message="Event not found or read error",
            provenance=self._provenance,
        )
