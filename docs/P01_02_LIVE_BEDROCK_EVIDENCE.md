# P-01.02 Live Bedrock Inference Evidence Record

**Phase**: P-01 Live Access, Zero-Cost & Platform Feasibility  
**Task**: P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Status**: **BLOCKED / NOT ACCEPTED** (Cycle 1: Account Verification Hold; Cycle 2: ValidationException / Operation Not Allowed)  
**Provenance**: `LIVE_AWS`

---

# Part I — First QA-Authorized Execution Cycle (Historical Truth)

**Observation Timestamp**: `2026-09-27T11:05:34+03:00`  
**Cycle Status**: `BLOCKED` (AWS New Account Verification In Progress)

### 1. Pre-Inference Credit Check (Cycle 1)
Immediately before discovery and inference, the live AWS Billing and Cost Management console (`/billing/home#/credits`) was verified:
- **Hackathon Promotional Credit**: `Amazon Devices Global Hackathon - Teams A4` remains **Active**.
- **Credit Balance**: Granted `$150.00`, Remaining `$150.00`, Used `$0.00` (Credit balance > `$0.00`).
- **Expiration Date**: `31.08.2028` (Conservative operational boundary).
- **Applicable Products**: Explicitly confirmed to cover `Amazon Bedrock Service` and `AmazonBedrockFoundationModels`.
- **Zero-Personal-Spend Invariant**: Preserved. Target remains strictly `$0.00`.

### 2. Authentication Surface & Security (Cycle 1)
- **Authentication Mechanism**: Official short-lived console-credential login flow (`aws login --profile stilldone-p01 --remote`).
- **AWS CLI Version**: `aws-cli/2.37.4 Python/3.14.6 Windows/10 exe/AMD64`.
- **Credentials Policy**: Zero static IAM access keys; zero root keys persisted; short-lived session cleaned up via `aws logout --profile stilldone-p01`.

### 3. Live Read-Only Foundation Model Discovery (Cycle 1)
Target Region: `us-east-1` (US East - N. Virginia).
Command:
```bash
aws bedrock list-foundation-models \
  --region us-east-1 \
  --profile stilldone-p01 \
  --by-provider amazon \
  --by-output-modality TEXT \
  --by-inference-type ON_DEMAND \
  --query "modelSummaries[?modelLifecycle.status=='ACTIVE'].{modelId:modelId,modelName:modelName,providerName:providerName,inferenceTypesSupported:inferenceTypesSupported,status:modelLifecycle.status}" \
  --output json
```
Discovered candidates: `amazon.nova-pro-v1:0`, `amazon.nova-2-sonic-v1:0`, `amazon.nova-lite-v1:0`, `amazon.nova-micro-v1:0`. Selected: `amazon.nova-micro-v1:0`.

### 4. Pre-Call Pricing & Cost Bounding (Cycle 1)
- Verified from official AWS Bedrock pricing: `$0.035 / 1M` input tokens, `$0.140 / 1M` output tokens.
- Planned prompt: `"Ping. Reply only with: pong"` (`maxTokens: 32`).
- Gross upper bound: `$0.00000553` $\ll \$0.01$.

### 5. Single Real Inference Attempt (Cycle 1)
Command:
```bash
aws bedrock-runtime converse \
  --region us-east-1 \
  --profile stilldone-p01 \
  --model-id "amazon.nova-micro-v1:0" \
  --messages "file://messages.json" \
  --inference-config "file://inference_config.json" \
  --output json
```
- **Exit Status**: Failed (Exit code `1`).
- **Error Class**: `AccessDeniedException`.
- **Sanitized Error Message**:
  > `An error occurred (AccessDeniedException) when calling the Converse operation: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification[at]amazon.com. We appreciate your patience.`
- **Usage Metadata**: `inputTokens`, `outputTokens`, `totalTokens`, `stopReason`: `NOT_RETURNED / NOT_AVAILABLE`.
- **Constitutional Enforcement**: Exactly 1 attempt consumed. Zero retries. Task remained `BLOCKED`.

