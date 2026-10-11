"""[FIXTURE EXAMPLE] Wrapping a mock Calendar update tool with mcp-verify.

Demonstrates:
1. Tool executes mutation against in-memory mock store.
2. Middleware intercepts result and queries independent read-back.
3. Verifier deterministically verifies expected predicate.
4. Demonstrates contradiction detection when read-back observes corrupted state.
"""

from __future__ import annotations

from mcp_verify import (
    PredicateOperator,
    VerifiableToolMiddleware,
    VerificationPredicate,
    VerificationStatus,
)


def run_example() -> None:
    middleware = VerifiableToolMiddleware()

    # In-memory external mock database representing Google Calendar
    calendar_database = {
        "evt_school": {
            "title": "Leave for school",
            "start_time": "2026-10-04T07:45:00+00:00",
        }
    }

    # 1. Register verifiable tool contract for calendar.update
    @middleware.register_verifiable_tool(
        tool_name="calendar_update",
        readback_tool_name="calendar_read",
    )
    def extract_calendar_predicate(tool_args: dict, tool_result: dict) -> VerificationPredicate:
        return VerificationPredicate(
            target_id=tool_args["event_id"],
            attribute="start_time",
            operator=PredicateOperator.EQUALS,
            expected_value=tool_args["start_time"],
        )

    # 2. Register readback handler
    @middleware.register_readback_handler("calendar_read")
    def handle_calendar_read(event_id: str) -> dict:
        return calendar_database.get(event_id, {})

    # Tool executor simulating calendar update
    def execute_calendar_update(args: dict) -> dict:
        event_id = args["event_id"]
        # Update database
        calendar_database[event_id]["start_time"] = args["start_time"]
        return {"status": "ok", "updated_event_id": event_id}

    print("=" * 68)
    print(" SCENARIO 1: Successful Mutation & Independent Read-Back Verification")
    print("=" * 68)
    outcome1 = middleware.execute_and_verify(
        tool_name="calendar_update",
        tool_args={
            "event_id": "evt_school",
            "start_time": "2026-10-04T07:30:00+00:00",
        },
        tool_executor=execute_calendar_update,
    )
    print(f"Tool Success:         {outcome1.execution.is_success}")
    print(f"Verification Status:  {outcome1.status.value}")
    print(f"Is Truly Verified:    {outcome1.is_verified}")
    print(f"Observed Read-back:   {outcome1.verification.observed_value}")
    print(f"Expected State:       {outcome1.verification.expected_value}")
    assert outcome1.is_verified is True
    assert outcome1.status == VerificationStatus.VERIFIED

    print("\n" + "=" * 68)
    print(" SCENARIO 2: Read-Back Contradiction (Write 200 OK, but Data Corrupted)")
    print("=" * 68)

    # Corrupted executor returning 200 OK but setting wrong time in DB
    def execute_corrupted_calendar_update(args: dict) -> dict:
        event_id = args["event_id"]
        # Bug: server stores 08:00 instead of 07:30
        calendar_database[event_id]["start_time"] = "2026-10-04T08:00:00+00:00"
        return {"status": "ok", "updated_event_id": event_id}

    outcome2 = middleware.execute_and_verify(
        tool_name="calendar_update",
        tool_args={
            "event_id": "evt_school",
            "start_time": "2026-10-04T07:30:00+00:00",
        },
        tool_executor=execute_corrupted_calendar_update,
    )
    print(f"Tool Success:         {outcome2.execution.is_success} (Raw execute returned 200 OK)")
    print(f"Verification Status:  {outcome2.status.value} (Flagged by mcp-verify!)")
    print(f"Is Truly Verified:    {outcome2.is_verified}")
    print(f"Details:              {outcome2.verification.details}")
    assert outcome2.is_verified is False
    assert outcome2.status == VerificationStatus.CONTRADICTED

    print("\n[SUCCESS] mcp-verify proven: prevented false success on corrupted write.")


if __name__ == "__main__":
    run_example()
