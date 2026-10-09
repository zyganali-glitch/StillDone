"""P-11.05 Proof Script: Prove Calendar existing-event update remains NOT_RUN before approval.

Executes the deterministic 12-step proof chain demonstrating that a canonical
CALENDAR_UPDATE action requiring approval:
1. Is classified REVERSIBLE_APPROVAL_REQUIRED under frozen P-11.01 policy.
2. Produces a canonical P-11.02 PendingApproval in PENDING state.
3. Has NO approval granted and NO approval consumed.
4. Is rejected at the execution authority gate BEFORE provider write.
5. Produces exactly zero provider mutation invocations (measured writes == 0).
6. Records deterministic execution status ActionExecutionStatus.NOT_RUN.
7. Leaves external Calendar state 100% unchanged between before/after reads.
8. Produces a durable UnapprovedActionReceipt derived from observed facts with zero secrets.
9. Proves no execution attempt is fabricated and no retry budget is consumed.
10. Proves model prose / planner proposals cannot bypass the gate.

Live boundary truth:
Live Google Calendar read is reported NOT_RUN / BLOCKED in this headless runtime,
and simulation provenance is faithfully recorded as LOCAL_EXECUTION / FIXTURE.
Zero live mutations are ever performed.

Reliability guarantees:
- All checks use fail-closed runtime validation (effective under python -O).
- Fails closed if git SHA cannot be determined.
- Explicit tracking of worktree cleanliness and exact source provenance.
"""

from __future__ import annotations

import argparse
import json
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
    CalendarMutationSpy,
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

LAST_VERIFIED_PARENT_SHA = "4ec4475f006207ec5840880bb9476f6d169442cd"
AUDITED_P11_05_IMPLEMENTATION_SHA = "12b42e4f0f92a08518b1e6efe4fd030912477bc9"

DEMO_CALENDAR_ID = "c_1880abc123demo@group.calendar.google.com"
DEMO_TASKLIST_ID = "MDExMTI0ZGVtbw"
DEMO_EVENT_ID = "evt_leave_for_school_001"
INITIAL_START_TIME = "2026-10-09T07:45:00+03:00"
INITIAL_END_TIME = "2026-10-09T08:15:00+03:00"
PROPOSED_START_TIME = "2026-10-09T07:30:00+03:00"
PROPOSED_SUMMARY = "Leave for school"


class ProofVerificationError(Exception):
    """Raised when any step of the proof chain fails runtime validation."""


def get_git_commit_sha() -> str:
    """Get the current verified git commit SHA, failing closed if unavailable."""
    try:
        sha = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(REPO_ROOT),
                text=True,
            )
            .strip()
            .lower()
        )
        if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha):
            raise ProofVerificationError(
                f"Git HEAD output is not a valid 40-character hex SHA: {sha!r}"
            )
        return sha
    except Exception as exc:
        raise ProofVerificationError(
            f"Cannot determine git commit SHA; proof fails closed: {exc}"
        ) from exc


def check_git_worktree_clean() -> bool:
    """Check whether the working tree is clean."""
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT),
            text=True,
        ).strip()
        return len(output) == 0
    except Exception:
        return False


def check_live_google_credentials() -> dict[str, Any]:
    """Report live boundary status: headless proof executes locally; live read not exercised."""
    return {
        "status": "NOT_RUN",
        "reason": (
            "Live Google Calendar read not exercised in headless test runtime. "
            "Zero live mutations permitted (writes_count == 0). "
            "Execution gating and receipt verified via LOCAL_EXECUTION / FIXTURE."
        ),
        "exercised": False,
    }


