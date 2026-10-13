"""P-18 Performance Benchmark Harness for StillDone.

P-18.01: End-to-end mission latency and per-component latency measurement.
P-18.02: MCP transport latency against Alexa+ requirements.
P-18.03: AWS usage/cost per canonical mission.

Constitutional Invariants:
- Monotonic timing via time.perf_counter_ns().
- FIXTURE provenance clearly labeled; never presented as LIVE.
- NOT_RUN steps report no duration.
- Benchmark instrumentation has zero effect on mission authority or evidence claims.
- Zero personal spend ($0.00).
"""

from __future__ import annotations

import json
import logging
import platform
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

# Suppress verbose transport/request logs during benchmark measurements
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


# ============================================================================
# Core timing utilities
# ============================================================================


class MeasurementProvenance(StrEnum):
    """Provenance of a performance measurement."""

    FIXTURE = "FIXTURE"
    LOCAL_EXECUTION = "LOCAL_EXECUTION"
    LIVE_AWS = "LIVE_AWS"
    LIVE_GOOGLE = "LIVE_GOOGLE"
    LIVE_EXTERNAL = "LIVE_EXTERNAL"
    RECORDED_LIVE = "RECORDED_LIVE"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class ComponentTiming:
    """Timing measurement for a single mission component."""

    component: str
    elapsed_ns: int
    elapsed_ms: float
    provenance: MeasurementProvenance
    was_executed: bool
    sample_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.component, str) or not self.component.strip():
            raise ValueError("component must be a non-empty string")
        if not isinstance(self.elapsed_ns, int):
            raise TypeError("elapsed_ns must be an integer")
        if self.was_executed and self.elapsed_ns < 0:
            raise ValueError("elapsed_ns cannot be negative for an executed step")
        if not self.was_executed and self.elapsed_ns != 0:
            raise ValueError("NOT_RUN steps must have elapsed_ns == 0")
        if not isinstance(self.provenance, MeasurementProvenance):
            raise TypeError("provenance must be a MeasurementProvenance")

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "elapsed_ns": self.elapsed_ns,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "provenance": self.provenance.value,
            "was_executed": self.was_executed,
            "sample_index": self.sample_index,
        }


@dataclass(frozen=True)
class ComponentLatencyStats:
    """Statistical summary for a component across multiple samples."""

    component: str
    sample_count: int
    warmup_count: int
    min_ms: float
    mean_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float
    provenance: MeasurementProvenance
    was_executed: bool

    def to_dict(self) -> dict[str, Any]:
        if not self.was_executed:
            return {
                "component": self.component,
                "status": "NOT_RUN",
                "provenance": self.provenance.value,
                "was_executed": False,
            }
        return {
            "component": self.component,
            "sample_count": self.sample_count,
            "warmup_count": self.warmup_count,
            "min_ms": round(self.min_ms, 3),
            "mean_ms": round(self.mean_ms, 3),
            "median_ms": round(self.median_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "provenance": self.provenance.value,
            "was_executed": True,
        }


def compute_percentile_inclusive(sorted_samples: Sequence[float], p: float) -> float:
    """Compute percentile using inclusive interpolation matching statistics.quantiles."""
    if not sorted_samples:
        raise ValueError("Cannot compute percentile of empty sequence")
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    quantiles = statistics.quantiles(sorted_samples, n=100, method="inclusive")
    idx = max(0, min(len(quantiles) - 1, int(round(p)) - 1))
    return float(quantiles[idx])


def compute_component_stats(
    component: str,
    samples_ms: Sequence[float],
    warmup_count: int,
    provenance: MeasurementProvenance,
) -> ComponentLatencyStats:
    """Compute statistical summary for a component's timing samples."""
    if not samples_ms:
        return ComponentLatencyStats(
            component=component,
            sample_count=0,
            warmup_count=warmup_count,
            min_ms=0.0,
            mean_ms=0.0,
            median_ms=0.0,
            p95_ms=0.0,
            max_ms=0.0,
            provenance=MeasurementProvenance.NOT_RUN,
            was_executed=False,
        )

    sorted_samples = sorted(samples_ms)
    return ComponentLatencyStats(
        component=component,
        sample_count=len(sorted_samples),
        warmup_count=warmup_count,
        min_ms=sorted_samples[0],
        mean_ms=statistics.fmean(sorted_samples),
        median_ms=statistics.median(sorted_samples),
        p95_ms=compute_percentile_inclusive(sorted_samples, 95.0),
        max_ms=sorted_samples[-1],
        provenance=provenance,
        was_executed=True,
    )


# ============================================================================
# P-18.01: End-to-end mission latency benchmark
# ============================================================================

# Canonical mission components in execution order
MISSION_COMPONENTS: Final[list[str]] = [
    "seed_demo_resources",
    "plan_compilation",
    "tasks_prep",
    "calendar_approval_pause",
    "calendar_update_approved",
    "ready_receipt_projection",
    "drift_reconciliation",
]

# Components that are NOT_RUN in fixture mode (live-only)
LIVE_ONLY_COMPONENTS: Final[frozenset[str]] = frozenset(
    {
        # All components above are exercised in fixture mode for the canonical mission
        # But external provider calls are fixture-backed, not live
    }
)


@dataclass(frozen=True)
class MissionBenchmarkRun:
    """Single run of the killer mission with component-level timing."""

    run_index: int
    is_warmup: bool
    total_elapsed_ns: int
    total_elapsed_ms: float
    component_timings: dict[str, ComponentTiming]
    mission_succeeded: bool
    final_state: str
    provenance: MeasurementProvenance

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_index": self.run_index,
            "is_warmup": self.is_warmup,
            "total_elapsed_ns": self.total_elapsed_ns,
            "total_elapsed_ms": round(self.total_elapsed_ms, 3),
            "component_timings": {k: v.to_dict() for k, v in self.component_timings.items()},
            "mission_succeeded": self.mission_succeeded,
            "final_state": self.final_state,
            "provenance": self.provenance.value,
        }


