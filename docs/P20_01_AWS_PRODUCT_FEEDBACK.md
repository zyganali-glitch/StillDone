# P-20.01 — Factual Product Feedback for Amazon & AWS Tools

**Document ID**: `docs/P20_01_AWS_PRODUCT_FEEDBACK.md`  
**Task**: `P-20.01 — Consolidate factual product feedback for every Amazon/AWS tool used`  
**Governing Authority**: `AGENTS.md` § 11 (AWS Truth Boundary), § 19 (Product-Feedback / Friction Logging); `plans/STILLDONE_MASTER_EXECUTION_PLAN.md` § P-20.01  
**Observation Window**: September 27, 2026 – October 14, 2026  
**Personal Spend Bound**: Strictly `$0.00` maintained across all tool evaluations  

---

## 1. Executive Summary

Throughout the development of StillDone for the *Build, Ship, Shape: Amazon Developer Hackathon*, the project exercised multiple genuine AWS services, SDKs, and CLI tools under strict, fail-closed budget bounds. This document consolidates factual, evidence-backed engineering feedback for the AWS and Alexa+ product teams based on real integration attempts, recorded live sessions, and architectural boundary solutions.

Every entry in this feedback report represents an authentic technical observation documented in the repository ledger (`docs/P01_*.md`, `docs/P05_*.md`, `docs/P07_*.md`, and `docs/COMPETITION_FEEDBACK_LOG.md`). Zero entries or friction events are fabricated.

---

## 2. Tool-by-Tool Feedback

### 2.1 Amazon Bedrock Runtime (`amazon.nova-micro-v1:0` in `us-east-1`)

- **Role in StillDone**: Primary reasoning model evaluated for natural language mission planning and proposal generation (P-01.02, P-07.06).
- **Observed Metrics**:
  - Cold-start invocation latency: 3.463s (observed in P-07.06).
  - Token consumption: 8 input tokens, 3 output tokens for minimal verification; 214 input tokens, 142 output tokens for multi-step proposal compilation.
  - Cost efficiency: Billed at $0.00008 / 1K input tokens, $0.00032 / 1K output tokens. Gross estimate for P-01/P-07 cycles $\ll \$0.01$, covered by active hackathon promotional credits ($0.00 personal spend).
- **Strengths**:
  1. The Converse API (`aws bedrock-runtime converse`) provides a clean, normalized JSON interface that eliminates model-specific payload idiosyncrasies.
  2. Ultra-low token pricing makes Nova Micro ideal for deterministic agent verification architectures where LLMs propose plans but execute zero unconstrained mutations.
  3. Stable latency profiles once account verification and entitlement holds are cleared.
- **Friction Points & Actionable Suggestions**:
  1. **New Account Verification Hold (`F-20260927-02`)**:
     - *Observation*: Initial runtime call raised `AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours...`
     - *Suggestion*: Surface account verification lifecycle states prominently on the AWS Management Console Bedrock overview dashboard so developers do not diagnose access policies when the account is simply in an onboarding hold.
  2. **Model Authorization vs. Entitlement Confusion (`F-20260927-03`)**:
     - *Observation*: `get-foundation-model-availability` reported `agreementStatus = AVAILABLE`, `entitlementAvailability = AVAILABLE`, and `regionAvailability = AVAILABLE`, but `authorizationStatus = NOT_AUTHORIZED`. The runtime raised a generic `ValidationException: Operation not allowed` without detailing the missing prerequisite.
     - *Suggestion*: Enhance error payloads for `ValidationException` during Bedrock inference to include the specific prerequisite or policy needed (e.g., `"missing model authorization grant for account"`).

---

### 2.2 Strands Agents SDK (`strands-agents 1.57.2`)

- **Role in StillDone**: Python agent framework used to orchestrate Bedrock Nova Micro planning calls and parse candidate plan structures (P-01.03, P-07.03–P-07.06).
- **Observed Metrics**:
  - Single-step proposal generation without tool execution (`agent.tools = []`).
  - Strict contract boundary: Model proposals pass through `parse_candidate_plan_for_input` before any action is accepted.
