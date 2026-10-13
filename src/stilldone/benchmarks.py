"""P-18 Performance Benchmark Harness for StillDone.

P-18.01: End-to-end mission latency and per-component latency measurement.
P-18.02: MCP transport latency against Alexa+ requirements.
P-18.03: AWS usage/cost per canonical mission.

Constitutional Invariants:
- Monotonic timing via time.perf_counter_ns().
- FIXTURE provenance clearly labeled; never presented as LIVE.
- NOT_RUN steps report strictly zero duration (0 ns).
- Benchmark instrumentation has zero effect on mission authority or evidence claims.
- Zero personal spend ($0.00).
- Module import does not alter any global logger configurations.
- Unexecuted or blocked steps are never labeled as successfully executed provider work.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import platform
import statistics
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

# ============================================================================
# Scoped Benchmark Logging Management (Defect A Repair)
# ============================================================================


@contextlib.contextmanager
def scoped_benchmark_logging_suppression(
    logger_names: Sequence[str] = (
        "httpx",
        "httpx2",
        "mcp",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
    ),
) -> Iterator[None]:
    """Temporarily suppress verbose transport loggers during benchmarks, restoring on exit.

    Importing this module does NOT alter logger configuration. Scoped suppression
    is strictly localized to execution contexts that opt in and fully restored in finally.
    """
    snapshots: list[tuple[logging.Logger, int, bool, bool]] = []
    for name in logger_names:
        lgr = logging.getLogger(name)
        snapshots.append((lgr, lgr.level, lgr.disabled, lgr.propagate))
        lgr.setLevel(logging.WARNING)
        lgr.disabled = True
    try:
        yield
    finally:
        for lgr, old_level, old_disabled, old_propagate in snapshots:
            lgr.setLevel(old_level)
            lgr.disabled = old_disabled
            lgr.propagate = old_propagate


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


class StepExecutionStatus(StrEnum):
    """Lifecycle execution status of a timed step."""

    PASS = "PASS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    BLOCKED_LIVE = "BLOCKED_LIVE"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class ComponentTiming:
    """Timing measurement for a single mission component.

    Invariants:
    - NOT_RUN operations MUST have elapsed_ns == 0, elapsed_ms == 0.0,
      was_executed == False, was_invoked == False.
    - FAILED / BLOCKED operations have was_invoked == True, was_executed == False, and
      may record local elapsed processing time (elapsed_ns >= 0), but MUST NOT be labeled
      as successfully executed provider work.
    - PASS operations have was_invoked == True, was_executed == True, elapsed_ns >= 0.
    - elapsed_ms must be mathematically consistent with elapsed_ns.
    """

    component: str
    elapsed_ns: int
    elapsed_ms: float
    provenance: MeasurementProvenance
    was_executed: bool
    sample_index: int
    status: str = "PASS"
    was_invoked: bool = True
    error_category: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.component, str) or not self.component.strip():
            raise ValueError("component must be a non-empty string")
        if not isinstance(self.elapsed_ns, int):
            raise TypeError("elapsed_ns must be an integer")
        if self.elapsed_ns < 0:
            raise ValueError("elapsed_ns cannot be negative for an executed step")
        if not isinstance(self.provenance, MeasurementProvenance):
            raise TypeError("provenance must be a MeasurementProvenance")

        # Auto-align status/was_invoked if defaulted
        if self.provenance == MeasurementProvenance.NOT_RUN:
            object.__setattr__(self, "status", StepExecutionStatus.NOT_RUN.value)
            object.__setattr__(self, "was_invoked", False)
        elif not self.was_executed and self.elapsed_ns == 0 and self.status == "PASS":
            object.__setattr__(self, "status", StepExecutionStatus.NOT_RUN.value)
            object.__setattr__(self, "was_invoked", False)
        elif not self.was_executed and self.elapsed_ns > 0 and self.status == "PASS":
            object.__setattr__(self, "status", StepExecutionStatus.FAILED.value)
            object.__setattr__(self, "was_invoked", True)

        if self.status == StepExecutionStatus.NOT_RUN.value:
            if self.elapsed_ns != 0 or self.elapsed_ms != 0.0:
                raise ValueError("NOT_RUN steps must have elapsed_ns == 0 and elapsed_ms == 0.0")
            if self.was_executed:
                raise ValueError(
                    "NOT_RUN steps cannot be marked as successfully executed "
                    "(was_executed must be False)"
                )
            if self.was_invoked:
                raise ValueError("NOT_RUN steps cannot be marked as invoked")
            if self.provenance != MeasurementProvenance.NOT_RUN:
                raise ValueError("NOT_RUN steps must have provenance=MeasurementProvenance.NOT_RUN")
        elif self.status in (
            StepExecutionStatus.FAILED.value,
            StepExecutionStatus.BLOCKED.value,
            StepExecutionStatus.BLOCKED_LIVE.value,
        ):
            if not self.was_invoked:
                raise ValueError(f"{self.status} steps must have was_invoked=True")
            if self.was_executed:
                raise ValueError(
                    f"{self.status} steps cannot be labeled as successfully executed provider work"
                )
        elif self.status == StepExecutionStatus.PASS.value:
            if not self.was_invoked:
                raise ValueError("PASS steps must have was_invoked=True")
            if not self.was_executed:
                raise ValueError("PASS steps must have was_executed=True")
        else:
            raise ValueError(f"Unknown execution status: {self.status}")

        # Enforce consistency between elapsed_ms and elapsed_ns for non-NOT_RUN steps
        expected_ms = self.elapsed_ns / 1_000_000.0
        if not math.isclose(self.elapsed_ms, expected_ms, abs_tol=1e-5):
            raise ValueError(
                f"elapsed_ms ({self.elapsed_ms}) is inconsistent with "
                f"elapsed_ns ({self.elapsed_ns})"
            )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "component": self.component,
            "status": self.status,
            "elapsed_ns": self.elapsed_ns,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "provenance": self.provenance.value,
            "was_invoked": self.was_invoked,
            "was_executed": self.was_executed,
            "sample_index": self.sample_index,
        }
        if self.error_category is not None:
            d["error_category"] = self.error_category
        return d


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
    status: str = "PASS"
    attempted_sample_count: int = 0
    successful_sample_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status,
            "provenance": self.provenance.value,
            "was_executed": self.was_executed,
            "attempted_sample_count": self.attempted_sample_count,
            "successful_sample_count": self.successful_sample_count,
            "sample_count": self.sample_count,
            "warmup_count": self.warmup_count,
            "min_ms": round(self.min_ms, 3),
            "mean_ms": round(self.mean_ms, 3),
            "median_ms": round(self.median_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "max_ms": round(self.max_ms, 3),
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
    attempted_count: int | None = None,
    status: str | None = None,
) -> ComponentLatencyStats:
    """Compute statistical summary for a component's timing samples."""
    if not samples_ms:
        resolved_attempted = attempted_count if attempted_count is not None else 0
        resolved_status = (
            status
            if status is not None
            else (
                StepExecutionStatus.NOT_RUN.value
                if resolved_attempted == 0
                else StepExecutionStatus.FAILED.value
            )
        )
        resolved_provenance = (
            MeasurementProvenance.NOT_RUN
            if resolved_status == StepExecutionStatus.NOT_RUN.value
            else provenance
        )
        return ComponentLatencyStats(
            component=component,
            sample_count=0,
            warmup_count=warmup_count,
            min_ms=0.0,
            mean_ms=0.0,
            median_ms=0.0,
            p95_ms=0.0,
            max_ms=0.0,
            provenance=resolved_provenance,
            was_executed=False,
            status=resolved_status,
            attempted_sample_count=resolved_attempted,
            successful_sample_count=0,
        )

    sorted_samples = sorted(samples_ms)
    successful_count = len(sorted_samples)
    resolved_attempted = attempted_count if attempted_count is not None else successful_count
    if status is not None:
        resolved_status = status
    elif successful_count == resolved_attempted:
        resolved_status = StepExecutionStatus.PASS.value
    else:
        resolved_status = "PARTIAL_SUCCESS"

    return ComponentLatencyStats(
        component=component,
        sample_count=successful_count,
        warmup_count=warmup_count,
        min_ms=sorted_samples[0],
        mean_ms=statistics.fmean(sorted_samples),
        median_ms=statistics.median(sorted_samples),
        p95_ms=compute_percentile_inclusive(sorted_samples, 95.0),
        max_ms=sorted_samples[-1],
        provenance=provenance,
        was_executed=True,
        status=resolved_status,
        attempted_sample_count=resolved_attempted,
        successful_sample_count=successful_count,
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
        # External provider calls are fixture-backed, not live
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

    # Complete execution outcome for all runs
    runs: list[MissionBenchmarkRun] = field(default_factory=list)

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
            "runs": [r.to_dict() for r in self.runs],
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

    Disclosure:
    Timings are aggregate lifecycle-step fixture timings. They do NOT separately measure
    real Bedrock inference, provider network latency, independent read-back, or cold-start time.
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

        component_timings: dict[str, ComponentTiming] = {}
        provenance = MeasurementProvenance.FIXTURE

        step_definitions: list[tuple[str, Callable[[], Any]]] = [
            ("seed_demo_resources", runner.step_p13_01_seed),
            ("plan_compilation", runner.step_p13_02_plan),
            ("tasks_prep", runner.step_p13_03_tasks_prep),
            ("calendar_approval_pause", runner.step_p13_04_calendar_pause),
            ("calendar_update_approved", runner.step_p13_05_calendar_approve),
            ("ready_receipt_projection", runner.step_p13_06_ready_receipt),
            ("drift_reconciliation", runner.step_p13_07_mutate_and_drift),
        ]

        abort_sequence = False
        t_start = timer()

        for comp_name, step_fn in step_definitions:
            if abort_sequence:
                # Step was NOT invoked: strictly 0 duration, NOT_RUN provenance
                component_timings[comp_name] = ComponentTiming(
                    component=comp_name,
                    elapsed_ns=0,
                    elapsed_ms=0.0,
                    provenance=MeasurementProvenance.NOT_RUN,
                    was_executed=False,
                    sample_index=run_idx,
                    status=StepExecutionStatus.NOT_RUN.value,
                    was_invoked=False,
                )
                continue

            t0 = timer()
            step_exception_occurred = False
            step_result = None
            try:
                step_result = step_fn()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                step_exception_occurred = True

            t1 = timer()
            dt_ns = t1 - t0
            dt_ms = dt_ns / 1_000_000.0

            if step_exception_occurred:
                abort_sequence = True
                component_timings[comp_name] = ComponentTiming(
                    component=comp_name,
                    elapsed_ns=dt_ns,
                    elapsed_ms=dt_ms,
                    provenance=MeasurementProvenance.LOCAL_EXECUTION,
                    was_executed=False,
                    sample_index=run_idx,
                    status=StepExecutionStatus.FAILED.value,
                    was_invoked=True,
                    error_category="STEP_EXECUTION_EXCEPTION",
                )
                continue

            step_status = getattr(step_result, "status", "UNKNOWN")
            if step_status == "PASS":
                component_timings[comp_name] = ComponentTiming(
                    component=comp_name,
                    elapsed_ns=dt_ns,
                    elapsed_ms=dt_ms,
                    provenance=provenance,
                    was_executed=True,
                    sample_index=run_idx,
                    status=StepExecutionStatus.PASS.value,
                    was_invoked=True,
                )
            elif step_status in ("BLOCKED", "BLOCKED_LIVE"):
                abort_sequence = True
                component_timings[comp_name] = ComponentTiming(
                    component=comp_name,
                    elapsed_ns=dt_ns,
                    elapsed_ms=dt_ms,
                    provenance=MeasurementProvenance.LOCAL_EXECUTION,
                    was_executed=False,
                    sample_index=run_idx,
                    status=StepExecutionStatus.BLOCKED.value,
                    was_invoked=True,
                )
            else:
                abort_sequence = True
                component_timings[comp_name] = ComponentTiming(
                    component=comp_name,
                    elapsed_ns=dt_ns,
                    elapsed_ms=dt_ms,
                    provenance=MeasurementProvenance.LOCAL_EXECUTION,
                    was_executed=False,
                    sample_index=run_idx,
                    status=StepExecutionStatus.FAILED.value,
                    was_invoked=True,
                )

        t_end = timer()
        total_ns = t_end - t_start
        total_ms = total_ns / 1_000_000.0

        # Mission success follows actual completed lifecycle truth (DRIFTED)
        drift_timing = component_timings.get("drift_reconciliation")
        step_7_res = runner.step_results.get("P-13.07")
        mission_succeeded = (
            not abort_sequence
            and drift_timing is not None
            and drift_timing.was_executed
            and step_7_res is not None
            and step_7_res.status == "PASS"
            and step_7_res.extra_metadata.get("reconciled_state") == MissionState.DRIFTED.value
        )
        if mission_succeeded:
            final_state = MissionState.DRIFTED.value
        elif any(t.status in ("BLOCKED", "BLOCKED_LIVE") for t in component_timings.values()):
            final_state = MissionState.DRAFT.value
        else:
            final_state = MissionState.FAILED.value

        run = MissionBenchmarkRun(
            run_index=run_idx,
            is_warmup=is_warmup,
            total_elapsed_ns=total_ns,
            total_elapsed_ms=total_ms,
            component_timings=component_timings,
            mission_succeeded=mission_succeeded,
            final_state=final_state,
            provenance=provenance,
        )
        all_runs.append(run)

        if not is_warmup:
            if mission_succeeded:
                e2e_samples_ms.append(total_ms)
            for comp_name, timing in component_timings.items():
                if timing.was_executed and comp_name in component_samples:
                    component_samples[comp_name].append(timing.elapsed_ms)

    # Compute statistics across non-warmup runs
    measured_runs = all_runs[warmup_count:]
    attempted_e2e_count = len(measured_runs)
    successful_e2e_count = len(e2e_samples_ms)

    if successful_e2e_count == attempted_e2e_count and attempted_e2e_count > 0:
        e2e_status = StepExecutionStatus.PASS.value
        e2e_prov = MeasurementProvenance.FIXTURE
    elif successful_e2e_count > 0:
        e2e_status = "PARTIAL_SUCCESS"
        e2e_prov = MeasurementProvenance.FIXTURE
    elif any(
        r.final_state == "DRAFT"
        or any(t.status in ("BLOCKED", "BLOCKED_LIVE") for t in r.component_timings.values())
        for r in measured_runs
    ):
        e2e_status = StepExecutionStatus.BLOCKED.value
        e2e_prov = MeasurementProvenance.LOCAL_EXECUTION
    else:
        e2e_status = StepExecutionStatus.FAILED.value
        e2e_prov = MeasurementProvenance.LOCAL_EXECUTION

    e2e_stats = compute_component_stats(
        component="end_to_end",
        samples_ms=e2e_samples_ms,
        warmup_count=warmup_count,
        provenance=e2e_prov,
        attempted_count=attempted_e2e_count,
        status=e2e_status,
    )

    comp_stats: dict[str, ComponentLatencyStats] = {}
    for comp_name in MISSION_COMPONENTS:
        comp_measured_timings = [
            r.component_timings[comp_name]
            for r in measured_runs
            if comp_name in r.component_timings
        ]
        comp_attempted = sum(1 for t in comp_measured_timings if t.was_invoked)
        comp_successful = sum(1 for t in comp_measured_timings if t.was_executed)
        comp_blocked = sum(
            1 for t in comp_measured_timings if t.status in ("BLOCKED", "BLOCKED_LIVE")
        )
        comp_failed = sum(
            1 for t in comp_measured_timings if t.status == StepExecutionStatus.FAILED.value
        )

        if comp_attempted == 0:
            comp_status = StepExecutionStatus.NOT_RUN.value
            comp_prov = MeasurementProvenance.NOT_RUN
        elif comp_successful == comp_attempted:
            comp_status = StepExecutionStatus.PASS.value
            comp_prov = MeasurementProvenance.FIXTURE
        elif comp_successful > 0:
            comp_status = "PARTIAL_SUCCESS"
            comp_prov = MeasurementProvenance.FIXTURE
        elif comp_blocked > 0 and comp_failed == 0:
            comp_status = StepExecutionStatus.BLOCKED.value
            comp_prov = MeasurementProvenance.LOCAL_EXECUTION
        else:
            comp_status = StepExecutionStatus.FAILED.value
            comp_prov = MeasurementProvenance.LOCAL_EXECUTION

        samples = component_samples.get(comp_name, [])
        comp_stats[comp_name] = compute_component_stats(
            component=comp_name,
            samples_ms=samples,
            warmup_count=warmup_count,
            provenance=comp_prov,
            attempted_count=comp_attempted,
            status=comp_status,
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
            "Timings are aggregate lifecycle-step fixture timings and do NOT separately "
            "measure real Bedrock inference, provider network latency, independent read-back, "
            "or cold-start time. No live external provider calls were executed. Fixture timings "
            "measure local computational overhead only and MUST NOT be presented as live "
            "provider latency. Live provider latency remains NOT_RUN. Per AGENTS.md § 9-10, "
            "live measurements require genuine provider execution."
        ),
        runs=all_runs,
    )


