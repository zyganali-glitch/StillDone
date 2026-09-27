# P-01 Live Feasibility Record — AWS Platform & Zero-Spend Boundary

**Phase**: P-01 Live Access, Zero-Cost & Platform Feasibility  
**Task**: P-01.01 — Verify AWS account, hackathon credit, billing safety, region, and service-access reality  
**Observation Timestamp**: `2026-09-27T09:50:00+03:00`  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Status**: **RECONCILED / SAFE_TO_ATTEMPT_NEXT_LIVE_TASK** (Awaiting Independent QA PASS)

---

## 1. Official Documentation & Competition Baseline

Facts verified against current official external sources on `2026-09-27`:

| Category | Source Authority | Official URL | Verified Observation |
|---|---|---|---|
| **Promotional Credits** | AWS Billing User Guide | `https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-credits.html` | Credits are viewed at Billing Console -> Credits (`/billing/home#/credits`). Applied automatically to eligible service charges until exhausted or expired. Fields: Credit ID, Credit type (e.g. Promotion), Status (Active/Paused/Exhausted/Expired), Amount remaining, Start date, Expiration date, Applicable products. Credit is a payment offset, not a hard billing cap. |
| **Bedrock Model Access** | Amazon Bedrock User Guide | `https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html` | Access to Amazon Bedrock foundation models is enabled by default with the correct AWS Marketplace permissions in all commercial AWS regions. Third-party models automatically initiate AWS Marketplace subscription on first invocation (requires Marketplace permissions and valid payment method). Anthropic models require First Time Use (FTU) use-case form submission. Amazon-provider models have no 3P EULA / FTU prerequisite. Merely seeing a model in catalog does not guarantee inference without permission verification. |
| **Bedrock Regional Availability** | Amazon Bedrock User Guide | `https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints-region-availability.html` | `us-east-1` (US East - N. Virginia) supports both `bedrock-runtime` and `bedrock-mantle` endpoints. |
| **AgentCore Supported Regions** | Amazon Bedrock AgentCore Developer Guide | `https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html` | `us-east-1` (US East - N. Virginia) is an officially supported region for Amazon Bedrock AgentCore features. |
| **Billing Safety** | AWS Budgets User Guide | `https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.md` | AWS Budgets updates asynchronously (8–12 hours delay, up to 3 times/day). It is an alerting/notification mechanism, **not** an instant real-time hard spending cap. |
| **Hackathon Resources** | Devpost Hackathon Resources | `https://amazonappdev2026.devpost.com/resources` | Official $150 credit request form (`https://forms.gle/GaHFxSbBQNG9Kti6A`). Request deadline: October 21, 2026. Credit has been successfully requested, received, and redeemed into the active account. |

---

## 2. Live Account State Observation (Read-Only)

Operator-observed live AWS account reality reconciled on `2026-09-27`:

| Dimension | Observed State | Evidence / Detail |
|---|---|---|
| **Authenticated Account Observable** | **YES** | Independently operator-observed via AWS Management Console sign-in. |
| **Account / Billing Mode** | **Paid account plan** | Explicitly approved and selected by operator to permit hackathon promotional-credit redemption. Support plan: Basic (free). |
| **Current Unexpected Charges** | **$0.00** | Sanitized observed fact: $0.00 usage/charges observed at inspection checkpoint. |
| **Hackathon Promotional Credit** | **PRESENT / ACTIVE** | Name displayed: `Amazon Devices Global Hackathon - Teams A4`. Type: `Promotion`. Status: `Active`. Granted: `$150.00`. Remaining: `$150.00`. Used: `$0.00`. Start date: `2026-09-01`. |
| **Credit Expiration Date** | **2028-09-01** | Directly observed in AWS Billing credit detail view. (Note: Overview or email communications may display `2028-08-31` due to timezone or billing boundary wording; directly observed Billing detail value is preserved). |
| **Separate AWS Signup Credit** | **PRESENT / ACTIVE** | Name displayed: `AWS Free Tier`. Status: `Active`. Granted: `$100.00`. Remaining: `$100.00`. Used: `$0.00`. Expiry: `2027-09-27`. Total observed remaining credit across both credits: `$250.00`. |
| **Account-Specific Credit Coverage** | **OBSERVED** | Operator opened the hackathon credit's live AWS Billing "Applicable products" list. Visibly confirmed coverage includes: `Amazon Bedrock Service`, `AmazonBedrockFoundationModels`, `Amazon Bedrock`, `Amazon Bedrock Managed Knowledge Base`, and `Amazon Bedrock AgentCore`. |
| **Account History Correction** | **RECONCILED** | Earlier sign-in blocker was based on the assumption that an existing AWS account already existed. Subsequent signup flow successfully created a new AWS account with the intended email, establishing that the prior state was a Builder ID / no usable AWS account situation rather than an inaccessible existing AWS account. The support case opened during that assumption is not active feasibility evidence and is no longer a blocker. |
| **Live Mutations Performed** | **NONE** | Zero cloud resources created, modified, or deleted. |
| **Bedrock Inference Performed** | **NONE** | Zero Bedrock inference calls executed. |
| **Bedrock Control-Plane Visibility** | **READY_FOR_BOUNDED_DISCOVERY** | Bedrock foundation-model access is enabled by default in commercial regions per current official documentation. Programmatic read discovery will take place strictly within task P-01.02 under bounded conditions. |

