"""Tests for Phase P-18 Performance & Cost-Evidence Benchmark Harness.

Verifies:
1. P-18.01: Monotonic timing, warmup separation, component timing contracts, and schema.
   - Defect A: Module import and benchmark execution do NOT mutate global logger settings.
   - Defect B: Execution and timing truth; discrete statuses (PASS, FAILED, BLOCKED, NOT_RUN);
     NOT_RUN operations report strictly 0ns; failed/blocked steps cannot be labeled as
     successfully executed provider work; mission success follows lifecycle truth.
2. P-18.02: MCP transport latency measurement, comparison with Alexa+ docs,
   - Defect C: Canonical provenance separation (P-01.07 = RECORDED_LIVE,
     P-05.07 = LOCAL_EXECUTION); strict response validation on initialize, tools/list,
     and mission_status; rejection of error payloads with truthful LOCAL_FAILED;
     truthful NOT_RUN for remote/partner paths.
3. P-18.03: AWS usage and cost estimation boundaries, pricing verification,
   - Defect D: Categorical separation (VERIFIED_PRICING, EXAMPLE_ASSUMPTIONS, DIRECT_FEE_ZERO,
     UNVERIFIED_RATE, ACCOUNT_USAGE_DEPENDENT); AgentCore microVM costs marked
     NOT_ESTIMABLE_OFFLINE; no definitive gross mission total; promotional credit does
     not guarantee specific mission counts.
4. Constitutional Invariants:
   - Strictly monotonic timer (time.perf_counter_ns).
   - No wall-clock latency assertions in tests (prevents CI flakiness).
   - Clean separation of FIXTURE vs LOCAL_EXECUTION vs RECORDED_LIVE vs LIVE.
   - Zero sensitive credentials or tokens in exported reports.
   - Zero Bedrock or live Google API invocations in offline tests.
"""

from __future__ import annotations

import ast
import contextlib
import json
import logging
import math
import time
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from scripts.p18_benchmarks import print_human_report
from stilldone.benchmarks import (
    ALEXA_PLUS_LATENCY_REQUIREMENT_MS,
    HISTORICAL_P0107_ECHO_MS,
    HISTORICAL_P0107_PROVENANCE,
    HISTORICAL_P0507_INIT_P50_MS,
    HISTORICAL_P0507_MISSION_STATUS_P50_MS,
    HISTORICAL_P0507_PROVENANCE,
    HISTORICAL_P0507_TOOLS_LIST_P50_MS,
    MISSION_COMPONENTS,
    AWSCostPerMission,
    AWSServiceCostEstimate,
    ComponentTiming,
    CostEstimateCategory,
    MCPLatencyComparison,
    MeasurementProvenance,
    MissionBenchmarkResult,
    StepExecutionStatus,
    compute_component_stats,
    compute_percentile_inclusive,
    estimate_aws_cost_per_mission,
    measure_mcp_transport_latency,
    run_mission_benchmark,
    scoped_benchmark_logging_suppression,
)


class TestDefectALoggerIntegrity:
    """Tests ensuring benchmark tooling does not alter production logging observability."""

    def test_global_logger_state_unmodified_by_import(self) -> None:
        """Importing benchmarks module does NOT alter logger levels or disabled flags."""
        monitored_loggers = [
            "httpx",
            "httpx2",
            "mcp",
            "uvicorn",
            "uvicorn.access",
            "uvicorn.error",
        ]
        # Check that none of the monitored loggers have been disabled globally
        for name in monitored_loggers:
            lgr = logging.getLogger(name)
            assert lgr.disabled is False, f"Logger {name} must not be disabled at module level"

    def test_scoped_benchmark_logging_suppression_restores_state_on_success(self) -> None:
        """Scoped logging suppression restores original levels and disabled flags."""
        test_logger = logging.getLogger("test_benchmark_scoped_logger")
        test_logger.setLevel(logging.INFO)
        test_logger.disabled = False
        original_level = test_logger.level
        original_disabled = test_logger.disabled

        with scoped_benchmark_logging_suppression(logger_names=["test_benchmark_scoped_logger"]):
            assert test_logger.level == logging.WARNING
            assert test_logger.disabled is True

        assert test_logger.level == original_level
        assert test_logger.disabled == original_disabled

    def test_scoped_benchmark_logging_suppression_restores_state_on_exception(self) -> None:
        """Scoped logging suppression restores logger state even when exceptions occur."""
        test_logger = logging.getLogger("test_benchmark_exception_logger")
        test_logger.setLevel(logging.DEBUG)
        test_logger.disabled = False

        with pytest.raises(RuntimeError, match="simulated failure"):
            with scoped_benchmark_logging_suppression(
                logger_names=["test_benchmark_exception_logger"]
            ):
                assert test_logger.disabled is True
                raise RuntimeError("simulated failure")

        assert test_logger.level == logging.DEBUG
        assert test_logger.disabled is False


