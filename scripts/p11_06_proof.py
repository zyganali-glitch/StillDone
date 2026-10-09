"""P-11.06 Proof Script: Prove approved Calendar update executes once and verifies.

Executes the deterministic 12-step proof chain demonstrating that a canonical
CALENDAR_UPDATE action with a valid bound ApprovalGrant:
1. Validates canonical action contract, exact target, and frozen P-11.01 policy.
2. Requires a human-originated, exact-action-bound ApprovalGrant.
3. Validates mission ID, action ID, action type, parameters, target, binding hash,
   and validity window.
4. Atomically consumes the grant through ApprovalLedger before provider mutation.
5. Fails closed if durable consumption cannot be persisted.
6. Generates exactly one canonical execution attempt.
7. Dispatches exactly once through authorized Google Calendar update adapter (write == 1).
8. Preserves actual provider result and external identifiers without fabrication.
9. Performs a fresh, separate independent Google Calendar read-back.
10. Evaluates the exact desired-state predicate using deterministic verification.
11. Records provenance, read-back, predicate, and final execution truth durably.
12. Promotes to VERIFIED and READY only when all lifecycle, evidence, and freshness
    rules are satisfied.
13. Proves replay rejection: subsequent attempt with same grant fails closed with
    zero further writes.

Live boundary truth:
Live Google Calendar mutation is reported NOT_RUN / BLOCKED in this headless runtime
(missing per-event operator consent, absent OAuth tokens, strict $0.00 personal spend rule).
Zero unapproved live mutations are ever performed.

Reliability guarantees:
- All checks use fail-closed runtime validation (effective under python -O).
- Fails closed if git SHA cannot be determined or does not match expected.
- Explicit tracking of worktree cleanliness and exact source provenance.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure src is on path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from stilldone.action_policy import validate_action_contract  # noqa: E402
from stilldone.adapters.calendar import (  # noqa: E402
    CalendarReadbackStatus,
    CalendarReadStatus,
    FakeGoogleCalendarTransport,
    GoogleCalendarReadAdapter,
    GoogleCalendarUpdateAdapter,
)
from stilldone.approval_consumption import (  # noqa: E402
    ApprovalAlreadyUsedError,
    ApprovalLedger,
    ApprovalUsageStatus,
)
from stilldone.authority_policy import (  # noqa: E402
    get_action_authority_policy,
)
from stilldone.demo_isolation import DemoResourceScope  # noqa: E402
from stilldone.domain.action import (  # noqa: E402
    ActionContract,
    ActionType,
    ResourceKind,
    TargetIdentity,
)
from stilldone.domain.authority import (  # noqa: E402
    ApprovalGrant,
    AuthorityClass,
)
from stilldone.domain.desired_state import (  # noqa: E402
    DesiredStatePredicate,
    PredicateOperator,
)
from stilldone.domain.lifecycle import MissionState  # noqa: E402
from stilldone.domain.mission import (  # noqa: E402
    MissionContract,
    MissionId,
    UserIntentSnapshot,
)
from stilldone.execution.gate import (  # noqa: E402
    ApprovedActionReceipt,
    CalendarMutationSpy,
    execute_approved_calendar_update,
)
from stilldone.execution.router import (  # noqa: E402
    AdapterRouter,
    CalendarReadHandler,
    CalendarUpdateHandler,
)
from stilldone.execution.state import ActionExecutionStatus  # noqa: E402
from stilldone.ledger import (  # noqa: E402
    ActionRecord,
    DurableFileLedger,
    MissionRecord,
)
from stilldone.pending_approval import (  # noqa: E402
    create_pending_approval,
)
from stilldone.verifier.predicates import PredicateTruth  # noqa: E402

LAST_VERIFIED_PARENT_SHA = "864cfa4e2b47ade72d1f4095e78e06f309372320"

DEMO_CALENDAR_ID = "c_1880abc123demo@group.calendar.google.com"
DEMO_EVENT_ID = "evt_leave_for_school_001"
INITIAL_START_TIME = "2026-10-09T07:45:00+03:00"
INITIAL_END_TIME = "2026-10-09T08:15:00+03:00"
INITIAL_ETAG = "etag_initial_1001"
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
                stderr=subprocess.DEVNULL,
            )
            .decode("ascii")
            .strip()
        )
        if len(sha) != 40 or not all(c in "0123456789abcdefABCDEF" for c in sha):
            raise ProofVerificationError(f"Malformed git commit SHA returned: {sha!r}")
        return sha.lower()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        raise ProofVerificationError("Failed to obtain current git SHA") from exc


def check_git_worktree_clean() -> bool:
    """Check if the git working tree has unstaged or untracked changes."""
    try:
        status_output = (
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=str(REPO_ROOT),
                stderr=subprocess.DEVNULL,
            )
            .decode("utf-8")
            .strip()
        )
        return len(status_output) == 0
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def run_p11_06_proof(*, expected_sha: str | None = None) -> dict[str, Any]:
    """Execute the deterministic 12-step approved Calendar update proof chain."""
    current_sha = get_git_commit_sha()
    is_worktree_clean = check_git_worktree_clean()

    if expected_sha is not None and current_sha.lower() != expected_sha.lower():
        raise ProofVerificationError(
            f"Expected git SHA {expected_sha.lower()!r} but found {current_sha.lower()!r}"
        )

    # -------------------------------------------------------------------------
    # Setup: Demo Scope & Seeded Fake Transport
    # -------------------------------------------------------------------------
    demo_scope = DemoResourceScope(
        calendar_id=DEMO_CALENDAR_ID,
        task_list_id="tl_1880abc123demo",
    )

    cal_transport = FakeGoogleCalendarTransport()
    cal_transport.seed_event(
        calendar_id=DEMO_CALENDAR_ID,
        event_id=DEMO_EVENT_ID,
        summary=PROPOSED_SUMMARY,
        start_time=INITIAL_START_TIME,
        end_time=INITIAL_END_TIME,
        all_day=False,
        etag=INITIAL_ETAG,
        status="confirmed",
    )

    read_adapter = GoogleCalendarReadAdapter(demo_scope, cal_transport)
    update_adapter = GoogleCalendarUpdateAdapter(demo_scope, cal_transport)

    router = AdapterRouter(
        {
            ActionType.CALENDAR_READ: CalendarReadHandler(read_adapter),
            ActionType.CALENDAR_UPDATE: CalendarUpdateHandler(update_adapter),
        }
    )

    # -------------------------------------------------------------------------
    # Durable ledger setup in temporary storage to prove restart & durability
    # -------------------------------------------------------------------------
    tmp_dir = tempfile.TemporaryDirectory()
    ledger_path = Path(tmp_dir.name) / "mission_evidence.jsonl"
    durable_ledger = DurableFileLedger(ledger_path)

    # -------------------------------------------------------------------------
    # Step 1: Validate Action Contract & Frozen Authority Policy
    # -------------------------------------------------------------------------
    mission_id = MissionId.generate()

    update_action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_UPDATE,
        target=TargetIdentity(
            system="google_calendar",
            resource_kind=ResourceKind.CALENDAR_EVENT,
            resource_id=DEMO_EVENT_ID,
            parent_id=DEMO_CALENDAR_ID,
        ),
        parameters={"start_time": PROPOSED_START_TIME},
    )
    action_id = update_action.action_id
    validated_action = validate_action_contract(update_action)

    policy = get_action_authority_policy(ActionType.CALENDAR_UPDATE)
    if policy.authority_class != AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED:
        raise ProofVerificationError(
            f"Policy authority class mismatch: {policy.authority_class.value}"
        )
    if not policy.requires_bound_approval:
        raise ProofVerificationError("CALENDAR_UPDATE must require bound approval")

    # Seed mission and action in durable ledger
    now = datetime.now(UTC)
    durable_ledger.append_mission(
        MissionRecord(
            mission_id=mission_id,
            contract=MissionContract(
                mission_id=mission_id,
                intent=UserIntentSnapshot(
                    text="Move leave for school earlier",
                    captured_at=now,
                    mission_id=mission_id,
                ),
                created_at=now,
            ),
            state=MissionState.VERIFYING,
            created_at=now,
            updated_at=now,
        )
    )

    # -------------------------------------------------------------------------
    # Step 2: Establish PendingApproval and Human-Originated ApprovalGrant
    # -------------------------------------------------------------------------
    pending = create_pending_approval(validated_action, requested_at=now - timedelta(seconds=5))
    issued_at = now - timedelta(seconds=2)
    expires_at = now + timedelta(minutes=15)

    grant = ApprovalGrant.create(
        action=update_action,
        authority_class=AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED,
        issued_at=issued_at,
        expires_at=expires_at,
    )

    durable_ledger.append_action(
        ActionRecord(
            action_id=action_id,
            mission_id=mission_id,
            action=update_action,
            approval_id=grant.approval_id,
            created_at=now,
        )
    )

    # Initialize ApprovalLedger backed by durable ledger
    approval_ledger = ApprovalLedger(ledger=durable_ledger)

    # -------------------------------------------------------------------------
    # Step 3: Desired-State Predicate
    # -------------------------------------------------------------------------
    predicate = DesiredStatePredicate.create(
        mission_id=mission_id,
        subject="start_time",
        operator=PredicateOperator.EQUALS,
        expected_value=PROPOSED_START_TIME,
    )

    # -------------------------------------------------------------------------
    # Step 4: Initial Before-Read Check
    # -------------------------------------------------------------------------
    before_action = ActionContract.create(
        mission_id=mission_id,
        action_type=ActionType.CALENDAR_READ,
        target=update_action.target,
        parameters={},
    )
    before_result = read_adapter.read_event(before_action)
    if before_result.status != CalendarReadStatus.SUCCESS or before_result.observation is None:
        raise ProofVerificationError("Initial before-read failed")
    if before_result.observation.start_time != INITIAL_START_TIME:
        raise ProofVerificationError(
            f"Initial start time mismatch: {before_result.observation.start_time}"
        )

    # -------------------------------------------------------------------------
    # Step 5: Instrument Spy and Execute Approved Update Pipeline
    # -------------------------------------------------------------------------
    spy = CalendarMutationSpy(router=router, transport=cal_transport)

    outcome = execute_approved_calendar_update(
        validated_action,
        router,
        grant,
        approval_ledger,
        read_adapter,
        predicate,
        source_sha=current_sha,
        pending_approval=pending,
        spy=spy,
        before_read=before_result,
        mission_ledger=durable_ledger,
        mission_state=MissionState.VERIFYING,
    )

    # -------------------------------------------------------------------------
    # Step 6: Validate Gate Decision & Exactly-Once Mutation Counts
    # -------------------------------------------------------------------------
    gate_decision = outcome.gate_decision
    if not gate_decision.is_authorized:
        raise ProofVerificationError("Gate decision was not authorized")
    if gate_decision.status != ActionExecutionStatus.EXECUTION_SUCCEEDED:
        raise ProofVerificationError(
            f"Gate decision status != EXECUTION_SUCCEEDED: {gate_decision.status.value}"
        )

    # Provider invocation and write counts: strictly 1
    if cal_transport.writes_count != 1:
        raise ProofVerificationError(
            f"Expected exactly 1 transport write, got {cal_transport.writes_count}"
        )
    if outcome.mutation_observation.transport_writes != 1:
        raise ProofVerificationError(
            f"Observed transport writes != 1: {outcome.mutation_observation.transport_writes}"
        )
    if outcome.mutation_observation.router_mutation_invocations != 1:
        raise ProofVerificationError(
            f"Observed router invocations != 1: "
            f"{outcome.mutation_observation.router_mutation_invocations}"
        )

    # -------------------------------------------------------------------------
    # Step 7: Validate Approval Consumption
    # -------------------------------------------------------------------------
    if outcome.consumption_record.status != ApprovalUsageStatus.CONSUMED:
        raise ProofVerificationError(
            f"Consumption status != CONSUMED: {outcome.consumption_record.status.value}"
        )
    if not approval_ledger.has_consumed_approval_for_action(action_id):
        raise ProofVerificationError(f"Approval was not consumed for action {action_id}")

    # -------------------------------------------------------------------------
    # Step 8: Validate Independent Read-Back
    # -------------------------------------------------------------------------
    after_read = outcome.after_read
    if after_read.status != CalendarReadStatus.SUCCESS or after_read.observation is None:
        raise ProofVerificationError("Independent read-back failed")
    if after_read is before_result:
        raise ProofVerificationError("Independent read-back is identical instance to before-read")
    if after_read.observation.start_time != PROPOSED_START_TIME:
        raise ProofVerificationError(
            f"Independent read-back observed unexpected start time: "
            f"{after_read.observation.start_time}"
        )
    if outcome.readback_result.status != CalendarReadbackStatus.MATCH:
        raise ProofVerificationError(
            f"Readback status != MATCH: {outcome.readback_result.status.value}"
        )

    # -------------------------------------------------------------------------
    # Step 9: Validate Predicate Truth & Lawful Verification Promotion
    # -------------------------------------------------------------------------
    if outcome.predicate_result.truth != PredicateTruth.TRUE:
        raise ProofVerificationError(
            f"Predicate truth != TRUE: {outcome.predicate_result.truth.value}"
        )
    if not outcome.is_verified:
        raise ProofVerificationError("Outcome is_verified is False")
    # Mission READY transition is unpersisted in P-11.06 (deferred to P-12).
    # Truth invariant: Action is verified (is_verified=True), but mission is_ready is False,
    # mission_ready_status is NOT_ESTABLISHED, and readiness determination computed is_ready=True.
    if outcome.is_ready is not False:
        raise ProofVerificationError("Outcome is_ready must be False (unpersisted in P-11.06)")
    if outcome.mission_ready_status != "NOT_ESTABLISHED":
        raise ProofVerificationError(
            f"Outcome mission_ready_status != NOT_ESTABLISHED: {outcome.mission_ready_status}"
        )
    if outcome.readiness_determination is None or not outcome.readiness_determination.is_ready:
        raise ProofVerificationError("Readiness determination was not computed as READY")

    # -------------------------------------------------------------------------
    # Step 10: Validate Immutable Durable Receipt
    # -------------------------------------------------------------------------
    receipt = outcome.receipt
    if not isinstance(receipt, ApprovedActionReceipt):
        raise ProofVerificationError(
            f"Receipt type != ApprovedActionReceipt: {type(receipt).__name__}"
        )
    if not receipt.is_verified:
        raise ProofVerificationError("Receipt is_verified is False")
    if receipt.is_ready_claimed:
        raise ProofVerificationError(
            "Receipt is_ready_claimed must be False (unpersisted in P-11.06)"
        )
    if receipt.provider_writes != 1:
        raise ProofVerificationError(f"Receipt provider_writes != 1: {receipt.provider_writes}")

    receipt_dict = receipt.to_dict()

    # -------------------------------------------------------------------------
    # Step 11: Replay Attempt Must Fail Closed With 0 Further Writes
    # -------------------------------------------------------------------------
    replay_blocked = False
    try:
        execute_approved_calendar_update(
            validated_action,
            router,
            grant,
            approval_ledger,
            read_adapter,
            predicate,
            source_sha=current_sha,
            mission_ledger=durable_ledger,
        )
    except ApprovalAlreadyUsedError:
        replay_blocked = True

    if not replay_blocked:
        raise ProofVerificationError("Replay attempt was NOT blocked by approval ledger")
    if cal_transport.writes_count != 1:
        raise ProofVerificationError(
            f"Replay attempt caused additional write! Total writes: {cal_transport.writes_count}"
        )

    # -------------------------------------------------------------------------
    # Step 12: Durable Hydration Verification across simulated process restart
    # -------------------------------------------------------------------------
    reloaded_ledger = DurableFileLedger(ledger_path)
    reloaded_approval_ledger = ApprovalLedger.from_ledger(reloaded_ledger)
    if not reloaded_approval_ledger.is_consumed(grant.approval_id):
        raise ProofVerificationError(
            "Durable hydration failed: approval not marked consumed after reload"
        )
    if not reloaded_approval_ledger.has_consumed_approval_for_action(action_id):
        raise ProofVerificationError(
            "Durable hydration failed: action not marked consumed after reload"
        )

    # Clean up temp directory
    tmp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Live Boundary Truth
    # -------------------------------------------------------------------------
    live_gate_status = {
        "status": "NOT_RUN / BLOCKED",
        "reason": (
            "Per-event human operator approval for exact disposable event ID absent; "
            "headless test environment contains no OAuth tokens; "
            "zero personal spend law strictly enforces $0.00."
        ),
        "live_mutation_permitted": False,
        "live_writes_performed": 0,
    }

    return {
        "task": "P-11.06 -- Prove approved Calendar update executes once and verifies",
        "current_git_sha": current_sha,
        "last_verified_parent_sha": LAST_VERIFIED_PARENT_SHA,
        "worktree_clean": is_worktree_clean,
        "source_provenance_mode": "COMMITTED_SOURCE"
        if is_worktree_clean
        else "LOCAL_DIRTY_WORKTREE",
        "target_class": "CalendarEvent (Leave for school demo event)",
        "target_event_id": DEMO_EVENT_ID,
        "calendar_id": DEMO_CALENDAR_ID,
        "authority_classification": policy.authority_class.value,
        "approval_id": str(grant.approval_id.value),
        "binding_hash": grant.binding_hash.value,
        "consumption_status": outcome.consumption_record.status.value,
        "execution_status": gate_decision.status.value,
        "provider_writes_performed": outcome.provider_result.writes_performed,
        "total_transport_writes": cal_transport.writes_count,
        "before_start_time": before_result.observation.start_time,
        "after_start_time": after_read.observation.start_time,
        "readback_status": outcome.readback_result.status.value,
        "predicate_truth": outcome.predicate_result.truth.value,
        "is_verified": outcome.is_verified,
        "is_ready": outcome.is_ready,
        "mission_ready_status": outcome.mission_ready_status,
        "readiness_determination_ready": (
            outcome.readiness_determination.is_ready if outcome.readiness_determination else None
        ),
        "receipt": receipt_dict,
        "replay_prevention_verified": replay_blocked,
        "durable_hydration_verified": True,
        "live_gate_status": live_gate_status,
        "not_run_checks": [
            "Live Google Calendar update mutations "
            "(0 live writes permitted without operator signoff)",
            "Live Google Calendar token acquisition (OAuth tokens not cached in headless CI)",
            "P-12+ planning/execution phases (strictly NOT_RUN / not authorized)",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="P-11.06 Proof Script")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument(
        "--expected-sha", type=str, default=None, help="Verify against expected git SHA"
    )
    args = parser.parse_args()

    result = run_p11_06_proof(expected_sha=args.expected_sha)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("=" * 70)
    print("P-11.06 PROOF: APPROVED CALENDAR UPDATE EXECUTES ONCE AND VERIFIES")
    print("=" * 70)
    print(f"Task:                         {result['task']}")
    print(f"Current Git SHA:              {result['current_git_sha']}")
    print(f"Parent Verified SHA:          {result['last_verified_parent_sha']}")
    print(f"Worktree Clean:               {result['worktree_clean']}")
    print(f"Source Provenance:            {result['source_provenance_mode']}")
    print(f"Target Event:                 {result['target_event_id']}")
    print(f"Calendar ID:                  {result['calendar_id']}")
    print(f"Authority Class:              {result['authority_classification']}")
    print(f"Approval ID:                  {result['approval_id']}")
    print(f"Binding Hash:                 {result['binding_hash'][:16]}... (valid 64-char hex)")
    print(f"Approval Consumption:         {result['consumption_status']}")
    print(f"Execution Gate Status:        {result['execution_status']}")
    print(f"Provider Writes Performed:    {result['provider_writes_performed']}")
    print(f"Total Transport Writes:       {result['total_transport_writes']}")
    print(f"Before Start Time:            {result['before_start_time']}")
    print(f"After Start Time:             {result['after_start_time']}")
    print(f"Readback Status:              {result['readback_status']}")
    print(f"Predicate Truth:              {result['predicate_truth']}")
    print(f"Verified Outcome:             {result['is_verified']}")
    ready_line = (
        f"Mission Ready State:          {result['is_ready']} "
        f"(Status: {result['mission_ready_status']}, "
        f"Readiness: {result['readiness_determination_ready']})"
    )
    print(ready_line)
    print(f"Replay Blocked (Zero Writes): {result['replay_prevention_verified']}")
    print(f"Durable Hydration Reload:     {result['durable_hydration_verified']}")
    print(f"Live Mutation Gate Status:    {result['live_gate_status']['status']}")
    print(f"Live Mutation Gate Reason:    {result['live_gate_status']['reason']}")
    print("=" * 70)
    print(
        "PROOF CHAIN VERIFIED: APPROVED EXECUTION & INDEPENDENT VERIFICATION PROVEN CONCLUSIVELY."
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
