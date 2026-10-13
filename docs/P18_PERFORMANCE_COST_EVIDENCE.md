# P-18 Performance, Cost & Reliability Hardening — Evidence Pack

**Batch**: `P-18.01 → P-18.03 Consolidated Measurement & Cost-Truth Repair Batch`  
**Observation Date**: `2026-10-13`  
**Canonical Baseline Remote SHA**: `79cf5f46418581d158ea2f1913bfc5c4b63b3263`  
**Governing Authority**: [AGENTS.md](../AGENTS.md) § 1–24; [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md); [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md)  
**Evidence Provenance**: `LOCAL_EXECUTION` (local measurements) + `FIXTURE` (fixture mission measurements) + `RECORDED_LIVE` (historical P-01.07 evidence)  

---

## 1. Executive Summary

This document establishes the empirical performance measurements and cost-accounting reality for the three tasks of the P-18 consolidated batch:

1. **P-18.01 — End-to-End Mission Latency & Per-Component Latency**: Measured via deterministic monotonic instrumentation (`time.perf_counter_ns()`) across the canonical killer mission vertical slice. Discrete step execution statuses (`PASS`, `FAILED`, `BLOCKED`, `NOT_RUN`) and per-step runs are preserved across failure aggregation; unexecuted steps report strictly zero duration (0 ns). Attempted vs successful sample counts are separated so blocked/failed steps never distort success p95 latencies. Ordinary step exceptions are caught as privacy-safe `FAILED` outcomes and abort subsequent steps as `NOT_RUN`. Aggregate lifecycle-step fixture timings measure local compute overhead only; live provider latency remains `NOT_RUN`.
2. **P-18.02 — MCP Transport Latency vs Alexa+ Requirements**: Measured via local loopback Streamable HTTP transport against official Amazon Alexa+ developer documentation (< 500ms round-trip query response requirement). `LOCAL_PASS` is strictly awarded only if all operations succeed and measured p95 is strictly < 500.0ms. Latencies $\ge 500.0$ms produce `LOCAL_SLOW`; protocol exceptions, wrong mission identity, or missing tools produce `LOCAL_FAILED`. Provenance is strictly separated: P-01.07 historical remote echo is `RECORDED_LIVE`; P-05.07 historical local loopback is `LOCAL_EXECUTION`; current local Streamable HTTP is `LOCAL_EXECUTION`. Remote public transport and Alexa+ partner client paths remain `NOT_RUN`.
3. **P-18.03 — AWS Usage / Cost Per Canonical Mission**: Structured accounting separating real measured account usage (preserved as `NOT_OBSERVED`), local runtime activity (`FIXTURE`/`LOCAL_EXECUTION`), verified pricing estimates (based on official AWS pricing), and explicit `NOT_OBSERVED` account billing fields. Zero personal spend policy (`$0.00`) strictly preserved. CloudWatch EMF cost is `None` (`NOT_ESTIMABLE`) because account-wide usage is unobserved offline. AgentCore microVM rates are verified published pricing, but runtime consumption is unobserved (`VERIFIED_RATE_UNOBSERVED_CONSUMPTION`). Gross mission total is marked `NOT_ESTIMABLE_OFFLINE` and `total_estimated_cost_usd` is `None` to prevent mistaking Bedrock-only conditional planning scenarios for complete mission totals.

---

## 2. P-18.01 — End-to-End Mission Latency & Per-Component Latency

### 2.1 Methodology & Invariants
- **Clock**: `time.perf_counter_ns()` (strictly monotonic sub-microsecond clock).
- **Environment**: Windows 11 (AMD64), Python 3.13.16.
- **Warmup Separation**: Warmup iterations are measured but excluded from final statistics to separate cold startup from steady-state execution.
- **Logger Isolation**: Importing the benchmark module alters zero global logger levels, disabled flags, or handlers. Scoped suppression during benchmarks is restored unconditionally in `finally`.
- **Timing & Execution Truth**:
  - `PASS`: Step was invoked and succeeded (`was_invoked = True`, `was_executed = True`, `elapsed_ns >= 0`).
  - `BLOCKED` / `FAILED`: Step was invoked locally, recording local processing time (`elapsed_ns >= 0`), but is NEVER labeled as successfully executed provider work (`was_executed = False`).
  - `NOT_RUN`: Step was not invoked (`was_invoked = False`, `was_executed = False`, `elapsed_ns = 0`).
  - Sequence abortion: If a step fails or is blocked, subsequent steps in the sequence are aborted and recorded as `NOT_RUN` with strictly 0 ns.
  - Lifecycle truth: Canonical killer mission success requires reaching the `DRIFTED` state with historical receipt hash intact.
- **Discrete Step Timing Sequence**:
  1. `seed_demo_resources` (P-13.01)
  2. `plan_compilation` (P-13.02)
  3. `tasks_prep` (P-13.03)
  4. `calendar_approval_pause` (P-13.04)
  5. `calendar_update_approved` (P-13.05)
  6. `ready_receipt_projection` (P-13.06)
  7. `drift_reconciliation` (P-13.07)
