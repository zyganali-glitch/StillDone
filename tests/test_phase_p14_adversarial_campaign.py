"""Tests for Phase P-14 Failure & Adversarial Campaign.

Verifies:
- P-14.01: Provider 5xx/timeout before mutation
- P-14.02: Timeout after mutation but before response
- P-14.03: Read-back mismatch after execute success
- P-14.04: OAuth permission revoked mid-mission
- P-14.05: Model returns malformed/unsupported/over-authorized plan
- P-14.06: Approval replay/mismatch/stale approval
- P-14.07: Evidence tamper/replay/stale receipt
- P-14.08: Duplicate retry stress
"""

from __future__ import annotations

import pytest

from stilldone.adversarial import (
    AdversarialCampaignHarness,
    AdversarialScenarioResult,
    FaultyCalendarTransport,
    FaultyTasksTransport,
)


@pytest.fixture
def harness() -> AdversarialCampaignHarness:
    return AdversarialCampaignHarness()


def test_p14_01_provider_5xx_before_mutation(harness: AdversarialCampaignHarness) -> None:
    result = harness.run_p14_01_provider_5xx_before_mutation()
    assert result.task_id == "P-14.01"
    assert result.status == "PASS"
    assert result.writes_performed == 0
    assert result.is_safe is True
    assert "ZERO_UNAUTHORIZED_MUTATION" in result.invariants_verified


def test_p14_02_timeout_after_mutation_before_response(
    harness: AdversarialCampaignHarness,
) -> None:
    result = harness.run_p14_02_timeout_after_mutation_before_response()
    assert result.task_id == "P-14.02"
    assert result.status == "PASS"
    assert result.writes_performed == 1
    assert result.duplicates_detected == 0
    assert result.is_safe is True
    assert "LOST_RESPONSE_NOT_PERMISSION_FOR_SECOND_EFFECT" in result.invariants_verified


def test_p14_03_readback_mismatch_after_execute_success(
    harness: AdversarialCampaignHarness,
) -> None:
    result = harness.run_p14_03_readback_mismatch_after_execute_success()
    assert result.task_id == "P-14.03"
    assert result.status == "PASS"
    assert result.writes_performed == 1
    assert result.is_safe is True
    assert "EXECUTE_SUCCESS_NOT_VERIFICATION" in result.invariants_verified


def test_p14_04_oauth_revoked_mid_mission(harness: AdversarialCampaignHarness) -> None:
    result = harness.run_p14_04_oauth_revoked_mid_mission()
    assert result.task_id == "P-14.04"
    assert result.status == "PASS"
    assert result.writes_performed == 0
    assert result.is_safe is True
    assert "NON_RETRYABLE_AUTH_FAILURE" in result.invariants_verified


def test_p14_05_model_malformed_unsupported_overauthorized(
    harness: AdversarialCampaignHarness,
) -> None:
    result = harness.run_p14_05_model_malformed_unsupported_overauthorized()
    assert result.task_id == "P-14.05"
    assert result.status == "PASS"
    assert result.writes_performed == 0
    assert result.is_safe is True
    assert "ZERO_MODEL_AUTHORITY" in result.invariants_verified


def test_p14_06_approval_replay_mismatch_stale(
    harness: AdversarialCampaignHarness,
) -> None:
    result = harness.run_p14_06_approval_replay_mismatch_stale()
    assert result.task_id == "P-14.06"
    assert result.status == "PASS"
    assert result.writes_performed == 0
    assert result.is_safe is True
    assert "ATOMIC_APPROVAL_CONSUMPTION" in result.invariants_verified


def test_p14_07_evidence_tamper_replay_stale_receipt(
    harness: AdversarialCampaignHarness,
) -> None:
    result = harness.run_p14_07_evidence_tamper_replay_stale_receipt()
    assert result.task_id == "P-14.07"
    assert result.status == "PASS"
    assert result.writes_performed == 0
    assert result.is_safe is True
    assert "CRYPTOGRAPHIC_RECEIPT_INTEGRITY" in result.invariants_verified


def test_p14_08_duplicate_retry_stress(harness: AdversarialCampaignHarness) -> None:
    result = harness.run_p14_08_duplicate_retry_stress()
    assert result.task_id == "P-14.08"
    assert result.status == "PASS"
    assert result.writes_performed == 1
    assert result.duplicates_detected == 9
    assert result.is_safe is True
    assert "EXACTLY_ONE_MUTATION_EFFECT" in result.invariants_verified


def test_p14_all_scenarios_pass_in_campaign(harness: AdversarialCampaignHarness) -> None:
    results = harness.run_all()
    assert len(results) == 8
    for task_id, res in results.items():
        assert res.status == "PASS", f"Scenario {task_id} failed"
        assert res.is_safe is True
