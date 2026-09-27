# P-01.02 Live Bedrock Inference Evidence Record

**Phase**: P-01 Live Access, Zero-Cost & Platform Feasibility  
**Task**: P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt  
**Observation Timestamp**: `2026-09-27T11:05:34+03:00`  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Status**: **BLOCKED / NOT ACCEPTED** (AWS New Account Verification In Progress)  
**Provenance**: `LIVE_AWS`

---

## 1. Pre-Inference Credit Check (Step 4)

Immediately before discovery and inference, the live AWS Billing and Cost Management console (`/billing/home#/credits`) was verified:
- **Hackathon Promotional Credit**: `Amazon Devices Global Hackathon - Teams A4` remains **Active**.
- **Credit Balance**: Granted `$150.00`, Remaining `$150.00`, Used `$0.00` (Credit balance > `$0.00`).
- **Expiration Date**: `31.08.2028` (Conservative operational boundary).
- **Applicable Products**: Explicitly confirmed to cover `Amazon Bedrock Service` and `AmazonBedrockFoundationModels`.
- **Zero-Personal-Spend Invariant**: Preserved. Target remains strictly `$0.00`.

---

## 2. Authentication Surface & Security (Step 3)

- **Authentication Mechanism**: Official short-lived console-credential login flow (`aws login --profile stilldone-p01 --remote`).
- **AWS CLI Version**: `aws-cli/2.37.4 Python/3.14.6 Windows/10 exe/AMD64` (installed locally via official package).
- **Credentials Policy**:
  - Zero static IAM access keys created.
  - Zero root access keys created or persisted.
  - Short-lived session credentials acquired via console browser authentication.
  - Session explicitly invalidated and cleaned up after execution via `aws logout --profile stilldone-p01`.
  - Zero secrets, session tokens, account IDs, or ARNs committed to repository.

---

## 3. Live Read-Only Foundation Model Discovery (Step 5)

Target Region: `us-east-1` (US East - N. Virginia).

Discovery command executed:
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

Live discovered candidate models:
| Model ID | Model Name | Provider | Supported Inference Types | Status |
|---|---|---|---|---|
| `amazon.nova-pro-v1:0` | Nova Pro | Amazon | `ON_DEMAND`, `INFERENCE_PROFILE` | `ACTIVE` |
| `amazon.nova-2-sonic-v1:0` | Nova 2 Sonic | Amazon | `ON_DEMAND` | `ACTIVE` |
| `amazon.nova-lite-v1:0` | Nova Lite | Amazon | `ON_DEMAND`, `INFERENCE_PROFILE` | `ACTIVE` |
| `amazon.nova-micro-v1:0` | Nova Micro | Amazon | `ON_DEMAND`, `INFERENCE_PROFILE` | `ACTIVE` |

### Model Selection & Rationale
- **Selected Model ID**: `amazon.nova-micro-v1:0`
- **Rationale**:
  1. Provider is `Amazon` (avoids 3P Marketplace EULA, onboarding delays, or FTU questionnaires).
  2. Supports text generation with active lifecycle (`ACTIVE`).
  3. Supports `ON_DEMAND` inference in `us-east-1`.
  4. Official AWS documentation confirms Amazon Bedrock Converse API support.
  5. Lowest-cost text generation model in the Amazon foundation model catalog.

---

## 4. Pre-Call Pricing & Cost Bounding (Step 6)

Official pricing verified from [Amazon Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/) for `amazon.nova-micro-v1:0` in `us-east-1`:
- **Input Tokens**: `$0.035 per 1,000,000 input tokens` (`$0.000035 / 1,000 tokens`).
- **Output Tokens**: `$0.140 per 1,000,000 output tokens` (`$0.000140 / 1,000 tokens`).

