# P-01.02 Live Bedrock Inference Evidence Record

**Phase**: P-01 Live Access, Zero-Cost & Platform Feasibility  
**Task**: P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Status**: **BLOCKED / NOT ACCEPTED** — account-specific Bedrock authorizationStatus = NOT_AUTHORIZED; AWS_SUPPORT_PENDING; underlying cause UNKNOWN / NOT_ESTABLISHED (Cycle 1: Account verification hold; Cycle 2: ValidationException: Operation not allowed; Diagnostic Cycle: authorizationStatus = NOT_AUTHORIZED; Support: OPEN / AWS RESPONSE PENDING)  
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
  - Cycle 1 explicitly reported an account-verification hold (`AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours.`).
  - Cycle 2, executed more than two hours later, returned a different error: `ValidationException: Operation not allowed`.
  - The Cycle 1 verification message was NOT repeated in Cycle 2.
  - Whether AWS account verification is fully complete is `NOT_ESTABLISHED` from this error transition alone; do not claim verification hold cleared unless independently observed through an authoritative account-verification surface.
  - Current official AWS documentation checked by independent QA:
    1. Main Bedrock model-access documentation currently states access to Amazon Bedrock foundation models is enabled by default with appropriate permissions in commercial AWS Regions.
    2. Current Nova Micro model documentation explicitly supports:
       - model ID: `amazon.nova-micro-v1:0`
       - endpoint: `bedrock-runtime`
       - in-region use in: `us-east-1`
    3. Current regional compatibility documentation marks Nova Micro In-Region support in `us-east-1`.
    4. While general current Bedrock documentation says model access is enabled by default and Nova Micro direct in-region model ID is documented for `us-east-1`, some AWS Nova getting-started material may still discuss requesting model access; this documentation inconsistency must NOT be converted into proof of this account's actual blocker.
  - Therefore, the observed live failure does NOT establish:
    - missing Model Access enablement;
    - inference-profile requirement;
    - IAM denial;
    - quota zero;
    - account verification completion or incompletion;
    - any other specific root cause.
  - **Canonical Root Cause**: `UNKNOWN / NOT_ESTABLISHED`.
  - **Observed Live Failure**: `ValidationException: Operation not allowed`.
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

# Part III — Read-Only Account-Specific Diagnostic Cycle

**Observation Timestamp**: `2026-09-27T20:58:05+03:00`  
**Diagnostic Authorization Boundary**: Independent QA explicitly authorized ONE read-only diagnostic cycle to determine account-specific Bedrock availability/authorization state using current official AWS read-only APIs.  
**Inference Authorization**: **ZERO MODEL INFERENCE** (Strictly unauthorized; inference attempts in this cycle = 0; lifetime P-01.02 inference attempts = 2).  
**Authentication Mechanism**: Official short-lived console-credential login flow (`aws login --profile stilldone-p01 --remote`). Short-lived credentials immediately cleaned up via `aws logout --profile stilldone-p01`. Zero static keys created. Zero sensitive identity data recorded.  
**Exact Read-Only API Operation**: `aws bedrock get-foundation-model-availability`  
**Region**: `us-east-1`  
**Model ID Checked**: `amazon.nova-micro-v1:0`  

### 1. Diagnostic Command Executed
```bash
aws bedrock get-foundation-model-availability \
  --region us-east-1 \
  --profile stilldone-p01 \
  --model-id amazon.nova-micro-v1:0 \
  --query "{modelId:modelId,authorizationStatus:authorizationStatus,agreementStatus:agreementAvailability.status,agreementError:agreementAvailability.errorMessage,entitlementAvailability:entitlementAvailability,regionAvailability:regionAvailability}" \
  --output json
```

### 2. Sanitized Exact Returned Availability Fields
```json
{
    "modelId": "amazon.nova-micro-v1",
    "authorizationStatus": "NOT_AUTHORIZED",
    "agreementStatus": "AVAILABLE",
    "agreementError": null,
    "entitlementAvailability": "AVAILABLE",
    "regionAvailability": "AVAILABLE"
}
```

### 3. Deterministic Diagnostic Classification & Analysis
- **Observed Blocker Dimension**: `BEDROCK_MODEL_AUTHORIZATION_NOT_AUTHORIZED` (`authorizationStatus = "NOT_AUTHORIZED"`).
- **Secondary Availability Dimensions**:
  - `agreementStatus`: `AVAILABLE`
  - `agreementError`: `null`
  - `entitlementAvailability`: `AVAILABLE`
  - `regionAvailability`: `AVAILABLE`
- **Underlying Root Cause**: `UNKNOWN / NOT_ESTABLISHED`.
  - While AWS Bedrock explicitly reports `authorizationStatus = "NOT_AUTHORIZED"` for this account and model in `us-east-1`, the underlying causal reason (such as whether an account verification hold remains active, or explicit Model Access agreement/request is required, or other account restriction) is not directly provided by the API response.
  - Per governance, this observed blocker dimension must NOT be speculatively attributed to unproven causes.
