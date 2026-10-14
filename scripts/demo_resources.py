"""StillDone — Sanitized Demo-Resource Operator CLI Tooling.

Provides a safe, fail-closed CLI for dedicated disposable StillDone demo resources:
1. INSPECT: Read-only inspection of demo calendar and task list (0 writes).
2. SETUP: Idempotent seeding/reset of canonical initial event (0 writes if already set).
3. VERIFY: Independent read-back pre-mission readiness assertion (0 writes).
4. TEARDOWN: Confirmed, narrowly scoped cleanup of disposable demo artifacts.

Laws:
- Default is strictly DRY_RUN / NO_MUTATION.
- Mutations execute ONLY when --execute is explicitly supplied.
- Teardown requires --confirm-teardown CONFIRM_TEARDOWN.
- Primary or default calendars/lists are strictly rejected.
- All outputs and logs are sanitized; external IDs are masked in text.
- Offline fixture mode (--fixture) executes using verified fakes without network calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from stilldone.demo_isolation import DemoResourceScope, DemoScopeError
from stilldone.demo_seeding import (
    DEFAULT_DEMO_CALENDAR_TITLE,
    DEFAULT_DEMO_TASK_LIST_TITLE,
    FakeCalendarSeedTransport,
    FakeTasksSeedTransport,
    create_canonical_event_spec,
)
from stilldone.demo_tooling import (
    DemoArtifactManifest,
    DemoOperationMode,
    execute_demo_resource_operation,
)
from stilldone.domain.provenance import EvidenceProvenance


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="StillDone Dedicated Demo-Resource Operator Tooling",
        prog="python scripts/demo_resources.py",
    )
    parser.add_argument(
        "--mode",
        choices=["inspect", "setup", "verify", "teardown"],
        default="inspect",
        help="Operation mode: 'inspect' (default, read-only), 'setup', 'verify', or 'teardown'",
    )
    parser.add_argument(
        "--calendar-id",
        type=str,
        required=True,
        help="Dedicated demo Calendar ID (must match 'StillDone Demo', not primary)",
    )
    parser.add_argument(
        "--task-list-id",
        type=str,
        required=True,
        help="Dedicated demo Task List ID (must match 'StillDone Demo', not default)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly permit mutations (default is DRY_RUN / NO_MUTATION)",
    )
    parser.add_argument(
        "--confirm-teardown",
        type=str,
        default=None,
        help="Required scope-bound confirmation token ('CONFIRM_TEARDOWN:<cal_id>:<tl_id>')",
    )
    parser.add_argument(
        "--owned-task-id",
        action="append",
        default=[],
        help="Explicitly owned demo task ID for teardown (can specify multiple times)",
    )
    parser.add_argument(
        "--owned-event-id",
        action="append",
        default=[],
        help="Explicitly owned duplicate demo event ID for teardown (can specify multiple times)",
    )
    parser.add_argument(
        "--canonical-event-id",
        type=str,
        default=None,
        help="Explicit canonical demo event ID to preserve during teardown",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        default=True,
        help="Use deterministic in-memory fake transports for offline verification (default: True)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output sanitized result in JSON format",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    mode_map = {
        "inspect": DemoOperationMode.INSPECT,
        "setup": DemoOperationMode.SETUP,
        "verify": DemoOperationMode.VERIFY,
        "teardown": DemoOperationMode.TEARDOWN,
    }
    selected_mode = mode_map[args.mode]

    try:
        scope = DemoResourceScope(
            calendar_id=args.calendar_id,
            task_list_id=args.task_list_id,
        )
    except DemoScopeError as exc:
        err_msg = f"Scope configuration rejected: {exc}"
        if args.json:
            print(json.dumps({"error": err_msg, "status": "REJECTED"}))
        else:
            print(f"ERROR: {err_msg}", file=sys.stderr)
        return 1

    # In fixture mode (default), populate fake transports
    cal_transport: Any
    tasks_transport: Any

    if args.fixture:
        provenance = EvidenceProvenance.FIXTURE
        cal_transport = FakeCalendarSeedTransport()
        cal_transport.add_calendar(scope.calendar_id, DEFAULT_DEMO_CALENDAR_TITLE)

        tasks_transport = FakeTasksSeedTransport()
        tasks_transport.add_task_list(scope.task_list_id, DEFAULT_DEMO_TASK_LIST_TITLE)
    else:
        # Live Google transports require explicit credentials; not executed in offline batch
        print(
            "ERROR: Live Google transports are disabled in offline verification batch. "
            "Use --fixture for deterministic local inspection.",
            file=sys.stderr,
        )
        return 1

    manifest = DemoArtifactManifest(
        owned_task_ids=args.owned_task_id,
        owned_event_ids=args.owned_event_id,
        canonical_event_id=args.canonical_event_id,
        scope=scope,
        is_cli_untrusted=True,
    )

    result = execute_demo_resource_operation(
        scope=scope,
        calendar_transport=cal_transport,
        tasks_transport=tasks_transport,
        mode=selected_mode,
        permit_mutation=args.execute,
        teardown_confirmation=args.confirm_teardown,
        event_spec=create_canonical_event_spec(),
        provenance=provenance,
        manifest=manifest,
    )

    fixture_notice = (
        "NOTE: Running in EPHEMERAL IN-MEMORY FIXTURE mode (in-memory fakes).\n"
        "Independent CLI executions DO NOT share persisted state, and mutations\n"
        "under --execute operate strictly in local memory with 0 calls to real Google APIs."
    )

    if args.json:
        data = result.to_sanitized_dict()
        data["ephemeral_fixture_notice"] = True
        data["fixture_warning"] = fixture_notice
        print(json.dumps(data, indent=2))
    else:
        print("\n" + "=" * 60)
        print("STILLDONE DEMO RESOURCE TOOLING RESULT")
        print("Environment:        EPHEMERAL FIXTURE (in-memory fake; 0 real Google calls)")
        print("=" * 60)
        print(f"Mode:               {result.mode.value}")
        print(f"Status:             {result.status.value}")
        print(f"Provenance:         {result.provenance.value}")
        print("Calendar ID:        ***")
        print("Task List ID:       ***")
        print(f"Writes Performed:   {result.writes_performed}")
        print(f"Read-back Verified: {result.readback_verified}")
        print(f"Success:            {result.is_success}")
        print(f"Details:            {result.details}")
        if result.error_message:
            print(f"Error Message:      {result.error_message}")
        print("-" * 60)
        print(fixture_notice)
        print("=" * 60 + "\n")

    return 0 if result.is_success or result.status.value.startswith("INSPECTED") else 1


if __name__ == "__main__":
    sys.exit(main())
