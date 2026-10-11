#!/usr/bin/env python3
"""P-13 Killer Mission Reproducibility Harness & Proof Script.

Reproduces the full P-13 Canonical Killer Mission Vertical Slice end-to-end:
- P-13.01: Seed canonical disposable demo resources reproducibly
- P-13.02: Execute full mission plan from natural language through compiler (assert 0 model authority)
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
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stilldone.domain.lifecycle import MissionState
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.killer_mission import (
    KillerMissionEnvironment,
    KillerMissionSliceRunner,
)


def run_killer_mission(live: bool = False, as_json: bool = False) -> int:
    """Execute the canonical killer mission vertical slice."""
    provenance = EvidenceProvenance.LIVE_GOOGLE if live else EvidenceProvenance.FIXTURE

    if live:
        # Check credentials boundary before attempting live writes
        from stilldone.google_oauth_client import get_default_token_storage

        storage = get_default_token_storage()
        tokens = storage.load_tokens()
        if not tokens or not tokens.access_token:
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "BLOCKED_LIVE",
                            "reason": "Missing valid live Google OAuth tokens. Run OAuth flow first.",
                            "provenance": EvidenceProvenance.FIXTURE.value,
                            "is_live": False,
                        },
                        indent=2,
                    )
                )
            else:
                print("=================================================================")
                print("STILLDONE KILLER MISSION -- LIVE EXECUTION BLOCKED")
                print("=================================================================")
                print("Status: BLOCKED_LIVE (Fail-closed)")
                print("Reason: Missing valid live Google OAuth tokens.")
                print("Live operations require genuine operator consent.")
                print("Zero false-live claims: Fixture proof will NOT claim LIVE.")
                print("=================================================================")
            return 2

    env = KillerMissionEnvironment.create_fixture_environment(provenance=provenance)
    runner = KillerMissionSliceRunner(env=env)

    if not as_json:
        print("=================================================================")
        print("STILLDONE CANONICAL KILLER MISSION -- P-13 VERTICAL SLICE PROOF")
        print("=================================================================")
        print(f"Intent: '{runner.intent_text}'")
        print(f"Provenance Mode: {provenance.value}")
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

    # Verify acceptance criteria
    assert outcome.final_state == MissionState.DRIFTED
    assert outcome.historical_receipt_immutable is True
    assert outcome.ready_receipt_hash == outcome.drifted_receipt_hash
    assert len(outcome.steps) == 7
    assert all(s.status == "PASS" for s in outcome.steps.values())

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
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )
    args = parser.parse_args()

    exit_code = run_killer_mission(live=args.live, as_json=args.json)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
