# P-19.03 Remote MCP Deployment Preflight & Live-Feasibility Gate

**Document ID**: `docs/P19_03_REMOTE_MCP_DEPLOYMENT_PREFLIGHT.md`  
**Task**: `P-19.03 — Deploy final remote MCP/runtime path`  
**Task State**: `COMPLETED (Read-Only Preflight & Local Preparation; Live Cloud Mutations STOPPED)`  
**Operator Decision Outcome**: **`BLOCKED / OPERATOR_DECISION_REQUIRED`**  
**Cloud Mutations Executed**: `NONE` (Zero AWS resources created, updated, or deleted; $0.00 personal spend maintained)  
**Governing Authority**: `AGENTS.md` § 1–24; Zero Personal Spend Law (§ 12); Live-First Law (§ 9); Evidence Provenance (§ 10); Desired-State Authority (§ 5)  

---

## 1. Executive Summary & Gate Status

This document establishes the verified local readiness, architecture, cost-risk boundaries, and account observation status for the remote Model Context Protocol (MCP) deployment on AWS Bedrock AgentCore Runtime in `us-east-1`.

In strict accordance with the task specification:
> *"The current instruction authorizes READ-ONLY CLOUD PREFLIGHT and LOCAL PREPARATION only. It does not authorize charge-capable cloud mutations."*

All local preparation, packaging validation, interface boundedness audits, rate-limiting policies, and session reuse hardening are **COMPLETED**. Because cloud credentials were not present in the local execution environment, live AWS account observation is deterministically classified as **`NOT_OBSERVED`**, and all charge-capable cloud mutations remain **`BLOCKED`**.

---

## 2. Canonical Truth & Architecture Verification

### 2.1 Proven AgentCore Serverless Architecture
The deployable StillDone MCP server reuses the historically verified AgentCore Runtime architecture from Phase P-05.06:
- **Base Container**: `Dockerfile` pinned to `linux/arm64` on Debian Bookworm (`python:3.13-slim-bookworm`).
- **User Security**: Non-root system execution via `USER stilldone`.
- **Target Port**: Container port `8000` (`EXPOSE 8000`).
- **Deployment Profile**: Explicit `--profile agentcore` flag enabling non-loopback `0.0.0.0:8000` binding while enforcing active SQLite rate limiting and health probes.
- **Data-Plane Protocol**: Server-Sent Events / Streamable HTTP transport at canonical `/mcp` path.
- **Ingress Security Boundary**: Inbound calls are protected at the AWS edge by IAM / SigV4 authentication (`bedrock-agentcore:InvokeAgentRuntime`). Unauthenticated public HTTP traffic cannot reach the container.

### 2.2 Wire Availability vs. Full Killer-Mission Behavior
A critical architectural invariant is enforced and verified:
- **MCP Exposed Tools**: The deployable MCP server registers exactly **2 tools**:
  1. `mission_start`: Initializes a mission in local `DRAFT` state within the runtime ledger.
  2. `mission_status`: Reads current mission state and timestamps from the runtime ledger.
- **Separation from Paid Inference & External Mutations**:
  - The MCP server exposes **ZERO** live Bedrock inference tools.
  - The MCP server exposes **ZERO** Google Calendar or Google Tasks mutation tools.
  - The live paid path remains fail-closed (`live_paid_path_enabled=False`).
  - Full killer-mission autonomous execution (`LiveKillerMissionSliceRunner` / `scripts/p13_killer_mission.py`) is decoupled from the public MCP endpoint.
- **Proof Distinction**: Standalone remote MCP wire availability (proved historically in `docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md`) is distinct from a full live desired-state mission completion (which was evaluated in deterministic regression mode in `docs/P13_KILLER_MISSION_AUDIT.md` with live cloud portions preserved as `BLOCKED_LIVE / NOT_RUN`).

### 2.3 Prevention of Unintended Additional Sessions
In historical P-05.06 execution, two distinct AgentCore runtime sessions / microVMs were exercised because `scripts/sigv4_proxy.py` initialized with `_active_session_id = None`, causing the first MCP Inspector request to spawn a new runtime session separate from earlier direct CLI calls.
- **Local Hardening Applied**:
  - `scripts/sigv4_proxy.py` updated to accept `--session-id <id>` and inspect `AGENT_RUNTIME_SESSION_ID` / `STILLDONE_AGENTCORE_SESSION_ID` environment variables.
  - On the very first incoming request, pre-seeded session IDs are passed directly to `aws bedrock-agentcore invoke-agent-runtime` via `--runtime-session-id` and `--mcp-session-id`.
  - Incoming `Mcp-Session-Id` headers persist and update active session state.
  - Validated by unit tests in `tests/test_sigv4_proxy.py` and `tests/test_phase_p19_03_remote_mcp_deployment.py`.

---

## 3. Read-Only AWS Account & Pricing Gate

### 3.1 Account Observation Status
- **AWS CLI in Local Environment**: `NOT_FOUND`
- **Active Credentials / ~/.aws**: `NONE`
- **Account Identity**: `NOT_OBSERVED`
- **Current Promotional Credit Balance**: `NOT_OBSERVED`
- **Applicable Products & Expiry**: Preserved from historical baseline (`$150.00` promotional credit, `2028-08-31` conservative expiry; `docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md`).
- **Current Incurred Charges**: `NOT_OBSERVED`
- **Retained Cloud Resources**: `NOT_OBSERVED`
- **Gate Verdict**: **`NOT_OBSERVED`** -> All cloud mutations halted fail-closed.