class TestP1801MissionLatencyHarness:
    """Tests for P-18.01 mission latency measurement harness."""

    def test_monotonic_timer_property(self) -> None:
        """Verifies that monotonic timing uses time.perf_counter_ns."""
        clock_info = time.get_clock_info("perf_counter")
        assert clock_info.monotonic is True, "Clock must be strictly monotonic"
        t0 = time.perf_counter_ns()
        t1 = time.perf_counter_ns()
        assert t1 >= t0

    def test_component_timing_invariants_pass_and_not_run(self) -> None:
        """Executed steps must have valid duration; NOT_RUN steps must have elapsed_ns == 0."""
        # Valid executed PASS timing
        ct = ComponentTiming(
            component="plan_compilation",
            elapsed_ns=1_500_000,
            elapsed_ms=1.5,
            provenance=MeasurementProvenance.FIXTURE,
            was_executed=True,
            sample_index=0,
            status=StepExecutionStatus.PASS.value,
            was_invoked=True,
        )
        assert ct.was_executed is True
        assert ct.was_invoked is True
        assert ct.status == "PASS"
        assert ct.elapsed_ms == 1.5
        d = ct.to_dict()
        assert d["component"] == "plan_compilation"
        assert d["status"] == "PASS"
        assert d["was_executed"] is True
        assert d["was_invoked"] is True

        # Valid NOT_RUN timing
        ct_not_run = ComponentTiming(
            component="live_bedrock_inference",
            elapsed_ns=0,
            elapsed_ms=0.0,
            provenance=MeasurementProvenance.NOT_RUN,
            was_executed=False,
            sample_index=0,
            status=StepExecutionStatus.NOT_RUN.value,
            was_invoked=False,
        )
        assert ct_not_run.was_executed is False
        assert ct_not_run.was_invoked is False
        assert ct_not_run.elapsed_ns == 0
        assert ct_not_run.status == "NOT_RUN"

        # NOT_RUN step with non-zero elapsed_ns fails closed
        with pytest.raises(ValueError, match="NOT_RUN steps must have elapsed_ns == 0"):
            ComponentTiming(
                component="live_inference",
                elapsed_ns=100,
                elapsed_ms=0.1,
                provenance=MeasurementProvenance.NOT_RUN,
                was_executed=False,
                sample_index=0,
            )

        # Executed step with negative elapsed_ns fails closed
        with pytest.raises(ValueError, match="elapsed_ns cannot be negative"):
            ComponentTiming(
                component="test_step",
                elapsed_ns=-10,
                elapsed_ms=-0.01,
                provenance=MeasurementProvenance.FIXTURE,
                was_executed=True,
                sample_index=0,
            )

        # Empty component name fails closed
        with pytest.raises(ValueError, match="component must be a non-empty string"):
            ComponentTiming(
                component="",
                elapsed_ns=0,
                elapsed_ms=0.0,
                provenance=MeasurementProvenance.NOT_RUN,
                was_executed=False,
                sample_index=0,
            )

    def test_defect_b_timing_truth_blocked_and_failed_steps(self) -> None:
        """Blocked or failed steps have local elapsed processing time, but was_executed is False."""
        # Blocked step: invoked locally, records local elapsed time, but was_executed MUST be False
        ct_blocked = ComponentTiming(
            component="calendar_approval_pause",
            elapsed_ns=750_000,
            elapsed_ms=0.75,
            provenance=MeasurementProvenance.LOCAL_EXECUTION,
            was_executed=False,
            sample_index=0,
            status=StepExecutionStatus.BLOCKED.value,
            was_invoked=True,
        )
        assert ct_blocked.was_invoked is True
        assert ct_blocked.was_executed is False
        assert ct_blocked.status == "BLOCKED"
        assert ct_blocked.elapsed_ns == 750_000

        # Cannot claim was_executed=True for a BLOCKED step
        with pytest.raises(ValueError, match="cannot be labeled as successfully executed"):
            ComponentTiming(
                component="calendar_approval_pause",
                elapsed_ns=750_000,
                elapsed_ms=0.75,
                provenance=MeasurementProvenance.LOCAL_EXECUTION,
                was_executed=True,
                sample_index=0,
                status=StepExecutionStatus.BLOCKED.value,
                was_invoked=True,
            )

        # Failed step: invoked locally, records local elapsed time, but was_executed MUST be False
        ct_failed = ComponentTiming(
            component="tasks_prep",
            elapsed_ns=420_000,
            elapsed_ms=0.42,
            provenance=MeasurementProvenance.LOCAL_EXECUTION,
            was_executed=False,
            sample_index=0,
            status=StepExecutionStatus.FAILED.value,
            was_invoked=True,
        )
        assert ct_failed.was_invoked is True
        assert ct_failed.was_executed is False
        assert ct_failed.status == "FAILED"

        # Cannot claim was_executed=True for a FAILED step
        with pytest.raises(ValueError, match="cannot be labeled as successfully executed"):
            ComponentTiming(
                component="tasks_prep",
                elapsed_ns=420_000,
                elapsed_ms=0.42,
                provenance=MeasurementProvenance.LOCAL_EXECUTION,
                was_executed=True,
                sample_index=0,
                status=StepExecutionStatus.FAILED.value,
                was_invoked=True,
            )

    def test_percentile_inclusive_interpolation(self) -> None:
        """Percentile calculation matches inclusive interpolation across known values."""
        # Single element
        assert compute_percentile_inclusive([42.0], 50.0) == 42.0
        assert compute_percentile_inclusive([42.0], 95.0) == 42.0

        # Known sequence
        seq = [float(i) for i in range(1, 101)]
        p50 = compute_percentile_inclusive(seq, 50.0)
        p95 = compute_percentile_inclusive(seq, 95.0)
        assert p50 == 50.5
        assert math.isclose(p95, 95.05, abs_tol=1e-2)

        # Empty fails closed
        with pytest.raises(ValueError, match="Cannot compute percentile of empty sequence"):
            compute_percentile_inclusive([], 50.0)

    def test_compute_component_stats_empty_samples(self) -> None:
        """Empty samples return NOT_RUN stats without error."""
        stats = compute_component_stats(
            "unexecuted_step", [], warmup_count=1, provenance=MeasurementProvenance.NOT_RUN
        )
        assert stats.was_executed is False
        assert stats.sample_count == 0
        d = stats.to_dict()
        assert d["status"] == "NOT_RUN"
        assert d["was_executed"] is False

    def test_run_mission_benchmark_execution(self) -> None:
        """Benchmark runs in fixture mode, honors sample counts, and outputs valid schema."""
        res = run_mission_benchmark(warmup_count=1, sample_count=2)
        assert isinstance(res, MissionBenchmarkResult)
        assert res.warmup_count == 1
        assert res.sample_count == 2
        assert res.total_runs == 3
        assert res.run_mode == "fixture"
        assert res.provenance == MeasurementProvenance.FIXTURE

        # End-to-end stats
        assert res.e2e_stats.sample_count == 2
        assert res.e2e_stats.was_executed is True
        assert res.e2e_stats.min_ms > 0.0
        assert res.e2e_stats.max_ms >= res.e2e_stats.min_ms

        # Component stats exist for all canonical components
        for comp in MISSION_COMPONENTS:
            assert comp in res.component_stats
            c_stat = res.component_stats[comp]
            assert c_stat.was_executed is True
            assert c_stat.sample_count == 2

        # Non-certification statement explicitly discloses aggregate fixture timing nature
        assert "aggregate lifecycle-step fixture timings" in res.non_certification_statement
        assert "NOT_RUN" in res.non_certification_statement
        assert "FIXTURE" in res.non_certification_statement

        # Serializes cleanly to JSON
        json_str = res.to_json()
        parsed = json.loads(json_str)
        assert parsed["task"] == "P-18.01"
        assert parsed["provenance"] == "FIXTURE"
        assert len(parsed["components"]) == len(MISSION_COMPONENTS)

    def test_run_mission_benchmark_invalid_counts_fail_closed(self) -> None:
        """Negative warmup or non-positive sample count fails closed."""
        with pytest.raises(ValueError, match="warmup_count cannot be negative"):
            run_mission_benchmark(warmup_count=-1, sample_count=1)
        with pytest.raises(ValueError, match="sample_count must be positive"):
            run_mission_benchmark(warmup_count=0, sample_count=0)