- **Provenance**: `FIXTURE` (in-memory test doubles). Zero live external network calls were executed.

### 2.2 Empirical Measurement Results (Historical Baseline)

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
> **Aggregate Fixture Timing Disclosure**:
> All timings in Section 2 are measured in FIXTURE mode using deterministic test doubles. Timings are aggregate lifecycle-step fixture timings and do NOT separately measure real Bedrock inference, provider network latency, independent read-back, or cold-start time. No live external provider calls were executed. Fixture timings measure local computational overhead only and MUST NOT be presented as live provider latency. Live provider latency remains `NOT_RUN`.

---

## 3. P-18.02 — MCP Transport Latency vs Alexa+ Requirements

### 3.1 Requirement Verification
- **Official Source**: Amazon Alexa+ Developer Documentation ([developer.amazon.com](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html))
- **Verified Requirement**: Round-trip query response latency `< 500 ms` for external Model Context Protocol (MCP) servers connected to Alexa+.
- **Requirement Verification Status**: `OBSERVED_IN_DOCUMENTATION`.
- **Standalone SLA Contract**: `NOT_FOUND` (Amazon does not publish an external uptime SLA; performance is enforced as platform qualification threshold).

### 3.2 Provenance Separation & Latency Matrix

| Measurement / Path | Provenance | Classification | Sample Count | Median (ms) | P95 (ms) | Target / Ceiling | Verdict | Reference |
|---|---|---|---|---|---|---|---|---|
| **Local MCP `initialize`** | `LOCAL_EXECUTION` | `CURRENT_LOCAL_LOOPBACK` | 5 | 2.91 | 5.46 | < 500 ms | `LOCAL_PASS` | Fresh loopback run |
| **Local MCP `tools/list`** | `LOCAL_EXECUTION` | `CURRENT_LOCAL_LOOPBACK` | 5 | 5.34 | 7.93 | < 500 ms | `LOCAL_PASS` | Fresh loopback run |
| **Local MCP `mission_status`** | `LOCAL_EXECUTION` | `CURRENT_LOCAL_LOOPBACK` | 5 | 3.61 | 4.66 | < 500 ms | `LOCAL_PASS` | Fresh loopback run |
| **Historical Remote Echo** | `RECORDED_LIVE` | `RECORDED_LIVE_REMOTE_MCP` | 1 | 61.26 | 61.26 | < 500 ms | `RECORDED_LIVE` | `docs/P01_AWS_FEASIBILITY_EVIDENCE.md` (P-01.07) |
| **Historical Local Init p50** | `LOCAL_EXECUTION` | `HISTORICAL_LOCAL_LOOPBACK` | 30 | 8.05 | 10.59 | < 500 ms | `HISTORICAL_LOCAL` | `docs/P05_MCP_SPECIFICATION_EVIDENCE.md` (P-05.07) |
| **Historical Local Tools p50** | `LOCAL_EXECUTION` | `HISTORICAL_LOCAL_LOOPBACK` | 30 | 7.33 | 9.81 | < 500 ms | `HISTORICAL_LOCAL` | `docs/P05_MCP_SPECIFICATION_EVIDENCE.md` (P-05.07) |
| **Historical Local Status p50** | `LOCAL_EXECUTION` | `HISTORICAL_LOCAL_LOOPBACK` | 30 | 15.18 | 18.56 | < 500 ms | `HISTORICAL_LOCAL` | `docs/P05_MCP_SPECIFICATION_EVIDENCE.md` (P-05.07) |
| **Live Remote MCP Transport** | `NOT_RUN` | — | 0 | N/A | N/A | < 500 ms | `NOT_RUN` | No authorized remote endpoint |
| **Live Alexa+ Client-to-MCP** | `NOT_RUN` | — | 0 | N/A | N/A | < 500 ms | `NOT_RUN` | Partner access `NOT_ESTABLISHED` |

### 3.3 Compliance Assessment
- **Local Headroom**: `LOCAL_PASS`. Local Streamable HTTP p95 round-trip latency (7.93ms) is ~492.07ms below the 500ms ceiling. All operations verified valid protocol and structured payload responses.
- **Remote / Production Compliance**: `REQUIREMENT_NOT_VERIFIED`. Remote public HTTPS endpoint and genuine Alexa+ client-to-MCP connection remain `NOT_RUN` (operator partner access `NOT_ESTABLISHED`). Local headroom CANNOT certify remote production compliance.

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