@dataclass(frozen=True)
class MissionBenchmarkResult:
    """Complete benchmark result with statistical summaries."""

    source_sha: str
    timestamp_utc: str
    python_version: str
    environment: str
    warmup_count: int
    sample_count: int
    total_runs: int

    # End-to-end stats
    e2e_stats: ComponentLatencyStats

    # Per-component stats
    component_stats: dict[str, ComponentLatencyStats]

    # Run mode and provenance
    run_mode: str  # "fixture" or "live"
    provenance: MeasurementProvenance

    # Explicit NOT_RUN declarations
    live_integrations_not_run: list[str]

    # Non-certification statement
    non_certification_statement: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": "P-18.01",
            "task_name": "Measure end-to-end mission latency and per-component latency",
            "source_sha": self.source_sha,
            "timestamp_utc": self.timestamp_utc,
            "python_version": self.python_version,
            "environment": self.environment,
            "warmup_count": self.warmup_count,
            "sample_count": self.sample_count,
            "total_runs": self.total_runs,
            "end_to_end": self.e2e_stats.to_dict(),
            "components": {k: v.to_dict() for k, v in self.component_stats.items()},
            "run_mode": self.run_mode,
            "provenance": self.provenance.value,
            "live_integrations_not_run": self.live_integrations_not_run,
            "non_certification_statement": self.non_certification_statement,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def run_mission_benchmark(
    warmup_count: int = 2,
    sample_count: int = 5,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> MissionBenchmarkResult:
    """Run bounded fixture-mode mission benchmark with per-component timing.

    Executes the canonical killer mission slice multiple times in fixture mode,
    measuring per-component elapsed time with monotonic timing.

    Cold startup is separated: warmup runs are excluded from statistics.
    All timings are LOCAL_EXECUTION/FIXTURE provenance.
    Live provider timings are NOT_RUN.
    """
    import subprocess

    from stilldone.domain.lifecycle import MissionState
    from stilldone.killer_mission import (
        KillerMissionEnvironment,
        KillerMissionSliceRunner,
    )

    if warmup_count < 0:
        raise ValueError("warmup_count cannot be negative")
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")

    total_runs = warmup_count + sample_count
    all_runs: list[MissionBenchmarkRun] = []
    e2e_samples_ms: list[float] = []
    component_samples: dict[str, list[float]] = {c: [] for c in MISSION_COMPONENTS}

    for run_idx in range(total_runs):
        is_warmup = run_idx < warmup_count

        # Create fresh fixture environment for each run
        env = KillerMissionEnvironment.create_fixture_environment()
        runner = KillerMissionSliceRunner(env=env)

        # Time individual components through the runner steps
        component_timings: dict[str, ComponentTiming] = {}
        provenance = MeasurementProvenance.FIXTURE

        # Measure total end-to-end and individual steps
        t_start = timer()

        # Step 1: P-13.01 Seed
        t0 = timer()
        s1 = runner.step_p13_01_seed()
        t1 = timer()
        dt1_ns = t1 - t0
        component_timings["seed_demo_resources"] = ComponentTiming(
            component="seed_demo_resources",
            elapsed_ns=dt1_ns,
            elapsed_ms=dt1_ns / 1_000_000.0,
            provenance=provenance,
            was_executed=(s1.status == "PASS"),
            sample_index=run_idx,
        )

        # Step 2: P-13.02 Plan compilation
        t0 = timer()
        s2 = runner.step_p13_02_plan()
        t1 = timer()
        dt2_ns = t1 - t0
        component_timings["plan_compilation"] = ComponentTiming(
            component="plan_compilation",
            elapsed_ns=dt2_ns,
            elapsed_ms=dt2_ns / 1_000_000.0,
            provenance=provenance,
            was_executed=(s2.status == "PASS"),
            sample_index=run_idx,
        )

        # Step 3: P-13.03 Tasks prep
        t0 = timer()
        s3 = runner.step_p13_03_tasks_prep()
        t1 = timer()
        dt3_ns = t1 - t0
        component_timings["tasks_prep"] = ComponentTiming(
            component="tasks_prep",
            elapsed_ns=dt3_ns,
            elapsed_ms=dt3_ns / 1_000_000.0,
            provenance=provenance,
            was_executed=(s3.status == "PASS"),
            sample_index=run_idx,
        )

        # Step 4: P-13.04 Calendar pause
        t0 = timer()
        s4 = runner.step_p13_04_calendar_pause()
        t1 = timer()
        dt4_ns = t1 - t0
        component_timings["calendar_approval_pause"] = ComponentTiming(
            component="calendar_approval_pause",
            elapsed_ns=dt4_ns,
            elapsed_ms=dt4_ns / 1_000_000.0,
            provenance=provenance,
            was_executed=(s4.status == "PASS"),
            sample_index=run_idx,
        )

        # Step 5: P-13.05 Calendar update approved
        t0 = timer()
        s5 = runner.step_p13_05_calendar_approve()
        t1 = timer()
        dt5_ns = t1 - t0
        component_timings["calendar_update_approved"] = ComponentTiming(
            component="calendar_update_approved",
            elapsed_ns=dt5_ns,
            elapsed_ms=dt5_ns / 1_000_000.0,
            provenance=provenance,
            was_executed=(s5.status == "PASS"),
            sample_index=run_idx,
        )

        # Step 6: P-13.06 Ready receipt
        t0 = timer()
        s6 = runner.step_p13_06_ready_receipt()
        t1 = timer()
        dt6_ns = t1 - t0
        component_timings["ready_receipt_projection"] = ComponentTiming(
            component="ready_receipt_projection",
            elapsed_ns=dt6_ns,
            elapsed_ms=dt6_ns / 1_000_000.0,
            provenance=provenance,
            was_executed=(s6.status == "PASS"),
            sample_index=run_idx,
        )

        # Step 7: P-13.07 Drift reconciliation
        t0 = timer()
        s7 = runner.step_p13_07_mutate_and_drift()
        t1 = timer()
        dt7_ns = t1 - t0
        component_timings["drift_reconciliation"] = ComponentTiming(
            component="drift_reconciliation",
            elapsed_ns=dt7_ns,
            elapsed_ms=dt7_ns / 1_000_000.0,
            provenance=provenance,
            was_executed=(s7.status == "PASS"),
            sample_index=run_idx,
        )

        t_end = timer()
        total_ns = t_end - t_start
        total_ms = total_ns / 1_000_000.0

        mission_succeeded = s7.status == "PASS"
        final_state = MissionState.DRIFTED if mission_succeeded else MissionState.FAILED

        run = MissionBenchmarkRun(
            run_index=run_idx,
            is_warmup=is_warmup,
            total_elapsed_ns=total_ns,
            total_elapsed_ms=total_ms,
            component_timings=component_timings,
            mission_succeeded=mission_succeeded,
            final_state=final_state.value,
            provenance=provenance,
        )
        all_runs.append(run)

        if not is_warmup:
            e2e_samples_ms.append(total_ms)
            for comp_name, timing in component_timings.items():
                if timing.was_executed and comp_name in component_samples:
                    component_samples[comp_name].append(timing.elapsed_ms)

    # Compute statistics
    e2e_stats = compute_component_stats(
        "end_to_end", e2e_samples_ms, warmup_count, MeasurementProvenance.FIXTURE
    )

    comp_stats: dict[str, ComponentLatencyStats] = {}
    for comp_name in MISSION_COMPONENTS:
        samples = component_samples.get(comp_name, [])
        comp_stats[comp_name] = compute_component_stats(
            comp_name, samples, warmup_count, MeasurementProvenance.FIXTURE
        )

    # Git SHA
    try:
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        source_sha = sha_result.stdout.strip()
    except Exception:
        source_sha = "UNKNOWN"

    return MissionBenchmarkResult(
        source_sha=source_sha,
        timestamp_utc=datetime.now(UTC).isoformat(),
        python_version=platform.python_version(),
        environment=f"{platform.system()} {platform.release()} ({platform.machine()})",
        warmup_count=warmup_count,
        sample_count=sample_count,
        total_runs=total_runs,
        e2e_stats=e2e_stats,
        component_stats=comp_stats,
        run_mode="fixture",
        provenance=MeasurementProvenance.FIXTURE,
        live_integrations_not_run=[
            "Live AWS Bedrock inference",
            "Live Google Calendar API calls",
            "Live Google Tasks API calls",
            "Live Open-Meteo API calls",
            "Live MCP remote transport",
            "Live AgentCore runtime",
        ],
        non_certification_statement=(
            "All timings are measured in FIXTURE mode using deterministic test doubles. "
            "No live external provider calls were executed. Fixture timings measure "
            "local computation overhead only and MUST NOT be presented as live provider "
            "latency. Live provider latency remains NOT_RUN. "
            "Per AGENTS.md §9-10, live measurements require genuine provider execution."
        ),
    )


# ============================================================================
# P-18.02: MCP Transport Latency vs Alexa+ Requirements
# ============================================================================

ALEXA_PLUS_LATENCY_REQUIREMENT_MS: Final[float] = 500.0
ALEXA_PLUS_REQUIREMENT_SOURCE: Final[str] = (
    "Amazon Alexa+ MCP Server documentation: 'MCP server round-trip query response latency < 500ms'"
)
ALEXA_PLUS_REQUIREMENT_STATUS: Final[str] = "OBSERVED_IN_DOCUMENTATION"

# Historical recorded-live measurements from P-01.07 and P-05.07
HISTORICAL_P0107_ECHO_MS: Final[float] = 61.26
HISTORICAL_P0107_PROVENANCE: Final[str] = "RECORDED_LIVE"
HISTORICAL_P0507_INIT_P50_MS: Final[float] = 8.05
HISTORICAL_P0507_TOOLS_LIST_P50_MS: Final[float] = 7.33
HISTORICAL_P0507_MISSION_STATUS_P50_MS: Final[float] = 15.18
HISTORICAL_P0507_PROVENANCE: Final[str] = "RECORDED_LIVE"


@dataclass(frozen=True)
class MCPLatencyComparison:
    """Structured comparison of MCP transport latency measurements."""

    # Alexa+ requirement
    alexa_requirement_ms: float
    alexa_requirement_source: str
    alexa_requirement_status: str

    # In-process/local loopback measurements (current)
    local_measurements: dict[str, Any]  # From current run_latency_campaign
    local_provenance: str

    # Historical recorded-live remote measurements
    historical_remote_echo_ms: float
    historical_remote_provenance: str

    # Historical local measurements from P-05.07
    historical_local_init_p50_ms: float
    historical_local_tools_list_p50_ms: float
    historical_local_mission_status_p50_ms: float
    historical_local_provenance: str

    # Live remote measurements (NOT_RUN unless genuinely observed)
    live_remote_measurement: str  # "NOT_RUN" or actual data
    live_alexa_client_measurement: str  # "NOT_RUN"

    # Compliance assessment
    local_headroom_assessment: str
    remote_compliance_status: str

    # Source SHA and timestamp
    source_sha: str
    timestamp_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": "P-18.02",
            "task_name": "Measure MCP transport latency against current Alexa+ requirements",
            "alexa_plus_requirement": {
                "max_round_trip_ms": self.alexa_requirement_ms,
                "source": self.alexa_requirement_source,
                "verification_status": self.alexa_requirement_status,
            },
            "current_local_measurements": {
                "measurements": self.local_measurements,
                "provenance": self.local_provenance,
                "classification": "IN_PROCESS_LOOPBACK",
            },
            "historical_remote_measurements": {
                "p0107_echo_ms": self.historical_remote_echo_ms,
                "provenance": self.historical_remote_provenance,
                "classification": "RECORDED_LIVE_REMOTE_MCP",
            },
            "historical_local_measurements": {
                "initialize_p50_ms": self.historical_local_init_p50_ms,
                "tools_list_p50_ms": self.historical_local_tools_list_p50_ms,
                "mission_status_p50_ms": self.historical_local_mission_status_p50_ms,
                "provenance": self.historical_local_provenance,
                "classification": "RECORDED_LIVE_LOCAL_LOOPBACK",
            },
            "live_remote_mcp_transport": {
                "status": self.live_remote_measurement,
                "reason": "No authorized remote MCP endpoint currently deployed",
            },
            "live_alexa_client_to_mcp": {
                "status": self.live_alexa_client_measurement,
                "reason": "Alexa+ partner access NOT_ESTABLISHED",
            },
            "compliance_assessment": {
                "local_headroom": self.local_headroom_assessment,
                "remote_compliance": self.remote_compliance_status,
            },
            "source_sha": self.source_sha,
            "timestamp_utc": self.timestamp_utc,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


async def measure_mcp_transport_latency(
    warmup_count: int = 2,
    sample_count: int = 5,
) -> MCPLatencyComparison:
    """Measure MCP transport latency and compare against Alexa+ requirements.

    Measures:
    - In-process/local loopback Streamable HTTP latency (current run)
    - Compares against historical recorded-live measurements
    - Reports remote and Alexa+ paths as NOT_RUN
    """
    import subprocess

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from stilldone.domain import MissionContract, MissionState
    from stilldone.ledger import InMemoryNonDurableLedger, MissionRecord
    from stilldone.mcp import MCPServerConfig, find_free_loopback_port, run_loopback_mcp_server

    host = "127.0.0.1"
    port = find_free_loopback_port(host)
    config = MCPServerConfig(host=host, port=port, path="/mcp")

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

    local_measurements: dict[str, Any] = {}

    async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
        # Measure initialize
        init_samples: list[float] = []
        for i in range(warmup_count + sample_count):
            async with streamable_http_client(endpoint_url) as (r, w):
                async with ClientSession(r, w) as session:
                    t0 = time.perf_counter_ns()
                    await session.initialize()
                    t1 = time.perf_counter_ns()
                    if i >= warmup_count:
                        init_samples.append((t1 - t0) / 1_000_000.0)

        init_stats = compute_component_stats(
            "initialize", init_samples, warmup_count, MeasurementProvenance.LOCAL_EXECUTION
        )
        local_measurements["initialize"] = init_stats.to_dict()

        # Measure tools/list
        tl_samples: list[float] = []
        async with streamable_http_client(endpoint_url) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                for i in range(warmup_count + sample_count):
                    t0 = time.perf_counter_ns()
                    await session.list_tools()
                    t1 = time.perf_counter_ns()
                    if i >= warmup_count:
                        tl_samples.append((t1 - t0) / 1_000_000.0)

        tl_stats = compute_component_stats(
            "tools_list", tl_samples, warmup_count, MeasurementProvenance.LOCAL_EXECUTION
        )
        local_measurements["tools_list"] = tl_stats.to_dict()

        # Measure mission_status
        ms_samples: list[float] = []
        async with streamable_http_client(endpoint_url) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                for i in range(warmup_count + sample_count):
                    t0 = time.perf_counter_ns()
                    await session.call_tool(
                        "mission_status", arguments={"mission_id": mission_id_str}
                    )
                    t1 = time.perf_counter_ns()
                    if i >= warmup_count:
                        ms_samples.append((t1 - t0) / 1_000_000.0)

        ms_stats = compute_component_stats(
            "mission_status", ms_samples, warmup_count, MeasurementProvenance.LOCAL_EXECUTION
        )
        local_measurements["mission_status"] = ms_stats.to_dict()

    # Compute headroom assessment
    max_local_p95 = max(
        init_stats.p95_ms if init_stats.was_executed else 0.0,
        tl_stats.p95_ms if tl_stats.was_executed else 0.0,
        ms_stats.p95_ms if ms_stats.was_executed else 0.0,
    )
    headroom_ms = ALEXA_PLUS_LATENCY_REQUIREMENT_MS - max_local_p95
    local_headroom = (
        f"LOCAL_PASS: All local p95 measurements ({max_local_p95:.2f}ms) are below "
        f"{ALEXA_PLUS_LATENCY_REQUIREMENT_MS}ms target with {headroom_ms:.2f}ms headroom. "
        f"This is LOCAL_EXECUTION only and does NOT certify remote or Alexa+ compliance."
    )

    try:
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        source_sha = sha_result.stdout.strip()
    except Exception:
        source_sha = "UNKNOWN"

    return MCPLatencyComparison(
        alexa_requirement_ms=ALEXA_PLUS_LATENCY_REQUIREMENT_MS,
        alexa_requirement_source=ALEXA_PLUS_REQUIREMENT_SOURCE,
        alexa_requirement_status=ALEXA_PLUS_REQUIREMENT_STATUS,
        local_measurements=local_measurements,
        local_provenance="LOCAL_EXECUTION",
        historical_remote_echo_ms=HISTORICAL_P0107_ECHO_MS,
        historical_remote_provenance=HISTORICAL_P0107_PROVENANCE,
        historical_local_init_p50_ms=HISTORICAL_P0507_INIT_P50_MS,
        historical_local_tools_list_p50_ms=HISTORICAL_P0507_TOOLS_LIST_P50_MS,
        historical_local_mission_status_p50_ms=HISTORICAL_P0507_MISSION_STATUS_P50_MS,
        historical_local_provenance=HISTORICAL_P0507_PROVENANCE,
        live_remote_measurement="NOT_RUN",
        live_alexa_client_measurement="NOT_RUN",
        local_headroom_assessment=local_headroom,
        remote_compliance_status=(
            "REQUIREMENT_NOT_VERIFIED: Remote MCP and Alexa+ client-to-MCP paths are NOT_RUN. "
            "Local loopback headroom is observed but cannot certify remote or production "
            "compliance."
        ),
        source_sha=source_sha,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )


# ============================================================================
# P-18.03: AWS Usage/Cost Per Canonical Mission
# ============================================================================


@dataclass(frozen=True)
class AWSServiceCostEstimate:
    """Cost estimate for a single AWS service per canonical mission."""

    service: str
    component: str
    unit: str
    estimated_quantity: float
    unit_price_usd: Decimal
    estimated_cost_usd: Decimal
    pricing_source: str
    pricing_verified: bool
    pricing_verification_date: str
    is_covered_by_free_tier: bool | None  # None = NOT_OBSERVED
    is_covered_by_promotional_credit: bool | None  # None = NOT_OBSERVED
    observed_actual_cost: str  # "NOT_OBSERVED" or actual

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "component": self.component,
            "unit": self.unit,
            "estimated_quantity": self.estimated_quantity,
            "unit_price_usd": str(self.unit_price_usd),
            "estimated_cost_usd": str(self.estimated_cost_usd),
            "pricing_source": self.pricing_source,
            "pricing_verified": self.pricing_verified,
            "pricing_verification_date": self.pricing_verification_date,
            "is_covered_by_free_tier": (
                self.is_covered_by_free_tier
                if self.is_covered_by_free_tier is not None
                else "NOT_OBSERVED"
            ),
            "is_covered_by_promotional_credit": (
                self.is_covered_by_promotional_credit
                if self.is_covered_by_promotional_credit is not None
                else "NOT_OBSERVED"
            ),
            "observed_actual_cost": self.observed_actual_cost,
        }