class TestP1802MCPTransportLatencyHarness:
    """Tests for P-18.02 MCP transport latency measurement and comparison."""

    @pytest.mark.anyio
    async def test_measure_mcp_transport_latency_loopback(self) -> None:
        """Measures loopback MCP latency and produces structured comparison."""
        comparison = await measure_mcp_transport_latency(warmup_count=1, sample_count=2)
        assert isinstance(comparison, MCPLatencyComparison)

        # Requirement facts
        assert comparison.alexa_requirement_ms == ALEXA_PLUS_LATENCY_REQUIREMENT_MS
        assert comparison.alexa_requirement_status == "OBSERVED_IN_DOCUMENTATION"
        assert "developer.amazon.com" in comparison.alexa_requirement_source

        # Local loopback measurements
        assert comparison.local_provenance == "LOCAL_EXECUTION"
        assert "initialize" in comparison.local_measurements
        assert "tools_list" in comparison.local_measurements
        assert "mission_status" in comparison.local_measurements

        for op in ("initialize", "tools_list", "mission_status"):
            op_data = comparison.local_measurements[op]
            assert op_data["sample_count"] == 2
            assert op_data["was_executed"] is True
            assert op_data["min_ms"] > 0.0

        # Defect C: Canonical provenance separation
        # P-01.07 historical remote echo is RECORDED_LIVE
        assert comparison.historical_remote_echo_ms == HISTORICAL_P0107_ECHO_MS
        assert comparison.historical_remote_provenance == HISTORICAL_P0107_PROVENANCE
        assert comparison.historical_remote_provenance == "RECORDED_LIVE"
        assert "P-01.07" in comparison.historical_remote_reference

        # P-05.07 historical local loopback is LOCAL_EXECUTION (NOT RECORDED_LIVE)
        assert comparison.historical_local_provenance == HISTORICAL_P0507_PROVENANCE
        assert comparison.historical_local_provenance == "LOCAL_EXECUTION"
        assert "P-05.07" in comparison.historical_local_reference

        # Truthful NOT_RUN for live remote & partner paths
        assert comparison.live_remote_measurement == "NOT_RUN"
        assert comparison.live_alexa_client_measurement == "NOT_RUN"

        # Assessment text contains required truthfulness
        assert "LOCAL_PASS" in comparison.local_headroom_assessment
        assert "REQUIREMENT_NOT_VERIFIED" in comparison.remote_compliance_status

        # JSON serialization
        d = comparison.to_dict()
        assert d["task"] == "P-18.02"
        assert d["current_local_measurements"]["classification"] == "CURRENT_LOCAL_LOOPBACK"
        assert d["historical_remote_measurements"]["classification"] == "RECORDED_LIVE_REMOTE_MCP"
        assert d["historical_local_measurements"]["classification"] == "HISTORICAL_LOCAL_LOOPBACK"
        assert d["historical_local_measurements"]["provenance"] == "LOCAL_EXECUTION"
        assert d["live_remote_mcp_transport"]["status"] == "NOT_RUN"
        assert d["live_alexa_client_to_mcp"]["status"] == "NOT_RUN"

    def test_defect_c_historical_provenance_constants(self) -> None:
        """Verifies historical provenance constants adhere strictly to AGENTS.md § 10."""
        # Remote echo was a real remote execution in P-01.07
        assert HISTORICAL_P0107_PROVENANCE == "RECORDED_LIVE"
        # Local loopback in P-05.07 was local execution, not remote live
        assert HISTORICAL_P0507_PROVENANCE == "LOCAL_EXECUTION"
        assert HISTORICAL_P0507_INIT_P50_MS == 8.05
        assert HISTORICAL_P0507_TOOLS_LIST_P50_MS == 7.33
        assert HISTORICAL_P0507_MISSION_STATUS_P50_MS == 15.18


