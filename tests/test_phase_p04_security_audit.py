"""Phase P-04 cross-boundary security audit tests.

Freezes integrated cross-module security invariants that no individual
P-04 micro-task suite can express cleanly.

Scope:
- No individual P-04 security result exposes VERIFIED/READY semantics.
- No forbidden provider/network imports in P-04 policy modules.
- Canonical action vocabulary remains exactly five.
- Authority classification remains exact.
- P-04 modules cannot directly execute providers.
- Future-phase module/route absence.
- Cross-gate non-substitutability.

This file is part of the P-04.07 security/threat-model audit.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from stilldone.action_policy import (
    ACTION_POLICIES,
    ValidatedActionContract,
    validate_action_contract,
)
from stilldone.authority_policy import (
    ACTION_AUTHORITY_TABLE,
    AuthorityDecisionStatus,
    evaluate_authority,
)
from stilldone.demo_isolation import (
    CalendarOutOfScopeError,
    DemoIsolationStatus,
    DemoResourceScope,
    verify_demo_resource_isolation,
)
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    AuthorityClass,
)
from stilldone.domain.lifecycle import MissionState, StepEvidenceState
from stilldone.domain.mission import MissionId
from stilldone.endpoint_protection import (
    CallerClass,
    EndpointProtectionPolicy,
    EndpointRequestAssessment,
    RateSnapshot,
    RequestExposureClass,
    evaluate_endpoint_admission,
)
from stilldone.redaction import redact_with_metadata
from stilldone.transitions import (
    IllegalStatePromotionError,
    assert_can_promote_to_ready,
)

# ===========================================================================
# Helpers
# ===========================================================================

P04_POLICY_MODULES = (
    "stilldone.config",
    "stilldone.redaction",
    "stilldone.capture",
    "stilldone.action_policy",
    "stilldone.authority_policy",
    "stilldone.demo_isolation",
    "stilldone.endpoint_protection",
)

FORBIDDEN_PROVIDER_IMPORTS = frozenset(
    {
        "boto3",
        "botocore",
        "google",
        "googleapiclient",
        "google_auth_oauthlib",
        "google.oauth2",
        "openmeteo",
        "openmeteo_sdk",
        "mcp",
        "starlette",
        "fastapi",
        "uvicorn",
        "httpx",
        "aiohttp",
        "requests",
        "strands",
        "strands_agents",
    }
)

SRC_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "stilldone"


def _make_calendar_read_contract() -> tuple[ActionContract, ValidatedActionContract]:
    """Create a valid calendar.read contract for testing."""
    action = ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.CALENDAR_READ,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="event-001",
            parent_id="demo-cal-001",
        ),
        parameters={},
    )
    return action, validate_action_contract(action)


def _make_calendar_update_contract() -> tuple[ActionContract, ValidatedActionContract]:
    """Create a valid calendar.update contract for testing."""
    action = ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.CALENDAR_UPDATE,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id="event-002",
            parent_id="demo-cal-001",
        ),
        parameters={"summary": "Updated title"},
    )
    return action, validate_action_contract(action)


# ===========================================================================
# INVARIANT 1: Canonical action vocabulary is exactly 5
# ===========================================================================


class TestCanonicalActionVocabulary:
    """Freeze the canonical action vocabulary at exactly 5 entries."""

    def test_action_type_has_exactly_five_members(self) -> None:
        assert len(ActionType) == 5

    def test_action_type_members_are_exact(self) -> None:
        expected = {
            "calendar.read",
            "calendar.update",
            "task.read",
            "task.create",
            "weather.read",
        }
        assert {at.value for at in ActionType} == expected

    def test_policy_table_covers_all_action_types(self) -> None:
        assert set(ACTION_POLICIES.keys()) == set(ActionType)
        assert len(ACTION_POLICIES) == 5

    def test_authority_table_covers_all_action_types(self) -> None:
        assert set(ACTION_AUTHORITY_TABLE.keys()) == set(ActionType)
        assert len(ACTION_AUTHORITY_TABLE) == 5


# ===========================================================================
# INVARIANT 2: Authority classification remains exact
# ===========================================================================


class TestExactAuthorityClassification:
    """Freeze the exact authority classification for all 5 actions."""

    def test_calendar_read_is_read_only(self) -> None:
        assert ACTION_AUTHORITY_TABLE[ActionType.CALENDAR_READ] == AuthorityClass.READ_ONLY

    def test_calendar_update_is_reversible_approval_required(self) -> None:
        assert (
            ACTION_AUTHORITY_TABLE[ActionType.CALENDAR_UPDATE]
            == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
        )

    def test_task_read_is_read_only(self) -> None:
        assert ACTION_AUTHORITY_TABLE[ActionType.TASK_READ] == AuthorityClass.READ_ONLY

    def test_task_create_is_reversible_auto(self) -> None:
        assert ACTION_AUTHORITY_TABLE[ActionType.TASK_CREATE] == AuthorityClass.REVERSIBLE_AUTO

    def test_weather_read_is_read_only(self) -> None:
        assert ACTION_AUTHORITY_TABLE[ActionType.WEATHER_READ] == AuthorityClass.READ_ONLY


# ===========================================================================
# INVARIANT 3: No individual security result exposes VERIFIED/READY
# ===========================================================================


class TestNoSecurityResultExposesVerifiedOrReady:
    """Verify that no P-04 security gate result can produce VERIFIED or READY."""

    def test_validated_action_contract_has_no_verified_or_ready_attribute(self) -> None:
        _, validated = _make_calendar_read_contract()
        attrs = dir(validated)
        for forbidden in ("verified", "ready", "is_verified", "is_ready", "VERIFIED", "READY"):
            assert forbidden not in attrs, (
                f"ValidatedActionContract exposes forbidden attribute: {forbidden}"
            )

    def test_authority_decision_authorized_has_no_verified_or_ready(self) -> None:
        _, validated = _make_calendar_read_contract()
        decision = evaluate_authority(validated, at=datetime.now(tz=UTC))
        assert decision.is_authorized
        attrs = dir(decision)
        for forbidden in ("verified", "ready", "is_verified", "is_ready"):
            assert forbidden not in attrs, (
                f"AuthorityDecision exposes forbidden attribute: {forbidden}"
            )
        assert decision.status not in {"VERIFIED", "READY", "EXECUTED"}

    def test_demo_isolation_result_has_no_verified_or_ready(self) -> None:
        _, validated = _make_calendar_read_contract()
        scope = DemoResourceScope(calendar_id="demo-cal-001", task_list_id="demo-tl-001")
        result = verify_demo_resource_isolation(validated, scope)
        assert result.status == DemoIsolationStatus.ISOLATED
        attrs = dir(result)
        for forbidden in ("verified", "ready", "is_verified", "is_ready"):
            assert forbidden not in attrs, (
                f"DemoIsolationResult exposes forbidden attribute: {forbidden}"
            )

    def test_endpoint_allow_decision_has_no_verified_or_ready(self) -> None:
        now = datetime.now(tz=UTC)
        policy = EndpointProtectionPolicy(
            max_requests_per_window=100,
            max_paid_live_requests_per_window=10,
            internal_gross_ceiling=Decimal("50.00"),
        )
        snapshot = RateSnapshot(
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(hours=1),
            total_requests=0,
            paid_live_requests=0,
        )
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )
        decision = evaluate_endpoint_admission(request, policy, snapshot, at=now)
        assert decision.is_allowed
        attrs = dir(decision)
        for forbidden in ("verified", "ready", "is_verified", "is_ready"):
            assert forbidden not in attrs, (
                f"EndpointAdmissionDecision exposes forbidden attribute: {forbidden}"
            )

    def test_redaction_metadata_has_no_verified_or_ready(self) -> None:
        _, meta = redact_with_metadata({"token": "secret_value"})
        attrs = dir(meta)
        for forbidden in ("verified", "ready", "is_verified", "is_ready"):
            assert forbidden not in attrs, (
                f"RedactionMetadata exposes forbidden attribute: {forbidden}"
            )


# ===========================================================================
# INVARIANT 4: No forbidden provider/network imports in P-04 modules
# ===========================================================================


class TestNoProviderImportsInP04Modules:
    """Verify P-04 policy modules import no provider SDKs or network libraries."""

    @pytest.mark.parametrize("module_name", P04_POLICY_MODULES)
    def test_no_forbidden_imports_via_ast(self, module_name: str) -> None:
        """Parse module source via AST and verify no forbidden imports."""
        mod = importlib.import_module(module_name)
        source_file = inspect.getfile(mod)
        source_path = pathlib.Path(source_file)
        source_text = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=source_file)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level = alias.name.split(".")[0]
                    assert top_level not in FORBIDDEN_PROVIDER_IMPORTS, (
                        f"Forbidden import '{alias.name}' found in {module_name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_level = node.module.split(".")[0]
                    assert top_level not in FORBIDDEN_PROVIDER_IMPORTS, (
                        f"Forbidden import from '{node.module}' found in {module_name}"
                    )


# ===========================================================================
# INVARIANT 5: P-04 modules cannot directly execute providers
# ===========================================================================


class TestNoProviderExecutionCapability:
    """Verify P-04 policy modules contain no provider execution functions."""

    @pytest.mark.parametrize("module_name", P04_POLICY_MODULES)
    def test_no_execute_or_call_provider_functions(self, module_name: str) -> None:
        mod = importlib.import_module(module_name)
        public_names = [name for name in dir(mod) if not name.startswith("_")]
        for name in public_names:
            lower = name.lower()
            assert "execute_provider" not in lower, (
                f"Provider execution function found: {module_name}.{name}"
            )
            assert "call_google" not in lower
            assert "call_aws" not in lower
            assert "invoke_bedrock" not in lower
            assert "invoke_lambda" not in lower


# ===========================================================================
# INVARIANT 6: Future-phase module/route absence
# ===========================================================================


class TestFuturePhaseAbsence:
    """Verify no P-05/P-06/P-07 implementation exists in src/stilldone/."""

    def test_no_mcp_server_module(self) -> None:
        """No MCP server, transport, or tool route modules exist."""
        forbidden_modules = [
            "mcp_server",
            "mcp_transport",
            "mcp_routes",
            "mcp_tools",
            "streamable_http",
            "auth_middleware",
        ]
        for mod_name in forbidden_modules:
            mod_path = SRC_ROOT / f"{mod_name}.py"
            assert not mod_path.exists(), f"Future-phase module found: {mod_path}"
            pkg_path = SRC_ROOT / mod_name
            assert not pkg_path.is_dir(), f"Future-phase package found: {pkg_path}"

    def test_no_provider_adapter_modules(self) -> None:
        """No Google/Open-Meteo provider adapter modules exist."""
        forbidden_modules = [
            "calendar_adapter",
            "google_calendar",
            "tasks_adapter",
            "google_tasks",
            "open_meteo",
            "weather_adapter",
            "readback_verifier",
            "read_back",
        ]
        for mod_name in forbidden_modules:
            mod_path = SRC_ROOT / f"{mod_name}.py"
            assert not mod_path.exists(), f"Future-phase module found: {mod_path}"
            pkg_path = SRC_ROOT / mod_name
            assert not pkg_path.is_dir(), f"Future-phase package found: {pkg_path}"

    def test_no_planner_or_model_integration(self) -> None:
        """No P-07 planner/model integration modules exist."""
        forbidden_modules = ["planner", "model_integration", "agent", "strands_agent"]
        for mod_name in forbidden_modules:
            mod_path = SRC_ROOT / f"{mod_name}.py"
            assert not mod_path.exists(), f"Future-phase module found: {mod_path}"


# ===========================================================================
# INVARIANT 7: Cross-gate non-substitutability
# ===========================================================================


class TestCrossGateNonSubstitutability:
    """Verify no single P-04 result can substitute for another gate."""

    def test_validated_action_does_not_imply_authority(self) -> None:
        """ValidatedActionContract does NOT imply authority."""
        _, validated = _make_calendar_update_contract()
        # Having a validated contract does not mean it's authorized
        decision = evaluate_authority(validated, at=datetime.now(tz=UTC))
        # calendar.update requires approval — should NOT be authorized without it
        assert not decision.is_authorized
        assert decision.status == AuthorityDecisionStatus.APPROVAL_REQUIRED

    def test_authority_allow_does_not_imply_demo_isolation(self) -> None:
        """AuthorityDecision ALLOW does NOT imply demo isolation."""
        _, validated = _make_calendar_read_contract()
        decision = evaluate_authority(validated, at=datetime.now(tz=UTC))
        assert decision.is_authorized
        # Authority allows but wrong scope should fail isolation
        wrong_scope = DemoResourceScope(calendar_id="wrong-calendar", task_list_id="wrong-tasklist")
        with pytest.raises(CalendarOutOfScopeError):
            verify_demo_resource_isolation(validated, wrong_scope)

    def test_demo_isolation_does_not_imply_authority(self) -> None:
        """DemoIsolationResult ISOLATED does NOT imply authority."""
        _, validated = _make_calendar_update_contract()
        scope = DemoResourceScope(calendar_id="demo-cal-001", task_list_id="demo-tl-001")
        result = verify_demo_resource_isolation(validated, scope)
        assert result.status == DemoIsolationStatus.ISOLATED
        # Still requires approval for calendar.update
        decision = evaluate_authority(validated, at=datetime.now(tz=UTC))
        assert not decision.is_authorized

    def test_endpoint_allow_does_not_imply_action_validation(self) -> None:
        """EndpointAdmissionDecision ALLOW does NOT imply action validation or authority."""
        now = datetime.now(tz=UTC)
        policy = EndpointProtectionPolicy(
            max_requests_per_window=100,
            max_paid_live_requests_per_window=10,
            internal_gross_ceiling=Decimal("50.00"),
        )
        snapshot = RateSnapshot(
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(hours=1),
            total_requests=0,
            paid_live_requests=0,
        )
        request = EndpointRequestAssessment(
            exposure_class=RequestExposureClass.NO_PAID_CAPABILITY,
            caller_class=CallerClass.PUBLIC_UNTRUSTED,
        )
        decision = evaluate_endpoint_admission(request, policy, snapshot, at=now)
        assert decision.is_allowed
        # But the decision object has no action/mission/authority semantics
        assert not hasattr(decision, "action_id")
        assert not hasattr(decision, "mission_id")
        assert not hasattr(decision, "authority_class")

    def test_approval_grant_does_not_imply_supported_action(self) -> None:
        """ApprovalGrant does NOT imply supported action or demo isolation."""
        # A grant can exist independently of whether the action is supported
        action, _ = _make_calendar_update_contract()
        now = datetime.now(tz=UTC)
        _grant = ApprovalGrant.create(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
        # Grant exists, but wrong scope should still fail isolation
        wrong_scope = DemoResourceScope(calendar_id="wrong-calendar", task_list_id="wrong-tasklist")
        validated = validate_action_contract(action)
        with pytest.raises(CalendarOutOfScopeError):
            verify_demo_resource_isolation(validated, wrong_scope)


# ===========================================================================
# INVARIANT 8: Fact-authority law preservation (P-03 contracts)
# ===========================================================================


class TestFactAuthorityLawPreservation:
    """Verify P-03 fact-authority laws remain intact after P-04."""

    def test_not_run_cannot_promote_to_ready(self) -> None:
        with pytest.raises(IllegalStatePromotionError, match="NOT_RUN"):
            assert_can_promote_to_ready(
                current_state=MissionState.VERIFYING,
                step_evidence_states=[StepEvidenceState.NOT_RUN],
            )

    def test_executed_unverified_cannot_promote_to_ready(self) -> None:
        with pytest.raises(IllegalStatePromotionError, match="EXECUTED_UNVERIFIED"):
            assert_can_promote_to_ready(
                current_state=MissionState.VERIFYING,
                step_evidence_states=[StepEvidenceState.EXECUTED_UNVERIFIED],
            )

    def test_ready_requires_all_verified(self) -> None:
        # Should succeed
        assert_can_promote_to_ready(
            current_state=MissionState.VERIFYING,
            step_evidence_states=[
                StepEvidenceState.VERIFIED,
                StepEvidenceState.VERIFIED,
            ],
        )

    def test_ready_requires_verifying_state(self) -> None:
        with pytest.raises(IllegalStatePromotionError):
            assert_can_promote_to_ready(
                current_state=MissionState.EXECUTING,
                step_evidence_states=[StepEvidenceState.VERIFIED],
            )
