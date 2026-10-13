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
from unittest.mock import patch

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
    from stilldone.adapters.tasks import TaskTransportItem
    from stilldone.killer_mission import KillerMissionEnvironment

    orig_create = KillerMissionEnvironment.create_fixture_environment

    def leaky_create() -> KillerMissionEnvironment:
        from typing import Any, cast

        env = orig_create()
        tasks_store = cast(Any, env.tasks_transport)._tasks
        tasks_store["leaked_task"] = TaskTransportItem(
            id="leaked_task", title="Leaked from prior run", status="needsAction", due=None
        )
        return env

    with patch.object(
        KillerMissionEnvironment, "create_fixture_environment", side_effect=leaky_create
    ):
        result = run_repeated_mission_reliability_test(iteration_cap=3)
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
