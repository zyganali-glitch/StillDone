# P-01.03 Live Strands Agent Execution Evidence Record

**Phase**: P-01 Live Access, Zero-Cost & Platform Feasibility  
**Task**: P-01.03 — Prove minimal real Strands agent execution against the selected Bedrock model  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Status**: **DONE — awaiting independent QA PASS**  
**Provenance**: `LIVE_AWS + REAL_STRANDS_RUNTIME`

---

## 1. Official Strands Agents Documentation & Architectural Reality

Facts verified against current official external sources on `2026-09-28`:

| Dimension | Source Authority | Official URL / Reference | Verified Observation |
|---|---|---|---|
| **Core Framework** | Strands Agents Python SDK | `https://strandsagents.com` | Official open-source, model-agnostic agent orchestration SDK. Primary package on PyPI is `strands-agents`. |
| **Bedrock Model Provider** | Strands Bedrock Provider | `https://strandsagents.com/models/bedrock` | `from strands.models.bedrock import BedrockModel`. Native integration with Amazon Bedrock via `boto3`. Supports `model_id`, `boto_session`, `streaming`, `max_tokens`, `temperature`. |
| **Agent API** | Strands Agent Class | `from strands import Agent` | Minimal agent initialized with `Agent(model=model, tools=[])`. Callable directly via `agent(prompt)` returning structured `AgentResult`. |
| **Dependency Boundary** | Ephemeral Isolation | Zero permanent dependencies added | Feasibility invocation executed ephemerally via `uv run --with strands-agents --with "botocore[crt]"`. `pyproject.toml` and `uv.lock` remain unmodified. |

---

## 2. Runtime Environment & Package Provenance

Exact versions resolved and executed during this feasibility test:
- **`strands-agents`**: `1.57.1`
- **`boto3`**: `1.43.103`
- **`botocore`**: `1.43.103`
- **`awscrt`**: `0.36.0` (required by `botocore` for loading credentials from `aws login` profile)
- **Python**: `3.13.5 (tags/v3.13.5:6cb20a2, Jun 11 2025, 16:15:46) [MSC v.1943 64 bit (AMD64)]`
- **Operating System**: Windows 10 / Windows 11 AMD64

---

## 3. Short-Lived AWS Profile Authentication

- **Authentication Mechanism**: Official console-credential login flow (`aws login --profile stilldone-p01 --remote`).
- **Profile Name**: `stilldone-p01`
- **Credentials Policy**: Zero static IAM access keys; zero root keys; short-lived session loaded via `boto3.Session(profile_name="stilldone-p01", region_name="us-east-1")`.
- **Session Cleanup**: `aws logout --profile stilldone-p01` executed immediately after the single test; cached credentials deleted.

---

## 4. Mandatory Live Preflight Gate

Immediately before configuring the Strands runtime, exactly one read-only Bedrock availability check was performed:

```bash
aws bedrock get-foundation-model-availability \
  --region us-east-1 \
  --profile stilldone-p01 \
  --model-id amazon.nova-micro-v1:0 \
  --query "{modelId:modelId,authorizationStatus:authorizationStatus,agreementStatus:agreementAvailability.status,agreementError:agreementAvailability.errorMessage,entitlementAvailability:entitlementAvailability,regionAvailability:regionAvailability}" \
  --output json
```

Returned JSON:
```json
{
    "modelId": "amazon.nova-micro-v1",
    "authorizationStatus": "AUTHORIZED",
    "agreementStatus": "AVAILABLE",
    "agreementError": null,
    "entitlementAvailability": "AVAILABLE",
    "regionAvailability": "AVAILABLE"
}
```

Pre-inference gate evaluation:
- `authorizationStatus`: `AUTHORIZED` (PASS)
- `agreementStatus`: `AVAILABLE` (PASS)
- `agreementError`: `null` (PASS)
- `entitlementAvailability`: `AVAILABLE` (PASS)
- `regionAvailability`: `AVAILABLE` (PASS)
- **Gate Decision**: `ALL CONDITIONS SATISFIED — STRANDS EXECUTION AUTHORIZED`.

---

## 5. Pricing Basis & Pre-Call Gross Cost Bounding

- **Model ID**: `amazon.nova-micro-v1:0` (Amazon Nova Micro)
- **Provider**: `Amazon`
- **Region**: `us-east-1`
- **Official On-Demand Pricing**:
  - Input tokens: `$0.035 / 1,000,000` tokens
  - Output tokens: `$0.140 / 1,000,000` tokens
- **Planned Generation Bound**: `max_tokens: 32`
- **Planned Prompt Bound**: $\le 30$ input tokens
- **Conservative Pre-Call Planned Gross Upper Bound**: `$0.00000553 \le \$0.01` (strictly preserved)

---

## 6. Exact Minimal Agent Configuration

- **BedrockModel**:
  ```python
  session = boto3.Session(profile_name="stilldone-p01", region_name="us-east-1")
  model = BedrockModel(
      boto_session=session,
      model_id="amazon.nova-micro-v1:0",
      streaming=False,
      max_tokens=32,
      temperature=0.0,
  )
  ```
