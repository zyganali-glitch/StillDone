# P-18 Performance, Cost & Reliability Hardening — Evidence Pack

**Batch**: `P-18.01 → P-18.07 Bounded Reliability, Cost & Safety Hardening`  
**Observation Date**: `2026-10-13`  
**Canonical Baseline Remote SHA**: `7252bc8c0b5a22a7505d935e17e68f2f259d55ce`  
**Governing Authority**: [AGENTS.md](../AGENTS.md) § 1–24; [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md); [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md)  
**Evidence Provenance**: `LOCAL_EXECUTION` + `FIXTURE` + `RECORDED_LIVE`  

---

## 1. Executive Summary

This document establishes the empirical performance measurements, quota boundaries, reliability verification, and cost-accounting reality for the tasks of Phase P-18:

1. **P-18.01 — End-to-End Mission Latency & Per-Component Latency**: Monotonic instrumentation (`time.perf_counter_ns()`) across the canonical killer mission vertical slice.
2. **P-18.02 — MCP Transport Latency vs Alexa+ Requirements**: Local Streamable HTTP loopback against Amazon Alexa+ developer documentation (< 500ms round-trip query response requirement).
3. **P-18.03 — AWS Usage / Cost Per Canonical Mission**: Structured accounting separating real measured account usage (`NOT_OBSERVED`), local runtime activity (`FIXTURE`/`LOCAL_EXECUTION`), verified pricing estimates, and explicit `NOT_OBSERVED` account billing fields.
4. **P-18.04 — Enforce Runtime Budget/Rate Limits**: Deterministic endpoint admission protection. Distinguishes active general request limiter from separately tested paid-capable admission contract; non-paid MCP tools handle requests safely without paid execution; exception handling in `RateLimitMiddleware` repaired fail-closed with bounded JSON payload; atomic SQLite concurrency safety; process restarts preserve limits; estimated cost ceiling != AWS billing hard cap.
5. **P-18.05 — Verify Google/Open-Meteo Quota Safety**: Documented published provider limits reconciled with official sources (Google Calendar: May 1, 2026 revision, 1M/day, 10k/min/project, 600/min/user; Google Tasks: 50k/day courtesy; Open-Meteo `/terms`: 10k/day, 5k/hr, 600/min). Actual remaining account quotas strictly `NOT_OBSERVED`. Calendar 429 yields 0 writes; 412 yields CONFLICT with 0 writes; idempotency duplicate yields NOOP with 0 writes; Tasks 429 yields 0 writes; Open-Meteo 429/timeout fails closed without coordinate/URL leakage; ambiguous mutation transport failure after server write never infers 0 remote writes, independent readback resolves truth.
6. **P-18.06 — Run Bounded Repeated-Mission Reliability Test**: Offline fixture-mode repeated-mission harness. Enforces validated iteration caps and timeouts; derives READY/DRIFTED milestones from actual runner state; dynamically evaluates canonical predicates; tracks qualification status (`QUALIFIED` vs `PARTIAL_UNQUALIFIED`) and untested scenarios; historical receipt hash verified intact across READY -> DRIFTED; zero cross-run contamination; zero duplicate unintended mutations; zero false READY.
7. **P-18.07 — Verify Judge-Period Availability Plan and Credit Expiry**: Implemented architectural plan (`docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md`, labeled `IMPLEMENTED / QA_PENDING`). Official Devpost deadline recorded as October 23, 2026 at 12:00 PM PDT (22:00 Europe/Istanbul, 19:00 UTC) with judging period November 9–20, 2026; Devpost FAQ vs Community Forum topics 45493 and 45411 operational ambiguity documented; preserves historical credit grant ($150) and conservative expiry boundary (2028-08-31) while treating current balance as unobserved offline; dual-surface architecture (Cloudflare Pages Free static exhibit `*.pages.dev` + authenticated on-demand operator runtime); three-tier bounded fallback plan; strictly $0.00 personal spend.

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

---

## 5. P-18.04 — Enforce Runtime Budget/Rate Limits

