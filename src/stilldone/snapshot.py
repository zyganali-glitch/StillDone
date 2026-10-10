"""Durable typed and versioned mission snapshot repository.

Phase P-12.01:
Implements durable, typed, versioned mission snapshots using the existing
approved file-based persistence path.

Core Architectural Laws:
- Snapshot captures complete deterministic mission state:
  * mission identity and contract;
  * desired-state predicates and freshness contracts;
  * lifecycle state;
  * actions, action dependencies, and step execution records;
  * pending approvals and consumed approval records;
  * execution attempts and provider results;
  * bound evidence IDs and historical references.
- Stores deterministic data only: planner proposals have ZERO authority.
- Validates schema/version fail-closed (rejects unknown versions).
- Validates lineage fail-closed (all child entities must match mission identity).
- Validates completeness and corruption fail-closed.
- Never silently converts missing or corrupted data into READY.
- Preserves immutable historical evidence references.
- No second persistence architecture, external database, or new service.
"""

from __future__ import annotations

import json
import os
import tempfile
import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stilldone.approval_consumption import (
    ApprovalConsumptionRecord,
    ApprovalUsageStatus,
)
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalId,
    BindingHash,
)
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    FreshnessMode,
    PredicateId,
    PredicateOperator,
    PredicateTargetBinding,
)
from stilldone.domain.execution import AttemptId, ExecutionAttempt, IdempotencyKey
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId, UserIntentSnapshot
from stilldone.evidence import EvidenceId
from stilldone.execution.state import (
    ActionExecutionStatus,
    ProviderExecutionResult,
    StepExecutionRecord,
)
from stilldone.ledger import (
    MissionLedgerPort,
    RecordNotFoundError,
    _is_verification_evidence,
)
from stilldone.pending_approval import (
    PendingApproval,
    PendingApprovalStatus,
)
from stilldone.serialization import (
    canonical_json,
)

CANONICAL_SNAPSHOT_VERSION: str = "v1"
SUPPORTED_SNAPSHOT_VERSIONS: frozenset[str] = frozenset({CANONICAL_SNAPSHOT_VERSION})

CALENDAR_SUBJECTS: frozenset[str] = frozenset(
    {
        "summary",
        "start",
        "end",
        "all_day",
        "allday",
        "event_id",
        "calendar_id",
        "description",
        "location",
        "start_time",
        "end_time",
    }
)
TASKS_SUBJECTS: frozenset[str] = frozenset(
    {
        "title",
        "due",
        "completed",
        "deleted",
        "task_id",
        "task_list_id",
        "notes",
        "due_date",
    }
)

# Detect planner/model classes if available to reject model authority injections
try:
    from stilldone.planning.contracts import (
        CandidateActionProposal,
        CandidatePlanProposal,
        PlannerInput,
    )

    _PLANNER_TYPES: tuple[type, ...] = (
        CandidatePlanProposal,
        CandidateActionProposal,
        PlannerInput,
    )
except ImportError:
    _PLANNER_TYPES = ()


# ===========================================================================
# Exception Hierarchy
# ===========================================================================


class SnapshotError(Exception):
    """Base exception for all StillDone snapshot operations."""


class SnapshotTypeError(SnapshotError, TypeError):
    """Raised when an argument has an invalid type."""


class SnapshotValueError(SnapshotError, ValueError):
    """Raised when an argument has an invalid value."""


class SnapshotLineageError(SnapshotError, ValueError):
    """Raised when child entities in a snapshot do not match mission identity."""


class SnapshotIntegrityError(SnapshotError, ValueError):
    """Raised when snapshot data is incomplete or has missing required fields."""


class SnapshotCorruptionError(SnapshotError):
    """Raised when snapshot data is corrupt, truncated, or unparseable."""


class UnknownSnapshotVersionError(SnapshotError, ValueError):
    """Raised when snapshot version is unrecognized or unsupported."""


class SnapshotNotFoundError(SnapshotError, KeyError):
    """Raised when a requested snapshot is not found in the repository."""


class SnapshotLedgerConflictError(SnapshotError, ValueError):
    """Raised when snapshot content contradicts the durable mission ledger."""


class PlannerSnapshotAuthorityError(SnapshotError, TypeError):
    """Raised when a planner/model proposal object is passed into snapshot operations."""


def assert_not_planner_for_snapshot(obj: Any, *, parameter_name: str = "argument") -> None:
    """Reject planner/model proposals fail-closed."""
    for pt in _PLANNER_TYPES:
        if isinstance(obj, pt):
            raise PlannerSnapshotAuthorityError(
                f"Model/planner proposal {type(obj).__name__} has ZERO authority "
                f"and cannot be used in mission snapshot ({parameter_name})"
            )


def _parse_bool(val: Any, field_name: str) -> bool:
    """Parse and strictly enforce boolean type fail-closed against string coercion."""
    if isinstance(val, bool):
        return val
    raise SnapshotCorruptionError(
        f"Field {field_name!r} must be a boolean, got {type(val).__name__} ({val!r})"
    )


# ===========================================================================
# Mission Snapshot Aggregate
# ===========================================================================