- **Agent**:
  ```python
  agent = Agent(
      model=model,
      tools=[],
      load_tools_from_directory=False,
  )
  ```
- **Tools**: Strictly `NONE` (`tools=[]`, zero default tools injected, zero MCP, zero shell/file/network tools).
- **Streaming Mode**: `False` (non-streaming Converse API path).
- **Temperature**: `0.0` (lowest deterministic value supported by Nova Micro / Strands).

---

## 7. The Single Real Strands Invocation

- **Number of Attempts**: **EXACTLY 1** (Attempt count = 1).
- **Synthetic Prompt**: `"Reply only with: STRANDS_OK"`
- **Zero Retries Performed**: No second attempt, no fallback model, no alternate region, no fixture fallback.

---

## 8. Live Response & Structured Event/Result Capture

- **Observation Timestamp**: `2026-09-28T17:07:30.469189+00:00`
- **Exit Status**: Success (Exit code `0`).
- **Exact Returned Model Text**: `"STRANDS_OK"`
- **Stop Reason**: `"end_turn"`
- **Cycle Count**: `1`
- **Tools Invoked**: `[]` (None; verified from `metrics.tool_metrics`)
- **Usage Metadata**:
  - `inputTokens`: `8`
  - `outputTokens`: `5`
  - `totalTokens`: `13`
- **Latency Metadata**:
  - `wallClockElapsed`: `1179 ms`
  - `modelLatencyMs`: `264 ms`
  - `timeToFirstByteMs`: `1174 ms`
- **Tracking ID**: `"c8b738aa-5acf-4422-84b5-c8d0d85edda9"`
- **Exact Structured `AgentResult.to_dict()` Capture**:
```json
{
  "type": "agent_result",
  "message": {
    "role": "assistant",
    "content": [
      {
        "text": "STRANDS_OK"
      }
    ],
    "metadata": {
      "usage": {
        "inputTokens": 8,
        "outputTokens": 5,
        "totalTokens": 13
      },
      "metrics": {
        "latencyMs": 264,
        "timeToFirstByteMs": 1174
      }
    },
    "tracking_id": "c8b738aa-5acf-4422-84b5-c8d0d85edda9"
  },
  "stop_reason": "end_turn",
  "checkpoint": null
}
```

---

## 9. Post-Attempt Billing Truth

- **Post-Call Billing/Credit Delta**: `NOT_OBSERVED / UNKNOWN` (No post-call Billing console read was performed during this automated CLI execution checkpoint; do not infer "$0 billed" without direct billing evidence).
- **Actual Billed Request Cost**: `NOT_OBSERVED / UNKNOWN`.
- **Personal-Spend Delta**: `NOT_OBSERVED / UNKNOWN`.
- **Usage-Derived Estimated Gross Request Cost from Observed Usage**:
  - Input tokens: $8 \times (\$0.035 / 1,000,000) = \$0.00000028$
  - Output tokens: $5 \times (\$0.140 / 1,000,000) = \$0.00000070$
  - Total usage-derived estimated gross cost: $\approx \$0.00000098$ ($\approx 9.8 \times 10^{-7}$ USD, well below the $\$0.01$ threshold).
  - Target personal spend remains strictly `$0.00`.

---

## 10. Cleanup & Constitutional Discipline

- **AWS Logout**: `aws logout --profile stilldone-p01` executed immediately after the call (Exit code 0: *"Removed cached login credentials for profile 'stilldone-p01'"*).
- **Ephemeral Script Cleanup**: Temporary execution script outside repository deleted immediately.
- **AWS Resource Mutations**: `0` (Zero cloud resources created, modified, or deleted).
- **Second Attempt**: `NOT_RUN / NOT_AUTHORIZED`.
- **Task P-01.04**: `NOT_STARTED / LOCKED`.

---

## 11. Lifecycle Summary & Next Safe Action

| Metric / Dimension | Observed Value |
|---|---|
| **Task** | `P-01.03 — Prove minimal real Strands agent execution against the selected Bedrock model` |
| **Status** | **`DONE — awaiting independent QA PASS`** |
| **Strands Version** | `strands-agents 1.57.1` |
| **Boto3 / Botocore** | `1.43.103` (`awscrt 0.36.0`) |
| **Model ID** | `amazon.nova-micro-v1:0` |
| **Region** | `us-east-1` |
| **Tools** | `NONE` (`tools=[]`) |
| **Streaming** | `False` |
| **Invocations** | Exactly `1` |
| **Model Output** | `"STRANDS_OK"` |
| **Stop Reason** | `"end_turn"` |
| **Total Tokens** | `13` (input: 8, output: 5) |
| **Latency** | `1179 ms` wall clock (`264 ms` model latency) |
| **Provenance** | `LIVE_AWS + REAL_STRANDS_RUNTIME` |

- **Next Exact Task after Independent QA PASS**:
  `P-01.04 — Prove minimal AgentCore runtime/deployment path or formally reject it with evidence`
- **Lock**: P-01.04 remains strictly `PENDING / LOCKED` until independent QA PASS is awarded.
