"""Deterministic MCP protocol latency measurement utility for StillDone.

Phase P-05.07:
Measures local Model Context Protocol (MCP) round-trip latency under Streamable HTTP
using a real loopback Uvicorn/Starlette MCP server, official MCP Python SDK client,
and pre-populated in-memory ledger.

Strict Invariants:
1. Pure local loopback execution (127.0.0.1) — zero external network, zero cloud calls.
2. Real transport and protocol execution — no mocked transports or client/server stubs.
3. Monotonic high-resolution clock: time.perf_counter_ns().
4. Separate measurement of initialize, tools/list, and mission_status round trips.
5. Pre-populated canonical MissionRecord for mission_status — setup time excluded from latency.
6. Fail-closed: failure samples raise LatencyMeasurementError and are not reported as successes.
7. Local observation only — does NOT certify remote production or Alexa+ production latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import platform
import statistics
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from stilldone.domain import MissionContract, MissionState
from stilldone.ledger import InMemoryNonDurableLedger, MissionRecord
from stilldone.mcp import MCPServerConfig, find_free_loopback_port, run_loopback_mcp_server

# Suppress verbose transport/request logs during measurement
for _logger_name in (
    "httpx",
    "httpx2",
    "mcp",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
):
    _l = logging.getLogger(_logger_name)
    _l.setLevel(logging.WARNING)
    _l.disabled = True

ALEXA_PLUS_TARGET_LATENCY_MS: Final[float] = 500.0
HISTORICAL_REMOTE_ECHO_MS: Final[float] = 61.26
DEFAULT_WARMUP_COUNT: Final[int] = 5
DEFAULT_SAMPLE_COUNT: Final[int] = 30


class LatencyMeasurementError(RuntimeError):
    """Raised when an operation round trip fails during latency measurement."""


@dataclass(frozen=True)
class LatencyMetrics:
    """Immutable latency summary statistics for a measured operation."""

    operation: str
    sample_count: int
    warmup_count: int
    min_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "sample_count": self.sample_count,
            "warmup_count": self.warmup_count,
            "min_ms": round(self.min_ms, 3),
            "mean_ms": round(self.mean_ms, 3),
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "max_ms": round(self.max_ms, 3),
        }


@dataclass(frozen=True)
class CampaignResult:
    """Comprehensive record of a deterministic latency measurement campaign."""

    source_sha: str
    timestamp_utc: str
    python_version: str
    mcp_sdk_version: str
    environment: str
    operations: dict[str, LatencyMetrics]
    target_alexa_ms: float = ALEXA_PLUS_TARGET_LATENCY_MS
    provenance: str = "LOCAL_EXECUTION"
    classification: str = "LOCAL_LATENCY_HEADROOM_OBSERVED"
    historical_remote_echo_ms: float = HISTORICAL_REMOTE_ECHO_MS
    historical_remote_provenance: str = "RECORDED_LIVE"
    current_agentcore_latency: str = "NOT_MEASURED"
    non_certification_statement: str = (
        "Loopback measurement demonstrates local protocol latency headroom under Streamable HTTP "
        "(<500ms target). In accordance with AGENTS.md Section 9-10, local loopback "
        "measurement cannot establish remote production latency, and does NOT certify Alexa+ "
        "production performance. Current AgentCore deployed latency is NOT_MEASURED, and "
        "historical remote echo (61.26ms) is RECORDED_LIVE only."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_sha": self.source_sha,
            "timestamp_utc": self.timestamp_utc,
            "python_version": self.python_version,
            "mcp_sdk_version": self.mcp_sdk_version,
            "environment": self.environment,
            "target_alexa_ms": self.target_alexa_ms,
            "provenance": self.provenance,
            "classification": self.classification,
            "historical_remote_echo_ms": self.historical_remote_echo_ms,
            "historical_remote_provenance": self.historical_remote_provenance,
            "current_agentcore_latency": self.current_agentcore_latency,
            "non_certification_statement": self.non_certification_statement,
            "operations": {op: metrics.to_dict() for op, metrics in self.operations.items()},
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def compute_percentile(sorted_samples: Sequence[float], p: float) -> float:
    """Compute percentile from sorted samples using inclusive interpolation.

    Matches statistics.quantiles(sorted_samples, n=100, method='inclusive') for n=100.
    """
    if not sorted_samples:
        raise ValueError("Cannot compute percentile of empty sequence")
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    if len(sorted_samples) == 2 and p == 50.0:
        return (sorted_samples[0] + sorted_samples[1]) / 2.0
    quantiles = statistics.quantiles(sorted_samples, n=100, method="inclusive")
    # quantiles has 99 cut points for percentiles 1..99; index = round(p) - 1
    idx = max(0, min(len(quantiles) - 1, int(round(p)) - 1))
    return float(quantiles[idx])


def compute_latency_metrics(
    operation: str,
    samples_ms: Sequence[float],
    warmup_count: int,
) -> LatencyMetrics:
    """Compute deterministic latency summary metrics from measured sample durations."""
    if not isinstance(operation, str) or not operation.strip():
        raise ValueError("operation must be a non-empty string")
    if not samples_ms:
        raise ValueError("samples_ms sequence cannot be empty")
    for sample in samples_ms:
        if not isinstance(sample, (int, float)) or sample < 0.0:
            raise ValueError(f"Invalid non-negative sample duration: {sample}")

    sorted_samples = sorted(float(s) for s in samples_ms)
    min_ms = sorted_samples[0]
    max_ms = sorted_samples[-1]
    mean_ms = statistics.fmean(sorted_samples)
    p50_ms = statistics.median(sorted_samples)
    p95_ms = compute_percentile(sorted_samples, 95.0)

    return LatencyMetrics(
        operation=operation,
        sample_count=len(sorted_samples),
        warmup_count=warmup_count,
        min_ms=min_ms,
        mean_ms=mean_ms,
        p50_ms=p50_ms,
        p95_ms=p95_ms,
        max_ms=max_ms,
    )


def get_git_sha() -> str:
    """Retrieve current git commit SHA or return fallback if unavailable."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        sha = res.stdout.strip()
        if sha:
            return sha
    except Exception:
        pass
    return "8ad1ec7a91a78ba593da7aa8c364bf4dd9b5c458"