### 6. Post-Attempt Billing Truth (Cycle 1)
- `Post-Call Billing/Credit Delta`: `NOT_OBSERVED / UNKNOWN`.
- `Actual Billed Request Cost`: `NOT_OBSERVED / UNKNOWN`.
- `Personal-Spend Delta`: `NOT_OBSERVED / UNKNOWN`.
- `Planned Successful-Call Gross Upper Bound`: `$0.00000553`.
- `AWS Resource Mutations`: `NONE`.

---

# Part II — Second QA-Authorized Execution Cycle

**Observation Timestamp**: `2026-09-27T13:19:20+03:00` (Elapsed time since Cycle 1 error: > 2 hours)  
**Authorization Boundary**: Independent QA explicitly authorized ONE NEW bounded P-01.02 execution cycle. (This was not an automatic retry, but a fresh QA-authorized execution cycle of the same canonical task).  
**Cycle Status**: **`BLOCKED / NOT ACCEPTED`** (ValidationException: Operation not allowed)

### 1. Fresh Credit-Safety Check (Cycle 2)
- Hackathon credit `Amazon Devices Global Hackathon - Teams A4` verified Active with `$150.00` remaining.
- Amazon Bedrock remains covered under Applicable products.
- Zero personal spend invariant preserved (`$0.00`).

### 2. Authentication Surface & Security (Cycle 2)
- Re-authenticated via browser-backed short-lived console session: `aws login --profile stilldone-p01 --remote`.
- Zero long-lived IAM or root keys created.
- Session immediately terminated and cached credentials wiped after the attempt via `aws logout --profile stilldone-p01`.
- Zero secrets or identity identifiers committed.

### 3. Fresh Live Read-Only Model Discovery (Cycle 2)
Target Region: `us-east-1`.
Command executed:
```bash
aws bedrock list-foundation-models \
  --region us-east-1 \
  --profile stilldone-p01 \
  --by-provider amazon \
  --by-output-modality TEXT \
  --by-inference-type ON_DEMAND \
  --query "modelSummaries[?modelLifecycle.status=='ACTIVE'].{modelId:modelId,modelName:modelName,providerName:providerName,inferenceTypesSupported:inferenceTypesSupported,status:modelLifecycle.status}" \
  --output json
```

Live discovered active models in `us-east-1`:
| Model ID | Model Name | Provider | Supported Inference Types | Status |
|---|---|---|---|---|
| `amazon.nova-pro-v1:0` | Nova Pro | Amazon | `ON_DEMAND`, `INFERENCE_PROFILE` | `ACTIVE` |
| `amazon.nova-2-sonic-v1:0` | Nova 2 Sonic | Amazon | `ON_DEMAND` | `ACTIVE` |
| `amazon.nova-lite-v1:0` | Nova Lite | Amazon | `ON_DEMAND`, `INFERENCE_PROFILE` | `ACTIVE` |
| `amazon.nova-micro-v1:0` | Nova Micro | Amazon | `ON_DEMAND`, `INFERENCE_PROFILE` | `ACTIVE` |

- **Selected Model ID**: `amazon.nova-micro-v1:0` (Nova Micro) maintained based on fresh discovery (Amazon-provider, text generation, ACTIVE, ON_DEMAND, Converse support, lowest cost).

### 4. Current Official Pricing & Cost Bounding (Cycle 2)
Verified against official [AWS Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/):
- Input: `$0.035 / 1M` tokens (`$0.000035 / 1K`).
- Output: `$0.140 / 1M` tokens (`$0.000140 / 1K`).
- Prompt: `"Ping. Reply only with: pong"` (~8 input tokens, bounded at `<= 30`).
- Bound: `maxTokens: 32`.
- Pre-call planned gross upper bound: `$0.00000553` $\le \$0.01$.

### 5. The Single Real Inference Attempt (Cycle 2)
Execution parameters:
- **API Operation**: `bedrock-runtime converse`
- **Region**: `us-east-1`
- **Model ID**: `amazon.nova-micro-v1:0`
- **Prompt**: `"Ping. Reply only with: pong"`
- **Generation Bound**: `maxTokens: 32`
- **Tools / Guardrails / Agents / KBs**: None
- **Number of Attempts in This Cycle**: **EXACTLY 1** (Attempt count = 1 in Cycle 2; Lifetime P-01.02 attempts = 2).

