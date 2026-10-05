# P-07.06 Live Bedrock Strands Planner Execution and Control Proof

**Phase**: P-07 Natural-Language Mission Planning  
**Task**: P-07.06 — Prove model is necessary for natural-language mission compilation in the live path  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Status**: **EXECUTED — awaiting independent QA review**  
**Provenance**: `LIVE_AWS`  

---

## 1. Canonical Closure Live Observation (Fail-Closed Exact-SHA Bound)

This canonical closure record documents the live Bedrock inference and Strands-compatible negative control executed from the exact committed source tree **COMMIT C** (`ca56e54e2cbe70fa004523c5e750af9bc3f527b9`) following explicit operator approval, positive `ASIA` credential enforcement, clean-tree verification, and fail-closed SHA parity gates.

### 1.1 Execution Binding & Authority Gate
- **Execution Source SHA**: `ca56e54e2cbe70fa004523c5e750af9bc3f527b9` (Commit C)
- **Pre-Execution Git Integrity Gates**:
  - `clean_tree_gate`: **PASS** (`git status --porcelain` verified empty prior to credential resolution)
  - `head_origin_parity`: **PASS** (`HEAD == origin/main == ca56e54e2cbe70fa004523c5e750af9bc3f527b9`)
  - `expected_sha_parity`: **PASS** (`HEAD == --expected-source-sha`)
- **Operator Live Approval**: Explicitly granted by operator prior to inference
  - `authorized_before_inference`: `true` (enforced fail-closed; zero AWS calls without validated reference)
  - `operator_approval_ref`: `"APPROVE P-07.06 FINAL REPAIR LIVE BEDROCK INFERENCE"`
- **Credential Truth**: Temporary session credentials strictly enforced
  - `credential_mode`: `temporary_session`
  - `session_token_present`: `true` (`AWS_SESSION_TOKEN` active)
  - `key_prefix`: `ASIA` (positively enforced; static `AKIA` or arbitrary non-`ASIA` keys fail closed)
  - `expiration`: `SESSION_ACTIVE`
  - Zero secrets logged, printed, or persisted

### 1.2 Model & Runtime Configuration
- **Model ID**: `amazon.nova-micro-v1:0` (strictly canonical, zero fallback)
- **Region**: `us-east-1` (strictly canonical, zero fallback)
- **Inference Configuration**:
  - `temperature`: `0.00001` (deterministic sampling)
  - `max_tokens`: `2048`
  - `total_max_attempts`: `1` (strictly zero retries)
  - `tools`: `[]` (empty list; zero tools configured on Strands Agent)
  - `turns`: `1` (strict single-turn limit)
  - `streaming`: `False`
- **Execution Latency & Timestamps**:
  - Start UTC: `2026-10-05T08:57:19.877288+00:00`
  - Completion UTC: `2026-10-05T08:57:23.340260+00:00`
  - Total Duration: `3.463 seconds`
- **Observed stop_reason**: `end_turn`

### 1.3 Dependency Versions (Isolated Planner Runtime)
- `strands-agents`: `1.57.2`
- `boto3`: `1.43.108`
- `botocore`: `1.43.108`
- `transitive mcp`: `2.1.1` (< 2.2.0 compatibility lock in `runtimes/strands_planner`)
- `root mcp`: `2.2.0` (in untouched root runtime `pyproject.toml`)

### 1.4 Input Contract & Validated Output Proposal
- **Input Mission Contract**:
  - `mission_id`: `bd9d9833-0533-4c87-a556-f1d9ac9b8792`
  - `intent`: `"Check today's calendar events and create a task to review project roadmap"`
- **Deterministically Validated CandidatePlanProposal**:
  Raw Bedrock output strictly crossed the mandatory StillDone deterministic boundary (`parse_candidate_plan_for_input`):
  - `steps_count`: `2`
  - **Proposed Step 1**:
    - `action_type`: `calendar.read`
    - `target_ref`: `calendar_event`
    - `parameters`: `{}`
  - **Proposed Step 2**:
    - `action_type`: `task.create`
    - `target_ref`: `task_list`
    - `parameters`: `{"title": "Review project roadmap"}`
  - `mission_id`: bound strictly to `bd9d9833-0533-4c87-a556-f1d9ac9b8792` (zero cross-mission leakage)