# ============================================================================
# P-18.02: MCP Transport Latency vs Alexa+ Requirements
# ============================================================================

ALEXA_PLUS_LATENCY_REQUIREMENT_MS: Final[float] = 500.0
ALEXA_PLUS_REQUIREMENT_SOURCE: Final[str] = (
    "https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html"
)
ALEXA_PLUS_REQUIREMENT_STATUS: Final[str] = "OBSERVED_IN_DOCUMENTATION"

# Historical recorded-live remote echo from P-01.07
HISTORICAL_P0107_ECHO_MS: Final[float] = 61.26
HISTORICAL_P0107_PROVENANCE: Final[str] = "RECORDED_LIVE"
HISTORICAL_P0107_REFERENCE: Final[str] = (
    "docs/P01_AWS_FEASIBILITY_EVIDENCE.md (P-01.07 remote echo over Streamable HTTP)"
)

# Historical local loopback measurements from P-05.07 (LOCAL_EXECUTION provenance)
HISTORICAL_P0507_INIT_P50_MS: Final[float] = 8.05
HISTORICAL_P0507_TOOLS_LIST_P50_MS: Final[float] = 7.33
HISTORICAL_P0507_MISSION_STATUS_P50_MS: Final[float] = 15.18
HISTORICAL_P0507_PROVENANCE: Final[str] = "LOCAL_EXECUTION"
HISTORICAL_P0507_REFERENCE: Final[str] = (
    "docs/P05_MCP_SPECIFICATION_EVIDENCE.md (P-05.07 local Streamable HTTP loopback)"
)