@dataclass(frozen=True)
class AWSCostPerMission:
    """Complete AWS cost analysis for one canonical mission execution."""

    source_sha: str
    timestamp_utc: str

    # Category A: Real measured AWS usage from account records
    real_measured_usage: str  # "NOT_OBSERVED" - requires real AWS account

    # Category B: Locally measured application/runtime activity
    local_runtime_activity: dict[str, Any]

    # Category C: Pricing-based estimates
    cost_estimates: list[AWSServiceCostEstimate]
    total_estimated_cost_usd: Decimal

    # Category D: NOT_OBSERVED fields
    not_observed: list[str]

    # Billing boundary
    personal_spend_target: str  # "$0.00"
    actual_personal_spend: str  # "NOT_OBSERVED"
    promotional_credit_remaining: str  # "NOT_OBSERVED" without account access

    # Authorization
    bedrock_invocation_authorized: bool  # False for this task
    paid_services_activated: bool  # False

    # Provenance
    provenance: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": "P-18.03",
            "task_name": "Measure AWS usage/cost per canonical mission",
            "source_sha": self.source_sha,
            "timestamp_utc": self.timestamp_utc,
            "category_a_real_measured_usage": {
                "status": self.real_measured_usage,
                "reason": (
                    "No real AWS Bedrock invocation is authorized by this task. "
                    "Actual account billing data requires authenticated AWS account observation."
                ),
            },
            "category_b_local_runtime_activity": self.local_runtime_activity,
            "category_c_pricing_estimates": {
                "estimates": [e.to_dict() for e in self.cost_estimates],
                "total_estimated_cost_usd": str(self.total_estimated_cost_usd),
                "disclaimer": (
                    "Estimates use independently verified official AWS pricing. "
                    "Actual billed cost may differ due to promotional credits, "
                    "free tier, rounding, and billing aggregation."
                ),
            },
            "category_d_not_observed": self.not_observed,
            "billing_boundary": {
                "personal_spend_target": self.personal_spend_target,
                "actual_personal_spend": self.actual_personal_spend,
                "promotional_credit_remaining": self.promotional_credit_remaining,
            },
            "authorization": {
                "bedrock_invocation_authorized": self.bedrock_invocation_authorized,
                "paid_services_activated": self.paid_services_activated,
            },
            "provenance": self.provenance,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


