# P-01.07 Live Remote MCP Streamable HTTP Feasibility Evidence

Observation date: `2026-09-29`
Exact task: `P-01.07 — Validate MCP/Alexa+ current protocol requirements and build a minimal remote Streamable HTTP echo/health proof`
Provenance: `LIVE_REMOTE_MCP`
Client provenance: `REAL_MCP_SDK_CLIENT`
Alexa+ client integration: `NOT_RUN`
Alexa+ partner access: `NOT_ESTABLISHED`

---

## 1. Executive Summary

This document durably records the execution and findings of micro-task **P-01.07**. 

In accordance with Master Plan P-01.07 and the StillDone Constitution (`AGENTS.md`):
1. **Official Protocol & Ecosystem Validation**: Current official technical documentation from Amazon Alexa+, the Model Context Protocol (MCP) specification, and Cloudflare was examined as of `2026-09-29`. Current requirements for Streamable HTTP, remote HTTPS, latency budgets (<500ms), and OAuth 2.1 authentication were recorded. Protocol version discrepancies across Amazon documentation were cataloged without silent reconciliation.
2. **Minimal Ephemeral MCP Server**: An isolated ephemeral MCP server was constructed strictly outside the canonical StillDone repository using the current official TypeScript MCP SDK (`@modelcontextprotocol/sdk` v1.31.0). The server exposed a single diagnostic transport-only `echo` tool (`{"text": "MCP_OK"}` $\to$ `MCP_OK`) reachable via Streamable HTTP at `/mcp` in stateless direct-JSON mode (`enableJsonResponse: true`), and an independent `/health` diagnostic endpoint (`{"status": "ok"}`). Zero StillDone dependencies, source files, or tests were modified.
3. **Ephemeral Remote HTTPS Tunnel**: A development-only Cloudflare Quick Tunnel (`cloudflared` v2026.9.3) was launched with strictly zero Cloudflare account, zero domain purchase, zero payment, and zero persistent resources, yielding a temporary public hostname on `trycloudflare.com`.
4. **Single Bounded Remote Protocol Proof**: An official MCP SDK client (`Client` and `StreamableHTTPClientTransport`) connected over the public HTTPS tunnel URL (`https://omissions-lessons-nutritional-warren.trycloudflare.com/mcp`). Exactly one protocol sequence was executed:
   - Connect and protocol negotiation: succeeded in **339.91ms**; negotiated protocol version `2025-11-25`.
   - Initialization and discovery: server identified as `{ name: "stilldone-diagnostic-mcp-server", version: "1.0.0" }`.
   - Tool discovery (`tools/list`): completed in **106.77ms**; discovered exactly 1 diagnostic tool (`echo`).
   - Tool invocation (`tools/call`): exactly 1 invocation of `echo({"text": "MCP_OK"})` executed; returned exact semantic result `MCP_OK` in **61.26ms**.
   - Client closed cleanly. Zero retries, zero product tools, zero fallback transports, zero external service calls.
5. **Latency Evaluation**: The single observed echo round-trip latency of `61.26ms` satisfies the Alexa+ `<500ms` responsiveness guideline (`ALEXA_PLUS_LATENCY_REQUIREMENT = OBSERVED_PASS_FOR_THIS_PROBE`).
6. **Mandatory Teardown**: The client was closed, Cloudflare tunnel terminated, local server terminated, and all scratch artifacts completely deleted.

---

## 2. Official Current Protocol Reality

### 2.1 Amazon Alexa+ MCP Integration Requirements

Inspected official Amazon Developer resources (`2026-09-29`):
- Alexa+ MCP QuickStart Guide: `https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html`
- Alexa+ Developer Overview: `https://developer.amazon.com/docs/alexaplus/add-ons/home.html`
- Alexa+ Integration Approaches: `https://developer.amazon.com/docs/alexaplus/add-ons/choose-the-proper-alexaplus-integration-approach.html`
- Alexa+ Lifecycle & Authentication: `https://developer.amazon.com/docs/alexaplus/add-ons/mcp-server-client-app-lifecycle.html`, `https://developer.amazon.com/docs/alexaplus/add-ons/mcp-authentication.html`
- Hackathon Rules & Devpost: `https://amazonappdev2026.devpost.com/resources`, `https://amazonappdev2026.devpost.com/rules`

