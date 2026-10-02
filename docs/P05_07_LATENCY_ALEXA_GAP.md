# P-05.07 MCP Protocol Latency & Alexa+ Direct-Access Compatibility Gap

**Task**: `P-05.07 — Measure protocol latency and document Alexa+ direct-access compatibility gap`  
**Observation Date**: `2026-10-02`  
**Measured Source SHA**: `8ad1ec7a91a78ba593da7aa8c364bf4dd9b5c458`  
**Governing Authority**: [AGENTS.md](../AGENTS.md) § 1–24; [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md); [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Evidence Provenance**: `LOCAL_EXECUTION` (local measurement) + `RECORDED_LIVE` (historical P-01.07 & P-05.06 evidence)  

---

## 1. Executive Summary

This document establishes two empirical and technical truths for StillDone:

1. **Deterministic Local MCP Protocol Latency**: Measured under pure local loopback execution over real Streamable HTTP transport using the official MCP Python client (`mcp==2.2.0`), loopback Uvicorn/Starlette server, and canonical pre-populated `InMemoryNonDurableLedger`. 
2. **Alexa+ Direct-Access Compatibility Gap Matrix**: An exhaustive, factual evaluation of current Amazon Alexa+ MCP platform requirements against StillDone's verified capabilities and AWS Bedrock AgentCore Runtime ingress characteristics.

### Critical Provenance Boundaries
In accordance with StillDone Constitution (`AGENTS.md` § 3, § 9, § 10):
- **CURRENT LOCAL MEASUREMENT**: Loopback performance over `127.0.0.1` (`LOCAL_EXECUTION`). Proves local latency headroom; does **not** certify remote production latency.
- **RECORDED LIVE REMOTE EVIDENCE**:
  - P-01.07 ephemeral Cloudflare tunnel probe (`61.26ms` tool round-trip).
  - P-05.06 real AWS AgentCore Runtime deployment in `us-east-1` (real `initialize`, `tools/list`, `mission_start`, and read-back `mission_status`).
- **CURRENT REMOTE ENDPOINT**: `NONE` (remote runtime was torn down immediately after P-05.06 proof capture; zero persistent cloud resources exist).
- **CURRENT AGENTCORE MCP LATENCY**: `NOT_MEASURED` (P-05.06 validated wire protocol correctness and rate limiting, but did not meter canonical request round-trip latency).

---

## 2. Deterministic Local Protocol Latency Measurement

### 2.1 Measurement Environment & Parameters
- **Utility**: `scripts/measure_mcp_latency.py`
- **Source SHA**: `8ad1ec7a91a78ba593da7aa8c364bf4dd9b5c458`
- **Timestamp (UTC)**: `2026-10-02T06:20:29.938125+00:00`
- **Host Platform**: Windows 10 (AMD64)
- **Runtimes**: Python `3.13.14`, MCP Python SDK `2.2.0`, `mcp-types==2.2.0`
- **Server Binding**: Loopback `127.0.0.1` on ephemeral port (`MCPServerConfig(path="/mcp")`)
- **Transport**: Real Streamable HTTP over Uvicorn / Starlette
- **Clock**: `time.perf_counter_ns()` (monotonic high-resolution clock; resolution < 1µs)
- **Ledger State**: Pre-populated canonical `MissionRecord` (`MissionState.DRAFT`); setup duration strictly excluded from latency.
- **Campaign Structure**: 5 warm-up requests + 30 measured requests per operation.
- **Fail-Closed Policy**: Any transport or tool error raises `LatencyMeasurementError` and aborts; failures are never recorded as successes.

### 2.2 Raw Summary Metrics Table

| Operation | Provenance | Samples | Min (ms) | Mean (ms) | Median / p50 (ms) | p95 (ms) | Max (ms) |
|---|---|---|---|---|---|---|---|
| **`initialize`** | `LOCAL_EXECUTION` | 30 | 5.18 | 7.02 | **7.34** | **8.62** | 9.18 |
| **`tools/list`** | `LOCAL_EXECUTION` | 30 | 5.30 | 6.65 | **6.12** | **8.73** | 9.16 |
| **`mission_status`** | `LOCAL_EXECUTION` | 30 | 5.51 | 7.11 | **6.93** | **8.60** | 12.11 |

### 2.3 Contextual Latency Comparison

| Reference / Observation | Provenance | Latency (ms) | Target / Threshold | Classification |
|---|---|---|---|---|
| **Local Protocol p50** | `LOCAL_EXECUTION` | 6.12 – 7.34 ms | < 500 ms | `LOCAL_LATENCY_HEADROOM_OBSERVED` |
| **Local Protocol p95** | `LOCAL_EXECUTION` | 8.60 – 8.73 ms | < 500 ms | `LOCAL_LATENCY_HEADROOM_OBSERVED` |
| **Historical Remote Echo (P-01.07)** | `RECORDED_LIVE` | 61.26 ms | < 500 ms | `RECORDED_LIVE` |
| **Deployed AWS AgentCore Latency** | `LIVE_AWS` | `NOT_MEASURED` | < 500 ms | `NOT_MEASURED` |
| **Alexa+ Production Certification** | N/A | N/A | < 500 ms | `NOT_ESTABLISHED` |

### 2.4 Explicit Non-Certification Statement

> [!WARNING]
> **Performance Non-Certification Notice**:
> Loopback measurement demonstrates local protocol latency headroom under Streamable HTTP (< 500ms target). In accordance with `AGENTS.md` § 3, § 9, and § 10, local loopback measurement cannot establish remote production latency, and does **NOT** certify Alexa+ production performance. Current AgentCore deployed latency is `NOT_MEASURED`, and historical remote echo (61.26ms) is `RECORDED_LIVE` only.

---

## 3. Official Platform Requirements Re-Check

**Observation Date**: `2026-10-02`  
**Inspected Official Sources**:
- Alexa+ MCP QuickStart: `https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html`
- Alexa+ MCP Authentication: `https://developer.amazon.com/docs/alexaplus/add-ons/mcp-authentication.html`
- Alexa+ MCP Client/App Lifecycle: `https://developer.amazon.com/docs/alexaplus/add-ons/mcp-server-client-app-lifecycle.html`
- AWS Bedrock AgentCore Runtime Documentation (Inbound Auth & Ingress)
- Model Context Protocol (MCP) Specification (Streamable HTTP 2025-11-25)

### Summary of Established Platform Requirements:
- **Transport**: Streamable HTTP mandatory (legacy HTTP+SSE deprecated).
- **Reachability**: Remotely reachable public HTTPS URL.
- **Responsiveness**: Round-trip query-response latency < 500 ms.
- **Token Delivery**: RFC 6750 Bearer tokens via `Authorization: Bearer <token>` header; query string tokens forbidden.
- **401 Discovery Semantics**: Initial unauthenticated request must return **HTTP 401 Unauthorized WITHOUT a `WWW-Authenticate` header**.
- **Metadata**: RFC 9728 Protected Resource Metadata (PRM) at `/.well-known/oauth-protected-resource/mcp`.
- **Scope & Parameters**: RFC 8707 `resource` parameter; scope `mcp:service` for service-level operations.
- **User Authentication**: PKCE S256 with `authorization_code` grant for user-specific tools.
- **Explicit Unsupported Features**: Dynamic Client Registration (DCR), OpenID Connect (OIDC) on the MCP path, Step-Up authorization.

---

## 4. Alexa+ Direct-Access Compatibility Gap Matrix

| Requirement Dimension | Alexa+ Specification | StillDone Verified Reality | Current Ingress / Architecture Truth | Status |
|---|---|---|---|---|
| **A. Transport** | Streamable HTTP mandatory | Implemented in `src/stilldone/mcp/` using official MCP SDK. | Proven over loopback and proven deployed on AWS AgentCore (P-05.06). | **PROVEN** |
| **B. Remote HTTPS MCP** | Remotely reachable HTTPS URL | Deployed and validated on AWS AgentCore in `us-east-1` (P-05.06). | Runtime torn down immediately post-proof. Current live endpoint: `NONE`. | **PROVEN HISTORICALLY / RECORDED_LIVE** |
| **C. Tool Discovery** | Standard MCP `tools/list` | Exposes `mission_status` and `mission_start`. | Discovered by official client and MCP Inspector 2.9.0 remotely. | **PROVEN** |
| **D. Remote Tool Execution** | Stateful tool invocation & read-back | `mission_start` $\to$ `DRAFT`, `mission_status` $\to$ same `DRAFT`. | Proven within live AgentCore session (P-05.06). | **PROVEN** |
| **E. Latency** | < 500 ms round-trip | Local p50 = 6.12–7.34 ms; Historical remote echo = 61.26 ms (`RECORDED_LIVE`). | Current AgentCore latency is `NOT_MEASURED`. Direct production certification is unproven. | **NOT_ESTABLISHED** |
| **F. Service-Level Auth (Tier 1)** | OAuth 2.0 `client_credentials` with scope `mcp:service` | StillDone RS accepts Bearer tokens with validated scopes (P-05.05). | AWS AgentCore ingress requires AWS SigV4 IAM signing, not Alexa+ OAuth `client_credentials`. | **INCOMPATIBLE AS DIRECT ALEXA+ AUTH PATH** |
| **G. User-Level Auth (Tier 2)** | OAuth 2.0 `authorization_code` + PKCE S256 | Local RS token verification proven (P-05.05). | No external production authorization server or account linking deployed. | **NOT_ESTABLISHED** |
| **H. 401 Discovery Semantics** | HTTP 401 **WITHOUT** `WWW-Authenticate` header | Implemented locally via `Alexa401CompatibilityMiddleware`. | AWS AgentCore OAuth ingress emits `WWW-Authenticate` on 401; IAM ingress returns SigV4 403. | **INCOMPATIBLE WITH CURRENT AGENTCORE INGRESS** |
| **I. RFC 9728 PRM** | Published at `/.well-known/oauth-protected-resource/mcp` | Implemented and proven locally in P-05.05. | Not exposed through a public hosted domain. | **NOT_ESTABLISHED** |
| **J. Auth Server Metadata** | RFC 8414 metadata endpoint | StillDone is strictly a Resource Server. | External Authorization Server is `NOT_ESTABLISHED`. | **NOT_ESTABLISHED** |
| **K. DCR / OIDC / Step-Up** | Explicitly unsupported by Alexa+ | Zero implementation; StillDone respects boundaries. | Unsupported features avoided. | **NOT_IMPLEMENTED (COMPLIANT)** |
| **L. Partner / Add-On Access** | Private partner program access | No invite / partner agreement available. | Hackathon participants lack direct Alexa+ deployment hooks. | **NOT_ESTABLISHED / NOT_RUN** |

---

## 5. Protocol Version Truth Analysis

Discrepancies in MCP protocol versions across Amazon and ecosystem resources were analyzed:

1. **Current Local Official Python Client**: Negotiates protocol version **`2025-11-25`** (the current official standard for Streamable HTTP).
2. **Recorded P-05.06 AgentCore Deployment**: Handshake request and response successfully completed using protocol version **`2024-11-05`**.
3. **Current Alexa+ Documentation Examples**: Documentation displays sample payloads referencing **`2024-11-05`** in schema snippets and **`2025-03-26`** in lifecycle examples, while deprecation notices reference **`2025-11-25`**.

### Findings:
- Current official Amazon Alexa+ documentation does **not** declare any single protocol version as a hard mandatory rejection criterion.
- MCP SDK clients and servers negotiate protocol versions dynamically during `initialize`.
- **Verdict**:
  $$\mathbf{PROTOCOL\_VERSION\_BLOCKER = NOT\_ESTABLISHED}$$
  Protocol version differences between documentation examples and runtime negotiation do not constitute an active compatibility blocker.

---

## 6. Deterministic Compatibility Verdict

$$\mathbf{ALEXA\_PLUS\_DIRECT\_ACCESS\_COMPATIBILITY = INCOMPATIBLE\_WITH\_CURRENT\_AGENTCORE\_INGRESS}$$

### Supporting Sub-Facts:
1. **Product MCP Server Integrity**: StillDone's core MCP server natively supports Streamable HTTP, canonical tools (`mission_start`, `mission_status`), RFC 9728 PRM, and Alexa-compatible 401 header suppression.
2. **AWS AgentCore Deployment Proven**: Containerized deployment, remote Streamable HTTP invocation, session affinity, and deployed rate limiting were proven on real AWS AgentCore in P-05.06.
3. **IAM Ingress Incompatibility**: The deployed AgentCore runtime was protected by AWS IAM / SigV4. Alexa+ does not sign requests using AWS SigV4; it requires standard OAuth 2.0 `client_credentials` with scope `mcp:service`.
4. **OAuth 401 Header Conflict**: When AWS Bedrock AgentCore Runtime is configured with native JWT/OAuth inbound authentication, the AWS platform automatically emits a `WWW-Authenticate: Bearer ...` header upon unauthenticated 401 responses. This directly conflicts with Alexa+'s explicit requirement for 401 responses without `WWW-Authenticate`.
5. **Authorization Server Absence**: An external two-tier RFC 8414 Authorization Server was not deployed, and direct Alexa+ partner portal registration is `NOT_ESTABLISHED`.
6. **Integrity Rule**: This compatibility gap is an objective integration fact of the current AWS AgentCore ingress surface, not a product defect in StillDone.

---

## 7. Future Architecture Options (Documented Only — Not Implemented)

To bridge the compatibility gap between AgentCore and Alexa+ in future phases, the following architecture options exist:

- **Option A (Dedicated Edge / Custom Reverse Proxy)**:
  Deploy an edge proxy (e.g. Cloudflare Worker or AWS API Gateway HTTP API) in front of the application that terminates OAuth 2.0, manages RFC 9728 PRM, strips `WWW-Authenticate` from 401 responses, and forwards requests to StillDone.
- **Option B (AWS Ingress Adapter)**:
  Configure an AWS Lambda function or CloudFront response headers policy to intercept AgentCore's 401 response and remove `WWW-Authenticate` before returning to the caller.
- **Option C (Simulated Alexa+ Client with Real AWS Backend)**:
  Provide a simulated Alexa+ client experience for the hackathon submission while preserving real AWS AgentCore execution evidence for backend verification. This satisfies the competition requirements without risking production authentication drift.

> [!IMPORTANT]
> **Strict Execution Boundary**: In accordance with P-05.07 constraints, **NONE** of these future architecture options are implemented in P-05.07. Zero Lambda functions, API Gateways, CloudFront distributions, or Cognito pools were created.

---

## 8. Competition Truth & Submission Contract

To protect technical integrity during hackathon judging:

- **Permitted Submission Claim**:
  > *"StillDone's MCP backend was validated on real AWS AgentCore over Streamable HTTP. Alexa+ direct partner authentication remains a documented platform compatibility gap; the demo client surface is simulated if direct partner access is unavailable."*
- **Forbidden False Claim**:
  > *"StillDone is integrated with Alexa+"* (Forbidden unless end-to-end partner onboarding and live execution are proven).
- Real AWS AgentCore backend evidence (`RECORDED_LIVE`) and simulated Alexa+ client surfaces must remain explicitly and separately labeled throughout all submission artifacts and video demonstrations.