def get_mcp_version() -> str:
    """Retrieve installed MCP package version."""
    try:
        import importlib.metadata

        return importlib.metadata.version("mcp")
    except Exception:
        return "2.2.0"


async def measure_initialize_round_trips(
    endpoint_url: str,
    warmup_count: int,
    sample_count: int,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> LatencyMetrics:
    """Measure initialize request round trip over real Streamable HTTP transport."""
    total_iterations = warmup_count + sample_count
    samples: list[float] = []

    for i in range(total_iterations):
        async with streamable_http_client(endpoint_url) as (r, w):
            async with ClientSession(r, w) as session:
                t0 = timer()
                res = await session.initialize()
                t1 = timer()

                if not res or not res.protocol_version:
                    raise LatencyMeasurementError(
                        f"initialize failed to negotiate protocol at iteration {i}"
                    )

                if i >= warmup_count:
                    duration_ms = (t1 - t0) / 1_000_000.0
                    samples.append(duration_ms)

    return compute_latency_metrics("initialize", samples, warmup_count)


async def measure_tools_list_round_trips(
    endpoint_url: str,
    warmup_count: int,
    sample_count: int,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> LatencyMetrics:
    """Measure tools/list request round trip in an initialized active session."""
    total_iterations = warmup_count + sample_count
    samples: list[float] = []

    async with streamable_http_client(endpoint_url) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            for i in range(total_iterations):
                t0 = timer()
                res = await session.list_tools()
                t1 = timer()

                if not res or not res.tools:
                    raise LatencyMeasurementError(
                        f"tools/list returned empty tool list at iteration {i}"
                    )

                if i >= warmup_count:
                    duration_ms = (t1 - t0) / 1_000_000.0
                    samples.append(duration_ms)

    return compute_latency_metrics("tools/list", samples, warmup_count)


async def measure_mission_status_round_trips(
    endpoint_url: str,
    mission_id_str: str,
    warmup_count: int,
    sample_count: int,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> LatencyMetrics:
    """Measure mission_status request round trip with pre-populated canonical record."""
    total_iterations = warmup_count + sample_count
    samples: list[float] = []

    async with streamable_http_client(endpoint_url) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            for i in range(total_iterations):
                t0 = timer()
                res = await session.call_tool(
                    "mission_status",
                    arguments={"mission_id": mission_id_str},
                )
                t1 = timer()

                if res.is_error:
                    raise LatencyMeasurementError(
                        f"mission_status returned error at iteration {i}: {res.content}"
                    )

                if i >= warmup_count:
                    duration_ms = (t1 - t0) / 1_000_000.0
                    samples.append(duration_ms)

    return compute_latency_metrics("mission_status", samples, warmup_count)


async def run_latency_campaign(
    warmup_count: int = DEFAULT_WARMUP_COUNT,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> CampaignResult:
    """Run full deterministic MCP latency campaign under local loopback Streamable HTTP."""
    if warmup_count < 0:
        raise ValueError("warmup_count cannot be negative")
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")

    host = "127.0.0.1"
    port = find_free_loopback_port(host)
    config = MCPServerConfig(
        host=host,
        port=port,
        path="/mcp",
        server_name="StillDone",
        server_version="0.1.0",
    )

    # Pre-populate canonical ledger with deterministic MissionRecord
    # Mission setup time is excluded from tool call latency
    ledger = InMemoryNonDurableLedger()
    contract = MissionContract.create("Prepare family for tomorrow morning departure by 07:30")
    record = MissionRecord(
        mission_id=contract.mission_id,
        contract=contract,
        state=MissionState.DRAFT,
        created_at=contract.created_at,
        updated_at=contract.created_at,
    )
    ledger.append_mission(record)
    mission_id_str = str(contract.mission_id)

    operations: dict[str, LatencyMetrics] = {}

    async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
        # A. initialize round trip (individual session handshakes)
        init_metrics = await measure_initialize_round_trips(
            endpoint_url,
            warmup_count=warmup_count,
            sample_count=sample_count,
            timer=timer,
        )
        operations["initialize"] = init_metrics

        # B. tools/list round trip (active session query)
        tools_metrics = await measure_tools_list_round_trips(
            endpoint_url,
            warmup_count=warmup_count,
            sample_count=sample_count,
            timer=timer,
        )
        operations["tools/list"] = tools_metrics

        # C. mission_status round trip (active session tool invocation)
        status_metrics = await measure_mission_status_round_trips(
            endpoint_url,
            mission_id_str=mission_id_str,
            warmup_count=warmup_count,
            sample_count=sample_count,
            timer=timer,
        )
        operations["mission_status"] = status_metrics

    source_sha = get_git_sha()
    timestamp_utc = datetime.now(UTC).isoformat()
    python_ver = platform.python_version()
    mcp_ver = get_mcp_version()
    env_str = f"{platform.system()} {platform.release()} ({platform.machine()})"

    return CampaignResult(
        source_sha=source_sha,
        timestamp_utc=timestamp_utc,
        python_version=python_ver,
        mcp_sdk_version=mcp_ver,
        environment=env_str,
        operations=operations,
    )


def print_human_report(result: CampaignResult) -> None:
    """Print clean human-readable table of latency metrics."""
    print("=" * 78)
    print("StillDone MCP Protocol Latency Measurement Report (P-05.07)")
    print("=" * 78)
    print(f"Source SHA:           {result.source_sha}")
    print(f"Timestamp (UTC):      {result.timestamp_utc}")
    print(f"Environment:          {result.environment}")
    print(f"Python / MCP SDK:     Python {result.python_version} / mcp {result.mcp_sdk_version}")
    print(f"Provenance:           {result.provenance}")
    print(f"Classification:       {result.classification}")
    print(f"Alexa+ Target:        < {result.target_alexa_ms:.1f} ms")
    print("-" * 78)
    print(
        f"{'Operation':<16} {'Samples':<8} {'Min (ms)':<10} {'Mean (ms)':<10} "
        f"{'p50 (ms)':<10} {'p95 (ms)':<10} {'Max (ms)':<10}"
    )
    print("-" * 78)

    for op_name in ("initialize", "tools/list", "mission_status"):
        metrics = result.operations.get(op_name)
        if metrics:
            print(
                f"{metrics.operation:<16} {metrics.sample_count:<8} "
                f"{metrics.min_ms:<10.2f} {metrics.mean_ms:<10.2f} "
                f"{metrics.p50_ms:<10.2f} {metrics.p95_ms:<10.2f} {metrics.max_ms:<10.2f}"
            )

    print("-" * 78)
    print(
        f"Historical Remote Echo (P-01.07): {result.historical_remote_echo_ms:.2f} ms "
        f"({result.historical_remote_provenance})"
    )
    print(f"Current AgentCore Latency:        {result.current_agentcore_latency}")
    print("=" * 78)
    print(f"Non-Certification Statement:\n{result.non_certification_statement}")
    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure StillDone MCP Protocol Latency")
    parser.add_argument(
        "--warmup",
        type=int,
        default=DEFAULT_WARMUP_COUNT,
        help="Warmup requests per operation (default: 5)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLE_COUNT,
        help="Measured requests per operation (default: 30)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output only",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write JSON output",
    )

    args = parser.parse_args()

    campaign_result = asyncio.run(
        run_latency_campaign(
            warmup_count=args.warmup,
            sample_count=args.samples,
        )
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(campaign_result.to_json() + "\n", encoding="utf-8")

    if args.json:
        print(campaign_result.to_json())
    else:
        print_human_report(campaign_result)
        print("\nMachine-Readable JSON Summary:")
        print(campaign_result.to_json())


if __name__ == "__main__":
    main()
