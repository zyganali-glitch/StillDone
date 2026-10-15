"""Tests for Phase P-20 Competition Evidence, Feedback & Claim Audit.

Validates:
- P-20.01: Consolidated factual product feedback for Amazon/AWS tools with verified metrics.
- P-20.02: Consolidated friction logs with causal uncertainty for network incidents.
- P-20.03: Claim-by-claim manifest with 6 canonical provenance values and bounded limits.
- P-20.04: Devpost judging criteria, friction bonus, and Open Source Mini Challenge bounds.
- P-20.05: Comprehensive provenance disclosure with distinct surface and status categories.
- P-20.06: Scoped clean-room donor audit, transitive license bounds, and Open-Meteo truth.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_p20_01_aws_product_feedback_integrity() -> None:
    """P-20.01: Verifies factual product feedback, pricing, and latency claims."""
    doc_path = REPO_ROOT / "docs" / "P20_01_AWS_PRODUCT_FEEDBACK.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    norm_content = " ".join(content.split())
    assert "P-20.01" in content
    assert "Amazon Bedrock Runtime" in content
    assert "amazon.nova-micro-v1:0" in content
    assert "Strands Agents SDK" in content
    assert "strands-agents 1.57.2" in content
    assert "Amazon Bedrock AgentCore Runtime" in content
    assert "@aws/agentcore" in content
    assert "AWS CLI v2" in content
    assert "Amazon Alexa+ MCP Integration Surface" in content

    # Substantive latency assertions: distinguish recorded traces from benchmarks
    assert "Observed Single Live Inference Duration" in content
    assert "NOT a formal cold-start latency benchmark" in norm_content
    assert "Observed Remote Echo Latency" in content
    assert "NOT an AgentCore microVM spin-up or cold-start benchmark" in norm_content

    # Pricing assertions: bound to official September 2026 snapshot
    assert "$0.035 per 1,000,000 input tokens" in content
    assert "$0.140 per 1,000,000 output tokens" in content

    # Token consumption assertions: verified P-01.02 receipt facts vs P-07.06 streaming facts
    assert "inputTokens=8" in content
    assert "outputTokens=3" in content
    assert "totalTokens=11" in content
    assert "NOT_DETERMINISTICALLY_OBSERVED" in content
    assert "214 input tokens" not in content
    assert "142 output tokens" not in content
    assert "$0.00008 / 1K" not in content

    # Architecture constraint truth
    assert "project architecture choice" in norm_content or "project constraint" in norm_content

    # Security truth: temporary credentials mitigate rather than eliminate all operational risk
    assert (
        "mitigate rather than completely eliminate all operational security risks" in norm_content
    )

    # Zero secrets verification
    assert "AKIA" not in content
    assert "ya29." not in content
    assert "AIza" not in content
    assert "client_secret" not in content


def test_p20_02_competition_friction_log_consolidation() -> None:
    """P-20.02: Verifies consolidated friction logs and DNS incident causal uncertainty."""
    doc_path = REPO_ROOT / "docs" / "COMPETITION_FEEDBACK_LOG.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")

    # Verify all 11 chronological entries exist
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

    # F-20261014-02 causal uncertainty assertions
    assert "UNKNOWN / SUSPECTED DNS OR NETWORK PATH" in content
    assert "NOT independently established" in content or "unconfirmed" in content

    # Zero secrets check
    assert "AKIA" not in content
    assert "ya29." not in content
    assert "client_secret" not in content


def test_p20_03_claim_manifest_and_file_existence() -> None:
    """P-20.03: Verifies claim manifest, exact provenance classes, and disk references."""
    doc_path = REPO_ROOT / "docs" / "P20_03_EVIDENCE_MANIFEST.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    assert "P-20.03" in content
    assert "Claim-by-Claim Evidence Manifest" in content

    # Verify claims C-01 through C-13 are documented
    for claim_num in range(1, 14):
        claim_id = f"C-{claim_num:02d}"
        assert claim_id in content, f"Missing claim: {claim_id}"

    # Six canonical execution provenance values
    assert "six canonical execution provenance values" in content

    # C-02 must be FIXTURE & LOCAL_EXECUTION, not RECORDED_LIVE
    c02_line = [line for line in content.splitlines() if "**C-02**" in line][0]
    assert "FIXTURE" in c02_line
    assert "LOCAL_EXECUTION" in c02_line
    assert "RECORDED_LIVE" not in c02_line.split("|")[3]  # Provenance column check

    # C-05: operator zero-spend policy & snapshot, not global guarantee
    c05_line = [line for line in content.splitlines() if "**C-05**" in line][0]
    assert "Zero Personal Spend ($0.00)" in c05_line
    assert "snapshot" in c05_line.lower()

    # C-07: execution date must be 2026-10-05
    c07_line = [line for line in content.splitlines() if "**C-07**" in line][0]
    assert "2026-10-05" in c07_line
    assert "2026-10-06" not in c07_line

    # C-10: deployed SHA ccf79f6 distinguished from refreshed exhibit
    c10_line = [line for line in content.splitlines() if "**C-10**" in line][0]
    assert "ccf79f6" in c10_line

    # Extract backtick paths like `src/...`, `tests/...`, `docs/...`, `scripts/...`
    cited_paths = set(re.findall(r"`((?:src|tests|docs|scripts)/[^`]+)`", content))
    assert len(cited_paths) >= 15, "Expected at least 15 cited repo paths in manifest"

    # Check each cited file or directory actually exists in the repository
    for rel_path in cited_paths:
        target = REPO_ROOT / rel_path
        assert target.exists(), f"Manifest cited non-existent path: {rel_path}"


def test_p20_04_judging_criteria_mapping_completeness() -> None:
    """P-20.04: Verifies judging-criteria map, bonus, and Open Source Mini Challenge bounds."""
    doc_path = REPO_ROOT / "docs" / "P20_04_JUDGING_CRITERIA_MAP.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    assert "P-20.04" in content
    assert "Stage 1" in content
    assert "Friction-Log Bonus" in content or "10% bonus" in content
    assert "Technological Implementation (25%)" in content
    assert "Design (25%)" in content
    assert "Potential Impact (25%)" in content
    assert "Quality of Idea (25%)" in content
    assert "AWS Builder Mini Challenge" in content
    assert "Open Source Mini Challenge" in content

    # Stage 1 baseline viability vs submission requirements separation (Defect A)
    assert "Submission Requirements (Prerequisites)" in content
    assert "Baseline Viability Assessment" in content or "baseline viability assessment" in content
    assert "project theme fit" in content
    assert "meaningful application of required APIs/SDKs" in content
    # Reject Stage 1 being described as merely mandatory submission-field validation
    assert "Stage 1: Eligibility Gate (Public repository" not in content
    assert not re.search(r"Stage 1.*merely mandatory submission", content, re.IGNORECASE)

    # Truthful simulated voice surface without audio synthesis or live device execution (Defect B)
    assert "SIMULATED ALEXA+ EXPERIENCE" in content
    assert "VoiceSummary" in content
    assert "src/stilldone/judge_ux/builder.py" in content
    assert "src/stilldone/judge_ux/html_renderer.py" in content
    assert "No Live Voice Device or Audio Synthesis" in content
    # Reject unsupported live Alexa+/Echo Show operation claims and audio synthesis
    assert "Synthesizes concise voice summaries" not in content
    assert "operate a live Echo Show or Alexa+ client device" in content
    assert "do not generate synthesized speech (audio / TTS) or operate a live Echo Show" in content

    # Open Source Mini Challenge eligibility assertions
    assert "packages/mcp_verify/" in content
    assert "BLOCKED_EXTERNAL / NOT_RUN" in content
    assert "ELIGIBILITY_UNCONFIRMED / OPERATOR_ACTION_REQUIRED" in content

    # Open Source Mini Challenge truthful package claims (rejecting false MIT and standalone CLI)
    assert "MIT" not in content
    assert "standalone CLI" not in content
    assert "Apache-2.0" in content
    assert "No packaged CLI entry point or CLI implementation exists" in content

    # Source-grounded package reality check against actual packages/mcp_verify files
    mcp_pyproject = REPO_ROOT / "packages" / "mcp_verify" / "pyproject.toml"
    assert mcp_pyproject.is_file()
    pyproject_text = mcp_pyproject.read_text(encoding="utf-8")
    assert 'license = "Apache-2.0"' in pyproject_text
    assert "project.scripts" not in pyproject_text

    mcp_license = REPO_ROOT / "packages" / "mcp_verify" / "LICENSE"
    assert mcp_license.is_file()
    license_text = mcp_license.read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text


def test_p20_05_provenance_and_simulation_disclosure() -> None:
    """P-20.05: Verifies complete taxonomy separation and verified script references."""
    doc_path = REPO_ROOT / "docs" / "P20_05_EVIDENCE_PROVENANCE_DISCLOSURE.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    assert "P-20.05" in content
    assert "six canonical execution provenance values" in content
    assert "LIVE_AWS" in content
    assert "LIVE_GOOGLE" in content
    assert "RECORDED_LIVE" in content
    assert "FIXTURE" in content
    assert "LOCAL_EXECUTION" in content
    assert "LIVE_EXTERNAL" in content

    # Separation of distinct categories
    assert "SIMULATED ALEXA+ EXPERIENCE" in content
    assert "NOT_RUN" in content
    assert "OPERATOR_OBSERVED" in content

    # Verified script references
    assert "scripts/demo_resources.py" in content
    assert "scripts/p19_02_demo_tooling.py" not in content

    # Semantic rejection of false client simulation and audio synthesis claims (Defect C)
    assert "fully functional multimodal client" not in content
    assert "spoken phrase synthesis" not in content

    # Verified source reality assertions
    assert "src/stilldone/judge_ux/builder.py" in content
    assert "src/stilldone/judge_ux/html_renderer.py" in content
    assert "voice-ready English text" in content
    assert "no audio player, speech synthesis implementation" in content
    assert "FIXTURE playback" in content


def test_p20_06_donor_license_and_clean_room_audit() -> None:
    """P-20.06: Verifies clean-room audit, scoped dependency licenses, and Open-Meteo terms."""
    doc_path = REPO_ROOT / "docs" / "DONOR_PROVENANCE.md"
    assert doc_path.is_file(), f"Missing required document: {doc_path}"

    content = doc_path.read_text(encoding="utf-8")
    assert "Section 7" in content or "## 7. Phase P-20 Final Audit" in content
    assert "P-20.06" in content
    assert "STRICTLY ZERO (0) LINES" in content
    assert "CONCEPT_ONLY" in content

    # Scoped dependency licensing and transitive closure limitation
    assert "NOT_AUDITED_TRANSITIVE_CLOSURE" in content
    assert "ZERO COPYLEFT / ZERO PROPRIETARY RESTRICTIONS" not in content

    # Open-Meteo licensing vs exhibit fixture data truth
    assert "GPL v3" in content or "GPL" in content
    assert "CC BY 4.0" in content
    assert "FakeOpenMeteoTransport" in content
    assert "offline synthetic fixture" in content

    # Verify no donor source directories exist in src/
    src_dir = REPO_ROOT / "src"
    for forbidden in ["changemesh", "contextseal", "universal_agent_os", "basebreak"]:
        assert not (src_dir / forbidden).exists(), f"Forbidden donor directory found: {forbidden}"
