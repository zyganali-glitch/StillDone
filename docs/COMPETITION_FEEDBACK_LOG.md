# Competition Feedback & Friction Log

Purpose:
capture factual Amazon/AWS/Alexa+/MCP development feedback throughout the build.

Do not invent entries.

## Entry template

### F-YYYYMMDD-NN — Short title

- Date/time:
- Exact task:
- Tool/API/SDK:
- Version/region/account mode:
- Attempt:
- Expected:
- Actual:
- Severity: `LOW | MEDIUM | HIGH | BLOCKER`
- Workaround:
- Evidence:
- Was this operator error, StillDone bug, docs friction, platform bug, limitation, or unknown?
- Actionable suggestion:
- Would we build with it again? `YES | NO | CONDITIONAL`
- Secrets/PII check: `CLEAN`

---

## Logged entries

### F-20260927-01 — AWS Account & Identity Onboarding Ambiguity

- Date/time: 2026-09-27T08:00:00Z
- Exact task: P-01.01 — AWS account, billing alerts, and Bedrock model-access verification
- Tool/API/SDK: AWS Management Console, IAM Identity Center / IAM Users
- Version/region/account mode: us-east-1 / Newly created AWS Free Tier account with hackathon credit
- Attempt: Initial account setup and identity provisioning for programmatic development access
- Expected: Single clear standard path documented for individual hackathon developer programmatic access combining credit application, billing alert configuration, and IAM/SSO credentials
- Actual: Significant friction between modern recommended IAM Identity Center (SSO) workflow and legacy IAM User access keys; confusing console prompts regarding root user security vs developer user creation; unclear guidance on whether promotional credits apply immediately to Bedrock inference
- Severity: `MEDIUM`
- Workaround: Configured minimal IAM User with scoped least-privilege permissions, MFA, and zero-spend budget alerts before testing credentials
- Evidence: `docs/P01_LIVE_FEASIBILITY.md`
- Was this operator error, StillDone bug, docs friction, platform bug, limitation, or unknown? Docs friction / UX onboarding complexity
- Actionable suggestion: Provide a unified "AI Hackathon Developer Quickstart" in AWS documentation that gives clear step-by-step guidance for credit-funded individual builder accounts to safely create programmatic Bedrock credentials without navigating enterprise SSO setup
- Would we build with it again? `CONDITIONAL`
- Secrets/PII check: `CLEAN`

---

### F-20260927-02 — New Account Verification Hold Blocked Initial Bedrock Inference

- Date/time: 2026-09-27T11:42:00Z
- Exact task: P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt
- Tool/API/SDK: AWS SDK for Python (`boto3 1.42.59`), Bedrock Runtime API (`converse`)
- Version/region/account mode: Python 3.13 / us-east-1 / Amazon Nova Micro (`us.amazon.nova-micro-v1:0`)
- Attempt: Attempt 1 (Cycle 1 inference execution)
- Expected: Successful Converse API response or standard quota/access denial error
- Actual: Runtime raised `AccessDeniedException` with explicit error message stating the AWS account was currently undergoing verification and Bedrock access would be available once verification completed
- Severity: `BLOCKER`
- Workaround: Paused inference execution, waited for account verification lifecycle to complete, and had operator confirm account status
- Evidence: `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md` Cycle 1 log
- Was this operator error, StillDone bug, docs friction, platform bug, limitation, or unknown? Platform policy / account verification lifecycle
- Actionable suggestion: Surface account verification hold state prominently in the AWS Management Console Bedrock dashboard and Model Access page rather than allowing access to appear configured while runtime calls fail with runtime verification exceptions
- Would we build with it again? `CONDITIONAL`
- Secrets/PII check: `CLEAN`

---

### F-20260927-03 — Bedrock Model Authorization Blocked Despite Available Entitlements

- Date/time: 2026-09-27T16:15:00Z
- Exact task: P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt
- Tool/API/SDK: AWS SDK for Python (`boto3 1.42.59`), Bedrock Control Plane (`GetFoundationModelAvailability`), Bedrock Runtime (`converse`)
- Version/region/account mode: Python 3.13 / us-east-1 / Amazon Nova Micro (`us.amazon.nova-micro-v1:0`)
- Attempt: Attempt 2 (Cycle 2 inference execution) and subsequent read-only diagnostic
- Expected: Converse API execution succeeds after account verification hold cleared, or returns actionable guidance if additional authorization is required
- Actual: Converse API raised `ValidationException: Operation not allowed`. Read-only diagnostic revealed `authorizationStatus = NOT_AUTHORIZED` despite `agreementAvailability.status = AVAILABLE`, `entitlementAvailability = AVAILABLE`, and `regionAvailability = AVAILABLE`. Underlying root cause is unknown/not established via APIs. Support escalation required.
- Severity: `BLOCKER`
- Workaround: Strictly halted runtime inference attempts (lifetime attempts capped at 2); opened AWS Support case; transitioned task state to `BLOCKED / NOT ACCEPTED` (`AWS_SUPPORT_PENDING`); locked downstream P-01.03
- Evidence: `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md`, `docs/P01_LIVE_FEASIBILITY.md`
- Was this operator error, StillDone bug, docs friction, platform bug, limitation, or unknown? Unknown / platform entitlement synchronization delay or account-specific service restriction
- Actionable suggestion: Improve `ValidationException: Operation not allowed` error messaging to specify the exact missing prerequisite (e.g. pending agreement signature, service quota block, or support approval) rather than generic validation failure
- Would we build with it again? `CONDITIONAL`
- Secrets/PII check: `CLEAN`