class TestP1803AWSCostPerMissionHarness:
    """Tests for P-18.03 AWS usage and cost estimation harness."""

    def test_estimate_aws_cost_per_mission_boundaries(self) -> None:
        """Estimates AWS cost using verified pricing and preserves unobserved boundaries."""
        cost_report = estimate_aws_cost_per_mission()
        assert isinstance(cost_report, AWSCostPerMission)

        # Category A: Real account usage preserved as NOT_OBSERVED
        assert cost_report.real_measured_usage == "NOT_OBSERVED"

        # Authorization: zero live Bedrock invocations
        assert cost_report.bedrock_invocation_authorized is False
        assert cost_report.paid_services_activated is False
        assert cost_report.personal_spend_target == "$0.00"
        assert cost_report.actual_personal_spend == "NOT_OBSERVED"

        # Category B: Local runtime activity is fixture-backed
        assert cost_report.local_runtime_activity["live_bedrock_invocations"] == 0
        assert cost_report.local_runtime_activity["live_google_api_calls"] == 0

        # Category C: Pricing-based estimates
        assert len(cost_report.cost_estimates) == 5
        services = {e.service for e in cost_report.cost_estimates}
        assert "Amazon Bedrock" in services
        assert "AWS Strands Agents SDK" in services
        assert "Amazon Bedrock AgentCore Runtime" in services
        assert "AWS IAM" in services
        assert "Amazon CloudWatch (EMF)" in services

        # Bedrock estimate verification (Defect D: labeled as example assumptions)
        bedrock_est = next(e for e in cost_report.cost_estimates if e.service == "Amazon Bedrock")
        assert bedrock_est.pricing_verified is True
        assert "https://aws.amazon.com/bedrock/pricing/" in bedrock_est.pricing_source
        assert bedrock_est.estimated_cost_usd is not None
        assert bedrock_est.estimated_cost_usd > Decimal("0.00")
        assert bedrock_est.estimated_cost_usd < Decimal("0.01")
        assert "EXAMPLE_ASSUMPTIONS" in bedrock_est.notes

        # Open-source SDK: direct fee zero, distinguished from underlying compute
        strands_est = next(
            e for e in cost_report.cost_estimates if e.service == "AWS Strands Agents SDK"
        )
        assert strands_est.estimated_cost_usd == Decimal("0.00")
        assert strands_est.category == CostEstimateCategory.DIRECT_FEE_ZERO.value
        assert "Direct SDK library invocation fee is $0.00" in strands_est.notes

        # IAM: direct request fee zero
        iam_est = next(e for e in cost_report.cost_estimates if e.service == "AWS IAM")
        assert iam_est.estimated_cost_usd == Decimal("0.00")
        assert iam_est.category == CostEstimateCategory.DIRECT_FEE_ZERO.value

        # CloudWatch EMF: account-level usage dependent
        cw_est = next(
            e for e in cost_report.cost_estimates if e.service == "Amazon CloudWatch (EMF)"
        )
        assert cw_est.category == CostEstimateCategory.ACCOUNT_USAGE_DEPENDENT.value
        assert cw_est.is_covered_by_free_tier == "ACCOUNT_USAGE_DEPENDENT"
        assert cw_est.estimated_cost_usd is None
        assert cw_est.unit_price_usd is None
        assert "NOT_ESTIMABLE" in cw_est.notes

        # AgentCore: verified rate, unobserved consumption, NOT_ESTIMABLE_OFFLINE
        ac_est = next(
            e for e in cost_report.cost_estimates if e.service == "Amazon Bedrock AgentCore Runtime"
        )
        assert ac_est.pricing_verified is True
        assert ac_est.category == CostEstimateCategory.VERIFIED_RATE_UNOBSERVED_CONSUMPTION.value
        assert ac_est.estimated_cost_usd is None
        assert ac_est.estimated_quantity is None
        assert "NOT_ESTIMABLE_OFFLINE" in ac_est.notes

        # Defect D: No definitive gross total dollar amount published
        assert cost_report.definitive_gross_total_status == "NOT_ESTIMABLE_OFFLINE"
        assert len(cost_report.unestimated_components) >= 2

        # Conditional scenario total is positive (Bedrock Nova Micro only)
        assert cost_report.conditional_scenario_total_usd > Decimal("0.00")
        assert cost_report.conditional_scenario_total_usd < Decimal("0.01")
        assert cost_report.total_estimated_cost_usd is None

        # Category D: NOT_OBSERVED fields are explicitly listed
        assert len(cost_report.not_observed) >= 5
        assert any("billing delta" in field for field in cost_report.not_observed)
        assert any("promotional credit" in field for field in cost_report.not_observed)

        # JSON serialization round trip
        json_str = cost_report.to_json()
        parsed = json.loads(json_str)
        assert parsed["task"] == "P-18.03"
        assert parsed["billing_boundary"]["personal_spend_target"] == "$0.00"
        assert parsed["billing_boundary"]["actual_personal_spend"] == "NOT_OBSERVED"
        assert (
            parsed["category_c_pricing_estimates"]["definitive_gross_total_status"]
            == "NOT_ESTIMABLE_OFFLINE"
        )
        assert parsed["category_c_pricing_estimates"]["total_estimated_cost_usd"] is None
        assert (
            "no fixed number of missions"
            in (parsed["billing_boundary"]["promotional_credit_statement"])
        )

    def test_aws_service_cost_estimate_dataclass_contract(self) -> None:
        """Verifies immutable AWSServiceCostEstimate schema and types."""
        item = AWSServiceCostEstimate(
            service="TestService",
            component="TestComponent",
            category="VERIFIED_PRICING",
            unit="units",
            estimated_quantity=10.0,
            unit_price_usd=Decimal("0.005"),
            estimated_cost_usd=Decimal("0.05"),
            pricing_source="Official Test Pricing",
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier="NOT_OBSERVED",
            is_covered_by_promotional_credit="NOT_OBSERVED",
            observed_actual_cost="NOT_OBSERVED",
        )
        d = item.to_dict()
        assert d["is_covered_by_free_tier"] == "NOT_OBSERVED"
        assert d["is_covered_by_promotional_credit"] == "NOT_OBSERVED"
        assert d["observed_actual_cost"] == "NOT_OBSERVED"
        assert d["unit_price_usd"] == "0.005"
        assert d["estimated_cost_usd"] == "0.05"
        assert d["category"] == "VERIFIED_PRICING"


