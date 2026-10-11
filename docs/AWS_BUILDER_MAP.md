# AWS Builder Architecture & Evidence Map (Phase P-16)

**Track**: AWS Builder Mini Challenge / Build, Ship, Shape: Amazon Developer Hackathon  
**Target Personal Spend**: Strictly `$0.00`  
**Current Net Spend**: `$0.00000000 USD` (100% covered by AWS Promotional Credit and AWS Free Tier)

---

## 1. Executive Summary

StillDone solves the foundational problem in autonomous AI agent systems: **a tool execution response (`200 OK`) does not prove that an outcome was actually verified or that reality will not drift later.**

Rather than assembling decorative AWS services to inflate hackathon checklists, StillDone's AWS architecture is **strictly lean, purposeful, and non-decorative**. Every service on the critical path defends a constitutional product invariant:

1. **Amazon Bedrock**: Translates messy human intent into typed, fail-closed candidate plans without prompt injection vulnerabilities.
2. **AWS Strands Agents SDK**: Orchestrates the planning lifecycle in dual-runtime isolation, keeping runtime dependencies separate from modern Streamable HTTP MCP libraries.
3. **Amazon Bedrock AgentCore Runtime**: Hosts the live self-hosted MCP server over Streamable HTTP in a secure microVM.
4. **AWS Identity and Access Management (IAM) & SigV4**: Cryptographically signs every request (`AWS4-HMAC-SHA256`) with least-privilege role boundaries and ephemeral credentials.
5. **Amazon CloudWatch Embedded Metric Format (EMF)**: Directly measures outcome verification latency, read-back contradictions, and external drift rates with zero network overhead, zero SDK bloat, and $0.00 spend.

```
                    +------------------------------------------+
                    |       Human Operator Intent (Alexa+)     |
                    +------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
| AWS Bedrock AgentCore Runtime (us-east-1)                                      |
| +-----------------------------------------------------------------------------+ |
| | StillDone MCP Server Spine (Streamable HTTP on /mcp)                        | |
| |   * SigV4 Inbound Authentication (StillDoneAgentCoreExecutionRole)          | |
| |   * Tools: mission.start, mission.status                                    | |
| +-----------------------------------------------------------------------------+ |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
| Dual-Runtime Planning & Inference                                               |
| +------------------------------------+   +------------------------------------+ |
| | Amazon Bedrock (Nova Micro/Claude) |<--| AWS Strands Agents SDK             | |
| |   * CandidatePlanProposal parsing  |   |   * Orchestration Loop             | |
| |   * Zero model readiness authority |   |   * Fail-closed parameter schema   | |
| +------------------------------------+   +------------------------------------+ |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
| StillDone Deterministic Verification Engine                                     |
| +-----------------------------+  +--------------------------------------------+ |
| | Bounded Mutation Pipeline   |  | Independent Read-Back & Predicates         | |
| | (Google Calendar / Tasks)   |  | (Execute success != Verification)          | |
| +-----------------------------+  +--------------------------------------------+ |
|                                        |                                        |
|                                        v                                        |
|                          +---------------------------+                          |
|                          | Reconcile: READY->DRIFTED |                          |
|                          +---------------------------+                          |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
| Amazon CloudWatch Embedded Metric Format (EMF) Telemetry                        |
| Namespace: StillDone/VerificationEngine                                         |
| Metrics: VerificationLatencyMs, ReadbackContradictionCount, DriftDetectedCount  |
+---------------------------------------------------------------------------------+
```

---

## 2. Audited AWS Critical Path Services (P-16.01)

| Service | Region | Role | Live Proof Reference | Non-Decorative Justification | Gross Spend | Net Spend |
|---|---|---|---|---|---|---|
| **Amazon Bedrock** | `us-east-1` | Model Reasoning | `P-01.02`, `P-07.06` (`docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md`) | Converts natural language intent to typed plans; strictly stripped of execution and readiness authority. | $\approx \$0.000002$ | **$0.00** (Promo Credit) |
| **AWS Strands Agents SDK** | `us-east-1` | Agent Orchestration | `P-01.03`, `P-07.06` (`docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md`) | Agent framework running planning loop in dual-runtime isolation. | $\$0.000000$ | **$0.00** |
| **Amazon Bedrock AgentCore Runtime** | `us-east-1` | Serverless MicroVM MCP Host | `P-05.06` (`docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md`) | MicroVM runtime hosting Streamable HTTP MCP server spine (`agentRuntimeArn: stilldone_mcp_runtime-oS0aWdAWg3`). | $\approx \$0.008388$ | **$0.00** (Promo Credit) |
| **AWS IAM & SigV4** | `us-east-1` | Ingress Security | `P-05.06` (`docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md`) | SigV4 request signing (`AWS4-HMAC-SHA256`) and least-privilege IAM roles (`StillDoneAgentCoreExecutionRole`). | $\$0.000000$ | **$0.00** (Free Tier) |
| **Amazon CloudWatch (EMF)** | `us-east-1` | High-Cardinality Observability | `P-16.02`, `P-16.03` (`src/stilldone/aws_builder.py`) | Zero-latency structured telemetry capturing verification latency, read-back contradictions, and drift rates. | $\$0.000000$ | **$0.00** (Free Tier) |

