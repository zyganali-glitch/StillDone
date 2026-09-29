"""Phase P-02 contract hardening, schema, serialization, and purity tests."""

from __future__ import annotations

import ast
import json
import pathlib
from datetime import UTC, datetime
from typing import Any

import stilldone.domain
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    ApprovalId,
    AuthorityClass,
)
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    FreshnessContract,
    FreshnessMode,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.execution import (
    AttemptId,
    ExecutionAttempt,
    IdempotencyKey,
    PredicateScope,
    ReconciliationReason,
    ReconciliationRequest,
    ResourceBinding,
    RetryPolicy,
    RetryStrategy,
)
from stilldone.domain.lifecycle import (
    DECLARATIVE_MISSION_TRANSITIONS,
    MissionState,
    StepEvidenceState,
)
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.domain.provenance import (
    EvidenceOrigin,
    EvidenceProvenance,
)

# ---------------------------------------------------------------------------
# Test-local projection helpers (Lossless JSON-compatible primitives)
# NOTE: These are test-local helpers for contract verification only.
# P-03.01 owns canonical serialization and content-addressed evidence IDs.
# ---------------------------------------------------------------------------


def _project_mission_contract(mc: MissionContract) -> dict[str, Any]:
    return {
        "mission_id": str(mc.mission_id),
        "intent": {
            "mission_id": str(mc.intent.mission_id),
            "text": mc.intent.text,
            "captured_at": mc.intent.captured_at.isoformat(),
        },
        "created_at": mc.created_at.isoformat(),
        "schema_version": mc.schema_version,
    }


def _project_predicate(pred: DesiredStatePredicate) -> dict[str, Any]:
    return {
        "predicate_id": str(pred.predicate_id),
        "mission_id": str(pred.mission_id),
        "subject": pred.subject,
        "operator": str(pred.operator),
        "expected_value": pred.expected_value,
        "required": pred.required,
        "freshness": {
            "mode": str(pred.freshness.mode),
            "max_age_seconds": pred.freshness.max_age_seconds,
        },
    }


def _project_action_contract(act: ActionContract) -> dict[str, Any]:
    return {
        "action_id": str(act.action_id),
        "mission_id": str(act.mission_id),
        "action_type": str(act.action_type),
        "target": {
            "system": act.target.system,
            "resource_kind": str(act.target.resource_kind),
            "resource_id": act.target.resource_id,
            "parent_id": act.target.parent_id,
        },
        "parameters": act.parameters.to_dict(),
    }


def _project_approval_grant(app: ApprovalGrant) -> dict[str, Any]:
    return {
        "approval_id": str(app.approval_id),
        "mission_id": str(app.mission_id),
        "action_id": str(app.action_id),
        "authority_class": str(app.authority_class),
        "issued_at": app.issued_at.isoformat(),
        "expires_at": app.expires_at.isoformat(),
        "binding_hash": str(app.binding_hash),
        "action": _project_action_contract(app.action),
    }


def _project_execution_attempt(att: ExecutionAttempt) -> dict[str, Any]:
    return {
        "attempt_id": str(att.attempt_id),
        "action_id": str(att.action_id),
        "idempotency_key": str(att.idempotency_key),
        "attempt_number": att.attempt_number,
        "started_at": att.started_at.isoformat(),
    }


def _project_retry_policy(rp: RetryPolicy) -> dict[str, Any]:
    return {
        "strategy": str(rp.strategy),
        "max_attempts": rp.max_attempts,
    }


def _project_resource_binding(rb: ResourceBinding) -> dict[str, Any]:
    resolved = None
    if rb.resolved_target is not None:
        resolved = {
            "system": rb.resolved_target.system,
            "resource_kind": str(rb.resolved_target.resource_kind),
            "resource_id": rb.resolved_target.resource_id,
            "parent_id": rb.resolved_target.parent_id,
        }
    return {
        "requested_target": {
            "system": rb.requested_target.system,
            "resource_kind": str(rb.requested_target.resource_kind),
            "resource_id": rb.requested_target.resource_id,
            "parent_id": rb.requested_target.parent_id,
        },
        "resolved_target": resolved,
        "is_resolved": rb.is_resolved,
    }


def _project_reconciliation_request(req: ReconciliationRequest) -> dict[str, Any]:
    return {
        "mission_id": str(req.mission_id),
        "reason": str(req.reason),
        "requested_at": req.requested_at.isoformat(),
        "scope": {
            "all_required": req.scope.all_required,
            "selected_predicates": [str(p) for p in req.scope.selected_predicates],
        },
    }