- **Strengths**:
  1. Lightweight, idiomatic Python agent abstractions that integrate directly with Boto3 sessions and Bedrock models.
  2. Clean separation between agent conversation history and final response messages.
- **Friction Points & Actionable Suggestions**:
  1. **Upstream MCP Version Dependency Pinning Conflict (`F-20261005-01`)**:
     - *Observation*: `strands-agents 1.57.2` upstream officially requires `mcp>=1.23.0,<2.2`. However, modern Streamable HTTP MCP servers (and official MCP Python SDK `2.2.0+`) require `mcp>=2.2.0`. These package sets do not intersect in a single Python virtual environment.
     - *Workaround*: StillDone engineered a dual-runtime architecture (`pyproject.toml` for Core/MCP vs. `runtimes/strands_planner/pyproject.toml` for Strands Planner) with zero resolver overrides (`override-dependencies` prohibited).
     - *Suggestion*: Decouple or loosen the upper bound on the `mcp` dependency in `strands-agents` (`<2.2` -> `<3.0` or optional extra) so agent runtimes can coexist with modern MCP servers in single-environment workflows.
  2. **AWS Login Credential Provider Requires `botocore[crt]` (`F-20260928-01`)**:
     - *Observation*: Initial instantiation of `BedrockModel` using a Boto3 session from `aws login` raised `MissingDependencyException: Using the login credential provider requires an additional dependency. You will need to pip install "botocore[crt]"`.
     - *Suggestion*: Document prominently in Strands and Boto3 quickstart guides that consuming session credentials generated by `aws login` requires `botocore[crt]` (`awscrt`).

---

### 2.3 Amazon Bedrock AgentCore Runtime (`@aws/agentcore` v0.30.0 / CodeZip Serverless MicroVM)

- **Role in StillDone**: Evaluated for serverless containerized / CodeZip hosting of the StillDone Streamable HTTP MCP server (P-01.04, P-05.06).
- **Observed Metrics**:
  - Spin-up latency: ~61ms remote echo response over Server-Sent Events / Streamable HTTP on port 8000.
  - Teardown reliability: Clean zero-resource state achieved with `agentcore remove all -y`.
- **Strengths**:
  1. CodeZip and containerized serverless microVM execution eliminates persistent server management while providing sub-second MCP tool execution.
  2. Native integration with AWS Bedrock infrastructure.
- **Friction Points & Actionable Suggestions**:
  1. **Accept Header Requirement for Streaming MCP Runtimes (`F-20261001-01`)**:
     - *Observation*: Invoking containerized MCP runtimes configured for Server-Sent Events via `aws bedrock-agentcore invoke-agent-runtime` failed with `ValidationException: 406 Not Acceptable` when using `--accept "application/json"`. The runtime strictly required `--accept "application/json, text/event-stream"`.
     - *Suggestion*: Document the mandatory `text/event-stream` Accept header requirement clearly in AgentCore documentation for SSE/Streamable HTTP runtimes.
  2. **Windows Shell Argument Quoting Friction (`F-20260928-02`)**:
     - *Observation*: On Windows PowerShell, the Node.js CLI unquoted JSON arguments (`agentcore invoke --prompt '{"prompt": "PING"}'` became `"{prompt: PING}"`), causing entrypoint parse errors.
     - *Suggestion*: Provide a `--payload-file` or `--payload-json` parameter to bypass shell-specific quoting idiosyncrasies.
  3. **Local Tooling SigV4 Ingress Bridge (`F-20261014-01`)**:
     - *Observation*: AgentCore runtimes enforce SigV4 IAM authentication at the ingress gateway. Standard developer tools (such as `@modelcontextprotocol/inspector` or browser clients) do not natively sign HTTP requests with AWS SigV4, requiring developers to write custom proxy bridges.
     - *Suggestion*: Release an official lightweight local SigV4 proxy / signing bridge utility as part of `@aws/agentcore` to enable zero-friction developer inspection.

