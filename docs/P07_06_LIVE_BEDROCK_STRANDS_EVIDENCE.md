# P-07.06 Live Bedrock Strands Planner Execution and Control Proof

**Phase**: P-07 Natural-Language Mission Planning  
**Task**: P-07.06 — Prove model is necessary for natural-language mission compilation in the live path  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Status**: **EXECUTED — awaiting independent QA review**
**Provenance**: `LIVE_AWS`  

---

## 1. Canonical Closure Live Observation (Exact-SHA Bound)

This canonical closure record documents the live Bedrock inference and Strands-compatible negative control executed from the exact committed source tree **COMMIT A** (`665c4388942ceb43c87335352bd99674dd6a9f85`) following explicit operator approval and hard gate verification.

### 1.1 Execution Binding & Authority Gate
- **Execution Source SHA**: `665c4388942ceb43c87335352bd99674dd6a9f85` (independently verified identical to `origin/main` at execution)
- **Operator Live Approval**: Explicitly granted by operator prior to inference
  - `authorized_before_inference`: `true`
  - `operator_approval_ref`: `"APPROVE P-07.06 REPAIR LIVE BEDROCK INFERENCE"`
- **Credential Mode**: Temporary session credentials
  - `session_token_present`: `true` (`AWS_SESSION_TOKEN` active)
  - `key_prefix`: `ASIA` (STS-issued short-lived session key; long-lived `AKIA` keys strictly forbidden and rejected)
  - `expiration`: `SESSION_ACTIVE`

### 1.2 Model & Runtime Configuration
- **Model ID**: `amazon.nova-micro-v1:0` (strictly canonical, zero fallback)
- **Region**: `us-east-1` (strictly canonical, zero fallback)
- **Inference Configuration**:
  - `temperature`: `0.00001` (deterministic sampling)
  - `max_tokens`: `2048`
  - `total_max_attempts`: `1` (zero retries)
  - `tools`: `[]` (empty list; zero tools passed to Strands Agent)
  - `turns`: `1` (strict single-turn limit)
  - `streaming`: `False`
- **Execution Latency & Timestamps**:
  - Start UTC: `2026-10-05T07:40:34.251921+00:00`
  - Completion UTC: `2026-10-05T07:40:38.336828+00:00`
  - Total Duration: `4.085 seconds`
- **Observed stop_reason**: `end_turn`

### 1.3 Dependency Versions (Isolated Planner Runtime)
- `strands-agents`: `1.57.2`
- `boto3`: `1.43.108`
- `botocore`: `1.43.108`
- `transitive mcp`: `2.1.1` (< 2.2.0 compatibility lock in `runtimes/strands_planner`)
- `root mcp`: `2.2.0` (in untouched root runtime `pyproject.toml`)

### 1.4 Input Contract & Validated Output Proposal
- **Input Mission Contract**:
  - `mission_id`: `c940f9a8-2c6f-4554-9ec5-be5e48d8c5eb`
  - `intent`: `"Check today's calendar events and create a task to review project roadmap"`
- **Deterministically Validated CandidatePlanProposal**:
  Raw Bedrock output crossed the mandatory StillDone deterministic boundary (`parse_candidate_plan_for_input`):
  - `steps_count`: `2`
  - **Proposed Step 1**:
    - `action_type`: `calendar.read`
    - `target_ref`: `calendar_event`
    - `parameters`: `{}`
  - **Proposed Step 2**:
    - `action_type`: `task.create`
    - `target_ref`: `task_list`
    - `parameters`: `{"title": "Review project roadmap"}`
  - `mission_id`: bound strictly to `c940f9a8-2c6f-4554-9ec5-be5e48d8c5eb` (zero cross-mission leakage)
- **Runtime Metadata**:
  - 18 canonical stored metadata fields attached to `StrandsPlannerResult.metadata`
  - `meta.tools_count`: `0` (derived property)

### 1.5 Tool & Authority Boundary Truth
- **Tool Observation Truth**:
  - Production `plan_with_strands` source constructs Strands `Agent` with `tools=[]`
  - Accepted P-07.03 unit tests independently enforce empty tool registry
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

### 1.7 Cost Truth & Zero Personal Spend
- **Live Call Count**: Exactly `1` (no retries, no secondary calls)
- **Underlying Service Cost**: `NOT_DETERMINISTICALLY_OBSERVED` (covered by active hackathon promotional credit)
- **Promotional Credit Status**: `ACTIVE / CONFIRMED`
- **Personal Out-of-Pocket Spend**: Strictly **$0.00**
- **Billing Boundary**: No paid subscriptions, no unmetered endpoints, zero personal charges.

---

## 2. Prior Recorded Live Observation (Historical Reference)

The prior recorded live run (`fdc13f03bb76b97e44451294935df83d01f7d3dc` era) is preserved as historical development evidence, but was superseded by Section 1 because it lacked exact-SHA source binding and used a non-subclassed control object:

- **Historical Execution SHA**: `fdc13f03bb76b97e44451294935df83d01f7d3dc`
- **Execution Timestamp (UTC)**: `2026-10-04T09:35:53.122878+00:00`
- **Mission ID**: `cb36b5e8-b966-47f7-bb30-69e18b7db56e`
- **Model**: `amazon.nova-micro-v1:0` (`us-east-1`)
- **Status**: Historical recorded evidence superseded by Section 1 canonical closure.
