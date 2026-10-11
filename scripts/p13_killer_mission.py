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
    CANONICAL_DEMO_CALENDAR_ID,
    CANONICAL_DEMO_TASK_LIST_ID,
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
) -> int:
    """Execute the canonical killer mission vertical slice."""
    if live:
        # Preflight gate: check credentials and operator consent before creating any environment
        import os
        from pathlib import Path

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
                from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]
                from googleapiclient.discovery import build  # type: ignore[import-untyped]

                resolved_token = (
                    token_path
                    if (isinstance(token_path, Path) and token_path.exists())
                    else creds_path
                )
                if resolved_token and os.path.exists(str(resolved_token)):
                    creds = Credentials.from_authorized_user_file(str(resolved_token))
                    google_creds = creds
                    cal_service = build("calendar", "v3", credentials=creds)
                    tasks_service = build("tasks", "v1", credentials=creds)
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
            calendar_id=CANONICAL_DEMO_CALENDAR_ID,
            task_list_id=CANONICAL_DEMO_TASK_LIST_ID,
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
                print("STILLDONE KILLER MISSION -- LIVE EXECUTION BLOCKED")
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
    runner = KillerMissionSliceRunner(env=env)

    if not as_json:
        print("=================================================================")
        print("STILLDONE CANONICAL KILLER MISSION -- P-13 VERTICAL SLICE PROOF")
        print("=================================================================")
        print(f"Intent: '{runner.intent_text}'")
        print(f"Provenance Mode: {runner.env.provenance.value}")
        print(f"Mission ID: {runner.mission_id}")
        print("-----------------------------------------------------------------")

    outcome = runner.run_full_slice()

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
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
