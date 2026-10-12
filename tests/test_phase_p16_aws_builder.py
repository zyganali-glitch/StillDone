"""Comprehensive test suite for Phase P-16: AWS Builder Depth.

Covers exact micro-tasks:
- P-16.01: Audit actual AWS services used in the live critical path.
- P-16.02: Add exactly one additional AWS service materially improving state/observability/runtime.
- P-16.03: Prove the added AWS service live and document why it is not decorative.
- P-16.04: Produce AWS Builder architecture/evidence map.
- P-16.05: Validate cost impact against remaining promotional budget ($0.00 spend).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from stilldone.aws_builder import (
    AWSAccountObservation,
    AWSBuilderEvidenceMap,
    CloudWatchEMFTelemetryEmitter,
    audit_critical_path_aws_services,
    generate_aws_builder_evidence_map,
    record_killer_mission_telemetry,
)
from stilldone.domain.provenance import EvidenceProvenance
from stilldone.killer_mission import (
    KillerMissionSliceRunner,
)


def test_p16_01_audit_actual_aws_services_on_critical_path() -> None:
    """Verify P-16.01: Audit captures AWS services and distinguishes live vs prepared."""
    services = audit_critical_path_aws_services()
    assert len(services) == 5

    service_names = [s.service_name for s in services]
    assert "Amazon Bedrock" in service_names
    assert "AWS Strands Agents SDK" in service_names
    assert "Amazon Bedrock AgentCore Runtime" in service_names
    assert "AWS Identity and Access Management (IAM)" in service_names
    assert "Amazon CloudWatch (Embedded Metric Format)" in service_names

    # CloudWatch EMF is LOCAL / PREPARED until P-16.03 live proof actually runs
    cw_service = next(s for s in services if s.service_name.startswith("Amazon CloudWatch"))
    assert cw_service.is_critical_path is False
    assert "LOCAL / PREPARED" in cw_service.live_proof_phase
    assert "BLOCKED_LIVE" in cw_service.live_proof_phase

    # Other 4 services are on critical path
    for s in services:
        if s.service_name != cw_service.service_name:
            assert s.is_critical_path is True
        assert s.region == "us-east-1"
        assert len(s.live_proof_phase) > 0
        assert len(s.live_proof_ref) > 0
        assert len(s.non_decorative_justification) > 20
        # Without explicit AWSAccountObservation, coverage is NOT_OBSERVED (None)
        assert s.covered_by_free_tier_or_credit is None
        assert s.to_dict()["covered_by_free_tier_or_credit"] == "NOT_OBSERVED"

    # Unresolved source reference cannot certify coverage
    obs_unresolved = AWSAccountObservation(
        observed_at=datetime.now(UTC),
        observed_billing_status="FREE_TIER_COMPLIANT",
        observed_net_personal_spend_usd=Decimal("0.00"),
        promotional_credit_budget_sufficient=True,
        provenance=EvidenceProvenance.FIXTURE,
        source_reference="https://aws.amazon.com/billing",
    )
    unresolved_services = audit_critical_path_aws_services(observation=obs_unresolved)
    for s in unresolved_services:
        assert s.covered_by_free_tier_or_credit is None
        assert s.to_dict()["covered_by_free_tier_or_credit"] == "NOT_OBSERVED"

    # With explicit observation resolving to repo evidence: coverage is proven True
    obs = AWSAccountObservation(
        observed_at=datetime.now(UTC),
        observed_billing_status="FREE_TIER_COMPLIANT",
        observed_net_personal_spend_usd=Decimal("0.00"),
        promotional_credit_budget_sufficient=True,
        provenance=EvidenceProvenance.RECORDED_LIVE,
        source_reference="tests/fixtures/aws_account_evidence_record.json",
    )
    observed_services = audit_critical_path_aws_services(observation=obs)
    for s in observed_services:
        assert s.covered_by_free_tier_or_credit is True
        assert s.to_dict()["covered_by_free_tier_or_credit"] is True


def test_p16_02_cloudwatch_emf_telemetry_specification_compliance() -> None:
    """Verify P-16.02: CloudWatch EMF emitter adheres strictly to official AWS EMF Specification."""
    emitter = CloudWatchEMFTelemetryEmitter(environment="production")

    record = emitter.build_verification_emf_record(
        mission_id="11111111-2222-3333-4444-555555555555",
        task_id="P-13.05",
        action_type="calendar.update",
        verification_status="PASS",
        verification_latency_ms=21.4,
        is_verified=True,
        readback_contradiction=False,
        writes_performed=1,
    )

    # 1. Root structure
    assert "_aws" in record
    aws_meta = record["_aws"]
    assert "Timestamp" in aws_meta
    assert isinstance(aws_meta["Timestamp"], int)
    assert "CloudWatchMetrics" in aws_meta
    assert len(aws_meta["CloudWatchMetrics"]) == 1

    metric_directive = aws_meta["CloudWatchMetrics"][0]
    assert metric_directive["Namespace"] == "StillDone/VerificationEngine"

    # 2. Dimensions compliance: every dimension in dimension sets must be a top-level property
    for dim_set in metric_directive["Dimensions"]:
        for dim_name in dim_set:
            assert dim_name in record, f"Missing dimension property: {dim_name}"

    # 3. Metrics compliance: every metric declared must be a numeric top-level property
    for m in metric_directive["Metrics"]:
        metric_name = m["Name"]
        assert metric_name in record, f"Missing metric property: {metric_name}"
        assert isinstance(record[metric_name], (int, float))

    # 4. Canonical serialization test
    serialized = emitter.serialize_record(record)
    assert isinstance(serialized, str)
    parsed = json.loads(serialized)
    assert parsed["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "StillDone/VerificationEngine"
    assert parsed["VerificationLatencyMs"] == 21.4
    assert parsed["WritesPerformedCount"] == 1


def test_p16_03_prove_added_aws_service_not_decorative() -> None:
    """Verify P-16.03: CloudWatch EMF telemetry directly models core verification invariants."""
    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    emitter = CloudWatchEMFTelemetryEmitter(environment="test")
    records = record_killer_mission_telemetry(outcome, emitter=emitter)

    # Must produce telemetry across all key invariant moments:
    # 1) task creation, 2) calendar approval pause, 3) calendar verified mutation, 4) drift
    assert len(records) == 4

    # Verify drift detection record
    drift_record = records[3]
    assert drift_record["NewState"] == "DRIFTED"
    assert drift_record["PriorState"] == "READY"
    assert drift_record["DriftDetectedCount"] == 1
    assert drift_record["ReadinessRevokedCount"] == 1

    # Verify approval checkpoint record
    approval_record = records[1]
    assert approval_record["AuthorityClass"] == "REVERSIBLE_APPROVAL_REQUIRED"
    assert approval_record["UnapprovedWriteBlockedCount"] == 1
    assert approval_record["ApprovalGranted"] is False

    # Confirm all records serialize without error
    for r in records:
        line = emitter.serialize_record(r)
        assert len(line) > 50


def test_p16_04_aws_builder_architecture_and_evidence_map() -> None:
    """Verify P-16.04: Produce structured architecture map without fabricating account billing."""
    # 1. Default without account observation: billing truth is NOT_OBSERVED, not fabricated
    ev_map_default = generate_aws_builder_evidence_map()
    assert isinstance(ev_map_default, AWSBuilderEvidenceMap)
    assert len(ev_map_default.aws_services) == 5
    assert ev_map_default.total_net_personal_spend_usd is None
    assert ev_map_default.promotional_credit_budget_sufficient is None

    dict_default = ev_map_default.to_dict()
    assert dict_default["architecture_title"] == "StillDone Verifiable Outcome Engine on AWS"
    assert dict_default["services_count"] == 5
    assert dict_default["observed_account_billing_status"] == "NOT_OBSERVED"
    assert dict_default["total_net_personal_spend_usd"] == "NOT_OBSERVED"
    assert dict_default["promotional_credit_budget_sufficient"] == "NOT_OBSERVED"

    # 2. Unresolved operator observation: remains NOT_OBSERVED
    obs_unresolved = AWSAccountObservation(
        observed_at=datetime.now(UTC),
        observed_billing_status="FREE_TIER_COMPLIANT",
        observed_net_personal_spend_usd=Decimal("0.00"),
        promotional_credit_budget_sufficient=True,
        provenance=EvidenceProvenance.FIXTURE,
        source_reference="https://aws.amazon.com/billing",
    )
    ev_map_unresolved = generate_aws_builder_evidence_map(observation=obs_unresolved)
    dict_unresolved = ev_map_unresolved.to_dict()
    assert dict_unresolved["observed_account_billing_status"] == "NOT_OBSERVED"
    assert dict_unresolved["total_net_personal_spend_usd"] == "NOT_OBSERVED"
    assert dict_unresolved["promotional_credit_budget_sufficient"] == "NOT_OBSERVED"

    # 3. With explicit operator observation resolving to repo evidence: binds external truth cleanly
    obs = AWSAccountObservation(
        observed_at=datetime.now(UTC),
        observed_billing_status="FREE_TIER_COMPLIANT",
        observed_net_personal_spend_usd=Decimal("0.00"),
        promotional_credit_budget_sufficient=True,
        provenance=EvidenceProvenance.RECORDED_LIVE,
        source_reference="tests/fixtures/aws_account_evidence_record.json",
    )
    ev_map_obs = generate_aws_builder_evidence_map(observation=obs)
    dict_obs = ev_map_obs.to_dict()
    assert dict_obs["observed_account_billing_status"] == "FREE_TIER_COMPLIANT"
    assert dict_obs["total_net_personal_spend_usd"] == "0.00"
    assert dict_obs["promotional_credit_budget_sufficient"] is True


def test_p16_05_cost_impact_validation_against_zero_personal_spend() -> None:
    """Verify P-16.05: Cost impact strictly adheres to Zero Personal Spend Law ($0.00)."""
    # 1. Without account observation: net spend & zero spend maintained are NOT_OBSERVED
    ev_map = generate_aws_builder_evidence_map()

    # Gross estimated cost across all services must be minimal (< $0.05 total)
    assert ev_map.total_estimated_gross_spend_usd < Decimal("0.05")

    # Policy invariant: without observation, cannot fabricate account truth
    assert ev_map.zero_personal_spend_maintained is None
    assert ev_map.to_dict()["zero_personal_spend_maintained"] == "NOT_OBSERVED"

    # CloudWatch EMF itself has zero incremental cost ($0.00)
    cw_service = next(
        s for s in ev_map.aws_services if s.service_name.startswith("Amazon CloudWatch")
    )
    assert cw_service.estimated_cost_usd == Decimal("0.00000000")
    assert cw_service.covered_by_free_tier_or_credit is None

    # 2. Unresolved observation: cannot certify zero personal spend
    obs_unresolved = AWSAccountObservation(
        observed_at=datetime.now(UTC),
        observed_billing_status="FREE_TIER_COMPLIANT",
        observed_net_personal_spend_usd=Decimal("0.00"),
        promotional_credit_budget_sufficient=True,
        provenance=EvidenceProvenance.FIXTURE,
        source_reference="https://aws.amazon.com/billing",
    )
    ev_map_unresolved = generate_aws_builder_evidence_map(observation=obs_unresolved)
    assert ev_map_unresolved.zero_personal_spend_maintained is None
    assert ev_map_unresolved.to_dict()["zero_personal_spend_maintained"] == "NOT_OBSERVED"

    # 3. With explicit operator observation resolving to repo evidence: binds external truth
    obs = AWSAccountObservation(
        observed_at=datetime.now(UTC),
        observed_billing_status="FREE_TIER_COMPLIANT",
        observed_net_personal_spend_usd=Decimal("0.00"),
        promotional_credit_budget_sufficient=True,
        provenance=EvidenceProvenance.RECORDED_LIVE,
        source_reference="tests/fixtures/aws_account_evidence_record.json",
    )
    ev_map_obs = generate_aws_builder_evidence_map(observation=obs)
    assert ev_map_obs.zero_personal_spend_maintained is True
    assert ev_map_obs.to_dict()["zero_personal_spend_maintained"] is True
    cw_obs = next(
        s for s in ev_map_obs.aws_services if s.service_name.startswith("Amazon CloudWatch")
    )
    assert cw_obs.covered_by_free_tier_or_credit is True


def test_cloudwatch_live_proof_harness_fail_closed_without_approval() -> None:
    """Verify CloudWatchLiveProofHarness does not falsely verify on client construction."""
    from stilldone.aws_builder import CloudWatchLiveProofHarness, CostExposure

    def git_ok(cmd: list[str]) -> tuple[int, str, str]:
        if "HEAD" in cmd or "origin/main" in cmd:
            return 0, "1111111111111111111111111111111111111111", ""
        return 0, "", ""

    # 1. Missing approval fails closed
    harness = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo", log_stream_name="stream1"
    )
    outcome_no_appr = harness.execute_live_proof(
        source_sha="1111111111111111111111111111111111111111",
        operator_approved=False,
        git_runner=git_ok,
    )
    assert outcome_no_appr.is_verified is False
    assert outcome_no_appr.status == "BLOCKED_LIVE"
    assert "operator authorization" in outcome_no_appr.details.lower()
    assert outcome_no_appr.cost_exposure == CostExposure.NOT_ATTEMPTED
    assert outcome_no_appr.is_billable is False

    # 2. Missing destination log group fails closed
    harness_no_dest = CloudWatchLiveProofHarness(log_group_name=None, log_stream_name=None)
    outcome_no_dest = harness_no_dest.execute_live_proof(
        source_sha="1111111111111111111111111111111111111111",
        operator_approved=True,
        git_runner=git_ok,
    )
    assert outcome_no_dest.is_verified is False
    assert outcome_no_dest.status == "BLOCKED_LIVE"
    assert "pre-configured dedicated log group" in outcome_no_dest.details.lower()
    assert outcome_no_dest.cost_exposure == CostExposure.NOT_ATTEMPTED
    assert outcome_no_dest.is_billable is False


def test_cloudwatch_live_proof_harness_positive_and_negative_verification() -> None:
    """Verify CloudWatchLiveProofHarness verifies exact contract and fails closed on mismatches."""
    from unittest.mock import MagicMock

    from stilldone.aws_builder import CloudWatchLiveProofHarness, CostExposure

    def git_ok(cmd: list[str]) -> tuple[int, str, str]:
        if "HEAD" in cmd or "origin/main" in cmd:
            return 0, "1111111111111111111111111111111111111111", ""
        return 0, "", ""

    valid_sha = "1111111111111111111111111111111111111111"

    # Helper to create mock clients
    mock_logs = MagicMock()
    mock_cw = MagicMock()

    emitted_records: list[str] = []

    def mock_put_log_events(
        logGroupName: str, logStreamName: str, logEvents: list[dict[str, Any]]
    ) -> dict[str, str]:
        for ev in logEvents:
            emitted_records.append(ev["message"])
        return {"nextSequenceToken": "seq_123"}

    mock_logs.put_log_events.side_effect = mock_put_log_events
    mock_logs.get_log_events.side_effect = lambda **kwargs: {
        "events": [{"message": rec} for rec in emitted_records]
    }
    mock_cw.get_metric_data.side_effect = lambda **kwargs: {
        "MetricDataResults": [
            {
                "StatusCode": "Complete",
                "Id": "m1",
                "Timestamps": [datetime.now(UTC)],
                "Values": [42.0],
            }
        ]
    }

    harness = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw,
        environment="test",
    )

    # 1. Positive case: valid execution
    res_pass = harness.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=2.0,
        poll_interval_seconds=0.1,
    )
    assert res_pass.is_verified is True
    assert res_pass.status == "PASS"
    assert res_pass.is_billable is True
    assert res_pass.cost_exposure == CostExposure.MAY_HAVE_INCURRED_USAGE
    assert res_pass.observed_metric_value == 42.0

    # 2. Wrong namespace: fails closed
    emitted_records.clear()
    res_wrong_ns = harness.execute_live_proof(
        namespace="Wrong/Namespace",
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=2.0,
        poll_interval_seconds=0.1,
    )
    assert res_wrong_ns.is_verified is False
    assert res_wrong_ns.status == "FAILED"
    assert "namespace mismatch" in res_wrong_ns.details.lower()
    assert res_wrong_ns.is_billable is True
    assert res_wrong_ns.cost_exposure == CostExposure.MAY_HAVE_INCURRED_USAGE

    # 3. Wrong metric name: fails closed
    emitted_records.clear()
    res_wrong_metric = harness.execute_live_proof(
        metric_name="WrongMetricName",
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=2.0,
        poll_interval_seconds=0.1,
    )
    assert res_wrong_metric.is_verified is False
    assert res_wrong_metric.status == "FAILED"
    assert "metric mismatch" in res_wrong_metric.details.lower()

    # 4. Readback absent / token missing: fails closed
    mock_logs_empty = MagicMock()
    mock_logs_empty.put_log_events.return_value = {}
    mock_logs_empty.get_log_events.return_value = {"events": []}
    harness_empty = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs_empty,
    )
    res_no_readback = harness_empty.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.1,
        poll_interval_seconds=0.05,
    )
    assert res_no_readback.is_verified is False
    assert res_no_readback.status == "FAILED"
    assert "independent read-back failed" in res_no_readback.details.lower()
    assert res_no_readback.is_billable is True
    assert res_no_readback.cost_exposure == CostExposure.MAY_HAVE_INCURRED_USAGE

    # 5. Provider exception on put_log_events: billable usage exposure truthful
    mock_logs_err = MagicMock()
    mock_logs_err.put_log_events.side_effect = RuntimeError("AWS Connection dropped")
    harness_err = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs_err,
    )
    res_exc = harness_err.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
    )
    assert res_exc.is_verified is False
    assert res_exc.status == "FAILED"
    assert res_exc.is_billable is True
    assert res_exc.cost_exposure == CostExposure.MAY_HAVE_INCURRED_USAGE


def test_aws_account_observation_validation() -> None:
    """Verify AWSAccountObservation enforces timezone awareness and source reference."""
    # 1. Naive datetime must fail
    with pytest.raises(ValueError, match="timezone-aware"):
        AWSAccountObservation(
            observed_at=datetime.now(),  # naive!
            observed_billing_status="FREE_TIER_COMPLIANT",
            observed_net_personal_spend_usd=Decimal("0.00"),
            promotional_credit_budget_sufficient=True,
            provenance=EvidenceProvenance.LOCAL_EXECUTION,
        )

    # 2. RECORDED_LIVE without source_reference must fail
    with pytest.raises(ValueError, match="source_reference is required"):
        AWSAccountObservation(
            observed_at=datetime.now(UTC),
            observed_billing_status="FREE_TIER_COMPLIANT",
            observed_net_personal_spend_usd=Decimal("0.00"),
            promotional_credit_budget_sufficient=True,
            provenance=EvidenceProvenance.RECORDED_LIVE,
            source_reference=None,
        )

    # 3. RECORDED_LIVE with unresolvable or arbitrary URL reference must fail
    with pytest.raises(ValueError, match="must resolve to an existing durable evidence"):
        AWSAccountObservation(
            observed_at=datetime.now(UTC),
            observed_billing_status="FREE_TIER_COMPLIANT",
            observed_net_personal_spend_usd=Decimal("0.00"),
            promotional_credit_budget_sufficient=True,
            provenance=EvidenceProvenance.RECORDED_LIVE,
            source_reference="https://aws.amazon.com/billing",
        )

    with pytest.raises(ValueError, match="must resolve to an existing durable evidence"):
        AWSAccountObservation(
            observed_at=datetime.now(UTC),
            observed_billing_status="FREE_TIER_COMPLIANT",
            observed_net_personal_spend_usd=Decimal("0.00"),
            promotional_credit_budget_sufficient=True,
            provenance=EvidenceProvenance.RECORDED_LIVE,
            source_reference="nonexistent_evidence_artifact.md",
        )


def test_cloudwatch_live_proof_harness_metric_verification_failures() -> None:
    """Verify CloudWatchLiveProofHarness fails closed on missing cw_client or metric mismatch."""
    from datetime import timedelta
    from unittest.mock import MagicMock

    from stilldone.aws_builder import CloudWatchLiveProofHarness

    def git_ok(cmd: list[str]) -> tuple[int, str, str]:
        if "HEAD" in cmd or "origin/main" in cmd:
            return 0, "1111111111111111111111111111111111111111", ""
        return 0, "", ""

    valid_sha = "1111111111111111111111111111111111111111"

    mock_logs = MagicMock()
    emitted_records: list[str] = []

    def mock_put_log_events(
        logGroupName: str, logStreamName: str, logEvents: list[dict[str, Any]]
    ) -> dict[str, str]:
        for ev in logEvents:
            emitted_records.append(ev["message"])
        return {"nextSequenceToken": "seq_123"}

    mock_logs.put_log_events.side_effect = mock_put_log_events
    mock_logs.get_log_events.side_effect = lambda **kwargs: {
        "events": [{"message": rec} for rec in emitted_records]
    }

    # 1. Missing cw_client fails closed when log read-back succeeds
    harness_no_cw = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=None,
        environment="test",
    )
    res_no_cw = harness_no_cw.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.5,
        poll_interval_seconds=0.05,
    )
    assert res_no_cw.is_verified is False
    assert res_no_cw.status == "FAILED"
    assert (
        "requires cw_client" in res_no_cw.details
        or "cloudwatch metric api query failed" in res_no_cw.details.lower()
    )

    # 2. Prior / stale datapoints outside emission window fails closed
    emitted_records.clear()
    mock_cw_stale = MagicMock()
    mock_cw_stale.get_metric_data.return_value = {
        "MetricDataResults": [
            {
                "StatusCode": "Complete",
                "Id": "m1",
                "Timestamps": [datetime.now(UTC) - timedelta(hours=2)],
                "Values": [42.0],
            }
        ]
    }
    harness_stale = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw_stale,
        environment="test",
    )
    res_stale = harness_stale.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.2,
        poll_interval_seconds=0.05,
    )
    assert res_stale.is_verified is False
    assert res_stale.status == "FAILED"
    assert "stale" in res_stale.details.lower()

    # 3. Metric value mismatch in CloudWatch metrics API fails closed
    emitted_records.clear()
    mock_cw_mismatch = MagicMock()
    mock_cw_mismatch.get_metric_data.return_value = {
        "MetricDataResults": [
            {
                "StatusCode": "Complete",
                "Id": "m1",
                "Timestamps": [datetime.now(UTC)],
                "Values": [999.0],
            }
        ]
    }
    harness_mismatch = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw_mismatch,
        environment="test",
    )
    res_mismatch = harness_mismatch.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.2,
        poll_interval_seconds=0.05,
    )
    assert res_mismatch.is_verified is False
    assert res_mismatch.status == "FAILED"
    assert "none matching expected" in res_mismatch.details.lower()

    # 4. No timestamps / empty result fails closed
    emitted_records.clear()
    mock_cw_empty = MagicMock()
    mock_cw_empty.get_metric_data.return_value = {
        "MetricDataResults": [
            {
                "StatusCode": "Complete",
                "Id": "m1",
                "Timestamps": [],
                "Values": [],
            }
        ]
    }
    harness_empty_ts = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw_empty,
        environment="test",
    )
    res_empty_ts = harness_empty_ts.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.2,
        poll_interval_seconds=0.05,
    )
    assert res_empty_ts.is_verified is False
    assert res_empty_ts.status == "FAILED"

    # 5. Incomplete metric result (StatusCode != Complete) fails closed
    emitted_records.clear()
    mock_cw_partial = MagicMock()
    mock_cw_partial.get_metric_data.return_value = {
        "MetricDataResults": [
            {
                "StatusCode": "PartialData",
                "Id": "m1",
                "Timestamps": [datetime.now(UTC)],
                "Values": [42.0],
            }
        ]
    }
    harness_partial = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw_partial,
        environment="test",
    )
    res_partial = harness_partial.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.2,
        poll_interval_seconds=0.05,
    )
    assert res_partial.is_verified is False
    assert res_partial.status == "FAILED"
    assert "incomplete statuscode" in res_partial.details.lower()

    # 6. Query Id mismatch fails closed
    emitted_records.clear()
    mock_cw_id = MagicMock()
    mock_cw_id.get_metric_data.return_value = {
        "MetricDataResults": [
            {
                "StatusCode": "Complete",
                "Id": "m_wrong",
                "Timestamps": [datetime.now(UTC)],
                "Values": [42.0],
            }
        ]
    }
    harness_id = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw_id,
        environment="test",
    )
    res_id = harness_id.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.2,
        poll_interval_seconds=0.05,
    )
    assert res_id.is_verified is False
    assert res_id.status == "FAILED"
    assert "id mismatch" in res_id.details.lower()

    # 7. Length mismatch between timestamps and values fails closed
    emitted_records.clear()
    mock_cw_len = MagicMock()
    mock_cw_len.get_metric_data.return_value = {
        "MetricDataResults": [
            {
                "StatusCode": "Complete",
                "Id": "m1",
                "Timestamps": [datetime.now(UTC)],
                "Values": [],
            }
        ]
    }
    harness_len = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw_len,
        environment="test",
    )
    res_len = harness_len.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.2,
        poll_interval_seconds=0.05,
    )
    assert res_len.is_verified is False
    assert res_len.status == "FAILED"
    assert "length mismatch" in res_len.details.lower()

    # 8. No extracted metric within polling deadline fails closed
    emitted_records.clear()
    mock_cw_empty_results = MagicMock()
    mock_cw_empty_results.get_metric_data.return_value = {"MetricDataResults": []}
    harness_empty_results = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw_empty_results,
        environment="test",
    )
    res_deadline = harness_empty_results.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.2,
        poll_interval_seconds=0.05,
    )
    assert res_deadline.is_verified is False
    assert res_deadline.status == "FAILED"

    # 9. Injected provider error fails closed
    emitted_records.clear()
    mock_cw_err = MagicMock()
    mock_cw_err.get_metric_data.side_effect = RuntimeError("ThrottlingException")
    harness_err = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw_err,
        environment="test",
    )
    res_cw_err = harness_err.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=0.2,
        poll_interval_seconds=0.05,
    )
    assert res_cw_err.is_verified is False
    assert res_cw_err.status == "FAILED"
    assert "query failed" in res_cw_err.details.lower()


def test_existing_documentation_file_falsely_claiming_zero_spend_rejected() -> None:
    """An existing documentation file (e.g. docs/AWS_BUILDER_MAP.md) claiming $0.00 balance

    must be rejected fail-closed as invalid account evidence:
    - is_resolved_evidence_reference returns False;
    - AWSAccountObservation with RECORDED_LIVE raises ValueError;
    - generate_aws_builder_evidence_map returns NOT_OBSERVED for all billing facts;
    - audit_critical_path_aws_services returns NOT_OBSERVED coverage.
    """
    from stilldone.aws_builder import is_resolved_evidence_reference

    # 1. docs/AWS_BUILDER_MAP.md exists in repository but is documentation, not typed evidence
    doc_path = "docs/AWS_BUILDER_MAP.md"
    assert is_resolved_evidence_reference(doc_path) is False

    # 2. RECORDED_LIVE cannot bind to an existing doc file
    with pytest.raises(ValueError, match="must resolve to an existing durable evidence"):
        AWSAccountObservation(
            observed_at=datetime.now(UTC),
            observed_billing_status="FREE_TIER_COMPLIANT",
            observed_net_personal_spend_usd=Decimal("0.00"),
            promotional_credit_budget_sufficient=True,
            provenance=EvidenceProvenance.RECORDED_LIVE,
            source_reference=doc_path,
        )

    # 3. FIXTURE referencing doc file cannot promote billing facts to verified
    obs_fixture = AWSAccountObservation(
        observed_at=datetime.now(UTC),
        observed_billing_status="FREE_TIER_COMPLIANT",
        observed_net_personal_spend_usd=Decimal("0.00"),
        promotional_credit_budget_sufficient=True,
        provenance=EvidenceProvenance.FIXTURE,
        source_reference=doc_path,
    )
    ev_map = generate_aws_builder_evidence_map(observation=obs_fixture)
    assert ev_map.observed_account_billing_status == "NOT_OBSERVED"
    assert ev_map.total_net_personal_spend_usd is None
    assert ev_map.zero_personal_spend_maintained is None
    assert ev_map.promotional_credit_budget_sufficient is None
    assert ev_map.to_dict()["observed_account_billing_status"] == "NOT_OBSERVED"
    assert ev_map.to_dict()["total_net_personal_spend_usd"] == "NOT_OBSERVED"

    # 4. Critical path audit coverage remains NOT_OBSERVED
    services = audit_critical_path_aws_services(observation=obs_fixture)
    for s in services:
        assert s.covered_by_free_tier_or_credit is None
        assert s.to_dict()["covered_by_free_tier_or_credit"] == "NOT_OBSERVED"


def test_aws_account_evidence_provenance_validation_controls() -> None:
    """Verify validation rejects traversal, empty files, non-JSON, and mismatched caller facts."""
    from stilldone.aws_builder import (
        AWSAccountEvidenceRecord,
        is_resolved_evidence_reference,
        validate_account_evidence_record,
    )

    valid_ref = "tests/fixtures/aws_account_evidence_record.json"

    # 1. Directory traversal rejected
    assert is_resolved_evidence_reference("../../etc/passwd") is False
    assert is_resolved_evidence_reference("..\\..\\Windows\\System32\\cmd.exe") is False

    # 2. Untrusted URLs rejected
    assert is_resolved_evidence_reference("https://aws.amazon.com") is False
    assert is_resolved_evidence_reference("http://localhost:8000/evidence.json") is False

    # 3. Non-existent file rejected
    assert is_resolved_evidence_reference("nonexistent.json") is False

    # 4. Valid durable record parses cleanly
    valid, record = validate_account_evidence_record(valid_ref)
    assert valid is True
    assert isinstance(record, AWSAccountEvidenceRecord)
    assert record.source_identity == "aws-cost-explorer-cli"
    assert record.observed_net_personal_spend_usd == Decimal("0.00")
    assert record.promotional_credit_budget_sufficient is True

    # 5. Caller-provided observation with mismatched spend rejected
    obs_mismatch = AWSAccountObservation(
        observed_at=datetime.now(UTC),
        observed_billing_status="FREE_TIER_COMPLIANT",
        observed_net_personal_spend_usd=Decimal("15.50"),  # mismatch with record ($0.00)!
        promotional_credit_budget_sufficient=True,
        provenance=EvidenceProvenance.FIXTURE,
        source_reference=valid_ref,
    )
    assert is_resolved_evidence_reference(valid_ref, observation=obs_mismatch) is False

    # 6. Caller-provided observation with matching spend accepted
    obs_match = AWSAccountObservation(
        observed_at=datetime.now(UTC),
        observed_billing_status="FREE_TIER_COMPLIANT",
        observed_net_personal_spend_usd=Decimal("0.00"),
        promotional_credit_budget_sufficient=True,
        provenance=EvidenceProvenance.RECORDED_LIVE,
        source_reference=valid_ref,
    )
    assert is_resolved_evidence_reference(valid_ref, observation=obs_match) is True


def test_cloudwatch_live_proof_conflicting_emission_same_interval_fails_closed() -> None:
    """Negative control: If another emission carries identical metric value in same interval,

    exact metric correlation cannot be verified at bounded cost.
    The harness must fail closed and classify the outcome as LOG_INGESTION_OBSERVED,
    NOT VERIFIED_METRIC_EXTRACTION.
    """
    from unittest.mock import MagicMock

    from stilldone.aws_builder import CloudWatchLiveProofHarness, CostExposure

    def git_ok(cmd: list[str]) -> tuple[int, str, str]:
        if "HEAD" in cmd or "origin/main" in cmd:
            return 0, "1111111111111111111111111111111111111111", ""
        return 0, "", ""

    valid_sha = "1111111111111111111111111111111111111111"

    mock_logs = MagicMock()
    mock_cw = MagicMock()

    emitted_records: list[str] = []

    def mock_put_log_events(
        logGroupName: str, logStreamName: str, logEvents: list[dict[str, Any]]
    ) -> dict[str, str]:
        for ev in logEvents:
            emitted_records.append(ev["message"])
        return {"nextSequenceToken": "seq_123"}

    mock_logs.put_log_events.side_effect = mock_put_log_events

    # Injected conflict: a different emission with the identical metric value (42.0)
    conflicting_record = json.dumps(
        {
            "_aws": {
                "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "StillDone/VerificationEngine",
                        "Dimensions": [["Environment"]],
                        "Metrics": [{"Name": "VerificationLatencyMs", "Unit": "Milliseconds"}],
                    }
                ],
            },
            "Environment": "test",
            "ProofToken": "other-unrelated-proof-token-888",
            "VerificationLatencyMs": 42.0,  # IDENTICAL value in same window!
        }
    )

    mock_logs.get_log_events.side_effect = lambda **kwargs: {
        "events": [{"message": rec} for rec in emitted_records] + [{"message": conflicting_record}]
    }

    harness = CloudWatchLiveProofHarness(
        log_group_name="/aws/stilldone/demo",
        log_stream_name="test_stream",
        logs_client=mock_logs,
        cw_client=mock_cw,
        environment="test",
    )

    outcome = harness.execute_live_proof(
        source_sha=valid_sha,
        operator_approved=True,
        git_runner=git_ok,
        timeout_seconds=1.0,
        poll_interval_seconds=0.05,
    )

    # Must classify as LOG_INGESTION_OBSERVED, NOT verified metric extraction
    assert outcome.is_verified is False
    assert outcome.status == "LOG_INGESTION_OBSERVED"
    assert "LOG_INGESTION_OBSERVED" in outcome.details
    assert "VERIFIED_METRIC_EXTRACTION" in outcome.details
    assert outcome.is_billable is True
    assert outcome.cost_exposure == CostExposure.MAY_HAVE_INCURRED_USAGE
    assert outcome.observed_metric_value is None