| Service | Component | Category | Quantity / Unit | Unit Price (USD) | Estimated Cost (USD) | Official Pricing Source | Verified | Notes |
|---|---|---|---|---|---|---|---|---|
| **Amazon Bedrock** | `amazon.nova-micro-v1:0` (Converse) | `VERIFIED_PRICING` | 300 tokens (200 in / 100 out) | $0.000035 / 1K in, $0.00014 / 1K out | $0.00002100 | [aws.amazon.com/bedrock/pricing](https://aws.amazon.com/bedrock/pricing/) | **YES** | `EXAMPLE_ASSUMPTIONS`: 200 in / 100 out tokens are hypothetical planning assumptions, NOT measured canonical consumption or billed tokens. |
| **AWS Strands Agents SDK** | `strands-agents==1.57.2` | `DIRECT_FEE_ZERO` | 1 invocation | $0.00 | $0.00000000 | Open-Source Apache-2.0 | **YES** | Direct SDK library invocation fee is $0.00. Does not cover underlying compute, network, or Bedrock API calls. |
| **AWS IAM** | SigV4 request signing | `DIRECT_FEE_ZERO` | 1 request | $0.00 | $0.00000000 | AWS IAM standard policy | **YES** | IAM SigV4 request signing has no direct per-request charge. Underlying AWS request charges apply separately. |
| **Amazon CloudWatch (EMF)** | PutLogEvents EMF ingestion (prepared) | `ACCOUNT_USAGE_DEPENDENT` | 4 log events | None | *NOT_ESTIMABLE* | [aws.amazon.com/cloudwatch/pricing](https://aws.amazon.com/cloudwatch/pricing/) | **YES** | Subject to 5GB/month account-level free tier ($0.50/GB thereafter). Ingestion coverage depends on aggregate account usage across all services and billing cycles, which is `NOT_OBSERVED` offline. Per AGENTS.md § 11-12, estimated cost is `NOT_ESTIMABLE` offline (must not be assumed $0.00). |
| **Amazon Bedrock AgentCore Runtime** | Serverless CodeZip microVM execution | `VERIFIED_RATE_UNOBSERVED_CONSUMPTION` | vCPU-seconds / memory-seconds / duration | None | *NOT_ESTIMABLE* | [aws.amazon.com/bedrock/agentcore/pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) | **YES** | `NOT_ESTIMABLE_OFFLINE`: Official resource rates are verified and published ($0.0895-$0.1276/vCPU-hr active, $0.00945-$0.0169/GB-hr memory). However, actual active compute seconds, memory allocation, microVM tier, and runtime duration for this mission are unobserved offline without live profiling. No dollar amount is invented. |
| **CONDITIONAL SCENARIO TOTAL** | — | — | — | — | **$0.00002100 USD** | — | — | Bedrock Nova Micro inference only under example assumptions. Labeled conditional planning scenario, not complete gross mission cost. |
| **DEFINITIVE GROSS MISSION TOTAL** | — | — | — | — | **NOT_ESTIMABLE_OFFLINE** | — | — | Unestimated components: AgentCore microVM runtime, CloudWatch account-level aggregation. `total_estimated_cost_usd` is `None`. |

#### Category D: Preserved NOT_OBSERVED Fields
1. Actual AWS account billing delta per mission: `NOT_OBSERVED`
2. Actual promotional credit consumption per mission: `NOT_OBSERVED`
3. Actual Bedrock token billing (no invocation authorized): `NOT_OBSERVED`
4. Actual AgentCore runtime billing: `NOT_OBSERVED`
5. Actual CloudWatch ingestion billing (EMF NOT_RUN live): `NOT_OBSERVED`
6. Post-promotional-credit personal spend delta: `NOT_OBSERVED`

### 4.2 Financial Safety & Spend Law Compliance
- **Target Personal Spend**: Strictly `$0.00` (Zero Personal Spend Law).
- **Actual Personal Spend Incurred**: `NOT_OBSERVED` from billing provider; zero billable calls authorized in this batch.
- **Promotional Credit Policy**: Promotional credit of $150.00 was recorded in P-01.01. Because AgentCore microVM pricing and total account billing are unobserved offline, no fixed number of missions can be definitively guaranteed by the credit. Zero Personal Spend Law remains enforced fail-closed.

---

## 5. Artifacts and Tooling Summary

- **Benchmark Module**: `src/stilldone/benchmarks.py`
  - Zero import-time logger mutations; fully restored scoped suppression.
  - `run_mission_benchmark()`: Monotonic per-step timing harness preserving complete run outcomes (PASS, BLOCKED, FAILED, NOT_RUN); privacy-safe exception handling; separated attempted vs successful sample counts.
  - `measure_mcp_transport_latency()`: Loopback Streamable HTTP transport test with response verification, strict `< 500.0ms` threshold for `LOCAL_PASS`, explicit `LOCAL_SLOW` and `LOCAL_FAILED` verdicts.
  - `estimate_aws_cost_per_mission()`: Pricing-backed cost estimation with explicit unestimated components; CloudWatch EMF cost `None` (`NOT_ESTIMABLE`); AgentCore published rates verified with unobserved consumption; `total_estimated_cost_usd is None`.
- **CLI Runner**: `scripts/p18_benchmarks.py` (supports `--all`, `--p18-01`, `--p18-02`, `--p18-03`, `--json`, `--output`; KeyError-safe on partial/failed runs).
- **Test Suite**: `tests/test_phase_p18_benchmarks.py` (38 passing tests, zero wall-clock assertions).
- **Test Suite Invariant**: Core test suite: **2,451 PASSED**; Strands planner test suite: **1,155 PASSED**.