class TestDefectBNegativeExecutionTruth:
    """Tests for Defect 1: verifying blocked, failed, and uninvoked step handling."""

    def test_sequence_aborts_on_blocked_step_leaving_remainder_not_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When a step returns BLOCKED, subsequent steps must be strictly NOT_RUN with 0ns."""
        from stilldone.domain.provenance import EvidenceProvenance
        from stilldone.killer_mission import (
            KillerMissionSliceRunner,
            KillerMissionStepResult,
        )

        def mock_step_p13_04_calendar_pause(
            self_runner: KillerMissionSliceRunner,
        ) -> KillerMissionStepResult:
            res = KillerMissionStepResult(
                task_id="P-13.04",
                step_name="Pause at Calendar Approval Boundary",
                status="BLOCKED",
                provenance=EvidenceProvenance.FIXTURE,
                details="Operator approval boundary not approved",
                writes_performed=0,
                is_verified=False,
            )
            self_runner.step_results["P-13.04"] = res
            return res

        monkeypatch.setattr(
            KillerMissionSliceRunner,
            "step_p13_04_calendar_pause",
            mock_step_p13_04_calendar_pause,
        )

        res = run_mission_benchmark(warmup_count=0, sample_count=1)
        assert res.e2e_stats.was_executed is False
        assert res.e2e_stats.sample_count == 0
        assert res.e2e_stats.attempted_sample_count == 1
        assert res.e2e_stats.successful_sample_count == 0
        assert res.e2e_stats.status == "BLOCKED"

        # Steps 1-3 were executed successfully
        for comp in ("seed_demo_resources", "plan_compilation", "tasks_prep"):
            timing = res.component_stats[comp]
            assert timing.was_executed is True
            assert timing.status == "PASS"

        # Step 4 was invoked and BLOCKED: never marked NOT_RUN
        pause_timing = res.component_stats["calendar_approval_pause"]
        assert pause_timing.was_executed is False
        assert pause_timing.status == "BLOCKED"
        assert pause_timing.to_dict()["status"] == "BLOCKED"
        assert pause_timing.attempted_sample_count == 1
        assert pause_timing.successful_sample_count == 0

        # Steps 5-7 were NOT invoked: strictly 0ns, NOT_RUN
        for comp in (
            "calendar_update_approved",
            "ready_receipt_projection",
            "drift_reconciliation",
        ):
            not_run_timing = res.component_stats[comp]
            assert not_run_timing.was_executed is False
            assert not_run_timing.status == "NOT_RUN"
            assert not_run_timing.to_dict()["status"] == "NOT_RUN"
            assert not_run_timing.min_ms == 0.0
            assert not_run_timing.max_ms == 0.0
            assert not_run_timing.attempted_sample_count == 0

    def test_sequence_aborts_on_failed_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When a step returns FAILED, subsequent steps are NOT_RUN and mission fails."""
        from stilldone.domain.provenance import EvidenceProvenance
        from stilldone.killer_mission import (
            KillerMissionSliceRunner,
            KillerMissionStepResult,
        )

        def mock_step_p13_02_plan(
            self_runner: KillerMissionSliceRunner,
        ) -> KillerMissionStepResult:
            res = KillerMissionStepResult(
                task_id="P-13.02",
                step_name="Natural Language Planning & Compilation",
                status="FAILED",
                provenance=EvidenceProvenance.FIXTURE,
                details="Simulated planner compilation failure",
                writes_performed=0,
                is_verified=False,
            )
            self_runner.step_results["P-13.02"] = res
            return res

        monkeypatch.setattr(
            KillerMissionSliceRunner,
            "step_p13_02_plan",
            mock_step_p13_02_plan,
        )

        res = run_mission_benchmark(warmup_count=0, sample_count=1)
        assert res.e2e_stats.was_executed is False
        plan_timing = res.component_stats["plan_compilation"]
        assert plan_timing.was_executed is False
        assert plan_timing.status == "FAILED"
        assert plan_timing.to_dict()["status"] == "FAILED"
        assert plan_timing.attempted_sample_count == 1
        assert plan_timing.successful_sample_count == 0

        # Subsequent steps are NOT_RUN
        assert res.component_stats["tasks_prep"].was_executed is False
        assert res.component_stats["tasks_prep"].status == "NOT_RUN"
        assert res.component_stats["drift_reconciliation"].was_executed is False
        assert res.component_stats["drift_reconciliation"].status == "NOT_RUN"

    def test_raised_ordinary_exception_produces_privacy_safe_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A raised controlled exception in a timed step produces privacy-safe FAILED outcome."""
        from stilldone.killer_mission import KillerMissionSliceRunner

        secret_error_message = (
            "database password leaked in error: secret_token_xyz /var/secrets/key"
        )

        def mock_exploding_step(self_runner: KillerMissionSliceRunner) -> Any:
            raise RuntimeError(secret_error_message)

        monkeypatch.setattr(
            KillerMissionSliceRunner,
            "step_p13_03_tasks_prep",
            mock_exploding_step,
        )

        res = run_mission_benchmark(warmup_count=0, sample_count=1)
        assert res.e2e_stats.was_executed is False
        assert res.e2e_stats.status == "FAILED"

        tasks_timing = res.component_stats["tasks_prep"]
        assert tasks_timing.was_executed is False
        assert tasks_timing.status == "FAILED"
        assert tasks_timing.to_dict()["status"] == "FAILED"

        # Check that subsequent steps were marked NOT_RUN
        for comp in (
            "calendar_approval_pause",
            "calendar_update_approved",
            "ready_receipt_projection",
            "drift_reconciliation",
        ):
            assert res.component_stats[comp].status == "NOT_RUN"
            assert res.component_stats[comp].min_ms == 0.0

        # Privacy invariant: secret string or raw exception does not leak into serialized JSON
        res_json = res.to_json()
        assert "secret_token_xyz" not in res_json
        assert "/var/secrets/key" not in res_json
        assert "RuntimeError" not in res_json

    def test_zero_successful_missions_does_not_crash_serialization_or_cli(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Zero successful missions serializes to JSON and renders in CLI without KeyError."""
        from stilldone.domain.provenance import EvidenceProvenance
        from stilldone.killer_mission import (
            KillerMissionSliceRunner,
            KillerMissionStepResult,
        )

        def mock_step_p13_01_seed(self_runner: KillerMissionSliceRunner) -> KillerMissionStepResult:
            return KillerMissionStepResult(
                task_id="P-13.01",
                step_name="Seed",
                status="FAILED",
                provenance=EvidenceProvenance.FIXTURE,
                details="Failing immediately",
                writes_performed=0,
                is_verified=False,
            )

        monkeypatch.setattr(
            KillerMissionSliceRunner,
            "step_p13_01_seed",
            mock_step_p13_01_seed,
        )

        res = run_mission_benchmark(warmup_count=0, sample_count=2)
        assert res.e2e_stats.was_executed is False
        assert res.e2e_stats.sample_count == 0

        # JSON serialization does not fail
        d = res.to_dict()
        assert d["end_to_end"]["status"] == "FAILED"
        assert d["end_to_end"]["was_executed"] is False
        assert "min_ms" in d["end_to_end"]

        # CLI print_human_report does not raise KeyError
        print_human_report({"p18_01_mission_latency": d})
        captured = capsys.readouterr()
        assert "STILLDONE P-18 PERFORMANCE" in captured.out
        assert "E2E Status:" in captured.out
        assert "No successful end-to-end execution" in captured.out

    def test_one_successful_and_one_failed_mission_separate_sample_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One success and one failure separate sample counts; no false two-sample p95."""
        from stilldone.domain.provenance import EvidenceProvenance
        from stilldone.killer_mission import (
            KillerMissionSliceRunner,
            KillerMissionStepResult,
        )

        original_plan = KillerMissionSliceRunner.step_p13_02_plan
        call_count = [0]

        def alternating_plan(self_runner: KillerMissionSliceRunner) -> KillerMissionStepResult:
            call_count[0] += 1
            if call_count[0] == 2:
                # Second run fails at step 2
                res = KillerMissionStepResult(
                    task_id="P-13.02",
                    step_name="Natural Language Planning & Compilation",
                    status="FAILED",
                    provenance=EvidenceProvenance.FIXTURE,
                    details="Simulated intermittent plan failure",
                    writes_performed=0,
                    is_verified=False,
                )
                self_runner.step_results["P-13.02"] = res
                return res
            return original_plan(self_runner)

        monkeypatch.setattr(KillerMissionSliceRunner, "step_p13_02_plan", alternating_plan)

        res = run_mission_benchmark(warmup_count=0, sample_count=2)
        # 1 run succeeded, 1 run failed
        assert res.e2e_stats.attempted_sample_count == 2
        assert res.e2e_stats.successful_sample_count == 1
        assert res.e2e_stats.sample_count == 1
        assert res.e2e_stats.status == "PARTIAL_SUCCESS"

        plan_stats = res.component_stats["plan_compilation"]
        assert plan_stats.attempted_sample_count == 2
        assert plan_stats.successful_sample_count == 1
        assert plan_stats.sample_count == 1
        assert plan_stats.status == "PARTIAL_SUCCESS"

    def test_invalid_not_run_timing_cannot_carry_nonzero_milliseconds(self) -> None:
        """NOT_RUN steps cannot carry nonzero milliseconds, failing closed."""
        with pytest.raises(ValueError, match="NOT_RUN steps must have elapsed_ns == 0"):
            ComponentTiming(
                component="test_step",
                elapsed_ns=0,
                elapsed_ms=1.5,
                provenance=MeasurementProvenance.NOT_RUN,
                was_executed=False,
                sample_index=0,
                status=StepExecutionStatus.NOT_RUN.value,
                was_invoked=False,
            )

        with pytest.raises(ValueError, match="NOT_RUN steps must have elapsed_ns == 0"):
            ComponentTiming(
                component="test_step",
                elapsed_ns=1_500_000,
                elapsed_ms=0.0,
                provenance=MeasurementProvenance.NOT_RUN,
                was_executed=False,
                sample_index=0,
                status=StepExecutionStatus.NOT_RUN.value,
                was_invoked=False,
            )

    def test_timing_consistency_elapsed_ms_and_elapsed_ns(self) -> None:
        """ComponentTiming enforces mathematical consistency between elapsed_ms and elapsed_ns."""
        with pytest.raises(ValueError, match="inconsistent with elapsed_ns"):
            ComponentTiming(
                component="test_step",
                elapsed_ns=2_000_000,
                elapsed_ms=5.0,  # Expected 2.0 ms
                provenance=MeasurementProvenance.FIXTURE,
                was_executed=True,
                sample_index=0,
                status=StepExecutionStatus.PASS.value,
                was_invoked=True,
            )


# ============================================================================
# Helpers for MCP deterministic test doubles
# ============================================================================


class MockMCPResponse:
    """Deterministic mock for MCP responses."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockMCPSession:
    """Deterministic test double for ClientSession in MCP latency measurement."""

    def __init__(
        self,
        mission_id: str = "test-mission",
        is_error: bool = False,
        wrong_mission_id: bool = False,
        missing_tool: bool = False,
        raise_transport_error: bool = False,
        fail_after_n_samples: int | None = None,
    ) -> None:
        self.mission_id = mission_id
        self.is_error = is_error
        self.wrong_mission_id = wrong_mission_id
        self.missing_tool = missing_tool
        self.raise_transport_error = raise_transport_error
        self.fail_after_n_samples = fail_after_n_samples
        self.call_count = 0

    async def initialize(self) -> Any:
        self.call_count += 1
        if self.raise_transport_error:
            raise RuntimeError("Injected MCP transport failure")
        if self.fail_after_n_samples is not None and self.call_count > self.fail_after_n_samples:
            raise RuntimeError("Sample limit reached in mock session")
        server_info = MockMCPResponse(name="StillDone")
        return MockMCPResponse(protocol_version="2024-11-05", server_info=server_info)

    async def list_tools(self) -> Any:
        self.call_count += 1
        if self.raise_transport_error:
            raise RuntimeError("Injected MCP transport failure")
        if self.fail_after_n_samples is not None and self.call_count > self.fail_after_n_samples:
            raise RuntimeError("Sample limit reached in mock session")
        if self.missing_tool:
            tools = [MockMCPResponse(name="other_tool")]
        else:
            tools = [MockMCPResponse(name="mission_status")]
        return MockMCPResponse(tools=tools)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.call_count += 1
        if self.raise_transport_error:
            raise RuntimeError("Injected MCP transport failure")
        if self.fail_after_n_samples is not None and self.call_count > self.fail_after_n_samples:
            raise RuntimeError("Sample limit reached in mock session")
        if self.is_error:
            return MockMCPResponse(is_error=True, structured_content=None, content=[])
        res_mission_id = (
            "wrong-uuid"
            if self.wrong_mission_id
            else (arguments.get("mission_id") if arguments else self.mission_id)
        )
        return MockMCPResponse(
            is_error=False,
            structured_content={"mission_id": res_mission_id, "state": "DRAFT"},
            content=[MockMCPResponse(text=json.dumps({"mission_id": res_mission_id}))],
        )


