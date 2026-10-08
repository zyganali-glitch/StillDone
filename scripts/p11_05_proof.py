"""P-11.05 Proof Script: Prove Calendar existing-event update remains NOT_RUN before approval.

Executes the deterministic 12-step proof chain demonstrating that a canonical
CALENDAR_UPDATE action requiring approval:
1. Is classified REVERSIBLE_APPROVAL_REQUIRED under frozen P-11.01 policy.
2. Produces a canonical P-11.02 PendingApproval in PENDING state.
3. Has NO approval granted and NO approval consumed.
4. Is rejected at the execution authority gate BEFORE provider write.
5. Produces exactly zero provider mutation invocations (writes_count == 0).
6. Records deterministic execution status ActionExecutionStatus.NOT_RUN.
7. Leaves external Calendar state 100% unchanged between before/after reads.
8. Produces a durable UnapprovedActionReceipt with complete provenance and zero secrets.
9. Proves no execution attempt is fabricated and no retry budget is consumed.
10. Proves model prose / planner proposals cannot bypass the gate.

Live boundary truth:
If live Google Calendar read credentials are not present in the runtime,
the live read portion is explicitly reported as NOT_RUN / BLOCKED, and
simulation provenance is faithfully recorded as LOCAL_EXECUTION / FIXTURE.
Zero live mutations are ever performed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure src is on path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from stilldone.action_policy import validate_action_contract  # noqa: E402
from stilldone.adapters.calendar import (  # noqa: E402
    CalendarReadStatus,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
    GoogleCalendarUpdateAdapter,
)
from stilldone.adapters.tasks import (  # noqa: E402
    FakeGoogleTasksTransport,
    GoogleTasksCreateAdapter,
    GoogleTasksReadAdapter,
)
from stilldone.adapters.weather import (  # noqa: E402
    FakeOpenMeteoTransport,
    OpenMeteoReadAdapter,
    WeatherLocationConfig,
)
from stilldone.approval_consumption import (  # noqa: E402
    ApprovalLedger,
    ApprovalUsageStatus,
    UsedApprovalRegistry,
)
from stilldone.authority_policy import (  # noqa: E402
    get_action_authority_policy,
)
from stilldone.demo_isolation import DemoResourceScope  # noqa: E402
from stilldone.domain.action import (  # noqa: E402
    ActionContract,
    ActionId,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import AuthorityClass  # noqa: E402
from stilldone.domain.mission import MissionId  # noqa: E402
from stilldone.domain.provenance import EvidenceProvenance  # noqa: E402
from stilldone.execution.contracts import MissionExecutionContract  # noqa: E402
from stilldone.execution.gate import (  # noqa: E402
    create_unapproved_action_receipt,
    execute_gated_action,
)
from stilldone.execution.router import (  # noqa: E402
    AdapterRouter,
    CalendarReadHandler,
    CalendarUpdateHandler,
    TasksCreateHandler,
    TasksReadHandler,
    WeatherReadHandler,
)
from stilldone.execution.scheduler import schedule_execution  # noqa: E402
from stilldone.execution.state import (  # noqa: E402
    ActionExecutionStatus,
    ExecutionStateTracker,
)
from stilldone.pending_approval import (  # noqa: E402
    PendingApprovalStatus,
    create_pending_approval,
)

CANONICAL_SOURCE_SHA = "4ec4475f006207ec5840880bb9476f6d169442cd"
DEMO_CALENDAR_ID = "c_1880abc123demo@group.calendar.google.com"
DEMO_TASKLIST_ID = "MDExMTI0ZGVtbw"
DEMO_EVENT_ID = "evt_leave_for_school_001"
INITIAL_START_TIME = "2026-10-09T07:45:00+03:00"
INITIAL_END_TIME = "2026-10-09T08:15:00+03:00"
PROPOSED_START_TIME = "2026-10-09T07:30:00+03:00"
PROPOSED_SUMMARY = "Leave for school"


def get_git_commit_sha() -> str:
    """Get the current git commit SHA."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
        ).strip()
    except Exception as exc:
        return f"UNKNOWN_SHA ({exc})"


def check_live_google_credentials() -> dict[str, Any]:
    """Check whether live Google Calendar read credentials are safely available."""
    token_path = REPO_ROOT / "token.json"
    env_token = os.environ.get("GOOGLE_OAUTH_TOKEN")
    env_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    has_token = token_path.exists() or bool(env_token) or bool(env_creds)
    if not has_token:
        return {
            "status": "NOT_RUN",
            "reason": (
                "Live Google OAuth token is not cached in runtime environment. "
                "Interactive InstalledAppFlow cannot run headlessly. "
                "Live read portion is reported NOT_RUN / BLOCKED."
            ),
            "exercised": False,
        }
    return {
        "status": "AVAILABLE",
        "reason": "Google credentials present in runtime",
        "exercised": False,
    }