### Bounded Request Cost Calculation
- **Sanitized Prompt**: `"Ping. Reply only with: pong"` (~8 input tokens, bounded at `<= 30`).
- **Max Generation Bounding**: `maxTokens: 32`.
- **Maximum Estimated Gross Cost**:
  $$\text{Input Cost} = 30 \times \frac{\$0.035}{1{,}000{,}000} = \$0.00000105$$
  $$\text{Output Cost} = 32 \times \frac{\$0.140}{1{,}000{,}000} = \$0.00000448$$
  $$\text{Total Gross Upper Bound} = \$0.00000553 \ll \$0.01$$
The single-call gross estimated cost is more than 1,800 times below the required `$0.01` limit and covered by promotional credit.

---

## 5. The Single Real Inference Attempt (Step 7)

Execution parameters:
- **API Operation**: `bedrock-runtime converse`
- **Region**: `us-east-1`
- **Model ID**: `amazon.nova-micro-v1:0`
- **Sanitized Prompt**: `"Ping. Reply only with: pong"`
- **Generation Bound**: `maxTokens: 32`
- **Tools**: None
- **Guardrails / Knowledge Bases / Agents**: None
- **Number of Attempts**: **EXACTLY 1** (Attempt count = 1)

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

### Result & Error Observation
- **Exit Status**: Failed (Exit code `1`)
- **Error Class**: `AccessDeniedException`
- **Sanitized Error Message**:
  > `An error occurred (AccessDeniedException) when calling the Converse operation: Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation. If you are still receiving this message after more than 2 hours, please let us know by writing to aws-verification[at]amazon.com. We appreciate your patience.`

### Usage & Token Metadata Observation
- **inputTokens**: `NOT_RETURNED / NOT_AVAILABLE`
- **outputTokens**: `NOT_RETURNED / NOT_AVAILABLE`
- **totalTokens**: `NOT_RETURNED / NOT_AVAILABLE`
- **stopReason**: `NOT_RETURNED / NOT_AVAILABLE`
- **Execution Truth**:
  - The request reached the real AWS Bedrock Converse authorization path.
  - It was rejected before a successful model response.
  - No model-response usage metadata was returned by AWS.
  - Zero token processing must not be inferred from the absence of usage metadata.

### Constitutional Strict Enforcement (No-Retry Law)
Per Master Plan and task safety instructions:
- **Zero Retries Performed**: Attempt count remains strictly **1**.
- **No Second Model Attempted**: Did not attempt fallback to Titan or any other model.
- **No Second Region Attempted**: Did not attempt fallback to other regions.
- **No Provider Fallback**: Did not attempt fallback to external providers.
- **No Simulation / No Fixture**: The error is recorded faithfully as real live truth. Task P-01.02 is **NOT** marked DONE.

---

## 6. Post-Attempt Billing & Resource Delta

- **Post-Call Billing/Credit Delta**: `NOT_OBSERVED / UNKNOWN`
- **Actual Billed Request Cost**: `NOT_OBSERVED / UNKNOWN`
- **Personal-Spend Delta**: `NOT_OBSERVED / UNKNOWN`
- **Planned Successful-Call Gross Upper Bound**: `$0.00000553` (strictly preserved as pre-call calculated risk bound)
- **Billing Observation Truth**:
  - No successful model response was obtained.
  - A real post-call Billing/Credits read was not performed at checkpoint; therefore, the failed authorization response must not be converted into proof of "$0 billed" without billing evidence.
- **AWS Resource Mutations**: `NONE`. Zero cloud resources created.

---

## 7. Status, Next Safe Action & Retry Authority

- **P-01.02 Status**: **`BLOCKED`** (AWS new-account verification pending).
- **P-01.03 Status**: **`NOT STARTED`** (Strictly locked; must not start).
- **Next Safe Action**: Wait for AWS account verification, then independent QA may authorize one new bounded execution cycle of the SAME P-01.02 task (`P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt`).
- **Retry Authority**: Retry is NOT automatically authorized. The previous execution contract allowed exactly one inference attempt and that attempt has been consumed. A later second execution cycle of P-01.02 requires fresh independent QA authorization after AWS verification is expected to have completed. Within that future execution cycle: exactly one inference attempt, no retry/fallback, and the same zero-spend boundary.