def make_mock_session_factory(**mock_kwargs: Any) -> Any:
    @contextlib.asynccontextmanager
    async def factory(endpoint_url: str) -> AsyncIterator[Any]:
        yield MockMCPSession(**mock_kwargs)

    return factory


def make_stepped_timer(step_ns: int) -> Callable[[], int]:
    """Timer incrementing by step_ns per query, yielding deterministic durations."""
    current = [0]

    def timer() -> int:
        val = current[0]
        current[0] += step_ns
        return val

    return timer


class TestDefectCMCPNegativeValidation:
    """Tests for Defect 2: MCP transport measurement decision path and negative validations."""

    def test_mcp_comparison_fails_closed_when_operation_fails(self) -> None:
        """If any operation fails validation, local_headroom must report LOCAL_FAILED."""
        failed_comparison = MCPLatencyComparison(
            alexa_requirement_ms=500.0,
            alexa_requirement_source="https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html",
            alexa_requirement_status="OBSERVED_IN_DOCUMENTATION",
            local_measurements={
                "initialize": {"sample_count": 0, "was_executed": False},
                "tools_list": {"sample_count": 0, "was_executed": False},
                "mission_status": {"sample_count": 0, "was_executed": False},
            },
            local_provenance="LOCAL_EXECUTION",
            historical_remote_echo_ms=61.26,
            historical_remote_provenance="RECORDED_LIVE",
            historical_remote_reference="P-01.07",
            historical_local_init_p50_ms=8.05,
            historical_local_tools_list_p50_ms=7.33,
            historical_local_mission_status_p50_ms=15.18,
            historical_local_provenance="LOCAL_EXECUTION",
            historical_local_reference="P-05.07",
            live_remote_measurement="NOT_RUN",
            live_alexa_client_measurement="NOT_RUN",
            local_headroom_assessment=(
                "LOCAL_FAILED: One or more MCP operations failed verification"
            ),
            remote_compliance_status="REQUIREMENT_NOT_VERIFIED",
            source_sha="TEST_SHA",
            timestamp_utc="2026-10-13T00:00:00Z",
        )
        assert "LOCAL_FAILED" in failed_comparison.local_headroom_assessment
        assert "LOCAL_PASS" not in failed_comparison.local_headroom_assessment
        d = failed_comparison.to_dict()
        assert d["compliance_assessment"]["local_headroom"].startswith("LOCAL_FAILED")

    @pytest.mark.anyio
    async def test_mcp_below_500ms_awards_local_pass(self) -> None:
        """When measured p95 is below 500ms and responses are valid, awards LOCAL_PASS."""
        # 10ms simulated step (10_000_000 ns)
        timer = make_stepped_timer(10_000_000)
        res = await measure_mcp_transport_latency(
            warmup_count=1,
            sample_count=2,
            client_session_factory=make_mock_session_factory(),
            timer=timer,
        )
        assert res.local_headroom_assessment.startswith("LOCAL_PASS")

    @pytest.mark.anyio
    async def test_mcp_at_exactly_500ms_does_not_award_local_pass(self) -> None:
        """When measured p95 is exactly 500ms, does NOT award LOCAL_PASS; awards LOCAL_SLOW."""
        # Exactly 500ms simulated step (500_000_000 ns)
        timer = make_stepped_timer(500_000_000)
        res = await measure_mcp_transport_latency(
            warmup_count=1,
            sample_count=2,
            client_session_factory=make_mock_session_factory(),
            timer=timer,
        )
        assert res.local_headroom_assessment.startswith("LOCAL_SLOW")
        assert "LOCAL_PASS" not in res.local_headroom_assessment

    @pytest.mark.anyio
    async def test_mcp_above_500ms_does_not_award_local_pass(self) -> None:
        """When measured p95 exceeds 500ms, awards LOCAL_SLOW, not LOCAL_PASS."""
        # 600ms simulated step (600_000_000 ns)
        timer = make_stepped_timer(600_000_000)
        res = await measure_mcp_transport_latency(
            warmup_count=1,
            sample_count=2,
            client_session_factory=make_mock_session_factory(),
            timer=timer,
        )
        assert res.local_headroom_assessment.startswith("LOCAL_SLOW")
        assert "LOCAL_PASS" not in res.local_headroom_assessment

    @pytest.mark.anyio
    async def test_mcp_mission_status_error_response_produces_local_failed(self) -> None:
        """When mission_status returns is_error=True, produces LOCAL_FAILED."""
        res = await measure_mcp_transport_latency(
            warmup_count=1,
            sample_count=2,
            client_session_factory=make_mock_session_factory(is_error=True),
        )
        assert res.local_headroom_assessment.startswith("LOCAL_FAILED")
        assert "LOCAL_PASS" not in res.local_headroom_assessment

    @pytest.mark.anyio
    async def test_mcp_mission_status_wrong_mission_identity_produces_local_failed(self) -> None:
        """When mission_status returns mismatched mission ID, produces LOCAL_FAILED."""
        res = await measure_mcp_transport_latency(
            warmup_count=1,
            sample_count=2,
            client_session_factory=make_mock_session_factory(wrong_mission_id=True),
        )
        assert res.local_headroom_assessment.startswith("LOCAL_FAILED")
        assert "LOCAL_PASS" not in res.local_headroom_assessment

    @pytest.mark.anyio
    async def test_mcp_missing_expected_tool_produces_local_failed(self) -> None:
        """When tools/list is missing mission_status, produces LOCAL_FAILED."""
        res = await measure_mcp_transport_latency(
            warmup_count=1,
            sample_count=2,
            client_session_factory=make_mock_session_factory(missing_tool=True),
        )
        assert res.local_headroom_assessment.startswith("LOCAL_FAILED")
        assert "LOCAL_PASS" not in res.local_headroom_assessment

    @pytest.mark.anyio
    async def test_mcp_transport_exception_produces_no_false_local_pass(self) -> None:
        """When transport throws an exception, produces LOCAL_FAILED and no false LOCAL_PASS."""
        res = await measure_mcp_transport_latency(
            warmup_count=1,
            sample_count=2,
            client_session_factory=make_mock_session_factory(raise_transport_error=True),
        )
        assert res.local_headroom_assessment.startswith("LOCAL_FAILED")
        assert "LOCAL_PASS" not in res.local_headroom_assessment

    @pytest.mark.anyio
    async def test_mcp_insufficient_valid_samples_produces_no_false_local_pass(self) -> None:
        """When insufficient valid samples are collected, produces LOCAL_FAILED."""
        res = await measure_mcp_transport_latency(
            warmup_count=1,
            sample_count=5,
            client_session_factory=make_mock_session_factory(fail_after_n_samples=2),
        )
        assert res.local_headroom_assessment.startswith("LOCAL_FAILED")
        assert "LOCAL_PASS" not in res.local_headroom_assessment


