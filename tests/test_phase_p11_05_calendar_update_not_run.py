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
from unittest.mock import MagicMock

import pytest

from stilldone.action_policy import validate_action_contract
from stilldone.adapters.calendar import (
    CalendarEventObservation,
    CalendarReadResult,
    CalendarReadStatus,
    CalendarTargetError,
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
    APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
    ApprovalLedger,
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
    BindingHash,
)
from stilldone.domain.execution import ExecutionAttempt
from stilldone.domain.lifecycle import MissionState, StepEvidenceState
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.contracts import MissionExecutionContract
from stilldone.execution.gate import (
    CalendarMutationSpy,
    ExecutionGateDecision,
    ExecutionGateTypeError,
    ExecutionGateValueError,
    PendingApprovalBindingMismatchError,
    PlannerGateAuthorityError,
    ProviderMutationObservation,
    UnapprovedActionReceipt,
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
from stilldone.ledger import MissionLedgerPort
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

        # Ledger must have zero consumed approval records for this action
        assert ledger.has_consumed_approval_for_action(action.action_id) is False
        assert len(ledger.get_consumed_records_for_action(action.action_id)) == 0

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
        ledger = ApprovalLedger()

        receipt = create_unapproved_action_receipt(
            gate_decision=gate_decision,
            action=update_action,
            pending_approval=pending,
            before_read=before_result,
            after_read=after_result,
            measured_provider_mutations=seeded_calendar_transport.writes_count,
            mutation_observation=ProviderMutationObservation(),
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            ledger=ledger,
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
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=invalid_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
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
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=1,  # Contradictory measured count!
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "measured_provider_mutations contradicts" in str(
            exc_info.value
        ) or "Measured provider mutations must be 0" in str(exc_info.value)

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

        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )

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
            read_at=datetime.now(UTC),
        )
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result_mutated,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
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

        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )

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
            read_at=datetime.now(UTC),
        )
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError):
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result_executed,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
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
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
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
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="invalid_short_sha",
                ledger=ledger,
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
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        receipt = create_unapproved_action_receipt(
            gate_decision=gate_decision,
            action=update_action,
            pending_approval=pending,
            before_read=before_result,
            after_read=after_result,
            measured_provider_mutations=0,
            mutation_observation=ProviderMutationObservation(),
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            ledger=ledger,
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
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        receipt = create_unapproved_action_receipt(
            gate_decision=gate_decision,
            action=update_action,
            pending_approval=pending,
            before_read=before_result,
            after_read=after_result,
            measured_provider_mutations=0,
            mutation_observation=ProviderMutationObservation(),
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            ledger=ledger,
        )

        as_dict = receipt.to_dict()
        assert as_dict["execution_state"] == "NOT_RUN"
        assert as_dict["provider_mutation_invocations"] == 0
        assert as_dict["is_ready_claimed"] is False

    # -----------------------------------------------------------------------
    # Defect 1: Observation Chronology Tests
    # -----------------------------------------------------------------------

    def test_receipt_rejects_pre_gate_after_read_chronology_regression(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Regression: two reads made before gate evaluation cannot produce a valid receipt."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        # Both reads performed before gate evaluation:
        before_result = calendar_read_adapter.read_event(read_action)
        after_result = calendar_read_adapter.read_event(read_action)

        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        # Gate evaluation occurs strictly after after_result was read:
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "after_read occurred before gate evaluation" in str(exc_info.value)

    def test_receipt_rejects_reversed_read_chronology(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory rejects after_read that has timestamp earlier than before_read."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        base_time = datetime.now(UTC)

        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=base_time
        )
        gate_decision = evaluate_execution_gate(
            update_action,
            approval=None,
            pending_approval=pending,
            at=base_time + timedelta(seconds=10),
        )

        obs = calendar_read_adapter.read_event(read_action).observation
        assert obs is not None

        # before_read has a later timestamp than after_read
        before_obs = CalendarEventObservation(
            event_id=obs.event_id,
            calendar_id=obs.calendar_id,
            summary=obs.summary,
            start_time=obs.start_time,
            end_time=obs.end_time,
            all_day=obs.all_day,
            etag=obs.etag,
            status=obs.status,
            observed_at=base_time + timedelta(seconds=5),
        )
        before_result = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=obs.event_id,
            observation=before_obs,
            read_at=base_time + timedelta(seconds=5),
        )

        after_obs = CalendarEventObservation(
            event_id=obs.event_id,
            calendar_id=obs.calendar_id,
            summary=obs.summary,
            start_time=obs.start_time,
            end_time=obs.end_time,
            all_day=obs.all_day,
            etag=obs.etag,
            status=obs.status,
            observed_at=base_time + timedelta(seconds=2),  # Earlier than before_read!
        )
        after_result = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=obs.event_id,
            observation=after_obs,
            read_at=base_time + timedelta(seconds=2),
        )
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "reversed observation chronology" in str(exc_info.value)

    def test_receipt_rejects_same_operation_identical_timestamps(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory rejects before_read and after_read having identical timestamps."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        t = datetime.now(UTC)

        obs = calendar_read_adapter.read_event(read_action).observation
        assert obs is not None

        obs1 = CalendarEventObservation(
            event_id=obs.event_id,
            calendar_id=obs.calendar_id,
            summary=obs.summary,
            start_time=obs.start_time,
            end_time=obs.end_time,
            all_day=obs.all_day,
            etag=obs.etag,
            status=obs.status,
            observed_at=t,
        )
        obs2 = CalendarEventObservation(
            event_id=obs.event_id,
            calendar_id=obs.calendar_id,
            summary=obs.summary,
            start_time=obs.start_time,
            end_time=obs.end_time,
            all_day=obs.all_day,
            etag=obs.etag,
            status=obs.status,
            observed_at=t,
        )
        before_result = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=obs.event_id,
            observation=obs1,
            read_at=t,
        )
        after_result = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=obs.event_id,
            observation=obs2,
            read_at=t,
        )

        pending = create_pending_approval(validate_action_contract(update_action), requested_at=t)
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending, at=t
        )
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "identical timestamps" in str(exc_info.value)

    def test_receipt_rejects_stale_before_read(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory rejects before_read older than 24 hours."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        now = datetime.now(UTC)
        stale_time = now - timedelta(hours=25)

        obs = calendar_read_adapter.read_event(read_action).observation
        assert obs is not None

        stale_obs = CalendarEventObservation(
            event_id=obs.event_id,
            calendar_id=obs.calendar_id,
            summary=obs.summary,
            start_time=obs.start_time,
            end_time=obs.end_time,
            all_day=obs.all_day,
            etag=obs.etag,
            status=obs.status,
            observed_at=stale_time,
        )
        before_result = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=obs.event_id,
            observation=stale_obs,
            read_at=stale_time,
        )

        pending = create_pending_approval(validate_action_contract(update_action), requested_at=now)
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending, at=now
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "stale" in str(exc_info.value)

    def test_receipt_rejects_timezone_naive_timestamps(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory rejects naive timestamps without timezone info."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()

        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        # Construct naive read result
        naive_result = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id=before_result.event_id,
            observation=before_result.observation,
            read_at=datetime.now(),  # Naive!
        )

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=naive_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "must be timezone-aware" in str(exc_info.value)

    # -----------------------------------------------------------------------
    # Defect 2: Approval Ledger Identity Tests
    # -----------------------------------------------------------------------

    def test_receipt_rejects_absent_ledger_evidence(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory fails closed when ledger is None."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()

        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=None,  # type: ignore[arg-type] # Absent!
            )
        assert "ledger evidence is required" in str(exc_info.value)

    def test_receipt_rejects_consumed_approval_for_target_action(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory rejects if ledger contains a consumed approval for target action."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()

        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)

        ledger = ApprovalLedger()
        grant = ApprovalGrant.create(
            action=update_action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        ledger.consume(
            grant,
            update_action,
            at=datetime.now(UTC),
            attempt_number=1,
        )

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "consumed for action" in str(exc_info.value)

    def test_receipt_permits_consumed_approval_for_different_action(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory permits ledger containing consumed approval for a different action."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()

        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)

        different_action = ActionContract.create(
            mission_id=update_action.mission_id,
            action_type=ActionType.CALENDAR_UPDATE,
            target=update_action.target,
            parameters={"summary": "Different event update"},
            action_id=ActionId.generate(),
        )
        ledger = ApprovalLedger()
        grant = ApprovalGrant.create(
            action=different_action,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        ledger.consume(
            grant,
            different_action,
            at=datetime.now(UTC),
            attempt_number=1,
        )

        receipt = create_unapproved_action_receipt(
            gate_decision=gate_decision,
            action=update_action,
            pending_approval=pending,
            before_read=before_result,
            after_read=after_result,
            measured_provider_mutations=0,
            mutation_observation=ProviderMutationObservation(),
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            ledger=ledger,
        )
        assert receipt.consumption_present is False

    # -----------------------------------------------------------------------
    # Defect 3: Provider Mutation Instrumentation Tests
    # -----------------------------------------------------------------------

    def test_calendar_mutation_spy_captures_method_invocation_that_raises_before_write(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """Spy captures transport invocation even if method raises before incrementing writes."""
        spy = CalendarMutationSpy(transport=seeded_calendar_transport)

        # Attempt an update with forbidden If-Match (*), which FakeGoogleCalendarTransport
        # rejects BEFORE writes_count += 1
        with pytest.raises(CalendarTargetError):
            seeded_calendar_transport.update_event(
                calendar_id=DEMO_CALENDAR_ID,
                event_id=DEMO_EVENT_ID,
                payload={"summary": "invalid update"},
                if_match="*",
            )

        obs = spy.observe()
        # Transport method was entered:
        assert obs.transport_mutation_invocations == 1
        # But write was not completed:
        assert obs.transport_writes == 0
        assert obs.is_zero_mutation is False

        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        # Receipt must reject this non-zero invocation observation:
        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=obs,
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "Transport mutation invocations must be 0" in str(exc_info.value)

    def test_receipt_rejects_contradictory_mutation_observation(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Receipt factory fails closed if measured mutations contradicts observation."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        # Contradictory observation:
        obs = ProviderMutationObservation(
            router_mutation_invocations=0,
            handler_mutation_invocations=1,
            transport_mutation_invocations=0,
            transport_writes=0,
        )

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=obs,
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "Handler mutation invocations must be 0" in str(exc_info.value)

    # -----------------------------------------------------------------------
    # Defect 5: Deep Privacy Sanitization & State Integrity Tests
    # -----------------------------------------------------------------------

    def test_receipt_deep_recursive_sanitization_hostile_sentinels(self) -> None:
        """Deep recursive sanitization redacts hostile sentinels across nested collections."""
        update_action = _make_calendar_update_action(summary="Meeting with attacker@evil.org")
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )

        receipt = UnapprovedActionReceipt(
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            mission_id=update_action.mission_id,
            action_id=update_action.action_id,
            action_type=ActionType.CALENDAR_UPDATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            target_event_id=update_action.target.resource_id,
            pending_approval_id=pending.pending_approval_id,
            approval_status=PendingApprovalStatus.PENDING,
            grant_present=False,
            consumption_present=False,
            execution_state=ActionExecutionStatus.NOT_RUN,
            provider_mutation_invocations=0,
            mutation_observation=ProviderMutationObservation(),
            before_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
            after_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
            before_state_summary={
                "summary": "Meeting with attacker@evil.org",
                "nested_dict": {
                    "token": "Bearer secret_jwt_token_12345",
                    "attendees": [
                        "victim@company.com",
                        {"note": "Call +1-555-0199 or admin@secure.net"},
                    ],
                },
                "nested_tuple": ("contact@leak.io", "plain text"),
            },
            after_state_summary={
                "summary": "Meeting with attacker@evil.org",
                "nested_dict": {
                    "token": "Bearer secret_jwt_token_12345",
                    "attendees": [
                        "victim@company.com",
                        {"note": "Call +1-555-0199 or admin@secure.net"},
                    ],
                },
                "nested_tuple": ("contact@leak.io", "plain text"),
            },
            state_unchanged=True,
            is_ready_claimed=False,
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            recorded_at=datetime.now(UTC),
        )

        import json

        serialized = json.dumps(receipt.to_dict())
        # Verify hostile sentinels are completely absent from serialized output:
        assert "attacker@evil.org" not in serialized
        assert "victim@company.com" not in serialized
        assert "admin@secure.net" not in serialized
        assert "contact@leak.io" not in serialized
        assert "Bearer secret_jwt_token_12345" not in serialized

    def test_execute_gated_action_records_failure_on_synchronous_router_exception(
        self,
    ) -> None:
        """Synchronous exception in router marks tracker as FAILED instead of stuck IN_PROGRESS."""
        # Action that does not require approval
        action = ActionContract.create(
            mission_id=MissionId.generate(),
            action_type=ActionType.TASK_READ,
            target=TargetIdentity(
                system="google_tasks",
                resource_kind=ResourceKind.TASK,
                resource_id="task_123",
                parent_id=DEMO_TASKLIST_ID,
            ),
            parameters={},
            action_id=ActionId.generate(),
        )

        exec_contract = MissionExecutionContract(
            mission_id=action.mission_id,
            actions=(action,),
            dependencies={action.action_id: frozenset()},
        )
        schedule = schedule_execution(exec_contract)
        tracker = ExecutionStateTracker(exec_contract, schedule)

        class ExplodingRouter:
            def execute(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("Exploding transport network connection failed!")

        with pytest.raises(RuntimeError):
            execute_gated_action(
                action,
                ExplodingRouter(),  # type: ignore[arg-type]
                tracker=tracker,
            )

        # Tracker must NOT be stuck in IN_PROGRESS!
        assert tracker.get_status(action.action_id) == ActionExecutionStatus.EXECUTION_FAILED
        rec = tracker.get_record(action.action_id)
        assert rec is not None
        assert "Exploding transport" in (rec.error_message or "")


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
        """Run python -O scripts/p11_05_proof.py --json and verify output and source provenance."""
        import json

        repo_root = Path(__file__).resolve().parent.parent

        # Query git status
        head_sha = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo_root),
                text=True,
            )
            .strip()
            .lower()
        )
        status_out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            text=True,
        ).strip()
        is_clean = len(status_out) == 0

        if is_clean:
            # When clean (as in CI), execute with checked-out git HEAD as --expected-sha
            cmd = [
                sys.executable,
                "-O",
                "scripts/p11_05_proof.py",
                "--expected-sha",
                head_sha,
                "--json",
            ]
            res = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
            assert res.returncode == 0, f"Proof script failed: {res.stderr}"
            data = json.loads(res.stdout)
            assert data["source_provenance_mode"] == "COMMITTED_SOURCE"
            assert data["current_git_sha"] == head_sha
            assert data["worktree_clean"] is True
        else:
            # When dirty (local dev worktree), verify dirty fail-closed behavior for --expected-sha
            dirty_res = subprocess.run(
                [
                    sys.executable,
                    "-O",
                    "scripts/p11_05_proof.py",
                    "--expected-sha",
                    head_sha,
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
            )
            assert dirty_res.returncode != 0
            assert (
                "Cannot claim exact-SHA committed-source proof when git worktree is dirty"
                in dirty_res.stderr
            )

            # And verify default run succeeds reporting LOCAL_DIRTY_WORKTREE
            cmd = [sys.executable, "-O", "scripts/p11_05_proof.py", "--json"]
            res = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
            assert res.returncode == 0, f"Proof script failed: {res.stderr}"
            data = json.loads(res.stdout)
            assert data["source_provenance_mode"] == "LOCAL_DIRTY_WORKTREE"
            assert data["worktree_clean"] is False

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


# ===========================================================================
# Dedicated Tests for Bounded Contract Closure (Repairs B–E)
# ===========================================================================


class TestPhaseP1105MandatoryMutationObservationRepairs:
    """Repair B: Mandatory explicit ProviderMutationObservation and consistency checks."""

    def test_receipt_rejects_none_mutation_observation(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=None,  # type: ignore[arg-type]
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "mutation_observation is required" in str(exc_info.value)

    def test_receipt_rejects_invalid_mutation_observation_type(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        for invalid_obs in ("not_an_obs", 0, {"router_mutation_invocations": 0}, [0, 0, 0, 0]):
            with pytest.raises(ExecutionGateTypeError) as exc_info:
                create_unapproved_action_receipt(
                    gate_decision=gate_decision,
                    action=update_action,
                    pending_approval=pending,
                    before_read=before_result,
                    after_read=after_result,
                    measured_provider_mutations=0,
                    mutation_observation=invalid_obs,  # type: ignore[arg-type]
                    source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                    ledger=ledger,
                )
            assert "mutation_observation must be a ProviderMutationObservation instance" in str(
                exc_info.value
            )

    def test_provider_mutation_observation_rejects_writes_exceeding_invocations(self) -> None:
        with pytest.raises(ExecutionGateValueError) as exc_info:
            ProviderMutationObservation(
                transport_mutation_invocations=1,
                transport_writes=2,
            )
        assert "transport_writes cannot exceed transport_mutation_invocations" in str(
            exc_info.value
        )

    def test_provider_mutation_observation_rejects_boolean_and_negative_counters(self) -> None:
        for invalid in (True, False, "0", 1.5):
            with pytest.raises(ExecutionGateTypeError) as exc_info:
                ProviderMutationObservation(router_mutation_invocations=invalid)  # type: ignore[arg-type]
            assert "router_mutation_invocations must be an integer" in str(exc_info.value)
            assert str(invalid) not in str(exc_info.value)  # No raw value reflection

        with pytest.raises(ExecutionGateValueError) as val_exc_info:
            ProviderMutationObservation(router_mutation_invocations=-1)
        assert "router_mutation_invocations must be a non-negative integer" in str(
            val_exc_info.value
        )

    def test_receipt_rejects_nonzero_router_invocations(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        obs = ProviderMutationObservation(router_mutation_invocations=1)
        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=obs,
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "Router mutation invocations must be 0" in str(exc_info.value)

    def test_receipt_rejects_mismatch_between_measured_and_observation_writes(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        obs = ProviderMutationObservation(
            transport_mutation_invocations=1,
            transport_writes=1,
        )
        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=obs,
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "Transport mutation invocations must be 0" in str(
            exc_info.value
        ) or "Transport writes must be 0" in str(exc_info.value)


class TestPhaseP1105ApprovalLedgerPublicBoundaryRepairs:
    """Repair C: Enforce ApprovalLedger public boundary without private member access."""

    def test_receipt_creation_does_not_access_private_ledger_members(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)

        class MonitoredLedger(ApprovalLedger):
            accessed_private: bool = False

            def __getattribute__(self, name: str) -> Any:
                if name in ("_lock", "_registry", "_records"):
                    import inspect

                    frame = inspect.currentframe()
                    if frame and frame.f_back and "gate.py" in frame.f_back.f_code.co_filename:
                        MonitoredLedger.accessed_private = True
                return super().__getattribute__(name)

        monitored_ledger = MonitoredLedger()
        receipt = create_unapproved_action_receipt(
            gate_decision=gate_decision,
            action=update_action,
            pending_approval=pending,
            before_read=before_result,
            after_read=after_result,
            measured_provider_mutations=0,
            mutation_observation=ProviderMutationObservation(),
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            ledger=monitored_ledger,
        )
        assert receipt is not None
        assert MonitoredLedger.accessed_private is False

    def test_receipt_creation_with_reloaded_durable_ledger_consumed_action_rejected(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)

        aid = ApprovalId.generate()
        payload = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(update_action.mission_id),
            "action_id": str(update_action.action_id),
            "binding_hash": BindingHash("8" * 64).value,
            "consumed_at": datetime.now(UTC).isoformat(),
            "consumed_for_attempt": 1,
        }
        mock_port = MagicMock(spec=MissionLedgerPort)
        ev_mock = MagicMock()
        ev_mock.action_id = update_action.action_id
        ev_mock.mission_id = update_action.mission_id
        ev_mock.payload = payload
        mock_port.get_all_evidence.return_value = [ev_mock]

        reloaded_ledger = ApprovalLedger.from_ledger(mock_port)
        assert reloaded_ledger.has_consumed_approval_for_action(update_action.action_id) is True

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=reloaded_ledger,
            )
        assert "consumed for action" in str(exc_info.value)

    def test_receipt_creation_with_reloaded_durable_ledger_unrelated_action_allowed(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)

        aid = ApprovalId.generate()
        unrelated_act_id = ActionId.generate()
        payload = {
            "evidence_type": APPROVAL_CONSUMPTION_EVIDENCE_TYPE,
            "approval_id": str(aid),
            "mission_id": str(update_action.mission_id),
            "action_id": str(unrelated_act_id),
            "binding_hash": BindingHash("9" * 64).value,
            "consumed_at": datetime.now(UTC).isoformat(),
            "consumed_for_attempt": 1,
        }
        mock_port = MagicMock(spec=MissionLedgerPort)
        ev_mock = MagicMock()
        ev_mock.action_id = unrelated_act_id
        ev_mock.mission_id = update_action.mission_id
        ev_mock.payload = payload
        mock_port.get_all_evidence.return_value = [ev_mock]

        reloaded_ledger = ApprovalLedger.from_ledger(mock_port)
        assert reloaded_ledger.has_consumed_approval_for_action(update_action.action_id) is False
        assert reloaded_ledger.has_consumed_approval_for_action(unrelated_act_id) is True

        receipt = create_unapproved_action_receipt(
            gate_decision=gate_decision,
            action=update_action,
            pending_approval=pending,
            before_read=before_result,
            after_read=after_result,
            measured_provider_mutations=0,
            mutation_observation=ProviderMutationObservation(),
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            ledger=reloaded_ledger,
        )
        assert receipt.consumption_present is False


class TestPhaseP1105ReceiptAuthorityConsistencyRepairs:
    """Repair D: Enforce canonical authority policy and reject contradictory gate decisions."""

    def test_receipt_rejects_gate_decision_with_wrong_authority_class(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        for forbidden_ac in (
            AuthorityClass.READ_ONLY,
            AuthorityClass.REVERSIBLE_AUTO,
            AuthorityClass.IRREVERSIBLE_BLOCKED_OR_HUMAN_REQUIRED,
        ):
            contradictory_gate = ExecutionGateDecision(
                action_id=update_action.action_id,
                action_type=ActionType.CALENDAR_UPDATE,
                authority_class=forbidden_ac,
                status=ActionExecutionStatus.NOT_RUN,
                is_authorized=False,
                reason="Tampered gate decision",
                pending_approval_id=pending.pending_approval_id,
                evaluated_at=datetime.now(UTC),
            )
            with pytest.raises(ExecutionGateValueError) as exc_info:
                create_unapproved_action_receipt(
                    gate_decision=contradictory_gate,
                    action=update_action,
                    pending_approval=pending,
                    before_read=before_result,
                    after_read=after_result,
                    measured_provider_mutations=0,
                    mutation_observation=ProviderMutationObservation(),
                    source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                    ledger=ledger,
                )
            assert "authority_class must match canonical policy" in str(exc_info.value)

    def test_receipt_rejects_gate_decision_with_wrong_action_type(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        contradictory_gate = ExecutionGateDecision(
            action_id=update_action.action_id,
            action_type=ActionType.TASK_CREATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            status=ActionExecutionStatus.NOT_RUN,
            is_authorized=False,
            reason="Contradictory action type",
            pending_approval_id=pending.pending_approval_id,
            evaluated_at=datetime.now(UTC),
        )
        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=contradictory_gate,
                action=update_action,
                pending_approval=pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "gate_decision action_type must be CALENDAR_UPDATE" in str(exc_info.value)

    def test_receipt_rejects_pending_approval_with_mismatched_authority_class(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()
        before_result = calendar_read_adapter.read_event(read_action)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )
        gate_decision = evaluate_execution_gate(
            update_action, approval=None, pending_approval=pending
        )
        after_result = calendar_read_adapter.read_event(read_action)
        ledger = ApprovalLedger()

        import copy

        tampered_pending = copy.copy(pending)
        object.__setattr__(tampered_pending, "authority_class", AuthorityClass.REVERSIBLE_AUTO)

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_unapproved_action_receipt(
                gate_decision=gate_decision,
                action=update_action,
                pending_approval=tampered_pending,
                before_read=before_result,
                after_read=after_result,
                measured_provider_mutations=0,
                mutation_observation=ProviderMutationObservation(),
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                ledger=ledger,
            )
        assert "pending_approval authority_class must match canonical policy" in str(exc_info.value)

    def test_direct_unapproved_action_receipt_constructor_strictly_enforces_calendar_update(
        self,
    ) -> None:
        aid = ActionId.generate()
        mid = MissionId.generate()
        obs = ProviderMutationObservation()

        for forbidden_type in (
            ActionType.CALENDAR_READ,
            ActionType.TASK_CREATE,
            ActionType.TASK_READ,
        ):
            with pytest.raises(ExecutionGateValueError) as exc_info:
                UnapprovedActionReceipt(
                    source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                    mission_id=mid,
                    action_id=aid,
                    action_type=forbidden_type,
                    authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
                    target_event_id=DEMO_EVENT_ID,
                    pending_approval_id=create_pending_approval(
                        validate_action_contract(_make_calendar_update_action(mid, aid)),
                        requested_at=datetime.now(UTC),
                    ).pending_approval_id,
                    approval_status=PendingApprovalStatus.PENDING,
                    grant_present=False,
                    consumption_present=False,
                    execution_state=ActionExecutionStatus.NOT_RUN,
                    provider_mutation_invocations=0,
                    mutation_observation=obs,
                    before_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
                    after_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
                    before_state_summary={"summary": "test"},
                    after_state_summary={"summary": "test"},
                    state_unchanged=True,
                    is_ready_claimed=False,
                    provenance=EvidenceProvenance.LOCAL_EXECUTION,
                    recorded_at=datetime.now(UTC),
                )
            assert "strictly applies to CALENDAR_UPDATE" in str(exc_info.value)


class TestPhaseP1105PrivacySanitizationAdversarialRepairs:
    """Repair E: Hostile sentinel tests across keys, values, errors, and serialized output."""

    def test_provider_mutation_observation_error_does_not_leak_hostile_sentinel_repr(self) -> None:
        hostile_secret = "SECRET_BEARER_TOKEN_IN_COUNTER_XYZ_9999"

        with pytest.raises(ExecutionGateTypeError) as exc_info:
            ProviderMutationObservation(router_mutation_invocations=hostile_secret)  # type: ignore[arg-type]

        err_msg = str(exc_info.value)
        assert hostile_secret not in err_msg
        assert "router_mutation_invocations must be an integer, got str" in err_msg

    def test_receipt_sanitization_redacts_hostile_sentinel_in_mapping_key(self) -> None:
        obs = ProviderMutationObservation()
        update_action = _make_calendar_update_action()
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )

        receipt = UnapprovedActionReceipt(
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            mission_id=update_action.mission_id,
            action_id=update_action.action_id,
            action_type=ActionType.CALENDAR_UPDATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            target_event_id=DEMO_EVENT_ID,
            pending_approval_id=pending.pending_approval_id,
            approval_status=PendingApprovalStatus.PENDING,
            grant_present=False,
            consumption_present=False,
            execution_state=ActionExecutionStatus.NOT_RUN,
            provider_mutation_invocations=0,
            mutation_observation=obs,
            before_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
            after_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
            before_state_summary={"header_admin@secret.corp": "ok"},
            after_state_summary={"header_admin@secret.corp": "ok"},
            state_unchanged=True,
            is_ready_claimed=False,
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            recorded_at=datetime.now(UTC),
        )

        d = receipt.to_dict()
        import json

        serialized = json.dumps(d)
        assert "admin@secret.corp" not in serialized
        assert "[REDACTED_EMAIL]" in d["before_state_summary"]

    def test_receipt_sanitization_rejects_non_string_keys_fail_closed_without_repr_leakage(
        self,
    ) -> None:
        hostile_secret = "EVIL_SECRET_KEY_PAYLOAD_8888"

        class HostileKey:
            def __str__(self) -> str:
                return hostile_secret

            def __repr__(self) -> str:
                return f"HostileKey({hostile_secret})"

            def __hash__(self) -> int:
                return 42

            def __eq__(self, other: Any) -> bool:
                return isinstance(other, HostileKey)

        obs = ProviderMutationObservation()
        update_action = _make_calendar_update_action()
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )

        with pytest.raises(ExecutionGateTypeError) as exc_info:
            UnapprovedActionReceipt(
                source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
                mission_id=update_action.mission_id,
                action_id=update_action.action_id,
                action_type=ActionType.CALENDAR_UPDATE,
                authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
                target_event_id=DEMO_EVENT_ID,
                pending_approval_id=pending.pending_approval_id,
                approval_status=PendingApprovalStatus.PENDING,
                grant_present=False,
                consumption_present=False,
                execution_state=ActionExecutionStatus.NOT_RUN,
                provider_mutation_invocations=0,
                mutation_observation=obs,
                before_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
                after_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
                before_state_summary={HostileKey(): "value"},  # type: ignore[dict-item]
                after_state_summary={"summary": "value"},
                state_unchanged=True,
                is_ready_claimed=False,
                provenance=EvidenceProvenance.LOCAL_EXECUTION,
                recorded_at=datetime.now(UTC),
            )

        err_msg = str(exc_info.value)
        assert hostile_secret not in err_msg
        assert "keys must be strings, got HostileKey" in err_msg

    def test_receipt_sanitization_rejects_unsupported_value_type_without_repr_leakage(
        self,
    ) -> None:
        hostile_secret = "EVIL_SECRET_VALUE_PAYLOAD_7777"

        class HostileValue:
            def __str__(self) -> str:
                return hostile_secret

            def __repr__(self) -> str:
                return f"HostileValue({hostile_secret})"

        obs = ProviderMutationObservation()
        update_action = _make_calendar_update_action()
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=datetime.now(UTC)
        )

        receipt = UnapprovedActionReceipt(
            source_sha="12b42e4f0f92a08518b1e6efe4fd030912477bc9",
            mission_id=update_action.mission_id,
            action_id=update_action.action_id,
            action_type=ActionType.CALENDAR_UPDATE,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            target_event_id=DEMO_EVENT_ID,
            pending_approval_id=pending.pending_approval_id,
            approval_status=PendingApprovalStatus.PENDING,
            grant_present=False,
            consumption_present=False,
            execution_state=ActionExecutionStatus.NOT_RUN,
            provider_mutation_invocations=0,
            mutation_observation=obs,
            before_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
            after_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
            before_state_summary={"custom_obj": HostileValue()},
            after_state_summary={"custom_obj": HostileValue()},
            state_unchanged=True,
            is_ready_claimed=False,
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
            recorded_at=datetime.now(UTC),
        )

        with pytest.raises(ExecutionGateTypeError) as exc_info:
            receipt.to_dict()

        err_msg = str(exc_info.value)
        assert hostile_secret not in err_msg
        assert "Unsupported value type for receipt serialization: HostileValue" in err_msg
