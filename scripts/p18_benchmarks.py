#!/usr/bin/env python3
"""StillDone P-18 Performance & Cost-Evidence Benchmark Runner.

Executes bounded offline benchmarks for:
- P-18.01: Measure end-to-end mission latency and per-component latency
- P-18.02: Measure MCP transport latency against current Alexa+ requirements
- P-18.03: Measure AWS usage/cost per canonical mission

Usage:
    python scripts/p18_benchmarks.py [--all] [--p18-01] [--p18-02] [--p18-03]
                                     [--json] [--output PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from stilldone.benchmarks import (
    estimate_aws_cost_per_mission,
    measure_mcp_transport_latency,
    run_mission_benchmark,
)


def run_all_benchmarks(
    warmup: int = 2,
    samples: int = 5,
    do_p18_01: bool = True,
    do_p18_02: bool = True,
    do_p18_03: bool = True,
) -> dict[str, Any]:
    """Execute selected P-18 benchmarks sequentially."""
    results: dict[str, Any] = {
        "batch": "P-18.01 -> P-18.03",
        "title": "STILLDONE Performance & Cost-Evidence Batch",
    }

    if do_p18_01:
        mission_res = run_mission_benchmark(warmup_count=warmup, sample_count=samples)
        results["p18_01_mission_latency"] = mission_res.to_dict()

    if do_p18_02:
        mcp_res = asyncio.run(
            measure_mcp_transport_latency(warmup_count=warmup, sample_count=samples)
        )
        results["p18_02_mcp_latency"] = mcp_res.to_dict()

    if do_p18_03:
        cost_res = estimate_aws_cost_per_mission()
        results["p18_03_aws_cost"] = cost_res.to_dict()

    return results


def print_human_report(results: dict[str, Any]) -> None:
    """Print readable text summary of benchmark results."""
    print("=" * 78)
    print("STILLDONE P-18 PERFORMANCE & COST-EVIDENCE BENCHMARK REPORT")
    print("=" * 78)

    if "p18_01_mission_latency" in results:
        p1 = results["p18_01_mission_latency"]
        print("\n--- P-18.01: Mission Latency (End-to-End & Components) ---")
        print(f"Source SHA:        {p1['source_sha']}")
        print(f"Environment:       {p1['environment']}")
        print(f"Provenance:        {p1['provenance']} (Run mode: {p1['run_mode']})")
        print(f"Warmup / Samples:  {p1['warmup_count']} / {p1['sample_count']}")
        e2e = p1["end_to_end"]
        print(
            f"E2E Min / Median / P95 / Max: "
            f"{e2e['min_ms']:.2f}ms / {e2e['median_ms']:.2f}ms / "
            f"{e2e['p95_ms']:.2f}ms / {e2e['max_ms']:.2f}ms"
        )
        print("\nPer-Component Breakdown:")
        print(f"{'Component':<28} {'Status':<10} {'Median (ms)':<12} {'P95 (ms)':<12}")
        print("-" * 64)
        for comp_name, stats in p1["components"].items():
            status = "EXECUTED" if stats.get("was_executed") else "NOT_RUN"
            med = f"{stats.get('median_ms', 0):.2f}" if stats.get("was_executed") else "N/A"
            p95 = f"{stats.get('p95_ms', 0):.2f}" if stats.get("was_executed") else "N/A"
            print(f"{comp_name:<28} {status:<10} {med:<12} {p95:<12}")
        print(f"\nLive Integrations NOT_RUN: {', '.join(p1['live_integrations_not_run'])}")
        print(f"Disclaimer: {p1['non_certification_statement']}")

    if "p18_02_mcp_latency" in results:
        p2 = results["p18_02_mcp_latency"]
        print("\n--- P-18.02: MCP Transport Latency vs Alexa+ Requirements ---")
        req = p2["alexa_plus_requirement"]
        print(
            f"Alexa+ Requirement:      < {req['max_round_trip_ms']:.1f}ms "
            f"({req['verification_status']})"
        )
        print(f"Alexa+ Source:           {req['source']}")
        print(f"Local Headroom Verdict:  {p2['compliance_assessment']['local_headroom']}")
        print(f"Remote Status:           {p2['compliance_assessment']['remote_compliance']}")
        local_ops = p2["current_local_measurements"]["measurements"]
        print("\nLocal In-Process Loopback Measurements:")
        print(f"{'Operation':<20} {'Samples':<8} {'Median (ms)':<12} {'P95 (ms)':<12}")
        print("-" * 54)
        for op_name, stats in local_ops.items():
            print(
                f"{op_name:<20} {stats.get('sample_count', 0):<8} "
                f"{stats.get('median_ms', 0):.2f}ms{'':<6} "
                f"{stats.get('p95_ms', 0):.2f}ms"
            )
        hist_remote = p2["historical_remote_measurements"]
        print(
            f"\nHistorical Remote Echo (P-01.07): {hist_remote['p0107_echo_ms']:.2f}ms "
            f"({hist_remote['provenance']})"
        )
        hist_local = p2["historical_local_measurements"]
        print(
            f"Historical Local Loopback (P-05.07): "
            f"init={hist_local['initialize_p50_ms']:.2f}ms, "
            f"tools={hist_local['tools_list_p50_ms']:.2f}ms, "
            f"status={hist_local['mission_status_p50_ms']:.2f}ms "
            f"({hist_local['provenance']})"
        )
        print(f"Live Remote Transport:            {p2['live_remote_mcp_transport']['status']}")
        print(f"Live Alexa+ Client-to-MCP:        {p2['live_alexa_client_to_mcp']['status']}")

    if "p18_03_aws_cost" in results:
        p3 = results["p18_03_aws_cost"]
        print("\n--- P-18.03: AWS Usage / Cost Per Canonical Mission ---")
        print(
            f"Personal Spend Target:            {p3['billing_boundary']['personal_spend_target']}"
        )
        print(
            f"Actual Personal Spend:            {p3['billing_boundary']['actual_personal_spend']}"
        )
        auth_status = p3["authorization"]["bedrock_invocation_authorized"]
        print(f"Bedrock Invocation Authorized:    {auth_status}")
        est = p3["category_c_pricing_estimates"]
        scenario_usd = Decimal(est["conditional_scenario_total_usd"])
        print(
            f"Conditional Scenario Cost:        ${scenario_usd:.8f} USD (Nova Micro planning only)"
        )
        print(f"Definitive Gross Mission Total:   {est['definitive_gross_total_status']}")
        print(f"Unestimated Components:           {', '.join(est['unestimated_components'])}")
        print("\nCost Breakdown by Service (Pricing-based Estimates):")
        print(f"{'Service':<22} {'Component':<26} {'Quantity':<12} {'Est Cost (USD)':<16}")
        print("-" * 78)
        for item in est["estimates"]:
            cost_str = (
                f"${Decimal(item['estimated_cost_usd']):.8f}"
                if item["estimated_cost_usd"] is not None
                else "NOT_ESTIMABLE"
            )
            qty_str = (
                f"{item['estimated_quantity']:.1f}"
                if item["estimated_quantity"] is not None
                else "N/A"
            )
            print(
                f"{item['service']:<22} {item['component'][:25]:<26} {qty_str:<12} {cost_str:<16}"
            )
        cat_a_status = p3["category_a_real_measured_usage"]["status"]
        print(f"\nCategory A (Real Measured Account Usage): {cat_a_status}")
        print(f"Category D (NOT_OBSERVED Fields Count):   {len(p3['category_d_not_observed'])}")
    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description="StillDone P-18 Performance & Cost Benchmark")
    parser.add_argument(
        "--all", action="store_true", default=True, help="Run all 3 benchmarks (default)"
    )
    parser.add_argument("--p18-01", action="store_true", help="Run P-18.01 only")
    parser.add_argument("--p18-02", action="store_true", help="Run P-18.02 only")
    parser.add_argument("--p18-03", action="store_true", help="Run P-18.03 only")
    parser.add_argument("--warmup", type=int, default=2, help="Warmup iterations (default: 2)")
    parser.add_argument(
        "--samples", type=int, default=5, help="Sample count per benchmark (default: 5)"
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON only")
    parser.add_argument("--output", type=Path, default=None, help="Save JSON output to file")

    args = parser.parse_args()

    specific_selected = args.p18_01 or args.p18_02 or args.p18_03
    do_01 = args.p18_01 or not specific_selected
    do_02 = args.p18_02 or not specific_selected
    do_03 = args.p18_03 or not specific_selected

    results = run_all_benchmarks(
        warmup=args.warmup,
        samples=args.samples,
        do_p18_01=do_01,
        do_p18_02=do_02,
        do_p18_03=do_03,
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_human_report(results)


if __name__ == "__main__":
    main()