def _project_evidence_origin(eo: EvidenceOrigin) -> dict[str, Any]:
    return {
        "provenance": str(eo.provenance),
        "observed_at": eo.observed_at.isoformat(),
        "recorded_live_origin": (
            str(eo.recorded_live_origin) if eo.recorded_live_origin is not None else None
        ),
    }


# ===========================================================================
# A. Serialization and Lossless Schema Projection Tests
# ===========================================================================


def test_mission_contract_projection_and_json_roundtrip() -> None:
    """A1. MissionContract projects into stable, lossless JSON primitives."""
    now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    contract = MissionContract.create(
        text="Get my family ready for tomorrow morning. We need to leave by 7:30.",
        mission_id=mid,
        created_at=now,
    )
    proj = _project_mission_contract(contract)

    assert proj["mission_id"] == "11111111-1111-4111-8111-111111111111"
    assert proj["intent"]["text"] == (
        "Get my family ready for tomorrow morning. We need to leave by 7:30."
    )
    assert proj["intent"]["captured_at"] == "2026-09-29T12:00:00+00:00"

    assert proj["created_at"] == "2026-09-29T12:00:00+00:00"
    assert proj["schema_version"] == "v1"

    # Lossless JSON serialization
    serialized = json.dumps(proj, sort_keys=True)
    deserialized = json.loads(serialized)
    assert deserialized == proj


def test_desired_state_predicate_projection_and_json_roundtrip() -> None:
    """A2. DesiredStatePredicate projects losslessly."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    pid = PredicateId("22222222-2222-4222-8222-222222222222")
    pred = DesiredStatePredicate.create(
        predicate_id=pid,
        mission_id=mid,
        subject="calendar_event.start_time",
        operator=PredicateOperator.EQUALS,
        expected_value="07:30",
        required=True,
        freshness=FreshnessContract.max_age(300),
    )
    proj = _project_predicate(pred)

    assert proj["predicate_id"] == "22222222-2222-4222-8222-222222222222"
    assert proj["operator"] == "=="
    assert proj["expected_value"] == "07:30"
    assert proj["required"] is True
    assert proj["freshness"]["mode"] == "MAX_AGE"
    assert proj["freshness"]["max_age_seconds"] == 300

    serialized = json.dumps(proj, sort_keys=True)
    assert json.loads(serialized) == proj


def test_action_and_approval_projection_and_json_roundtrip() -> None:
    """A3. ActionContract and ApprovalGrant project losslessly with parameter ordering."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    aid = ActionId("33333333-3333-4333-8333-333333333333")
    target = TargetIdentity(
        system="google_calendar",
        resource_kind=ResourceKind.CALENDAR_EVENT,
        resource_id="evt-456",
        parent_id="demo-cal",
    )
    # Provide unordered dict; NormalizedParameters orders keys deterministically
    raw_params = {"summary": "Leave for school", "start_time": "07:30", "all_day": False}
    action = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=target,
        parameters=raw_params,
    )
    t_issued = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    t_expires = datetime(2026, 9, 29, 12, 15, 0, tzinfo=UTC)
    app_id = ApprovalId("44444444-4444-4444-8444-444444444444")
    grant = ApprovalGrant.create(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=t_issued,
        expires_at=t_expires,
        approval_id=app_id,
    )

    proj_action = _project_action_contract(action)
    assert list(proj_action["parameters"].keys()) == ["all_day", "start_time", "summary"]
    assert proj_action["action_type"] == "calendar.update"
    assert proj_action["target"]["resource_kind"] == "calendar_event"

    proj_grant = _project_approval_grant(grant)
    assert proj_grant["authority_class"] == "REVERSIBLE_APPROVAL_REQUIRED"
    assert len(proj_grant["binding_hash"]) == 64
    assert proj_grant["action"] == proj_action

    serialized = json.dumps(proj_grant, sort_keys=True)
    assert json.loads(serialized) == proj_grant


