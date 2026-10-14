"""Tests for Phase P-20 Competition Evidence, Feedback & Claim Audit.

Validates:
- P-20.01: Consolidated factual product feedback for every Amazon/AWS tool used.
- P-20.02: Consolidated friction logs and actionable suggestions without secrets.
- P-20.03: Claim-by-claim evidence manifest where all mapped files and tests exist on disk.
- P-20.04: Authoritative judging-criteria map (4 criteria at 25% each + mini challenges).
- P-20.05: Comprehensive evidence provenance disclosure (LIVE, RECORDED_LIVE, etc.).
- P-20.06: Clean-room donor audit, license verification, and chronological build-period truth.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_p20_01_aws_product_feedback_integrity() -> None:
    """P-20.01: Verifies factual product feedback document for all Amazon/AWS tools."""
    doc_path = REPO_ROOT / "docs" / "P20_01_AWS_PRODUCT_FEEDBACK.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    assert "P-20.01" in content
    assert "Amazon Bedrock Runtime" in content
    assert "amazon.nova-micro-v1:0" in content
    assert "Strands Agents SDK" in content
    assert "strands-agents 1.57.2" in content
    assert "Amazon Bedrock AgentCore Runtime" in content
    assert "@aws/agentcore" in content
    assert "AWS CLI v2" in content
    assert "Amazon Alexa+ MCP Integration Surface" in content

    # Zero secrets verification
    assert "AKIA" not in content
    assert "ya29." not in content
    assert "AIza" not in content
    assert "client_secret" not in content


def test_p20_02_competition_friction_log_consolidation() -> None:
    """P-20.02: Verifies consolidated friction logs and actionable suggestions."""
    doc_path = REPO_ROOT / "docs" / "COMPETITION_FEEDBACK_LOG.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")

    # Verify all chronological entries exist
    expected_entries = [
        "F-20260927-01",
        "F-20260927-02",
        "F-20260927-03",
        "F-20260928-01",
        "F-20260928-02",
        "F-20260929-01",
        "F-20261001-01",
        "F-20261001-02",
        "F-20261005-01",
        "F-20261014-01",
        "F-20261014-02",
    ]
    for entry in expected_entries:
        assert entry in content, f"Missing friction log entry: {entry}"

    # Actionable suggestions check
    assert "Actionable suggestion:" in content
    assert "Upstream Strands Agents MCP Dependency Pinning Conflict" in content
    assert "Bedrock AgentCore SigV4 Proxy Session Isolation Boundary" in content
    assert "Cloudflare Pages Direct Upload DNS Resolution on Residential ISPs" in content

    # Zero secrets check
    assert "AKIA" not in content
    assert "ya29." not in content
    assert "client_secret" not in content


def test_p20_03_claim_manifest_and_file_existence() -> None:
    """P-20.03: Verifies claim manifest and proves every cited path exists on disk."""
    doc_path = REPO_ROOT / "docs" / "P20_03_EVIDENCE_MANIFEST.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    assert "P-20.03" in content
    assert "Claim-by-Claim Evidence Manifest" in content

    # Verify claims C-01 through C-13 are documented
    for claim_num in range(1, 14):
        claim_id = f"C-{claim_num:02d}"
        assert claim_id in content, f"Missing claim: {claim_id}"

    # Verify negative bounds / non-capabilities are explicitly disclosed
    assert "Negative Claims & Explicit Non-Capabilities" in content
    assert "No Live Backend on Public Exhibit" in content
    assert "Alexa+ Partner Access is NOT_ESTABLISHED" in content
    assert "Current Remote Deployment is BLOCKED / NOT_RUN" in content
    assert "Complete 7-Step Killer Demo in Exhibit is FIXTURE Playback" in content

    # Extract backtick paths like `src/...`, `tests/...`, `docs/...`, `scripts/...`
    cited_paths = set(re.findall(r"`((?:src|tests|docs|scripts)/[^`]+)`", content))
    assert len(cited_paths) >= 15, "Expected at least 15 cited repo paths in manifest"

    # Check each cited file or directory actually exists in the repository
    for rel_path in cited_paths:
        target = REPO_ROOT / rel_path
        assert target.exists(), f"Manifest cited non-existent path: {rel_path}"


def test_p20_04_judging_criteria_mapping_completeness() -> None:
    """P-20.04: Verifies judging-criteria map against official Devpost criteria."""
    doc_path = REPO_ROOT / "docs" / "P20_04_JUDGING_CRITERIA_MAP.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    assert "P-20.04" in content
    assert "Technological Implementation (25%)" in content
    assert "Design (25%)" in content
    assert "Potential Impact (25%)" in content
    assert "Quality of Idea (25%)" in content
    assert "AWS Builder Mini Challenge" in content
    assert "Open Source Mini Challenge" in content


def test_p20_05_provenance_and_simulation_disclosure() -> None:
    """P-20.05: Verifies complete live/recorded/fixture/simulated disclosure."""
    doc_path = REPO_ROOT / "docs" / "P20_05_EVIDENCE_PROVENANCE_DISCLOSURE.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    assert "P-20.05" in content
    assert "LIVE_AWS" in content
    assert "LIVE_GOOGLE" in content
    assert "RECORDED_LIVE" in content
    assert "FIXTURE" in content
    assert "SIMULATED ALEXA+ EXPERIENCE" in content
    assert "NOT_RUN / BLOCKED" in content

    # Verifies explicit 7-step fixture distinction
    assert "Complete 7-Step Exhibit Status" in content
    assert "FIXTURE playback" in content


def test_p20_06_donor_license_and_clean_room_audit() -> None:
    """P-20.06: Verifies clean-room audit (0 donor code lines imported) and licenses."""
    doc_path = REPO_ROOT / "docs" / "DONOR_PROVENANCE.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    assert "Section 7" in content or "## 7. Phase P-20 Final Audit" in content
    assert "P-20.06" in content
    assert "STRICTLY ZERO (0) LINES" in content
    assert "CONCEPT_ONLY" in content
    assert "ZERO COPYLEFT / ZERO PROPRIETARY RESTRICTIONS" in content

    # Check third-party permissive licenses
    assert "MIT License" in content
    assert "Apache-2.0 License" in content
    assert "Creative Commons Attribution 4.0 International" in content

    # Verify no donor source directories exist in src/
    src_dir = REPO_ROOT / "src"
    for forbidden in ["changemesh", "contextseal", "universal_agent_os", "basebreak"]:
        assert not (src_dir / forbidden).exists(), f"Forbidden donor directory found: {forbidden}"