Command executed:
```bash
aws bedrock-runtime converse \
  --region us-east-1 \
  --profile stilldone-p01 \
  --model-id "amazon.nova-micro-v1:0" \
  --messages "file://messages.json" \
  --inference-config "file://inference_config.json" \
  --output json
```

### Result & Error Observation (Cycle 2)
- **Exit Status**: Failed (Exit code `1`).
- **Error Class**: `ValidationException`.
- **Sanitized Error Message**:
  > `An error occurred (ValidationException) when calling the Converse operation: Operation not allowed`
- **Observation Analysis**:
  - The previous Cycle 1 error (`AccessDeniedException: Your account is currently being verified`) is **no longer present**, confirming the initial new-account verification hold has cleared.
  - However, AWS Bedrock returned `ValidationException: Operation not allowed` on the direct invocation of `amazon.nova-micro-v1:0`.
  - In Bedrock, `Operation not allowed` typically indicates that model access has not been granted/requested in the Amazon Bedrock Console (Bedrock -> Model access), or requires an Amazon Bedrock inference profile ARN rather than a raw foundation model ID for cross-region invocation.
- **Usage & Token Metadata**:
  - `inputTokens`: `NOT_RETURNED / NOT_AVAILABLE`
  - `outputTokens`: `NOT_RETURNED / NOT_AVAILABLE`
  - `totalTokens`: `NOT_RETURNED / NOT_AVAILABLE`
  - `stopReason`: `NOT_RETURNED / NOT_AVAILABLE`
  - The request was rejected by AWS before model generation occurred. No token usage metadata was returned.

### Constitutional Strict Enforcement (No-Retry Law)
- **Zero Retries Performed**: Exactly 1 attempt consumed in Cycle 2.
- **No Second Model Attempted**: Did not fallback to Titan, Nova Lite, or any other model.
- **No Second Region Attempted**: Did not fallback to other regions.
- **No Provider Fallback**: No third-party or mock provider invoked.
- **No Simulation**: Recorded honestly as real live failure. Task P-01.02 is **NOT** marked DONE.

### 6. Post-Attempt Billing & Resource Delta (Cycle 2)
- **Post-Call Billing/Credit Delta**: `NOT_OBSERVED / UNKNOWN` (No post-call billing read was performed at checkpoint; do not infer "$0 billed" without billing evidence).
- **Actual Billed Request Cost**: `NOT_OBSERVED / UNKNOWN`.
- **Personal-Spend Delta**: `NOT_OBSERVED / UNKNOWN`.
- **Planned Successful-Call Gross Upper Bound**: `$0.00000553`.
- **AWS Resource Mutations**: `NONE`. Zero cloud resources created.

---

## 7. Cumulative Lifecycle Summary & Next Safe Action

| Cycle | Timestamp | Error Class | Observed Error Message | Task State |
|---|---|---|---|---|
| **Cycle 1** | `2026-09-27T11:05:34+03:00` | `AccessDeniedException` | `Your account is currently being verified. Verification normally takes less than 2 hours.` | `BLOCKED` |
| **Cycle 2** | `2026-09-27T13:19:20+03:00` | `ValidationException` | `Operation not allowed` | `BLOCKED / NOT ACCEPTED` |

- **Cumulative P-01.02 Attempts**: `2` (Cycle 1: 1 attempt, Cycle 2: 1 attempt).
- **Current Canonical Status**: **`BLOCKED / NOT ACCEPTED`**.
- **Task P-01.03 Status**: **`NOT STARTED`** (Strictly locked; must not start before P-01.02 achieves live model response and independent QA PASS).
- **Next Safe Action**:
  Independent QA evaluation and authorization required before any future bounded execution cycle. Operator/QA investigation is required on why AWS Bedrock returned `ValidationException: Operation not allowed` for `amazon.nova-micro-v1:0` (e.g. checking Bedrock Console -> Model Access for Amazon Nova models, or inspecting inference profile requirements).
- **Retry Authority**:
  A subsequent execution cycle of P-01.02 is NOT automatically authorized. It requires fresh independent QA authorization after investigating the model access prerequisite.
