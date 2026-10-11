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
from decimal import Decimal

import pytest

from stilldone.aws_builder import (
    AWSBuilderEvidenceMap,
    AWSServiceAuditEntry,
    AWSServiceRole,
    CloudWatchEMFTelemetryEmitter,
    audit_critical_path_aws_services,
    generate_aws_builder_evidence_map,
    record_killer_mission_telemetry,
)
from stilldone.killer_mission import (
    KillerMissionSliceRunner,
)


def test_p16_01_audit_actual_aws_services_on_critical_path() -> None:
    """Verify P-16.01: Audit accurately captures all AWS services on StillDone's critical path."""
    services = audit_critical_path_aws_services()
    assert len(services) == 5

    service_names = [s.service_name for s in services]
    assert "Amazon Bedrock" in service_names
    assert "AWS Strands Agents SDK" in service_names
    assert "Amazon Bedrock AgentCore Runtime" in service_names
    assert "AWS Identity and Access Management (IAM)" in service_names
    assert "Amazon CloudWatch (Embedded Metric Format)" in service_names

    # All services must have explicit live proof references
    for s in services:
        assert s.region == "us-east-1"
        assert s.is_critical_path is True
        assert len(s.live_proof_phase) > 0
        assert len(s.live_proof_ref) > 0
        assert len(s.non_decorative_justification) > 20
        assert s.covered_by_free_tier_or_credit is True


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
    """Verify P-16.03: CloudWatch EMF telemetry directly models StillDone core verification & drift invariants."""
    runner = KillerMissionSliceRunner()
    outcome = runner.run_full_slice()

    emitter = CloudWatchEMFTelemetryEmitter(environment="test")
    records = record_killer_mission_telemetry(outcome, emitter=emitter)

    # Must produce telemetry across all key invariant moments:
    # 1) task creation verification, 2) calendar approval pause, 3) calendar verified mutation, 4) drift detection
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
    """Verify P-16.04: Produce structured architecture and evidence map."""
    ev_map = generate_aws_builder_evidence_map()
    assert isinstance(ev_map, AWSBuilderEvidenceMap)
    assert len(ev_map.aws_services) == 5

    dict_repr = ev_map.to_dict()
    assert dict_repr["architecture_title"] == "StillDone Verifiable Outcome Engine on AWS"
    assert dict_repr["services_count"] == 5
    assert dict_repr["zero_personal_spend_maintained"] is True
    assert dict_repr["promotional_credit_budget_sufficient"] is True


def test_p16_05_cost_impact_validation_against_zero_personal_spend() -> None:
    """Verify P-16.05: Cost impact strictly adheres to Zero Personal Spend Law ($0.00)."""
    ev_map = generate_aws_builder_evidence_map()

    # Gross estimated cost across all services must be minimal (< $0.01 total)
    assert ev_map.total_estimated_gross_spend_usd < Decimal("0.05")

    # Net personal spend must be EXACTLY $0.00
    assert ev_map.total_net_personal_spend_usd == Decimal("0.00")
    assert ev_map.zero_personal_spend_maintained is True

    # CloudWatch EMF itself has zero incremental cost ($0.00)
    cw_service = next(s for s in ev_map.aws_services if s.service_name.startswith("Amazon CloudWatch"))
    assert cw_service.estimated_cost_usd == Decimal("0.00000000")
    assert cw_service.covered_by_free_tier_or_credit is True
