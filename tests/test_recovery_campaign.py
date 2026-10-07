"""Adversarial and Injected Failure Campaign for Phase P-10.06.

Proves the recovery engine under realistic injected failure orderings:
- TASK_CREATE: timeout-after-write vs. timeout-before-effect.
- Ambiguous/inconclusive read-back fail-closed behavior.
- Duplicate detection and duplicate evidence truth.
- CALENDAR_UPDATE: timeout-after-write and no redundant mutation.
- Process crash / restart recovery continuity using durable mission ledger.
- Attempt ceiling persistence across restarts.
- Authority/security and programming errors never retried.
- Model / planner pollution rejection and zero authority.
- Privacy minimization: no raw provider payloads leaked in evidence.

Core invariant under test:
LOST RESPONSE != PERMISSION TO CREATE A SECOND EFFECT.

Uses controlled injected test doubles ONLY (Zero network calls, $0.00 personal spend).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from stilldone.adapters.calendar import (
    CalendarTransportError,
    CalendarTransportEvent,
    CalendarUpdateStatus,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
    GoogleCalendarUpdateAdapter,
)
from stilldone.adapters.tasks import (
    FakeGoogleTasksTransport,
    GoogleTasksCreateAdapter,
    GoogleTasksDuplicateDetector,
    TaskCreateStatus,
    TaskTransportError,
    TaskTransportItem,
)
from stilldone.demo_isolation import DemoResourceScope
from stilldone.domain.action import (
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import ApprovalGrant, AuthorityClass
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.mission import MissionContract, MissionId
from stilldone.ledger import ActionRecord, DurableFileLedger, MissionRecord
from stilldone.planning.contracts import CandidateActionProposal
from stilldone.recovery.continuity import (
    reconstruct_action_recovery_state,
    record_duplicate_determination,
    record_execution_attempt,
)
from stilldone.recovery.duplicate import (
    DuplicateDeterminationStatus,
    GoogleCalendarEffectDetectorAdapter,
    GoogleTasksDuplicateDetectorAdapter,
    derive_intended_mutation_identity,
)
from stilldone.recovery.idempotency import PlannerRecoveryAuthorityError
from stilldone.recovery.orchestrator import (
    RecoveryActionType,
    evaluate_post_execution_recovery,
    evaluate_readback_recovery,
)
from stilldone.recovery.retry import (
    RetryClassification,
    RetryPolicy,
    classify_error,
)

# ---------------------------------------------------------------------------
# Scope & Test Fixtures
# ---------------------------------------------------------------------------

DEMO_SCOPE = DemoResourceScope(
    calendar_id="demo_cal@example.com",
    task_list_id="demo_tasks_list_123",
)

TASKS_TARGET = TargetIdentity(
    system="google_tasks",
    resource_kind=ResourceKind.TASK_LIST,
    resource_id=DEMO_SCOPE.task_list_id,
    parent_id=None,
)

CAL_TARGET = TargetIdentity(
    system="google_calendar",
    resource_kind=ResourceKind.CALENDAR_EVENT,
    resource_id="event_briefing_1",
    parent_id=DEMO_SCOPE.calendar_id,
)


def _make_task_create_action(
    title: str = "Pack rain gear", due: str | None = "2026-10-10"
) -> ActionContract:
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.TASK_CREATE,
        target=TASKS_TARGET,
        parameters={"title": title, "due": due},
    )


def _make_calendar_update_action(
    summary: str = "Family Briefing", start: str = "2026-10-08T07:00:00Z"
) -> ActionContract:
    return ActionContract.create(
        mission_id=MissionId.generate(),
        action_type=ActionType.CALENDAR_UPDATE,
        target=CAL_TARGET,
        parameters={"summary": summary, "start_time": start},
    )


def _make_approval_grant(action: ActionContract) -> ApprovalGrant:
    now = datetime.now(UTC)
    return ApprovalGrant(
        action=action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=10),
    )


def _register_action_in_ledger(ledger: DurableFileLedger, action: ActionContract) -> None:
    mission = MissionContract.create(
        "Testing crash and restart recovery",
        mission_id=action.mission_id,
    )
    ledger.append_mission(
        MissionRecord(
            mission_id=mission.mission_id,
            contract=mission,
            state=MissionState.EXECUTING,
            created_at=mission.created_at,
            updated_at=mission.created_at,
        )
    )
    ledger.append_action(
        ActionRecord(
            action_id=action.action_id,
            mission_id=mission.mission_id,
            action=action,
            approval_id=None,
            created_at=mission.created_at,
        )
    )


# ---------------------------------------------------------------------------
# Injected Test Doubles
# ---------------------------------------------------------------------------


class FaultyGoogleTasksTransport(FakeGoogleTasksTransport):
    """Injected test double capable of precise failure-mode simulations."""

    def __init__(self) -> None:
        super().__init__()
        self.inject_timeout_after_write: bool = False
        self.inject_timeout_before_write: bool = False
        self.inject_list_error: bool = False
        self.last_failure_reason: str | None = None

    def insert_task(self, task_list_id: str, body: dict[str, Any]) -> TaskTransportItem:
        if self.inject_timeout_before_write:
            self.last_failure_reason = "timeout_before_write"
            raise TimeoutError("Connection timeout connecting to tasks.googleapis.com")

        # Write effect in store
        item = super().insert_task(task_list_id, body)

        if self.inject_timeout_after_write:
            self.last_failure_reason = "timeout_after_write"
            raise TimeoutError("Read timeout waiting for tasks.googleapis.com response")

        return item

    def list_tasks(
        self,
        task_list_id: str,
        show_completed: bool = False,
        show_deleted: bool = False,
        show_hidden: bool = False,
        show_assigned: bool = False,
        max_results: int = 100,
        page_token: str | None = None,
    ) -> tuple[list[TaskTransportItem], str | None]:
        if self.inject_list_error:
            raise TaskTransportError(
                "Internal server error from tasks.googleapis.com (status 500)",
                status_code=500,
            )
        return super().list_tasks(
            task_list_id,
            show_completed=show_completed,
            show_deleted=show_deleted,
            show_hidden=show_hidden,
            show_assigned=show_assigned,
            max_results=max_results,
            page_token=page_token,
        )


class FaultyGoogleCalendarTransport(FakeGoogleCalendarTransport):
    """Injected test double for Calendar failure simulations."""

    def __init__(self) -> None:
        super().__init__()
        self.inject_timeout_after_write: bool = False
        self.inject_timeout_before_write: bool = False
        self.inject_read_error: bool = False

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        payload: dict[str, Any],
        if_match: str,
        send_updates: str = "none",
    ) -> CalendarTransportEvent:
        if self.inject_timeout_before_write:
            raise TimeoutError("Connection timeout connecting to calendar.googleapis.com")

        # Apply update
        event = super().update_event(
            calendar_id, event_id, payload, if_match=if_match, send_updates=send_updates
        )

        if self.inject_timeout_after_write:
            raise TimeoutError("Read timeout reading response from calendar.googleapis.com")

        return event

    def get_event(self, calendar_id: str, event_id: str) -> CalendarTransportEvent | None:
        if self.inject_read_error:
            raise CalendarTransportError(
                "Internal server error from calendar.googleapis.com (status 500)",
                status_code=500,
            )
        return super().get_event(calendar_id, event_id)


# ===========================================================================
# 13 Mandatory Injected Campaign Scenarios
# ===========================================================================


class TestP10CampaignScenarios:
    """The 13 mandatory recovery campaign scenarios defined in Phase P-10.06."""

    def test_scenario_01_task_create_lost_response_no_blind_second_create(self) -> None:
        """Scenario 1: TASK_CREATE write succeeds, response lost / timeout raised.

        Recovery must NOT blindly issue a second create.
        """
        transport = FaultyGoogleTasksTransport()
        transport.inject_timeout_after_write = True
        adapter = GoogleTasksCreateAdapter(scope=DEMO_SCOPE, transport=transport)
        action = _make_task_create_action(title="Pack rain gear")

        # Attempt 1: provider performs write, then raises timeout
        result = adapter.create_task(action)
        assert result.status == TaskCreateStatus.PROVIDER_ERROR
        assert transport.writes_count == 1  # Effect was written

        # Recovery evaluation MUST require independent verification, NOT blindly retry!
        decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=result.error_message or "Read timeout (status 504)",
        )
        assert decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION

        # CRITICAL PROOF: write count remains exactly 1, no second create issued!
        assert transport.writes_count == 1

    def test_scenario_02_task_create_timeout_after_write_read_finds_effect_write_count_one(
        self,
    ) -> None:
        """Scenario 2: TASK_CREATE timeout-after-write; read-before-retry finds intended effect.

        Execution count remains exactly one.
        """
        transport = FaultyGoogleTasksTransport()
        transport.inject_timeout_after_write = True
        adapter = GoogleTasksCreateAdapter(scope=DEMO_SCOPE, transport=transport)
        action = _make_task_create_action(title="Pack rain gear")

        # Attempt 1: write occurs, response lost
        result = adapter.create_task(action)
        assert result.status == TaskCreateStatus.PROVIDER_ERROR
        assert transport.writes_count == 1

        post_decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=result.error_message or "Read timeout (status 504)",
        )
        assert post_decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION

        # Read-before-retry duplicate inspection
        detector_core = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        detector = GoogleTasksDuplicateDetectorAdapter(detector=detector_core)

        evidence = detector.detect(action)
        assert evidence.status == DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS
        assert evidence.match_count == 1

        # Evaluate read-back decision
        readback_decision = evaluate_readback_recovery(
            action=action,
            readback_result=evidence.to_readback_result(),
            attempt_number=1,
        )
        assert readback_decision.action_type == RecoveryActionType.EFFECT_ALREADY_EXISTS

        # Further mutation prohibited; write count remains exactly 1!
        assert transport.writes_count == 1

    def test_scenario_03_task_create_timeout_before_effect_read_absent_retry_executes_once(
        self,
    ) -> None:
        """Scenario 3: TASK_CREATE timeout before effect; read proves effect absent.

        Bounded retry may execute once if canonical strategy permits.
        """
        transport = FaultyGoogleTasksTransport()
        transport.inject_timeout_before_write = True
        adapter = GoogleTasksCreateAdapter(scope=DEMO_SCOPE, transport=transport)
        action = _make_task_create_action(title="Pack rain gear")

        # Attempt 1: connection fails BEFORE writing
        result1 = adapter.create_task(action)
        assert result1.status == TaskCreateStatus.PROVIDER_ERROR
        assert transport.writes_count == 0  # No effect was written

        post_decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=result1.error_message or "Connection timeout (status 504)",
        )
        assert post_decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION

        # Read-before-retry inspection
        detector_core = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        detector = GoogleTasksDuplicateDetectorAdapter(detector=detector_core)

        evidence = detector.detect(action)
        assert evidence.status == DuplicateDeterminationStatus.EFFECT_ABSENT
        assert evidence.match_count == 0

        # Readback decision permits bounded retry
        readback_decision = evaluate_readback_recovery(
            action=action,
            readback_result=evidence.to_readback_result(),
            attempt_number=1,
        )
        assert readback_decision.action_type == RecoveryActionType.RETRY
        assert readback_decision.attempt_number == 1

        # Attempt 2: clear transient connection failure and execute retry
        transport.inject_timeout_before_write = False
        result2 = adapter.create_task(action)
        assert result2.status == TaskCreateStatus.CREATED
        assert result2.writes_performed == 1

        # CRITICAL PROOF: exactly one write was performed total!
        assert transport.writes_count == 1

    def test_scenario_04_inconclusive_readback_fails_closed_no_blind_retry(self) -> None:
        """Scenario 4: Ambiguous / inconclusive read-back; no blind duplicate-risk retry."""
        transport = FaultyGoogleTasksTransport()
        transport.inject_timeout_after_write = True
        transport.inject_list_error = True  # Read-back will fail with 500 error
        adapter = GoogleTasksCreateAdapter(scope=DEMO_SCOPE, transport=transport)
        action = _make_task_create_action(title="Pack rain gear")

        # Attempt 1: write occurs, timeout raised
        result = adapter.create_task(action)
        assert result.status == TaskCreateStatus.PROVIDER_ERROR
        assert transport.writes_count == 1

        # Read-before-retry fails due to provider list error -> INCONCLUSIVE
        detector_core = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        detector = GoogleTasksDuplicateDetectorAdapter(detector=detector_core)

        evidence = detector.detect(action)
        assert evidence.status == DuplicateDeterminationStatus.DETERMINATION_INCONCLUSIVE

        # Recovery evaluation MUST fail closed (DO_NOT_RETRY)
        readback_decision = evaluate_readback_recovery(
            action=action,
            readback_result=evidence.to_readback_result(),
            attempt_number=1,
        )
        assert readback_decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert "inconclusive" in readback_decision.reason.lower()

        # No further writes allowed; write count remains 1
        assert transport.writes_count == 1

    def test_scenario_05_duplicate_already_exists_truthfully_recorded_no_second_mutation(
        self,
    ) -> None:
        """Scenario 5: Duplicate already exists; duplicate recorded truthfully; no mutation."""
        transport = FaultyGoogleTasksTransport()
        # Seed 2 identical tasks already in external system
        transport.seed_task(DEMO_SCOPE.task_list_id, "task_1", "Pack rain gear", due="2026-10-10")
        transport.seed_task(DEMO_SCOPE.task_list_id, "task_2", "Pack rain gear", due="2026-10-10")

        action = _make_task_create_action(title="Pack rain gear", due="2026-10-10")

        # Duplicate detector observes 2 matches
        detector_core = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        detector = GoogleTasksDuplicateDetectorAdapter(detector=detector_core)

        evidence = detector.detect(action)
        assert evidence.status == DuplicateDeterminationStatus.DUPLICATE_DETECTED
        assert evidence.match_count == 2

        # Recovery halts with DUPLICATE_PREVENTED
        decision = evaluate_readback_recovery(
            action=action,
            readback_result=evidence.to_readback_result(),
            attempt_number=1,
        )
        assert decision.action_type == RecoveryActionType.DUPLICATE_PREVENTED
        assert "Duplicate effect detected" in decision.reason

        # CRITICAL PROOF: zero writes were performed!
        assert transport.writes_count == 0

    def test_scenario_06_calendar_update_timeout_after_write_verification_proves_no_redundant_write(
        self,
    ) -> None:
        """Scenario 6: CALENDAR_UPDATE timeout-after-write; state verified; no rewrite."""
        transport = FaultyGoogleCalendarTransport()
        # Seed event with old state
        transport.seed_event(
            calendar_id=DEMO_SCOPE.calendar_id,
            event_id="event_briefing_1",
            summary="Old Meeting",
            start_time="2026-10-08T06:00:00Z",
            end_time="2026-10-08T06:30:00Z",
        )
        action = _make_calendar_update_action(
            summary="Family Briefing", start="2026-10-08T07:00:00Z"
        )
        approval = _make_approval_grant(action)

        # Inject timeout-after-write on update
        transport.inject_timeout_after_write = True
        update_adapter = GoogleCalendarUpdateAdapter(scope=DEMO_SCOPE, transport=transport)

        result = update_adapter.update_event(action, approval=approval)
        assert result.status == CalendarUpdateStatus.PROVIDER_ERROR
        assert transport.writes_count == 1  # Event was updated in transport before timeout

        # Recovery evaluation requires verification
        post_decision = evaluate_post_execution_recovery(
            action=action,
            attempt_number=1,
            error=result.error_message or "Read timeout (status 504)",
        )
        assert post_decision.action_type == RecoveryActionType.REQUIRES_VERIFICATION

        # Read-back effect detector verifies updated properties
        read_adapter = GoogleCalendarReadAdapter(scope=DEMO_SCOPE, transport=transport)
        detector = GoogleCalendarEffectDetectorAdapter(read_adapter=read_adapter)
        evidence = detector.detect(action)
        assert evidence.status == DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS
        assert evidence.match_count == 1

        # Recovery halts with EFFECT_ALREADY_EXISTS
        readback_decision = evaluate_readback_recovery(
            action=action,
            readback_result=evidence.to_readback_result(),
            attempt_number=1,
        )
        assert readback_decision.action_type == RecoveryActionType.EFFECT_ALREADY_EXISTS

        # CRITICAL PROOF: No redundant second update mutation is executed!
        assert transport.writes_count == 1

    def test_scenario_07_crash_ambiguous_restart_preserves_attempts_and_identity(
        self, tmp_path: Any
    ) -> None:
        """Scenario 7: Process crash after ambiguous mutation outcome before recovery completion.

        Restart from durable recovery state preserves attempt count and mutation identity;
        no duplicate effect is created.
        """
        log_file = tmp_path / "mission_recovery_s7.jsonl"
        ledger1 = DurableFileLedger(log_file)
        transport = FaultyGoogleTasksTransport()
        transport.inject_timeout_after_write = True
        adapter = GoogleTasksCreateAdapter(scope=DEMO_SCOPE, transport=transport)
        action = _make_task_create_action(title="Pack rain gear")

        # Register mission and action in durable ledger
        _register_action_in_ledger(ledger1, action)

        # Attempt 1: write occurs, timeout raised
        result = adapter.create_task(action)
        assert result.status == TaskCreateStatus.PROVIDER_ERROR
        assert transport.writes_count == 1

        # Record in-flight attempt in durable ledger
        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error=result.error_message or "Read timeout (status 504)",
        )
        pre_crash_identity = derive_intended_mutation_identity(action)

        # PROCESS CRASH: drop in-memory ledger
        del ledger1

        # PROCESS RESTART: reload from durable file
        ledger2 = DurableFileLedger(log_file)
        recovery_state = reconstruct_action_recovery_state(action=action, ledger=ledger2)

        # Invariant checks: attempt count and mutation identity survive restart
        assert recovery_state.prior_attempt_count == 1
        assert recovery_state.intended_mutation == pre_crash_identity
        assert (
            recovery_state.resumption_decision.action_type
            == RecoveryActionType.REQUIRES_VERIFICATION
        )

        # Recovery resumes: read-before-retry discovers intended effect
        detector_core = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        detector = GoogleTasksDuplicateDetectorAdapter(detector=detector_core)
        evidence = detector.detect(action)
        assert evidence.status == DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS

        record_duplicate_determination(ledger=ledger2, evidence=evidence)

        final_decision = evaluate_readback_recovery(
            action=action,
            readback_result=evidence.to_readback_result(),
            attempt_number=recovery_state.prior_attempt_count,
        )
        assert final_decision.action_type == RecoveryActionType.EFFECT_ALREADY_EXISTS

        # CRITICAL PROOF: write count remains exactly 1 across crash and recovery!
        assert transport.writes_count == 1

    def test_scenario_08_crash_after_effect_before_ack_readback_finds_effect_no_second_write(
        self, tmp_path: Any
    ) -> None:
        """Scenario 8: Crash after write before ack; readback finds effect; no second write."""
        log_file = tmp_path / "mission_recovery_s8.jsonl"
        ledger1 = DurableFileLedger(log_file)
        transport = FaultyGoogleTasksTransport()
        action = _make_task_create_action(title="Pack rain gear")

        # Register mission and action in durable ledger
        _register_action_in_ledger(ledger1, action)

        # Effect was written in provider
        transport.insert_task(
            DEMO_SCOPE.task_list_id, {"title": "Pack rain gear", "due": "2026-10-10T00:00:00.000Z"}
        )
        assert transport.writes_count == 1

        # Crash happens BEFORE client can record clean success; only in-flight attempt exists
        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error="Read timeout (status 504)",
        )

        # PROCESS CRASH
        del ledger1

        # PROCESS RESTART
        ledger2 = DurableFileLedger(log_file)
        recovery_state = reconstruct_action_recovery_state(action=action, ledger=ledger2)
        assert recovery_state.prior_attempt_count == 1
        assert (
            recovery_state.resumption_decision.action_type
            == RecoveryActionType.REQUIRES_VERIFICATION
        )

        # Read-back discovers task in provider
        detector_core = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        detector = GoogleTasksDuplicateDetectorAdapter(detector=detector_core)
        evidence = detector.detect(action)
        assert evidence.status == DuplicateDeterminationStatus.INTENDED_EFFECT_EXISTS

        # Prohibits second write
        decision = evaluate_readback_recovery(
            action=action,
            readback_result=evidence.to_readback_result(),
            attempt_number=1,
        )
        assert decision.action_type == RecoveryActionType.EFFECT_ALREADY_EXISTS

        # CRITICAL PROOF: write count remains exactly 1!
        assert transport.writes_count == 1

    def test_scenario_09_crash_before_effect_restart_resumes_under_bounded_retry(
        self, tmp_path: Any
    ) -> None:
        """Scenario 9: Crash before effect; resume executes only under canonical retry rules."""
        log_file = tmp_path / "mission_recovery_s9.jsonl"
        ledger1 = DurableFileLedger(log_file)
        transport = FaultyGoogleTasksTransport()
        action = _make_task_create_action(title="Pack rain gear")

        # Register mission and action in durable ledger
        _register_action_in_ledger(ledger1, action)

        # Crash before provider received write: write count is 0
        record_execution_attempt(
            ledger=ledger1,
            action=action,
            attempt_number=1,
            error="Connection timeout (status 504)",
        )
        assert transport.writes_count == 0

        # CRASH & RESTART
        del ledger1
        ledger2 = DurableFileLedger(log_file)
        recovery_state = reconstruct_action_recovery_state(action=action, ledger=ledger2)
        assert recovery_state.prior_attempt_count == 1

        # Read-before-retry proves effect is absent
        detector_core = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        detector = GoogleTasksDuplicateDetectorAdapter(detector=detector_core)
        evidence = detector.detect(action)
        assert evidence.status == DuplicateDeterminationStatus.EFFECT_ABSENT

        # Decision permits retry under bounded ceiling
        decision = evaluate_readback_recovery(
            action=action,
            readback_result=evidence.to_readback_result(),
            attempt_number=1,
        )
        assert decision.action_type == RecoveryActionType.RETRY

        # Resume executes attempt 2
        adapter = GoogleTasksCreateAdapter(scope=DEMO_SCOPE, transport=transport)
        result2 = adapter.create_task(action)
        assert result2.status == TaskCreateStatus.CREATED

        # Record clean completion
        record_execution_attempt(
            ledger=ledger2,
            action=action,
            attempt_number=2,
            error=None,
        )

        # Write count became 1 (from 0 + 1)
        assert transport.writes_count == 1

    def test_scenario_10_attempt_ceiling_survives_restart_cannot_reset_retry_budget(
        self, tmp_path: Any
    ) -> None:
        """Scenario 10: Attempt ceiling survives restart; restart cannot reset retry budget."""
        log_file = tmp_path / "mission_recovery_s10.jsonl"
        ledger1 = DurableFileLedger(log_file)
        action = _make_task_create_action(title="Pack rain gear")
        policy = RetryPolicy(max_attempts=3)

        # Register mission and action in durable ledger
        _register_action_in_ledger(ledger1, action)

        # Record 3 exhausted attempts in durable ledger
        for i in range(1, 4):
            record_execution_attempt(
                ledger=ledger1,
                action=action,
                attempt_number=i,
                error=TimeoutError("Transient timeout"),
            )

        # CRASH & RESTART
        del ledger1
        ledger2 = DurableFileLedger(log_file)
        recovery_state = reconstruct_action_recovery_state(
            action=action, ledger=ledger2, policy=policy
        )

        # Budget is strictly 0 and cannot be reset
        assert recovery_state.prior_attempt_count == 3
        assert recovery_state.remaining_attempt_budget == 0
        assert recovery_state.resumption_decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert "Attempt ceiling reached" in recovery_state.resumption_decision.reason

    def test_scenario_11_authority_security_programming_failure_never_retryable(self) -> None:
        """Scenario 11: Security or programming failure never converted to retryable behavior."""
        action = _make_task_create_action(title="Pack rain gear")

        # 1. Authentication / Authorization failure (HTTP 401/403)
        auth_err = TaskTransportError("Authentication failed (status 401)", status_code=401)
        classification = classify_error(auth_err)
        assert classification == RetryClassification.AUTHORITY_SECURITY_FAILURE

        decision = evaluate_post_execution_recovery(action=action, attempt_number=1, error=auth_err)
        assert decision.action_type == RecoveryActionType.DO_NOT_RETRY
        assert decision.delay_seconds == 0.0

        # 2. Client / policy / malformed parameters failure (HTTP 400)
        client_err = ValueError("Invalid field parameters")
        classification = classify_error(client_err)
        assert classification == RetryClassification.CONTRACT_PROGRAMMING_FAILURE

        decision2 = evaluate_post_execution_recovery(
            action=action, attempt_number=1, error=client_err
        )
        assert decision2.action_type == RecoveryActionType.DO_NOT_RETRY

        # 3. Not found on non-existent resource (HTTP 404)
        not_found_err = TaskTransportError("Resource not found (status 404)", status_code=404)
        classification3 = classify_error(not_found_err)
        assert classification3 == RetryClassification.NON_RETRYABLE_PERMANENT
        decision3 = evaluate_post_execution_recovery(
            action=action, attempt_number=1, error=not_found_err
        )
        assert decision3.action_type == RecoveryActionType.DO_NOT_RETRY

    def test_scenario_12_planner_model_objects_cannot_authorize_retry_or_suppress_duplicates(
        self,
    ) -> None:
        """Scenario 12: Planner cannot authorize retry, suppress duplicates, or declare success."""
        # 1. Planner proposal passed as action to evaluate_post_execution_recovery
        proposal = CandidateActionProposal.create(
            action_type=ActionType.TASK_CREATE,
            target_ref="demo_task_list",
            parameters={"title": "Pack rain gear"},
        )
        with pytest.raises(PlannerRecoveryAuthorityError, match="ZERO recovery authority"):
            evaluate_post_execution_recovery(
                action=proposal,  # type: ignore[arg-type]
                attempt_number=1,
                error="Some error",
            )

        # 2. Planner proposal passed as action to evaluate_readback_recovery
        with pytest.raises(PlannerRecoveryAuthorityError, match="ZERO recovery authority"):
            evaluate_readback_recovery(
                action=proposal,  # type: ignore[arg-type]
                readback_result=MagicMock(),
                attempt_number=1,
            )

        # 3. Model prose cannot override duplicate determination
        transport = FaultyGoogleTasksTransport()
        transport.seed_task(DEMO_SCOPE.task_list_id, "task_1", "Pack rain gear", due="2026-10-10")
        transport.seed_task(DEMO_SCOPE.task_list_id, "task_2", "Pack rain gear", due="2026-10-10")

        action = _make_task_create_action(title="Pack rain gear")
        detector_core = GoogleTasksDuplicateDetector(scope=DEMO_SCOPE, transport=transport)
        detector = GoogleTasksDuplicateDetectorAdapter(detector=detector_core)

        # Even if a hypothetical model output says "Success: task created and no duplicates exist"
        evidence = detector.detect(action)
        assert evidence.status == DuplicateDeterminationStatus.DUPLICATE_DETECTED

        decision = evaluate_readback_recovery(
            action=action,
            readback_result=evidence.to_readback_result(),
            attempt_number=1,
        )
        # Deterministic evidence overrides any prose claim
        assert decision.action_type == RecoveryActionType.DUPLICATE_PREVENTED

    def test_scenario_13_privacy_recovery_evidence_does_not_leak_raw_provider_data(self) -> None:
        """Scenario 13: Privacy: recovery evidence does not leak unrelated raw provider data."""
        action = _make_task_create_action(title="Private Medical Appointment")

        detector_core = GoogleTasksDuplicateDetector(
            scope=DEMO_SCOPE, transport=FakeGoogleTasksTransport()
        )
        evidence = GoogleTasksDuplicateDetectorAdapter(detector=detector_core).detect(action)

        payload = evidence.to_canonical_payload()

        # Deterministic, bounded fields only
        assert "action_id" in payload
        assert "mutation_id" in payload
        assert "status" in payload
        assert "match_count" in payload

        # Zero raw provider headers, tokens, or unparsed JSON
        assert "Authorization" not in payload
        assert "Bearer" not in payload
        assert "raw_response" not in payload
        assert "headers" not in payload
        assert "cookies" not in payload

        # String representation does not leak internal sensitive secrets
        rep = repr(evidence)
        assert "Bearer" not in rep
        assert "OAuth" not in rep
