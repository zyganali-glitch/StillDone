# P-19.03 Remote MCP Deployment Preflight & Live-Feasibility Gate

**Document ID**: `docs/P19_03_REMOTE_MCP_DEPLOYMENT_PREFLIGHT.md`  
**Task**: `P-19.03 — Deploy final remote MCP/runtime path`  
**Task State**: `COMPLETED (Read-Only Preflight & Local Preparation; Live Cloud Mutations STOPPED)`  
**Operator Decision Outcome**: **`BLOCKED / OPERATOR_DECISION_RECORDED`**  
**Cloud Mutations Executed**: `NONE` (Zero AWS resources created, updated, or deleted; $0.00 personal spend maintained)  
**Governing Authority**: `AGENTS.md` § 1–24; Zero Personal Spend Law (§ 12); Live-First Law (§ 9); Evidence Provenance (§ 10); Desired-State Authority (§ 5)  

---

## 1. Executive Summary & Gate Status

This document establishes the verified local readiness, architecture, cost-risk boundaries, and account observation status for the remote Model Context Protocol (MCP) deployment on AWS Bedrock AgentCore Runtime in `us-east-1`.

### 1.1 Truthful Gate Status Taxonomy

- **LOCAL PREFLIGHT**: **`PERFORMED`** (Container packaging, `/mcp` Streamable HTTP contract, rate limiter, session reuse proxy, adversarial fail-closed boundaries fully verified).
- **OPERATOR AWS CONSOLE OBSERVATIONS**: **`DATED AND RECORDED (2026-10-14)`** (See dedicated observation record in [`docs/P19_03_OPERATOR_AWS_OBSERVATIONS_2026-10-14.md`](P19_03_OPERATOR_AWS_OBSERVATIONS_2026-10-14.md)).
- **ACTUAL REMOTE DEPLOYMENT**: **`BLOCKED / NOT_RUN`** (No container pushed to ECR, no AgentCore runtime provisioned, zero AWS API calls executed).
- **FULL LIVE KILLER MISSION**: **`BLOCKED_LIVE / NOT_RUN`** (Autonomous live multi-step execution across Bedrock + Google remains blocked; deterministic regression mode passes clean).
- **P-19.03 Overall**: **`NOT INDEPENDENTLY CLOSED AS DEPLOYED`** (Preflight and preparation completed; deployment execution gate remains intentionally blocked by operator instruction).
- **Independent QA Baseline**: The last independently QA-PASS SHA remains **`c54dde8579d6ac47ea536d7827b0921375bc6ac5`** pending independent QA review of this batch.

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

### 2.3 Fail-Closed Session Boundary & Proxy Hardening
In historical P-05.06 execution, two distinct AgentCore runtime sessions / microVMs were exercised because `scripts/sigv4_proxy.py` initialized with `_active_session_id = None`, causing the first MCP Inspector request to spawn a new runtime session separate from earlier direct CLI calls.
- **Fail-Closed Session Hardening**:
  - `scripts/sigv4_proxy.py` updated to accept `--session-id <id>` and inspect `AGENT_RUNTIME_SESSION_ID` / `STILLDONE_AGENTCORE_SESSION_ID` environment variables.
  - **Mismatched Client Rejection**: Inbound `Mcp-Session-Id` headers that mismatch an active bound proxy session are rejected fail-closed with HTTP 400 Bad Request, preventing arbitrary client overrides.
  - **Upstream Session Anomaly Protection**: If upstream AgentCore returns an unexpected session identity different from the active session, the proxy fails closed with HTTP 502 Bad Gateway and does not switch sessions or retry blindly.
  - **Log Sanitization & Privacy**: Raw query strings (e.g. `?token=...` or `?session_id=...`) are stripped from path logs; the server startup log reports `[session-bound]` without leaking the session ID string itself.
  - Validated by 14 focused tests in `tests/test_sigv4_proxy.py`.
  - **Note**: Local unit tests prove proxy parameter forwarding and session validation logic; they do not prove AWS cloud microVM reuse.

---

## 3. Read-Only AWS Account & Pricing Gate

### 3.1 Account Observation Status (Console Snapshot 2026-10-14)
As permanently recorded in [`docs/P19_03_OPERATOR_AWS_OBSERVATIONS_2026-10-14.md`](P19_03_OPERATOR_AWS_OBSERVATIONS_2026-10-14.md):
- **Executor Runtime**: Zero AWS credentials configured in the automated environment; automated live account API calls are `NOT_RUN`.
- **Operator Console Snapshot (2026-10-14)**:
  - 4 active credit grants ($285.66 estimated remaining credits, including $150.00 hackathon promotional credit expiring August 31, 2028).
  - Outstanding balance: TRY 0.00 ($0.00 personal spend maintained).
  - 0 active Bedrock AgentCore Runtimes.
  - 1 ECR repository (CDK bootstrap) containing 0 container images.
  - 1 CloudFormation stack (`CDKToolkit`, `UPDATE_COMPLETE`, 11 bootstrap resources).
