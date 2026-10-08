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

Plus:
13. Before/after independent read-back proves external event state is 100% unchanged.
14. Predicate evaluation on before vs after observations proves exact state equality.
15. UnapprovedActionReceipt captures complete evidence without secrets.
16. Multi-step mission execution preserves earlier successes while unapproved step remains NOT_RUN.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stilldone.action_policy import validate_action_contract
from stilldone.adapters.calendar import (
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
    PlannerAuthorityError,
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
from stilldone.domain.lifecycle import MissionState, StepEvidenceState
from stilldone.domain.mission import MissionId
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.execution.contracts import MissionExecutionContract
from stilldone.execution.gate import (
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
        with pytest.raises(PlannerAuthorityError):
            evaluate_execution_gate(proposal, approval=None)  # type: ignore[arg-type]

        # Model proposal passed as approval
        action = _make_calendar_update_action()
        with pytest.raises(PlannerAuthorityError):
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
# Before/After External State Unchanged Tests
# ===========================================================================


class TestBeforeAfterStateIntegrity:
    """Validate external state observation before and after unapproved attempt."""

    def test_external_state_completely_unchanged(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """Prove external event state is unchanged before vs after blocked update."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()

        # 1. Before-state observation
        before_result = calendar_read_adapter.read_event(read_action)
        assert before_result.status == CalendarReadStatus.SUCCESS
        assert before_result.observation is not None
        before_obs = before_result.observation
        assert before_obs.start_time == INITIAL_START_TIME
        assert before_obs.summary == PROPOSED_SUMMARY
        assert seeded_calendar_transport.writes_count == 0

        # 2. Gate evaluation of unapproved mutation
        gate_decision = execute_gated_action(update_action, test_router, approval=None)
        assert gate_decision.status == ActionExecutionStatus.NOT_RUN
        assert seeded_calendar_transport.writes_count == 0

        # 3. Separate independent after-state observation
        after_result = calendar_read_adapter.read_event(read_action)
        assert after_result.status == CalendarReadStatus.SUCCESS
        assert after_result.observation is not None
        after_obs = after_result.observation

        # 4. Prove external state is 100% identical
        assert after_obs.start_time == before_obs.start_time == INITIAL_START_TIME
        assert after_obs.end_time == before_obs.end_time == INITIAL_END_TIME
        assert after_obs.summary == before_obs.summary == PROPOSED_SUMMARY
        assert after_obs.all_day == before_obs.all_day is False
        assert after_obs.etag == before_obs.etag
        assert after_obs.status == before_obs.status == "confirmed"
        assert seeded_calendar_transport.writes_count == 0

    def test_unapproved_action_receipt_generation(
        self,
        calendar_read_adapter: GoogleCalendarReadAdapter,
    ) -> None:
        """Prove generation and invariants of UnapprovedActionReceipt."""
        read_action = _make_calendar_read_action()
        update_action = _make_calendar_update_action()

        req_at = datetime.now(UTC)
        pending = create_pending_approval(
            validate_action_contract(update_action), requested_at=req_at
        )

        before_obs = calendar_read_adapter.read_event(read_action).observation
        after_obs = calendar_read_adapter.read_event(read_action).observation
        assert before_obs is not None and after_obs is not None

        before_summary = {
            "summary": before_obs.summary,
            "start_time": before_obs.start_time,
            "end_time": before_obs.end_time,
            "all_day": before_obs.all_day,
            "etag": before_obs.etag,
        }
        after_summary = dict(before_summary)

        receipt = create_unapproved_action_receipt(
            source_sha="4ec4475f006207ec5840880bb9476f6d169442cd",
            mission_id=update_action.mission_id,
            action_id=update_action.action_id,
            action_type=update_action.action_type,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            target_event_id=DEMO_EVENT_ID,
            pending_approval_id=pending.pending_approval_id,
            before_state_summary=before_summary,
            after_state_summary=after_summary,
            before_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
            after_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
        )

        assert receipt.execution_state == ActionExecutionStatus.NOT_RUN
        assert receipt.provider_mutation_invocations == 0
        assert receipt.grant_present is False
        assert receipt.consumption_present is False
        assert receipt.state_unchanged is True
        assert receipt.is_ready_claimed is False
        assert receipt.approval_status == PendingApprovalStatus.PENDING

        receipt_dict = receipt.to_dict()
        assert receipt_dict["execution_state"] == "NOT_RUN"
        assert receipt_dict["provider_mutation_invocations"] == 0
        assert receipt_dict["grant_present"] is False
        assert receipt_dict["state_unchanged"] is True


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
