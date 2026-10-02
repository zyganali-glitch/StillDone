"""Tests for deterministic MCP protocol latency measurement utility.

Phase P-05.07 Requirements:
1. Measurement uses monotonic high-resolution timer.
2. Correct operation labels ("initialize", "tools/list", "mission_status").
3. Requested sample count is honored.
4. Percentile calculation is deterministic across known distributions.
5. Failure samples are not silently reported as successes.
6. Output schema is deterministic and complete.
7. No external provider / model calls occur.
8. No wall-clock latency thresholds asserted in CI to prevent flaky tests.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import math
import sys
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def _cleanup_mcp_sys_modules() -> Generator[None, None, None]:
    """Module-level cleanup to keep sys.modules pure after MCP server tests finish."""
    yield
    mcp_keys = [
        k
        for k in list(sys.modules.keys())
        if k == "mcp"
        or k.startswith("mcp.")
        or k.startswith("mcp_")
        or k.startswith("stilldone.mcp")
        or k == "measure_mcp_latency"
    ]
    for k in mcp_keys:
        sys.modules.pop(k, None)


def _get_latency_module() -> Any:
    """Lazily load scripts/measure_mcp_latency.py at test runtime (not collection time)."""
    if "measure_mcp_latency" in sys.modules:
        return sys.modules["measure_mcp_latency"]
    _script_path = Path(__file__).parent.parent / "scripts" / "measure_mcp_latency.py"
    _spec = importlib.util.spec_from_file_location("measure_mcp_latency", _script_path)
    assert _spec is not None and _spec.loader is not None
    _latency_mod = importlib.util.module_from_spec(_spec)
    sys.modules["measure_mcp_latency"] = _latency_mod
    _spec.loader.exec_module(_latency_mod)
    return _latency_mod


class TestMCPLatencyMeasurementUtility:
    """Verify measurement mechanics, schema determinism, and safety boundaries."""

    def test_01_timer_monotonic_high_resolution(self) -> None:
        """1. Measurement uses monotonic high-resolution clock."""
        mod = _get_latency_module()
        clock_info = time.get_clock_info("perf_counter")
        assert clock_info.monotonic is True, "Clock must be strictly monotonic"
        assert clock_info.resolution < 1e-6, "Clock resolution must be sub-microsecond"

        # Verify time.perf_counter_ns monotonicity
        t0 = time.perf_counter_ns()
        t1 = time.perf_counter_ns()
        assert t1 >= t0, "time.perf_counter_ns must be monotonically non-decreasing"

        # Verify measurement functions default to time.perf_counter_ns
        for fn in (
            mod.measure_initialize_round_trips,
            mod.measure_tools_list_round_trips,
            mod.measure_mission_status_round_trips,
            mod.run_latency_campaign,
        ):
            sig = inspect.signature(fn)
            assert "timer" in sig.parameters, f"{fn.__name__} must accept a timer parameter"
            assert sig.parameters["timer"].default == time.perf_counter_ns

    def test_02_correct_operation_labels(self) -> None:
        """2. Operation labels are correctly assigned and validated."""
        mod = _get_latency_module()
        for label in ("initialize", "tools/list", "mission_status"):
            metrics = mod.compute_latency_metrics(label, [10.0, 12.0, 15.0], warmup_count=2)
            assert metrics.operation == label
            assert metrics.to_dict()["operation"] == label

        # Empty or whitespace labels fail closed
        with pytest.raises(ValueError, match="operation must be a non-empty string"):
            mod.compute_latency_metrics("", [10.0], warmup_count=1)

        with pytest.raises(ValueError, match="operation must be a non-empty string"):
            mod.compute_latency_metrics("   ", [10.0], warmup_count=1)

    @pytest.mark.anyio
    async def test_03_requested_sample_count_honored(self) -> None:
        """3. Requested sample and warmup counts are honored during campaign execution."""
        mod = _get_latency_module()
        # Execute minimal fast campaign: 1 warmup, 2 measured samples
        result = await mod.run_latency_campaign(warmup_count=1, sample_count=2)

        assert isinstance(result, mod.CampaignResult)
        assert set(result.operations.keys()) == {"initialize", "tools/list", "mission_status"}

        for op_name, metrics in result.operations.items():
            assert metrics.operation == op_name
            assert metrics.sample_count == 2, f"{op_name} sample_count mismatch"
            assert metrics.warmup_count == 1, f"{op_name} warmup_count mismatch"
            assert metrics.min_ms > 0.0
            assert metrics.max_ms >= metrics.min_ms
            assert metrics.p50_ms >= metrics.min_ms
            assert metrics.p95_ms >= metrics.p50_ms

        # Invalid counts fail closed
        with pytest.raises(ValueError, match="warmup_count cannot be negative"):
            await mod.run_latency_campaign(warmup_count=-1, sample_count=1)

        with pytest.raises(ValueError, match="sample_count must be positive"):
            await mod.run_latency_campaign(warmup_count=0, sample_count=0)

    def test_04_percentile_calculation_deterministic(self) -> None:
        """4. Percentile calculation is deterministic across known distributions."""
        mod = _get_latency_module()

        # Case A: Single item
        single_val = [42.0]
        m_single = mod.compute_latency_metrics("test", single_val, warmup_count=0)
        assert m_single.min_ms == 42.0
        assert m_single.max_ms == 42.0
        assert m_single.mean_ms == 42.0
        assert m_single.p50_ms == 42.0
        assert m_single.p95_ms == 42.0

        # Case B: 30 sequential numbers 1.0 to 30.0
        seq30 = [float(i) for i in range(1, 31)]
        m_seq = mod.compute_latency_metrics("test", seq30, warmup_count=5)
        assert m_seq.sample_count == 30
        assert m_seq.warmup_count == 5
        assert m_seq.min_ms == 1.0
        assert m_seq.max_ms == 30.0
        assert m_seq.mean_ms == 15.5
        assert m_seq.p50_ms == 15.5
        assert math.isclose(m_seq.p95_ms, 28.55, abs_tol=1e-5)

        # Case C: Two elements
        two_vals = [10.0, 20.0]
        m_two = mod.compute_latency_metrics("test", two_vals, warmup_count=0)
        assert m_two.min_ms == 10.0
        assert m_two.max_ms == 20.0
        assert m_two.mean_ms == 15.0
        assert m_two.p50_ms == 15.0
        assert math.isclose(m_two.p95_ms, 19.5, abs_tol=1e-5)

        # Case D: Identical elements
        identical = [7.5, 7.5, 7.5, 7.5]
        m_id = mod.compute_latency_metrics("test", identical, warmup_count=1)
        assert m_id.min_ms == 7.5
        assert m_id.max_ms == 7.5
        assert m_id.mean_ms == 7.5
        assert m_id.p50_ms == 7.5
        assert m_id.p95_ms == 7.5

        # Empty sequence raises ValueError
        with pytest.raises(ValueError, match="Cannot compute percentile of empty sequence"):
            mod.compute_percentile([], 95.0)

    def test_05_failure_samples_not_silently_reported_as_successes(self) -> None:
        """5. Failure samples raise exceptions and are not silently reported as successes."""
        mod = _get_latency_module()

        # Empty samples fail closed
        with pytest.raises(ValueError, match="samples_ms sequence cannot be empty"):
            mod.compute_latency_metrics("test", [], warmup_count=0)

        # Negative sample duration fails closed
        with pytest.raises(ValueError, match="Invalid non-negative sample duration"):
            mod.compute_latency_metrics("test", [10.0, -1.0, 5.0], warmup_count=0)

    @pytest.mark.anyio
    async def test_05b_tool_call_error_raises_latency_measurement_error(self) -> None:
        """5b. Tool call errors raise LatencyMeasurementError instead of recording success."""
        mod = _get_latency_module()

        mock_result = MagicMock()
        mock_result.is_error = True
        mock_result.content = "Internal execution error"

        mock_session = AsyncMock()
        mock_session.initialize.return_value = MagicMock()
        mock_session.call_tool.return_value = mock_result

        with patch.object(mod, "streamable_http_client") as mock_client:
            mock_client.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
            with patch.object(mod, "ClientSession") as mock_cls:
                mock_cls.return_value.__aenter__.return_value = mock_session
                with pytest.raises(
                    mod.LatencyMeasurementError,
                    match="mission_status returned error at iteration 0",
                ):
                    await mod.measure_mission_status_round_trips(
                        "http://127.0.0.1:9999/mcp",
                        mission_id_str="test-id",
                        warmup_count=0,
                        sample_count=1,
                    )

    @pytest.mark.anyio
    async def test_05c_tools_list_empty_raises_latency_measurement_error(self) -> None:
        """5c. Empty tools/list raises LatencyMeasurementError instead of recording success."""
        mod = _get_latency_module()

        mock_result = MagicMock()
        mock_result.tools = []

        mock_session = AsyncMock()
        mock_session.initialize.return_value = MagicMock()
        mock_session.list_tools.return_value = mock_result

        with patch.object(mod, "streamable_http_client") as mock_client:
            mock_client.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
            with patch.object(mod, "ClientSession") as mock_cls:
                mock_cls.return_value.__aenter__.return_value = mock_session
                with pytest.raises(
                    mod.LatencyMeasurementError,
                    match="tools/list returned empty tool list at iteration 0",
                ):
                    await mod.measure_tools_list_round_trips(
                        "http://127.0.0.1:9999/mcp",
                        warmup_count=0,
                        sample_count=1,
                    )

    def test_06_output_schema_deterministic(self) -> None:
        """6. CampaignResult schema and serialized JSON are deterministic."""
        mod = _get_latency_module()

        op_metrics = {
            "initialize": mod.compute_latency_metrics("initialize", [5.0, 7.0], warmup_count=1),
            "tools/list": mod.compute_latency_metrics("tools/list", [4.0, 6.0], warmup_count=1),
            "mission_status": mod.compute_latency_metrics(
                "mission_status", [6.0, 8.0], warmup_count=1
            ),
        }
        campaign = mod.CampaignResult(
            source_sha="test_sha_123",
            timestamp_utc="2026-10-02T12:00:00+00:00",
            python_version="3.13.14",
            mcp_sdk_version="2.2.0",
            environment="Windows Test (AMD64)",
            operations=op_metrics,
        )

        d = campaign.to_dict()
        expected_keys = {
            "source_sha",
            "timestamp_utc",
            "python_version",
            "mcp_sdk_version",
            "environment",
            "target_alexa_ms",
            "provenance",
            "classification",
            "historical_remote_echo_ms",
            "historical_remote_provenance",
            "current_agentcore_latency",
            "non_certification_statement",
            "operations",
        }
        assert set(d.keys()) == expected_keys
        assert d["source_sha"] == "test_sha_123"
        assert d["target_alexa_ms"] == mod.ALEXA_PLUS_TARGET_LATENCY_MS
        assert d["provenance"] == "LOCAL_EXECUTION"
        assert d["classification"] == "LOCAL_LATENCY_HEADROOM_OBSERVED"
        assert d["historical_remote_echo_ms"] == mod.HISTORICAL_REMOTE_ECHO_MS
        assert d["historical_remote_provenance"] == "RECORDED_LIVE"
        assert d["current_agentcore_latency"] == "NOT_MEASURED"

        # Operations schema
        for op in ("initialize", "tools/list", "mission_status"):
            assert op in d["operations"]
            op_dict = d["operations"][op]
            assert set(op_dict.keys()) == {
                "operation",
                "sample_count",
                "warmup_count",
                "min_ms",
                "mean_ms",
                "p50_ms",
                "p95_ms",
                "max_ms",
            }
            assert op_dict["sample_count"] == 2
            assert op_dict["warmup_count"] == 1

        # JSON deserialization round trip
        json_str = campaign.to_json()
        reparsed = json.loads(json_str)
        assert reparsed["source_sha"] == "test_sha_123"
        assert reparsed["classification"] == "LOCAL_LATENCY_HEADROOM_OBSERVED"

    def test_07_no_external_provider_model_calls(self) -> None:
        """7. AST analysis proves zero external provider or model SDK imports in utility."""
        script_path = Path(__file__).parent.parent / "scripts" / "measure_mcp_latency.py"
        assert script_path.is_file(), "scripts/measure_mcp_latency.py must exist"

        tree = ast.parse(script_path.read_text(encoding="utf-8"))

        forbidden_modules = {
            "boto3",
            "botocore",
            "google",
            "googleapiclient",
            "requests",
            "urllib.request",
            "openai",
            "anthropic",
            "strands",
            "bedrock",
        }

        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])

        intersection = imported_modules & forbidden_modules
        assert not intersection, f"Forbidden external provider modules imported: {intersection}"

    def test_08_no_wall_clock_performance_assertions_in_test_suite(self) -> None:
        """8. Meta-test: confirms test methods do NOT assert fragile wall-clock limits in CI."""
        test_file_path = Path(__file__)
        tree = ast.parse(test_file_path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                test_expr = node.test
                if isinstance(test_expr, ast.Compare):
                    for comparator in test_expr.comparators:
                        if isinstance(comparator, ast.Constant) and isinstance(
                            comparator.value, (int, float)
                        ):
                            if (
                                any(isinstance(op, (ast.Lt, ast.LtE)) for op in test_expr.ops)
                                and comparator.value == 500.0
                            ):
                                pytest.fail(
                                    "Forbidden wall-clock < 500ms assertion found in CI test"
                                )
