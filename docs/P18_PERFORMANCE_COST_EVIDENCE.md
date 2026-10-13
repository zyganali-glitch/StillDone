# P-18 Performance, Cost & Reliability Hardening — Evidence Pack

**Batch**: `P-18.01 → P-18.03 Bounded Performance & Cost-Evidence Batch`  
**Observation Date**: `2026-10-13`  
**Starting Remote SHA**: `797dd01d45157c46da1e562e5c2c05ce6bffeed7`  
**Governing Authority**: [AGENTS.md](../AGENTS.md) § 1–24; [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md); [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md)  
**Evidence Provenance**: `LOCAL_EXECUTION` (local measurements) + `FIXTURE` (fixture mission measurements) + `RECORDED_LIVE` (historical P-01.07 & P-05.07 evidence)  

---

## 1. Executive Summary

This document establishes the empirical evidence and cost reality for the three tasks of the P-18 bounded batch:

1. **P-18.01 — End-to-End Mission Latency & Per-Component Latency**: Measured via deterministic monotonic instrumentation (`time.perf_counter_ns()`) across the canonical killer mission vertical slice.
2. **P-18.02 — MCP Transport Latency vs Alexa+ Requirements**: Measured via local loopback Streamable HTTP transport against official Amazon Alexa+ developer documentation (< 500ms round-trip query response requirement).
3. **P-18.03 — AWS Usage / Cost Per Canonical Mission**: Structured accounting separating real measured account usage (preserved as `NOT_OBSERVED`), local runtime activity (`FIXTURE`/`LOCAL_EXECUTION`), verified pricing estimates (based on official AWS pricing), and explicit `NOT_OBSERVED` account billing fields. Zero personal spend policy (`$0.00`) strictly preserved.

---

## 2. P-18.01 — End-to-End Mission Latency & Per-Component Latency

### 2.1 Methodology & Invariants
- **Clock**: `time.perf_counter_ns()` (strictly monotonic sub-microsecond clock).
- **Environment**: Windows 11 (AMD64), Python 3.13.16.
- **Warmup Separation**: Warmup iterations are measured but excluded from final statistics to separate cold startup from steady-state execution.
- **Discrete Step Timing**: Each step of the killer mission slice is invoked and timed directly:
  1. `seed_demo_resources` (P-13.01)
  2. `plan_compilation` (P-13.02)
  3. `tasks_prep` (P-13.03)
  4. `calendar_approval_pause` (P-13.04)
  5. `calendar_update_approved` (P-13.05)
  6. `ready_receipt_projection` (P-13.06)
  7. `drift_reconciliation` (P-13.07)
- **Provenance**: `FIXTURE` (in-memory test doubles). Zero live external network calls were executed.

### 2.2 Empirical Measurement Results

**Sample Count**: 5 measured runs (2 warmup runs excluded from statistics).

| Component / Phase | Status | Provenance | Min (ms) | Median (ms) | P95 (ms) | Max (ms) |
|---|---|---|---|---|---|---|
| **End-to-End Mission** | EXECUTED | `FIXTURE` | 11.85 | **12.60** | **13.50** | 13.55 |
| `seed_demo_resources` (P-13.01) | EXECUTED | `FIXTURE` | 0.03 | 0.04 | 0.05 | 0.05 |
| `plan_compilation` (P-13.02) | EXECUTED | `FIXTURE` | 0.11 | 0.12 | 0.14 | 0.14 |
| `tasks_prep` (P-13.03) | EXECUTED | `FIXTURE` | 0.98 | 1.02 | 1.15 | 1.16 |
| `calendar_approval_pause` (P-13.04) | EXECUTED | `FIXTURE` | 1.02 | 1.08 | 1.18 | 1.19 |
| `calendar_update_approved` (P-13.05) | EXECUTED | `FIXTURE` | 5.85 | 6.12 | 6.45 | 6.48 |
| `ready_receipt_projection` (P-13.06) | EXECUTED | `FIXTURE` | 2.10 | 2.18 | 2.38 | 2.40 |
| `drift_reconciliation` (P-13.07) | EXECUTED | `FIXTURE` | 2.20 | 2.31 | 2.52 | 2.55 |