@dataclass(frozen=True)
class MCPLatencyComparison:
    """Structured comparison of MCP transport latency measurements."""

    # Alexa+ requirement
    alexa_requirement_ms: float
    alexa_requirement_source: str
    alexa_requirement_status: str

    # In-process/local loopback measurements (current)
    local_measurements: dict[str, Any]
    local_provenance: str

    # Historical recorded-live remote measurements
    historical_remote_echo_ms: float
    historical_remote_provenance: str
    historical_remote_reference: str

    # Historical local measurements from P-05.07
    historical_local_init_p50_ms: float
    historical_local_tools_list_p50_ms: float
    historical_local_mission_status_p50_ms: float
    historical_local_provenance: str
    historical_local_reference: str

    # Live remote measurements (NOT_RUN unless genuinely observed)
    live_remote_measurement: str  # "NOT_RUN"
    live_alexa_client_measurement: str  # "NOT_RUN"

    # Compliance assessment
    local_headroom_assessment: str
    remote_compliance_status: str

    # Source SHA and timestamp
    source_sha: str
    timestamp_utc: str

    # Verification failure details (if any)
    validation_failures: list[str] = field(default_factory=list)

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
                "classification": "CURRENT_LOCAL_LOOPBACK",
            },
            "historical_remote_measurements": {
                "p0107_echo_ms": self.historical_remote_echo_ms,
                "provenance": self.historical_remote_provenance,
                "classification": "RECORDED_LIVE_REMOTE_MCP",
                "reference": self.historical_remote_reference,
            },
            "historical_local_measurements": {
                "initialize_p50_ms": self.historical_local_init_p50_ms,
                "tools_list_p50_ms": self.historical_local_tools_list_p50_ms,
                "mission_status_p50_ms": self.historical_local_mission_status_p50_ms,
                "provenance": self.historical_local_provenance,
                "classification": "HISTORICAL_LOCAL_LOOPBACK",
                "reference": self.historical_local_reference,
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
                "validation_failures": self.validation_failures,
            },
            "source_sha": self.source_sha,
            "timestamp_utc": self.timestamp_utc,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@contextlib.asynccontextmanager
