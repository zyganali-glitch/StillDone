"""Tests for P-18.06: Bounded repeated-mission reliability test.

Verifies:
- Strictly offline FIXTURE mode execution.
- Finite iteration cap and execution timeout enforcement.
- Per-run isolation and distinct mission identity.
- Historical receipt integrity (READY -> DRIFTED hash preservation).
- Failure isolation: representative blocked, failed, and interrupted runs.
- Cross-run contamination detection.
- Duplicate unintended mutation detection.
- False READY rejection.
- Zero network access, zero live AWS/Google/Open-Meteo execution.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stilldone.benchmarks import (
    MeasurementProvenance,
    MissionReliabilityRunOutcome,
    MissionReliabilityTestResult,
    run_repeated_mission_reliability_test,
)


def test_reliability_test_runs_bounded_offline_iterations() -> None:
    """Verify default 15-iteration reliability run executes bounded offline fixture runs."""
    result = run_repeated_mission_reliability_test(iteration_cap=15)

    assert isinstance(result, MissionReliabilityTestResult)
    assert result.iteration_cap == 15
    assert result.total_runs == 15
    assert result.successful_runs == 11
    assert result.blocked_runs == 2
    assert result.failed_runs == 2
    assert result.provenance == MeasurementProvenance.FIXTURE
    assert result.cross_run_contamination_detected is False
    assert result.duplicate_unintended_mutation_detected is False
    assert result.false_ready_detected is False
    assert result.historical_receipt_integrity_verified is True
    assert result.predicate_correctness_verified is True
    assert result.source_sha != ""
    assert "Python" in result.environment


def test_reliability_test_enforces_finite_positive_cap() -> None:
    """Verify that iteration_cap must be strictly positive."""
    with pytest.raises(ValueError, match="strictly positive"):
        run_repeated_mission_reliability_test(iteration_cap=0)

    with pytest.raises(ValueError, match="strictly positive"):
        run_repeated_mission_reliability_test(iteration_cap=-5)


def test_reliability_test_scenario_distribution() -> None:
    """Verify that 15 iterations distribute across required representative scenarios."""
    result = run_repeated_mission_reliability_test(iteration_cap=15)

    scenarios = {r.scenario for r in result.runs}
    assert scenarios == {
        "SUCCESSFUL_LIFECYCLE",
        "BLOCKED_APPROVAL",
        "BLOCKED_PREFLIGHT",
        "FAILED_READBACK",
        "INTERRUPTED_PROVIDER_ERROR",
    }

    # Verify per-scenario assertions
    for run in result.runs:
        assert isinstance(run, MissionReliabilityRunOutcome)
        assert run.elapsed_ns > 0
        assert run.elapsed_ms > 0
        assert run.provenance == MeasurementProvenance.FIXTURE
        assert run.details is not None

        if run.scenario == "SUCCESSFUL_LIFECYCLE":
            assert run.status == "PASS"
            assert run.reached_ready is True
            assert run.reached_drifted is True
            assert run.receipt_projection_hash is not None
            assert run.drifted_receipt_projection_hash == run.receipt_projection_hash
            assert run.historical_receipt_intact is True
            assert run.writes_performed == 3
        elif run.scenario == "BLOCKED_APPROVAL":
            assert run.status == "BLOCKED"
            assert run.reached_ready is False
            assert run.reached_drifted is False
            assert run.receipt_projection_hash is None
            # Seed + task prep performed; calendar write paused/rejected
            assert run.writes_performed == 2
        elif run.scenario == "BLOCKED_PREFLIGHT":
            assert run.status == "BLOCKED"
            assert run.reached_ready is False
            assert run.reached_drifted is False
            assert run.receipt_projection_hash is None
            assert run.writes_performed == 0
        elif run.scenario == "FAILED_READBACK":
            assert run.status == "FAILED"
            assert run.reached_ready is False
            assert run.reached_drifted is False
            assert run.receipt_projection_hash is None
            assert run.error_category == "READBACK_CONTRADICTION"
        elif run.scenario == "INTERRUPTED_PROVIDER_ERROR":
            assert run.status == "FAILED"
            assert run.reached_ready is False
            assert run.reached_drifted is False
            assert run.receipt_projection_hash is None
            assert run.error_category == "PROVIDER_429_THROTTLED"


def test_historical_receipt_projection_hash_stability() -> None:
    """Verify that historical receipt hashes remain unmodified through READY -> DRIFTED."""
    result = run_repeated_mission_reliability_test(iteration_cap=15)

    assert result.historical_receipt_integrity_verified is True
    successful_runs = [r for r in result.runs if r.scenario == "SUCCESSFUL_LIFECYCLE"]
    assert len(successful_runs) == 11
    for r in successful_runs:
        assert r.historical_receipt_intact is True
        assert r.receipt_projection_hash is not None
        assert r.receipt_projection_hash == r.drifted_receipt_projection_hash


def test_no_cross_run_contamination() -> None:
    """Verify that runs do not leak state, IDs, or tokens between iterations."""
    result = run_repeated_mission_reliability_test(iteration_cap=15)

    assert result.cross_run_contamination_detected is False
    mids = [r.mission_id for r in result.runs]
    assert len(mids) == len(set(mids)), "Mission IDs must be unique across all runs"


def test_cross_run_contamination_detector_triggers_on_leaked_state() -> None:
    """Verify that simulated state leakage from a prior run triggers contamination flag."""
    result = run_repeated_mission_reliability_test(
        iteration_cap=3,
        fault_config={"fault_type": "LEAK_STATE"},
    )
    assert result.cross_run_contamination_detected is True


def test_no_duplicate_unintended_mutations() -> None:
    """Verify that total write operations match exact required expectations per scenario."""
    result = run_repeated_mission_reliability_test(iteration_cap=15)

    assert result.duplicate_unintended_mutation_detected is False
    for r in result.runs:
        if r.scenario == "SUCCESSFUL_LIFECYCLE":
            assert r.writes_performed == 3
        elif r.scenario == "BLOCKED_PREFLIGHT":
            assert r.writes_performed == 0


def test_false_ready_never_detected() -> None:
    """Verify that no blocked, failed, or interrupted run ever falsely achieves READY."""
    result = run_repeated_mission_reliability_test(iteration_cap=15)

    assert result.false_ready_detected is False
    non_successful_runs = [r for r in result.runs if r.status != "PASS"]
    assert len(non_successful_runs) == 4
    for r in non_successful_runs:
        assert r.reached_ready is False
        assert r.reached_drifted is False
        assert r.receipt_projection_hash is None


def test_custom_small_iteration_cap() -> None:
    """Verify execution with smaller custom iteration cap (e.g., 3 runs)."""
    result = run_repeated_mission_reliability_test(iteration_cap=3)

    assert result.total_runs == 3
    assert result.successful_runs == 3
    assert result.blocked_runs == 0
    assert result.failed_runs == 0
    assert result.cross_run_contamination_detected is False


def test_serialization_and_disclaimer() -> None:
    """Verify JSON dictionary and string serialization and non-certification disclaimer."""
    result = run_repeated_mission_reliability_test(iteration_cap=5)

    d = result.to_dict()
    assert d["total_runs"] == 5
    assert d["provenance"] == "FIXTURE"
    assert "exercises simulated fixture environments only" in d["non_certification_statement"]
    assert len(d["runs"]) == 5

    raw_json = result.to_json()
    parsed = json.loads(raw_json)
    assert parsed["total_runs"] == 5
    assert parsed["provenance"] == "FIXTURE"


class TestReliabilityAdversarialIntegrity:
    """Adversarial coverage for injected corruptions, predicate mismatches, and timeouts."""

    def test_iteration_cap_type_and_bound_validation(self) -> None:
        """Reject non-int, boolean, zero, negative, and unreasonable iteration caps."""
        with pytest.raises(TypeError, match="must be an integer"):
            run_repeated_mission_reliability_test(iteration_cap=True)

        with pytest.raises(TypeError, match="must be an integer"):
            run_repeated_mission_reliability_test(iteration_cap="15")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="strictly positive"):
            run_repeated_mission_reliability_test(iteration_cap=0)

        with pytest.raises(ValueError, match="must not exceed reasonable bounded maximum"):
            run_repeated_mission_reliability_test(iteration_cap=1001)

    def test_timeout_validation_rejects_invalid_inputs(self) -> None:
        """Reject non-float, boolean, non-positive, and infinite timeouts."""
        with pytest.raises(TypeError, match="must be a float or int"):
            run_repeated_mission_reliability_test(timeout_per_run_seconds=True)

        with pytest.raises(TypeError, match="must be a float or int"):
            run_repeated_mission_reliability_test(timeout_per_run_seconds="5.0")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="positive finite number"):
            run_repeated_mission_reliability_test(timeout_per_run_seconds=-1.0)

        with pytest.raises(ValueError, match="positive finite number"):
            run_repeated_mission_reliability_test(timeout_per_run_seconds=float("inf"))

    def test_runner_timeout_enforcement_marks_run_failed(self) -> None:
        """Enforces execution timeout: excessive duration yields FAILED with EXECUTION_TIMEOUT."""
        curr = 0

        def leaping_timer() -> int:
            nonlocal curr
            curr += 10_000_000_000  # 10 seconds per timer call
            return curr

        result = run_repeated_mission_reliability_test(
            iteration_cap=1,
            timeout_per_run_seconds=1.0,
            timer=leaping_timer,
        )

        assert result.failed_runs == 1
        assert result.successful_runs == 0
        run0 = result.runs[0]
        assert run0.status == "FAILED"
        assert run0.error_category == "EXECUTION_TIMEOUT"
        assert run0.reached_ready is False
        assert run0.reached_drifted is False
        assert "Execution timed out" in (run0.details or "")

    def test_injected_predicate_mismatch_fails_qualification(self) -> None:
        """Injected predicate mismatch prevents false PASS and marks
        predicate verification FALSE.
        """
        result = run_repeated_mission_reliability_test(
            iteration_cap=1,
            fault_config={"fault_type": "PREDICATE_MISMATCH"},
        )

        assert result.predicate_correctness_verified is False
        assert result.failed_runs == 1
        assert result.successful_runs == 0
        assert result.runs[0].status == "FAILED"
        assert result.runs[0].error_category == "PREDICATE_EVALUATION_FAILED"

    def test_injected_corrupted_receipt_hash_fails_integrity(self) -> None:
        """Altering historical receipt hash during drift causes receipt integrity to fail."""
        result = run_repeated_mission_reliability_test(
            iteration_cap=1,
            fault_config={"fault_type": "CORRUPT_RECEIPT_HASH"},
        )

        assert result.historical_receipt_integrity_verified is False
        assert result.failed_runs == 1
        assert result.successful_runs == 0
        assert result.runs[0].historical_receipt_intact is False

    def test_partial_run_explicitly_tracks_untested_scenarios(self) -> None:
        """When iteration_cap < 15, qualification is PARTIAL_UNQUALIFIED
        and untested scenarios are explicit.
        """
        partial = run_repeated_mission_reliability_test(iteration_cap=3)
        assert partial.qualification_status == "PARTIAL_UNQUALIFIED"
        assert len(partial.untested_scenarios) == 4
        assert "BLOCKED_APPROVAL" in partial.untested_scenarios
        assert "BLOCKED_PREFLIGHT" in partial.untested_scenarios
        assert "FAILED_READBACK" in partial.untested_scenarios
        assert "INTERRUPTED_PROVIDER_ERROR" in partial.untested_scenarios
        d = partial.to_dict()
        assert d["qualification_status"] == "PARTIAL_UNQUALIFIED"
        assert "BLOCKED_APPROVAL" in d["untested_scenarios"]

        full = run_repeated_mission_reliability_test(iteration_cap=15)
        assert full.qualification_status == "QUALIFIED"
        assert full.untested_scenarios == ()
        assert full.to_dict()["qualification_status"] == "QUALIFIED"
        assert full.to_dict()["untested_scenarios"] == []

    def test_hanging_scenario_interrupted_in_real_time_within_bound(self) -> None:
        """A hanging scenario is interrupted in real time by the daemon watchdog."""
        import time

        t_start = time.perf_counter()
        result = run_repeated_mission_reliability_test(
            iteration_cap=1,
            timeout_per_run_seconds=0.1,
            fault_config={"fault_type": "HANG", "sleep_seconds": 2.0},
        )
        elapsed_wall = time.perf_counter() - t_start

        # Interrupted promptly in ~0.1s; well before the 2.0s sleep would finish
        assert elapsed_wall < 1.0, f"Watchdog took too long: {elapsed_wall:.2f}s"
        assert result.failed_runs == 1
        assert result.successful_runs == 0
        run0 = result.runs[0]
        assert run0.status == "FAILED"
        assert run0.error_category == "EXECUTION_TIMEOUT"
        assert "Execution timed out" in (run0.details or "")

    def test_scenario_missing_expected_exception_fails_qualification(self) -> None:
        """If FAILED_READBACK fails to raise its expected exception,
        qualification is DISQUALIFIED.
        """
        result = run_repeated_mission_reliability_test(
            iteration_cap=15,
            fault_config={
                "fault_type": "MISSING_EXPECTED_EXCEPTION",
                "scenario": "FAILED_READBACK",
            },
        )

        # Scenario 12 (FAILED_READBACK) must report MISSING_EXPECTED_EXCEPTION
        readback_runs = [r for r in result.runs if r.scenario == "FAILED_READBACK"]
        assert len(readback_runs) == 1
        assert readback_runs[0].status == "FAILED"
        assert readback_runs[0].error_category == "MISSING_EXPECTED_EXCEPTION"

        # All 5 scenarios executed, but one failed assertion -> DISQUALIFIED
        assert result.qualification_status == "DISQUALIFIED"

    def test_unexpected_exception_is_caught_and_disqualifies(self) -> None:
        """An unexpected harness exception is caught fail-closed and disqualifies."""
        result = run_repeated_mission_reliability_test(
            iteration_cap=15,
            fault_config={"fault_type": "UNEXPECTED_EXCEPTION", "exc_type": "RuntimeError"},
        )

        # Run did not crash unhandled; caught and classified fail-closed
        assert result.failed_runs >= 1
        for r in result.runs:
            if r.scenario == "SUCCESSFUL_LIFECYCLE":
                assert r.status == "FAILED"
                assert r.error_category == "UNEXPECTED_EXCEPTION_RuntimeError"
        assert result.qualification_status == "DISQUALIFIED"

    def test_failed_lifecycle_marks_qualification_disqualified(self) -> None:
        """A failure in SUCCESSFUL_LIFECYCLE prevents QUALIFIED and sets DISQUALIFIED."""
        result = run_repeated_mission_reliability_test(
            iteration_cap=15,
            fault_config={"fault_type": "LIFECYCLE_VERIFICATION_MISMATCH", "run_index": 0},
        )

        assert result.runs[0].status == "FAILED"
        assert result.runs[0].error_category == "LIFECYCLE_VERIFICATION_MISMATCH"
        assert result.qualification_status == "DISQUALIFIED"


class TestKillableTimeoutAndPrecedenceQualification:
    """Adversarial regression tests for P-18.06 killable timeout and qualification precedence."""

    def test_killable_timeout_prevents_delayed_mutation_after_timeout(self, tmp_path: Path) -> None:
        """Requirement 5 & 8: Prove a delayed mutation never occurs after timeout.

        Verifies that when a worker exceeds timeout, it is genuinely terminated via
        isolated OS process boundary. Waiting well past the worker's original
        sleep duration proves that no delayed filesystem or fixture mutation occurs after timeout.
        """
        import time

        marker_file = tmp_path / "delayed_mutation.marker"
        t0 = time.perf_counter()
        result = run_repeated_mission_reliability_test(
            iteration_cap=1,
            timeout_per_run_seconds=0.05,
            fault_config={
                "fault_type": "DELAYED_MUTATION",
                "marker_file": str(marker_file),
                "sleep_seconds": 0.3,
            },
        )
        t_return = time.perf_counter()

        assert result.runs[0].status == "FAILED"
        assert result.runs[0].error_category == "EXECUTION_TIMEOUT"
        # Caller returns promptly bounded by timeout + reap
        assert t_return - t0 < 0.3
        assert not marker_file.exists()

        # Wait well beyond the 0.3s worker sleep to prove no delayed mutation ever occurs
        time.sleep(0.4)
        assert not marker_file.exists()

    def test_delayed_fixture_mutation_never_occurs_after_scenario_timeout(
        self, tmp_path: Path
    ) -> None:
        """Harness level: prove delayed fixture mutation never occurs after scenario timeout."""
        import time

        marker_file = tmp_path / "delayed_fixture_mutation.marker"

        res = run_repeated_mission_reliability_test(
            iteration_cap=1,
            timeout_per_run_seconds=0.05,
            fault_config={
                "fault_type": "DELAYED_MUTATION",
                "marker_file": str(marker_file),
                "sleep_seconds": 0.3,
            },
        )

        assert res.runs[0].status == "FAILED"
        assert res.runs[0].error_category == "EXECUTION_TIMEOUT"
        # Qualification is DISQUALIFIED due to failure
        assert res.qualification_status == "DISQUALIFIED"

        # Wait past the worker sleep duration to confirm mutation never executed
        time.sleep(0.4)
        assert not marker_file.exists()

    def test_partial_run_with_failure_reports_disqualified_not_partial_unqualified(
        self,
    ) -> None:
        """Requirement 7: Failure/integrity checks take precedence over partial scenario coverage.

        If a tested scenario fails unexpectedly, report DISQUALIFIED, even when other
        scenarios remain untested (e.g. iteration_cap=2 < 15).
        """
        result = run_repeated_mission_reliability_test(
            iteration_cap=2,
            fault_config={"fault_type": "UNEXPECTED_EXCEPTION", "run_index": 0},
        )

        # Scenarios remain untested because iteration_cap < 15
        assert len(result.untested_scenarios) > 0
        assert result.failed_runs >= 1
        # Precedence rule: MUST be DISQUALIFIED, NOT PARTIAL_UNQUALIFIED
        assert result.qualification_status == "DISQUALIFIED"

    def test_clean_partial_run_preserves_partial_unqualified(self) -> None:
        """Requirement 8: Preserve PARTIAL_UNQUALIFIED for clean partial coverage."""
        clean_partial = run_repeated_mission_reliability_test(iteration_cap=3)

        assert clean_partial.failed_runs == 0
        assert clean_partial.cross_run_contamination_detected is False
        assert clean_partial.duplicate_unintended_mutation_detected is False
        assert clean_partial.false_ready_detected is False
        assert len(clean_partial.untested_scenarios) > 0
        assert clean_partial.qualification_status == "PARTIAL_UNQUALIFIED"