---

## 3. Added Service: Amazon CloudWatch Embedded Metric Format (P-16.02 & P-16.03)

### Why CloudWatch EMF is Material and Non-Decorative

In traditional architectures, logging an agent action emits a generic line: `POST /update_event 200 OK`. This conventional pattern hides the critical failure mode that StillDone solves:
- The provider may return 200 OK while the event start time was corrupted.
- The event may be correctly updated at 07:30, but an external party shifts it to 08:00 ten minutes later.
- An agent may attempt to write without human operator approval.

StillDone embeds AWS CloudWatch Embedded Metric Format (EMF) directly into its verification pipeline (`src/stilldone/aws_builder.py`). EMF output conforms to the official AWS EMF Specification v1.0, generating high-resolution metrics without network overhead or third-party daemon requirements:

```json
{
  "_aws": {
    "Timestamp": 1791645600000,
    "CloudWatchMetrics": [
      {
        "Namespace": "StillDone/VerificationEngine",
        "Dimensions": [
          ["Environment", "VerificationStatus"],
          ["Environment", "ActionType"],
          ["Environment"]
        ],
        "Metrics": [
          {"Name": "VerificationLatencyMs", "Unit": "Milliseconds"},
          {"Name": "VerificationSuccessCount", "Unit": "Count"},
          {"Name": "ReadbackContradictionCount", "Unit": "Count"},
          {"Name": "WritesPerformedCount", "Unit": "Count"}
        ]
      }
    ]
  },
  "Environment": "production",
  "VerificationStatus": "PASS",
  "ActionType": "calendar.update",
  "VerificationLatencyMs": 24.2,
  "VerificationSuccessCount": 1,
  "ReadbackContradictionCount": 0,
  "WritesPerformedCount": 1,
  "MissionId": "11111111-2222-3333-4444-555555555555",
  "TaskId": "P-13.05",
  "Service": "StillDone"
}
```

### Emitted Metric Types
1. **`VerificationLatencyMs`**: Measures the latency delta between mutation execution and independent read-back verification.
2. **`ReadbackContradictionCount`**: Increments when write execution succeeded (200 OK) but independent read-back contradicted expected state.
3. **`DriftDetectedCount`**: Increments when an externally induced reality change shifts a `READY` mission into `DRIFTED`.
4. **`UnapprovedWriteBlockedCount`**: Increments when an unapproved write halts fail-closed at the human approval boundary.

---

## 4. Cost Impact Validation & Zero Personal Spend Law (P-16.05)

StillDone is governed by the **Zero Personal Spend Law** (`AGENTS.md` Rule 12):
> Target personal spend is `$0.00`. Allowed: hackathon promotional credits, permanent free tiers, local development. Forbidden: paid subscriptions, unmetered endpoints, deposits.

### Cost Breakdown
1. **Amazon Bedrock (Nova Micro / Claude 3.5 Sonnet)**:
   - Nova Micro: \$0.000035 / 1K input tokens, \$0.00014 / 1K output tokens.
   - Live killer mission execution: 12 tokens $\approx \$0.00000168\text{ USD}$.
   - 100% offset by AWS Developer Hackathon promotional credit balance.
2. **Amazon Bedrock AgentCore Runtime**:
   - MicroVM session hosting MCP server: billable usage in September 2026 was `$0.0083883943 USD`.
   - 100% offset by promotional credit (verified in billing audit: net spend `$0.0000000000 USD`).
   - Clean shutdown teardown commands verified in `docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md`.
3. **AWS IAM & SigV4 Authentication**:
   - Standard AWS feature: \$0.00 cost.
4. **Amazon CloudWatch Embedded Metric Format**:
   - Emits structured JSON logs to standard stdout streams.
   - AWS Free Tier includes 5 GB log ingestion and 10 custom metrics per month at \$0.00 cost.
5. **Net Personal Spend**:
   $$\text{Net Spend} = \mathbf{\$0.00000000\text{ USD}}$$