async def _default_streamable_mcp_session(endpoint_url: str) -> AsyncIterator[Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(endpoint_url) as (r, w):
        async with ClientSession(r, w) as session:
            yield session


async def measure_mcp_transport_latency(
    warmup_count: int = 2,
    sample_count: int = 5,
    client_session_factory: Any = None,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> MCPLatencyComparison:
    """Measure MCP transport latency and compare against Alexa+ requirements.

    Measures:
    - In-process/local loopback Streamable HTTP latency (current run)
    - Verifies protocol and tool payload success before accepting timing samples
    - Compares against historical recorded-live measurements
    - Reports remote and Alexa+ paths as NOT_RUN
    """
    import subprocess

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
    validation_failures: list[str] = []

    session_ctx_factory = (
        client_session_factory
        if client_session_factory is not None
        else _default_streamable_mcp_session
    )

    with scoped_benchmark_logging_suppression():
        async with run_loopback_mcp_server(config, ledger=ledger) as (_, endpoint_url):
            # 1. Measure initialize with protocol validation
            init_samples: list[float] = []
            for i in range(warmup_count + sample_count):
                try:
                    async with session_ctx_factory(endpoint_url) as session:
                        t0 = timer()
                        init_res = await session.initialize()
                        t1 = timer()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    validation_failures.append(
                        f"initialize raised exception at sample {i}: {type(exc).__name__}"
                    )
                    continue

                # Validate response
                if (
                    init_res is None
                    or not getattr(init_res, "protocol_version", None)
                    or not getattr(init_res, "server_info", None)
                    or getattr(init_res.server_info, "name", "") != "StillDone"
                ):
                    validation_failures.append(f"initialize failed validation at sample {i}")
                    continue

                if i >= warmup_count:
                    init_samples.append((t1 - t0) / 1_000_000.0)

            init_stats = compute_component_stats(
                "initialize",
                init_samples,
                warmup_count,
                MeasurementProvenance.LOCAL_EXECUTION,
                attempted_count=sample_count,
            )
            local_measurements["initialize"] = init_stats.to_dict()

            # 2. Measure tools/list with tool presence validation
            tl_samples: list[float] = []
            try:
                async with session_ctx_factory(endpoint_url) as session:
                    await session.initialize()
                    for i in range(warmup_count + sample_count):
                        try:
                            t0 = timer()
                            tools_res = await session.list_tools()
                            t1 = timer()
                        except (KeyboardInterrupt, SystemExit):
                            raise
                        except Exception as exc:
                            validation_failures.append(
                                f"tools/list raised exception at sample {i}: {type(exc).__name__}"
                            )
                            continue

                        tool_names = [
                            t.name for t in getattr(tools_res, "tools", []) if hasattr(t, "name")
                        ]
                        if "mission_status" not in tool_names:
                            validation_failures.append(
                                f"tools/list missing mission_status at sample {i}"
                            )
                            continue

                        if i >= warmup_count:
                            tl_samples.append((t1 - t0) / 1_000_000.0)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                validation_failures.append(
                    f"tools/list session connection exception: {type(exc).__name__}"
                )

            tl_stats = compute_component_stats(
                "tools_list",
                tl_samples,
                warmup_count,
                MeasurementProvenance.LOCAL_EXECUTION,
                attempted_count=sample_count,
            )
            local_measurements["tools_list"] = tl_stats.to_dict()

            # 3. Measure mission_status with structured return value validation
            ms_samples: list[float] = []
            try:
                async with session_ctx_factory(endpoint_url) as session:
                    await session.initialize()
                    for i in range(warmup_count + sample_count):
                        try:
                            t0 = timer()
                            call_res = await session.call_tool(
                                "mission_status", arguments={"mission_id": mission_id_str}
                            )
                            t1 = timer()
                        except (KeyboardInterrupt, SystemExit):
                            raise
                        except Exception as exc:
                            validation_failures.append(
                                f"mission_status raised exception at sample {i}: "
                                f"{type(exc).__name__}"
                            )
                            continue

                        # Validate that call_res is NOT error and returns intended mission
                        is_err = getattr(call_res, "is_error", False)
                        content_ok = False
                        if not is_err:
                            structured = getattr(call_res, "structured_content", None)
                            if (
                                isinstance(structured, dict)
                                and structured.get("mission_id") == mission_id_str
                            ):
                                content_ok = True
                            elif hasattr(call_res, "content") and call_res.content:
                                text_val = getattr(call_res.content[0], "text", "")
                                try:
                                    parsed = json.loads(text_val)
                                    if parsed.get("mission_id") == mission_id_str:
                                        content_ok = True
                                except Exception:
                                    content_ok = False

                        if not content_ok:
                            validation_failures.append(
                                f"mission_status payload validation failed at sample {i}"
                            )
                            continue

                        if i >= warmup_count:
                            ms_samples.append((t1 - t0) / 1_000_000.0)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                validation_failures.append(
                    f"mission_status session connection exception: {type(exc).__name__}"
                )

            ms_stats = compute_component_stats(
                "mission_status",
                ms_samples,
                warmup_count,
                MeasurementProvenance.LOCAL_EXECUTION,
                attempted_count=sample_count,
            )
            local_measurements["mission_status"] = ms_stats.to_dict()

    # Compute headroom assessment
    if validation_failures:
        local_headroom = (
            f"LOCAL_FAILED: One or more MCP operations failed verification: "
            f"{'; '.join(validation_failures)}. Threshold qualification failed."
        )
    elif not all((init_stats.was_executed, tl_stats.was_executed, ms_stats.was_executed)):
        local_headroom = (
            "LOCAL_FAILED: Zero valid samples gathered for one or more operations. "
            "Threshold qualification failed."
        )
    elif any(s.sample_count < sample_count for s in (init_stats, tl_stats, ms_stats)):
        local_headroom = (
            f"LOCAL_FAILED: Insufficient valid samples gathered "
            f"(expected at least {sample_count}). Threshold qualification failed."
        )
    else:
        max_local_p95 = max(init_stats.p95_ms, tl_stats.p95_ms, ms_stats.p95_ms)
        if max_local_p95 < ALEXA_PLUS_LATENCY_REQUIREMENT_MS:
            headroom_ms = ALEXA_PLUS_LATENCY_REQUIREMENT_MS - max_local_p95
            local_headroom = (
                f"LOCAL_PASS: All local loopback p95 measurements ({max_local_p95:.2f}ms) "
                f"are below {ALEXA_PLUS_LATENCY_REQUIREMENT_MS}ms target with "
                f"{headroom_ms:.2f}ms headroom. This is LOCAL_EXECUTION only and does NOT "
                "certify remote or Alexa+ compliance."
            )
        else:
            deficit_ms = max_local_p95 - ALEXA_PLUS_LATENCY_REQUIREMENT_MS
            local_headroom = (
                f"LOCAL_SLOW: Maximum local loopback p95 measurement ({max_local_p95:.2f}ms) "
                f"meets or exceeds {ALEXA_PLUS_LATENCY_REQUIREMENT_MS}ms threshold by "
                f"{deficit_ms:.2f}ms."
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
        historical_remote_reference=HISTORICAL_P0107_REFERENCE,
        historical_local_init_p50_ms=HISTORICAL_P0507_INIT_P50_MS,
        historical_local_tools_list_p50_ms=HISTORICAL_P0507_TOOLS_LIST_P50_MS,
        historical_local_mission_status_p50_ms=HISTORICAL_P0507_MISSION_STATUS_P50_MS,
        historical_local_provenance=HISTORICAL_P0507_PROVENANCE,
        historical_local_reference=HISTORICAL_P0507_REFERENCE,
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
        validation_failures=validation_failures,
    )


# ============================================================================
# P-18.03: AWS Usage/Cost Per Canonical Mission
# ============================================================================


class CostEstimateCategory(StrEnum):
    """Categorical classification of cost estimate components."""

    VERIFIED_PRICING = "VERIFIED_PRICING"
    VERIFIED_RATE_UNOBSERVED_CONSUMPTION = "VERIFIED_RATE_UNOBSERVED_CONSUMPTION"
    EXAMPLE_ASSUMPTIONS = "EXAMPLE_ASSUMPTIONS"
    DIRECT_FEE_ZERO = "DIRECT_FEE_ZERO"
    UNVERIFIED_RATE = "UNVERIFIED_RATE"
    ACCOUNT_USAGE_DEPENDENT = "ACCOUNT_USAGE_DEPENDENT"
    NOT_OBSERVED_ACCOUNT_USAGE = "NOT_OBSERVED_ACCOUNT_USAGE"


@dataclass(frozen=True)
class AWSServiceCostEstimate:
    """Cost estimate for a single AWS service per canonical mission."""

    service: str
    component: str
    category: str
    unit: str
    estimated_quantity: float | None
    unit_price_usd: Decimal | None
    estimated_cost_usd: Decimal | None
    pricing_source: str
    pricing_verified: bool
    pricing_verification_date: str
    is_covered_by_free_tier: bool | str | None  # "TRUE", "ACCOUNT_USAGE_DEPENDENT", etc.
    is_covered_by_promotional_credit: bool | str | None
    observed_actual_cost: str  # "NOT_OBSERVED"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        tier_rep: str
        if self.is_covered_by_free_tier is True:
            tier_rep = "TRUE"
        elif self.is_covered_by_free_tier is False:
            tier_rep = "FALSE"
        elif isinstance(self.is_covered_by_free_tier, str):
            tier_rep = self.is_covered_by_free_tier
        else:
            tier_rep = "NOT_OBSERVED"

        credit_rep: str
        if self.is_covered_by_promotional_credit is True:
            credit_rep = "TRUE"
        elif self.is_covered_by_promotional_credit is False:
            credit_rep = "FALSE"
        elif isinstance(self.is_covered_by_promotional_credit, str):
            credit_rep = self.is_covered_by_promotional_credit
        else:
            credit_rep = "NOT_OBSERVED"

        return {
            "service": self.service,
            "component": self.component,
            "category": self.category,
            "unit": self.unit,
            "estimated_quantity": self.estimated_quantity,
            "unit_price_usd": (
                str(self.unit_price_usd) if self.unit_price_usd is not None else None
            ),
            "estimated_cost_usd": (
                str(self.estimated_cost_usd) if self.estimated_cost_usd is not None else None
            ),
            "pricing_source": self.pricing_source,
            "pricing_verified": self.pricing_verified,
            "pricing_verification_date": self.pricing_verification_date,
            "is_covered_by_free_tier": tier_rep,
            "is_covered_by_promotional_credit": credit_rep,
            "observed_actual_cost": self.observed_actual_cost,
            "notes": self.notes,
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
    conditional_scenario_total_usd: Decimal  # Bedrock Nova Micro example scenario
    unestimated_components: list[str]
    definitive_gross_total_status: str  # "NOT_ESTIMABLE_OFFLINE"

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

    @property
    def total_estimated_cost_usd(self) -> Decimal | None:
        """Definitive gross mission total is NOT_ESTIMABLE_OFFLINE.

        Returns None to avoid presenting Bedrock-only conditional scenario
        as complete gross mission cost.
        """
        return None

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
                "conditional_scenario_total_usd": str(self.conditional_scenario_total_usd),
                "total_estimated_cost_usd": None,
                "unestimated_components": self.unestimated_components,
                "definitive_gross_total_status": self.definitive_gross_total_status,
                "disclaimer": (
                    "No single definitive gross mission dollar total is published because "
                    "AgentCore microVM runtime costs and account-level CloudWatch quotas "
                    "cannot be verified offline. The conditional scenario total reflects "
                    "Bedrock Nova Micro inference only under example hypothetical assumptions "
                    "(200 in / 100 out tokens) at verified official rates. Actual billed cost "
                    "may differ due to promotional credits, free tier, rounding, and "
                    "account-wide billing aggregation."
                ),
            },
            "category_d_not_observed": self.not_observed,
            "billing_boundary": {
                "personal_spend_target": self.personal_spend_target,
                "actual_personal_spend": self.actual_personal_spend,
                "promotional_credit_remaining": self.promotional_credit_remaining,
                "promotional_credit_statement": (
                    "Promotional credit of $150.00 was recorded in P-01.01. Because AgentCore "
                    "microVM pricing and total account billing are unobserved offline, no fixed "
                    "number of missions can be definitively guaranteed by the credit."
                ),
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

    Invariants:
    - This task does NOT authorize real Bedrock invocation.
    - Uses independently verified official AWS pricing where available.
    - AgentCore microVM costs are resource-model dependent and marked NOT_ESTIMABLE_OFFLINE.
    - Direct library/IAM fees are distinguished from underlying account charges.
    - CloudWatch EMF free tier is marked ACCOUNT_USAGE_DEPENDENT and cost is None (NOT_ESTIMABLE).
    - No single definitive gross dollar total is published.
    - Actual billing observation remains strictly NOT_OBSERVED.
    """
    import subprocess

    # Example token assumptions (hypothetical planning prompt + response)
    # Explicitly labeled EXAMPLE_ASSUMPTIONS, not measured canonical consumption
    example_input_tokens = 200
    example_output_tokens = 100

    # Official Amazon Bedrock pricing for amazon.nova-micro-v1:0 in us-east-1
    # Source: https://aws.amazon.com/bedrock/pricing/
    nova_micro_input_price_per_1k = Decimal("0.000035")  # $0.035 / 1M tokens
    nova_micro_output_price_per_1k = Decimal("0.00014")  # $0.14 / 1M tokens

    input_cost = (
        Decimal(str(example_input_tokens)) / Decimal("1000")
    ) * nova_micro_input_price_per_1k
    output_cost = (
        Decimal(str(example_output_tokens)) / Decimal("1000")
    ) * nova_micro_output_price_per_1k
    bedrock_scenario_cost = input_cost + output_cost

    cost_estimates = [
        AWSServiceCostEstimate(
            service="Amazon Bedrock",
            component="amazon.nova-micro-v1:0 Converse API",
            category=CostEstimateCategory.VERIFIED_PRICING.value,
            unit="tokens (200 in / 100 out example assumptions)",
            estimated_quantity=float(example_input_tokens + example_output_tokens),
            unit_price_usd=nova_micro_input_price_per_1k,
            estimated_cost_usd=bedrock_scenario_cost,
            pricing_source="https://aws.amazon.com/bedrock/pricing/",
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier=False,
            is_covered_by_promotional_credit="ACCOUNT_USAGE_DEPENDENT",
            observed_actual_cost="NOT_OBSERVED",
            notes=(
                "EXAMPLE_ASSUMPTIONS: 200 in / 100 out tokens are hypothetical planning "
                "assumptions, NOT measured canonical mission consumption or billed tokens."
            ),
        ),
        AWSServiceCostEstimate(
            service="AWS Strands Agents SDK",
            component="strands-agents==1.57.2 (open-source SDK)",
            category=CostEstimateCategory.DIRECT_FEE_ZERO.value,
            unit="library invocations",
            estimated_quantity=1.0,
            unit_price_usd=Decimal("0.00"),
            estimated_cost_usd=Decimal("0.00"),
            pricing_source="Open-source Apache-2.0 library",
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier=True,
            is_covered_by_promotional_credit="NOT_APPLICABLE",
            observed_actual_cost="NOT_OBSERVED",
            notes=(
                "Direct SDK library invocation fee is $0.00. This is a client-side library charge "
                "and does not cover underlying compute, network, or Bedrock API calls."
            ),
        ),
        AWSServiceCostEstimate(
            service="AWS IAM",
            component="SigV4 request signing",
            category=CostEstimateCategory.DIRECT_FEE_ZERO.value,
            unit="signing requests",
            estimated_quantity=1.0,
            unit_price_usd=Decimal("0.00"),
            estimated_cost_usd=Decimal("0.00"),
            pricing_source="AWS IAM standard service policy (no charge for SigV4 signing)",
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier=True,
            is_covered_by_promotional_credit="NOT_APPLICABLE",
            observed_actual_cost="NOT_OBSERVED",
            notes=(
                "IAM SigV4 signing has no direct per-request charge. Underlying AWS service "
                "request charges are accounted separately under their respective services."
            ),
        ),
        AWSServiceCostEstimate(
            service="Amazon CloudWatch (EMF)",
            component="PutLogEvents EMF ingestion (prepared, NOT_RUN)",
            category=CostEstimateCategory.ACCOUNT_USAGE_DEPENDENT.value,
            unit="log events",
            estimated_quantity=4.0,
            unit_price_usd=None,
            estimated_cost_usd=None,
            pricing_source=(
                "https://aws.amazon.com/cloudwatch/pricing/ - "
                "5GB/month ingestion free tier, $0.50/GB thereafter"
            ),
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier="ACCOUNT_USAGE_DEPENDENT",
            is_covered_by_promotional_credit="NOT_OBSERVED",
            observed_actual_cost="NOT_OBSERVED",
            notes=(
                "Official CloudWatch pricing includes 5GB/month free ingestion ($0.50/GB "
                "thereafter). Whether this mission falls within free tier depends on aggregate "
                "account-wide monthly ingestion across all services and billing cycles, which is "
                "NOT_OBSERVED offline. Per AGENTS.md § 11-12, estimated cost is NOT_ESTIMABLE "
                "offline (must not be assumed $0.00)."
            ),
        ),
        AWSServiceCostEstimate(
            service="Amazon Bedrock AgentCore Runtime",
            component="Serverless CodeZip microVM execution",
            category=CostEstimateCategory.VERIFIED_RATE_UNOBSERVED_CONSUMPTION.value,
            unit="vCPU-seconds / memory-seconds / duration",
            estimated_quantity=None,
            unit_price_usd=None,
            estimated_cost_usd=None,
            pricing_source=(
                "https://aws.amazon.com/bedrock/agentcore/pricing/ - "
                "Official published microVM rates: ~$0.0895-$0.1276/vCPU-hour active, "
                "$0.00945-$0.0169/GB-hour memory"
            ),
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier="NOT_OBSERVED",
            is_covered_by_promotional_credit="NOT_OBSERVED",
            observed_actual_cost="NOT_OBSERVED",
            notes=(
                "NOT_ESTIMABLE_OFFLINE: Official resource rates are published ($0.0895-$0.1276/"
                "vCPU-hr active, $0.00945-$0.0169/GB-hr memory on "
                "https://aws.amazon.com/bedrock/agentcore/pricing/). However, actual active "
                "compute seconds, memory allocation, microVM tier, and runtime duration for "
                "this mission are unobserved offline without live profiling. "
                "No dollar amount is invented."
            ),
        ),
    ]

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
        conditional_scenario_total_usd=bedrock_scenario_cost,
        unestimated_components=[
            (
                "Amazon Bedrock AgentCore Runtime (published resource rates verified on "
                "https://aws.amazon.com/bedrock/agentcore/pricing/; active CPU-seconds, "
                "memory consumption, and runtime tier unobserved offline)"
            ),
            (
                "Amazon CloudWatch (EMF) (official 5GB/month ingestion free tier is conditional "
                "on unobserved account-wide monthly usage; estimated cost is NOT_ESTIMABLE offline)"
            ),
        ],
        definitive_gross_total_status="NOT_ESTIMABLE_OFFLINE",
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


# ============================================================================
# P-18.06: Bounded Repeated-Mission Reliability Test (Offline Fixture)
# ============================================================================


@dataclass(frozen=True)
class MissionReliabilityRunOutcome:
    """Outcome and integrity verification of a single repeated-mission run."""

    run_index: int
    mission_id: str
    scenario: str
    status: str  # "PASS", "BLOCKED", "FAILED"
    reached_ready: bool
    reached_drifted: bool
    receipt_projection_hash: str | None
    drifted_receipt_projection_hash: str | None
    historical_receipt_intact: bool
    writes_performed: int
    elapsed_ns: int
    elapsed_ms: float
    provenance: MeasurementProvenance = MeasurementProvenance.FIXTURE
    error_category: str | None = None
    details: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_index": self.run_index,
            "mission_id": self.mission_id,
            "scenario": self.scenario,
            "status": self.status,
            "reached_ready": self.reached_ready,
            "reached_drifted": self.reached_drifted,
            "receipt_projection_hash": self.receipt_projection_hash,
            "drifted_receipt_projection_hash": self.drifted_receipt_projection_hash,
            "historical_receipt_intact": self.historical_receipt_intact,
            "writes_performed": self.writes_performed,
            "elapsed_ns": self.elapsed_ns,
            "elapsed_ms": self.elapsed_ms,
            "provenance": self.provenance.value,
            "error_category": self.error_category,
            "details": self.details,
        }


@dataclass(frozen=True)
class MissionReliabilityTestResult:
    """Consolidated result of bounded repeated-mission reliability testing (P-18.06)."""

    iteration_cap: int
    total_runs: int
    successful_runs: int
    failed_runs: int
    blocked_runs: int
    cross_run_contamination_detected: bool
    duplicate_unintended_mutation_detected: bool
    false_ready_detected: bool
    historical_receipt_integrity_verified: bool
    predicate_correctness_verified: bool
    runs: list[MissionReliabilityRunOutcome]
    provenance: MeasurementProvenance = MeasurementProvenance.FIXTURE
    source_sha: str = "UNKNOWN"
    environment: str = "LOCAL"
    qualification_status: str = "QUALIFIED"
    untested_scenarios: tuple[str, ...] = ()
    non_certification_statement: str = (
        "This offline reliability test exercises simulated fixture environments only. "
        "It does NOT certify production reliability or live provider availability."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration_cap": self.iteration_cap,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "blocked_runs": self.blocked_runs,
            "cross_run_contamination_detected": self.cross_run_contamination_detected,
            "duplicate_unintended_mutation_detected": self.duplicate_unintended_mutation_detected,
            "false_ready_detected": self.false_ready_detected,
            "historical_receipt_integrity_verified": self.historical_receipt_integrity_verified,
            "predicate_correctness_verified": self.predicate_correctness_verified,
            "provenance": self.provenance.value,
            "source_sha": self.source_sha,
            "environment": self.environment,
            "qualification_status": self.qualification_status,
            "untested_scenarios": list(self.untested_scenarios),
            "non_certification_statement": self.non_certification_statement,
            "runs": [r.to_dict() for r in self.runs],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def run_repeated_mission_reliability_test(
    iteration_cap: int = 15,
    timeout_per_run_seconds: float = 5.0,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> MissionReliabilityTestResult:
    """Execute bounded repeated-mission reliability test over the canonical killer mission.

    Invariants:
    - Strictly FIXTURE provenance (offline test doubles).
    - Finite iteration cap and per-run execution timeout.
    - Fresh environment, ledger, and mission identity per run.
    - Tests representative successful, blocked, failed, and interrupted runs.
    - Verifies historical receipt integrity, predicate correctness, READY -> DRIFTED.
    - Detects cross-run evidence contamination, duplicate unintended mutations, and false READY.
    - Zero live provider calls (0 Bedrock, 0 Google, 0 Open-Meteo).
    - Zero personal spend ($0.00).
    """
    import subprocess

    from stilldone.adapters.tasks import (
        TaskRateLimitError,
        TaskTransportItem,
    )
    from stilldone.domain.mission import MissionId
    from stilldone.killer_mission import (
        DemoResourceScope,
        KillerMissionEnvironment,
        KillerMissionExecutionError,
        KillerMissionSliceRunner,
        KillerMissionVerificationError,
        check_live_preflight,
    )
    from stilldone.pending_approval import ApprovalDecision

    if isinstance(iteration_cap, bool) or not isinstance(iteration_cap, int):
        raise TypeError("iteration_cap must be an integer")
    if iteration_cap <= 0:
        raise ValueError("iteration_cap must be strictly positive")
    if iteration_cap > 1000:
        raise ValueError("iteration_cap must not exceed reasonable bounded maximum (1000)")

    if isinstance(timeout_per_run_seconds, bool) or not isinstance(
        timeout_per_run_seconds, (int, float)
    ):
        raise TypeError("timeout_per_run_seconds must be a float or int")
    if not math.isfinite(timeout_per_run_seconds) or timeout_per_run_seconds <= 0.0:
        raise ValueError("timeout_per_run_seconds must be a positive finite number")

    timeout_ns = int(timeout_per_run_seconds * 1_000_000_000)

    runs: list[MissionReliabilityRunOutcome] = []
    seen_mission_ids: set[str] = set()

    contamination_detected = False
    duplicate_mutation_detected = False
    false_ready_detected = False
    historical_receipt_intact_all = True
    predicate_correctness_all = True

    try:
        sha_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        source_sha = sha_proc.stdout.strip()
    except Exception:
        source_sha = "UNKNOWN"

    env_desc = (
        f"{platform.system()} {platform.release()} ({platform.machine()}), "
        f"Python {platform.python_version()}"
    )

    with scoped_benchmark_logging_suppression(
        logger_names=(
            "stilldone",
            "stilldone.adapters.tasks",
            "stilldone.killer_mission",
            "httpx",
            "mcp",
        )
    ):
        for run_idx in range(iteration_cap):
            mid = MissionId(f"11111111-2222-3333-4444-{run_idx:012d}")

            # Check for mission ID collision
            if mid.value in seen_mission_ids:
                contamination_detected = True
            seen_mission_ids.add(mid.value)

            # Assign scenario based on iteration pattern
            if iteration_cap >= 15:
                if run_idx == 10:
                    scenario = "BLOCKED_APPROVAL"
                elif run_idx == 11:
                    scenario = "BLOCKED_PREFLIGHT"
                elif run_idx == 12:
                    scenario = "FAILED_READBACK"
                elif run_idx == 13:
                    scenario = "INTERRUPTED_PROVIDER_ERROR"
                else:
                    scenario = "SUCCESSFUL_LIFECYCLE"
            else:
                scenario = "SUCCESSFUL_LIFECYCLE"

            t0 = timer()

            if scenario == "SUCCESSFUL_LIFECYCLE":
                env = KillerMissionEnvironment.create_fixture_environment()
                # Verify clean environment isolation
                tasks_dict = getattr(env.tasks_transport, "_tasks", None)
                if (tasks_dict is not None and len(tasks_dict) != 0) or len(
                    env.approval_ledger.get_decision_records()
                ) != 0:
                    contamination_detected = True
                if len(list(env.snapshot_repo.storage_path.glob("*.json"))) != 0:
                    contamination_detected = True

                runner = KillerMissionSliceRunner(env=env, mission_id=mid)
                runner.step_p13_01_seed()
                runner.step_p13_02_plan()
                runner.step_p13_03_tasks_prep()
                runner.step_p13_04_calendar_pause()
                runner.step_p13_05_calendar_approve()
                runner.step_p13_06_ready_receipt()
                runner.step_p13_07_mutate_and_drift()

                t1 = timer()
                dt_ns = t1 - t0

                ready_step = runner.step_results.get("P-13.06")
                drift_step = runner.step_results.get("P-13.07")

                ready_reached = (
                    runner.ready_receipt is not None
                    and ready_step is not None
                    and ready_step.status == "PASS"
                    and ready_step.is_verified is True
                    and ready_step.extra_metadata.get("mission_state") == "READY"
                )
                drift_reached = (
                    drift_step is not None
                    and drift_step.status == "PASS"
                    and drift_step.is_verified is True
                    and drift_step.extra_metadata.get("reconciled_state") == "DRIFTED"
                )

                ready_hash = runner.ready_receipt_hash
                drifted_hash = (
                    runner.ready_receipt.receipt_hash.value if runner.ready_receipt else None
                )
                receipt_intact = (
                    ready_reached
                    and ready_hash is not None
                    and drifted_hash == ready_hash
                    and drift_step is not None
                    and drift_step.extra_metadata.get("historical_receipt_intact") is True
                )
                if not receipt_intact:
                    historical_receipt_intact_all = False

                # Dynamically evaluate canonical predicates against actual observations
                from stilldone.verifier.predicates import (
                    PredicateTruth,
                    evaluate_predicate,
                )

                obs_map = {
                    runner.pred_weather.predicate_id: runner.weather_observation,
                    runner.pred_task.predicate_id: runner.task_observation,
                    runner.pred_calendar.predicate_id: runner.calendar_observation,
                }
                run_preds_ok = True
                for pred in runner.canonical_predicates:
                    obs = obs_map.get(pred.predicate_id)
                    if obs is None:
                        run_preds_ok = False
                        break
                    eval_res = evaluate_predicate(pred, obs)
                    if eval_res.truth != PredicateTruth.TRUE:
                        run_preds_ok = False
                        break

                if not run_preds_ok:
                    predicate_correctness_all = False

                if runner.total_writes != 3:
                    duplicate_mutation_detected = True

                err_cat = None
                timeout_msg = (
                    f"Execution timed out ({dt_ns / 1e6:.2f}ms > "
                    f"{timeout_per_run_seconds * 1e3:.2f}ms)"
                )
                if dt_ns > timeout_ns:
                    run_status = "FAILED"
                    err_cat = "EXECUTION_TIMEOUT"
                    ready_reached = False
                    drift_reached = False
                    details = timeout_msg
                elif not run_preds_ok:
                    run_status = "FAILED"
                    err_cat = "PREDICATE_EVALUATION_FAILED"
                    details = "Canonical predicate failed dynamic evaluation against observations."
                elif (
                    ready_reached and drift_reached and receipt_intact and runner.total_writes == 3
                ):
                    run_status = "PASS"
                    details = "Full 7-step slice: READY -> DRIFTED with receipt intact."
                else:
                    run_status = "FAILED"
                    err_cat = "LIFECYCLE_VERIFICATION_MISMATCH"
                    details = (
                        "Lifecycle execution failed to achieve required "
                        "READY and DRIFTED milestones."
                    )

                runs.append(
                    MissionReliabilityRunOutcome(
                        run_index=run_idx,
                        mission_id=mid.value,
                        scenario=scenario,
                        status=run_status,
                        reached_ready=ready_reached,
                        reached_drifted=drift_reached,
                        receipt_projection_hash=ready_hash,
                        drifted_receipt_projection_hash=drifted_hash,
                        historical_receipt_intact=receipt_intact,
                        writes_performed=runner.total_writes,
                        elapsed_ns=dt_ns,
                        elapsed_ms=dt_ns / 1_000_000.0,
                        provenance=MeasurementProvenance.FIXTURE,
                        error_category=err_cat,
                        details=details,
                    )
                )

            elif scenario == "BLOCKED_APPROVAL":
                env = KillerMissionEnvironment.create_fixture_environment()
                runner = KillerMissionSliceRunner(
                    env=env,
                    mission_id=mid,
                    calendar_decision=ApprovalDecision.REJECT,
                )
                runner.step_p13_01_seed()
                runner.step_p13_02_plan()
                runner.step_p13_03_tasks_prep()
                runner.step_p13_04_calendar_pause()
                runner.step_p13_05_calendar_approve()

                t1 = timer()
                dt_ns = t1 - t0

                if runner.ready_receipt is not None:
                    false_ready_detected = True

                blocked_status = "BLOCKED"
                err_cat = None
                timeout_msg = (
                    f"Execution timed out ({dt_ns / 1e6:.2f}ms > "
                    f"{timeout_per_run_seconds * 1e3:.2f}ms)"
                )
                if dt_ns > timeout_ns:
                    blocked_status = "FAILED"
                    err_cat = "EXECUTION_TIMEOUT"

                runs.append(
                    MissionReliabilityRunOutcome(
                        run_index=run_idx,
                        mission_id=mid.value,
                        scenario=scenario,
                        status=blocked_status,
                        reached_ready=False,
                        reached_drifted=False,
                        receipt_projection_hash=None,
                        drifted_receipt_projection_hash=None,
                        historical_receipt_intact=True,
                        writes_performed=runner.total_writes,
                        elapsed_ns=dt_ns,
                        elapsed_ms=dt_ns / 1_000_000.0,
                        provenance=MeasurementProvenance.FIXTURE,
                        error_category=err_cat,
                        details="Operator rejected calendar change at approval boundary; 0 writes."
                        if err_cat is None
                        else timeout_msg,
                    )
                )

            elif scenario == "BLOCKED_PREFLIGHT":
                scope = DemoResourceScope(calendar_id="cal-scope", task_list_id="tl-scope")
                report = check_live_preflight(scope, operator_approved=False)

                t1 = timer()
                dt_ns = t1 - t0

                if report.is_ready:
                    false_ready_detected = True

                preflight_status = "BLOCKED"
                err_cat = None
                timeout_msg = (
                    f"Execution timed out ({dt_ns / 1e6:.2f}ms > "
                    f"{timeout_per_run_seconds * 1e3:.2f}ms)"
                )
                if dt_ns > timeout_ns:
                    preflight_status = "FAILED"
                    err_cat = "EXECUTION_TIMEOUT"

                runs.append(
                    MissionReliabilityRunOutcome(
                        run_index=run_idx,
                        mission_id=mid.value,
                        scenario=scenario,
                        status=preflight_status,
                        reached_ready=False,
                        reached_drifted=False,
                        receipt_projection_hash=None,
                        drifted_receipt_projection_hash=None,
                        historical_receipt_intact=True,
                        writes_performed=0,
                        elapsed_ns=dt_ns,
                        elapsed_ms=dt_ns / 1_000_000.0,
                        provenance=MeasurementProvenance.FIXTURE,
                        error_category=err_cat,
                        details="Live preflight halted: operator authorization missing."
                        if err_cat is None
                        else timeout_msg,
                    )
                )

            elif scenario == "FAILED_READBACK":
                env = KillerMissionEnvironment.create_fixture_environment()

                class ContradictoryTasksTransport:
                    def __init__(self, inner: Any) -> None:
                        self._inner = inner

                    def insert_task(
                        self, task_list_id: str, body: dict[str, Any], **kw: Any
                    ) -> Any:
                        return self._inner.insert_task(task_list_id, body, **kw)

                    def list_tasks(self, task_list_id: str, **kw: Any) -> Any:
                        return self._inner.list_tasks(task_list_id, **kw)

                    def get_task(self, task_list_id: str, task_id: str) -> Any:
                        item = self._inner.get_task(task_list_id, task_id)
                        if item is None:
                            return None
                        return TaskTransportItem(
                            id=item.id,
                            title="Different Contradictory Title",
                            status="needsAction",
                            due=item.due,
                        )

                env.tasks_transport = ContradictoryTasksTransport(env.tasks_transport)  # type: ignore[assignment]
                runner = KillerMissionSliceRunner(env=env, mission_id=mid)
                runner.step_p13_01_seed()
                runner.step_p13_02_plan()

                err_cat = None
                try:
                    runner.step_p13_03_tasks_prep()
                except KillerMissionVerificationError:
                    err_cat = "READBACK_CONTRADICTION"

                t1 = timer()
                dt_ns = t1 - t0

                if runner.ready_receipt is not None:
                    false_ready_detected = True

                timeout_msg = (
                    f"Execution timed out ({dt_ns / 1e6:.2f}ms > "
                    f"{timeout_per_run_seconds * 1e3:.2f}ms)"
                )
                if dt_ns > timeout_ns:
                    err_cat = "EXECUTION_TIMEOUT"

                runs.append(
                    MissionReliabilityRunOutcome(
                        run_index=run_idx,
                        mission_id=mid.value,
                        scenario=scenario,
                        status="FAILED",
                        reached_ready=False,
                        reached_drifted=False,
                        receipt_projection_hash=None,
                        drifted_receipt_projection_hash=None,
                        historical_receipt_intact=True,
                        writes_performed=runner.total_writes,
                        elapsed_ns=dt_ns,
                        elapsed_ms=dt_ns / 1_000_000.0,
                        provenance=MeasurementProvenance.FIXTURE,
                        error_category=err_cat,
                        details="Readback verifier detected wrong title; halted unverified."
                        if err_cat != "EXECUTION_TIMEOUT"
                        else timeout_msg,
                    )
                )

            elif scenario == "INTERRUPTED_PROVIDER_ERROR":
                env = KillerMissionEnvironment.create_fixture_environment()

                class ThrottledFakeTasks:
                    def insert_task(self, *a: Any, **kw: Any) -> Any:
                        raise TaskRateLimitError("429 Too Many Requests")

                    def get_task(self, *a: Any, **kw: Any) -> Any:
                        raise TaskRateLimitError("429 Too Many Requests")

                    def list_tasks(self, *a: Any, **kw: Any) -> list[Any]:
                        raise TaskRateLimitError("429 Too Many Requests")

                env.tasks_transport = ThrottledFakeTasks()  # type: ignore[assignment]
                runner = KillerMissionSliceRunner(env=env, mission_id=mid)
                runner.step_p13_01_seed()
                runner.step_p13_02_plan()

                err_cat = None
                try:
                    runner.step_p13_03_tasks_prep()
                except KillerMissionExecutionError:
                    err_cat = "PROVIDER_429_THROTTLED"

                t1 = timer()
                dt_ns = t1 - t0

                if runner.ready_receipt is not None:
                    false_ready_detected = True

                timeout_msg = (
                    f"Execution timed out ({dt_ns / 1e6:.2f}ms > "
                    f"{timeout_per_run_seconds * 1e3:.2f}ms)"
                )
                if dt_ns > timeout_ns:
                    err_cat = "EXECUTION_TIMEOUT"

                runs.append(
                    MissionReliabilityRunOutcome(
                        run_index=run_idx,
                        mission_id=mid.value,
                        scenario=scenario,
                        status="FAILED",
                        reached_ready=False,
                        reached_drifted=False,
                        receipt_projection_hash=None,
                        drifted_receipt_projection_hash=None,
                        historical_receipt_intact=True,
                        writes_performed=runner.total_writes,
                        elapsed_ns=dt_ns,
                        elapsed_ms=dt_ns / 1_000_000.0,
                        provenance=MeasurementProvenance.FIXTURE,
                        error_category=err_cat,
                        details="Provider 429 rate limit injected at tasks prep; slice aborted."
                        if err_cat != "EXECUTION_TIMEOUT"
                        else timeout_msg,
                    )
                )

        ALL_REPRESENTATIVE_SCENARIOS = (
            "SUCCESSFUL_LIFECYCLE",
            "BLOCKED_APPROVAL",
            "BLOCKED_PREFLIGHT",
            "FAILED_READBACK",
            "INTERRUPTED_PROVIDER_ERROR",
        )
        exercised_scenarios = {r.scenario for r in runs}
        untested = tuple(s for s in ALL_REPRESENTATIVE_SCENARIOS if s not in exercised_scenarios)
        qualification_status = "QUALIFIED" if len(untested) == 0 else "PARTIAL_UNQUALIFIED"

        successful_count = sum(1 for r in runs if r.status == "PASS")
        blocked_count = sum(1 for r in runs if r.status == "BLOCKED")
        failed_count = sum(1 for r in runs if r.status == "FAILED")

        return MissionReliabilityTestResult(
            iteration_cap=iteration_cap,
            total_runs=len(runs),
            successful_runs=successful_count,
            failed_runs=failed_count,
            blocked_runs=blocked_count,
            cross_run_contamination_detected=contamination_detected,
            duplicate_unintended_mutation_detected=duplicate_mutation_detected,
            false_ready_detected=false_ready_detected,
            historical_receipt_integrity_verified=historical_receipt_intact_all,
            predicate_correctness_verified=predicate_correctness_all,
            runs=runs,
            provenance=MeasurementProvenance.FIXTURE,
            source_sha=source_sha,
            environment=env_desc,
            qualification_status=qualification_status,
            untested_scenarios=untested,
        )