Durably established Alexa+ technical requirements:
- **Streamable HTTP Mandatory**: Legacy HTTP+SSE (Server-Sent Events) is deprecated for Alexa+ integration. Alexa+ requires MCP servers to support Streamable HTTP.
- **Remote HTTPS URL Mandatory**: Servers must be reachable via a public, valid remote HTTPS URL.
- **Latency Guideline**: Alexa+ voice/conversational interaction targets an initial response threshold of **< 500ms** to avoid noticeable dialogue latency.
- **Access Boundary**: Category SDK and Alexa+ MCP Add-on registration are currently limited to select partners. Direct Alexa+ partner access remains **`NOT_ESTABLISHED`** for StillDone unless independently proven.
- **Authentication Architecture (Production)**:
  - Protocol: OAuth 2.1 authorization code grant with Proof Key for Code Exchange (PKCE) using the `S256` code challenge method.
  - Metadata Discovery: Protected Resource Metadata (PRM) endpoint per RFC 9728 (`/.well-known/oauth-protected-resource`), and Authorization Server Metadata per RFC 8414 (`/.well-known/oauth-authorization-server`).
  - Scoping: `resource` parameter per RFC 8707.
  - Access Tokens: Bearer token usage per RFC 6750.
  - Deprecated / Unsupported: Legacy OAuth 2.0 Implicit Grant, Resource Owner Password Credentials Grant, and static unauthenticated production endpoints are disallowed for customer data.

### 2.2 Protocol Version Documentation Discrepancy

Current Amazon documentation exhibits different MCP protocol versions across different documents:
- Schema reference examples cite `2024-11-05` (the initial public MCP baseline).
- Alexa+ `initialize` request/response payload examples cite `2025-03-26`.
- Deprecation notes for HTTP+SSE transport cite specification updates from `2025-11-25`.

**StillDone Law**: This discrepancy is explicitly recorded as observed without silent reconciliation. The server implementation was not hard-coded to an obsolete sample version; instead, official SDK protocol-version negotiation was utilized.

### 2.3 Model Context Protocol (MCP) Specification Reality

Inspected official Model Context Protocol resources (`2026-09-29`):
- Specification: `https://spec.modelcontextprotocol.io/` / `https://modelcontextprotocol.io/`
- TypeScript SDK Repository: `https://github.com/modelcontextprotocol/typescript-sdk`

Established MCP facts:
- **Specification Supported Versions**: Official SDK defines `LATEST_PROTOCOL_VERSION = "2025-11-25"` and `SUPPORTED_PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07"]`.
- **Streamable HTTP Architecture**:
  - Unified endpoint: Uses a single HTTP URL for communication (unlike legacy dual-endpoint SSE).
  - Messaging format: Standard JSON-RPC 2.0.
  - Response modes: Supports both Server-Sent Events (SSE) streaming and direct JSON responses (`application/json`).
  - Metadata headers: Requests mirror protocol version and session metadata in HTTP headers (`mcp-session-id`, `mcp-protocol-version`).
- **Negotiation Behavior**: The client sends its preferred protocol version during the `initialize` request. The server responds with its negotiated protocol version. If both parties support the version, that version governs the session.

---

## 3. Ephemeral Server Architecture & Transport Mode

### 3.1 Implementation Environment

- **Location**: Scratch directory completely outside the StillDone git repository (`%appDataDir%\brain\<conversation-id>\scratch\mcp_proof`).
- **Runtime**: Node.js `v24.13.1` (npm `11.8.0`) on Windows AMD64.
- **Packages Used**:
  - `@modelcontextprotocol/sdk`: `1.31.0` (official TypeScript MCP SDK)
  - `express`: `5.2.1`
  - `zod`: `4.6.5`
- **Zero Repo Changes**: `pyproject.toml`, `uv.lock`, `src/`, and `tests/` in StillDone were completely untouched.

### 3.2 Transport and SSE Truth

- **Endpoint**: Local HTTP server listening at `127.0.0.1:3456`, path `/mcp`.
- **Mode**: Stateless (`sessionIdGenerator: undefined`) with direct JSON responses (`enableJsonResponse: true`).
- **Direct JSON vs. SSE Truth**:
  - Cloudflare Quick Tunnels (`trycloudflare.com`) do not support long-lived HTTP Server-Sent Events (SSE) streams due to proxy buffering and disconnect policies.
  - The MCP server was therefore intentionally configured with `enableJsonResponse: true` to return valid direct JSON-RPC responses over Streamable HTTP.
  - **SSE was NOT claimed proven.** Direct JSON mode over Streamable HTTP was exercised and proven.