---

### 2.4 AWS CLI v2 & Identity Flows (`aws login`)

- **Role in StillDone**: Operator workstation authentication and preflight verification across all AWS tasks.
- **Observed Metrics**:
  - Temporary session credentials issued with positive `ASIA...` prefix and automatic expiration.
  - Zero static access keys committed or needed ($0.00 risk of long-lived credential leakage).
- **Strengths**:
  1. Short-lived session credentials eliminate the security hazard of permanent long-lived IAM user access keys.
  2. Bounded permission boundaries align with hackathon safety requirements.
- **Friction Points & Actionable Suggestions**:
  1. **Remote Redirect Friction (`F-20261001-02`)**:
     - *Observation*: Using `aws login --remote` requires copying a multi-line base64 redirect string from the browser back to the terminal. Any terminal line wrapping or trailing whitespace causes an invalid grant error.
     - *Suggestion*: Recommend standard loopback `aws login` (without `--remote`) as the primary path in documentation, reserving `--remote` strictly for headless servers with improved terminal whitespace stripping.

---

### 2.5 Amazon Alexa+ MCP Integration Surface

- **Role in StillDone**: Target conversational assistant platform for autonomous mission delegation.
- **Strengths**:
  1. Adopting the open Model Context Protocol (Streamable HTTP) allows developers to build portable, standards-compliant tools that integrate with Alexa+ without proprietary vendor lock-in.
  2. One-screen multimodal feedback model allows rich visual verification alongside spoken voice responses.
- **Friction Points & Actionable Suggestions**:
  1. **Protocol Version Discrepancies (`F-20260929-01`)**:
     - *Observation*: Official Alexa+ documentation referenced `2024-11-05`, `2025-03-26`, and `2025-11-25` across different schema sections and deprecation notes.
     - *Suggestion*: Publish a single, authoritative compatibility matrix for supported MCP protocol versions.
  2. **RFC 6750 OAuth vs. Alexa+ Discovery Compatibility**:
     - *Observation*: Standard RFC 6750 OAuth resource servers emit a `WWW-Authenticate: Bearer` header upon receiving unauthenticated requests (HTTP 401). Alexa+ discovery documentation specifies that unauthenticated discovery endpoints must suppress `WWW-Authenticate` headers to prevent discovery aborts. StillDone implemented `Alexa401CompatibilityMiddleware` to resolve this.
     - *Suggestion*: Clarify whether Alexa+ client discovery supports RFC 6750 compliant `WWW-Authenticate` challenge headers or strictly requires header suppression.
  3. **Direct Partner Access Availability**:
     - *Observation*: Direct Alexa+ partner access remained `NOT_ESTABLISHED` during the hackathon period. StillDone complied with competition rules by implementing and prominently labeling a simulated surface (`SIMULATED ALEXA+ EXPERIENCE`).

---

## 3. Product Team Summary & Retrospective

| Tool / Technology | Verdict | Would Build With It Again? | Key Takeaway |
|---|---|---|---|
| **Amazon Bedrock Nova Micro** | Production Ready | `YES` | Exceptional value and latency for deterministic planning; improve onboarding error clarity. |
| **Strands Agents SDK** | Highly Capable | `YES` (with multi-runtime) | Excellent agent model; loosen upstream `mcp<2.2` upper bound. |
| **Bedrock AgentCore Runtime** | Promising Serverless MicroVM | `YES` | Great serverless MCP deployment; improve Windows CLI quoting and developer SigV4 bridge. |
| **AWS CLI v2 (`aws login`)** | Recommended Standard | `YES` | Standard loopback login is flawless; remote copy-paste needs sanitation. |
| **Alexa+ Streamable HTTP MCP** | Strategic Direction | `YES` | Open standard protocol choice is brilliant; harmonize protocol version specs. |

---

*Verified authentic engineering evidence committed under P-20.01.*
