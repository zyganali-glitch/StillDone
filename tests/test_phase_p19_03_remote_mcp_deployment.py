"""Tests for Phase P-19.03: Remote MCP Deployment & Live-Feasibility Preflight.

Validates:
1. Local Container Packaging & Profile:
   - Dockerfile specifies platform linux/arm64, non-root user stilldone, port 8000.
   - Command specifies --profile agentcore.
2. AgentCore Deployment Configuration:
   - create_agentcore_config sets host 0.0.0.0, port 8000, path /mcp, ping_path /ping.
   - Rate limit policy active by default; live_paid_path_enabled=False.
3. Tool Registration & Separation of Concerns:
   - Server exposes exactly mission_start and mission_status tools.
   - No live Bedrock inference tools or external Google mutation tools exposed over MCP.
4. Session Reuse & Anti-Duplicate Mechanism:
   - sigv4_proxy supports --session-id and env var AGENT_RUNTIME_SESSION_ID.
   - Prevents unintended additional AgentCore sessions (historical P-05 deviation).
5. AWS Account & Pricing Gate:
   - Missing credentials report NOT_OBSERVED and fail closed before cloud changes.
   - No assumptions made about unobserved account balances or credit sufficiency.
6. Conservative Cost-Risk Upper Bound:
   - Rate-based calculation conforms mathematically to official AWS Bedrock AgentCore rates.
   - Platform V1 (2 vCPU / 8 GB RAM, 300s max lifetime): single session ~$0.021217 USD,
     two sessions + allowances ~$0.047602 USD, strictly below $0.05 USD ceiling.
7. Preflight CLI Execution:
   - scripts/p19_03_preflight.py returns structured JSON and text report.
   - Returns BLOCKED / OPERATOR_DECISION_REQUIRED without cloud mutation.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent

_preflight_path = REPO_ROOT / "scripts" / "p19_03_preflight.py"
_spec = importlib.util.spec_from_file_location("p19_03_preflight", _preflight_path)
assert _spec is not None and _spec.loader is not None
preflight_mod: Any = importlib.util.module_from_spec(_spec)
sys.modules["p19_03_preflight"] = preflight_mod
_spec.loader.exec_module(preflight_mod)


def test_dockerfile_packaging_compliance() -> None:
    """1. Dockerfile specifies arm64, non-root user, port 8000, and agentcore profile."""
    dockerfile_path = REPO_ROOT / "Dockerfile"
    assessment = preflight_mod.inspect_dockerfile(dockerfile_path)

    assert assessment.dockerfile_exists is True
    assert assessment.platform == "linux/arm64"
    assert assessment.user == "stilldone"
    assert assessment.exposed_port == 8000
    assert assessment.cmd_profile == "agentcore"
    assert assessment.is_valid is True


def test_agentcore_config_and_rate_limit_policy() -> None:
    """2. create_agentcore_config sets 0.0.0.0, /mcp, /ping, and live_paid_path_enabled=False."""
    from stilldone.mcp.server import DEPLOYMENT_PROFILE_AGENTCORE, create_agentcore_config

    cfg = create_agentcore_config()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8000
    assert cfg.path == "/mcp"
    assert cfg.ping_path == "/ping"
    assert cfg.stateless_http is False
    assert cfg.deployment_profile == DEPLOYMENT_PROFILE_AGENTCORE
    assert cfg.auth_config is None

    policy = cfg.rate_limit_policy
    assert policy is not None
    assert policy.max_requests_per_window == 10
    assert policy.live_paid_path_enabled is False
    assert policy.internal_gross_ceiling == Decimal("0.05")


def test_mcp_interface_tools_isolation() -> None:
    """3. MCP server registers exactly mission_start/status with zero paid inference tools."""
    assessment = preflight_mod.inspect_mcp_interface()

    assert assessment.registered_tools == ["mission_start", "mission_status"]
    assert assessment.has_live_inference_tools is False
    assert assessment.has_calendar_mutation_tools is False
    assert assessment.has_tasks_mutation_tools is False
    assert assessment.live_paid_path_enabled is False
    assert assessment.rate_limit_policy_active is True
    assert assessment.is_bounded is True


def test_session_management_inspection() -> None:
    """4. sigv4_proxy supports CLI and env session ID configuration to prevent dual sessions."""
    assessment = preflight_mod.inspect_session_management()

    assert assessment.sigv4_proxy_exists is True
    assert assessment.supports_cli_session_id is True
    assert assessment.supports_env_session_id is True
    assert assessment.prevents_duplicate_sessions is True


def test_aws_account_preflight_missing_credentials_fails_closed() -> None:
    """5. Missing credentials or AWS CLI report NOT_OBSERVED and halt without mutation."""
    with patch("shutil.which", return_value=None):
        assessment = preflight_mod.inspect_aws_account()
        assert assessment.aws_cli_installed is False
        assert assessment.credentials_present is False
        assert "NOT_OBSERVED" in assessment.credit_balance_status
        assert assessment.live_observation_verdict == "NOT_OBSERVED"

    fake_cli = "C:\\Program Files\\Amazon\\AWSCLIV2\\aws.exe"
    with patch("shutil.which", return_value=fake_cli), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Unable to locate credentials")
        assessment = preflight_mod.inspect_aws_account()
        assert assessment.aws_cli_installed is True
        assert assessment.credentials_present is False
        assert assessment.live_observation_verdict == "NOT_OBSERVED"


def test_cost_risk_assessment_mathematical_bounds() -> None:
    """6. Conservative cost-risk bounds adhere strictly to official rates."""
    assessment = preflight_mod.calculate_cost_risk_assessment(can_observe_aws=False)

    assert assessment.agentcore_platform_version == "V1"
    assert assessment.hardware_ceiling_vcpu == 2
    assert assessment.hardware_ceiling_ram_gb == 8
    assert assessment.max_session_lifetime_seconds == 300
    assert assessment.idle_session_timeout_seconds == 60

    # Validate math: 5m of 2 vCPU @ 0.0895 + 8 GB @ 0.00945 = 5/60 * (0.179 + 0.0756) = 0.0212166...
    single_val = Decimal(assessment.single_session_cost_ceiling_usd)
    assert Decimal("0.021210") <= single_val <= Decimal("0.021220")

    # Campaign ceiling: 2 * single + 0.005169 non-compute = 0.042434 + 0.005169 = 0.047603...
    two_val = Decimal(assessment.two_session_cost_ceiling_usd)
    assert Decimal("0.047600") <= two_val <= Decimal("0.047610")
    assert two_val < Decimal("0.050000")

    # Zero spend cannot be guaranteed by software alone
    assert assessment.can_guarantee_zero_personal_spend is False


def test_preflight_report_generation_returns_blocked() -> None:
    """7. generate_preflight_report returns BLOCKED / OPERATOR_DECISION_REQUIRED."""
    report = preflight_mod.generate_preflight_report()

    assert report.task == "P-19.03 — Deploy final remote MCP/runtime path"
    assert "BLOCKED / OPERATOR_DECISION_REQUIRED" in report.decision
    assert report.packaging.is_valid is True
    assert report.mcp_interface.is_bounded is True
    assert report.session_management.prevents_duplicate_sessions is True
    assert "OPERATOR DECISION MANDATORY" in report.operator_guidance


def test_preflight_cli_execution_text_and_json() -> None:
    """8. Standalone CLI execution works in both text and JSON modes."""
    # Text mode
    res_text = subprocess.run(
        [sys.executable, str(_preflight_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "STILLDONE P-19.03 REMOTE MCP DEPLOYMENT PREFLIGHT REPORT" in res_text.stdout
    assert "BLOCKED / OPERATOR_DECISION_REQUIRED" in res_text.stdout
    assert "linux/arm64" in res_text.stdout
    assert "mission_start, mission_status" in res_text.stdout

    # JSON mode
    res_json = subprocess.run(
        [sys.executable, str(_preflight_path), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res_json.stdout)
    assert data["task"] == "P-19.03 — Deploy final remote MCP/runtime path"
    assert data["packaging"]["is_valid"] is True
    assert data["mcp_interface"]["is_bounded"] is True
    assert "BLOCKED / OPERATOR_DECISION_REQUIRED" in data["decision"]