### 3.3 Diagnostic Tool Boundary

Strictly one diagnostic tool was exposed:
- **Name**: `echo`
- **Description**: `Diagnostic transport-only echo. Not a StillDone product tool.`
- **Input Schema**: `{"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}`
- **Behavior**: Returns `{ content: [{ type: "text", text: input.text }] }`.
- **Enforced Boundaries**: Strictly zero filesystem access, zero shell commands, zero AWS calls, zero Bedrock models, zero Google Calendar/Tasks calls, zero Open-Meteo calls, and zero external state writes.

An independent non-MCP health endpoint was also exposed at `GET /health` returning `{"status": "ok"}` to verify raw tunnel connectivity. In accordance with task rules, `/health` is not counted as MCP proof.

---

## 4. Remote HTTPS Development Tunnel

### 4.1 Tunnel Configuration & Attributes

- **Provider**: Cloudflare Quick Tunnel (`cloudflared` v2026.9.3, built `2026-09-24T08:31 UTC`).
- **Mechanism**: `cloudflared tunnel --url http://127.0.0.1:3456`.
- **Tunnel Class**: `EPHEMERAL_DEVELOPMENT_QUICK_TUNNEL`.
- **Account Required**: `NO` (zero Cloudflare account created or authenticated).
- **Domain Purchase**: `NO`.
- **Paid Plan**: `NO` ($0.00 personal spend).
- **Persistent Resource**: `NO` (no DNS records, no named tunnels, no credentials files).
- **Production Suitability**: `NOT_PROVEN / NOT_INTENDED` (explicitly development-only).
- **Assigned Hostname**: `https://omissions-lessons-nutritional-warren.trycloudflare.com`.

### 4.2 Raw HTTPS Connectivity Verification

Prior to running the MCP client, raw HTTPS reachability was confirmed via curl:
```bash
curl.exe --ssl-no-revoke -s https://omissions-lessons-nutritional-warren.trycloudflare.com/health
```
Output:
```json
{"status":"ok"}
```
Exit code: `0`.

---

## 5. Live Remote MCP Protocol Proof Execution

### 5.1 Client Configuration & Method

- **Client Classification**: `REAL_MCP_SDK_CLIENT` (using official `@modelcontextprotocol/sdk/client` `Client` and `StreamableHTTPClientTransport`).
- **Client Identity**: `{ name: "stilldone-diagnostic-mcp-client", version: "1.0.0" }`.
- **Client Provenance**: This is an automated SDK client, **NOT** Alexa+ and **NOT** a simulated Alexa+ surface.
- **Target URL**: `https://omissions-lessons-nutritional-warren.trycloudflare.com/mcp`.

### 5.2 Single Bounded Protocol Sequence

The client executed exactly one bounded protocol sequence:
1. **Connect & Protocol Negotiation**:
   - Sent `initialize` request over public HTTPS Streamable HTTP.
   - Negotiated Protocol Version: `2025-11-25`.
   - Server Identification: `{ name: "stilldone-diagnostic-mcp-server", version: "1.0.0" }`.
   - Server Capabilities: `{ tools: { listChanged: true } }`.
   - Connect Elapsed Time: **339.91ms**.
2. **Tool Discovery (`tools/list`)**:
   - Requested available tools list.
   - Tools Count: 1.
   - Tool Name: `echo`.
   - Description: `Diagnostic transport-only echo. Not a StillDone product tool.`.
   - Tools List Elapsed Time: **106.77ms**.
3. **Diagnostic Tool Call (`tools/call`)**:
   - Executed single call: `echo({"text": "MCP_OK"})`.
   - Returned Semantic Result: `MCP_OK`.
   - Content: `[ { "type": "text", "text": "MCP_OK" } ]`.
   - Echo Round-Trip Latency: **61.26ms**.
4. **Client Termination**:
   - Transport closed cleanly.

### 5.3 Complete Structured Evidence Payload