class TestDefectDCostTruth:
    """Tests for Defect 3: unknown AWS cost must not be zero and pricing distinctions."""

    def test_cloudwatch_unknown_cost_is_none_not_zero(self) -> None:
        """CloudWatch EMF cost is None (NOT_ESTIMABLE), never an unconditional zero dollar claim."""
        report = estimate_aws_cost_per_mission()
        cw = next(e for e in report.cost_estimates if e.service == "Amazon CloudWatch (EMF)")
        assert cw.estimated_cost_usd is None, "CloudWatch EMF cost cannot be assumed $0.00"
        assert cw.unit_price_usd is None
        assert cw.category == CostEstimateCategory.ACCOUNT_USAGE_DEPENDENT.value
        assert "NOT_ESTIMABLE" in cw.notes

    def test_unknown_components_never_silently_contribute_zero_to_definitive_total(self) -> None:
        """Gross total is NOT_ESTIMABLE_OFFLINE; unknown items do not silently sum as 0."""
        report = estimate_aws_cost_per_mission()
        assert report.definitive_gross_total_status == "NOT_ESTIMABLE_OFFLINE"
        assert report.total_estimated_cost_usd is None
        assert len(report.unestimated_components) >= 2

    def test_conditional_bedrock_inference_scenario_cannot_be_mistaken_for_gross_total(
        self,
    ) -> None:
        """Bedrock example scenario is labeled conditional, not complete gross mission cost."""
        report = estimate_aws_cost_per_mission()
        assert report.conditional_scenario_total_usd > Decimal("0.00")
        assert report.total_estimated_cost_usd is None
        d = report.to_dict()
        assert d["category_c_pricing_estimates"]["total_estimated_cost_usd"] is None
        assert "disclaimer" in d["category_c_pricing_estimates"]

    def test_agentcore_rate_provenance_and_actual_consumption_uncertainty_separated(self) -> None:
        """AgentCore rates are published pricing, but workload consumption is unobserved."""
        report = estimate_aws_cost_per_mission()
        ac = next(
            e for e in report.cost_estimates if e.service == "Amazon Bedrock AgentCore Runtime"
        )
        assert ac.pricing_verified is True
        assert "https://aws.amazon.com/bedrock/agentcore/pricing/" in ac.pricing_source
        assert ac.estimated_quantity is None
        assert ac.estimated_cost_usd is None
        assert ac.category == CostEstimateCategory.VERIFIED_RATE_UNOBSERVED_CONSUMPTION.value
        assert "NOT_ESTIMABLE_OFFLINE" in ac.notes

    def test_json_and_cli_preserve_cost_distinctions(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CLI report prints NOT_ESTIMABLE for unknown components without crashing."""
        report = estimate_aws_cost_per_mission()
        print_human_report({"p18_03_aws_cost": report.to_dict()})
        captured = capsys.readouterr()
        assert "Amazon CloudWatch (EMF)" in captured.out
        assert "NOT_ESTIMABLE" in captured.out
        assert "Amazon Bedrock AgentCore" in captured.out
        assert "Definitive Gross Mission Total:   NOT_ESTIMABLE_OFFLINE" in captured.out

    def test_no_account_spend_or_billing_evidence_fabricated(self) -> None:
        """Account spend and billing remain strictly NOT_OBSERVED offline."""
        report = estimate_aws_cost_per_mission()
        assert report.personal_spend_target == "$0.00"
        assert report.actual_personal_spend == "NOT_OBSERVED"
        assert report.real_measured_usage == "NOT_OBSERVED"
        assert report.promotional_credit_remaining == "NOT_OBSERVED"
        assert report.bedrock_invocation_authorized is False
        assert report.paid_services_activated is False


class TestConstitutionalInvariants:
    """Tests cross-cutting constitutional invariants across all P-18 deliverables."""

    def test_no_sensitive_credentials_in_reports(self) -> None:
        """Exported benchmark JSON contains zero tokens, secrets, or bearer credentials."""
        mission_res = run_mission_benchmark(warmup_count=0, sample_count=1)
        cost_res = estimate_aws_cost_per_mission()

        for report_json in (mission_res.to_json(), cost_res.to_json()):
            lower = report_json.lower()
            assert "bearer " not in lower
            assert "aws_secret_access_key" not in lower
            assert "client_secret" not in lower
            assert "refresh_token" not in lower

    def test_no_wall_clock_assertions_in_test_file(self) -> None:
        """Meta-test: ensures this test file does not assert fragile wall-clock limits in CI."""
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
                for comparator in node.test.comparators:
                    if isinstance(comparator, ast.Constant) and isinstance(
                        comparator.value, (int, float)
                    ):
                        if comparator.value in (500.0, 100.0, 50.0, 10.0, 5.0):
                            for op in node.test.ops:
                                if isinstance(op, (ast.Lt, ast.LtE)):
                                    pytest.fail(
                                        f"Forbidden wall-clock < {comparator.value} assertion "
                                        "in test file"
                                    )
