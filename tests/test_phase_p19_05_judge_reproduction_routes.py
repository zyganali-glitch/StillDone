"""Tests for Phase P-19.05: No-Install Judge Path and Full Reproduction Routes.

Validates:
1. No-Install Browser Review Path:
   - docs/REPRODUCTION.md and README.md clearly document the no-install path.
   - Points directly to artifacts/judge_exhibit/index.html and
     artifacts/stilldone_judge_exhibit.html.
2. Truth Matrix Documentation:
   - Distinguishes RECORDED_LIVE, FIXTURE / LOCAL_EXECUTION, and BLOCKED / NOT_RUN.
   - Accurately reports AWS Bedrock Nova Micro, AgentCore microVM, Google Calendar/Tasks,
     and Open-Meteo.
3. Historical Receipts vs Current State Explanation:
   - Clearly explains ReceiptProjection vs CurrentStateProjection.
   - Explains the Drift Law invariant (READY -> DRIFTED while historical receipt hash is preserved).
4. Dual Environment Reproduction & Setup Downloads Distinction:
   - Explains Core mcp >= 2.2.0 vs Strands mcp < 2.2.0 isolation.
   - Discloses that package manager wheel downloads from PyPI are distinct from zero
     external cloud calls.
5. Link Integrity & Path Sanitization:
   - All markdown links in docs/REPRODUCTION.md, README.md, and
     docs/P19_04_PUBLIC_JUDGE_EXHIBIT.md resolve to existing files.
   - No broken links.
   - No machine-specific absolute developer paths leaked in public judge guides.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_reproduction_guide_contains_no_install_browser_path() -> None:
    """1. docs/REPRODUCTION.md and README.md prominently document no-install browser path."""
    repro_path = REPO_ROOT / "docs" / "REPRODUCTION.md"
    readme_path = REPO_ROOT / "README.md"

    assert repro_path.is_file(), "docs/REPRODUCTION.md missing"
    assert readme_path.is_file(), "README.md missing"

    repro_content = repro_path.read_text(encoding="utf-8")
    readme_content = readme_path.read_text(encoding="utf-8")

    # Path A: No-Install Browser Review Path
    assert "NO-INSTALL BROWSER REVIEW PATH" in repro_content.upper()
    assert "artifacts/judge_exhibit/index.html" in repro_content
    assert "artifacts/stilldone_judge_exhibit.html" in repro_content

    # Section 2.2 must reflect published status and never regress to NOT_PUBLISHED
    assert "https://stilldone-judge-exhibit.pages.dev" in repro_content
    assert "NOT_PUBLISHED" not in repro_content
    assert "OPERATOR_CONFIRMED_PUBLISHED" in repro_content
    assert "NOT GUARANTEED" in repro_content

    assert "No-Install Browser Review Path" in readme_content
    assert "artifacts/judge_exhibit/index.html" in readme_content


def test_truth_matrix_distinguishes_live_fixture_and_blocked() -> None:
    """2. docs/REPRODUCTION.md contains truth matrix distinguishing live, fixture, and blocked."""
    repro_path = REPO_ROOT / "docs" / "REPRODUCTION.md"
    content = repro_path.read_text(encoding="utf-8")

    assert "Truth Matrix" in content
    assert "RECORDED_LIVE" in content
    assert "FIXTURE / LOCAL_EXECUTION" in content
    assert "BLOCKED / NOT_RUN" in content
    assert "BLOCKED_LIVE / NOT_RUN" in content

    # Component references
    assert "AWS Bedrock Nova Micro" in content
    assert "AWS Bedrock AgentCore Runtime" in content
    assert "Google Calendar API" in content
    assert "Google Tasks API" in content
    assert "Open-Meteo Weather API" in content


def test_receipt_vs_current_state_drift_explanation() -> None:
    """3. docs/REPRODUCTION.md explains historical receipts vs current state drift."""
    repro_path = REPO_ROOT / "docs" / "REPRODUCTION.md"
    content = repro_path.read_text(encoding="utf-8")

    assert "ReceiptProjection" in content
    assert "CurrentStateProjection" in content
    assert "DRIFTED" in content
    assert "READY" in content
    assert "Permanence Law" in content or "permanently" in content


def test_dual_environment_and_setup_downloads_distinction() -> None:
    """4. docs/REPRODUCTION.md explains dual environment isolation and setup downloads."""
    repro_path = REPO_ROOT / "docs" / "REPRODUCTION.md"
    content = repro_path.read_text(encoding="utf-8")

    assert "Dual Python Environment" in content
    assert "mcp >= 2.2.0" in content
    assert "strands-agents == 1.57.2" in content
    assert "uv.lock" in content
    assert "Setup Downloads Are Not Cloud API Calls" in content or "package installation" in content


def test_markdown_document_links_integrity() -> None:
    """5. All relative links in REPRODUCTION.md, README.md, and exhibits resolve."""
    docs_to_check = [
        REPO_ROOT / "docs" / "REPRODUCTION.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "P19_04_PUBLIC_JUDGE_EXHIBIT.md",
    ]

    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    for doc_path in docs_to_check:
        assert doc_path.is_file(), f"Document missing: {doc_path}"
        content = doc_path.read_text(encoding="utf-8")

        for match in link_pattern.finditer(content):
            link_target = match.group(2).strip()

            # Skip external web URLs and anchors
            if (
                link_target.startswith("http://")
                or link_target.startswith("https://")
                or link_target.startswith("#")
                or link_target.startswith("mailto:")
            ):
                continue

            # Strip any internal anchor
            clean_target = link_target.split("#")[0]
            if not clean_target:
                continue

            target_path = (doc_path.parent / clean_target).resolve()
            msg = f"Broken link in {doc_path.name}: '{link_target}' -> {target_path}"
            assert target_path.exists(), msg


def test_no_machine_specific_absolute_paths_leaked() -> None:
    """6. All public P-19 guides do not leak developer-machine-specific home directories."""
    docs_to_check = [
        REPO_ROOT / "docs" / "REPRODUCTION.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "P19_04_PUBLIC_JUDGE_EXHIBIT.md",
        REPO_ROOT / "docs" / "P19_03_REMOTE_MCP_DEPLOYMENT_PREFLIGHT.md",
        REPO_ROOT / "docs" / "P19_03_OPERATOR_AWS_OBSERVATIONS_2026-10-14.md",
        REPO_ROOT / "docs" / "P19_06_FRESH_ENVIRONMENT_EVIDENCE.md",
    ]

    for doc_path in docs_to_check:
        if not doc_path.is_file():
            continue
        content = doc_path.read_text(encoding="utf-8")
        assert "c:\\users\\" not in content.lower(), (
            f"Machine-specific path leaked in {doc_path.name}"
        )
        assert "/home/" not in content.lower(), (
            f"Machine-specific linux home leaked in {doc_path.name}"
        )


def test_truth_matrix_maps_authentic_historical_evidence_milestones() -> None:
    """7. Verifies REPRODUCTION.md maps authentic historical evidence files and milestone IDs."""
    repro_path = REPO_ROOT / "docs" / "REPRODUCTION.md"
    content = repro_path.read_text(encoding="utf-8")

    # Calendar: P-01.05 (read), P-06.08 (live update), separated from P-11.06 (local approval)
    assert "P01_05_LIVE_GOOGLE_READ_EVIDENCE.md" in content
    assert "P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md" in content
    assert "P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md" in content

    cal_rows = [
        line for line in content.splitlines() if "**Google Calendar API Integration**" in line
    ]
    assert len(cal_rows) == 1
    assert "RECORDED_LIVE" in cal_rows[0]
    assert "P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md" in cal_rows[0]
    assert "AUTHORIZED_BY_BOUND_APPROVAL" in cal_rows[0]
    assert "P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md" not in cal_rows[0]

    approval_rows = [
        line
        for line in content.splitlines()
        if "**Cryptographic Approval & Replay-Prevention Lifecycle**" in line
    ]
    assert len(approval_rows) == 1
    approval_cols = [col.strip() for col in approval_rows[0].split("|")]
    assert "LOCAL_EXECUTION / FIXTURE" in approval_cols[2]
    assert "RECORDED_LIVE" not in approval_cols[2]
    assert "P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md" in approval_rows[0]
    assert "ApprovalLedger" in approval_rows[0]
    assert "FakeGoogleCalendarTransport" in approval_rows[0]

    agentcore_rows = [
        line for line in content.splitlines() if "**AWS Bedrock AgentCore Runtime**" in line
    ]
    assert len(agentcore_rows) == 1
    assert "mission_start" in agentcore_rows[0]
    assert "DRAFT" in agentcore_rows[0]
    assert "mission_status" in agentcore_rows[0]

    # Tasks: P-06.07 (live create & read-back)
    assert "P06_07_LIVE_TASKS_VERIFIED_EVIDENCE.md" in content

    # Weather: P-01.06 (read), P-06.06 (closure)
    assert "P01_06_LIVE_OPEN_METEO_EVIDENCE.md" in content
    assert "P06_06_LIVE_WEATHER_FINAL_CLOSURE_EVIDENCE.md" in content

    # Bedrock Nova Micro: P-01.02 & P-07.06
    assert "P01_02_LIVE_BEDROCK_EVIDENCE.md" in content
    assert "P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md" in content

    # P-13 killer mission slice is marked FIXTURE, not cited as live Google read-back proof
    assert "P-13.01–P-13.07" in content
    assert "NOT cited as live Google mutation proof" in content