- **Gate Verdict**: **`OBSERVED_BY_OPERATOR / STOPPED_FAIL_CLOSED`** -> All cloud mutations halted fail-closed.

### 3.2 Pricing Truth & Cost-Risk Boundaries

> [!IMPORTANT]
> **Pricing Verification & Cost-Ceiling Truth**:
> - **Scenario-Specific Calculation, NOT Total Campaign Guarantee**: The figure **$0.047603 USD** is a scenario-specific calculation for exactly two maximum 5-minute sessions with non-compute allowances. It is **NOT** a guaranteed upper bound for an entire competition campaign if additional microVMs are spawned or sessions linger.
> - **12-Day Evaluation Availability Truth**: Maintaining 12 days of judging availability (November 9–20, 2026) does **NOT** mean 12 days of continuously running compute. Running an AgentCore microVM continuously for 288 hours would consume ~$73.32 USD, exceeding single promotional grants and presenting intolerable financial risk. Availability is fulfilled via on-demand evaluation and static exhibits.
> - **No Software-Only Hard Stop**: Software admission controls enforce rate limits and non-paid tool exposure, but **no software-only hard stop can guarantee $0.00 personal expenditure** on AWS because AWS Budgets alerts are asynchronous and promotional credits do not prevent pay-as-you-go continuation.
> - **Historical vs. Current Rates**: Published pricing figures from Phase P-01 are historical snapshots and cannot establish current billing rates without fresh official verification.

#### Platform V1 Calculation Reference (`us-east-1`):
- Compute vCPU rate: **$0.0895** / vCPU-hour
- Compute Memory rate: **$0.00945** / GB-hour
- MicroVM Hardware Ceiling: **2 vCPU / 8 GB RAM**
- Max lifetime: 300 seconds (5 minutes); idle timeout: 60 seconds.
- Single 5-minute session ceiling: $\left(\frac{5}{60}\right) \times (2 \times 0.0895 + 8 \times 0.00945) \approx \mathbf{\$0.021217\text{ USD}}$.
- Two-session scenario ceiling + allowances: $\mathbf{\$0.047603\text{ USD}}$.

---

## 4. Judge-Period Availability & Hosting Constraints

### 4.1 Safe Dual-Surface Architecture
StillDone strictly decouples public evaluation from authenticated execution:
1. **Surface 1: Public Read-Only Judge Exhibit (Cloudflare Pages Free)**:
   - Serves static interactive exhibit, historical evidence, video demo, and receipts at strictly **$0.00**.
   - No Python backend execution, no live Bedrock calls, no Google mutations, no external credentials required.
2. **Surface 2: Authenticated Operator Runtime (AWS AgentCore)**:
   - Deployed exclusively during bounded, supervised evaluation sessions with immediate teardown upon proof collection.
   - Zero public unmetered endpoints.

---

## 5. Operator Decision Record

The operator has reviewed the preflight assessment and issued the following binding decisions:

1. **NO New Permanent AWS Access Keys**: Specifically, **NO root-user access keys** and no long-lived IAM user keys will be generated or stored. Any future cloud access, if authorized, must use existing AWS-supported short-lived browser-backed authentication (e.g. AWS IAM Identity Center or AWS CLI web login).
2. **NO AWS Deployment or API Calls**: Zero ECR pushes, zero AgentCore runtime deployments, and zero cloud API invocations will take place in this batch.
3. **NO Cloud Resource Deletion**: The existing `CDKToolkit` CloudFormation stack and constituent bootstrap resources are standard infrastructure and will NOT be deleted.
4. **NO Automatic Paid Fallback**: If credits or quotas are exhausted, execution must fail closed, never falling back to paid personal credit cards.
5. **Historical Evidence Preservation**: Historical AWS, MCP, Calendar, and Tasks evidence in `docs/` remains valid historical proof of technological implementation, but is not represented as a currently active live endpoint.
6. **Cloudflare Pages Exhibit Preparation**: Safe preparation of the static, read-only public exhibit is authorized under $0.00 personal spend. If actual public deployment requires operator account actions, instructions will be provided and marked `NOT_PUBLISHED / OPERATOR_ACTION_REQUIRED`.

### Verdict
**`BLOCKED / OPERATOR_DECISION_RECORDED`**  
Local preparation complete. Cloud deployment remains intentionally blocked.

---

## 6. Critical Evidence References Truth Audit

- The nonexistent reference `docs/P13_KILLER_MISSION_EVIDENCE.md` was detected in `docs/REPRODUCTION.md` and `scripts/reproduce.py`.
- **Correction Applied**:
  - `docs/REPRODUCTION.md` updated to reference `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md` (for `RECORDED_LIVE` AWS Bedrock evidence) and `docs/P13_KILLER_MISSION_AUDIT.md` (for the canonical killer-mission milestone audit evaluated in deterministic `FIXTURE` regression mode with live cloud portions preserved as `BLOCKED_LIVE / NOT_RUN`).
  - `scripts/reproduce.py` updated to reflect the exact same evidence truth.
- Zero other false evidence references exist in the repository.
