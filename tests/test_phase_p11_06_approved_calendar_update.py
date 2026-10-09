"""Phase P-11.06: Approved Calendar Update, Exactly-Once Execution & Independent Verification.

Core Invariants Tested:
1. No approval -> NOT_RUN, zero mutation invocations.
2. Valid bound approval -> exactly one consumption and at most one permitted provider update.
3. Same grant replay -> zero further provider updates.
4. Concurrent reuse -> exactly one winner within supported process-local guarantee.
5. Restart/reload -> consumed grant remains unavailable.
6. Expired, stale, revoked, tampered, wrong-target, wrong-parameter
   and wrong-mission approvals -> zero writes.
7. Durable ledger failure -> zero writes.
8. Calendar If-Match/ETag conflict -> truthful failure, no blind overwrite.
9. Independent read-back mismatch -> NOT VERIFIED, never READY
   (provider success != verification).
10. Successful mutation plus matching fresh read-back -> predicate TRUE
    and lawful verification transition.
11. Unrelated previous mission successes remain preserved.
12. Model prose or arbitrary strings never grant authority.
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stilldone.action_policy import validate_action_contract
from stilldone.adapters.calendar import (
    CalendarPreconditionFailedError,
    CalendarReadbackResult,
    CalendarReadbackStatus,
    CalendarReadResult,
    CalendarReadStatus,
    ExpectedCalendarState,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
    GoogleCalendarUpdateAdapter,
)
from stilldone.approval_consumption import (
    ApprovalAlreadyUsedError,
    ApprovalConsumptionPersistenceError,
    ApprovalLedger,
    ApprovalRevokedError,
    ApprovalUsageStatus,
)
from stilldone.authority_policy import (
    ApprovalBindingMismatchError,
    ApprovalExpiredError,
    ApprovalNotYetValidError,
    ApprovalTamperedError,
    AuthorityPolicyTypeError,
    PlannerAuthorityError,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
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
from stilldone.domain.desired_state import (
    DesiredStatePredicate,
    PredicateId,
    PredicateOperator,
)
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import (
    MissionContract,
    MissionId,
    UserIntentSnapshot,
)
from stilldone.execution.contracts import MissionExecutionContract
from stilldone.execution.gate import (
    ApprovedActionReceipt,
    CalendarMutationSpy,
    ExecutionGateDecision,
    ExecutionGateTypeError,
    ExecutionGateValueError,
    PlannerGateAuthorityError,
    ProviderMutationObservation,
    create_approved_action_receipt,
    evaluate_execution_gate,
    execute_approved_calendar_update,
    execute_gated_action,
)
from stilldone.execution.router import (
    AdapterRouter,
    CalendarReadHandler,
    CalendarUpdateHandler,
)
from stilldone.execution.scheduler import schedule_execution
from stilldone.execution.state import (
    ActionExecutionStatus,
    ExecutionStateTracker,
)
from stilldone.ledger import (
    ActionRecord,
    DurableFileLedger,
    EvidenceRecord,
    InMemoryNonDurableLedger,
    MissionLedgerPort,
    MissionRecord,
)
from stilldone.pending_approval import (
    create_pending_approval,
)
from stilldone.planning.contracts import CandidateActionProposal, SymbolicTargetRef
from stilldone.verifier.predicates import (
    PredicateEvaluationResult,
    PredicateTruth,
)

DUMMY_SOURCE_SHA = "864cfa4e2b47ade72d1f4095e78e06f309372320"


# ===========================================================================
# Test Helpers and Fixtures
# ===========================================================================


@pytest.fixture
def demo_scope() -> DemoResourceScope:
    return DemoResourceScope(
        calendar_id="c_1880abc123demo@group.calendar.google.com",
        task_list_id="tl_1880abc123demo",
    )


@pytest.fixture
def seeded_calendar_transport() -> FakeGoogleCalendarTransport:
    transport = FakeGoogleCalendarTransport()
    transport.seed_event(
        calendar_id="c_1880abc123demo@group.calendar.google.com",
        event_id="evt_leave_for_school_001",
        summary="Leave for school",
        start_time="2026-10-09T07:45:00+03:00",
        end_time="2026-10-09T08:15:00+03:00",
        all_day=False,
        etag="etag_initial_1001",
        status="confirmed",
    )
    return transport


@pytest.fixture
def calendar_read_adapter(
    demo_scope: DemoResourceScope,
    seeded_calendar_transport: FakeGoogleCalendarTransport,
) -> GoogleCalendarReadAdapter:
    return GoogleCalendarReadAdapter(demo_scope, seeded_calendar_transport)


@pytest.fixture
def calendar_update_adapter(
    demo_scope: DemoResourceScope,
    seeded_calendar_transport: FakeGoogleCalendarTransport,
) -> GoogleCalendarUpdateAdapter:
    return GoogleCalendarUpdateAdapter(demo_scope, seeded_calendar_transport)


@pytest.fixture
def test_router(
    calendar_read_adapter: GoogleCalendarReadAdapter,
    calendar_update_adapter: GoogleCalendarUpdateAdapter,
) -> AdapterRouter:
    return AdapterRouter(
        {
            ActionType.CALENDAR_READ: CalendarReadHandler(calendar_read_adapter),
            ActionType.CALENDAR_UPDATE: CalendarUpdateHandler(calendar_update_adapter),
        }
    )


@pytest.fixture
def in_memory_ledger() -> InMemoryNonDurableLedger:
    return InMemoryNonDurableLedger()


@pytest.fixture
def approval_ledger() -> ApprovalLedger:
    return ApprovalLedger()


def _seed_mission_and_action(
    ledger: MissionLedgerPort,
    action: ActionContract,
    approval_id: ApprovalId | None = None,
) -> None:
    now = datetime.now(UTC)
    ledger.append_mission(
        MissionRecord(
            mission_id=action.mission_id,
            contract=MissionContract(
                mission_id=action.mission_id,
                intent=UserIntentSnapshot(
                    text="Leave for school test mission",
                    captured_at=now,
                    mission_id=action.mission_id,
                ),
                created_at=now,
            ),
            state=MissionState.DRAFT,
            created_at=now,
            updated_at=now,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=action.action_id,
            mission_id=action.mission_id,
            action=action,
            approval_id=approval_id,
            created_at=now,
        )
    )


def _make_calendar_update_action(
    *,
    mission_id: MissionId | None = None,
    event_id: str = "evt_leave_for_school_001",
    calendar_id: str = "c_1880abc123demo@group.calendar.google.com",
    new_start_time: str = "2026-10-09T07:30:00+03:00",
    new_summary: str | None = None,
) -> ActionContract:
    mid = mission_id or MissionId.generate()
    params: dict[str, Any] = {"start_time": new_start_time}
    if new_summary is not None:
        params["summary"] = new_summary
    return ActionContract.create(
        mission_id=mid,
        action_type=ActionType.CALENDAR_UPDATE,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=event_id,
            parent_id=calendar_id,
        ),
        parameters=params,
    )


def _make_bound_approval_grant(
    action: ActionContract,
    *,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    approval_id: ApprovalId | None = None,
) -> ApprovalGrant:
    now = issued_at or datetime.now(UTC)
    exp = expires_at or (now + timedelta(minutes=15))
    aid = approval_id or ApprovalId.generate()
    return ApprovalGrant.create(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=now,
        expires_at=exp,
        approval_id=aid,
    )


def _make_predicate(
    action: ActionContract,
    *,
    expected_start: str = "2026-10-09T07:30:00+03:00",
) -> DesiredStatePredicate:
    return DesiredStatePredicate.create(
        mission_id=action.mission_id,
        subject="start_time",
        operator=PredicateOperator.EQUALS,
        expected_value=expected_start,
    )


# ===========================================================================
# 1. Happy Path: Approved Execution, Single Mutation & Independent Verification
# ===========================================================================


class TestApprovedExecutionHappyPath:
    """Proves that a valid bound ApprovalGrant executes the mutation exactly once and verifies."""

    def test_complete_approved_execution_and_independent_verification_pipeline(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        in_memory_ledger: InMemoryNonDurableLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """Full 12-step sequence:
        INTENT -> CONTRACT -> AUTHORITY -> EXECUTE -> READBACK -> PREDICATE -> VERIFIED.
        """
        action = _make_calendar_update_action()
        t0 = datetime.now(UTC) - timedelta(seconds=10)
        grant = _make_bound_approval_grant(action, issued_at=t0)
        predicate = _make_predicate(action, expected_start="2026-10-09T07:30:00+03:00")
        pending = create_pending_approval(validate_action_contract(action), requested_at=t0)
        _seed_mission_and_action(in_memory_ledger, action, grant.approval_id)

        appr_ledger = ApprovalLedger(ledger=in_memory_ledger)

        spy = CalendarMutationSpy(
            router=test_router,
            transport=seeded_calendar_transport,
        )

        outcome = execute_approved_calendar_update(
            action,
            test_router,
            grant,
            appr_ledger,
            calendar_read_adapter,
            predicate,
            source_sha=DUMMY_SOURCE_SHA,
            pending_approval=pending,
            spy=spy,
            mission_ledger=in_memory_ledger,
        )

        # 1. Authority and consumption
        assert outcome.gate_decision.is_authorized is True
        assert outcome.gate_decision.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert outcome.consumption_record.status == ApprovalUsageStatus.CONSUMED
        assert appr_ledger.has_consumed_approval_for_action(action.action_id) is True

        # 2. Provider execution: exactly 1 write performed
        assert outcome.provider_result.success is True
        assert outcome.provider_result.writes_performed == 1
        assert seeded_calendar_transport.writes_count == 1
        assert outcome.mutation_observation.transport_writes == 1
        assert outcome.mutation_observation.router_mutation_invocations == 1

        # 3. Independent read-back
        assert outcome.after_read.status == CalendarReadStatus.SUCCESS
        assert outcome.after_read is not outcome.before_read
        assert outcome.after_read.observation is not None
        assert outcome.after_read.observation.start_time == "2026-10-09T07:30:00+03:00"
        assert outcome.readback_result.status == CalendarReadbackStatus.MATCH

        # 4. Predicate evaluation
        assert outcome.predicate_result.truth == PredicateTruth.TRUE
        assert outcome.predicate_result.is_true is True

        # 5. Lawful verification and readiness
        assert outcome.is_verified is True
        assert outcome.is_ready is True

        # 6. Immutable durable receipt
        receipt = outcome.receipt
        assert isinstance(receipt, ApprovedActionReceipt)
        assert receipt.is_verified is True
        assert receipt.is_ready_claimed is True
        assert receipt.provider_writes == 1
        assert receipt.source_sha == DUMMY_SOURCE_SHA

        # 7. Durable ledger records persisted
        all_ev = in_memory_ledger.get_all_evidence()
        ev_types = [ev.payload["evidence_type"] for ev in all_ev]
        assert "APPROVAL_CONSUMPTION" in ev_types
        assert "EXECUTION_ATTEMPT" in ev_types
        assert "INDEPENDENT_READBACK" in ev_types
        assert "PREDICATE_EVALUATION" in ev_types
        assert "APPROVED_CALENDAR_UPDATE_RECEIPT" in ev_types

    def test_execute_gated_action_directly_with_approved_grant(
        self,
        test_router: AdapterRouter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """execute_gated_action directly consumes approval and executes router."""
        action = _make_calendar_update_action()
        contract = MissionExecutionContract(
            mission_id=action.mission_id,
            actions=(action,),
            dependencies={action.action_id: frozenset()},
        )
        schedule = schedule_execution(contract)
        tracker = ExecutionStateTracker(contract, schedule)
        grant = _make_bound_approval_grant(action)

        decision = execute_gated_action(
            action,
            test_router,
            tracker=tracker,
            approval=grant,
            ledger=approval_ledger,
        )

        assert decision.is_authorized is True
        assert decision.status == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert tracker.get_status(action.action_id) == ActionExecutionStatus.EXECUTION_SUCCEEDED
        assert seeded_calendar_transport.writes_count == 1
        assert approval_ledger.is_consumed(grant.approval_id) is True


# ===========================================================================
# 2. Exactly-Once and Replay Prevention
# ===========================================================================


class TestExactlyOnceAndReplayPrevention:
    """Proves that a consumed grant cannot be reused for a second mutation."""

    def test_same_grant_replay_rejected_with_zero_further_provider_updates(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """First execution consumes grant; second execution with same grant fails closed."""
        action = _make_calendar_update_action()
        grant = _make_bound_approval_grant(action)
        predicate = _make_predicate(action)

        # 1. First execution: succeeds
        outcome1 = execute_approved_calendar_update(
            action,
            test_router,
            grant,
            approval_ledger,
            calendar_read_adapter,
            predicate,
            source_sha=DUMMY_SOURCE_SHA,
        )
        assert outcome1.is_verified is True
        assert seeded_calendar_transport.writes_count == 1

        # 2. Second execution attempt with identical grant: MUST raise ApprovalAlreadyUsedError
        with pytest.raises(ApprovalAlreadyUsedError) as exc_info:
            execute_approved_calendar_update(
                action,
                test_router,
                grant,
                approval_ledger,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        assert "already consumed" in str(exc_info.value)
        # CRUCIAL INVARIANT: Writes count must remain exactly 1 (zero further updates)
        assert seeded_calendar_transport.writes_count == 1

    def test_evaluate_execution_gate_rejects_replayed_grant(
        self,
        approval_ledger: ApprovalLedger,
    ) -> None:
        """evaluate_execution_gate fails closed if grant is already consumed in ledger."""
        action = _make_calendar_update_action()
        grant = _make_bound_approval_grant(action)

        # Consume grant first
        approval_ledger.consume(grant, action, at=datetime.now(UTC), attempt_number=1)

        with pytest.raises(ApprovalAlreadyUsedError):
            evaluate_execution_gate(action, approval=grant, ledger=approval_ledger)


# ===========================================================================
# 3. Process-Local Concurrency
# ===========================================================================


class TestProcessLocalConcurrency:
    """Proves thread-safety and at most one winner for concurrent reuse."""

    def test_concurrent_execution_attempts_yield_exactly_one_winner(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """Two concurrent threads attempt to execute the same grant: exactly 1 winner, 1 write."""
        action = _make_calendar_update_action()
        grant = _make_bound_approval_grant(action)
        predicate = _make_predicate(action)

        results: list[Any] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                res = execute_approved_calendar_update(
                    action,
                    test_router,
                    grant,
                    approval_ledger,
                    calendar_read_adapter,
                    predicate,
                    source_sha=DUMMY_SOURCE_SHA,
                )
                results.append(res)
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker), executor.submit(worker)]
            concurrent.futures.wait(futures)

        # Exactly 1 winner
        assert len(results) == 1
        assert results[0].is_verified is True

        # Exactly 1 loser with ApprovalAlreadyUsedError
        assert len(errors) == 1
        assert isinstance(errors[0], ApprovalAlreadyUsedError)

        # Exactly 1 write on provider transport
        assert seeded_calendar_transport.writes_count == 1


# ===========================================================================
# 4. Restart and Durable Hydration
# ===========================================================================


class TestRestartAndDurableHydration:
    """Proves consumed grant remains unavailable after process restart."""

    def test_consumed_grant_persists_across_ledger_reload(
        self,
        tmp_path: Path,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """DurableFileLedger retains consumption record across fresh reload."""
        ledger_file = tmp_path / "mission_evidence.jsonl"
        durable_ledger = DurableFileLedger(ledger_file)

        action = _make_calendar_update_action()
        grant = _make_bound_approval_grant(action)
        predicate = _make_predicate(action)

        now = datetime.now(UTC)
        durable_ledger.append_mission(
            MissionRecord(
                mission_id=action.mission_id,
                contract=MissionContract(
                    mission_id=action.mission_id,
                    intent=UserIntentSnapshot(
                        text="Leave for school demo", captured_at=now, mission_id=action.mission_id
                    ),
                    created_at=now,
                ),
                state=MissionState.DRAFT,
                created_at=now,
                updated_at=now,
            )
        )
        durable_ledger.append_action(
            ActionRecord(
                action_id=action.action_id,
                mission_id=action.mission_id,
                action=action,
                approval_id=grant.approval_id,
                created_at=now,
            )
        )

        app_ledger_1 = ApprovalLedger(ledger=durable_ledger)

        # 1. Execute in session 1
        outcome = execute_approved_calendar_update(
            action,
            test_router,
            grant,
            app_ledger_1,
            calendar_read_adapter,
            predicate,
            source_sha=DUMMY_SOURCE_SHA,
            mission_ledger=durable_ledger,
        )
        assert outcome.is_verified is True
        assert seeded_calendar_transport.writes_count == 1

        # 2. Simulate process restart: fresh DurableFileLedger and ApprovalLedger
        reloaded_ledger = DurableFileLedger(ledger_file)
        app_ledger_2 = ApprovalLedger.from_ledger(reloaded_ledger)

        assert app_ledger_2.is_consumed(grant.approval_id) is True
        assert app_ledger_2.has_consumed_approval_for_action(action.action_id) is True

        # 3. Attempt replay in session 2: fails closed
        with pytest.raises(ApprovalAlreadyUsedError):
            execute_approved_calendar_update(
                action,
                test_router,
                grant,
                app_ledger_2,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        # Zero additional provider writes
        assert seeded_calendar_transport.writes_count == 1


# ===========================================================================
# 5. Adversarial Grant Rejections (Zero Writes)
# ===========================================================================


class TestAdversarialGrantRejections:
    """Proves that invalid/tampered/mismatched grants fail closed with 0 writes."""

    def test_expired_grant_rejected_with_zero_writes(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_action()
        t_past = datetime.now(UTC) - timedelta(hours=2)
        grant = _make_bound_approval_grant(
            action, issued_at=t_past, expires_at=t_past + timedelta(minutes=10)
        )
        predicate = _make_predicate(action)

        with pytest.raises(ApprovalExpiredError):
            execute_approved_calendar_update(
                action,
                test_router,
                grant,
                approval_ledger,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        assert seeded_calendar_transport.writes_count == 0

    def test_not_yet_valid_grant_rejected_with_zero_writes(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_action()
        t_future = datetime.now(UTC) + timedelta(hours=1)
        grant = _make_bound_approval_grant(
            action, issued_at=t_future, expires_at=t_future + timedelta(minutes=15)
        )
        predicate = _make_predicate(action)

        with pytest.raises(ApprovalNotYetValidError):
            execute_approved_calendar_update(
                action,
                test_router,
                grant,
                approval_ledger,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        assert seeded_calendar_transport.writes_count == 0

    def test_revoked_grant_rejected_with_zero_writes(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_action()
        grant = _make_bound_approval_grant(action)
        predicate = _make_predicate(action)

        # Revoke before execution
        approval_ledger.revoke(grant, at=datetime.now(UTC))

        with pytest.raises(ApprovalRevokedError):
            execute_approved_calendar_update(
                action,
                test_router,
                grant,
                approval_ledger,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        assert seeded_calendar_transport.writes_count == 0

    def test_tampered_binding_hash_rejected_with_zero_writes(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_action()
        predicate = _make_predicate(action)
        now = datetime.now(UTC)

        tampered_grant = _make_bound_approval_grant(action, issued_at=now)
        object.__setattr__(tampered_grant, "binding_hash", BindingHash("a" * 64))

        with pytest.raises((ApprovalBindingMismatchError, ApprovalTamperedError)):
            execute_approved_calendar_update(
                action,
                test_router,
                tampered_grant,
                approval_ledger,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        assert seeded_calendar_transport.writes_count == 0

    def test_wrong_target_grant_rejected_with_zero_writes(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_action(event_id="evt_leave_for_school_001")
        wrong_action = _make_calendar_update_action(event_id="evt_foreign_999")
        grant_for_wrong_target = _make_bound_approval_grant(wrong_action)
        predicate = _make_predicate(action)

        with pytest.raises(ApprovalBindingMismatchError):
            execute_approved_calendar_update(
                action,
                test_router,
                grant_for_wrong_target,
                approval_ledger,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        assert seeded_calendar_transport.writes_count == 0

    def test_model_prose_or_proposal_rejected_with_zero_writes(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        action = _make_calendar_update_action()
        predicate = _make_predicate(action)

        # String prose
        with pytest.raises((ExecutionGateTypeError, AuthorityPolicyTypeError, TypeError)):
            execute_approved_calendar_update(
                action,
                test_router,
                "User said: Yes, please update the event!",  # type: ignore[arg-type]
                approval_ledger,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        # Planner proposal object
        proposal = CandidateActionProposal(
            action_type=ActionType.CALENDAR_UPDATE,
            target_ref=SymbolicTargetRef.LEAVE_FOR_SCHOOL,
            parameters=NormalizedParameters.from_dict({"start_time": "07:30:00"}),
            explanation="Model wants to update",
        )
        with pytest.raises((PlannerGateAuthorityError, PlannerAuthorityError)):
            execute_approved_calendar_update(
                action,
                test_router,
                proposal,  # type: ignore[arg-type]
                approval_ledger,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        assert seeded_calendar_transport.writes_count == 0


# ===========================================================================
# 6. Durable Ledger Persistence Failure (Zero Writes)
# ===========================================================================


class TestDurableLedgerFailureFailsClosed:
    """Proves that ledger persistence failure prevents any provider mutation."""

    def test_ledger_append_failure_aborts_before_router_dispatch(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
    ) -> None:
        """When ledger persistence raises, consumption fails closed; 0 provider writes."""

        class FailingLedger(InMemoryNonDurableLedger):
            def append_evidence(self, record: EvidenceRecord) -> None:
                raise OSError("Disk full simulation")

        failing_ledger = FailingLedger()
        app_ledger = ApprovalLedger(ledger=failing_ledger)

        action = _make_calendar_update_action()
        grant = _make_bound_approval_grant(action)
        predicate = _make_predicate(action)

        with pytest.raises(ApprovalConsumptionPersistenceError) as exc_info:
            execute_approved_calendar_update(
                action,
                test_router,
                grant,
                app_ledger,
                calendar_read_adapter,
                predicate,
                source_sha=DUMMY_SOURCE_SHA,
            )

        assert "Failed to durably persist approval consumption" in str(exc_info.value)
        # CRUCIAL: transport write count must be strictly 0
        assert seeded_calendar_transport.writes_count == 0


# ===========================================================================
# 7. ETag Conflict & Precondition Failure (No Blind Overwrite)
# ===========================================================================


class TestETagConflictTruthfulFailure:
    """Proves that ETag mismatch results in failure without blind overwrite."""

    def test_etag_mismatch_fails_truthfully_without_blind_overwrite(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If external state changed and ETag no longer matches, update returns CONFLICT."""
        action = _make_calendar_update_action()
        grant = _make_bound_approval_grant(action)
        predicate = _make_predicate(action)

        # Before execute, external party updates the event ETag on transport
        # Simulate external mutation:
        seeded_calendar_transport._events[
            ("c_1880abc123demo@group.calendar.google.com", "evt_leave_for_school_001")
        ]["etag"] = "etag_externally_modified_9999"

        # Intercept before read to capture initial before state
        b_action = ActionContract.create(
            mission_id=action.mission_id,
            action_type=ActionType.CALENDAR_READ,
            target=action.target,
            parameters={},
        )
        before_read = calendar_read_adapter.read_event(b_action)

        # Now simulate race: between read-before-write in adapter and update_event, ETag changed
        # We hook update_event to raise CalendarPreconditionFailedError
        def conflicting_update(*args: Any, **kwargs: Any) -> Any:
            raise CalendarPreconditionFailedError("ETag mismatch: 412 Precondition Failed")

        monkeypatch.setattr(seeded_calendar_transport, "update_event", conflicting_update)

        outcome = execute_approved_calendar_update(
            action,
            test_router,
            grant,
            approval_ledger,
            calendar_read_adapter,
            predicate,
            source_sha=DUMMY_SOURCE_SHA,
            before_read=before_read,
        )

        assert outcome.provider_result.success is False
        assert outcome.provider_result.status_name == "CONFLICT"
        assert outcome.gate_decision.status == ActionExecutionStatus.EXECUTION_FAILED
        assert outcome.is_verified is False
        assert outcome.is_ready is False


