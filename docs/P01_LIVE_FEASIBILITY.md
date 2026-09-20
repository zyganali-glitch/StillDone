# P-01 Live Feasibility Record — AWS Platform & Zero-Spend Boundary

**Phase**: P-01 Live Access, Zero-Cost & Platform Feasibility  
**Task**: P-01.01 — Verify AWS account, hackathon credit, billing safety, region, and service-access reality  
**Observation Timestamp**: `2026-09-20T21:05:00+03:00`  
**Governing Authority**: [AGENTS.md](../AGENTS.md), [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md), [STILLDONE_MASTER_EXECUTION_PLAN.md](../plans/STILLDONE_MASTER_EXECUTION_PLAN.md)  
**Status**: **BLOCKED** (Zero Personal Spend Boundary Preserved)

---

## 1. Official Documentation & Competition Baseline

Facts verified against current official external sources on `2026-09-20`:

| Category | Source Authority | Official URL | Verified Observation |
|---|---|---|---|
| **Promotional Credits** | AWS Billing User Guide | `https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-credits.md` | Credits are viewed at Billing Console -> Credits (`/billing/home#/credits`). Fields: Credit ID, Status (Active/Paused/Exhausted/Expired), Amount remaining, Start/Expiration date, Applicable products. |
| **Billing Safety** | AWS Budgets User Guide | `https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.md` | AWS Budgets updates 8–12 hours after previous updates (up to 3 times/day). It is an asynchronous alerting/notification mechanism, **not** a real-time hard spending cap. |
| **Bedrock Regions** | Amazon Bedrock User Guide | `https://docs.aws.amazon.com/bedrock/latest/userguide/` | Bedrock regional availability varies by model family. `us-east-1` (N. Virginia) and `us-west-2` (Oregon) provide primary foundation model coverage and cross-region inference profiles. |
| **Bedrock Model Access** | Amazon Bedrock User Guide | `https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html` | Model access must be requested/enabled in the Bedrock console under Model access before programmatic invocation. EULA acceptance or use-case submission may be required. |
| **Hackathon Resources** | Devpost Hackathon Resources | `https://amazonappdev2026.devpost.com/resources` | Official $150 credit request form (`https://forms.gle/GaHFxSbBQNG9Kti6A`). Request deadline: October 21, 2026. Official form notes processing takes up to 5 business days. |

---

## 2. Live Account State Observation (Read-Only)

Executed in local host environment on `2026-09-20`:

| Dimension | Observed State | Evidence / Detail |
|---|---|---|
| **Authenticated Account Observable** | **NO** | `aws` CLI is not installed on the system PATH. `$HOME/.aws` contains only an empty `sso/cache` directory; no `credentials` or `config` files exist. No `AWS_*` environment variables exist in the execution environment. |
| **Account / Billing Mode** | **UNKNOWN** | Cannot be observed programmatically without active authenticated credentials. |
| **Hackathon $150 Credit** | **NOT_OBSERVABLE** | Operator submitted the credit request form on 2026-09-20 (receipt: "Yanıtınız kaydedildi."). Form processing window is up to 5 business days. Credit presence in an AWS account has not yet been independently observed. |
| **Credit Amount Remaining** | **NOT_OBSERVABLE** | N/A (no authenticated session). |
| **Credit Expiration Date** | **NOT_OBSERVABLE** | N/A (no authenticated session). |
| **Current Unexpected Charges** | **UNKNOWN** | Cannot be observed programmatically without active authenticated credentials. |
| **Live Mutations Performed** | **NONE** | Zero mutations executed. |
| **Bedrock Inference Performed** | **NONE** | Zero Bedrock inference calls executed. |
| **Bedrock Control-Plane Visibility** | **BLOCKED** | Cannot execute read-only API calls (e.g. `bedrock:ListFoundationModels`) without credentials. |

---

## 3. Candidate AWS Region & Rationale

- **Primary Candidate Region**: `us-east-1` (US East - N. Virginia)
  - **Rationale**:
    1. Maximum availability of Amazon Bedrock foundation models (Anthropic Claude 3.5 Sonnet, Claude 3 Haiku, Amazon Titan, Amazon Nova).
    2. Native support for Amazon Bedrock AgentCore Runtime with Python 3.13 (`PYTHON_3_13`, AL2023 base).
    3. Full compatibility with AWS Strands Agents SDK.
    4. Standard primary endpoint for AWS promotional credit application across all core developer hackathon services.
- **Alternative Regions Evaluated**:
  - `eu-central-1` (Frankfurt): Closer to operator timezone (UTC+3), but historically slower to receive new model releases and preview features.
  - `us-west-2` (Oregon): Excellent secondary region; candidate for cross-region inference fallback if needed.
- **Model ID Decision**: **UNFROZEN** in P-01.01. Model selection will occur during P-01.02 based on live catalog discovery.

---

## 4. Zero-Personal-Spend Safety Decision

### Decision: `BLOCKED_ZERO_SPEND`

**Deterministic Rationale**:
1. Target personal spend is strictly **`$0.00`** (AGENTS.md § 12).
2. The $150 promotional credit request was submitted on 2026-09-20 and is currently in the 5-business-day processing window. Credit availability in the AWS account is not yet observed.
3. No active, authenticated, spend-bounded AWS session exists in the execution environment.
4. AWS Budgets updates asynchronously (8–12 hours delay) and does not provide an instant, real-time circuit breaker against unexpected personal charges.
5. In accordance with StillDone Constitution § 12 and P-01.01 acceptance criteria, proceeding with live model invocation without verified promotional credits or proven zero-spend isolation is strictly forbidden.
6. Therefore, Phase P-01 live execution is blocked at this boundary until credit arrival and account state are independently confirmed.

---

## 5. Safe Budget & Kill Strategy for Future Live Work

Prior to executing any future paid-capable task (specifically P-01.02):

1. **Pre-Execution Credit Confirmation**:
   - Operator must log in to the AWS Management Console directly via browser.
   - Navigate to the **Credits** page (`https://console.aws.amazon.com/billing/home#/credits`).
   - Confirm that the `$150.00` Hackathon Promotional Credit is present with status **Active** and non-zero amount remaining.
2. **Strict Invocation Bounding**:
   - For all test Bedrock calls in P-01.02, enforce minimal token usage:
     - `max_tokens` / `maxTokens`: capped at `<= 100`.
     - Prompts: single-turn, sanitized, minimal strings (e.g. `"Ping: return pong"`).
     - Number of calls: bounded to exactly 1 inference for initial feasibility.
3. **No Automatic Paid Fallback**:
   - If promotional credit is exhausted or expired, all live AWS calls must immediately abort with `BLOCKED_ZERO_SPEND`.
   - Never charge operator credit cards or enable pay-as-you-go continuation.
4. **Immediate Teardown of Ephemeral Resources**:
   - No provisioned throughput, reserved instances, or marketplace subscriptions may be purchased.
   - Any test IAM roles, S3 buckets, or temporary log groups must be deleted immediately after validation.
5. **Kill Switch Threshold**:
   - If unexpected personal spend of even `$0.01` is detected on the account, all AWS integration tasks must immediately halt.

---

## 6. Execution Boundary & Next Step Lock

> [!CAUTION]
> **P-01.02 Execution Lock**:
> Task `P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt` has **NOT** been executed.
> Under decision `BLOCKED_ZERO_SPEND`, P-01.02 is strictly blocked from starting until independent QA and the operator verify credit disbursement and authorize progression.