- **Runtime Metadata**:
  - 18 canonical stored metadata fields attached to `StrandsPlannerResult.metadata`
  - `meta.tools_count`: `0` (derived property)

### 1.5 Tool & Authority Boundary Truth
- **Tool Observation Truth**:
  - Production `plan_with_strands` source constructs Strands `Agent` with `tools=[]`
  - P-07.03 unit tests independently enforce empty tool registry
  - Live result runtime metadata reports `tools_count == 0`
  - External actions executed: `0`
  - External tools executed: `0`
- **Authority Invariants (Evaluated Assertions)**:
  - Zero ActionId authority: `not hasattr(result.plan, "action_id")` -> **PASS**
  - Zero EvidenceId authority: `not hasattr(result.plan, "evidence_id")` -> **PASS**
  - Zero ApprovalGrant authority: `not hasattr(result.plan, "approval_grant")` -> **PASS**
  - Zero VERIFIED state promotion: `not hasattr(result.plan, "verified")` -> **PASS**
  - Zero READY state promotion: `not hasattr(result.plan, "ready")` -> **PASS**

### 1.6 Compatible Negative Control Proof (Model Necessity)
- **Control Model**: `StrandsCompatibleNonProducingModel` inheriting directly from `strands.models.model.Model`
- **Orchestration Contract**: Normal Strands stream orchestration entered (`stream_call_count == 1`)
- **Network Call Count**: Strictly `0` (zero network calls, zero AWS calls)
- **Deterministic Pipeline Result**: Pipeline fails closed immediately with specific bounded exception `StrandsEmptyResponseError`
- **Zero CandidatePlan**: Exactly zero candidate plans produced without model inference

### 1.7 Cost Truth & Billing Observation Separation
- **Live Call Count**: Exactly `1` (zero retries, zero fallback, zero secondary calls)
- **Proof Runtime Observations (Facts generated by Bedrock proof script)**:
  - `underlying_service_cost`: `"NOT_DETERMINISTICALLY_OBSERVED"`
  - `promotional_credit_status`: `"NOT_OBSERVED_BY_THIS_RUNTIME"`
  - `personal_spend_delta`: `"NOT_OBSERVED_BY_THIS_RUNTIME"`
- **Separate Operator / Account Observation (External Truth)**:
  - Operator AWS Account status: Active AWS Hackathon promotional credits confirmed ($0.00 personal spend).
  - Out-of-pocket charges: `$0.00`.
  - Billing boundary: No paid subscriptions, no unmetered endpoints, zero personal charges.
  - *Distinction*: The Bedrock proof script does not own billing truth and therefore emits `NOT_OBSERVED_BY_THIS_RUNTIME`. External zero-spend status is established independently by account/operator verification.

---

## 2. Prior Recorded Live Observations (Historical Reference)

### 2.1 Commit A Observation (`665c4388942ceb43c87335352bd99674dd6a9f85`)
- **Execution Source SHA**: `665c4388942ceb43c87335352bd99674dd6a9f85`
- **Execution Timestamp (UTC)**: `2026-10-05T07:40:34.251921+00:00`
- **Mission ID**: `c940f9a8-2c6f-4554-9ec5-be5e48d8c5eb`
- **Model**: `amazon.nova-micro-v1:0` (`us-east-1`)
- **Status**: Historical evidence superseded by Section 1 fail-closed gate hardening (Commit C).

### 2.2 Initial Bootstrap Observation (`fdc13f03bb76b97e44451294935df83d01f7d3dc`)
- **Historical Execution SHA**: `fdc13f03bb76b97e44451294935df83d01f7d3dc`
- **Execution Timestamp (UTC)**: `2026-10-04T09:35:53.122878+00:00`
- **Mission ID**: `cb36b5e8-b966-47f7-bb30-69e18b7db56e`
- **Model**: `amazon.nova-micro-v1:0` (`us-east-1`)
- **Status**: Historical recorded development evidence.