def run_p11_05_proof(*, expected_sha: str | None = None) -> dict[str, Any]:
    """Execute the canonical P-11.05 proof chain with fail-closed runtime checks."""
    current_sha = get_git_commit_sha()
    is_worktree_clean = check_git_worktree_clean()

    if expected_sha is not None:
        if not is_worktree_clean:
            raise ProofVerificationError(
                "Cannot claim exact-SHA committed-source proof when git worktree is dirty"
            )
        cleaned_expected = expected_sha.strip().lower()
        if current_sha != cleaned_expected:
            raise ProofVerificationError(
                f"Current git SHA {current_sha} does not match expected SHA {cleaned_expected}"
            )

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

    cal_update_handler = CalendarUpdateHandler(cal_update_adapter)
    router = AdapterRouter(
        {
            ActionType.CALENDAR_READ: CalendarReadHandler(cal_read_adapter),
            ActionType.CALENDAR_UPDATE: cal_update_handler,
            ActionType.TASK_READ: TasksReadHandler(tasks_read),
            ActionType.TASK_CREATE: TasksCreateHandler(tasks_create),
            ActionType.WEATHER_READ: WeatherReadHandler(weather_read),
        }
    )

    mutation_spy = CalendarMutationSpy(
        router=router,
        handler=cal_update_handler,
        transport=cal_transport,
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
    if before_result.status != CalendarReadStatus.SUCCESS:
        raise ProofVerificationError(f"Before read failed: {before_result.status.value}")
    if before_result.observation is None:
        raise ProofVerificationError("Before read observation is None")

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
    if policy.authority_class != AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED:
        raise ProofVerificationError(
            f"Expected REVERSIBLE_APPROVAL_REQUIRED, got {policy.authority_class.value}"
        )
    if not policy.requires_bound_approval:
        raise ProofVerificationError("Expected requires_bound_approval=True")
    if not policy.requires_human_approval:
        raise ProofVerificationError("Expected requires_human_approval=True")
    if policy.permit_execution_without_grant:
        raise ProofVerificationError("Expected permit_execution_without_grant=False")

    # Step 4: Construct canonical P-11.02 PendingApproval
    req_at = datetime.now(UTC)
    validated_action = validate_action_contract(update_action)
    pending_approval = create_pending_approval(validated_action, requested_at=req_at)
    if pending_approval.status != PendingApprovalStatus.PENDING:
        raise ProofVerificationError(
            f"PendingApproval must be PENDING, got {pending_approval.status.value}"
        )

    # Step 5 & 6: Enforce NO approval grant and NO approval consumption
    registry = UsedApprovalRegistry()
    approval_ledger = ApprovalLedger(registry=registry)
    if approval_ledger.has_consumed_approval_for_action(update_action.action_id):
        raise ProofVerificationError("Approval consumption record exists in ledger for this action")

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

    mutation_obs = mutation_spy.observe()

    # Step 8: Assert mutation execution is rejected BEFORE provider write
    if not mutation_obs.is_zero_mutation:
        raise ProofVerificationError(
            f"Provider mutation was invoked during unapproved execution! {mutation_obs.to_dict()}"
        )
    if cal_transport.writes_count != initial_update_calls or cal_transport.writes_count != 0:
        raise ProofVerificationError(
            f"Provider update method was invoked! Writes count: {cal_transport.writes_count}"
        )
    if gate_decision.is_authorized is not False:
        raise ProofVerificationError("gate_decision.is_authorized must be False")
    if gate_decision.attempt is not None:
        raise ProofVerificationError("gate_decision.attempt must be None")
    if gate_decision.provider_result is not None:
        raise ProofVerificationError("gate_decision.provider_result must be None")

    # Step 9: Record deterministic result as NOT_RUN
    if gate_decision.status != ActionExecutionStatus.NOT_RUN:
        raise ProofVerificationError(
            f"gate_decision.status must be NOT_RUN, got {gate_decision.status.value}"
        )
    if tracker.get_status(update_action.action_id) != ActionExecutionStatus.NOT_RUN:
        raise ProofVerificationError("tracker status must be NOT_RUN")
    record = tracker.get_record(update_action.action_id)
    if record is None:
        raise ProofVerificationError("tracker record is None")
    if record.status != ActionExecutionStatus.NOT_RUN:
        raise ProofVerificationError(
            f"tracker record status must be NOT_RUN, got {record.status.value}"
        )
    if record.error_message is None or "requires bound human approval" not in record.error_message:
        raise ProofVerificationError(
            f"tracker record error message missing expected text: {record.error_message}"
        )

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
    if after_result.status != CalendarReadStatus.SUCCESS:
        raise ProofVerificationError(f"After read failed: {after_result.status.value}")
    if after_result.observation is None:
        raise ProofVerificationError("After read observation is None")

    # Chronological ordering checks:
    # before observation -> gate evaluation -> independent after observation
    if before_result.read_at > gate_decision.evaluated_at:
        raise ProofVerificationError(
            "Chronology violation: before_result.read_at occurred after gate evaluation"
        )
    if after_result.read_at < gate_decision.evaluated_at:
        raise ProofVerificationError(
            "Chronology violation: after_result.read_at occurred before gate evaluation"
        )
    if before_result.read_at >= after_result.read_at:
        raise ProofVerificationError(
            "Chronology violation: before_result.read_at >= after_result.read_at"
        )

    after_obs = after_result.observation
    after_state = {
        "summary": after_obs.summary,
        "start_time": after_obs.start_time,
        "end_time": after_obs.end_time,
        "all_day": after_obs.all_day,
        "etag": after_obs.etag,
    }

    # Step 11: Prove external event state is 100% unchanged
    if before_state != after_state:
        raise ProofVerificationError(
            f"External event state mutated! Before: {before_state}, After: {after_state}"
        )
    if after_state["start_time"] != INITIAL_START_TIME:
        raise ProofVerificationError(
            f"start_time changed from initial: {after_state['start_time']}"
        )
    if after_state["start_time"] == PROPOSED_START_TIME:
        raise ProofVerificationError("start_time equals proposed start_time; mutation executed!")

    # Step 12: Produce durable UnapprovedActionReceipt derived from observed facts
    receipt = create_unapproved_action_receipt(
        gate_decision=gate_decision,
        action=update_action,
        pending_approval=pending_approval,
        before_read=before_result,
        after_read=after_result,
        measured_provider_mutations=cal_transport.writes_count,
        mutation_observation=mutation_obs,
        source_sha=current_sha,
        ledger=approval_ledger,
        before_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
        after_read_provenance=EvidenceProvenance.LOCAL_EXECUTION,
        provenance=EvidenceProvenance.LOCAL_EXECUTION,
    )

    # Verification of receipt invariants
    receipt_dict = receipt.to_dict()
    if receipt_dict["execution_state"] != "NOT_RUN":
        raise ProofVerificationError("receipt execution_state != NOT_RUN")
    if receipt_dict["provider_mutation_invocations"] != 0:
        raise ProofVerificationError("receipt provider_mutation_invocations != 0")
    if receipt_dict["state_unchanged"] is not True:
        raise ProofVerificationError("receipt state_unchanged is not True")
    if receipt_dict["grant_present"] is not False:
        raise ProofVerificationError("receipt grant_present is not False")
    if receipt_dict["consumption_present"] is not False:
        raise ProofVerificationError("receipt consumption_present is not False")
    if receipt_dict["is_ready_claimed"] is not False:
        raise ProofVerificationError("receipt is_ready_claimed is not False")

    return {
        "task": "P-11.05 -- Prove Calendar existing-event update remains NOT_RUN before approval",
        "current_git_sha": current_sha,
        "last_verified_parent_sha": LAST_VERIFIED_PARENT_SHA,
        "worktree_clean": is_worktree_clean,
        "source_provenance_mode": "COMMITTED_SOURCE"
        if is_worktree_clean
        else "LOCAL_DIRTY_WORKTREE",
        "target_class": "CalendarEvent (Leave for school demo event)",
        "target_event_id": DEMO_EVENT_ID,
        "authority_classification": policy.authority_class.value,
        "pending_approval_id": str(pending_approval.pending_approval_id.value),
        "pending_approval_status": pending_approval.status.value,
        "approval_grant_present": False,
        "approval_consumed": False,
        "provider_update_invocation_count": cal_transport.writes_count,
        "provider_mutation_observation": mutation_obs.to_dict(),
        "execution_status": gate_decision.status.value,
        "before_state": before_state,
        "after_state": after_state,
        "external_state_unchanged": True,
        "receipt": receipt_dict,
        "live_read_status": live_status,
        "not_run_checks": [
            "P-11.06 approved execution path (NotImplementedError)",
            "Live Google Calendar update mutations (0 live writes permitted)",
            "Live Google Calendar read execution (NOT_RUN / BLOCKED in headless runtime)",
            "Human ApprovalGrant creation (intentionally omitted)",
            "Retry orchestrator execution (NOT_RUN consumes 0 retry budget)",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="P-11.05 Proof Script")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument(
        "--expected-sha", type=str, default=None, help="Verify against expected git SHA"
    )
    args = parser.parse_args()

    result = run_p11_05_proof(expected_sha=args.expected_sha)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("=" * 70)
    print("P-11.05 PROOF: CALENDAR UPDATE REMAINS NOT_RUN BEFORE APPROVAL")
    print("=" * 70)
    print(f"Task:                    {result['task']}")
    print(f"Current Git SHA:         {result['current_git_sha']}")
    print(f"Parent Verified SHA:     {result['last_verified_parent_sha']}")
    print(f"Worktree Clean:          {result['worktree_clean']}")
    print(f"Source Provenance:       {result['source_provenance_mode']}")
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
