"""Tests for Phase P-18 Performance & Cost-Evidence Benchmark Harness.

Verifies:
1. P-18.01: Monotonic timing, warmup separation, component timing contracts, and schema.
2. P-18.02: Local MCP loopback transport latency measurement, comparison with Alexa+ docs,
            and truthful NOT_RUN for unexecuted remote / partner paths.
3. P-18.03: AWS usage and cost estimation boundaries, pricing verification, Category A vs C,
            NOT_OBSERVED account spend preservation, and $0.00 personal spend policy.
4. Constitutional Invariants:
   - Monotonic timer (time.perf_counter_ns).
   - No wall-clock latency assertions in tests (prevents CI flakiness).
   - NOT_RUN steps report no duration.
   - Clean separation of FIXTURE vs LOCAL_EXECUTION vs RECORDED_LIVE vs LIVE.
   - Zero sensitive credentials or tokens in exported reports.
   - Zero Bedrock or live Google API invocations in offline tests.
"""

from __future__ import annotations

import json
import math
import time
from decimal import Decimal

import pytest

from stilldone.benchmarks import (
    ALEXA_PLUS_LATENCY_REQUIREMENT_MS,
    HISTORICAL_P0107_ECHO_MS,
    MISSION_COMPONENTS,
    AWSCostPerMission,
    AWSServiceCostEstimate,
    ComponentTiming,
    MCPLatencyComparison,
    MeasurementProvenance,
    MissionBenchmarkResult,
    compute_component_stats,
    compute_percentile_inclusive,
    estimate_aws_cost_per_mission,
    measure_mcp_transport_latency,
    run_mission_benchmark,
)


class TestP1801MissionLatencyHarness:
    """Tests for P-18.01 mission latency measurement harness."""

    def test_monotonic_timer_property(self) -> None:
        """Verifies that monotonic timing uses time.perf_counter_ns."""
        clock_info = time.get_clock_info("perf_counter")
        assert clock_info.monotonic is True, "Clock must be strictly monotonic"
        t0 = time.perf_counter_ns()
        t1 = time.perf_counter_ns()
        assert t1 >= t0

    def test_component_timing_invariants(self) -> None:
        """Executed steps must have valid duration; NOT_RUN steps must have elapsed_ns == 0."""
        # Valid executed timing
        ct = ComponentTiming(
            component="plan_compilation",
            elapsed_ns=1_500_000,
            elapsed_ms=1.5,
            provenance=MeasurementProvenance.FIXTURE,
            was_executed=True,
            sample_index=0,
        )
        assert ct.was_executed is True
        assert ct.elapsed_ms == 1.5
        d = ct.to_dict()
        assert d["component"] == "plan_compilation"
        assert d["was_executed"] is True

        # Valid NOT_RUN timing
        ct_not_run = ComponentTiming(
            component="live_bedrock_inference",
            elapsed_ns=0,
            elapsed_ms=0.0,
            provenance=MeasurementProvenance.NOT_RUN,
            was_executed=False,
            sample_index=0,
        )
        assert ct_not_run.was_executed is False
        assert ct_not_run.elapsed_ns == 0

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

        # Non-certification statement is present
        assert "FIXTURE" in res.non_certification_statement
        assert "NOT_RUN" in res.non_certification_statement

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

        # Historical recorded-live remote data preserved
        assert comparison.historical_remote_echo_ms == HISTORICAL_P0107_ECHO_MS
        assert comparison.historical_remote_provenance == "RECORDED_LIVE"

        # Truthful NOT_RUN for live remote & partner paths
        assert comparison.live_remote_measurement == "NOT_RUN"
        assert comparison.live_alexa_client_measurement == "NOT_RUN"

        # Assessment text contains required truthfulness
        assert "LOCAL_PASS" in comparison.local_headroom_assessment
        assert "REQUIREMENT_NOT_VERIFIED" in comparison.remote_compliance_status

        # JSON serialization
        d = comparison.to_dict()
        assert d["task"] == "P-18.02"
        assert d["historical_remote_measurements"]["p0107_echo_ms"] == 61.26
        assert d["live_remote_mcp_transport"]["status"] == "NOT_RUN"
        assert d["live_alexa_client_to_mcp"]["status"] == "NOT_RUN"


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

        # Bedrock estimate verification
        bedrock_est = next(e for e in cost_report.cost_estimates if e.service == "Amazon Bedrock")
        assert bedrock_est.pricing_verified is True
        assert "https://aws.amazon.com/bedrock/pricing/" in bedrock_est.pricing_source
        assert bedrock_est.estimated_cost_usd > Decimal("0.00")
        assert bedrock_est.estimated_cost_usd < Decimal("0.01")  # Fractions of a cent

        # Open-source SDK has zero charge
        strands_est = next(
            e for e in cost_report.cost_estimates if e.service == "AWS Strands Agents SDK"
        )
        assert strands_est.estimated_cost_usd == Decimal("0.00")
        assert strands_est.is_covered_by_free_tier is True

        # IAM has zero charge
        iam_est = next(e for e in cost_report.cost_estimates if e.service == "AWS IAM")
        assert iam_est.estimated_cost_usd == Decimal("0.00")

        # Total estimated cost is positive but minuscule (well within hackathon credit)
        assert cost_report.total_estimated_cost_usd > Decimal("0.00")
        assert cost_report.total_estimated_cost_usd < Decimal("0.01")

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

    def test_aws_service_cost_estimate_dataclass_contract(self) -> None:
        """Verifies immutable AWSServiceCostEstimate schema and types."""
        item = AWSServiceCostEstimate(
            service="TestService",
            component="TestComponent",
            unit="units",
            estimated_quantity=10.0,
            unit_price_usd=Decimal("0.005"),
            estimated_cost_usd=Decimal("0.05"),
            pricing_source="Official Test Pricing",
            pricing_verified=True,
            pricing_verification_date="2026-10-01",
            is_covered_by_free_tier=None,
            is_covered_by_promotional_credit=None,
            observed_actual_cost="NOT_OBSERVED",
        )
        d = item.to_dict()
        assert d["is_covered_by_free_tier"] == "NOT_OBSERVED"
        assert d["is_covered_by_promotional_credit"] == "NOT_OBSERVED"
        assert d["observed_actual_cost"] == "NOT_OBSERVED"
        assert d["unit_price_usd"] == "0.005"
        assert d["estimated_cost_usd"] == "0.05"


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
        import ast
        from pathlib import Path

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