def test_execution_contracts_projection_and_json_roundtrip() -> None:
    """A4. ExecutionAttempt, RetryPolicy, ResourceBinding, ReconciliationRequest project."""

    aid = ActionId("33333333-3333-4333-8333-333333333333")
    key = IdempotencyKey("55555555-5555-4555-8555-555555555555")
    att_id = AttemptId("66666666-6666-4666-8666-666666666666")
    t0 = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)

    # Attempt
    att = ExecutionAttempt.create(
        action_id=aid,
        idempotency_key=key,
        attempt_number=1,
        started_at=t0,
        attempt_id=att_id,
    )
    proj_att = _project_execution_attempt(att)
    assert proj_att["idempotency_key"] == "55555555-5555-4555-8555-555555555555"
    assert proj_att["attempt_number"] == 1
    assert json.loads(json.dumps(proj_att)) == proj_att

    # RetryPolicy
    rp = RetryPolicy.read_before_retry(max_attempts=3)
    proj_rp = _project_retry_policy(rp)
    assert proj_rp == {"strategy": "READ_BEFORE_RETRY", "max_attempts": 3}
    assert json.loads(json.dumps(proj_rp)) == proj_rp

    # ResourceBinding
    parent = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="list-1",
    )
    child = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK,
        resource_id="task-99",
        parent_id="list-1",
    )
    rb = ResourceBinding.resolved(parent, child)
    proj_rb = _project_resource_binding(rb)
    assert proj_rb["is_resolved"] is True
    assert proj_rb["resolved_target"]["resource_kind"] == "task"
    assert json.loads(json.dumps(proj_rb)) == proj_rb

    # ReconciliationRequest
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    p1 = PredicateId("22222222-2222-4222-8222-222222222222")
    req = ReconciliationRequest.create(
        mission_id=mid,
        reason=ReconciliationReason.POST_EXECUTION_VERIFY,
        requested_at=t0,
        scope=PredicateScope.selective([p1]),
    )
    proj_req = _project_reconciliation_request(req)
    assert proj_req["reason"] == "POST_EXECUTION_VERIFY"
    assert proj_req["scope"]["all_required"] is False
    assert proj_req["scope"]["selected_predicates"] == ["22222222-2222-4222-8222-222222222222"]
    assert json.loads(json.dumps(proj_req)) == proj_req


def test_provenance_projection_and_json_roundtrip() -> None:
    """A5. EvidenceOrigin projects losslessly for live and recorded-live."""
    t0 = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    origin_live = EvidenceOrigin.live_google(observed_at=t0)
    proj_live = _project_evidence_origin(origin_live)
    assert proj_live == {
        "provenance": "LIVE_GOOGLE",
        "observed_at": "2026-09-29T12:00:00+00:00",
        "recorded_live_origin": None,
    }
    assert json.loads(json.dumps(proj_live)) == proj_live

    origin_rec = EvidenceOrigin.recorded_live(
        original_provenance=EvidenceProvenance.LIVE_AWS,
        observed_at=t0,
    )
    proj_rec = _project_evidence_origin(origin_rec)
    assert proj_rec == {
        "provenance": "RECORDED_LIVE",
        "observed_at": "2026-09-29T12:00:00+00:00",
        "recorded_live_origin": "LIVE_AWS",
    }
    assert json.loads(json.dumps(proj_rec)) == proj_rec


def test_repeated_projection_is_strictly_deterministic() -> None:
    """A6. Repeated projection of identical contracts produces bitwise identical JSON."""
    mid = MissionId("11111111-1111-4111-8111-111111111111")
    aid = ActionId("33333333-3333-4333-8333-333333333333")
    target = TargetIdentity(
        system="google_tasks",
        resource_kind=ResourceKind.TASK_LIST,
        resource_id="list-1",
    )
    act = ActionContract.create(
        action_id=aid,
        mission_id=mid,
        action_type=ActionType.TASK_CREATE,
        target=target,
        parameters={"title": "Pack umbrella", "due": "2026-09-30"},
    )
    s1 = json.dumps(_project_action_contract(act), sort_keys=True)
    s2 = json.dumps(_project_action_contract(act), sort_keys=True)
    assert s1 == s2


# ===========================================================================
# B. Phase-Wide Schema Stability Tests (Prevent Silent Enum Expansion)
# ===========================================================================