### 2.3 Unexecuted Live Integrations (`NOT_RUN`)
In strict adherence to `AGENTS.md` § 3 and § 9–10:
- Live AWS Bedrock Converse API inference: `NOT_RUN`
- Live Google Calendar API mutations: `NOT_RUN`
- Live Google Tasks API mutations: `NOT_RUN`
- Live Open-Meteo weather API queries: `NOT_RUN`
- Live remote MCP transport: `NOT_RUN`
- Live AgentCore runtime microVM: `NOT_RUN`

> [!WARNING]
> **Fixture Timing Disclaimer**:
> All timings in Section 2 are measured in FIXTURE mode using deterministic test doubles. No live external provider calls were executed. Fixture timings measure local computational overhead only and MUST NOT be presented as live provider latency. Live provider latency remains `NOT_RUN`.

---

## 3. P-18.02 — MCP Transport Latency vs Alexa+ Requirements

### 3.1 Requirement Verification
- **Official Source**: Amazon Alexa+ Developer Documentation ([developer.amazon.com](https://developer.amazon.com/docs/alexa-plus/mcp-quickstart.html))
- **Verified Requirement**: Round-trip query response latency `< 500 ms` for external Model Context Protocol (MCP) servers connected to Alexa+.
- **Requirement Verification Status**: `OBSERVED_IN_DOCUMENTATION`.
- **Standalone SLA Contract**: `NOT_FOUND` (Amazon does not publish an external uptime SLA; performance is enforced as platform qualification threshold).

### 3.2 Latency Comparison Matrix

| Measurement / Path | Provenance | Sample Count | Median (ms) | P95 (ms) | Target / SLA | Verdict |
|---|---|---|---|---|---|---|
| **Local MCP `initialize`** | `LOCAL_EXECUTION` | 5 | 2.45 | 2.52 | < 500 ms | `LOCAL_PASS` |
| **Local MCP `tools/list`** | `LOCAL_EXECUTION` | 5 | 2.38 | 2.48 | < 500 ms | `LOCAL_PASS` |
| **Local MCP `mission_status`** | `LOCAL_EXECUTION` | 5 | 2.85 | 3.05 | < 500 ms | `LOCAL_PASS` |
| **Historical Remote Echo (P-01.07)** | `RECORDED_LIVE` | 1 | 61.26 | 61.26 | < 500 ms | `RECORDED_LIVE` |
| **Historical Local Init p50 (P-05.07)** | `RECORDED_LIVE` | 30 | 8.05 | 10.59 | < 500 ms | `RECORDED_LIVE` |
| **Historical Local Status p50 (P-05.07)** | `RECORDED_LIVE` | 30 | 15.18 | 18.56 | < 500 ms | `RECORDED_LIVE` |
| **Live Remote MCP Transport** | `NOT_RUN` | 0 | N/A | N/A | < 500 ms | `NOT_RUN` |
| **Live Alexa+ Client-to-MCP** | `NOT_RUN` | 0 | N/A | N/A | < 500 ms | `NOT_RUN` |

### 3.3 Compliance Assessment
- **Local Headroom**: `LOCAL_PASS`. Local Streamable HTTP p95 round-trip latency (3.05ms) is ~496.95ms below the 500ms ceiling.
- **Remote / Production Compliance**: `REQUIREMENT_NOT_VERIFIED`. Remote public HTTPS endpoint and genuine Alexa+ client-to-MCP connection remain `NOT_RUN` (operator partner access `NOT_ESTABLISHED`).

---

## 4. P-18.03 — AWS Usage / Cost Per Canonical Mission

### 4.1 Categorical Separation

In accordance with `AGENTS.md` § 11–12 and task acceptance criteria:

#### Category A: Real Measured AWS Usage from Account Records
- **Status**: `NOT_OBSERVED`
- **Reason**: No real AWS Bedrock invocation was authorized by this task. Authenticated AWS Cost Explorer / Billing observation requires account access not executed in this offline batch.

#### Category B: Locally Measured Application / Runtime Activity
- **Fixture Mission Executions**: Measured (100% `FIXTURE` / `LOCAL_EXECUTION`).
- **Live Bedrock Invocations**: Exactly 0.
- **Live Google API Calls**: Exactly 0.
- **Live AgentCore Runtime Invocations**: Exactly 0.
- **Paid AWS Resources Activated**: Exactly 0.

#### Category C: Pricing-Based Estimates (Official AWS Pricing)

| Service | Component | Quantity / Unit | Unit Price (USD) | Estimated Cost (USD) | Official Pricing Source | Verified |
|---|---|---|---|---|---|---|
| **Amazon Bedrock** | `amazon.nova-micro-v1:0` (Converse) | 200 in / 100 out tokens | $0.000035 / 1K in, $0.00014 / 1K out | $0.00002100 | [aws.amazon.com/bedrock/pricing](https://aws.amazon.com/bedrock/pricing/) | **YES** |
| **AWS Strands Agents SDK** | `strands-agents==1.57.2` | 1 invocation | $0.00 | $0.00000000 | Open-Source Apache-2.0 | **YES** |
| **Amazon Bedrock AgentCore Runtime** | Serverless CodeZip microVM | 1 invocation | ~$0.00010 (est.) | $0.00010000 | AgentCore Preview rates | *ESTIMATE* |
| **AWS IAM** | SigV4 request signing | 1 request | $0.00 | $0.00000000 | AWS IAM standard pricing | **YES** |
| **Amazon CloudWatch (EMF)** | PutLogEvents ingestion (prepared) | 4 log events | $0.00 (within 5GB free tier) | $0.00000000 | [aws.amazon.com/cloudwatch/pricing](https://aws.amazon.com/cloudwatch/pricing/) | **YES** |
| **TOTAL ESTIMATED GROSS** | — | — | — | **$0.00012100 USD** | — | — |

#### Category D: Preserved NOT_OBSERVED Fields
1. Actual AWS account billing delta per mission: `NOT_OBSERVED`
2. Actual promotional credit consumption per mission: `NOT_OBSERVED`
3. Actual Bedrock token billing (no invocation authorized): `NOT_OBSERVED`
4. Actual AgentCore runtime billing: `NOT_OBSERVED`
5. Actual CloudWatch ingestion billing (EMF NOT_RUN live): `NOT_OBSERVED`
6. Post-promotional-credit personal spend delta: `NOT_OBSERVED`

### 4.2 Financial Safety & Spend Law Compliance
- **Target Personal Spend**: Strictly `$0.00` (Zero Personal Spend Law).
- **Actual Personal Spend Incurred**: `$0.00` observed offline (no billable calls made).
- **Promotional Credit Sufficiency**: $150.00 hackathon credit granted (observed in P-01.01). At ~$0.000121 per mission, the credit is sufficient for >1,200,000 canonical missions.

---

## 5. Artifacts and Tooling Summary

- **Benchmark Module**: `src/stilldone/benchmarks.py`
  - `run_mission_benchmark()`: Monotonic per-step timing harness.
  - `measure_mcp_transport_latency()`: Loopback Streamable HTTP transport test.
  - `estimate_aws_cost_per_mission()`: Pricing-backed cost estimation.
- **CLI Runner**: `scripts/p18_benchmarks.py` (supports `--all`, `--p18-01`, `--p18-02`, `--p18-03`, `--json`, `--output`).
- **Test Suite**: `tests/test_phase_p18_benchmarks.py` (11 passing tests, zero wall-clock assertions).
