"""Deterministic process restart, resume, and recovery continuity from durable ledger.

Phase P-10.05:
Reconstructs in-flight mutation and recovery state following process restart or crash.

Core Architectural Laws:
- Reuses the canonical StillDone ledger/state architecture (MissionLedgerPort).
- Does NOT build an unrelated second persistence subsystem.
- Specifically focused on recovery continuity for an interrupted in-flight mutation/retry.
- On restart, reconstructs deterministic recovery state:
  * mission and action identity;
  * intended mutation identity (stable content-addressed);
  * stable idempotency identity;
  * prior execution attempt count (never reset merely because process restarted);
  * ambiguous outcome state (never converted to SUCCESS);
  * required verification / read-before-retry state (never silently re-executed);
  * duplicate evidence / determination;
  * remaining bounded attempt eligibility (attempt ceiling survives restart).
- Model / planner proposals have ZERO authority over recovery state reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from stilldone.domain.action import ActionContract, ActionId, ActionType
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceOrigin, EvidenceProvenance
from stilldone.ledger import EvidenceRecord, MissionLedgerPort
from stilldone.recovery.duplicate import (
    DuplicateDeterminationStatus,
    DuplicateEvidenceRecord,
    IntendedMutationIdentity,
    derive_intended_mutation_identity,
)
from stilldone.recovery.idempotency import (
    DuplicateRiskClass,
    assert_not_planner_for_recovery,
    derive_idempotency_key,
    get_idempotency_strategy,
)
from stilldone.recovery.orchestrator import (
    RecoveryActionType,
    RecoveryDecision,
    evaluate_post_execution_recovery,
    evaluate_readback_recovery,
)
from stilldone.recovery.retry import (
    RetryClassification,
    RetryPolicy,
    classify_error,
)
from stilldone.redaction import redact_text

EXECUTION_ATTEMPT_EVIDENCE_TYPE = "EXECUTION_ATTEMPT"
DUPLICATE_DETERMINATION_EVIDENCE_TYPE = "DUPLICATE_DETERMINATION"


# ===========================================================================
# Durable Attempt & Duplicate Recording Helpers
# ===========================================================================


def record_execution_attempt(
    *,
    ledger: MissionLedgerPort,
    action: ActionContract,
    attempt_number: int,
    error: Exception | str | int | None = None,
    provenance: EvidenceProvenance = EvidenceProvenance.LOCAL_EXECUTION,
    observed_at: datetime | None = None,
) -> EvidenceRecord:
    """Record an execution attempt as an immutable EvidenceRecord in the durable ledger.

    Guarantees that attempt occurrences, errors, and classifications are durably
    preserved before any retry or recovery decision.
    """
    assert_not_planner_for_recovery(action, parameter_name="action")
    if error is not None:
        assert_not_planner_for_recovery(error, parameter_name="error")
    if not isinstance(ledger, MissionLedgerPort):
        raise TypeError("ledger must implement MissionLedgerPort")
    if not isinstance(action, ActionContract):
        raise TypeError("action must be ActionContract")
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise TypeError("attempt_number must be an integer")
    if attempt_number < 1:
        raise ValueError("attempt_number must be >= 1")

    now = observed_at or datetime.now(UTC)
    classification = classify_error(error).value if error is not None else None
    error_msg = redact_text(str(error)) if error is not None else None

    payload: dict[str, Any] = {
        "evidence_type": EXECUTION_ATTEMPT_EVIDENCE_TYPE,
        "attempt_number": attempt_number,
        "action_id": str(action.action_id),
        "mission_id": str(action.mission_id),
        "action_type": action.action_type.value,
        "success": error is None,
        "recorded_at": now.isoformat(),
    }
    if error_msg:
        payload["error_message"] = error_msg
    if classification:
        payload["classification"] = classification

    origin = EvidenceOrigin(provenance=provenance, observed_at=now)
    record = EvidenceRecord.create(
        action_id=action.action_id,
        mission_id=action.mission_id,
        origin=origin,
        payload=payload,
        created_at=now,
    )
    ledger.append_evidence(record)
    return record


def record_duplicate_determination(
    *,
    ledger: MissionLedgerPort,
    duplicate_evidence: DuplicateEvidenceRecord | None = None,
    evidence: DuplicateEvidenceRecord | None = None,
) -> EvidenceRecord:
    """Record duplicate determination evidence into the durable ledger."""
    target_evidence = duplicate_evidence if duplicate_evidence is not None else evidence
    if target_evidence is None:
        raise ValueError("Either duplicate_evidence or evidence must be provided")
    assert_not_planner_for_recovery(target_evidence, parameter_name="duplicate_evidence")
    if not isinstance(ledger, MissionLedgerPort):
        raise TypeError("ledger must implement MissionLedgerPort")
    if not isinstance(target_evidence, DuplicateEvidenceRecord):
        raise TypeError("duplicate_evidence must be DuplicateEvidenceRecord")

    record = target_evidence.to_evidence_record()
    ledger.append_evidence(record)
    return record


# ===========================================================================
# Action Recovery State Contract
# ===========================================================================


@dataclass(frozen=True)
class ActionRecoveryState:
    """Immutable reconstructed recovery state of an action following restart.

    Captures durable operational facts without losing attempt history or
    accidentally authorizing blind mutation retries.
    """

    mission_id: MissionId
    action_id: ActionId
    action_type: ActionType
    intended_mutation: IntendedMutationIdentity
    stable_idempotency_key: str
    prior_attempt_count: int
    is_ambiguous_outcome: bool
    requires_verification_before_retry: bool
    duplicate_evidence: DuplicateEvidenceRecord | None
    remaining_attempt_budget: int
    resumption_decision: RecoveryDecision

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, MissionId):
            raise TypeError("mission_id must be MissionId")
        if not isinstance(self.action_id, ActionId):
            raise TypeError("action_id must be ActionId")
        if not isinstance(self.action_type, ActionType):
            raise TypeError("action_type must be ActionType")
        if not isinstance(self.intended_mutation, IntendedMutationIdentity):
            raise TypeError("intended_mutation must be IntendedMutationIdentity")
        if not isinstance(self.stable_idempotency_key, str):
            raise TypeError("stable_idempotency_key must be a str")
        if isinstance(self.prior_attempt_count, bool) or not isinstance(
            self.prior_attempt_count, int
        ):
            raise TypeError("prior_attempt_count must be an integer")
        if self.prior_attempt_count < 0:
            raise ValueError("prior_attempt_count cannot be negative")
        if not isinstance(self.is_ambiguous_outcome, bool):
            raise TypeError("is_ambiguous_outcome must be a bool")
        if not isinstance(self.requires_verification_before_retry, bool):
            raise TypeError("requires_verification_before_retry must be a bool")
        if isinstance(self.remaining_attempt_budget, bool) or not isinstance(
            self.remaining_attempt_budget, int
        ):
            raise TypeError("remaining_attempt_budget must be an integer")
        if self.remaining_attempt_budget < 0:
            raise ValueError("remaining_attempt_budget cannot be negative")
        if not isinstance(self.resumption_decision, RecoveryDecision):
            raise TypeError("resumption_decision must be RecoveryDecision")

    def to_dict(self) -> dict[str, Any]:
        """Convert recovery state to serializable dictionary."""
        return {
            "mission_id": str(self.mission_id),
            "action_id": str(self.action_id),
            "action_type": self.action_type.value,
            "intended_mutation": self.intended_mutation.to_dict(),
            "stable_idempotency_key": self.stable_idempotency_key,
            "prior_attempt_count": self.prior_attempt_count,
            "is_ambiguous_outcome": self.is_ambiguous_outcome,
            "requires_verification_before_retry": self.requires_verification_before_retry,
            "duplicate_evidence": (
                self.duplicate_evidence.to_canonical_payload() if self.duplicate_evidence else None
            ),
            "remaining_attempt_budget": self.remaining_attempt_budget,
            "resumption_decision": self.resumption_decision.to_dict(),
        }


# ===========================================================================
# Deterministic State Reconstruction Engine
# ===========================================================================


def reconstruct_action_recovery_state(
    *,
    action: ActionContract,
    ledger: MissionLedgerPort,
    policy: RetryPolicy | None = None,
) -> ActionRecoveryState:
    """Reconstruct an action's recovery state from durable ledger evidence.

    Laws:
    - Attempt count is reconstructed from durable facts; NEVER reset to 0.
    - Intended mutation identity is deterministic; NEVER regenerated differently.
    - Ambiguous outcome (e.g. timeout) is preserved; NEVER converted to SUCCESS.
    - High-duplicate-risk mutations (TASK_CREATE) and ambiguous timeouts preserve
      requires_verification_before_retry = True; NEVER silently re-executed.
    - Attempt budget ceiling is preserved; remaining = max(0, ceiling - prior_attempts).
    - Model/planner proposals have ZERO authority.
    """
    assert_not_planner_for_recovery(action, parameter_name="action")
    if policy is not None:
        assert_not_planner_for_recovery(policy, parameter_name="policy")
    if not isinstance(ledger, MissionLedgerPort):
        raise TypeError("ledger must implement MissionLedgerPort")
    if not isinstance(action, ActionContract):
        raise TypeError("action must be ActionContract")

    strategy = get_idempotency_strategy(action)
    intended_mutation = derive_intended_mutation_identity(action)
    stable_key = derive_idempotency_key(action, attempt_number=1)
    eff_policy = policy or RetryPolicy()
    effective_ceiling = min(eff_policy.max_attempts, strategy.max_attempt_ceiling)

    # 1. Fetch all durable evidence records for this action
    try:
        evidence_records = ledger.get_evidence_for_action(action.action_id)
    except Exception:
        evidence_records = []

    # 2. Extract attempt evidence and duplicate evidence
    attempt_records: list[EvidenceRecord] = []
    duplicate_record: DuplicateEvidenceRecord | None = None

    for ev in evidence_records:
        ev_type = ev.payload.get("evidence_type")
        if ev_type == EXECUTION_ATTEMPT_EVIDENCE_TYPE:
            attempt_records.append(ev)
        elif ev_type == "DUPLICATE_DETERMINATION":
            status_val = ev.payload.get("status")
            if status_val:
                try:
                    det_status = DuplicateDeterminationStatus(status_val)
                    duplicate_record = DuplicateEvidenceRecord(
                        status=det_status,
                        intended_mutation=intended_mutation,
                        match_count=ev.payload.get("match_count", 0),
                        scanned_items=ev.payload.get("scanned_items", 0),
                        scanned_pages=ev.payload.get("scanned_pages", 0),
                        observed_at=ev.origin.observed_at,
                        matched_resource_id=ev.payload.get("matched_resource_id"),
                        error_message=ev.payload.get("error_message"),
                        provenance=ev.origin.provenance,
                    )
                except Exception:
                    pass

    prior_attempt_count = len(attempt_records)
    remaining_budget = max(0, effective_ceiling - prior_attempt_count)

    # 3. Determine if last attempt was an ambiguous outcome
    is_ambiguous = False
    last_error_classification: RetryClassification | None = None
    if attempt_records:
        last_attempt = attempt_records[-1]
        cls_name = last_attempt.payload.get("classification")
        if cls_name:
            try:
                last_error_classification = RetryClassification(cls_name)
            except ValueError:
                pass
        if last_error_classification == RetryClassification.AMBIGUOUS_TIMEOUT:
            is_ambiguous = True

    # 4. Determine if verification is required before retry
    requires_verification = False
    if strategy.duplicate_risk != DuplicateRiskClass.NONE:
        if is_ambiguous:
            requires_verification = True
        elif (
            strategy.requires_read_before_retry and prior_attempt_count > 0 and remaining_budget > 0
        ):
            requires_verification = True

    # 5. Compute resumption decision
    if duplicate_record is not None:
        # Duplicate determination already took place
        resumption_dec = evaluate_readback_recovery(
            action=action,
            attempt_number=max(1, prior_attempt_count),
            readback_result=duplicate_record.to_readback_result(),
            policy=eff_policy,
        )
    elif prior_attempt_count == 0:
        # Action has never been attempted yet
        resumption_dec = RecoveryDecision(
            action_type=RecoveryActionType.RETRY,
            action_id=action.action_id,
            attempt_number=1,
            delay_seconds=0.0,
            reason="Initial execution attempt eligible",
            idempotency_key=stable_key,
        )
    elif remaining_budget == 0:
        # Attempt ceiling was reached before crash/restart
        resumption_dec = RecoveryDecision(
            action_type=RecoveryActionType.DO_NOT_RETRY,
            action_id=action.action_id,
            attempt_number=prior_attempt_count,
            delay_seconds=0.0,
            reason=(
                f"Attempt ceiling reached ({prior_attempt_count} >= {effective_ceiling}); "
                "retry budget exhausted"
            ),
            retry_classification=last_error_classification,
            idempotency_key=stable_key,
        )
    elif requires_verification:
        # In-flight timeout / ambiguous mutation requires verification before retry
        resumption_dec = RecoveryDecision(
            action_type=RecoveryActionType.REQUIRES_VERIFICATION,
            action_id=action.action_id,
            attempt_number=prior_attempt_count,
            delay_seconds=0.0,
            reason=(
                "Process restarted during in-flight mutation; requires independent "
                "read-before-retry to determine whether intended effect exists"
            ),
            retry_classification=last_error_classification,
            idempotency_key=stable_key,
        )
    else:
        # Safe retry (e.g. read-only action on transient error)
        resumption_dec = evaluate_post_execution_recovery(
            action=action,
            attempt_number=prior_attempt_count,
            error=(
                last_error_classification.value
                if last_error_classification
                else "transient_failure"
            ),
            policy=eff_policy,
        )

    return ActionRecoveryState(
        mission_id=action.mission_id,
        action_id=action.action_id,
        action_type=action.action_type,
        intended_mutation=intended_mutation,
        stable_idempotency_key=stable_key,
        prior_attempt_count=prior_attempt_count,
        is_ambiguous_outcome=is_ambiguous,
        requires_verification_before_retry=requires_verification,
        duplicate_evidence=duplicate_record,
        remaining_attempt_budget=remaining_budget,
        resumption_decision=resumption_dec,
    )