def test_phase_p02_all_enum_vocabularies_are_frozen() -> None:
    """B1. Assert exact stable vocabularies across all 10 domain enums."""
    # 1. MissionState (exact 10)
    assert len(MissionState) == 10
    assert set(MissionState) == {
        "DRAFT",
        "PLANNED",
        "EXECUTING",
        "NEEDS_APPROVAL",
        "VERIFYING",
        "READY",
        "PARTIAL",
        "FAILED",
        "DRIFTED",
        "CANCELLED",
    }

    # 2. StepEvidenceState (exact 7)
    assert len(StepEvidenceState) == 7
    assert set(StepEvidenceState) == {
        "NOT_RUN",
        "EXECUTED_UNVERIFIED",
        "VERIFIED",
        "CONTRADICTED",
        "BLOCKED",
        "FAILED",
        "STALE",
    }

    # 3. PredicateOperator (exact 8)
    assert len(PredicateOperator) == 8
    assert set(PredicateOperator) == {
        "==",
        "!=",
        "exists",
        "does_not_exist",
        "<",
        "<=",
        ">",
        ">=",
    }

    # 4. FreshnessMode (exact 2)
    assert len(FreshnessMode) == 2
    assert set(FreshnessMode) == {"CURRENT", "MAX_AGE"}

    # 5. ActionType (exact 5)
    assert len(ActionType) == 5
    assert set(ActionType) == {
        "calendar.read",
        "calendar.update",
        "task.read",
        "task.create",
        "weather.read",
    }

    # 6. ResourceKind (exact 4)
    assert len(ResourceKind) == 4
    assert set(ResourceKind) == {
        "calendar_event",
        "task_list",
        "task",
        "weather_location",
    }

    # 7. AuthorityClass (exact 5)
    assert len(AuthorityClass) == 5
    assert set(AuthorityClass) == {
        "READ_ONLY",
        "REVERSIBLE_AUTO",
        "REVERSIBLE_APPROVAL_REQUIRED",
        "EXTERNAL_COMMUNICATION_APPROVAL_REQUIRED",
        "IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED",
    }

    # 8. RetryStrategy (exact 3)
    assert len(RetryStrategy) == 3
    assert set(RetryStrategy) == {
        "NO_RETRY",
        "IDEMPOTENT_RETRY",
        "READ_BEFORE_RETRY",
    }

    # 9. ReconciliationReason (exact 3)
    assert len(ReconciliationReason) == 3
    assert set(ReconciliationReason) == {
        "POST_EXECUTION_VERIFY",
        "EXPLICIT_USER_CHECK",
        "FRESHNESS_REFRESH",
    }

    # 10. EvidenceProvenance (exact 6)
    assert len(EvidenceProvenance) == 6
    assert set(EvidenceProvenance) == {
        "FIXTURE",
        "LOCAL_EXECUTION",
        "LIVE_AWS",
        "LIVE_GOOGLE",
        "LIVE_EXTERNAL",
        "RECORDED_LIVE",
    }


def test_phase_p02_public_domain_exports() -> None:
    """B2. All required P-02 public domain primitives remain exported from stilldone.domain."""
    required_exports = {
        "APPROVAL_BINDING_DOMAIN_SEPARATOR",
        "ActionContract",
        "ActionId",
        "ActionType",
        "Approval",
        "ApprovalGrant",
        "ApprovalId",
        "AttemptId",
        "AuthorityClass",
        "BindingHash",
        "DECLARATIVE_MISSION_TRANSITIONS",
        "DesiredStatePredicate",
        "EvidenceOrigin",
        "EvidenceProvenance",
        "EvidenceProvenanceContract",
        "ExecutionAttempt",
        "ExpectedValueType",
        "FreshnessContract",
        "FreshnessMode",
        "IdempotencyKey",
        "MAX_RETRY_ATTEMPTS_CEILING",
        "MissionContract",
        "MissionId",
        "MissionState",
        "NormalizedParameters",
        "NormalizedScalar",
        "PredicateId",
        "PredicateOperator",
        "PredicateScope",
        "ReconciliationReason",
        "ReconciliationRequest",
        "ResourceBinding",
        "ResourceKind",
        "RetryPolicy",
        "RetryStrategy",
        "StepEvidenceState",
        "TargetIdentity",
        "UserIntentSnapshot",
        "VALID_RECORDED_LIVE_ORIGINS",
        "compute_approval_binding_hash",
    }
    actual_exports = set(stilldone.domain.__all__)
    assert required_exports.issubset(actual_exports)


# ===========================================================================
# C. Forbidden-Transition Tests (Declarative Lifecycle Metadata Validation)
# ===========================================================================


def test_forbidden_transitions_to_ready() -> None:
    """C1. Direct transitions from DRAFT, PLANNED, EXECUTING to READY are strictly forbidden."""
    forbidden_starts = [
        MissionState.DRAFT,
        MissionState.PLANNED,
        MissionState.EXECUTING,
        MissionState.NEEDS_APPROVAL,
        MissionState.PARTIAL,
        MissionState.FAILED,
        MissionState.CANCELLED,
    ]
    for start_state in forbidden_starts:
        assert (start_state, MissionState.READY) not in DECLARATIVE_MISSION_TRANSITIONS, (
            f"Forbidden declarative transition permitted: {start_state} -> READY"
        )