---

## 3. Candidate AWS Region & Rationale

- **Primary Candidate Region**: `us-east-1` (US East - N. Virginia)
  - **Factual Rationale** (based strictly on current official AWS documentation):
    1. Full availability of Amazon Bedrock inference endpoints (`bedrock-runtime` and `bedrock-mantle`) per official endpoints documentation.
    2. Official support for Amazon Bedrock AgentCore Runtime per official AgentCore regions documentation.
    3. Factual basis only: Region selection is based solely on documented service and runtime support. Region selection has no bearing on promotional credit redemption.
- **Alternative Regions Evaluated**:
  - `us-west-2` (Oregon): Secondary candidate supported by Bedrock runtime and AgentCore; available for cross-region fallback if necessary.
- **Model ID Decision**: **UNFROZEN** in P-01.01. Model selection will occur during P-01.02 based on live Bedrock catalog discovery. The first feasibility call should prefer an Amazon-provider text model (e.g. Amazon Titan or Amazon Nova family) to avoid third-party Marketplace/EULA/FTU onboarding friction.

---

## 4. Zero-Personal-Spend Safety Decision

### Decision: `SAFE_TO_ATTEMPT_NEXT_LIVE_TASK`

**Deterministic Rationale**:
1. Target personal spend is strictly **`$0.00`** (AGENTS.md § 12).
2. The official `$150.00` Hackathon Promotional Credit is confirmed Active and redeemed in the AWS account, with `$150.00` remaining and `$0.00` used at checkpoint.
3. Live "Applicable products" list in AWS Billing explicitly covers Amazon Bedrock and Amazon Bedrock AgentCore.
4. Current unexpected account charges are `$0.00` at checkpoint.
5. The prior blocker (`BLOCKED_ZERO_SPEND` due to unobserved credit disbursement) is resolved by direct operator observation.

**Strict Scope of `SAFE_TO_ATTEMPT_NEXT_LIVE_TASK`**:
- This decision means **ONLY**: One independently authorized, tightly bounded P-01.02 Bedrock feasibility inference may be attempted after independent P-01.01 QA PASS.
- It does **NOT** mean:
  - unlimited AWS usage;
  - unlimited spend;
  - permission to exhaust credits;
  - permission for paid fallback;
  - permission to create unrelated resources;
  - permission for provisioned throughput;
  - permission for arbitrary Marketplace purchases.
- Promotional credit is a payment offset, **not** a hard billing cap.
- AWS Budgets remains an asynchronous alerting/notification mechanism (8–12 hr delay), not an instant hard circuit breaker.

---

## 5. Future P-01.02 Safety Contract

Documented requirements and constraints for future task P-01.02 (do NOT execute during P-01.01):

1. **Pre-Invocation Credit Verification**:
   - Re-check that the hackathon promotional credit remains Active and non-zero immediately prior to invocation where practical.
2. **Live Catalog Model Selection**:
   - Discover available models from live Bedrock state; do NOT hard-code a model ID from stale documentation.
   - Prefer an Amazon-provider text model for the initial feasibility call to avoid unnecessary third-party Marketplace subscription delays, EULAs, or FTU use-case questionnaires.
3. **Strict Invocation Bounding**:
   - Single-turn, sanitized, minimal prompt string (e.g. `"Ping: return pong"`).
   - Aggressive token bounding: `max_tokens` / `maxTokens` capped at `<= 100`.
   - Number of calls: exactly **1** inference initially.
4. **Metadata & Cost Audit**:
   - Record actual region, model ID, latency, and request/response metadata without secrets.
   - Verify post-call credit and cost evidence in the Billing console when observable.
5. **Kill Switch & No Paid Fallback**:
   - If promotional credit is exhausted, fails to apply, or if any unexpected personal charge (even `$0.01`) appears, immediately abort all live execution with `BLOCKED_ZERO_SPEND`.
   - Never charge operator payment methods or enable pay-as-you-go continuation.

---

## 6. Execution Boundary & Next Step Lock

> [!CAUTION]
> **P-01.02 Execution Lock**:
> Task `P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt` has **NOT** been executed.
> Under decision `SAFE_TO_ATTEMPT_NEXT_LIVE_TASK`, P-01.02 is strictly locked from starting until independent QA awards `PASS` to task P-01.01.
> Zero Bedrock inferences executed in P-01.01. Zero AWS resources created.