- **Optional Second-Model Check**: `NOT_RUN` (Nova Micro diagnostic result established a clear, unambiguous blocker dimension: `authorizationStatus = NOT_AUTHORIZED`; per instructions, no second check was required or run).
- **AWS Mutations**: `NONE` (0 resources created, 0 modified, 0 deleted).
- **Inference Calls in This Cycle**: `0` (Strictly zero inference).
- **Lifetime P-01.02 Inference Attempts**: `2` (Cycle 1: 1, Cycle 2: 1).
- **Session Cleanup**: `aws logout --profile stilldone-p01` executed immediately; cached credentials deleted.

---

# Part IV — Authenticated AWS Support Blocker Escalation

**Date**: `2026-09-27`  
**External Resolution State**: `AWS_SUPPORT_PENDING`  
**Support Case Status**: `OPEN — AWS RESPONSE PENDING`  
**Case Subject**: `Amazon Bedrock account security restriction — Operation not allowed / NOT_AUTHORIZED`  

### 1. Context & Operator-Submitted Facts
On `2026-09-27`, the operator successfully opened a formal support case through the authenticated AWS Support Center (`/support/home`).
The case submission included the following sanitized technical facts:
- Account participates in the official Amazon Devices Global Hackathon;
- Active AWS Paid Plan account with verified promotional AWS credits;
- Bedrock control-plane discovery functions as expected (`list-foundation-models` discovers active models in `us-east-1`);
- Live read-only `get-foundation-model-availability` check for `amazon.nova-micro-v1:0` returns:
  - `authorizationStatus`: `NOT_AUTHORIZED`
  - `agreementStatus`: `AVAILABLE`
  - `entitlementAvailability`: `AVAILABLE`
  - `regionAvailability`: `AVAILABLE`
- Live Bedrock Runtime `converse` invocation fails with:
  - `ValidationException: Operation not allowed`
- Request submitted to AWS Support to review the account-level Bedrock authorization / security restriction and clarify any required verification or remediation actions.

### 2. Official AWS Troubleshooting Classification vs Account Truth Boundary
- **Official AWS Troubleshooting Classification**:
  In official AWS documentation and troubleshooting guidance, `Operation not allowed` on foundation model operations is categorized within an account security restriction class for which direct AWS Support contact is recommended.
- **This Account's Underlying Causal Root Cause**:
  Remains strictly **`UNKNOWN / NOT_ESTABLISHED`** pending authoritative AWS Support response.
- **Strict Non-Claims**:
  - AWS has not yet confirmed the specific underlying root cause for this account;
  - AWS has not yet confirmed an explicit security restriction on this specific account;
  - No assumption is made that authorization will be automatically restored;
  - No response SLA beyond standard AWS Support queuing is assumed;
  - Zero sensitive identifiers (Account ID, Support Case ID, root email, credit ID, payment details, phone, address, credentials, or screenshots) are committed.

---

## 7. Cumulative Lifecycle Summary & Next Safe Action

| Cycle | Timestamp | API / Error Class | Observed Result / Error Message | Task State |
|---|---|---|---|---|
| **Cycle 1** | `2026-09-27T11:05:34+03:00` | `AccessDeniedException` | `Your account is currently being verified. Verification normally takes less than 2 hours.` | `BLOCKED` |
| **Cycle 2** | `2026-09-27T13:19:20+03:00` | `ValidationException` | `Operation not allowed` | `BLOCKED / NOT ACCEPTED` |
| **Diagnostic Cycle** | `2026-09-27T20:58:05+03:00` | `get-foundation-model-availability` (Read-only) | `authorizationStatus = NOT_AUTHORIZED` (agreement: AVAILABLE, entitlement: AVAILABLE, region: AVAILABLE) | `BLOCKED / NOT ACCEPTED` |
| **Support Escalation** | `2026-09-27` | Authenticated AWS Support Case | Case OPEN: `Amazon Bedrock account security restriction — Operation not allowed / NOT_AUTHORIZED` | `AWS_SUPPORT_PENDING` |

- **Cumulative P-01.02 Inference Attempts**: `2` (Cycle 1: 1 attempt, Cycle 2: 1 attempt, Diagnostic Cycle: 0 attempts, Support Escalation: 0 attempts; lifetime P-01.02 inference attempts = 2).
- **Current Canonical Status**: **`BLOCKED / NOT ACCEPTED — authorizationStatus = NOT_AUTHORIZED; AWS_SUPPORT_PENDING; underlying cause UNKNOWN / NOT_ESTABLISHED`**.
- **External Resolution State**: **`AWS_SUPPORT_PENDING`** (Support case OPEN / AWS response pending).
- **Task P-01.03 Status**: **`NOT STARTED / LOCKED`** (Strictly locked; must not start before P-01.02 achieves live model response and independent QA PASS).
- **Next Safe Action**:
  Wait for authoritative AWS Support response.
  Third inference attempt is strictly **NOT AUTHORIZED** without fresh independent QA authorization.