@dataclass(frozen=True)
class MissionSnapshot:
    """Immutable, typed, versioned snapshot of full mission state."""

    snapshot_id: str
    snapshot_version: str
    mission_id: MissionId
    state: MissionState
    contract: MissionContract
    desired_state: tuple[DesiredStatePredicate, ...]
    actions: tuple[ActionContract, ...]
    action_dependencies: Mapping[ActionId, tuple[ActionId, ...]]
    step_records: Mapping[ActionId, StepExecutionRecord]
    pending_approvals: tuple[PendingApproval, ...]
    consumed_approvals: tuple[ApprovalConsumptionRecord, ...]
    execution_attempts: tuple[ExecutionAttempt, ...]
    evidence_ids: tuple[EvidenceId, ...]
    created_at: datetime
    predicate_bindings: tuple[PredicateTargetBinding, ...] = ()
    is_persisted: bool = False

    def __post_init__(self) -> None:
        assert_not_planner_for_snapshot(self.contract, parameter_name="contract")
        assert_not_planner_for_snapshot(self.actions, parameter_name="actions")
        assert_not_planner_for_snapshot(self.desired_state, parameter_name="desired_state")

        if not isinstance(self.snapshot_id, str) or not self.snapshot_id.strip():
            raise SnapshotValueError("snapshot_id must be a non-empty string")

        if not isinstance(self.snapshot_version, str):
            raise SnapshotTypeError("snapshot_version must be a string")
        if self.snapshot_version not in SUPPORTED_SNAPSHOT_VERSIONS:
            raise UnknownSnapshotVersionError(
                f"Unsupported snapshot version: {self.snapshot_version!r}. "
                f"Supported versions: {sorted(SUPPORTED_SNAPSHOT_VERSIONS)}"
            )

        if not isinstance(self.mission_id, MissionId):
            raise SnapshotTypeError(
                f"mission_id must be a MissionId, got {type(self.mission_id).__name__}"
            )
        if not isinstance(self.state, MissionState):
            raise SnapshotTypeError(
                f"state must be a MissionState, got {type(self.state).__name__}"
            )
        if not isinstance(self.contract, MissionContract):
            raise SnapshotTypeError(
                f"contract must be a MissionContract, got {type(self.contract).__name__}"
            )
        if self.contract.mission_id != self.mission_id:
            raise SnapshotLineageError(
                f"Contract mission_id {self.contract.mission_id} does not match {self.mission_id}"
            )

        if not isinstance(self.desired_state, tuple):
            raise SnapshotTypeError("desired_state must be a tuple")
        for i, pred in enumerate(self.desired_state):
            if not isinstance(pred, DesiredStatePredicate):
                raise SnapshotTypeError(
                    f"desired_state[{i}] must be DesiredStatePredicate, got {type(pred).__name__}"
                )
            if pred.mission_id != self.mission_id:
                raise SnapshotLineageError(
                    f"Predicate {pred.predicate_id} mission_id {pred.mission_id} "
                    f"does not match snapshot mission {self.mission_id}"
                )

        if not isinstance(self.actions, tuple):
            raise SnapshotTypeError("actions must be a tuple")
        known_action_ids: set[ActionId] = set()
        for i, act in enumerate(self.actions):
            if not isinstance(act, ActionContract):
                raise SnapshotTypeError(
                    f"actions[{i}] must be ActionContract, got {type(act).__name__}"
                )
            if act.mission_id != self.mission_id:
                raise SnapshotLineageError(
                    f"Action {act.action_id} mission_id {act.mission_id} "
                    f"does not match snapshot mission {self.mission_id}"
                )
            known_action_ids.add(act.action_id)

        if not isinstance(self.action_dependencies, Mapping):
            raise SnapshotTypeError("action_dependencies must be a Mapping")
        frozen_deps: dict[ActionId, tuple[ActionId, ...]] = {}
        for aid, deps in self.action_dependencies.items():
            if not isinstance(aid, ActionId):
                raise SnapshotTypeError("action_dependencies key must be ActionId")
            if aid not in known_action_ids:
                raise SnapshotLineageError(f"action_dependencies references unknown action {aid}")
            if not isinstance(deps, tuple):
                raise SnapshotTypeError(f"dependencies for action {aid} must be a tuple")
            for dep in deps:
                if not isinstance(dep, ActionId):
                    raise SnapshotTypeError("dependency must be ActionId")
                if dep not in known_action_ids:
                    raise SnapshotLineageError(
                        f"dependency {dep} of action {aid} is not in snapshot actions"
                    )
            frozen_deps[aid] = deps
        object.__setattr__(self, "action_dependencies", types.MappingProxyType(frozen_deps))

        if not isinstance(self.step_records, Mapping):
            raise SnapshotTypeError("step_records must be a Mapping")
        frozen_steps: dict[ActionId, StepExecutionRecord] = {}
        for aid, srec in self.step_records.items():
            if not isinstance(aid, ActionId):
                raise SnapshotTypeError("step_records key must be ActionId")
            if not isinstance(srec, StepExecutionRecord):
                raise SnapshotTypeError("step_records value must be StepExecutionRecord")
            if srec.action_id != aid:
                raise SnapshotLineageError(
                    f"StepExecutionRecord action_id {srec.action_id} does not match key {aid}"
                )
            if aid not in known_action_ids:
                raise SnapshotLineageError(f"StepExecutionRecord references unknown action {aid}")
            frozen_steps[aid] = srec
        object.__setattr__(self, "step_records", types.MappingProxyType(frozen_steps))

        if not isinstance(self.pending_approvals, tuple):
            raise SnapshotTypeError("pending_approvals must be a tuple")
        for i, pa in enumerate(self.pending_approvals):
            if not isinstance(pa, PendingApproval):
                raise SnapshotTypeError(
                    f"pending_approvals[{i}] must be PendingApproval, got {type(pa).__name__}"
                )
            if pa.mission_id != self.mission_id:
                raise SnapshotLineageError(
                    f"PendingApproval {pa.pending_approval_id} mission_id {pa.mission_id} "
                    f"does not match snapshot mission {self.mission_id}"
                )
            if pa.action_id not in known_action_ids:
                raise SnapshotLineageError(
                    f"PendingApproval {pa.pending_approval_id} action_id {pa.action_id} "
                    "not in snapshot actions"
                )

        if not isinstance(self.consumed_approvals, tuple):
            raise SnapshotTypeError("consumed_approvals must be a tuple")
        for i, ca in enumerate(self.consumed_approvals):
            if not isinstance(ca, ApprovalConsumptionRecord):
                raise SnapshotTypeError(
                    f"consumed_approvals[{i}] must be ApprovalConsumptionRecord, "
                    f"got {type(ca).__name__}"
                )
            if ca.mission_id != self.mission_id:
                raise SnapshotLineageError(
                    f"ApprovalConsumptionRecord {ca.approval_id} mission_id {ca.mission_id} "
                    f"does not match snapshot mission {self.mission_id}"
                )
            if ca.action_id not in known_action_ids:
                raise SnapshotLineageError(
                    f"ApprovalConsumptionRecord {ca.approval_id} action_id {ca.action_id} "
                    "not in snapshot actions"
                )

        if not isinstance(self.execution_attempts, tuple):
            raise SnapshotTypeError("execution_attempts must be a tuple")
        for i, att in enumerate(self.execution_attempts):
            if not isinstance(att, ExecutionAttempt):
                raise SnapshotTypeError(
                    f"execution_attempts[{i}] must be ExecutionAttempt, got {type(att).__name__}"
                )
            if att.action_id not in known_action_ids:
                raise SnapshotLineageError(
                    f"ExecutionAttempt {att.attempt_id} action_id {att.action_id} "
                    "not in snapshot actions"
                )

        if not isinstance(self.evidence_ids, tuple):
            raise SnapshotTypeError("evidence_ids must be a tuple")
        for i, eid in enumerate(self.evidence_ids):
            if not isinstance(eid, EvidenceId):
                raise SnapshotTypeError(
                    f"evidence_ids[{i}] must be EvidenceId, got {type(eid).__name__}"
                )

        if not isinstance(self.created_at, datetime):
            raise SnapshotTypeError("created_at must be a datetime instance")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise SnapshotValueError("created_at must be timezone-aware (UTC required)")
        if self.created_at.tzinfo != UTC:
            object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))

        # Enforce READY state invariants fail-closed:
        # Snapshots must never create or confer mission READY authority independently.
        if self.state == MissionState.READY:
            if len(self.desired_state) == 0 or not any(p.required for p in self.desired_state):
                raise SnapshotIntegrityError(
                    "Mission cannot be in READY state with zero required desired state predicates"
                )
            if len(self.actions) > 0 and len(self.evidence_ids) == 0:
                raise SnapshotIntegrityError(
                    "Mission cannot be in READY state with zero evidence records"
                )
            if len(self.desired_state) > 0 and len(self.actions) == 0:
                raise SnapshotIntegrityError(
                    "Cannot construct READY snapshot with predicates but zero actions"
                )
            for act in self.actions:
                if act.action_id not in self.step_records:
                    raise SnapshotIntegrityError(
                        f"Action {act.action_id} missing step execution record in READY snapshot"
                    )
                srec = self.step_records[act.action_id]
                if srec.status != ActionExecutionStatus.EXECUTION_SUCCEEDED:
                    raise SnapshotIntegrityError(
                        f"Action {act.action_id} has non-succeeded status {srec.status.value} "
                        "in READY snapshot"
                    )
                if srec.attempt is None:
                    raise SnapshotIntegrityError(
                        f"Action {act.action_id} missing execution attempt in READY snapshot"
                    )
                if srec.provider_result is None or not srec.provider_result.success:
                    raise SnapshotIntegrityError(
                        f"Action {act.action_id} missing successful provider "
                        "result in READY snapshot"
                    )
            for pa in self.pending_approvals:
                if pa.status == PendingApprovalStatus.PENDING:
                    raise SnapshotIntegrityError(
                        f"Pending approval {pa.pending_approval_id} is still "
                        "PENDING in READY snapshot"
                    )

            from stilldone.authority_policy import get_action_authority_class
            from stilldone.domain.authority import AuthorityClass

            for act in self.actions:
                if (
                    get_action_authority_class(act.action_type)
                    == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
                ):
                    has_consumed = any(
                        ca.action_id == act.action_id and ca.status == ApprovalUsageStatus.CONSUMED
                        for ca in self.consumed_approvals
                    )
                    if not has_consumed:
                        raise SnapshotIntegrityError(
                            f"Action {act.action_id} requires approval but lacks consumed "
                            "approval in READY snapshot"
                        )

            if len(self.predicate_bindings) > 0:
                required_pids = {p.predicate_id for p in self.desired_state if p.required}
                bound_pids = {pb.predicate_id for pb in self.predicate_bindings}
                missing_bindings = required_pids - bound_pids
                if missing_bindings:
                    raise SnapshotIntegrityError(
                        "Required predicates missing target bindings in READY snapshot: "
                        f"{missing_bindings}"
                    )

        if not isinstance(self.predicate_bindings, tuple):
            raise SnapshotTypeError("predicate_bindings must be a tuple")
        known_pred_ids = {p.predicate_id for p in self.desired_state}
        known_action_targets = [a.target for a in self.actions]
        seen_pids: set[PredicateId] = set()
        for i, pb in enumerate(self.predicate_bindings):
            if not isinstance(pb, PredicateTargetBinding):
                raise SnapshotTypeError(
                    f"predicate_bindings[{i}] must be PredicateTargetBinding, "
                    f"got {type(pb).__name__}"
                )
            if pb.mission_id != self.mission_id:
                raise SnapshotLineageError(
                    f"PredicateTargetBinding {pb.predicate_id} mission {pb.mission_id} "
                    f"does not match snapshot mission {self.mission_id}"
                )
            if pb.predicate_id not in known_pred_ids:
                raise SnapshotLineageError(
                    f"PredicateTargetBinding {pb.predicate_id} not in snapshot desired_state"
                )
            if pb.target not in known_action_targets:
                raise SnapshotLineageError(
                    f"PredicateTargetBinding {pb.predicate_id} target does not match "
                    "any action target"
                )
            if pb.predicate_id in seen_pids:
                raise SnapshotIntegrityError(
                    f"Duplicate predicate target binding for predicate {pb.predicate_id}"
                )
            seen_pids.add(pb.predicate_id)

    def get_target_for_predicate(self, predicate_id: PredicateId) -> TargetIdentity:
        """Lookup the authoritative TargetIdentity bound to a predicate."""
        for b in self.predicate_bindings:
            if b.predicate_id == predicate_id:
                return b.target
        raise SnapshotIntegrityError(f"No target binding found for predicate {predicate_id}")

    def project_current_state(
        self,
        historical_receipt: Any | None = None,
        as_of: datetime | None = None,
    ) -> Any:
        """Project authoritative current truth from this snapshot."""
        from stilldone.receipt import project_current_state

        return project_current_state(
            self,
            historical_receipt=historical_receipt,
            as_of=as_of,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to deterministic serializable dictionary."""
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "mission_id": str(self.mission_id),
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "contract": {
                "mission_id": str(self.contract.mission_id),
                "created_at": self.contract.created_at.isoformat(),
                "schema_version": self.contract.schema_version,
                "intent": {
                    "text": self.contract.intent.text,
                    "captured_at": self.contract.intent.captured_at.isoformat(),
                    "mission_id": str(self.contract.intent.mission_id),
                },
            },
            "desired_state": [
                {
                    "predicate_id": str(p.predicate_id),
                    "mission_id": str(p.mission_id),
                    "subject": p.subject,
                    "operator": p.operator.value,
                    "expected_value": p.expected_value,
                    "required": p.required,
                    "freshness": {
                        "mode": p.freshness.mode.value,
                        "max_age_seconds": p.freshness.max_age_seconds,
                    },
                }
                for p in self.desired_state
            ],
            "actions": [
                {
                    "action_id": str(a.action_id),
                    "mission_id": str(a.mission_id),
                    "action_type": a.action_type.value,
                    "target": {
                        "system": a.target.system,
                        "resource_kind": a.target.resource_kind.value,
                        "resource_id": a.target.resource_id,
                        "parent_id": a.target.parent_id,
                    },
                    "parameters": a.parameters.to_dict(),
                }
                for a in self.actions
            ],
            "action_dependencies": {
                str(aid): [str(d) for d in deps] for aid, deps in self.action_dependencies.items()
            },
            "step_records": {
                str(aid): {
                    "action_id": str(sr.action_id),
                    "status": sr.status.value,
                    "attempt": (
                        {
                            "action_id": str(sr.attempt.action_id),
                            "idempotency_key": str(sr.attempt.idempotency_key),
                            "attempt_number": sr.attempt.attempt_number,
                            "started_at": sr.attempt.started_at.isoformat(),
                            "attempt_id": str(sr.attempt.attempt_id),
                        }
                        if sr.attempt is not None
                        else None
                    ),
                    "provider_result": (
                        {
                            "action_type": sr.provider_result.action_type.value,
                            "success": sr.provider_result.success,
                            "status_name": sr.provider_result.status_name,
                            "writes_performed": sr.provider_result.writes_performed,
                            "captured_at": sr.provider_result.captured_at.isoformat(),
                            "details": dict(sr.provider_result.details),
                            "error_message": sr.provider_result.error_message,
                        }
                        if sr.provider_result is not None
                        else None
                    ),
                    "error_message": sr.error_message,
                    "blocked_by": str(sr.blocked_by) if sr.blocked_by is not None else None,
                }
                for aid, sr in self.step_records.items()
            },
            "pending_approvals": [
                {
                    "pending_approval_id": str(pa.pending_approval_id),
                    "mission_id": str(pa.mission_id),
                    "action_id": str(pa.action_id),
                    "action_type": pa.action_type.value,
                    "authority_class": pa.authority_class.value,
                    "target": {
                        "system": pa.target.system,
                        "resource_kind": pa.target.resource_kind.value,
                        "resource_id": pa.target.resource_id,
                        "parent_id": pa.target.parent_id,
                    },
                    "parameters": pa.parameters.to_dict(),
                    "parameters_digest": pa.parameters_digest,
                    "requested_at": pa.requested_at.isoformat(),
                    "decision_contract": pa.decision_contract,
                    "status": pa.status.value,
                    "decision_options": list(pa.decision_options),
                }
                for pa in self.pending_approvals
            ],
            "consumed_approvals": [
                {
                    "approval_id": str(ca.approval_id),
                    "mission_id": str(ca.mission_id),
                    "action_id": str(ca.action_id),
                    "binding_hash": str(ca.binding_hash),
                    "status": ca.status.value,
                    "consumed_at": ca.consumed_at.isoformat(),
                    "attempt_number": ca.attempt_number,
                    "reason": ca.reason,
                }
                for ca in self.consumed_approvals
            ],
            "execution_attempts": [
                {
                    "action_id": str(att.action_id),
                    "idempotency_key": str(att.idempotency_key),
                    "attempt_number": att.attempt_number,
                    "started_at": att.started_at.isoformat(),
                    "attempt_id": str(att.attempt_id),
                }
                for att in self.execution_attempts
            ],
            "evidence_ids": [str(eid) for eid in self.evidence_ids],
            "predicate_bindings": [b.to_dict() for b in self.predicate_bindings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MissionSnapshot:
        """Construct MissionSnapshot from serialized dictionary, failing closed on any flaw."""
        if not isinstance(data, dict):
            raise SnapshotCorruptionError(
                f"Snapshot data must be a dict, got {type(data).__name__}"
            )

        # Check required top-level keys
        required_keys = (
            "snapshot_id",
            "snapshot_version",
            "mission_id",
            "state",
            "created_at",
            "contract",
            "desired_state",
            "actions",
            "action_dependencies",
            "step_records",
            "pending_approvals",
            "consumed_approvals",
            "execution_attempts",
            "evidence_ids",
        )
        for rk in required_keys:
            if rk not in data:
                raise SnapshotIntegrityError(f"Missing required snapshot field: {rk!r}")

        version = data["snapshot_version"]
        if not isinstance(version, str) or version not in SUPPORTED_SNAPSHOT_VERSIONS:
            raise UnknownSnapshotVersionError(f"Unsupported snapshot version: {version!r}")

        try:
            m_id = MissionId(data["mission_id"])
            st = MissionState(data["state"])
            c_at = datetime.fromisoformat(data["created_at"])

            # Contract
            c_data = data["contract"]
            intent_data = c_data["intent"]
            intent = UserIntentSnapshot(
                text=intent_data["text"],
                captured_at=datetime.fromisoformat(intent_data["captured_at"]),
                mission_id=MissionId(intent_data["mission_id"]),
            )
            contract = MissionContract(
                mission_id=MissionId(c_data["mission_id"]),
                intent=intent,
                created_at=datetime.fromisoformat(c_data["created_at"]),
                schema_version=c_data.get("schema_version", "v1"),
            )

            # Desired state
            preds: list[DesiredStatePredicate] = []
            for pd in data["desired_state"]:
                req_val = _parse_bool(pd.get("required", True), "required")
                preds.append(
                    DesiredStatePredicate(
                        predicate_id=PredicateId(pd["predicate_id"]),
                        mission_id=MissionId(pd["mission_id"]),
                        subject=pd["subject"],
                        operator=PredicateOperator(pd["operator"]),
                        expected_value=pd["expected_value"],
                        freshness=FreshnessContract(
                            mode=FreshnessMode(pd["freshness"]["mode"]),
                            max_age_seconds=pd["freshness"].get("max_age_seconds"),
                        ),
                        required=req_val,
                    )
                )

            # Actions
            acts: list[ActionContract] = []
            for ad in data["actions"]:
                td = ad["target"]
                target = TargetIdentity(
                    system=td["system"],
                    resource_kind=ResourceKind(td["resource_kind"]),
                    resource_id=td["resource_id"],
                    parent_id=td.get("parent_id"),
                )
                acts.append(
                    ActionContract(
                        action_id=ActionId(ad["action_id"]),
                        mission_id=MissionId(ad["mission_id"]),
                        action_type=ActionType(ad["action_type"]),
                        target=target,
                        parameters=NormalizedParameters.from_dict(ad["parameters"]),
                    )
                )

            # Action dependencies
            action_deps: dict[ActionId, tuple[ActionId, ...]] = {}
            for aid_str, d_list in data["action_dependencies"].items():
                action_deps[ActionId(aid_str)] = tuple(ActionId(d) for d in d_list)

            # Step records
            s_recs: dict[ActionId, StepExecutionRecord] = {}
            for aid_str, sd in data["step_records"].items():
                aid = ActionId(aid_str)
                att_obj: ExecutionAttempt | None = None
                if sd.get("attempt") is not None:
                    att_data = sd["attempt"]
                    att_obj = ExecutionAttempt(
                        action_id=ActionId(att_data["action_id"]),
                        idempotency_key=IdempotencyKey(att_data["idempotency_key"]),
                        attempt_number=int(att_data["attempt_number"]),
                        started_at=datetime.fromisoformat(att_data["started_at"]),
                        attempt_id=AttemptId(att_data["attempt_id"]),
                    )

                pr_obj: ProviderExecutionResult | None = None
                if sd.get("provider_result") is not None:
                    prd = sd["provider_result"]
                    succ_val = _parse_bool(prd["success"], "success")
                    pr_obj = ProviderExecutionResult(
                        action_type=ActionType(prd["action_type"]),
                        success=succ_val,
                        status_name=str(prd["status_name"]),
                        writes_performed=int(prd.get("writes_performed", 0)),
                        captured_at=datetime.fromisoformat(prd["captured_at"]),
                        details=dict(prd.get("details", {})),
                        error_message=prd.get("error_message"),
                    )

                s_recs[aid] = StepExecutionRecord(
                    action_id=ActionId(sd["action_id"]),
                    status=ActionExecutionStatus(sd["status"]),
                    attempt=att_obj,
                    provider_result=pr_obj,
                    error_message=sd.get("error_message"),
                    blocked_by=ActionId(sd["blocked_by"]) if sd.get("blocked_by") else None,
                )

            # Pending approvals
            import dataclasses

            from stilldone.action_policy import validate_action_contract
            from stilldone.pending_approval import create_pending_approval

            pas: list[PendingApproval] = []
            for pad in data["pending_approvals"]:
                pa_aid = ActionId(pad["action_id"])
                matched_act = next((a for a in acts if a.action_id == pa_aid), None)
                if matched_act is None:
                    raise SnapshotLineageError(
                        f"PendingApproval references action {pa_aid} not present in actions"
                    )
                req_at = datetime.fromisoformat(pad["requested_at"])
                base_pa = create_pending_approval(
                    validate_action_contract(matched_act), requested_at=req_at
                )

                # Strict fail-closed verification against serialized fields
                if pad.get("pending_approval_id") != str(base_pa.pending_approval_id):
                    raise SnapshotIntegrityError(
                        f"Tampered pending_approval_id: {pad.get('pending_approval_id')} "
                        f"!= {base_pa.pending_approval_id}"
                    )
                if pad.get("mission_id") != str(base_pa.mission_id):
                    raise SnapshotLineageError(
                        f"PendingApproval mission_id {pad.get('mission_id')} "
                        f"does not match base {base_pa.mission_id}"
                    )
                if pad.get("action_type") != base_pa.action_type.value:
                    raise SnapshotIntegrityError(
                        f"PendingApproval action_type {pad.get('action_type')} "
                        f"does not match {base_pa.action_type.value}"
                    )
                if pad.get("authority_class") != base_pa.authority_class.value:
                    raise SnapshotIntegrityError(
                        f"PendingApproval authority_class {pad.get('authority_class')} "
                        f"does not match {base_pa.authority_class.value}"
                    )
                if pad.get("parameters_digest") != base_pa.parameters_digest:
                    raise SnapshotIntegrityError("PendingApproval parameters_digest was tampered")
                base_contract_dict = (
                    base_pa.decision_contract.to_dict()
                    if hasattr(base_pa.decision_contract, "to_dict")
                    else base_pa.decision_contract
                )
                if pad.get("decision_contract") != base_contract_dict:
                    raise SnapshotIntegrityError("PendingApproval decision_contract was tampered")

                ser_target = pad.get("target")
                if not isinstance(ser_target, dict) or ser_target != {
                    "system": base_pa.target.system,
                    "resource_kind": base_pa.target.resource_kind.value,
                    "resource_id": base_pa.target.resource_id,
                    "parent_id": base_pa.target.parent_id,
                }:
                    raise SnapshotIntegrityError("PendingApproval target was tampered")

                if pad.get("parameters") != base_pa.parameters.to_dict():
                    raise SnapshotIntegrityError("PendingApproval parameters was tampered")

                status_val = PendingApprovalStatus(pad.get("status", "PENDING"))
                if base_pa.status != status_val:
                    reconstructed_pa = dataclasses.replace(base_pa, status=status_val)
                else:
                    reconstructed_pa = base_pa
                pas.append(reconstructed_pa)

            # Consumed approvals
            cas: list[ApprovalConsumptionRecord] = []
            for cad in data["consumed_approvals"]:
                cas.append(
                    ApprovalConsumptionRecord(
                        approval_id=ApprovalId(cad["approval_id"]),
                        mission_id=MissionId(cad["mission_id"]),
                        action_id=ActionId(cad["action_id"]),
                        binding_hash=BindingHash(cad["binding_hash"]),
                        status=ApprovalUsageStatus(cad["status"]),
                        consumed_at=datetime.fromisoformat(cad["consumed_at"]),
                        attempt_number=int(cad["attempt_number"]),
                        reason=cad.get("reason"),
                    )
                )

            # Execution attempts
            eatts: list[ExecutionAttempt] = []
            for attd in data["execution_attempts"]:
                eatts.append(
                    ExecutionAttempt(
                        action_id=ActionId(attd["action_id"]),
                        idempotency_key=IdempotencyKey(attd["idempotency_key"]),
                        attempt_number=int(attd["attempt_number"]),
                        started_at=datetime.fromisoformat(attd["started_at"]),
                        attempt_id=AttemptId(attd["attempt_id"]),
                    )
                )

            # Evidence IDs
            eids = [EvidenceId(eid_str) for eid_str in data["evidence_ids"]]

            # Predicate bindings
            pbs: list[PredicateTargetBinding] = []
            if "predicate_bindings" in data:
                raw_pbs = data["predicate_bindings"]
                if not isinstance(raw_pbs, list):
                    raise SnapshotCorruptionError("predicate_bindings must be a list")
                for pbd in raw_pbs:
                    pbs.append(PredicateTargetBinding.from_dict(pbd))
            else:
                # Unambiguous legacy derivation check
                distinct_targets = {
                    (
                        a.target.system,
                        a.target.resource_kind,
                        a.target.resource_id,
                        a.target.parent_id,
                    ): a.target
                    for a in acts
                }
                if len(distinct_targets) == 1:
                    sole_target = next(iter(distinct_targets.values()))
                    for p in preds:
                        pbs.append(
                            PredicateTargetBinding.create(
                                predicate_id=p.predicate_id,
                                mission_id=m_id,
                                target=sole_target,
                            )
                        )
                elif len(distinct_targets) == 0 or len(preds) == 0:
                    pass
                else:
                    raise SnapshotCorruptionError(
                        "Ambiguous historical snapshot: multiple distinct action targets present "
                        "without explicit predicate bindings"
                    )

            return cls(
                snapshot_id=str(data["snapshot_id"]),
                snapshot_version=version,
                mission_id=m_id,
                state=st,
                contract=contract,
                desired_state=tuple(preds),
                actions=tuple(acts),
                action_dependencies=action_deps,
                step_records=s_recs,
                pending_approvals=tuple(pas),
                consumed_approvals=tuple(cas),
                execution_attempts=tuple(eatts),
                evidence_ids=tuple(eids),
                created_at=c_at,
                predicate_bindings=tuple(pbs),
            )
        except (SnapshotError, UnknownSnapshotVersionError):
            raise
        except Exception as exc:
            raise SnapshotCorruptionError(f"Failed to parse snapshot data: {exc}") from exc


# ===========================================================================
# Snapshot Creation Helper
# ===========================================================================


def create_mission_snapshot(
    *,
    mission_id: MissionId,
    state: MissionState,
    contract: MissionContract,
    desired_state: Sequence[DesiredStatePredicate],
    actions: Sequence[ActionContract],
    action_dependencies: Mapping[ActionId, Sequence[ActionId]] | None = None,
    step_records: Mapping[ActionId, StepExecutionRecord] | None = None,
    pending_approvals: Sequence[PendingApproval] | None = None,
    consumed_approvals: Sequence[ApprovalConsumptionRecord] | None = None,
    execution_attempts: Sequence[ExecutionAttempt] | None = None,
    evidence_ids: Sequence[EvidenceId] | None = None,
    predicate_bindings: Sequence[PredicateTargetBinding]
    | Mapping[PredicateId, TargetIdentity]
    | None = None,
    snapshot_id: str | None = None,
    snapshot_version: str = CANONICAL_SNAPSHOT_VERSION,
    created_at: datetime | None = None,
) -> MissionSnapshot:
    """Helper to construct a validated, immutable MissionSnapshot."""
    snap_id = (
        snapshot_id or f"snap_{mission_id}_{int((created_at or datetime.now(UTC)).timestamp())}"
    )
    now = created_at or datetime.now(UTC)

    # Validate action and predicate lineage upfront
    for act in actions:
        if act.mission_id != mission_id:
            raise SnapshotLineageError(
                f"Action {act.action_id} mission {act.mission_id} "
                f"does not match snapshot mission {mission_id}"
            )
    for p in desired_state:
        if p.mission_id != mission_id:
            raise SnapshotLineageError(
                f"Predicate {p.predicate_id} mission {p.mission_id} "
                f"does not match snapshot mission {mission_id}"
            )

    # Normalize dependencies
    deps_map: dict[ActionId, tuple[ActionId, ...]] = {}
    if action_dependencies is not None:
        for aid, dlist in action_dependencies.items():
            deps_map[aid] = tuple(dlist)

    # Step records handling
    step_map: dict[ActionId, StepExecutionRecord] = {}
    if step_records is not None:
        step_map.update(step_records)

    # Predicate bindings normalization
    norm_pbs: list[PredicateTargetBinding] = []
    if predicate_bindings is not None:
        if isinstance(predicate_bindings, Mapping):
            for pid, tgt in predicate_bindings.items():
                norm_pbs.append(
                    PredicateTargetBinding.create(
                        predicate_id=pid,
                        mission_id=mission_id,
                        target=tgt,
                    )
                )
        else:
            norm_pbs.extend(predicate_bindings)
    else:
        distinct_targets = {
            (
                a.target.system,
                a.target.resource_kind,
                a.target.resource_id,
                a.target.parent_id,
            ): a.target
            for a in actions
        }
        if len(distinct_targets) == 1 and len(desired_state) > 0:
            sole_target = next(iter(distinct_targets.values()))
            for p in desired_state:
                norm_pbs.append(
                    PredicateTargetBinding.create(
                        predicate_id=p.predicate_id,
                        mission_id=mission_id,
                        target=sole_target,
                    )
                )
        elif len(distinct_targets) == 0 or len(desired_state) == 0:
            pass
        else:
            # When multiple distinct action targets exist, explicit predicate_bindings
            # are strictly required fail-closed. Heuristic guessing is prohibited.
            pass

    if state == MissionState.READY:
        if step_records is None:
            raise SnapshotIntegrityError(
                "Cannot construct READY snapshot with missing step records"
            )
        for act in actions:
            if act.action_id not in step_map:
                raise SnapshotIntegrityError(
                    f"Action {act.action_id} missing step execution record in READY snapshot"
                )
            srec = step_map[act.action_id]
            if srec.status != ActionExecutionStatus.EXECUTION_SUCCEEDED:
                raise SnapshotIntegrityError(
                    f"Action {act.action_id} has non-succeeded status {srec.status.value} "
                    "in READY snapshot"
                )
            if srec.attempt is None:
                raise SnapshotIntegrityError(
                    f"Action {act.action_id} missing execution attempt in READY snapshot"
                )
            if srec.provider_result is None or not srec.provider_result.success:
                raise SnapshotIntegrityError(
                    f"Action {act.action_id} missing successful provider result in READY snapshot"
                )
        if len(actions) > 0 and (not evidence_ids or len(evidence_ids) == 0):
            raise SnapshotIntegrityError("Cannot construct READY snapshot with zero evidence IDs")
    else:
        # Default step records to NOT_RUN for any action missing one in non-READY states
        for act in actions:
            if act.action_id not in step_map:
                step_map[act.action_id] = StepExecutionRecord(
                    action_id=act.action_id,
                    status=ActionExecutionStatus.NOT_RUN,
                )

    return MissionSnapshot(
        snapshot_id=snap_id,
        snapshot_version=snapshot_version,
        mission_id=mission_id,
        state=state,
        contract=contract,
        desired_state=tuple(desired_state),
        actions=tuple(actions),
        action_dependencies=deps_map,
        step_records=step_map,
        pending_approvals=tuple(pending_approvals or ()),
        consumed_approvals=tuple(consumed_approvals or ()),
        execution_attempts=tuple(execution_attempts or ()),
        evidence_ids=tuple(evidence_ids or ()),
        created_at=now,
        predicate_bindings=tuple(norm_pbs),
    )


# ===========================================================================
# Durable Snapshot Repository
# ===========================================================================


class DurableSnapshotRepository:
    """Durable repository for mission snapshots using approved file persistence.

    Supports atomic per-mission file storage or append-only log with fsync.
    Provides fail-closed corruption detection and optional ledger consistency verification.
    """

    def __init__(
        self,
        storage_path: Path | str,
        *,
        ledger: MissionLedgerPort | None = None,
    ) -> None:
        self._path = Path(storage_path).resolve()
        self._ledger = ledger

        # If path ends in .json or .jsonl, treat as a single snapshot file/log.
        # Otherwise, treat as a directory of snapshots.
        self._is_file_mode = self._path.suffix in {".json", ".jsonl"}
        if self._is_file_mode:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self._path.mkdir(parents=True, exist_ok=True)

    @property
    def storage_path(self) -> Path:
        return self._path

    @property
    def ledger(self) -> MissionLedgerPort | None:
        return self._ledger

    def _snapshot_file_for_mission(self, mission_id: MissionId) -> Path:
        if self._is_file_mode:
            return self._path
        return self._path / f"{mission_id}.snapshot.json"

    def verify_consistency_with_ledger(
        self,
        snapshot: MissionSnapshot,
        ledger: MissionLedgerPort | None = None,
    ) -> None:
        """Verify snapshot facts against canonical mission ledger fail-closed."""
        target_ledger = ledger or self._ledger
        if target_ledger is None:
            return

        # 1. Mission must exist in ledger and match contract
        try:
            m_rec = target_ledger.get_mission(snapshot.mission_id)
        except RecordNotFoundError as exc:
            raise SnapshotLedgerConflictError(
                f"Mission {snapshot.mission_id} in snapshot does not exist in ledger"
            ) from exc

        if m_rec.contract != snapshot.contract:
            raise SnapshotLedgerConflictError(
                f"Snapshot mission {snapshot.mission_id} contract does not match ledger"
            )

        if m_rec.state != snapshot.state:
            raise SnapshotLedgerConflictError(
                f"Snapshot state {snapshot.state.value} contradicts "
                f"ledger state {m_rec.state.value}"
            )

        # 2. Every action in snapshot must exist in ledger
        known_action_ids: set[ActionId] = set()
        for act in snapshot.actions:
            try:
                a_rec = target_ledger.get_action(act.action_id)
            except RecordNotFoundError as exc:
                raise SnapshotLedgerConflictError(
                    f"Snapshot action {act.action_id} does not exist in ledger"
                ) from exc
            if a_rec.action != act:
                raise SnapshotLedgerConflictError(
                    f"Snapshot action {act.action_id} contract differs from ledger action"
                )
            known_action_ids.add(act.action_id)

        # 3. Every evidence_id in snapshot must exist in ledger and match mission/action lineage
        for eid in snapshot.evidence_ids:
            try:
                ev_rec = target_ledger.get_evidence(eid)
            except RecordNotFoundError as exc:
                raise SnapshotLedgerConflictError(
                    f"Snapshot evidence {eid} does not exist in ledger"
                ) from exc
            if ev_rec.mission_id != snapshot.mission_id:
                raise SnapshotLedgerConflictError(
                    f"Snapshot evidence {eid} belongs to mission {ev_rec.mission_id}, "
                    f"expected snapshot mission {snapshot.mission_id}"
                )
            if ev_rec.action_id not in known_action_ids:
                raise SnapshotLedgerConflictError(
                    f"Snapshot evidence {eid} belongs to action {ev_rec.action_id} "
                    "not present in snapshot actions"
                )

        # 4. If snapshot claims READY, verify authoritative verification lineage in ledger
        if snapshot.state == MissionState.READY:
            required_pids = {p.predicate_id for p in snapshot.desired_state if p.required}
            bound_pids = {pb.predicate_id for pb in snapshot.predicate_bindings}
            missing_bindings = required_pids - bound_pids
            if missing_bindings:
                raise SnapshotLedgerConflictError(
                    "Required predicates missing target bindings in READY snapshot: "
                    f"{missing_bindings}"
                )
            if len(snapshot.desired_state) > 0 and len(snapshot.actions) == 0:
                raise SnapshotLedgerConflictError(
                    "READY snapshot with desired state predicates must have actions in ledger"
                )
            for act in snapshot.actions:
                act_evidences = target_ledger.get_evidence_for_action(act.action_id)
                if not act_evidences:
                    raise SnapshotLedgerConflictError(
                        f"Action {act.action_id} lacks durable verification evidence in ledger "
                        "for READY mission"
                    )
                if not any(_is_verification_evidence(ev) for ev in act_evidences):
                    raise SnapshotLedgerConflictError(
                        f"Action {act.action_id} lacks durable verification evidence in ledger "
                        "for READY mission"
                    )
            for pb in snapshot.predicate_bindings:
                matching_action_ev = False
                for act in snapshot.actions:
                    if (
                        act.target.system == pb.system
                        and act.target.resource_kind == pb.resource_kind
                        and act.target.resource_id == pb.resource_id
                        and act.target.parent_id == pb.parent_id
                    ):
                        act_evs = target_ledger.get_evidence_for_action(act.action_id)
                        for ev in act_evs:
                            if _is_verification_evidence(ev):
                                ev_pid = ev.payload.get("predicate_id")
                                if ev_pid and str(ev_pid) != str(pb.predicate_id):
                                    continue
                                matching_action_ev = True
                                break
                        if matching_action_ev:
                            break
                if not matching_action_ev:
                    raise SnapshotLedgerConflictError(
                        f"Predicate {pb.predicate_id} bound target lacks verification evidence "
                        "in ledger for READY mission"
                    )

    def save_snapshot(self, snapshot: MissionSnapshot) -> None:
        """Save a snapshot durably with atomic write and fsync.

        Verifies ledger consistency if a ledger is configured.
        """
        assert_not_planner_for_snapshot(snapshot, parameter_name="snapshot")
        if not isinstance(snapshot, MissionSnapshot):
            raise SnapshotTypeError(
                f"snapshot must be MissionSnapshot, got {type(snapshot).__name__}"
            )

        if self._ledger is not None:
            self.verify_consistency_with_ledger(snapshot, self._ledger)

        serialized = canonical_json(snapshot.to_dict())

        if self._is_file_mode:
            # Append-only log file with flush and fsync
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(serialized + "\n")
                f.flush()
                os.fsync(f.fileno())
            object.__setattr__(snapshot, "is_persisted", True)
        else:
            # Atomic file replacement in directory
            target_file = self._snapshot_file_for_mission(snapshot.mission_id)
            temp_dir = self._path
            fd, tmp_path_str = tempfile.mkstemp(prefix="snap_", suffix=".tmp", dir=temp_dir)
            tmp_path = Path(tmp_path_str)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(serialized + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target_file)
                object.__setattr__(snapshot, "is_persisted", True)
            except Exception:
                if tmp_path.exists():
                    tmp_path.unlink()
                raise

    def load_snapshot(self, mission_id: MissionId) -> MissionSnapshot:
        """Load a mission snapshot from durable storage fail-closed."""
        if not isinstance(mission_id, MissionId):
            raise SnapshotTypeError(
                f"mission_id must be MissionId, got {type(mission_id).__name__}"
            )

        if self._is_file_mode:
            if not self._path.exists():
                raise SnapshotNotFoundError(f"Snapshot file {self._path} does not exist")
            target_mission_str = str(mission_id)
            found: MissionSnapshot | None = None
            with open(self._path, encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        data = json.loads(line_str)
                    except Exception as exc:
                        raise SnapshotCorruptionError(
                            f"Malformed JSON in snapshot log at line {line_num}: {exc}"
                        ) from exc
                    if not isinstance(data, dict):
                        raise SnapshotCorruptionError(
                            f"Line {line_num} in snapshot log is not a JSON object"
                        )
                    if data.get("mission_id") == target_mission_str:
                        found = MissionSnapshot.from_dict(data)
            if found is None:
                if self._ledger is not None and hasattr(self._ledger, "get_transition_snapshot"):
                    proj = self._ledger.get_transition_snapshot(mission_id)
                    if proj is not None:
                        recovered = MissionSnapshot.from_dict(proj)
                        self.verify_consistency_with_ledger(recovered, self._ledger)
                        try:
                            self.save_snapshot(recovered)
                        except Exception as exc:
                            raise SnapshotIntegrityError(
                                "Failed to heal snapshot projection to durable storage for mission "
                                f"{mission_id}: {exc}"
                            ) from exc
                        found = recovered
                if found is None:
                    raise SnapshotNotFoundError(
                        f"No snapshot found for mission {mission_id} in {self._path}"
                    )
            if self._ledger is not None:
                if hasattr(self._ledger, "get_transition_snapshot"):
                    proj = self._ledger.get_transition_snapshot(mission_id)
                    if proj is not None and (
                        proj.get("snapshot_id") != found.snapshot_id
                        or proj.get("state") != found.state.value
                    ):
                        recovered = MissionSnapshot.from_dict(proj)
                        self.verify_consistency_with_ledger(recovered, self._ledger)
                        try:
                            self.save_snapshot(recovered)
                        except Exception as exc:
                            raise SnapshotIntegrityError(
                                "Failed to heal snapshot projection to durable storage for mission "
                                f"{mission_id}: {exc}"
                            ) from exc
                        found = recovered
                self.verify_consistency_with_ledger(found, self._ledger)
            if found is not None:
                object.__setattr__(found, "is_persisted", True)
            return found
        else:
            target_file = self._snapshot_file_for_mission(mission_id)
            if not target_file.exists():
                if self._ledger is not None and hasattr(self._ledger, "get_transition_snapshot"):
                    proj = self._ledger.get_transition_snapshot(mission_id)
                    if proj is not None:
                        recovered = MissionSnapshot.from_dict(proj)
                        self.verify_consistency_with_ledger(recovered, self._ledger)
                        try:
                            self.save_snapshot(recovered)
                        except Exception as exc:
                            raise SnapshotIntegrityError(
                                "Failed to heal snapshot projection to durable storage for mission "
                                f"{mission_id}: {exc}"
                            ) from exc
                        return recovered
                raise SnapshotNotFoundError(
                    f"Snapshot file for mission {mission_id} not found at {target_file}"
                )
            try:
                with open(target_file, encoding="utf-8") as f:
                    content = f.read()
                if not content.strip():
                    raise SnapshotCorruptionError(
                        f"Snapshot file for mission {mission_id} is empty (0 bytes)"
                    )
                data = json.loads(content)
            except (SnapshotError, UnknownSnapshotVersionError):
                raise
            except Exception as exc:
                raise SnapshotCorruptionError(
                    f"Failed to read snapshot file for mission {mission_id}: {exc}"
                ) from exc

            snapshot = MissionSnapshot.from_dict(data)
            if snapshot.mission_id != mission_id:
                raise SnapshotLineageError(
                    f"Snapshot file for mission {mission_id} contains conflicting "
                    f"mission_id {snapshot.mission_id}"
                )
            if self._ledger is not None:
                if hasattr(self._ledger, "get_transition_snapshot"):
                    proj = self._ledger.get_transition_snapshot(mission_id)
                    if proj is not None and (
                        proj.get("snapshot_id") != snapshot.snapshot_id
                        or proj.get("state") != snapshot.state.value
                    ):
                        recovered = MissionSnapshot.from_dict(proj)
                        self.verify_consistency_with_ledger(recovered, self._ledger)
                        try:
                            self.save_snapshot(recovered)
                        except Exception as exc:
                            raise SnapshotIntegrityError(
                                "Failed to heal snapshot projection to durable storage for mission "
                                f"{mission_id}: {exc}"
                            ) from exc
                        snapshot = recovered
                self.verify_consistency_with_ledger(snapshot, self._ledger)
            object.__setattr__(snapshot, "is_persisted", True)
            return snapshot

    def _receipt_file_for_mission(self, mission_id: MissionId) -> Path:
        if self._is_file_mode:
            return self._path
        return self._path / f"{mission_id}.receipt.json"

    def save_receipt(self, receipt: Any) -> None:
        """Save a historical receipt projection durably with atomic write and fsync."""
        assert_not_planner_for_snapshot(receipt, parameter_name="receipt")
        from stilldone.receipt import ReceiptProjection

        if not isinstance(receipt, ReceiptProjection):
            raise SnapshotTypeError(
                f"receipt must be ReceiptProjection, got {type(receipt).__name__}"
            )
        if not receipt.is_historical:
            raise SnapshotValueError("Only historical receipt projections can be saved")

        if self._ledger is not None:
            try:
                self._ledger.get_mission(receipt.mission_id)
            except RecordNotFoundError as exc:
                raise SnapshotLedgerConflictError(
                    f"Mission {receipt.mission_id} in receipt does not exist in ledger"
                ) from exc
            for eid in receipt.evidence_ids:
                try:
                    self._ledger.get_evidence(eid)
                except RecordNotFoundError as exc:
                    raise SnapshotLedgerConflictError(
                        f"Evidence {eid} in receipt does not exist in ledger"
                    ) from exc

        serialized = canonical_json(receipt.to_canonical())

        if self._is_file_mode:
            entry = {"_type": "receipt", **receipt.to_canonical()}
            ser_entry = canonical_json(entry)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(ser_entry + "\n")
                f.flush()
                os.fsync(f.fileno())
        else:
            target_file = self._receipt_file_for_mission(receipt.mission_id)
            fd, tmp_path_str = tempfile.mkstemp(prefix="rcpt_", suffix=".tmp", dir=self._path)
            tmp_path = Path(tmp_path_str)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(serialized + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target_file)
            except Exception:
                if tmp_path.exists():
                    tmp_path.unlink()
                raise

    def load_receipt(self, mission_id: MissionId) -> Any:
        """Load a historical receipt projection from durable storage fail-closed."""
        if not isinstance(mission_id, MissionId):
            raise SnapshotTypeError(
                f"mission_id must be MissionId, got {type(mission_id).__name__}"
            )
        from stilldone.receipt import ReceiptNotFoundError, ReceiptProjection

        if self._is_file_mode:
            if not self._path.exists():
                raise ReceiptNotFoundError(f"Receipt file {self._path} does not exist")
            target_mission_str = str(mission_id)
            found_data: dict[str, Any] | None = None
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        d = json.loads(line_str)
                    except Exception:
                        continue
                    if (
                        isinstance(d, dict)
                        and d.get("_type") == "receipt"
                        and d.get("mission_id") == target_mission_str
                    ):
                        found_data = d
            if found_data is None:
                raise ReceiptNotFoundError(
                    f"No receipt found for mission {mission_id} in {self._path}"
                )
            clean_data = {k: v for k, v in found_data.items() if k != "_type"}
            return ReceiptProjection.from_dict(clean_data)
        else:
            target_file = self._receipt_file_for_mission(mission_id)
            if not target_file.exists():
                raise ReceiptNotFoundError(
                    f"Receipt file for mission {mission_id} not found at {target_file}"
                )
            try:
                with open(target_file, encoding="utf-8") as f:
                    content = f.read()
                if not content.strip():
                    raise SnapshotCorruptionError(
                        f"Receipt file for mission {mission_id} is empty (0 bytes)"
                    )
                data = json.loads(content)
            except Exception as exc:
                if isinstance(exc, (SnapshotError, UnknownSnapshotVersionError)):
                    raise
                raise SnapshotCorruptionError(f"Failed to read receipt file: {exc}") from exc
            return ReceiptProjection.from_dict(data)

    def get_historical_receipt(self, mission_id: MissionId) -> Any | None:
        """Get the historical receipt for a mission, or None if not present."""
        from stilldone.receipt import ReceiptNotFoundError

        try:
            return self.load_receipt(mission_id)
        except (ReceiptNotFoundError, SnapshotNotFoundError):
            return None
