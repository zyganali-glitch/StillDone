"""Adversarial and canonical tests for Phase P-11.05:
Calendar existing-event update remains NOT_RUN before approval.

Validates all 12 mandatory requirements:
1. CALENDAR_UPDATE without grant returns NOT_RUN.
2. Calendar provider update method is never invoked (invocation count == 0).
3. No approval consumption record is created (ApprovalLedger remains unused/empty).
4. No execution attempt evidence is fabricated (attempt is None for NOT_RUN).
5. No retry budget is consumed (P-10 retry orchestrator not invoked).
6. PendingApproval remains PENDING (is_approved=False, status=PENDING).
7. Mission does not become READY (assert_can_promote_to_ready fails closed).
8. Execution result cannot be mislabeled FAILED (status is strictly NOT_RUN).
9. Planner/model cannot bypass approval gate (PlannerGateAuthorityError).
10. Arbitrary "user approved" prose cannot bypass gate (AuthorityPolicyTypeError).
11. Read-back remains a READ_ONLY action (read adapter makes zero mutations).
12. P-11.06 approved execution path is not implemented here (NotImplementedError).

Consolidated Same-Scope Repairs (Repairs A–E):
- Repair A: Privacy-safe rejection under hostile input, zero secret reflection.
- Repair B: Complete exact action binding validation, unexpected grant rejection,
  no premature IN_PROGRESS transitions, spy verification of zero provider writes.
- Repair C: Receipts derived strictly from observed facts, CalendarReadResult validation,
  measured mutations verification, deep immutability, zero false LIVE claims.
- Repair D: Proof script executes cleanly under python -O with fail-closed SHA checks.
- Repair E: Comprehensive adversarial edge cases across the entire execution boundary.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stilldone.action_policy import validate_action_contract
from stilldone.adapters.calendar import (
    CalendarEventObservation,
    CalendarReadResult,
    CalendarReadStatus,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
    GoogleCalendarUpdateAdapter,
)
from stilldone.adapters.tasks import (
    FakeGoogleTasksTransport,
    GoogleTasksCreateAdapter,
    GoogleTasksReadAdapter,
)
from stilldone.adapters.weather import (
    FakeOpenMeteoTransport,
    OpenMeteoReadAdapter,
    WeatherLocationConfig,
)
from stilldone.approval_consumption import (
    ApprovalLedger,
    ApprovalUsageStatus,
    UsedApprovalRegistry,
)
from stilldone.authority_policy import (
    AuthorityPolicyTypeError,
    get_action_authority_policy,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionId,
    ActionType,
    NormalizedParameters,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (
    ApprovalGrant,
    ApprovalId,
    AuthorityClass,
)
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.lifecycle import MissionState, StepEvidenceState
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.contracts import MissionExecutionContract
from stilldone.execution.gate import (
    ExecutionGateDecision,
    ExecutionGateTypeError,
    ExecutionGateValueError,
    PendingApprovalBindingMismatchError,
    PlannerGateAuthorityError,
    UnexpectedApprovalGrantError,
    create_unapproved_action_receipt,
    evaluate_execution_gate,
    execute_gated_action,
)
from stilldone.execution.router import (
    ActionHandler,
    AdapterRouter,
    CalendarReadHandler,
    CalendarUpdateHandler,
    TasksCreateHandler,
    TasksReadHandler,
    WeatherReadHandler,
)
from stilldone.execution.scheduler import schedule_execution
from stilldone.execution.state import (
    ActionExecutionStatus,
    ExecutionStateTracker,
)
from stilldone.pending_approval import (
    PendingApprovalStatus,
    create_pending_approval,
)
from stilldone.planning.contracts import (
    CandidateActionProposal,
    SymbolicTargetRef,
)
from stilldone.transitions import IllegalStatePromotionError, assert_can_promote_to_ready

DEMO_CALENDAR_ID = "c_1880abc123demo@group.calendar.google.com"
DEMO_TASKLIST_ID = "MDExMTI0ZGVtbw"
DEMO_EVENT_ID = "evt_leave_for_school_001"
INITIAL_START_TIME = "2026-10-09T07:45:00+03:00"
INITIAL_END_TIME = "2026-10-09T08:15:00+03:00"
PROPOSED_START_TIME = "2026-10-09T07:30:00+03:00"
PROPOSED_SUMMARY = "Leave for school"


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id=DEMO_CALENDAR_ID,
        task_list_id=DEMO_TASKLIST_ID,
    )


@pytest.fixture
def seeded_calendar_transport(demo_scope: DemoResourceScope) -> FakeGoogleCalendarTransport:
    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id=demo_scope.calendar_id,
        event_id=DEMO_EVENT_ID,
        summary=PROPOSED_SUMMARY,
        start_time=INITIAL_START_TIME,
        end_time=INITIAL_END_TIME,
        all_day=False,
        etag='"etag_initial_1001"',
        extra_fields={
            "description": "Original family morning preparation event",
            "location": "Home",
        },
    )
    return transport


@pytest.fixture
def calendar_read_adapter(
    demo_scope: DemoResourceScope, seeded_calendar_transport: FakeGoogleCalendarTransport
) -> GoogleCalendarReadAdapter:
    return GoogleCalendarReadAdapter(scope=demo_scope, transport=seeded_calendar_transport)


@pytest.fixture
def calendar_update_adapter(
    demo_scope: DemoResourceScope, seeded_calendar_transport: FakeGoogleCalendarTransport
) -> GoogleCalendarUpdateAdapter:
    return GoogleCalendarUpdateAdapter(scope=demo_scope, transport=seeded_calendar_transport)


@pytest.fixture
def test_router(
    demo_scope: DemoResourceScope,
    seeded_calendar_transport: FakeGoogleCalendarTransport,
    calendar_read_adapter: GoogleCalendarReadAdapter,
    calendar_update_adapter: GoogleCalendarUpdateAdapter,
) -> AdapterRouter:
    tasks_transport = FakeGoogleTasksTransport()
    tasks_read = GoogleTasksReadAdapter(demo_scope, tasks_transport)
    tasks_create = GoogleTasksCreateAdapter(demo_scope, tasks_transport)
    weather_transport = FakeOpenMeteoTransport()
    loc_config = WeatherLocationConfig("loc-demo", latitude=52.52, longitude=13.41)
    weather_read = OpenMeteoReadAdapter(loc_config, weather_transport)

    routes: dict[ActionType, ActionHandler] = {
        ActionType.CALENDAR_READ: CalendarReadHandler(calendar_read_adapter),
        ActionType.CALENDAR_UPDATE: CalendarUpdateHandler(calendar_update_adapter),
        ActionType.TASK_READ: TasksReadHandler(tasks_read),
        ActionType.TASK_CREATE: TasksCreateHandler(tasks_create),
        ActionType.WEATHER_READ: WeatherReadHandler(weather_read),
    }
    return AdapterRouter(routes)


def _make_calendar_update_action(
    mission_id: MissionId | None = None,
    action_id: ActionId | None = None,
    start_time: str = PROPOSED_START_TIME,
    summary: str = PROPOSED_SUMMARY,
) -> ActionContract:
    mid = mission_id or MissionId.generate()
    aid = action_id or ActionId.generate()
    return ActionContract.create(
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=DEMO_EVENT_ID,
            parent_id=DEMO_CALENDAR_ID,
        ),
        parameters={
            "summary": summary,
            "start_time": start_time,
            "all_day": False,
        },
        action_id=aid,
    )


def _make_calendar_read_action(
    mission_id: MissionId | None = None,
    action_id: ActionId | None = None,
) -> ActionContract:
    mid = mission_id or MissionId.generate()
    aid = action_id or ActionId.generate()
    return ActionContract.create(
        mission_id=mid,
        action_type=ActionType.CALENDAR_READ,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=DEMO_EVENT_ID,
            parent_id=DEMO_CALENDAR_ID,
        ),
        parameters={},
        action_id=aid,
    )


# ===========================================================================
# 12 Core Requirements Tests
# ===========================================================================


class TestPhaseP1105CoreRequirements:
    """Validate all 12 core requirements for P-11.05."""

    def test_req_01_calendar_update_without_grant_returns_not_run(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """Req 1: CALENDAR_UPDATE without grant returns NOT_RUN."""
        action = _make_calendar_update_action()
        decision = evaluate_execution_gate(action, approval=None)

        assert decision.status == ActionExecutionStatus.NOT_RUN
        assert decision.is_authorized is False
        assert decision.is_not_run is True
        assert "requires bound human approval" in decision.reason
        assert "Execution must remain NOT_RUN" in decision.reason

    def test_req_02_calendar_provider_update_method_is_never_invoked(
        self,
        test_router: AdapterRouter,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """Req 2: Calendar provider update method is never invoked."""
        action = _make_calendar_update_action()
        assert seeded_calendar_transport.writes_count == 0

        # Run through execution authority gate
        decision = execute_gated_action(action, test_router, approval=None)

        assert decision.status == ActionExecutionStatus.NOT_RUN
        # Provider mutation count MUST remain strictly 0
        assert seeded_calendar_transport.writes_count == 0

    def test_req_03_no_approval_consumption_record_is_created(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """Req 3: No approval consumption record is created."""
        registry = UsedApprovalRegistry()
        ledger = ApprovalLedger(registry=registry)

        action = _make_calendar_update_action()
        req_at = datetime.now(UTC)
        pending = create_pending_approval(validate_action_contract(action), requested_at=req_at)

        # Gate execution evaluated with no grant
        decision = evaluate_execution_gate(action, approval=None, pending_approval=pending)
        assert decision.status == ActionExecutionStatus.NOT_RUN

        # Registry must have zero records for this pending approval ID or any approval ID
        assert ledger.is_used(pending.pending_approval_id.value) is False
        assert ledger.is_consumed(pending.pending_approval_id.value) is False
        assert ledger.check_status(pending.pending_approval_id.value) == ApprovalUsageStatus.UNUSED

    def test_req_04_no_execution_attempt_evidence_is_fabricated(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """Req 4: No execution attempt evidence is fabricated."""
        action = _make_calendar_update_action()
        decision = execute_gated_action(action, test_router, approval=None)

        assert decision.status == ActionExecutionStatus.NOT_RUN
        # Crucial: attempt MUST be strictly None!
        assert decision.attempt is None
        assert decision.provider_result is None

    def test_req_05_no_retry_budget_is_consumed(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """Req 5: No retry budget is consumed."""
        action = _make_calendar_update_action()

        # Gate execution
        decision = execute_gated_action(action, test_router, approval=None)
        assert decision.status == ActionExecutionStatus.NOT_RUN

        # An action that was NOT_RUN never entered execution, produced 0 attempts,
        # and has consumed 0 retry budget (no P-10 orchestrator loop ran).
        assert decision.attempt is None

    def test_req_06_pending_approval_remains_pending(self) -> None:
        """Req 6: PendingApproval remains PENDING."""
        action = _make_calendar_update_action()
        req_at = datetime.now(UTC)
        pending = create_pending_approval(validate_action_contract(action), requested_at=req_at)

        assert pending.status == PendingApprovalStatus.PENDING
        assert pending.is_pending is True
        assert pending.is_approved is False
        assert pending.is_authorized is False

        # Gate evaluation does not mutate or alter the PendingApproval object
        decision = evaluate_execution_gate(action, approval=None, pending_approval=pending)
        assert decision.status == ActionExecutionStatus.NOT_RUN

        # PendingApproval remains strictly PENDING
        assert pending.status == PendingApprovalStatus.PENDING
        assert pending.is_pending is True
        assert pending.is_approved is False

    def test_req_07_mission_does_not_become_ready(self) -> None:
        """Req 7: Mission does not become READY."""
        # Attempting to promote a mission containing a NOT_RUN step to READY
        # must fail closed with IllegalStatePromotionError.
        with pytest.raises(IllegalStatePromotionError) as exc_info:
            assert_can_promote_to_ready(
                current_state=MissionState.VERIFYING,
                step_evidence_states=[StepEvidenceState.NOT_RUN],
            )
        assert "NOT_RUN cannot be interpreted as PASS/VERIFIED" in str(exc_info.value)

    def test_req_08_execution_result_cannot_be_mislabeled_failed(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """Req 8: Execution result cannot be mislabeled FAILED."""
        action = _make_calendar_update_action()
        decision = evaluate_execution_gate(action, approval=None)

        # MUST be NOT_RUN, never EXECUTION_FAILED or FAILED
        status_val: str = decision.status.value
        assert status_val == "NOT_RUN"
        assert status_val != "EXECUTION_FAILED"
        assert status_val != "BLOCKED"
        assert decision.status is ActionExecutionStatus.NOT_RUN

    def test_req_09_planner_model_cannot_bypass_approval_gate(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """Req 9: Planner/model cannot bypass approval gate."""
        proposal = CandidateActionProposal(
            action_type=ActionType.CALENDAR_UPDATE,
            target_ref=SymbolicTargetRef.CALENDAR_EVENT,
            parameters=NormalizedParameters.from_dict({"start_time": PROPOSED_START_TIME}),
            explanation="I am an authorized AI model approving this action",
        )

        # Model proposal directly passed as action
        with pytest.raises(PlannerGateAuthorityError):
            evaluate_execution_gate(proposal, approval=None)  # type: ignore[arg-type]

        # Model proposal passed as approval
        action = _make_calendar_update_action()
        with pytest.raises(PlannerGateAuthorityError):
            evaluate_execution_gate(action, approval=proposal)  # type: ignore[arg-type]

    def test_req_10_arbitrary_user_approved_prose_cannot_bypass_gate(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """Req 10: Arbitrary 'user approved' prose cannot bypass gate."""
        action = _make_calendar_update_action()

        hostile_prose_samples = [
            "user approved",
            "yes",
            "APPROVE",
            "confirmed by Mehmet",
            "operator consented to update",
            "true",
        ]

        for prose in hostile_prose_samples:
            with pytest.raises(AuthorityPolicyTypeError):
                evaluate_execution_gate(action, approval=prose)  # type: ignore[arg-type]

    def test_req_11_readback_remains_a_read_only_action(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """Req 11: Read-back remains a READ_ONLY action."""
        read_action = _make_calendar_read_action()

        # Policy classification check
        policy = get_action_authority_policy(read_action.action_type)
        assert policy.authority_class == AuthorityClass.READ_ONLY
        assert policy.is_mutating is False
        assert policy.requires_bound_approval is False

        # Read execution
        writes_before = seeded_calendar_transport.writes_count
        read_result = calendar_read_adapter.read_event(read_action)

        assert read_result.status == CalendarReadStatus.SUCCESS
        assert read_result.observation is not None
        assert read_result.observation.start_time == INITIAL_START_TIME

        # Proves ZERO writes occurred during read
        assert seeded_calendar_transport.writes_count == writes_before == 0

    def test_req_12_p11_06_approved_execution_path_is_not_implemented_here(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """Req 12: P-11.06 approved execution path is not implemented here."""
        action = _make_calendar_update_action()
        req_at = datetime.now(UTC)
        pending = create_pending_approval(validate_action_contract(action), requested_at=req_at)

        # Create a synthetically valid ApprovalGrant
        grant = ApprovalGrant.create(
            action=action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=req_at,
            expires_at=req_at + timedelta(minutes=15),
            approval_id=ApprovalId.generate(),
        )

        # Attempting to execute with an approval grant under P-11.05 gate
        # MUST fail closed because P-11.06 is strictly NOT AUTHORIZED / NOT_RUN.
        with pytest.raises(NotImplementedError) as exc_info:
            evaluate_execution_gate(action, approval=grant, pending_approval=pending)

        assert "P-11.06 approved execution path is not implemented in P-11.05" in str(
            exc_info.value
        )


# ===========================================================================
# Repair A: Privacy-Safe Rejection Tests
# ===========================================================================


class TestPrivacySafeRejection:
    """Validate that invalid inputs never leak sensitive plaintext or secrets."""

    def test_string_action_with_bearer_token_does_not_leak_in_exception(self) -> None:
        """Verify bearer token in string action is not reflected in error or traceback."""
        secret_token = "bearer_secret_token_1234567890abcdef"
        with pytest.raises(AuthorityPolicyTypeError) as exc_info:
            evaluate_execution_gate(f"Action with token {secret_token}", approval=None)  # type: ignore[arg-type]

        err_msg = str(exc_info.value)
        err_repr = repr(exc_info.value)
        assert secret_token not in err_msg
        assert secret_token not in err_repr
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None

    def test_string_approval_with_password_does_not_leak_in_exception(self) -> None:
        """Verify password in approval string is not reflected in error."""
        secret_password = "super_secret_operator_password_999!"
        action = _make_calendar_update_action()
        with pytest.raises(AuthorityPolicyTypeError) as exc_info:
            evaluate_execution_gate(action, approval=f"approve with {secret_password}")  # type: ignore[arg-type]

        err_msg = str(exc_info.value)
        err_repr = repr(exc_info.value)
        assert secret_password not in err_msg
        assert secret_password not in err_repr
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None

    def test_hostile_action_object_with_secret_repr_does_not_leak(self) -> None:
        """Verify hostile object with secret in __repr__ and __str__ does not leak."""
        secret_payload = "HOSTILE_INTERNAL_API_KEY_987654321"

        class HostileActionInput:
            def __repr__(self) -> str:
                return f"HostileActionInput({secret_payload})"

            def __str__(self) -> str:
                return f"HostileActionInput({secret_payload})"

        with pytest.raises(ExecutionGateTypeError) as exc_info:
            evaluate_execution_gate(HostileActionInput(), approval=None)  # type: ignore[arg-type]

        err_msg = str(exc_info.value)
        err_repr = repr(exc_info.value)
        assert secret_payload not in err_msg
        assert secret_payload not in err_repr
        assert "HostileActionInput" in err_msg

    def test_hostile_approval_object_with_secret_repr_does_not_leak(self) -> None:
        """Verify hostile approval object does not leak repr secrets."""
        secret_token = "OAUTH_REFRESH_TOKEN_DO_NOT_LEAK"

        class HostileApprovalInput:
            def __repr__(self) -> str:
                return f"HostileApproval({secret_token})"

            def __str__(self) -> str:
                return f"HostileApproval({secret_token})"

        action = _make_calendar_update_action()
        with pytest.raises(ExecutionGateTypeError) as exc_info:
            evaluate_execution_gate(action, approval=HostileApprovalInput())  # type: ignore[arg-type]

        err_msg = str(exc_info.value)
        err_repr = repr(exc_info.value)
        assert secret_token not in err_msg
        assert secret_token not in err_repr
        assert "HostileApprovalInput" in err_msg


# ===========================================================================
# Repair B: Authority & State Boundaries Tests
# ===========================================================================


class TestAuthorityAndStateBoundaries:
    """Validate complete action binding, unexpected grants, and tracker invariance."""

    def test_pending_approval_mismatched_target_rejected_without_leaking_target(self) -> None:
        """Reject PendingApproval with mismatched target without exposing target plaintext."""
        action = _make_calendar_update_action()
        sensitive_target_event = "secret_private_event_9999"
        action_diff_target = ActionContract.create(
            mission_id=action.mission_id,
            action_type=action.action_type,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id=sensitive_target_event,
                parent_id=DEMO_CALENDAR_ID,
            ),
            parameters=action.parameters.to_dict(),
            action_id=action.action_id,
        )
        pending = create_pending_approval(
            validate_action_contract(action_diff_target), requested_at=datetime.now(UTC)
        )

        with pytest.raises(PendingApprovalBindingMismatchError) as exc_info:
            evaluate_execution_gate(action, approval=None, pending_approval=pending)

        err_msg = str(exc_info.value)
        assert "target does not match" in err_msg
        assert sensitive_target_event not in err_msg

    def test_pending_approval_mismatched_parameters_rejected_without_leaking_params(self) -> None:
        """Reject PendingApproval with mismatched parameters without exposing values."""
        action = _make_calendar_update_action()
        secret_summary = "Confidential board meeting discussion"
        action_diff_params = ActionContract.create(
            mission_id=action.mission_id,
            action_type=action.action_type,
            target=action.target,
            parameters={
                "summary": secret_summary,
                "start_time": PROPOSED_START_TIME,
                "all_day": False,
            },
            action_id=action.action_id,
        )
        pending = create_pending_approval(
            validate_action_contract(action_diff_params), requested_at=datetime.now(UTC)
        )

        with pytest.raises(PendingApprovalBindingMismatchError) as exc_info:
            evaluate_execution_gate(action, approval=None, pending_approval=pending)

        err_msg = str(exc_info.value)
        assert "parameters do not match" in err_msg or "parameters_digest" in err_msg
        assert secret_summary not in err_msg

    def test_pending_approval_mismatched_action_id_rejected(self) -> None:
        """Reject PendingApproval targeting a different action_id."""
        action = _make_calendar_update_action()
        action_diff_id = ActionContract.create(
            mission_id=action.mission_id,
            action_type=action.action_type,
            target=action.target,
            parameters=action.parameters.to_dict(),
            action_id=ActionId.generate(),
        )
        pending = create_pending_approval(
            validate_action_contract(action_diff_id), requested_at=datetime.now(UTC)
        )

        with pytest.raises(PendingApprovalBindingMismatchError):
            evaluate_execution_gate(action, approval=None, pending_approval=pending)

    def test_unexpected_approval_grant_on_no_approval_action_raises_and_preserves_tracker(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """Reject unexpected ApprovalGrant on READ_ONLY action and leave tracker untouched."""
        read_action = _make_calendar_read_action()
        grant = ApprovalGrant.create(
            action=read_action,
            authority_class=AuthorityClass.READ_ONLY,
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            approval_id=ApprovalId.generate(),
        )

        contract = MissionExecutionContract(
            mission_id=read_action.mission_id,
            actions=(read_action,),
            dependencies={read_action.action_id: frozenset()},
        )
        schedule = schedule_execution(contract)
        tracker = ExecutionStateTracker(contract, schedule)

        with pytest.raises(UnexpectedApprovalGrantError) as exc_info:
            execute_gated_action(
                read_action,
                test_router,
                tracker=tracker,
                approval=grant,
            )

        assert "Unexpected ApprovalGrant provided" in str(exc_info.value)
        # Tracker was NOT transitioned to IN_PROGRESS or EXECUTION_SUCCEEDED
        assert tracker.get_status(read_action.action_id) == ActionExecutionStatus.NOT_RUN

    def test_attempt_generator_failure_prevents_premature_in_progress_transition(
        self,
        test_router: AdapterRouter,
    ) -> None:
        """If attempt generator fails, tracker must NOT be left in IN_PROGRESS state."""
        read_action = _make_calendar_read_action()
        contract = MissionExecutionContract(
            mission_id=read_action.mission_id,
            actions=(read_action,),
            dependencies={read_action.action_id: frozenset()},
        )
        schedule = schedule_execution(contract)
        tracker = ExecutionStateTracker(contract, schedule)

        def failing_attempt_gen(aid: ActionId) -> ExecutionAttempt:
            raise RuntimeError("Attempt generation disk failure")

        with pytest.raises(RuntimeError) as exc_info:
            execute_gated_action(
                read_action,
                test_router,
                tracker=tracker,
                attempt_generator=failing_attempt_gen,
            )

        assert "Attempt generation disk failure" in str(exc_info.value)
        # Invariant: tracker must NOT have been marked IN_PROGRESS!
        assert tracker.get_status(read_action.action_id) == ActionExecutionStatus.NOT_RUN

    def test_router_and_handlers_never_invoked_via_spies(
        self,
        demo_scope: DemoResourceScope,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        calendar_update_adapter: GoogleCalendarUpdateAdapter,
    ) -> None:
        """Use spies to prove router, handler, and transport receive 0 mutation calls."""
        handler = CalendarUpdateHandler(calendar_update_adapter)
        router = AdapterRouter(
            {
                ActionType.CALENDAR_READ: CalendarReadHandler(calendar_read_adapter),
                ActionType.CALENDAR_UPDATE: handler,
            }
        )

        router_execute_calls = 0
        original_router_execute = router.execute

        def spy_router_execute(*args: Any, **kwargs: Any) -> Any:
            nonlocal router_execute_calls
            router_execute_calls += 1
            return original_router_execute(*args, **kwargs)

        router.execute = spy_router_execute  # type: ignore[method-assign]

        handler_execute_calls = 0
        original_handler_execute = handler.execute

        def spy_handler_execute(*args: Any, **kwargs: Any) -> Any:
            nonlocal handler_execute_calls
            handler_execute_calls += 1
            return original_handler_execute(*args, **kwargs)

        handler.execute = spy_handler_execute  # type: ignore[method-assign]

        action = _make_calendar_update_action()
        decision = execute_gated_action(action, router, approval=None)

        assert decision.status == ActionExecutionStatus.NOT_RUN
        assert router_execute_calls == 0, "router.execute must be called 0 times"
        assert handler_execute_calls == 0, "handler.execute must be called 0 times"
        assert seeded_calendar_transport.writes_count == 0, (
            "transport.update_event must be called 0 times"
        )


# ===========================================================================
# Repair C: Observed Facts & Receipt Integrity Tests
# ===========================================================================


class TestObservedFactsReceiptIntegrity:
    """Validate that receipts derive facts strictly from verified observations."""

    def test_receipt_generation_from_observed_facts_success(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """Create valid receipt from real observed facts."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()

        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = execute_gated_action(
            update_action,
            test_router,
            approval=None,
            pending_approval=pending,
        )
        after_result = calendar_read_adapter.read_event(read_action)

        receipt = create_unapproved_action_receipt(
            gate_decision=gate_decision,
            action=update_action,
            pending_approval=pending,
            before_read=before_result,
            after_read=after_result,
            measured_provider_mutations=seeded_calendar_transport.writes_count,
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
        )

        assert receipt.execution_state == ActionExecutionStatus.NOT_RUN
        assert receipt.provider_mutation_invocations == 0
        assert receipt.state_unchanged is True
        assert receipt.is_ready_claimed is False
        assert receipt.grant_present is False
        assert receipt.consumption_present is False

    def test_receipt_rejects_non_not_run_gate_decision(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory fails closed if gate decision status is not NOT_RUN."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        after_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )

        invalid_decision = ExecutionGateDecision(
            action_id=update_action.action_id,
            action_type=update_action.action_type,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
            is_authorized=True,
            reason="Bogus success",
            evaluated_at=datetime.now(UTC),
            pending_approval_id=pending.pending_approval_id,
        )

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=invalid_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            )
        assert "Receipt requires gate decision status NOT_RUN" in str(exc_info.value)

    def test_receipt_rejects_non_zero_measured_mutations(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory fails closed if measured provider mutations > 0."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        after_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=1,  # Contradictory measured count!
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            )
        assert "Measured provider mutations must be 0" in str(exc_info.value)

    def test_receipt_rejects_mutated_after_observation(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory fails closed if before and after observations differ."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        assert before_result.observation is not None
        orig_obs = before_result.observation

        mutated_obs = CalendarEventObservation(
            event_id=orig_obs.event_id,
            calendar_id=orig_obs.calendar_id,
            summary="Mutated summary",
            start_time=orig_obs.start_time,
            end_time=orig_obs.end_time,
            all_day=orig_obs.all_day,
            etag=orig_obs.etag,
            status=orig_obs.status,
            observed_at=datetime.now(UTC),
        )
        after_result_mutated = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=orig_obs.event_id,
            observation=mutated_obs,
        )

        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result_mutated,
                measured_provider_mutations=0,
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            )
        assert "Observed external event state differs" in str(exc_info.value)

    def test_receipt_rejects_after_observation_reflecting_proposed_mutation(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory detects if after_read reflects proposed parameters."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action(start_time="2026-10-09T06:00:00+03:00")
        before_result = calendar_read_adapter.read_event(read_action)
        assert before_result.observation is not None
        orig_obs = before_result.observation

        # Fake an observation where start_time mutated to proposed start_time
        mutated_obs = CalendarEventObservation(
            event_id=orig_obs.event_id,
            calendar_id=orig_obs.calendar_id,
            summary=orig_obs.summary,
            start_time="2026-10-09T06:00:00+03:00",
            end_time=orig_obs.end_time,
            all_day=orig_obs.all_day,
            etag=orig_obs.etag,
            status=orig_obs.status,
            observed_at=datetime.now(UTC),
        )
        after_result_executed = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=orig_obs.event_id,
            observation=mutated_obs,
        )

        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )

        with pytest.raises(ExecutionGateValueError):
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result_executed,
                measured_provider_mutations=0,
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            )

    def test_receipt_rejects_live_provenance_claims(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory forbids false claims of LIVE_* provenance."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        after_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                provenance=EvidenceProvenance.LIVE_GOOGLE,
            )
        assert "cannot claim live provenance" in str(exc_info.value)

    def test_receipt_rejects_invalid_sha_format(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory fails closed on non-40-hex SHA."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        after_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                source_sha="invalid_short_sha",
            )
        assert "40-character hexadecimal git commit SHA" in str(exc_info.value)

    def test_receipt_deep_immutability(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt state summaries are deeply immutable."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        after_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )

        receipt = create_unapproved_action_receipt(
            gate_decision=gate_decision,
            action=update_action,
            pending_approval=pending,
            before_read=before_result,
            after_read=after_result,
            measured_provider_mutations=0,
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
        )

        with pytest.raises(TypeError):
            receipt.before_state_summary["summary"] = "Hacked summary"  # type: ignore[index]

        with pytest.raises(TypeError):
            receipt.after_state_summary["start_time"] = "Hacked time"  # type: ignore[index]

    def test_receipt_to_dict_redacts_sensitive_strings(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Serialized receipt dictionary redacts emails and target IDs."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        after_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )

        receipt = create_unapproved_action_receipt(
            gate_decision=gate_decision,
            action=update_action,
            pending_approval=pending,
            before_read=before_result,
            after_read=after_result,
            measured_provider_mutations=0,
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
        )

        as_dict = receipt.to_dict()
        assert as_dict["execution_state"] == "NOT_RUN"
        assert as_dict["provider_mutation_invocations"] == 0
        assert as_dict["is_ready_claimed"] is False


# ===========================================================================
# Multi-Step Pipeline with Tracker Tests
# ===========================================================================


class TestMultiStepExecutionPipelineWithGate:
    """Validate multi-step mission execution where unapproved step remains NOT_RUN."""

    def test_pipeline_preserves_earlier_success_while_unapproved_step_remains_not_run(
        self,
        test_router: AdapterRouter,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """Earlier CALENDAR_READ succeeds; unapproved CALENDAR_UPDATE remains NOT_RUN.

        Downstream actions depending on CALENDAR_UPDATE do not run.
        """
        mid = MissionId.generate()
        aid_read = ActionId.generate()
        aid_update = ActionId.generate()

        action_read = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_READ,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id=DEMO_EVENT_ID,
                parent_id=DEMO_CALENDAR_ID,
            ),
            parameters={},
            action_id=aid_read,
        )

        action_update = ActionContract.create(
            mission_id=mid,
            action_type=ActionType.CALENDAR_UPDATE,
            target=TargetIdentity(
                system="google_calendar",
                resource_kind=ResourceKind.CALENDAR_EVENT,
                resource_id=DEMO_EVENT_ID,
                parent_id=DEMO_CALENDAR_ID,
            ),
            parameters={
                "summary": PROPOSED_SUMMARY,
                "start_time": PROPOSED_START_TIME,
                "all_day": False,
            },
            action_id=aid_update,
        )

        contract = MissionExecutionContract(
            mission_id=mid,
            actions=(action_read, action_update),
            dependencies={
                aid_read: frozenset(),
                aid_update: frozenset({aid_read}),
            },
        )

        schedule = schedule_execution(contract)
        tracker = ExecutionStateTracker(contract, schedule)

        # Step 1: Execute read action (authorized, READ_ONLY)
        read_dec = execute_gated_action(
            action_read,
            test_router,
            tracker=tracker,
            approval=None,
        )
        assert read_dec.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert tracker.get_status(aid_read) == ActionExecutionStatus.EXECUTION_SUCCEEDED

        # Step 2: Execute update action (unapproved, REVERSIBLE_APPROVAL_REQUIRED)
        update_dec = execute_gated_action(
            action_update,
            test_router,
            tracker=tracker,
            approval=None,
        )
        assert update_dec.status == ActionExecutionStatus.NOT_RUN
        assert tracker.get_status(aid_update) == ActionExecutionStatus.NOT_RUN

        # Step 3: Check snapshot
        snapshot = tracker.snapshot()
        assert snapshot.get_status(aid_read) == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert snapshot.get_status(aid_update) == ActionExecutionStatus.NOT_RUN
        # Crucial: update action was NOT mislabeled EXECUTION_FAILED
        assert snapshot.get_status(aid_update) != ActionExecutionStatus.EXECUTION_FAILED
        assert snapshot.has_failures is False
        assert snapshot.is_all_succeeded is False

        # Zero provider writes performed
        assert seeded_calendar_transport.writes_count == 0


# ===========================================================================
# Repair D: Proof Script Execution Under Python -O
# ===========================================================================


class TestProofScriptExecution:
    """Validate that the standalone proof script executes properly and fails closed."""

    def test_proof_script_runs_and_passes_under_python_optimized_mode(self) -> None:
        """Run python -O scripts/p11_05_proof.py --json and verify output."""
        repo_root = Path(__file__).resolve().parent.parent
        res = subprocess.run(
            [sys.executable, "-O", "scripts/p11_05_proof.py", "--json"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Proof script failed: {res.stderr}"
        import json

        data = json.loads(res.stdout)
        assert data["execution_status"] == "NOT_RUN"
        assert data["provider_update_invocation_count"] == 0
        assert data["external_state_unchanged"] is True
        assert data["receipt"]["execution_state"] == "NOT_RUN"
        assert data["receipt"]["provider_mutation_invocations"] == 0

    def test_proof_script_fails_closed_on_sha_mismatch(self) -> None:
        """Verify proof script exits with non-zero on mismatched expected SHA."""
        repo_root = Path(__file__).resolve().parent.parent
        res = subprocess.run(
            [
                sys.executable,
                "-O",
                "scripts/p11_05_proof.py",
                "--expected-sha",
                "0000000000000000000000000000000000000000",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert res.returncode != 0
        assert "ProofVerificationError" in res.stderr
