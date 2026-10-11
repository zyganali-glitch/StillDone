#!/usr/bin/env python3
"""StillDone Phase P-14 Failure & Adversarial Campaign Standalone Proof CLI.

Exercises all 8 failure injection & adversarial verification scenarios:
- P-14.01: Provider 5xx/timeout before mutation
- P-14.02: Timeout after mutation but before response
- P-14.03: Read-back mismatch after execute success
- P-14.04: OAuth permission revoked mid-mission
- P-14.05: Model returns malformed/unsupported/over-authorized plan
- P-14.06: Approval replay/mismatch/stale approval
- P-14.07: Evidence tamper/replay/stale receipt
- P-14.08: Duplicate retry stress

Usage:
    python scripts/p14_adversarial_proof.py
    python scripts/p14_adversarial_proof.py --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from stilldone.adversarial import AdversarialCampaignHarness, AdversarialScenarioResult


def main() -> int:
    parser = argparse.ArgumentParser(
        description="StillDone Phase P-14 Failure & Adversarial Campaign Harness"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Emit full results in structured JSON format",
    )
    args = parser.parse_args()

    if args.json_mode:
        logging.getLogger("stilldone").setLevel(logging.ERROR)

    harness = AdversarialCampaignHarness()
    results = harness.run_all()

    all_passed = all(res.status == "PASS" for res in results.values())

    if args.json_mode:
        output_payload = {
            "campaign_phase": "P-14",
            "campaign_name": "Failure & Adversarial Campaign",
            "all_scenarios_passed": all_passed,
            "scenarios_count": len(results),
            "results": {
                task_id: {
                    "task_id": res.task_id,
                    "scenario_name": res.scenario_name,
                    "status": res.status,
                    "provenance": res.provenance,
                    "writes_performed": res.writes_performed,
                    "duplicates_detected": res.duplicates_detected,
                    "invariants_verified": res.invariants_verified,
                    "details": res.details,
                    "is_safe": res.is_safe,
                }
                for task_id, res in results.items()
            },
        }
        print(json.dumps(output_payload, indent=2))
        return 0 if all_passed else 1

    print("================================================================================")
    print(" STILLDONE PHASE P-14 -- FAILURE & ADVERSARIAL CAMPAIGN PROOF HARNESS")
    print("================================================================================")
    print(f"{'Task ID':<10} {'Scenario':<42} {'Status':<8} {'Writes':<8} {'Duplicates'}")
    print("--------------------------------------------------------------------------------")

    for task_id, res in results.items():
        print(
            f"{res.task_id:<10} {res.scenario_name[:40]:<42} {res.status:<8} "
            f"{res.writes_performed:<8} {res.duplicates_detected}"
        )
        print(f"   -> Details: {res.details}")
        print(f"   -> Invariants: {', '.join(res.invariants_verified)}")
        print("--------------------------------------------------------------------------------")

    if all_passed:
        print("[PASS] All 8 Phase P-14 failure & adversarial scenarios verified successfully!")
        return 0
    else:
        print("[FAIL] Some adversarial scenarios failed verification.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