def test_ready_only_arises_from_verifying() -> None:
    """C2. In declarative metadata, READY can ONLY be entered from VERIFYING."""
    incoming_to_ready = [
        src for (src, dst) in DECLARATIVE_MISSION_TRANSITIONS if dst == MissionState.READY
    ]
    assert incoming_to_ready == [MissionState.VERIFYING], (
        f"READY has unexpected source states in declarative transitions: {incoming_to_ready}"
    )


def test_ready_can_transition_to_drifted() -> None:
    """C3. READY -> DRIFTED is permitted and renewable."""
    assert (MissionState.READY, MissionState.DRIFTED) in DECLARATIVE_MISSION_TRANSITIONS

    # DRIFTED can transition back to VERIFYING or EXECUTING or CANCELLED
    assert (MissionState.DRIFTED, MissionState.VERIFYING) in DECLARATIVE_MISSION_TRANSITIONS
    assert (MissionState.DRIFTED, MissionState.EXECUTING) in DECLARATIVE_MISSION_TRANSITIONS
    assert (MissionState.DRIFTED, MissionState.CANCELLED) in DECLARATIVE_MISSION_TRANSITIONS


def test_executing_cannot_bypass_verifying_to_reach_ready() -> None:
    """C4. Model/tool execution success has no path that bypasses VERIFYING to reach READY."""
    executing_destinations = {
        dst for (src, dst) in DECLARATIVE_MISSION_TRANSITIONS if src == MissionState.EXECUTING
    }
    # From EXECUTING, state can move to VERIFYING, PARTIAL, or FAILED. Never READY.
    assert executing_destinations == {
        MissionState.VERIFYING,
        MissionState.PARTIAL,
        MissionState.FAILED,
    }


# ===========================================================================
# D. Static AST Provider-Purity Inspection Across All Domain Modules
# ===========================================================================


def test_domain_source_ast_purity() -> None:
    """D1. Static AST inspection proves zero provider, network, UI, or DB imports in domain."""
    domain_dir = pathlib.Path(stilldone.domain.__file__).parent
    domain_py_files = list(domain_dir.glob("*.py"))
    assert len(domain_py_files) >= 6, "Expected at least 6 domain modules"

    forbidden_packages = {
        "boto3",
        "botocore",
        "strands",
        "agentcore",
        "google",
        "googleapiclient",
        "mcp",
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "flask",
        "fastapi",
        "sqlite3",
        "sqlalchemy",
        "tkinter",
    }

    for py_file in domain_py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_pkg = alias.name.split(".")[0]
                    assert top_pkg not in forbidden_packages, (
                        f"Forbidden import {alias.name!r} in {py_file.name}:{node.lineno}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                top_pkg = node.module.split(".")[0]
                assert top_pkg not in forbidden_packages, (
                    f"Forbidden from-import {node.module!r} in {py_file.name}:{node.lineno}"
                )


# ===========================================================================
# E. Future-Leakage Assertions (P-02 Boundary Protection)
# ===========================================================================


def test_no_database_or_persistence_implementation_in_domain() -> None:
    """E1. Ensure P-02 did not introduce persistence engines, SQLite, or file storage."""
    domain_dir = pathlib.Path(stilldone.domain.__file__).parent
    for py_file in domain_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "sqlite3" not in content
        assert "CREATE TABLE" not in content
        assert "INSERT INTO" not in content
        # Ensure no open() file persistence operations in domain logic
        tree = ast.parse(content, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "open", (
                    f"Forbidden open() call in {py_file.name}:{node.lineno}"
                )


def test_no_generic_evidence_ledger_or_hashing_in_domain() -> None:
    """E2. Ensure P-02 did not introduce P-03 generic evidence IDs, ledger, or content hashing."""
    domain_dir = pathlib.Path(stilldone.domain.__file__).parent
    for py_file in domain_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "EvidenceLedger" not in content
        assert "EvidenceId" not in content
        assert "content_hash" not in content
        assert "canonical_serialize" not in content


def test_no_runtime_transition_engine_or_model_invocation_in_domain() -> None:
    """E3. Ensure P-02 did not introduce runtime transition guards or model invocation."""
    domain_dir = pathlib.Path(stilldone.domain.__file__).parent
    for py_file in domain_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "invoke_model" not in content
        assert "call_model" not in content
        assert "bedrock" not in content
        assert "transition_to" not in content
        assert "advance_state" not in content