### 3.2 Official Rate-Based Conservative Cost-Risk Upper Bound
Using published AWS Bedrock AgentCore Runtime pricing for Platform V1 (`us-east-1`):
- Compute vCPU rate: **$0.0895** / vCPU-hour
- Compute Memory rate: **$0.00945** / GB-hour
- Hardware Allocation: **2 vCPU / 8 GB RAM** (non-adjustable microVM ceiling)
- Session Timeout: `idleRuntimeSessionTimeout = 60s`, `maxLifetime = 300s (5 minutes)`

#### Single-Session Ceiling:
$$\left(\frac{300}{3600}\right) \times \left[(2 \times 0.0895) + (8 \times 0.00945)\right] = \left(\frac{5}{60}\right) \times 0.2546 \approx \mathbf{\$0.021217\text{ USD}}$$

#### Two-Session Campaign Upper Bound (Compute + Ancillary Allowances):
- Two maximum 5-minute sessions: $2 \times \$0.021217 = \$0.042434\text{ USD}$
- CloudWatch telemetry allowance: $\$0.005000\text{ USD}$
- ECR / S3 storage & retrieval allowance: $\$0.000169\text{ USD}$
- **Gross Risk Upper Bound**: $\mathbf{\$0.047603\text{ USD}}$ (strictly below the operator's $\$0.05\text{ USD}$ threshold).

---

## 4. Judge-Period Availability & Hosting Constraints

### 4.1 November 9–20, 2026 Evaluation Constraints
As documented in `docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md`:
1. **No Real-Time Hard Kill Switch**: AWS Budgets alerts are asynchronous and promotional credits do NOT prevent billing continuation into pay-as-you-go if exhausted or expired.
2. **24/7 Hosting Prohibited**: Running an AgentCore runtime continuously for 12 days would consume 288 hours of microVM time ($\approx \$73.32\text{ USD}$), presenting an unacceptable risk of violating the **$0.00 Personal Spend Law**.
3. **Dual-Surface Architecture**:
   - **Public Read-Only Surface (Cloudflare Pages Free)**: Serves static interactive exhibit, historical evidence, video demo, and receipts at strictly **$0.00**.
   - **Authenticated Operator Runtime**: AgentCore MCP server deployed exclusively during bounded, supervised evaluation sessions with immediate teardown upon proof collection.

---

## 5. Operator GO / BLOCKED Decision Report

In compliance with Step 4 of the P-19.03 specification, the executor reports:

1. **Exact Deployment Architecture & Region**:
   - Serverless AgentCore microVM in `us-east-1`.
   - ARM64 container running `python -m stilldone --profile agentcore`.
   - SigV4 ingress authentication; local rate-limiting middleware (`10 req/min`, `$0.05` internal ceiling).
2. **Current Credits & Charges**:
   - `NOT_OBSERVED` (No AWS credentials configured on executor machine).
3. **Conservative Gross Cost-Risk Estimate & Lifecycle**:
   - Maximum lifetime: 300 seconds (5 minutes); idle timeout: 60 seconds.
   - Single-session compute ceiling: **$0.021217 USD**.
   - Two-session campaign gross risk: **$0.047603 USD** (strictly $< \$0.05\text{ USD}$).
4. **Protection of Zero Personal Spending**:
   - Software admission controls enforce rate limits and non-paid tool exposure, but **cannot guarantee $0.00 spend on AWS without active credit balance observation and operator teardown supervision**.
5. **Exact Cloud Resources Requiring Authorization**:
   - IAM Execution Role: `StillDoneAgentCoreExecutionRole`.
   - ECR Container Image: Tag `latest` or commit SHA.
   - Bedrock AgentCore Runtime: `stilldone_mcp_runtime`.
6. **Live Mission Behavior vs Limited MCP Tools**:
   - The deployable endpoint provides **strictly limited MCP tools** (`mission_start` and `mission_status` only). Full killer-mission live execution is not wired into the public MCP interface.
7. **Judge Accessibility Constraints**:
   - Public judging is served via static Cloudflare Pages exhibit and video. Continuous 24/7 live cloud hosting is financially impossible under $0.00 personal spend.
8. **Smallest Safe Deployment / Verification / Teardown Procedure**:
   - If authorized by operator: build ARM64 image -> push to ECR -> create runtime with 300s max lifetime -> execute single MCP verification with session reuse -> immediately delete runtime, ECR image, and IAM role.

### Verdict
**`BLOCKED / OPERATOR_DECISION_REQUIRED`**  
Execution is strictly stopped. No cloud mutations or paid service calls were executed.

---

## 6. Critical Evidence References Truth Audit

In compliance with Step 5 of the P-19.03 specification:
- The nonexistent reference `docs/P13_KILLER_MISSION_EVIDENCE.md` was detected in `docs/REPRODUCTION.md` and `scripts/reproduce.py`.
- **Correction Applied**:
  - `docs/REPRODUCTION.md` updated to reference `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md` (for `RECORDED_LIVE` AWS Bedrock evidence) and `docs/P13_KILLER_MISSION_AUDIT.md` (for the canonical killer-mission milestone audit evaluated in deterministic `FIXTURE` regression mode with live cloud portions preserved as `BLOCKED_LIVE / NOT_RUN`).
  - `scripts/reproduce.py` updated to reflect the exact same evidence truth.
- Zero other false evidence references exist in the repository.