### 5.1 Admission Control & Endpoint Protection Truth
- **Module**: `src/stilldone/endpoint_protection.py` & `src/stilldone/mcp/rate_limit.py`.
- **Public & Unauthenticated Gate**: Public or anonymous requests cannot invoke paid AWS operations. Calling paid-capable endpoints requires valid authentication and active authorization (`HTTP 401 Unauthorized` / `HTTP 403 Forbidden`).
- **Runtime Admission Boundary**: Current MCP tools (`mission_start`, `mission_status`) operate strictly under non-paid capability (`NO_PAID_CAPABILITY / PUBLIC_UNTRUSTED`), creating local DRAFT missions without executing paid provider calls. Paid-capable live runtime admission wiring is separated and tested; it is marked `NOT_INTEGRATED / NOT_AUTHORIZED` for unauthenticated callers.
- **Fail-Closed Exception Safety**: `RateLimitMiddleware.__call__` initializes a sanitized, bounded JSON 500 error response unconditionally, preventing `UnboundLocalError` on unexpected store errors and leaking no internal secrets.
- **Operator-Controlled Kill-Switch**: The admission gate evaluates `live_paid_path_enabled`. When `False` (default), all paid-capable invocation requests fail closed with `HTTP 403 Forbidden`.
- **Budget Snapshot Fail-Closed**: Missing, expired, or corrupted budget snapshots immediately deny execution. Stale data never permits execution.
- **Pre-Mutation Rate Limit Denial**: Rate-limit exhaustion returns `HTTP 429 Too Many Requests` *before* initiating any provider mutation or downstream model execution.
- **Atomic Persistent Concurrency Safety**: The SQLite token bucket tracker operates under WAL mode with `BEGIN IMMEDIATE` transactions, ensuring atomic token reservation across concurrent callers.
- **Cost Ceiling != AWS Billing Cap**: Internal estimated cost limits are strictly modeled as application-level admission thresholds and explicitly documented as distinct from guaranteed AWS billing hard stops.
- **Evidence Provenance**: `LOCAL_EXECUTION` (21 focused adversarial tests in `tests/test_phase_p18_04_budget_rate_limits.py`). Zero live AWS calls executed.

---

## 6. P-18.05 — Verify Google/Open-Meteo Quota Safety