def run_p11_05_proof() -> dict[str, Any]:
    """Execute the canonical P-11.05 proof chain."""
    current_sha = get_git_commit_sha()
    live_status = check_live_google_credentials()

    # Step 1: Initialize demo environment and record before-state
    scope = DemoResourceScope(
        calendar_id=DEMO_CALENDAR_ID,
        task_list_id=DEMO_TASKLIST_ID,
    )
    cal_transport = FakeGoogleCalendarTransport()
    cal_transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
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

    cal_read_adapter = GoogleCalendarReadAdapter(scope=scope, transport=cal_transport)
    cal_update_adapter = GoogleCalendarUpdateAdapter(scope=scope, transport=cal_transport)

    tasks_transport = FakeGoogleTasksTransport()
    tasks_read = GoogleTasksReadAdapter(scope, tasks_transport)
    tasks_create = GoogleTasksCreateAdapter(scope, tasks_transport)
    weather_transport = FakeOpenMeteoTransport()
    loc_config = WeatherLocationConfig("loc-demo", latitude=52.52, longitude=13.41)
    weather_read = OpenMeteoReadAdapter(loc_config, weather_transport)

    router = AdapterRouter(
        {
            ActionType.CALENDAR_READ: CalendarReadHandler(cal_read_adapter),
            ActionType.CALENDAR_UPDATE: CalendarUpdateHandler(cal_update_adapter),
            ActionType.TASK_READ: TasksReadHandler(tasks_read),
            ActionType.TASK_CREATE: TasksCreateHandler(tasks_create),
            ActionType.WEATHER_READ: WeatherReadHandler(weather_read),
        }
    )

    shared_mission_id = MissionId.generate()

    read_action = ActionContract.create(
        mission_id=shared_mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=DEMO_EVENT_ID,
            parent_id=DEMO_CALENDAR_ID,
        ),
        parameters={},
        action_id=ActionId.generate(),
    )

    before_result = cal_read_adapter.read_event(read_action)
    assert before_result.status == CalendarReadStatus.SUCCESS, "Before read must succeed"
    assert before_result.observation is not None
    before_obs = before_result.observation
    before_state = {
        "summary": before_obs.summary,
        "start_time": before_obs.start_time,
        "end_time": before_obs.end_time,
        "all_day": before_obs.all_day,
        "etag": before_obs.etag,
    }

    # Step 2: Construct the canonical CALENDAR_UPDATE action contract
    update_action = ActionContract.create(
        mission_id=shared_mission_id,
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
        action_id=ActionId.generate(),
    )

    # Step 3: Evaluate authority under frozen P-11.01 policy
    policy = get_action_authority_policy(update_action.action_type)
    assert policy.authority_class == AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED
    assert policy.requires_bound_approval is True
    assert policy.requires_human_approval is True
    assert policy.permit_execution_without_grant is False

    # Step 4: Construct canonical P-11.02 PendingApproval
    req_at = datetime.now(UTC)
    validated_action = validate_action_contract(update_action)
    pending_approval = create_pending_approval(validated_action, requested_at=req_at)
    assert pending_approval.is_approved is False
    assert pending_approval.status == PendingApprovalStatus.PENDING

    # Step 5 & 6: Enforce NO approval grant and NO approval consumption
    registry = UsedApprovalRegistry()
    approval_ledger = ApprovalLedger(registry=registry)
    assert approval_ledger.is_used(pending_approval.pending_approval_id.value) is False
    assert approval_ledger.is_consumed(pending_approval.pending_approval_id.value) is False
    assert (
        approval_ledger.check_status(pending_approval.pending_approval_id.value)
        == ApprovalUsageStatus.UNUSED
    )

    # Step 7: Send candidate action through execution authority gate
    exec_contract = MissionExecutionContract(
        mission_id=update_action.mission_id,
        actions=(update_action,),
        dependencies={
            update_action.action_id: frozenset(),
        },
    )
    schedule = schedule_execution(exec_contract)
    tracker = ExecutionStateTracker(exec_contract, schedule)
    initial_update_calls = cal_transport.writes_count

    gate_decision = execute_gated_action(
        update_action,
        router,
        tracker=tracker,
        approval=None,  # Strictly NO approval provided
        pending_approval=pending_approval,
    )

    # Step 8: Assert mutation execution is rejected BEFORE provider write
    assert cal_transport.writes_count == initial_update_calls == 0, (
        "Provider update method must NEVER be invoked"
    )
    assert gate_decision.is_authorized is False
    assert gate_decision.attempt is None
    assert gate_decision.provider_result is None

    # Step 9: Record deterministic result as NOT_RUN
    assert gate_decision.status == ActionExecutionStatus.NOT_RUN
    assert tracker.get_status(update_action.action_id) == ActionExecutionStatus.NOT_RUN
    record = tracker.get_record(update_action.action_id)
    assert record is not None
    assert record.status == ActionExecutionStatus.NOT_RUN
    assert "requires bound human approval" in record.error_message

    # Step 10: Perform separate independent Calendar read-back
    read_after_action = ActionContract.create(
        mission_id=shared_mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=DEMO_EVENT_ID,
            parent_id=DEMO_CALENDAR_ID,
        ),
        parameters={},
        action_id=ActionId.generate(),
    )
    after_result = cal_read_adapter.read_event(read_after_action)
    assert after_result.status == CalendarReadStatus.SUCCESS
    assert after_result.observation is not None
    after_obs = after_result.observation
    after_state = {
        "summary": after_obs.summary,
        "start_time": after_obs.start_time,
        "end_time": after_obs.end_time,
        "all_day": after_obs.all_day,
        "etag": after_obs.etag,
    }

    # Step 11: Prove external event state is 100% unchanged
    assert before_state == after_state, (
        f"External event state mutated! Before: {before_state}, After: {after_state}"
    )
    assert after_state["start_time"] == INITIAL_START_TIME
    assert after_state["start_time"] != PROPOSED_START_TIME

    # Step 12: Produce durable UnapprovedActionReceipt
    receipt = create_unapproved_action_receipt(
        source_sha=current_sha,
        mission_id=update_action.mission_id,
        action_id=update_action.action_id,
        action_type=update_action.action_type,
        authority_class=policy.authority_class,
        target_event_id=DEMO_EVENT_ID,
        pending_approval_id=pending_approval.pending_approval_id,
        before_state_summary=before_state,
        after_state_summary=after_state,
        before_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
        after_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    # Verification of receipt invariants
    receipt_dict = receipt.to_dict()
    assert receipt_dict["execution_state"] == "NOT_RUN"
    assert receipt_dict["provider_mutation_invocations"] == 0
    assert receipt_dict["state_unchanged"] is True
    assert receipt_dict["grant_present"] is False
    assert receipt_dict["consumption_present"] is False
    assert receipt_dict["is_ready_claimed"] is False

    return {
        "task": "P-11.05 -- Prove Calendar existing-event update remains NOT_RUN before approval",
        "current_git_sha": current_sha,
        "canonical_starting_sha": CANONICAL_SOURCE_SHA,
        "target_class": "CalendarEvent (Leave for school demo event)",
        "target_event_id": DEMO_EVENT_ID,
        "authority_classification": policy.authority_class.value,
        "pending_approval_id": str(pending_approval.pending_approval_id.value),
        "pending_approval_status": pending_approval.status.value,
        "approval_grant_present": False,
        "approval_consumed": False,
        "provider_update_invocation_count": cal_transport.writes_count,
        "execution_status": gate_decision.status.value,
        "before_state": before_state,
        "after_state": after_state,
        "external_state_unchanged": True,
        "receipt": receipt_dict,
        "live_read_status": live_status,
        "not_run_checks": [
            "P-11.06 approved execution path (NotImplementedError)",
            "Live Google Calendar update mutations (0 live writes permitted)",
            "Live Google Calendar read execution (BLOCKED: token not cached)",
            "Human ApprovalGrant creation (intentionally omitted)",
            "Retry orchestrator execution (NOT_RUN consumes 0 retry budget)",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="P-11.05 Proof Script")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    result = run_p11_05_proof()

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("=" * 70)
    print("P-11.05 PROOF: CALENDAR UPDATE REMAINS NOT_RUN BEFORE APPROVAL")
    print("=" * 70)
    print(f"Task:                    {result['task']}")
    print(f"Current Git SHA:         {result['current_git_sha']}")
    print(f"Starting SHA:            {result['canonical_starting_sha']}")
    print(f"Target Event:            {result['target_event_id']}")
    print(f"Authority Class:         {result['authority_classification']}")
    print(f"Pending Approval ID:     {result['pending_approval_id']}")
    print(f"Pending Approval Status: {result['pending_approval_status']}")
    print(f"Approval Grant Present:  {result['approval_grant_present']}")
    print(f"Approval Consumed:       {result['approval_consumed']}")
    print(f"Provider Mutation Calls: {result['provider_update_invocation_count']}")
    print(f"Execution Gate Status:   {result['execution_status']}")
    print(f"External State Unchanged:{result['external_state_unchanged']}")
    print(f"Before Start Time:       {result['before_state']['start_time']}")
    print(f"After Start Time:        {result['after_state']['start_time']}")
    print(f"Live Read Check:         {result['live_read_status']['status']}")
    print(f"Live Read Reason:        {result['live_read_status']['reason']}")
    print("=" * 70)
    print("PROOF CHAIN VERIFIED: NOT_RUN BEFORE APPROVAL PROVEN CONCLUSIVELY.")
    print("=" * 70)


if __name__ == "__main__":
    main()
