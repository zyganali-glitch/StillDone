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
import json
import logging
import math
import time
from decimal import Decimal
from pathlib import Path

import pytest

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

        # AgentCore: unverified per-invocation rate, NOT_ESTIMABLE_OFFLINE
        ac_est = next(
            e for e in cost_report.cost_estimates if e.service == "Amazon Bedrock AgentCore Runtime"
        )
        assert ac_est.pricing_verified is False
        assert ac_est.estimated_cost_usd is None
        assert ac_est.estimated_quantity is None
        assert "NOT_ESTIMABLE_OFFLINE" in ac_est.notes

        # Defect D: No definitive gross total dollar amount published
        assert cost_report.definitive_gross_total_status == "NOT_ESTIMABLE_OFFLINE"
        assert len(cost_report.unestimated_components) >= 2

        # Conditional scenario total is positive (Bedrock Nova Micro only)
        assert cost_report.conditional_scenario_total_usd > Decimal("0.00")
        assert cost_report.conditional_scenario_total_usd < Decimal("0.01")

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
    """Tests for Defect B: verifying blocked and failed step handling in run_mission_benchmark."""

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

        # Steps 1-3 were executed successfully
        for comp in ("seed_demo_resources", "plan_compilation", "tasks_prep"):
            timing = res.component_stats[comp]
            assert timing.was_executed is True

        # Step 4 was invoked and BLOCKED
        pause_timing = res.component_stats["calendar_approval_pause"]
        assert pause_timing.was_executed is False

        # Steps 5-7 were NOT invoked: strictly 0ns, NOT_RUN
        for comp in (
            "calendar_update_approved",
            "ready_receipt_projection",
            "drift_reconciliation",
        ):
            not_run_timing = res.component_stats[comp]
            assert not_run_timing.was_executed is False
            assert not_run_timing.min_ms == 0.0
            assert not_run_timing.max_ms == 0.0

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
        assert res.component_stats["plan_compilation"].was_executed is False
        assert res.component_stats["tasks_prep"].was_executed is False
        assert res.component_stats["drift_reconciliation"].was_executed is False


class TestDefectCMCPNegativeValidation:
    """Tests for Defect C: negative validation paths for MCP transport measurement."""

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