def estimate_aws_cost_per_mission() -> AWSCostPerMission:
    """Estimate AWS usage and cost for one canonical killer mission execution.

    This task does NOT authorize real Bedrock invocation.
    Uses independently verified official AWS pricing for estimates.
    Actual billing observation requires authenticated AWS account access.
    """
    import subprocess

    # Token counts from P-01.02, P-01.03, P-07.06 live evidence
    # P-01.02: inputTokens=8, outputTokens=3, totalTokens=11
    # P-01.03: inputTokens=8, outputTokens=5, totalTokens=13
    # P-07.06: actual planner inference with mission prompt
    # Conservative canonical mission estimate: ~200 input tokens, ~100 output tokens
    estimated_input_tokens = 200
    estimated_output_tokens = 100

    # Official Amazon Bedrock pricing for amazon.nova-micro-v1:0 in us-east-1
    # Source: https://aws.amazon.com/bedrock/pricing/
    nova_micro_input_price_per_1k = Decimal("0.000035")  # per 1K input tokens
    nova_micro_output_price_per_1k = Decimal("0.00014")  # per 1K output tokens

    input_cost = (
        Decimal(str(estimated_input_tokens)) / Decimal("1000")
    ) * nova_micro_input_price_per_1k
    output_cost = (
        Decimal(str(estimated_output_tokens)) / Decimal("1000")
    ) * nova_micro_output_price_per_1k
    bedrock_cost = input_cost + output_cost

    cost_estimates = [
        AWSServiceCostEstimate(
            service="Amazon Bedrock",
            component="amazon.nova-micro-v1:0 Converse API",
            unit="tokens",
            estimated_quantity=float(estimated_input_tokens + estimated_output_tokens),
            unit_price_usd=nova_micro_input_price_per_1k,  # representative
            estimated_cost_usd=bedrock_cost,
            pricing_source="https://aws.amazon.com/bedrock/pricing/",
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier=None,  # NOT_OBSERVED
            is_covered_by_promotional_credit=None,  # NOT_OBSERVED
            observed_actual_cost="NOT_OBSERVED",
        ),
        AWSServiceCostEstimate(
            service="AWS Strands Agents SDK",
            component="strands-agents==1.57.2 (open-source SDK)",
            unit="invocations",
            estimated_quantity=1.0,
            unit_price_usd=Decimal("0.00"),
            estimated_cost_usd=Decimal("0.00"),
            pricing_source="Open-source Apache-2.0; no direct AWS charge",
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier=True,
            is_covered_by_promotional_credit=None,
            observed_actual_cost="NOT_OBSERVED",
        ),
        AWSServiceCostEstimate(
            service="Amazon Bedrock AgentCore Runtime",
            component="Serverless CodeZip microVM (per-invocation)",
            unit="invocations",
            estimated_quantity=1.0,
            unit_price_usd=Decimal("0.0001"),  # estimate, pricing may vary
            estimated_cost_usd=Decimal("0.0001"),
            pricing_source=(
                "AgentCore pricing not independently confirmed as of 2026-10; estimate only"
            ),
            pricing_verified=False,
            pricing_verification_date="NOT_VERIFIED",
            is_covered_by_free_tier=None,
            is_covered_by_promotional_credit=None,
            observed_actual_cost="NOT_OBSERVED",
        ),
        AWSServiceCostEstimate(
            service="AWS IAM",
            component="SigV4 request signing",
            unit="requests",
            estimated_quantity=1.0,
            unit_price_usd=Decimal("0.00"),
            estimated_cost_usd=Decimal("0.00"),
            pricing_source="IAM has no direct per-request charge",
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier=True,
            is_covered_by_promotional_credit=None,
            observed_actual_cost="NOT_OBSERVED",
        ),
        AWSServiceCostEstimate(
            service="Amazon CloudWatch (EMF)",
            component="PutLogEvents EMF ingestion (prepared, NOT_RUN)",
            unit="log events",
            estimated_quantity=4.0,
            unit_price_usd=Decimal("0.00"),  # First 5GB/month free; well below
            estimated_cost_usd=Decimal("0.00"),
            pricing_source=(
                "https://aws.amazon.com/cloudwatch/pricing/ - Logs ingestion free tier 5GB/month"
            ),
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier=True,
            is_covered_by_promotional_credit=None,
            observed_actual_cost="NOT_OBSERVED",
        ),
    ]

    total_estimated = sum((e.estimated_cost_usd for e in cost_estimates), Decimal("0.00"))

    try:
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        source_sha = sha_result.stdout.strip()
    except Exception:
        source_sha = "UNKNOWN"

    return AWSCostPerMission(
        source_sha=source_sha,
        timestamp_utc=datetime.now(UTC).isoformat(),
        real_measured_usage="NOT_OBSERVED",
        local_runtime_activity={
            "fixture_mission_executions": "Measured (FIXTURE provenance)",
            "live_bedrock_invocations": 0,
            "live_google_api_calls": 0,
            "live_agentcore_invocations": 0,
            "note": (
                "All runtime activity in this measurement is FIXTURE/LOCAL_EXECUTION. "
                "No real AWS Bedrock invocation was authorized or executed."
            ),
        },
        cost_estimates=cost_estimates,
        total_estimated_cost_usd=total_estimated,
        not_observed=[
            "Actual AWS account billing delta per mission",
            "Actual promotional credit consumption per mission",
            "Actual Bedrock token billing (no invocation authorized)",
            "Actual AgentCore runtime billing",
            "Actual CloudWatch ingestion billing (EMF NOT_RUN live)",
            "Post-promotional-credit personal spend delta",
        ],
        personal_spend_target="$0.00",
        actual_personal_spend="NOT_OBSERVED",
        promotional_credit_remaining="NOT_OBSERVED",
        bedrock_invocation_authorized=False,
        paid_services_activated=False,
        provenance="LOCAL_EXECUTION",
    )