### 6.1 Published Provider Limits vs. Actual Quotas
- **Google Calendar API**:
  - Published limit: Documented threshold of 1,000,000 queries/day for standard Workspace projects; May 1, 2026 quota revision includes 10,000 req/min/project and 600 req/min/user ([Google Calendar Quota Docs](https://developers.google.com/workspace/calendar/api/guides/quota)).
  - Actual remaining account quota: Strictly `NOT_OBSERVED` offline without authenticated Google Cloud Console inspection.
- **Google Tasks API**:
  - Published limit: Documented courtesy limit of 50,000 queries/day ([Google Tasks Limits Docs](https://developers.google.com/workspace/tasks/limits)).
  - Actual remaining account quota: Strictly `NOT_OBSERVED` offline.
- **Open-Meteo API**:
  - Published limit: 10,000 daily API calls, 5,000/hour, 600/minute for non-commercial evaluation ([Open-Meteo Terms](https://open-meteo.com/en/terms)).
  - Actual remaining account quota: Strictly `NOT_OBSERVED` offline.

### 6.2 Provider Failure & Throttling Safety
- **HTTP 429 Throttling**: Simulated 429 responses in Google Calendar and Google Tasks adapters fail closed with `writes_performed = 0`. Throttling cannot trigger unbounded retries or duplicate writes.
- **State Integrity**: Throttled or rejected mutations never transition to `VERIFIED` or `READY`.
- **Ambiguous Mutation Handling**: Transport failures occurring after a provider mutation has applied remotely never infer zero remote writes from the client exception. Read-back verification is required before any retry, preventing duplicate writes and false verified states.
- **Idempotency Deduplication**: Duplicate event creation requests return `NOOP_ALREADY_APPLIED` with exactly 0 new writes performed.
- **Privacy Preservation**: Open-Meteo adapter errors sanitize coordinates and query parameters from error messages and logs.
- **Evidence Provenance**: `FIXTURE` / `LOCAL_EXECUTION` (15 focused quota safety tests in `tests/test_phase_p18_05_quota_safety.py`).

---

## 7. P-18.06 — Bounded Repeated-Mission Reliability Test

### 7.1 Methodology & Invariants
- **Harness**: `run_repeated_mission_reliability_test(iteration_cap=15)` in `src/stilldone/benchmarks.py`.
- **Execution Mode**: Strictly `FIXTURE` (offline test doubles). Zero network calls.
- **Enforced Bounds & Validation**: Validates `iteration_cap` (1 to 1000) and `timeout_per_run_seconds` (positive finite float); enforces execution timeout.
- **Dynamic Milestone & Predicate Derivation**: Step milestones (`reached_ready`, `reached_drifted`) and canonical predicates are evaluated dynamically against actual runner observations and ledgers rather than unconditionally assigned.
- **Qualification Tracking**: Tracks qualification status (`QUALIFIED` when all 5 representative scenarios are exercised; `PARTIAL_UNQUALIFIED` when `iteration_cap < 15` with explicit `untested_scenarios`).
- **Lifecycle Verification**: Exercises the complete canonical killer mission slice across 15 bounded runs:
  - 11 successful full lifecycle runs (`READY -> DRIFTED` with historical receipt hash intact).
  - 2 blocked runs: operator rejected at approval boundary (writes = 0 for calendar), missing preflight authorization (writes = 0).
  - 2 failed runs: contradictory read-back (mission halted unverified), provider 429 rate limit (slice aborted fail-closed).
- **Integrity Checks**:
  - Cross-run evidence contamination: `False` (zero leaked tasks, grants, or snapshot files across runs).
  - Duplicate unintended mutation: `False` (successful runs perform exactly 3 planned writes; blocked/failed runs perform 0 unapproved writes).
  - False READY: `False` (no blocked or failed run ever achieved `reached_ready = True` or generated a receipt).
  - Historical receipt integrity: `True` (all 11 successful runs maintain identical `receipt_projection_hash` through `DRIFTED`).
- **Evidence Provenance**: `FIXTURE` (16 tests in `tests/test_phase_p18_06_reliability.py`).

---

## 8. P-18.07 — Judge-Period Availability Plan and Credit Expiry

### 8.1 Strategic Plan Summary
- **Master Plan Document**: [docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md](JUDGE_PERIOD_AVAILABILITY_PLAN.md) (Status: `IMPLEMENTED / QA_PENDING`).
- **Official Competition Requirements**: Devpost submission deadline Friday, October 23, 2026 at 12:00 PM PDT (22:00 Europe/Istanbul, 19:00 UTC); judging period November 9–20, 2026; 3-minute video demo; public code repository URL. 24/7 unmetered cloud uptime is NOT an official requirement.
- **Devpost FAQ vs Community Operational Conflict**: Documented ambiguity across official Devpost FAQ (visibility after deadline) vs Forum topics 45493 and 45411 (confusion over draft submission visibility). StillDone assumes immediate public visibility and sanitizes all secrets.
- **Historical Credit Facts**: $150.00 hackathon promotional credit granted; active at P-01 checkpoint. Conservative expiration boundary enforced as `2028-08-31`. Current balance and account-wide charges remain `NOT_OBSERVED` offline. Credits do not provide a hard spending cap.
- **Dual-Surface Architecture**:
  1. *Surface 1 (Public Read-Only Exhibit)*: Hosted on Cloudflare Pages Free tier (`*.pages.dev`, $0.00 cost, zero domain purchase). Serves static evidence, recorded live receipts, immutable hashes, video walkthrough, and local reproduction instructions. Does NOT execute Python or live Bedrock inference.
  2. *Surface 2 (Authenticated Operator Runtime)*: Streamable HTTP MCP server with persistent SQLite sliding window rate limiter (`RateLimitMiddleware`) and endpoint admission protection. Run on-demand for live evaluations; never left unmetered 24/7.
- **Three-Tier Fallback Plan**: (1) Static exhibit & video walkthrough; (2) Clean-checkout local reproduction CLI (`python scripts/p18_benchmarks.py --all`); (3) Scheduled operator-assisted live verification session.
- **Evidence Provenance**: `LOCAL_EXECUTION` (11 tests in `tests/test_phase_p18_07_availability_plan.py`).

---

## 9. Artifacts and Tooling Summary

- **Benchmark & Reliability Module**: `src/stilldone/benchmarks.py`
  - Zero import-time logger mutations; fully restored scoped suppression.
  - `run_mission_benchmark()`: Monotonic per-step timing harness (PASS, BLOCKED, FAILED, NOT_RUN).
  - `measure_mcp_transport_latency()`: Loopback Streamable HTTP transport test (< 500ms threshold).
  - `estimate_aws_cost_per_mission()`: Pricing-backed cost estimation with explicit unestimated components.
  - `run_repeated_mission_reliability_test()`: Offline fixture reliability harness (validated iteration caps, timeout enforcement, dynamic predicate evaluation, qualification tracking).
- **CLI Runner**: `scripts/p18_benchmarks.py` (supports `--all`, `--p18-01`, `--p18-02`, `--p18-03`, `--p18-06`, `--reliability-iterations`, `--json`, `--output`).
- **Safety Architecture Document**: `docs/JUDGE_PERIOD_AVAILABILITY_PLAN.md` (`IMPLEMENTED / QA_PENDING`).
- **Test Suites**:
  - `tests/test_phase_p18_benchmarks.py`: 38 passing tests.
  - `tests/test_phase_p18_04_budget_rate_limits.py`: 21 passing tests.
  - `tests/test_phase_p18_05_quota_safety.py`: 15 passing tests.
  - `tests/test_phase_p18_06_reliability.py`: 16 passing tests.
  - `tests/test_phase_p18_07_availability_plan.py`: 11 passing tests.
  - **Batch P-18 Total**: **101 PASSED** tests.
- **Zero Personal Spend Law**: Maximum personal spend is strictly `$0.00`. Zero paid cloud resources activated.