```json
{
  "remoteUrl": "https://omissions-lessons-nutritional-warren.trycloudflare.com/mcp",
  "transport": "Streamable HTTP",
  "clientClassification": "REAL_MCP_SDK_CLIENT",
  "connectionElapsedMs": 339.91,
  "negotiatedProtocolVersion": "2025-11-25",
  "serverVersion": {
    "name": "stilldone-diagnostic-mcp-server",
    "version": "1.0.0"
  },
  "serverCapabilities": {
    "tools": {
      "listChanged": true
    }
  },
  "toolsListElapsedMs": 106.77,
  "toolsCount": 1,
  "tools": [
    {
      "name": "echo",
      "description": "Diagnostic transport-only echo. Not a StillDone product tool.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "text": {
            "type": "string",
            "description": "Diagnostic text"
          }
        },
        "required": [
          "text"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#"
      },
      "execution": {
        "taskSupport": "forbidden"
      }
    }
  ],
  "echoInput": {
    "text": "MCP_OK"
  },
  "echoResult": {
    "content": [
      {
        "type": "text",
        "text": "MCP_OK"
      }
    ]
  },
  "echoSemanticResult": "MCP_OK",
  "echoRoundTripMs": 61.26,
  "alexaPlusLatencyPass": true,
  "alexaPlusLatencyRequirement": "OBSERVED_PASS_FOR_THIS_PROBE",
  "productToolsCount": 0,
  "retriesCount": 0,
  "externalApiCallsCount": 0
}
```

### 5.4 Probe Latency & Alexa+ Performance Requirement

- **Connection & Protocol Negotiation**: `339.91ms`.
- **`tools/list` Round-Trip**: `106.77ms`.
- **`echo` Tool Call Round-Trip**: `61.26ms`.
- **Evaluation**: The observed round-trip latency of `61.26ms` is well within the `< 500ms` Alexa+ threshold.
- **Classification**: `ALEXA_PLUS_LATENCY_REQUIREMENT = OBSERVED_PASS_FOR_THIS_PROBE`.
- **Integrity Note**: Exactly one probe was performed. No reruns were executed to hunt for better latency numbers.

---

## 6. Access and Authentication Boundaries

| Dimension | Classification | Factual Status |
|---|---|---|
| **MCP Transport Interoperability** | `PROVEN` | Full Streamable HTTP JSON-RPC negotiation, tools/list, and echo call succeeded over remote HTTPS |
| **Remote HTTPS Reachability** | `PROVEN` | Reached via public `trycloudflare.com` tunnel |
| **Alexa+ Actual Client Integration** | `NOT_RUN` | Direct Alexa+ partner access is unavailable; real SDK client was used and honestly labeled |
| **Alexa+ Production Authentication** | `NOT_IMPLEMENTED / REQUIREMENT_RECORDED` | Full OAuth 2.1 / PKCE stack not implemented in minimal feasibility proof; requirements cataloged |
| **Alexa+ Partner / Add-On Access** | `NOT_ESTABLISHED` | Official registration remains restricted to partner channels |

---

## 7. Teardown and Cleanup Verification

Immediately following the single protocol probe:
1. **MCP Client**: Closed cleanly via `client.close()`.
2. **Cloudflare Quick Tunnel**: Process terminated via task management; confirmed port `3456` released from tunnel binding.
3. **Local MCP Server**: Process terminated; confirmed port `3456` in `TimeWait` and then closed; zero listening sockets remain.
4. **Scratch Purge**: The entire scratch directory (`%appDataDir%\brain\<conversation-id>\scratch\*`) containing `mcp_proof`, `cloudflared.exe`, and log files was recursively removed.
5. **No Lingering Resources**: Confirmed zero persistent Cloudflare resources, zero DNS entries, and zero account state.

---

## 8. Master Plan Acceptance Criteria Checklist

- [x] **Current spec requirements re-verified**: Verified official Amazon Alexa+ docs, MCP spec, and SDK capabilities on `2026-09-29`.
- [x] **Remote HTTPS endpoint**: Successfully provisioned and resolved via Cloudflare Quick Tunnel (`https://omissions-lessons-nutritional-warren.trycloudflare.com`).
- [x] **Streamable HTTP works**: End-to-end JSON-RPC 2.0 handshake, tool listing, and tool invocation executed over Streamable HTTP transport.
- [x] **Protocol/version recorded**: Negotiated protocol version `2025-11-25`; documented discrepancies (`2024-11-05`, `2025-03-26`, `2025-11-25`).
- [x] **Latency measured**: Connection `339.91ms`, echo tool invocation `61.26ms` (`OBSERVED_PASS_FOR_THIS_PROBE`).
- [x] **No product tools yet**: Strictly 0 product tools; exactly 1 diagnostic transport-only `echo` tool.
- [x] **Zero personal spend**: `$0.00` personal spend incurred.
- [x] **Zero retries / fallback**: Exactly 1 invocation attempt; 0 retries; 0 transport fallbacks.
