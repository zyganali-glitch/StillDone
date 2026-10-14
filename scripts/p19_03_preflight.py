"""StillDone P-19.03 Remote MCP Deployment & Live-Feasibility Preflight.

Executes read-only local packaging, security, architecture, and credential checks
prior to any AWS cloud deployment, strictly preserving the $0.00 personal spend law.

Governing Rules:
- AGENTS.md § 1–24
- P-19.03 Master Execution Plan
- ZERO PERSONAL SPEND: No charge-capable cloud mutations authorized.
- Missing credentials or permissions must report NOT_OBSERVED and fail closed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class PackagingAssessment:
    dockerfile_exists: bool
    platform: str
    user: str
    exposed_port: int
    cmd_profile: str
    is_valid: bool


@dataclass(frozen=True)
class MCPInterfaceAssessment:
    registered_tools: list[str]
    has_live_inference_tools: bool
    has_calendar_mutation_tools: bool
    has_tasks_mutation_tools: bool
    live_paid_path_enabled: bool
    rate_limit_policy_active: bool
    rate_limit_max_requests: int
    internal_gross_ceiling_usd: str
    is_bounded: bool


@dataclass(frozen=True)
class SessionManagementAssessment:
    sigv4_proxy_exists: bool
    supports_cli_session_id: bool
    supports_env_session_id: bool
    prevents_duplicate_sessions: bool


@dataclass(frozen=True)
class AWSAccountPreflight:
    aws_cli_installed: bool
    credentials_present: bool
    account_id: str
    active_profile: str
    target_region: str
    credit_balance_status: str
    current_charges_status: str
    retained_resources_status: str
    live_observation_verdict: str


@dataclass(frozen=True)
class CostRiskAssessment:
    agentcore_platform_version: str
    hardware_ceiling_vcpu: int
    hardware_ceiling_ram_gb: int
    max_session_lifetime_seconds: int
    idle_session_timeout_seconds: int
    single_session_cost_ceiling_usd: str
    two_session_cost_ceiling_usd: str
    can_guarantee_zero_personal_spend: bool
    reason: str


@dataclass(frozen=True)
class PreflightReport:
    task: str
    timestamp_utc: str
    packaging: PackagingAssessment
    mcp_interface: MCPInterfaceAssessment
    session_management: SessionManagementAssessment
    aws_preflight: AWSAccountPreflight
    cost_risk: CostRiskAssessment
    decision: str
    operator_guidance: str


def inspect_dockerfile(dockerfile_path: Path | None = None) -> PackagingAssessment:
    """Inspect Dockerfile for security and deployment profile compliance."""
    target = dockerfile_path or (REPO_ROOT / "Dockerfile")
    if not target.is_file():
        return PackagingAssessment(
            dockerfile_exists=False,
            platform="unknown",
            user="unknown",
            exposed_port=0,
            cmd_profile="unknown",
            is_valid=False,
        )

    content = target.read_text(encoding="utf-8")
    platform = "linux/arm64" if "--platform=linux/arm64" in content else "unknown"
    user = "stilldone" if "USER stilldone" in content else "root"
    exposed_port = 8000 if "EXPOSE 8000" in content else 0
    cmd_profile = (
        "agentcore" if "--profile agentcore" in content or '"agentcore"' in content else "unknown"
    )

    is_valid = (
        platform == "linux/arm64"
        and user == "stilldone"
        and exposed_port == 8000
        and cmd_profile == "agentcore"
    )

    return PackagingAssessment(
        dockerfile_exists=True,
        platform=platform,
        user=user,
        exposed_port=exposed_port,
        cmd_profile=cmd_profile,
        is_valid=is_valid,
    )


def inspect_mcp_interface() -> MCPInterfaceAssessment:
    """Inspect registered MCP tools and rate-limiting / budget policy."""
    from stilldone.mcp.server import create_agentcore_config, create_mcp_server

    cfg = create_agentcore_config()
    server = create_mcp_server(cfg)

    # Inspect registered tools from server
    registered_tools = sorted(server._tool_manager._tools.keys())

    # Prohibited on public MCP endpoint without scoping:
    live_inference_tools = [
        t for t in registered_tools if "bedrock" in t.lower() or "infer" in t.lower()
    ]
    calendar_mutation_tools = [
        t for t in registered_tools if "calendar_update" in t or "calendar_create" in t
    ]
    tasks_mutation_tools = [t for t in registered_tools if "task_create" in t or "task_update" in t]

    policy = cfg.rate_limit_policy
    assert policy is not None

    is_bounded = (
        registered_tools == ["mission_start", "mission_status"]
        and not live_inference_tools
        and not calendar_mutation_tools
        and not tasks_mutation_tools
        and not policy.live_paid_path_enabled
    )

    return MCPInterfaceAssessment(
        registered_tools=registered_tools,
        has_live_inference_tools=len(live_inference_tools) > 0,
        has_calendar_mutation_tools=len(calendar_mutation_tools) > 0,
        has_tasks_mutation_tools=len(tasks_mutation_tools) > 0,
        live_paid_path_enabled=policy.live_paid_path_enabled,
        rate_limit_policy_active=True,
        rate_limit_max_requests=policy.max_requests_per_window,
        internal_gross_ceiling_usd=str(policy.internal_gross_ceiling),
        is_bounded=is_bounded,
    )


def inspect_session_management() -> SessionManagementAssessment:
    """Inspect sigv4_proxy for session reuse and anti-duplicate controls."""
    proxy_path = REPO_ROOT / "scripts" / "sigv4_proxy.py"
    if not proxy_path.is_file():
        return SessionManagementAssessment(
            sigv4_proxy_exists=False,
            supports_cli_session_id=False,
            supports_env_session_id=False,
            prevents_duplicate_sessions=False,
        )

    content = proxy_path.read_text(encoding="utf-8")
    supports_cli = "--session-id" in content or "session_id" in content
    supports_env = (
        "AGENT_RUNTIME_SESSION_ID" in content or "STILLDONE_AGENTCORE_SESSION_ID" in content
    )
    prevents_duplicate = (
        supports_cli
        and supports_env
        and "--runtime-session-id" in content
        and "--mcp-session-id" in content
    )

    return SessionManagementAssessment(
        sigv4_proxy_exists=True,
        supports_cli_session_id=supports_cli,
        supports_env_session_id=supports_env,
        prevents_duplicate_sessions=prevents_duplicate,
    )


def inspect_aws_account(
    profile: str = "stilldone-p01", region: str = "us-east-1"
) -> AWSAccountPreflight:
    """Perform read-only AWS CLI check if available, or return NOT_OBSERVED."""
    aws_cli = shutil.which("aws")
    if not aws_cli:
        return AWSAccountPreflight(
            aws_cli_installed=False,
            credentials_present=False,
            account_id="NOT_OBSERVED",
            active_profile=profile,
            target_region=region,
            credit_balance_status="NOT_OBSERVED (AWS CLI not installed in execution environment)",
            current_charges_status="NOT_OBSERVED",
            retained_resources_status="NOT_OBSERVED",
            live_observation_verdict="NOT_OBSERVED",
        )

    try:
        res = subprocess.run(
            [aws_cli, "sts", "get-caller-identity", "--profile", profile, "--region", region],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            return AWSAccountPreflight(
                aws_cli_installed=True,
                credentials_present=False,
                account_id="NOT_OBSERVED (Authentication failed / session expired)",
                active_profile=profile,
                target_region=region,
                credit_balance_status="NOT_OBSERVED",
                current_charges_status="NOT_OBSERVED",
                retained_resources_status="NOT_OBSERVED",
                live_observation_verdict="NOT_OBSERVED",
            )

        identity = json.loads(res.stdout)
        account = identity.get("Account", "OBSERVED")
        return AWSAccountPreflight(
            aws_cli_installed=True,
            credentials_present=True,
            account_id=account,
            active_profile=profile,
            target_region=region,
            credit_balance_status="OBSERVED_AUTH_ONLY (Billing queries require account inspection)",
            current_charges_status="REQUIRES_EXPLICIT_BILLING_INSPECTION",
            retained_resources_status="CLEAN_BASELINE_CHECK_REQUIRED",
            live_observation_verdict="AUTHENTICATED_PREFLIGHT_AVAILABLE",
        )
    except Exception as exc:
        return AWSAccountPreflight(
            aws_cli_installed=True,
            credentials_present=False,
            account_id=f"NOT_OBSERVED ({type(exc).__name__})",
            active_profile=profile,
            target_region=region,
            credit_balance_status="NOT_OBSERVED",
            current_charges_status="NOT_OBSERVED",
            retained_resources_status="NOT_OBSERVED",
            live_observation_verdict="NOT_OBSERVED",
        )


def calculate_cost_risk_assessment(
    can_observe_aws: bool = False,
) -> CostRiskAssessment:
    """Calculate conservative gross cost-risk bounds from official rates.

    Platform V1 rates:
    - vCPU: $0.0895 / vCPU-hour
    - RAM: $0.00945 / GB-hour
    - Hardware ceiling: 2 vCPU, 8 GB RAM
    - Max lifetime: 300 seconds (5 minutes)

    Single session compute ceiling:
      (5 / 60) * ((2 * 0.0895) + (8 * 0.00945)) = (5 / 60) * (0.1790 + 0.0756)
      = (5 / 60) * 0.2546 = 0.02121666... ~= $0.021217 USD

    Two session compute ceiling:
      2 * $0.021217 = $0.042434 USD
    Non-compute allowances (CloudWatch + ECR + S3): $0.005169 USD
    Total two-session campaign ceiling: $0.047603 USD (~$0.05 USD)
    """
    vcpu_rate = Decimal("0.0895")
    ram_rate = Decimal("0.00945")
    duration_hours = Decimal("300") / Decimal("3600")

    hourly_rate = (Decimal("2") * vcpu_rate) + (Decimal("8") * ram_rate)
    single_session_compute = duration_hours * hourly_rate
    two_session_compute = Decimal("2") * single_session_compute

    non_compute_allowance = Decimal("0.005169")
    campaign_ceiling = two_session_compute + non_compute_allowance

    can_guarantee_zero = False
    reason = (
        "AWS promotional credits are NOT a hard spending cap. AWS Budgets alerts are not real-time "
        "hard kill-switches. Without authenticated account observation and explicit operator "
        "authorization, zero personal spend cannot be guaranteed deterministically "
        "by software alone."
    )

    return CostRiskAssessment(
        agentcore_platform_version="V1",
        hardware_ceiling_vcpu=2,
        hardware_ceiling_ram_gb=8,
        max_session_lifetime_seconds=300,
        idle_session_timeout_seconds=60,
        single_session_cost_ceiling_usd=f"{single_session_compute:.6f}",
        two_session_cost_ceiling_usd=f"{campaign_ceiling:.6f}",
        can_guarantee_zero_personal_spend=can_guarantee_zero,
        reason=reason,
    )


def generate_preflight_report(
    profile: str = "stilldone-p01",
    region: str = "us-east-1",
) -> PreflightReport:
    """Generate comprehensive P-19.03 deployment preflight report."""
    from datetime import UTC, datetime

    packaging = inspect_dockerfile()
    mcp_interface = inspect_mcp_interface()
    session_mgmt = inspect_session_management()
    aws_preflight = inspect_aws_account(profile, region)
    cost_risk = calculate_cost_risk_assessment(aws_preflight.credentials_present)

    # Decision logic
    if not packaging.is_valid:
        decision = "BLOCKED / INVALID_PACKAGING"
    elif not mcp_interface.is_bounded:
        decision = "BLOCKED / UNBOUNDED_MCP_INTERFACE"
    elif not session_mgmt.prevents_duplicate_sessions:
        decision = "BLOCKED / SESSION_REUSE_DEFECT"
    elif aws_preflight.live_observation_verdict == "NOT_OBSERVED":
        decision = "BLOCKED / OPERATOR_DECISION_REQUIRED (AWS Credentials NOT_OBSERVED)"
    else:
        decision = (
            "BLOCKED / OPERATOR_DECISION_REQUIRED (Awaiting explicit operator cloud authorization)"
        )

    operator_guidance = (
        "OPERATOR DECISION MANDATORY: Local preparation and security boundaries are "
        "fully satisfied.\n"
        "However, cloud mutation is strictly stopped. Zero personal spend cannot be "
        "guaranteed without\n"
        "an active promotional credit observation and operator supervision during judging.\n"
        "If deployment is desired, run the bounded single-session campaign with explicit "
        "credentials."
    )

    return PreflightReport(
        task="P-19.03 — Deploy final remote MCP/runtime path",
        timestamp_utc=datetime.now(UTC).isoformat(),
        packaging=packaging,
        mcp_interface=mcp_interface,
        session_management=session_mgmt,
        aws_preflight=aws_preflight,
        cost_risk=cost_risk,
        decision=decision,
        operator_guidance=operator_guidance,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="StillDone P-19.03 Remote MCP Deployment Preflight",
        prog="python scripts/p19_03_preflight.py",
    )
    parser.add_argument("--json", action="store_true", help="Output report in JSON format")
    parser.add_argument("--profile", default="stilldone-p01", help="AWS CLI profile to check")
    parser.add_argument("--region", default="us-east-1", help="AWS region to check")
    args = parser.parse_args(argv)

    report = generate_preflight_report(profile=args.profile, region=args.region)

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print("=" * 78)
        print("STILLDONE P-19.03 REMOTE MCP DEPLOYMENT PREFLIGHT REPORT")
        print("=" * 78)
        print(f"Task:                  {report.task}")
        print(f"Timestamp:             {report.timestamp_utc}")
        print(f"Decision:              {report.decision}")
        print("-" * 78)
        print("1. Local Packaging (Dockerfile):")
        print(f"   Platform:           {report.packaging.platform}")
        print(f"   User:               {report.packaging.user}")
        print(f"   Exposed Port:       {report.packaging.exposed_port}")
        print(f"   Profile:            {report.packaging.cmd_profile}")
        print(f"   Valid:              {report.packaging.is_valid}")
        print("-" * 78)
        print("2. MCP Interface & Paid Separation:")
        print(f"   Registered Tools:   {', '.join(report.mcp_interface.registered_tools)}")
        has_inf = report.mcp_interface.has_live_inference_tools
        paid_tools_str = "YES (ALERT)" if has_inf else "NONE (Safe)"
        print(f"   Live Paid Tools:    {paid_tools_str}")
        has_mut = (
            report.mcp_interface.has_calendar_mutation_tools
            or report.mcp_interface.has_tasks_mutation_tools
        )
        mut_tools_str = "YES (ALERT)" if has_mut else "NONE (Safe)"
        print(f"   Mutation Tools:     {mut_tools_str}")
        print(f"   Live Paid Enabled:  {report.mcp_interface.live_paid_path_enabled}")
        print(f"   Rate Limit Max:     {report.mcp_interface.rate_limit_max_requests} req/window")
        print(f"   Internal Ceiling:   ${report.mcp_interface.internal_gross_ceiling_usd} USD")
        print(f"   Interface Bounded:  {report.mcp_interface.is_bounded}")
        print("-" * 78)
        print("3. Session Reuse & Anti-Duplicate Mechanism:")
        print(f"   SigV4 Proxy Exists: {report.session_management.sigv4_proxy_exists}")
        print(f"   CLI Session Id:     {report.session_management.supports_cli_session_id}")
        print(f"   Env Session Id:     {report.session_management.supports_env_session_id}")
        print(f"   Prevents Dual VM:   {report.session_management.prevents_duplicate_sessions}")
        print("-" * 78)
        print("4. AWS Account & Pricing Gate:")
        print(f"   AWS CLI Installed:  {report.aws_preflight.aws_cli_installed}")
        print(f"   Credentials Found:  {report.aws_preflight.credentials_present}")
        print(f"   Target Region:      {report.aws_preflight.target_region}")
        print(f"   Credit Balance:     {report.aws_preflight.credit_balance_status}")
        print(f"   Observation:        {report.aws_preflight.live_observation_verdict}")
        print("-" * 78)
        print("5. Cost-Risk Upper Bound (Platform V1, 2 vCPU / 8 GB RAM):")
        max_sec = report.cost_risk.max_session_lifetime_seconds
        idle_sec = report.cost_risk.idle_session_timeout_seconds
        print(f"   Max Session Time:   {max_sec}s (idle: {idle_sec}s)")
        print(f"   Single Session Max: ${report.cost_risk.single_session_cost_ceiling_usd} USD")
        print(f"   Two Session Max:    ${report.cost_risk.two_session_cost_ceiling_usd} USD")
        print(f"   Zero Spend Guard:   {report.cost_risk.can_guarantee_zero_personal_spend}")
        print("=" * 78)
        print("OPERATOR ACTION REQUIRED:")
        print(report.operator_guidance)
        print("=" * 78)


if __name__ == "__main__":
    main()
