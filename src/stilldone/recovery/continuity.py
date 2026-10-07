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


class RecoveryContinuityError(Exception):
    """Raised when durable recovery state cannot be safely or reliably reconstructed.

    Enforces fail-closed recovery: unreadable, corrupt, gapped, or mismatched
    history MUST NOT be interpreted as zero previous attempts or authorize mutation retry.
    """


def reconstruct_action_recovery_state(
    *,
    action: ActionContract,
    ledger: MissionLedgerPort,
    policy: RetryPolicy | None = None,
) -> ActionRecoveryState:
    """Reconstruct an action's recovery state from durable ledger evidence.

    Laws:
    - Ledger read failure or missing action MUST fail closed (RecoveryContinuityError).
    - Attempt count is reconstructed from durable facts; NEVER reset to 0.
    - Attempt history must be non-conflicting and contiguous; gapped or malformed fails closed.
    - Durably recorded execution success NEVER synthesizes transient retry.
    - Duplicate determination evidence must match mutation identity lineage;
      forged/mismatched fails closed.
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

    # 1. Validate action existence and lineage in durable ledger
    try:
        ledger_action = ledger.get_action(action.action_id)
    except Exception as exc:
        raise RecoveryContinuityError(
            f"Unable to read canonical action {action.action_id} from durable ledger: {exc}"
        ) from exc

    if ledger_action.mission_id != action.mission_id:
        raise RecoveryContinuityError(
            f"Ledger action {action.action_id} mission {ledger_action.mission_id} "
            f"does not match requested action mission {action.mission_id}"
        )
    if ledger_action.action.action_type != action.action_type:
        raise RecoveryContinuityError(
            f"Ledger action {action.action_id} action_type {ledger_action.action.action_type} "
            f"does not match requested action_type {action.action_type}"
        )

    # 2. Fetch all durable evidence records for this action - fail closed on read failure
    try:
        evidence_records = ledger.get_evidence_for_action(action.action_id)
    except Exception as exc:
        raise RecoveryContinuityError(
            f"Unable to read durable recovery evidence for action {action.action_id}: {exc}"
        ) from exc

    # 3. Extract and validate attempt evidence and duplicate evidence
    attempt_records: list[EvidenceRecord] = []
    duplicate_record: DuplicateEvidenceRecord | None = None

    for ev in evidence_records:
        ev_type = ev.payload.get("evidence_type")
        if ev_type == EXECUTION_ATTEMPT_EVIDENCE_TYPE:
            if ev.action_id != action.action_id or ev.mission_id != action.mission_id:
                raise RecoveryContinuityError(
                    f"Attempt evidence {ev.evidence_id} record lineage mismatch: "
                    f"action_id={ev.action_id}, mission_id={ev.mission_id}"
                )
            p = ev.payload
            if p.get("action_id") != str(action.action_id):
                raise RecoveryContinuityError(
                    f"Attempt evidence {ev.evidence_id} payload action_id mismatch: "
                    f"{p.get('action_id')}"
                )
            if p.get("mission_id") != str(action.mission_id):
                raise RecoveryContinuityError(
                    f"Attempt evidence {ev.evidence_id} payload mission_id mismatch: "
                    f"{p.get('mission_id')}"
                )
            if p.get("action_type") != action.action_type.value:
                raise RecoveryContinuityError(
                    f"Attempt evidence {ev.evidence_id} payload action_type mismatch: "
                    f"{p.get('action_type')}"
                )
            att_num = p.get("attempt_number")
            if isinstance(att_num, bool) or not isinstance(att_num, int) or att_num < 1:
                raise RecoveryContinuityError(
                    f"Attempt evidence {ev.evidence_id} has invalid attempt_number: {att_num}"
                )
            if not isinstance(p.get("success"), bool):
                raise RecoveryContinuityError(
                    f"Attempt evidence {ev.evidence_id} has invalid or missing "
                    f"success field: {p.get('success')}"
                )
            success = p["success"]
            cls_name = p.get("classification")
            err_msg = p.get("error_message")

            if success is False:
                if cls_name is None or not isinstance(cls_name, str):
                    raise RecoveryContinuityError(
                        f"Attempt evidence {ev.evidence_id} has success=False but missing "
                        f"or non-string classification: {cls_name!r}"
                    )
                try:
                    RetryClassification(cls_name)
                except ValueError as exc:
                    raise RecoveryContinuityError(
                        f"Attempt evidence {ev.evidence_id} has unknown or invalid failure "
                        f"classification: {cls_name!r}"
                    ) from exc
            else:
                # success is True: must NOT carry failure classification or error message
                if cls_name is not None:
                    raise RecoveryContinuityError(
                        f"Attempt evidence {ev.evidence_id} has success=True but carries "
                        f"contradictory failure classification: {cls_name!r}"
                    )
                if err_msg is not None:
                    raise RecoveryContinuityError(
                        f"Attempt evidence {ev.evidence_id} has success=True but carries "
                        f"contradictory error_message: {err_msg!r}"
                    )
            attempt_records.append(ev)

        elif ev_type == DUPLICATE_DETERMINATION_EVIDENCE_TYPE:
            if ev.action_id != action.action_id or ev.mission_id != action.mission_id:
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} record lineage mismatch: "
                    f"action_id={ev.action_id}, mission_id={ev.mission_id}"
                )
            p = ev.payload
            if p.get("action_id") != str(action.action_id):
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} payload action_id mismatch: "
                    f"{p.get('action_id')}"
                )
            if p.get("mission_id") != str(action.mission_id):
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} payload mission_id mismatch: "
                    f"{p.get('mission_id')}"
                )
            if p.get("action_type") != action.action_type.value:
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} payload action_type mismatch: "
                    f"{p.get('action_type')}"
                )
            if p.get("mutation_id") != intended_mutation.mutation_id:
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} mutation_id mismatch: "
                    f"got {p.get('mutation_id')}, expected {intended_mutation.mutation_id}"
                )
            if p.get("idempotency_key") != intended_mutation.idempotency_key:
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} idempotency_key mismatch: "
                    f"got {p.get('idempotency_key')}, expected {intended_mutation.idempotency_key}"
                )
            if "target_system" in p and p.get("target_system") != intended_mutation.target.system:
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} target_system mismatch: "
                    f"{p.get('target_system')}"
                )
            if (
                "target_resource_kind" in p
                and p.get("target_resource_kind") != intended_mutation.target.resource_kind.value
            ):
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} target_resource_kind mismatch: "
                    f"{p.get('target_resource_kind')}"
                )
            status_str = p.get("status")
            if not isinstance(status_str, str):
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} has non-string or missing status: "
                    f"{status_str}"
                )
            try:
                det_status = DuplicateDeterminationStatus(status_str)
            except Exception as exc:
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} has invalid status {status_str}: {exc}"
                ) from exc

            match_cnt = p.get("match_count", 0)
            try:
                duplicate_record = DuplicateEvidenceRecord(
                    status=det_status,
                    intended_mutation=intended_mutation,
                    match_count=match_cnt,
                    scanned_items=p.get("scanned_items", 0),
                    scanned_pages=p.get("scanned_pages", 0),
                    observed_at=ev.origin.observed_at,
                    matched_resource_id=p.get("matched_resource_id"),
                    error_message=p.get("error_message"),
                    provenance=ev.origin.provenance,
                )
            except Exception as exc:
                raise RecoveryContinuityError(
                    f"Duplicate evidence {ev.evidence_id} failed invariant check: {exc}"
                ) from exc

    # 4. Validate attempt history ordering and contiguous sequence
    prior_attempt_count = len(attempt_records)
    if prior_attempt_count > 0:
        attempt_numbers = [r.payload["attempt_number"] for r in attempt_records]
        expected_sequence = list(range(1, prior_attempt_count + 1))
        if attempt_numbers != expected_sequence:
            raise RecoveryContinuityError(
                f"Non-contiguous, duplicate, or out-of-order attempt numbers in durable ledger: "
                f"got {attempt_numbers}, expected {expected_sequence}"
            )

        # Terminal success invariant:
        # Once an EXECUTION_ATTEMPT for the action durably records success=True,
        # there MUST NOT be any later EXECUTION_ATTEMPT for that same canonical action.
        saw_success_at: int | None = None
        for r in attempt_records:
            att_num = r.payload["attempt_number"]
            if saw_success_at is not None:
                raise RecoveryContinuityError(
                    f"Durable execution success observed at attempt {saw_success_at}, "
                    f"but subsequent attempt {att_num} was found in attempt history. "
                    "Success must be terminal within execution attempt history."
                )
            if r.payload["success"] is True:
                saw_success_at = att_num

    remaining_budget = max(0, effective_ceiling - prior_attempt_count)

    # 5. Inspect latest attempt facts
    last_attempt_success = False
    is_ambiguous = False
    last_error_classification: RetryClassification | None = None
    if attempt_records:
        last_attempt = attempt_records[-1]
        last_payload = last_attempt.payload
        if last_payload.get("success") is True:
            last_attempt_success = True
        else:
            cls_name = last_payload["classification"]
            last_error_classification = RetryClassification(cls_name)
            if last_error_classification == RetryClassification.AMBIGUOUS_TIMEOUT:
                is_ambiguous = True

    # 6. Determine if verification is required before retry
    requires_verification = False
    if strategy.duplicate_risk != DuplicateRiskClass.NONE:
        if is_ambiguous:
            requires_verification = True
        elif (
            not strategy.allows_blind_retry
            and prior_attempt_count > 0
            and remaining_budget > 0
            and not last_attempt_success
        ):
            requires_verification = True
        elif (
            strategy.requires_read_before_retry
            and prior_attempt_count > 0
            and remaining_budget > 0
            and not last_attempt_success
        ):
            requires_verification = True

    # 7. Compute resumption decision
    if duplicate_record is not None:
        # Duplicate determination already took place
        resumption_dec = evaluate_readback_recovery(
            action=action,
            attempt_number=max(1, prior_attempt_count),
            readback_result=duplicate_record.to_readback_result(),
            policy=eff_policy,
        )
    elif last_attempt_success:
        # Durable execution success recorded!
        # NEVER synthesize transient failure; NEVER authorize another mutation.
        # Preserves independent verification boundary.
        if strategy.duplicate_risk == DuplicateRiskClass.NONE:
            resumption_reason = "Durable execution success observed; no further execution required"
        else:
            resumption_reason = (
                "Durable execution success observed; downstream verification remains required"
            )
        resumption_dec = RecoveryDecision(
            action_type=RecoveryActionType.DO_NOT_RETRY,
            action_id=action.action_id,
            attempt_number=prior_attempt_count,
            delay_seconds=0.0,
            reason=resumption_reason,
            idempotency_key=stable_key,
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
        if last_error_classification is None:
            raise RecoveryContinuityError(
                f"Attempt failure for action {action.action_id} lacks canonical classification"
            )
        resumption_dec = evaluate_post_execution_recovery(
            action=action,
            attempt_number=prior_attempt_count,
            error=last_error_classification.value,
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
