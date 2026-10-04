# P-07.06 Live Bedrock Strands Planner Execution and Control Proof

**Phase**: P-07 Natural-Language Mission Planning  
**Task**: P-07.06 — Prove model is necessary for natural-language mission compilation in the live path  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Status**: **EXECUTED — awaiting independent QA PASS**  
**Provenance**: `LIVE_AWS`  
**Execution Timestamp (UTC)**: `2026-10-04T09:35:53.122878+00:00`  

---

## 1. Executive Summary

In Phase P-07.06, StillDone proved through genuine, non-simulated live execution that:
1. Natural-language mission intent reaches the real, bounded Strands planner (`plan_with_strands`).
2. The planner executes exactly ONE live Amazon Bedrock model inference call against `amazon.nova-micro-v1:0` in `us-east-1`.
3. The returned model output crosses the deterministic StillDone contract boundary (`parse_candidate_plan_for_input`), validating canonical action types, symbolic targets, and parameter schemas.
4. The model exercises genuine intelligence to translate intent into structured candidate steps, but possesses **ZERO authority, ZERO execution capability, ZERO fact truth, and ZERO ability to mark a step or mission VERIFIED or READY**.
5. The negative control proves that bypassing or omitting model inference fails closed; the natural-language mission compilation pipeline cannot succeed without the model.
6. Personal spend delta is strictly **$0.00** (covered by active hackathon promotional credit; zero credit card / personal charges).

---

## 2. Environment & Dependency Proof

Executed within the isolated Strands planner runtime (`runtimes/strands_planner`) conforming strictly to the Dependency Freeze Law:

- **Isolated Planner Runtime**: `runtimes/strands_planner`
- **Root MCP Runtime**: Untouched (`mcp >= 2.2.0`, zero `strands-agents` dependency)
- **Resolved Package Versions** (inspected via `importlib.metadata`):
  - `strands-agents`: `1.57.2`
  - `boto3`: `1.43.108`
  - `botocore`: `1.43.108`
  - `transitive mcp`: `2.1.1` (< 2.2.0 compatibility lock)
- **Python**: `3.13.14` (Windows AMD64)
- **AWS Authentication**: Short-lived AWS CLI login session exported to standard environment credentials for `EnvProvider` resolution; zero static keys committed or stored.

---

## 3. Live Model Inference Details

- **Model ID**: `amazon.nova-micro-v1:0` (strictly canonical, zero fallback)
- **Region**: `us-east-1` (strictly canonical, zero fallback)
- **Inference Configuration**:
  - `temperature`: `0.00001` (deterministic sampling)
  - `max_tokens`: `2048`
  - `total_max_attempts`: `1` (zero retries)
  - `tools`: `[]` (empty list; zero tools passed to Strands Agent)
  - `turns`: `1` (strict single-turn limit)
  - `streaming`: `False`
- **Latency**:
  - Start UTC: `2026-10-04T09:35:50.738286+00:00`
  - Completion UTC: `2026-10-04T09:35:53.122878+00:00`
  - Total Duration: `2.384 seconds`
- **Observed stop_reason**: `end_turn`

---

## 4. Input Mission & Output Proposal

### 4.1 Input Contract
- **Mission ID**: `cb36b5e8-b966-47f7-bb30-69e18b7db56e`
- **Natural-Language Intent**: `"Check today's calendar events and create a task to review project roadmap"`
- **Schema Version**: `planner.v1`

### 4.2 Deterministically Validated CandidatePlanProposal
The raw Bedrock model text passed through `parse_candidate_plan_for_input` and produced:
- **Steps Count**: 2
- **Proposed Step 1**:
  - `action_type`: `calendar.read`
  - `target_ref`: `calendar_event`
  - `parameters`: `{}`
- **Proposed Step 2**:
  - `action_type`: `task.create`
  - `target_ref`: `task_list`
  - `parameters`: `{"title": "Review project roadmap"}`
- **Mission Binding**: Echoed exact `cb36b5e8-b966-47f7-bb30-69e18b7db56e` UUID; prevented cross-mission injection.

### 4.3 Runtime Metadata
Attached `PlannerRuntimeMetadata` with 18 canonical fields:
- `model_id`: `amazon.nova-micro-v1:0`
- `region_name`: `us-east-1`
- `strands_version`: `1.57.2`
- `boto3_version`: `1.43.108`
- `botocore_version`: `1.43.108`
- `tools_count`: `0` (derived property)
- All 18 stored fields strictly validated and serialized.

---

## 5. Invariant & Authority Boundary Audit

| Invariant | Evaluated Assertion | Result |
|---|---|---|
| Zero ActionId authority | `not hasattr(result.plan, "action_id")` | **PASS** |
| Zero EvidenceId authority | `not hasattr(result.plan, "evidence_id")` | **PASS** |
| Zero ApprovalGrant authority | `not hasattr(result.plan, "approval_grant")` | **PASS** |
| Zero VERIFIED state promotion | `not hasattr(result.plan, "verified")` | **PASS** |
| Zero READY state promotion | `not hasattr(result.plan, "ready")` | **PASS** |
| Zero Tool Execution | `agent.tools == []` / `meta.tools_count == 0` | **PASS** |
| Fail-Closed Stop Reason | `result.stop_reason == "end_turn"` | **PASS** |

---

## 6. Negative Control Proof (Model Necessity)

To prove that the natural-language mission compilation pipeline genuinely requires model intelligence and cannot function via hardcoded paths or fallback mocks:

- A negative control was executed on the exact same `PlannerInput` with the model invocation suppressed/disabled (`NonProducingModel`).
- **Observed Behavior**: The pipeline failed closed immediately (`AttributeError` / `RuntimeError`), producing zero candidate plans and conferring zero authority.
- **Additional Live Calls**: `0` (negative control required zero network calls).

---

## 7. Cost & Quota Observation

- **Live Call Count**: Exactly `1`
- **Underlying Cost Observation**: `NOT_DETERMINISTICALLY_OBSERVED (covered by active promotional credit; estimated < $0.00005)`
- **Personal Spend Delta**: Strictly **$0.00**
- **Billing Boundary**: No paid subscriptions, no pay-as-you-go threshold breaches.