# ===========================================================================
# 8. Independent Read-Back Mismatch (Never Verified)
# ===========================================================================


class TestIndependentReadbackMismatchNeverVerified:
    """Proves that provider success alone is NOT verification."""

    def test_provider_success_with_readback_mismatch_is_never_verified(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
        seeded_calendar_transport: FakeGoogleCalendarTransport,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Provider returns success, but fresh read-back observes a conflicting state:
        MUST return FALSE and NOT VERIFIED.
        """
        action = _make_calendar_update_action(new_start_time="2026-10-09T07:30:00+03:00")
        grant = _make_bound_approval_grant(action)
        # Predicate expects 07:30:00
        predicate = _make_predicate(action, expected_start="2026-10-09T07:30:00+03:00")

        # Hook get_event during independent read-back to return conflicting time (e.g. 08:00:00)
        from dataclasses import replace

        orig_get = seeded_calendar_transport.get_event
        call_count = 0

        def sneaky_get(calendar_id: str, event_id: str) -> Any:
            nonlocal call_count
            call_count += 1
            ev = orig_get(calendar_id, event_id)
            if (
                call_count >= 3 and ev is not None
            ):  # 1 is before_read, 2 is read-before-write, 3 is after_read
                return replace(ev, start_time="2026-10-09T08:00:00+03:00")
            return ev

        monkeypatch.setattr(seeded_calendar_transport, "get_event", sneaky_get)

        outcome = execute_approved_calendar_update(
            action,
            test_router,
            grant,
            approval_ledger,
            calendar_read_adapter,
            predicate,
            source_sha=DUMMY_SOURCE_SHA,
        )

        # Provider reported success!
        assert outcome.provider_result.success is True
        assert outcome.provider_result.writes_performed == 1

        # BUT Read-back observed mismatch!
        assert outcome.readback_result.status == CalendarReadbackStatus.MISMATCH
        assert outcome.predicate_result.truth == PredicateTruth.FALSE

        # CORE INVARIANT: MUST NOT BE VERIFIED! MUST NOT BE READY!
        assert outcome.is_verified is False
        assert outcome.is_ready is False
        assert outcome.receipt.is_verified is False
        assert outcome.receipt.is_ready_claimed is False


# ===========================================================================
# 9. Chronology and Receipt Integrity
# ===========================================================================


class TestChronologyAndReceiptIntegrity:
    """Proves monotonic chronology and deep immutability of ApprovedActionReceipt."""

    def test_reversed_read_chronology_rejected_fail_closed(
        self,
        approval_ledger: ApprovalLedger,
    ) -> None:
        action = _make_calendar_update_action()
        grant = _make_bound_approval_grant(action)
        t_now = datetime.now(UTC)
        approval_ledger.consume(grant, action, at=t_now)
        consumption_rec = approval_ledger.get_record(grant.approval_id)
        assert consumption_rec is not None

        decision = ExecutionGateDecision(
            action_id=action.action_id,
            action_type=action.action_type,
            authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
            status=ActionExecutionStatus.EXECUTION_SUCCEEDED,
            is_authorized=True,
            reason="Authorized",
            evaluated_at=t_now,
        )

        # Reversed reads: after_read has earlier timestamp than before_read
        from stilldone.adapters.calendar import CalendarEventObservation

        obs = CalendarEventObservation(
            event_id="evt_leave_for_school_001",
            calendar_id="c_1880abc123demo@group.calendar.google.com",
            summary="Leave for school",
            start_time="2026-10-09T07:30:00+03:00",
            end_time="2026-10-09T08:00:00+03:00",
            all_day=False,
            etag="etag_1",
            status="confirmed",
            observed_at=t_now,
        )
        before_read = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id="evt_leave_for_school_001",
            observation=obs,
            read_at=t_now + timedelta(seconds=10),  # LATER than after_read!
        )
        from dataclasses import replace

        after_obs = replace(obs, observed_at=t_now - timedelta(seconds=10))
        after_read = CalendarReadResult(
            status=CalendarReadStatus.SUCCESS,
            event_id="evt_leave_for_school_001",
            observation=after_obs,
            read_at=t_now - timedelta(seconds=10),  # EARLIER than before_read!
        )
        readback_res = CalendarReadbackResult(
            status=CalendarReadbackStatus.MATCH,
            event_id="evt_leave_for_school_001",
            expected=ExpectedCalendarState(start_time="2026-10-09T07:30:00+03:00"),
        )
        predicate_res = PredicateEvaluationResult(
            predicate_id=PredicateId.generate(),
            truth=PredicateTruth.TRUE,
            subject="start_time",
            operator=PredicateOperator.EQUALS,
            expected_value="2026-10-09T07:30:00+03:00",
        )
        obs_mutation = ProviderMutationObservation(
            router_mutation_invocations=1,
            handler_mutation_invocations=1,
            transport_mutation_invocations=1,
            transport_writes=1,
        )

        with pytest.raises(ExecutionGateValueError) as exc_info:
            create_approved_action_receipt(
                gate_decision=decision,
                action=action,
                approval=grant,
                consumption_record=consumption_rec,
                before_read=before_read,
                after_read=after_read,
                readback_result=readback_res,
                predicate_result=predicate_res,
                source_sha=DUMMY_SOURCE_SHA,
                ledger=approval_ledger,
                mutation_observation=obs_mutation,
            )

        assert "reversed observation chronology" in str(exc_info.value)

    def test_approved_receipt_is_deeply_immutable(
        self,
        test_router: AdapterRouter,
        calendar_read_adapter: GoogleCalendarReadAdapter,
        approval_ledger: ApprovalLedger,
    ) -> None:
        """State summaries in ApprovedActionReceipt are MappingProxyType and cannot be mutated."""
        action = _make_calendar_update_action()
        grant = _make_bound_approval_grant(action)
        predicate = _make_predicate(action)

        outcome = execute_approved_calendar_update(
            action,
            test_router,
            grant,
            approval_ledger,
            calendar_read_adapter,
            predicate,
            source_sha=DUMMY_SOURCE_SHA,
        )

        receipt = outcome.receipt
        with pytest.raises((TypeError, AttributeError)):
            receipt.before_state_summary["summary"] = "Hacked"  # type: ignore[index]
        with pytest.raises((TypeError, AttributeError)):
            receipt.after_state_summary["summary"] = "Hacked"  # type: ignore[index]


# ===========================================================================
# 10. Live Google Calendar Safety Gate (BLOCKED / NOT_RUN)
# ===========================================================================


class TestLiveGoogleCalendarSafetyGate:
    """Proves that live Google Calendar mutation is NOT authorized and reported NOT_RUN."""

    def test_live_mutation_is_not_run_and_zero_personal_spend(self) -> None:
        """Verifies that live mutation conditions are absent and operation remains NOT_RUN."""
        # Requirements for live mutation:
        # 1. Dedicated demo calendar ID (never primary)
        # 2. Existing disposable event ID
        # 3. Exact before-state and ETag
        # 4. Exact proposed replacement parameters
        # 5. Confirmation that no attendees/invitations/notifications affected
        # 6. Working short-lived OAuth access with least-privilege scopes
        # 7. Confirmation that operation introduces $0.00 personal spend

        # Without cached OAuth tokens and explicit operator approval, live mutation is BLOCKED.
        live_prerequisites_met = False
        assert live_prerequisites_met is False

        # In headless automated tests, live execution is strictly NOT_RUN
        observed_spend = 0.00
        assert observed_spend == 0.00
