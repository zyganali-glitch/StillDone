#!/usr/bin/env python3
"""P-13 Killer Mission Reproducibility Harness & Proof Script.

Reproduces the full P-13 Canonical Killer Mission Vertical Slice end-to-end:
- P-13.01: Seed canonical disposable demo resources reproducibly
- P-13.02: Execute full mission plan through compiler (0 model authority)
- P-13.03: Execute and independently verify Tasks preparation action (REVERSIBLE_AUTO)
- P-13.04: Pause Calendar mutation at approval boundary (REVERSIBLE_APPROVAL_REQUIRED -> NOT_RUN)
- P-13.05: Issue bound approval, execute Calendar update once (writes=1), and read back
- P-13.06: Deterministically compute READY state and issue immutable historical receipt
- P-13.07: Mutate Calendar externally and prove READY -> DRIFTED reconciliation
- P-13.08: Reproduce cleanly from zero state

Usage:
    python scripts/p13_killer_mission.py [--fixture | --live] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys

from stilldone.adapters.calendar import GoogleApiClientCalendarTransport
from stilldone.adapters.tasks import GoogleApiClientTasksTransport
from stilldone.adapters.weather import OpenMeteoHttpTransport
from stilldone.domain.lifecycle import MissionState
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.killer_mission import (
    InvalidEnvironmentConfigurationError,
    KillerMissionEnvironment,
    KillerMissionSliceRunner,
    LiveKillerMissionSliceRunner,
    check_live_preflight,
)
from stilldone.planning.bedrock import BedrockPlannerAdapter


def run_killer_mission(
    live: bool = False,
    as_json: bool = False,
    operator_approved: bool = False,
    source_sha: str | None = None,
    demo_calendar_id: str | None = None,
    demo_task_list_id: str | None = None,
    demo_date: str | None = None,
    calendar_decision: str | None = None,
) -> int:
    """Execute the canonical killer mission vertical slice."""
    if live:
        # Phase A: Zero SDK / Local Gate
        # Validate operator consent, source SHA format, git status, container IDs, date format.
        # MUST halt with 0 SDK imports, 0 network, 0 external calls if any local check fails.
        import os
        import re
        import subprocess
        from datetime import UTC, datetime, timedelta
        from pathlib import Path

        local_blockers: list[str] = []

        if not operator_approved:
            local_blockers.append("Operator approval required for live mode (--operator-approved).")

        if not source_sha or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
            local_blockers.append(
                "A valid 40-character lowercase hex source_sha is required for live execution."
            )

        resolved_cal_id = (
            demo_calendar_id or os.environ.get("STILLDONE_DEMO_CALENDAR_ID") or ""
        ).strip()
        resolved_tasks_id = (
            demo_task_list_id or os.environ.get("STILLDONE_DEMO_TASK_LIST_ID") or ""
        ).strip()

        disallowed_containers = {"primary", "default", "@default", "tasks", ""}
        if not resolved_cal_id or resolved_cal_id.lower() in disallowed_containers:
            local_blockers.append(
                "Dedicated demo calendar container ID required "
                f"(cannot be empty, primary, default, or @default; got: '{resolved_cal_id}')."
            )
        if not resolved_tasks_id or resolved_tasks_id.lower() in disallowed_containers:
            local_blockers.append(
                "Dedicated demo task list container ID required "
                f"(cannot be empty, primary, default, or @default; got: '{resolved_tasks_id}')."
            )

        resolved_date = demo_date
        if resolved_date is not None:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", resolved_date):
                local_blockers.append(
                    f"demo_date must be formatted YYYY-MM-DD; got: '{resolved_date}'."
                )
            else:
                try:
                    datetime.strptime(resolved_date, "%Y-%m-%d")
                except ValueError:
                    local_blockers.append(
                        f"demo_date '{resolved_date}' is an impossible calendar date."
                    )
        else:
            resolved_date = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%d")

        if calendar_decision in ("APPROVE",):
            local_blockers.append(
                "Pre-authorized --calendar-decision APPROVE is prohibited in live mode. "
                "Human approval must occur after the exact PendingApproval has been produced."
            )

        # Git checks (fail-closed)
        try:
            head_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.PIPE, text=True
            ).strip()
            origin_main_sha = subprocess.check_output(
                ["git", "rev-parse", "origin/main"], stderr=subprocess.PIPE, text=True
            ).strip()
            status_output = subprocess.check_output(
                ["git", "status", "--porcelain"], stderr=subprocess.PIPE, text=True
            ).strip()

            if source_sha and head_sha != source_sha:
                local_blockers.append(
                    f"HEAD SHA ({head_sha}) does not match expected source_sha ({source_sha})."
                )
            if source_sha and origin_main_sha != source_sha:
                local_blockers.append(
                    f"origin/main SHA ({origin_main_sha}) does not match expected "
                    f"source_sha ({source_sha})."
                )
            if head_sha != origin_main_sha:
                local_blockers.append(
                    f"Local HEAD ({head_sha}) does not match origin/main ({origin_main_sha})."
                )
            if status_output:
                local_blockers.append(
                    "Working tree has uncommitted modifications; "
                    "live execution requires a clean working tree."
                )
        except Exception as e:
            local_blockers.append(f"Git repository integrity check failed: {e}")

        if local_blockers:
            blocker_details = "; ".join(local_blockers)
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "BLOCKED_LIVE",
                            "phase": "PHASE_A_LOCAL_GATE",
                            "reason": blocker_details,
                            "provenance": EvidenceProvenance.FIXTURE.value,
                            "is_live": False,
                            "writes_performed": 0,
                            "blocker_reasons": local_blockers,
                        },
                        indent=2,
                    )
                )
            else:
                print("=================================================================")
                print("STILLDONE KILLER MISSION -- LIVE EXECUTION BLOCKED (PHASE A)")
                print("=================================================================")
                print("Status: BLOCKED_LIVE (Fail-closed)")
                print(f"Reason: {blocker_details}")
                print("Live operations require genuine operator consent and clean git source.")
                print("0 SDK calls; 0 writes performed; 0 approvals consumed.")
                print("=================================================================")
            return 2

        # Phase B: External Preflight & Runner
        from stilldone.demo_isolation import DemoResourceScope

        token_path = os.environ.get("GOOGLE_TOKEN_PATH") or (
            Path.home() / ".stilldone" / "token.json"
        )
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        has_google_token = (
            bool(creds_path and os.path.exists(creds_path))
            or (isinstance(token_path, Path) and token_path.exists())
            or (isinstance(token_path, str) and os.path.exists(token_path))
        )
        google_creds = None
        cal_transport: GoogleApiClientCalendarTransport | None = None
        tasks_transport: GoogleApiClientTasksTransport | None = None

        if has_google_token:
            try:
                import importlib

                creds_mod = importlib.import_module("google.oauth2.credentials")
                discovery_mod = importlib.import_module("googleapiclient.discovery")

                resolved_token = (
                    token_path
                    if (isinstance(token_path, Path) and token_path.exists())
                    else creds_path
                )
                if resolved_token and os.path.exists(str(resolved_token)):
                    credentials_cls = creds_mod.Credentials
                    build_fn = discovery_mod.build
                    creds = credentials_cls.from_authorized_user_file(str(resolved_token))
                    google_creds = creds
                    cal_service = build_fn("calendar", "v3", credentials=creds)
                    tasks_service = build_fn("tasks", "v1", credentials=creds)
                    cal_transport = GoogleApiClientCalendarTransport(service=cal_service)
                    tasks_transport = GoogleApiClientTasksTransport(service=tasks_service)
            except Exception:
                google_creds = None
                cal_transport = None
                tasks_transport = None

        # AWS Bedrock detection
        aws_credentials_available = False
        bedrock_planner: BedrockPlannerAdapter | None = None
        try:
            import boto3  # type: ignore[import-untyped]

            session = boto3.Session()
            if session.get_credentials() is not None:
                aws_credentials_available = True
                bedrock_client = session.client("bedrock-runtime", region_name="us-east-1")
                bedrock_planner = BedrockPlannerAdapter(client=bedrock_client)
        except Exception:
            aws_credentials_available = False
            bedrock_planner = None

        weather_transport = OpenMeteoHttpTransport()

        scope = DemoResourceScope(
            calendar_id=resolved_cal_id,
            task_list_id=resolved_tasks_id,
        )
        preflight = check_live_preflight(
            scope=scope,
            operator_approved=operator_approved,
            source_sha=source_sha,
            google_credentials=google_creds,
            aws_credentials_available=aws_credentials_available,
            calendar_transport=cal_transport,
            tasks_transport=tasks_transport,
            weather_transport=weather_transport,
            bedrock_planner_available=(bedrock_planner is not None),
        )

        if not preflight.is_ready:
            blocker_details = "; ".join(preflight.blocker_reasons)
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "BLOCKED_LIVE",
                            "phase": "PHASE_B_PREFLIGHT_GATE",
                            "reason": blocker_details,
                            "provenance": EvidenceProvenance.FIXTURE.value,
                            "is_live": False,
                            "writes_performed": 0,
                            "blocker_reasons": preflight.blocker_reasons,
                        },
                        indent=2,
                    )
                )
            else:
                print("=================================================================")
                print("STILLDONE KILLER MISSION -- LIVE EXECUTION BLOCKED (PHASE B)")
                print("=================================================================")
                print("Status: BLOCKED_LIVE (Fail-closed)")
                print(f"Reason: {blocker_details}")
                print("Live operations require genuine operator consent ($0.00 spend law).")
                print("Zero false-live claims: Fixture proof will NOT claim LIVE.")
                print("0 writes performed; 0 approvals consumed.")
                print("=================================================================")
            return 2

        # If preflight passed, construct canonical live environment and runner
        live_env = KillerMissionEnvironment.create_live_environment(
            scope=scope,
            calendar_transport=cal_transport,
            tasks_transport=tasks_transport,
            weather_transport=weather_transport,
        )
        runner = LiveKillerMissionSliceRunner(
            env=live_env,
            operator_approved=operator_approved,
            source_sha=source_sha,
            bedrock_planner=bedrock_planner,
            aws_credentials_available=aws_credentials_available,
            google_credentials=google_creds,
            demo_date=resolved_date,
            calendar_decision=calendar_decision,
        )
        outcome = runner.run_full_slice()
        if as_json:
            print(json.dumps(outcome.to_dict(), indent=2))
        else:
            print("=================================================================")
            print("STILLDONE KILLER MISSION -- LIVE EXECUTION COMPLETE")
            print("=================================================================")
            print(f"Final State: {outcome.final_state.value}")
            print(f"Total Writes: {outcome.total_writes_performed}")
        return 0

    # Fixture mode: strict closed-world fixture environment with zero live connectivity
    if live:
        raise InvalidEnvironmentConfigurationError(
            "Live mode cannot use fixture environment; strict closed-world boundary enforced."
        )
    env = KillerMissionEnvironment.create_fixture_environment()
    fixture_runner = KillerMissionSliceRunner(env=env)

    if not as_json:
        print("=================================================================")
        print("STILLDONE CANONICAL KILLER MISSION -- P-13 VERTICAL SLICE PROOF")
        print("=================================================================")
        print(f"Intent: '{fixture_runner.intent_text}'")
        print(f"Provenance Mode: {fixture_runner.env.provenance.value}")
        print(f"Mission ID: {fixture_runner.mission_id}")
        print("-----------------------------------------------------------------")

    outcome = fixture_runner.run_full_slice()

    if as_json:
        print(json.dumps(outcome.to_dict(), indent=2))
        return 0

    for task_id, step in outcome.steps.items():
        status_symbol = "PASS" if step.status == "PASS" else "FAIL"
        print(f"[{status_symbol}] {task_id}: {step.step_name} -> {step.status}")
        print(f"    Writes: {step.writes_performed} | Verified: {step.is_verified}")
        print(f"    Details: {step.details}")
        if step.receipt_hash:
            print(f"    Receipt Hash: {step.receipt_hash[:16]}...")
        print()

    print("-----------------------------------------------------------------")
    print(f"Final Mission State: {outcome.final_state.value}")
    print(f"Historical Receipt Hash (READY):   {outcome.ready_receipt_hash}")
    print(f"Reconciled Receipt Hash (DRIFTED): {outcome.drifted_receipt_hash}")
    print(f"Receipt Immutability Preserved:    {outcome.historical_receipt_immutable}")
    print(f"Total Mutations Executed:          {outcome.total_writes_performed}")
    print("=================================================================")

    # Explicit deterministic acceptance validation (optimization-safe under python -O)
    acceptance_failures: list[str] = []
    if outcome.final_state != MissionState.DRIFTED:
        acceptance_failures.append(f"Expected final state DRIFTED, got {outcome.final_state.value}")
    if not outcome.historical_receipt_immutable:
        acceptance_failures.append("Historical receipt immutability violated")
    if outcome.ready_receipt_hash != outcome.drifted_receipt_hash:
        acceptance_failures.append("Receipt hash mismatch between READY and DRIFTED")
    if len(outcome.steps) != 7:
        acceptance_failures.append(f"Expected 7 steps, got {len(outcome.steps)}")
    failed_steps = [s.task_id for s in outcome.steps.values() if s.status != "PASS"]
    if failed_steps:
        acceptance_failures.append(f"Steps did not PASS: {', '.join(failed_steps)}")

    if acceptance_failures:
        for failure in acceptance_failures:
            print(f"ACCEPTANCE FAILURE: {failure}", file=sys.stderr)
        return 1

    print("ALL 7 P-13 ACCEPTANCE CRITERIA RIGIDLY VERIFIED.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="P-13 Killer Mission Reproducibility Script")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Attempt live Google execution (requires authorized credentials; fails closed)",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        default=True,
        help="Execute deterministic fixture slice (default)",
    )
    parser.add_argument(
        "--operator-approved",
        action="store_true",
        default=False,
        help="Explicit operator authorization for live execution",
    )
    parser.add_argument(
        "--source-sha",
        type=str,
        default=None,
        help="Exact 40-character source SHA binding for live preflight",
    )
    parser.add_argument(
        "--demo-calendar-id",
        type=str,
        default=None,
        help="Dedicated demo calendar container ID (not primary, default, or @default)",
    )
    parser.add_argument(
        "--demo-task-list-id",
        type=str,
        default=None,
        help="Dedicated demo task list container ID (not primary, default, or @default)",
    )
    parser.add_argument(
        "--demo-date",
        type=str,
        default=None,
        help="Target date for the mission in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--calendar-decision",
        type=str,
        default=None,
        choices=["APPROVE", "REJECT", "PENDING", "NONE"],
        help="Explicit operator decision for Calendar mutation approval",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )
    args = parser.parse_args()

    exit_code = run_killer_mission(
        live=args.live,
        as_json=args.json,
        operator_approved=args.operator_approved,
        source_sha=args.source_sha,
        demo_calendar_id=args.demo_calendar_id,
        demo_task_list_id=args.demo_task_list_id,
        demo_date=args.demo_date,
        calendar_decision=args.calendar_decision,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
