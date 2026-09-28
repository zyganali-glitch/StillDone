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

- Date/time: 2026-09-27 — exact event time not preserved in canonical evidence
- Exact task: P-01.01 — Verify AWS account, hackathon credit, billing safety, region, and service-access reality
- Tool/API/SDK: AWS account signup / AWS Management Console / Builder ID context
- Version/region/account mode: us-east-1 / Paid account plan; Basic support
- Attempt: Initial AWS account setup and sign-in verification for hackathon development
- Expected: Seamless sign-in and clear distinction between AWS Builder ID credentials and an active, usable AWS account
- Actual: Initial sign-in blocker was based on the assumption that an existing usable AWS account already existed; sign-in and account-state confusion occurred because AWS Builder ID was separate from an AWS account. Subsequent official AWS signup successfully created the usable AWS account with a Paid account plan (explicitly authorized by the operator to enable promotional-credit redemption) and Basic support plan. Hackathon promotional credit was later redeemed and observed Active. The earlier sign-in assumption was corrected. No IAM User or access-key provisioning was part of this canonical evidence.
- Severity: `MEDIUM`
- Workaround: Clarified account state, completed official AWS account signup, selected Paid account plan with Basic support, and redeemed hackathon promotional credit
- Evidence: `docs/P01_LIVE_FEASIBILITY.md`
- Was this operator error, StillDone bug, docs friction, platform bug, limitation, or unknown? account-state/onboarding ambiguity
- Actionable suggestion: Clarify distinction between AWS Builder ID and full AWS account in developer hackathon documentation to avoid sign-in/account-state confusion for new builders
- Would we build with it again? `CONDITIONAL`
- Secrets/PII check: `CLEAN`

---

### F-20260927-02 — New Account Verification Hold Blocked Initial Bedrock Inference

- Date/time: 2026-09-27T11:05:34+03:00
- Exact task: P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt
- Tool/API/SDK: AWS CLI (`aws-cli/2.37.4 Python/3.14.6 Windows/10 exe/AMD64`), Bedrock Runtime (`aws bedrock-runtime converse`), authenticated via `aws login --profile stilldone-p01 --remote`
- Version/region/account mode: us-east-1 / model: `amazon.nova-micro-v1:0` / Paid account plan; Basic support
- Attempt: Attempt 1 (Cycle 1 inference execution)
- Expected: Successful Converse API response or standard model invocation error
- Actual: Runtime raised `AccessDeniedException` with explicit AWS message stating the account was currently being verified ("Your account is currently being verified. Verification normally takes less than 2 hours. Until your account is verified, you may not have access to this operation..."). Zero usage/token metadata returned. Zero retries performed.
- Severity: `BLOCKER`
- Workaround: Stopped immediately; preserved the failure; zero retries; waited beyond the AWS-stated verification interval (> 2 hours); later allowed a fresh independently authorized cycle
- Evidence: `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md` Part I (Cycle 1)
- Was this operator error, StillDone bug, docs friction, platform bug, limitation, or unknown? account verification lifecycle / platform policy
- Actionable suggestion: Surface account verification hold state prominently in the AWS Management Console Bedrock dashboard rather than allowing access to appear configured while runtime calls fail with runtime verification exceptions
- Would we build with it again? `CONDITIONAL`
- Secrets/PII check: `CLEAN`

---

### F-20260927-03 — Bedrock Model Authorization Blocked Despite Available Entitlements

- Date/time: Cycle 2: `2026-09-27T13:19:20+03:00`; Read-only diagnostic: `2026-09-27T20:58:05+03:00`
- Exact task: P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt
- Tool/API/SDK: AWS CLI (`aws bedrock-runtime converse`, `aws bedrock get-foundation-model-availability`), authenticated via `aws login --profile stilldone-p01 --remote`
- Version/region/account mode: us-east-1 / model: `amazon.nova-micro-v1:0` / Paid account plan; Basic support
- Attempt: Attempt 2 (Cycle 2 inference execution) and subsequent read-only diagnostic cycle
- Expected: Converse API execution succeeds, or returns actionable guidance if additional authorization is required
- Actual: Cycle 2 operation (`aws bedrock-runtime converse`) with model `amazon.nova-micro-v1:0` raised `ValidationException: Operation not allowed`. Subsequent read-only diagnostic (`aws bedrock get-foundation-model-availability`) revealed `authorizationStatus = NOT_AUTHORIZED` with `agreementStatus = AVAILABLE`, `agreementError = null`, `entitlementAvailability = AVAILABLE`, and `regionAvailability = AVAILABLE`. Underlying causal root cause is unknown and not established via APIs.
- Severity: `BLOCKER` (FUNCTIONALLY REMEDIATED via AWS Support account adjustments on 2026-09-28)
- Workaround: Strictly halted runtime inference attempts (lifetime attempts capped at 2; zero inference attempts in diagnostic cycle); opened authenticated AWS Support case; transitioned task state to `BLOCKED / NOT ACCEPTED` (`AWS_SUPPORT_PENDING`); locked downstream P-01.03. AWS Support escalation was the remediation path.
- Evidence: `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md` Parts II, III, IV, V; `docs/P01_LIVE_FEASIBILITY.md`
- Resolution / Outcome (2026-09-28):
  - Operator provided project context to AWS Support; AWS Support confirmed authorized service team completed account adjustments for base Amazon Bedrock models.
  - Subsequent preflight on 2026-09-28 observed `authorizationStatus = AUTHORIZED`.
  - Cycle 3 single inference attempt against `amazon.nova-micro-v1:0` in `us-east-1` succeeded with genuine model response (`pong`, stopReason=`end_turn`, tokens: in=8, out=3, total=11).
  - Bedrock access blocker is functionally remediated by current live evidence; AWS Support case administrative state remains `NOT_OBSERVED / NOT_ESTABLISHED`.
  - Historical `NOT_AUTHORIZED` observation remains preserved as factual at observation time; current authorization state is confirmed `AUTHORIZED`.
  - Internal causal root cause remains `NOT_ESTABLISHED`.
- Was this operator error, StillDone bug, docs friction, platform bug, limitation, or unknown? UNKNOWN / NOT_ESTABLISHED
- Actionable suggestion: Improve `ValidationException: Operation not allowed` error messaging to specify the exact missing prerequisite rather than generic validation failure
- Would we build with it again? `CONDITIONAL`
- Secrets/PII check: `CLEAN`

---

### F-20260928-01 — AWS Login Credential Provider Requires awscrt Extra in Boto3

- Date/time: 2026-09-28T17:04:30Z
- Exact task: P-01.03 — Prove minimal real Strands agent execution against the selected Bedrock model
- Tool/API/SDK: Python (`3.13.5`), `strands-agents 1.57.1`, `boto3 1.43.103`, `botocore 1.43.103`
- Version/region/account mode: us-east-1 / model: `amazon.nova-micro-v1:0` / profile: `stilldone-p01` (from `aws login`)
- Attempt: Initial instantiation of `BedrockModel` with a `boto3.Session(profile_name="stilldone-p01")`
- Expected: `boto3` transparently loads session credentials created by the official `aws login` CLI flow
- Actual: `botocore` raised `botocore.exceptions.MissingDependencyException: Missing Dependency: Using the login credential provider requires an additional dependency. You will need to pip install "botocore[crt]" before proceeding.`
- Severity: `LOW`
- Workaround: Included `botocore[crt]` (`awscrt 0.36.0`) in the execution environment (`uv run --with strands-agents --with "botocore[crt]"`).
- Evidence: `docs/P01_03_LIVE_STRANDS_EVIDENCE.md`
- Was this operator error, StillDone bug, docs friction, platform bug, limitation, or unknown? docs/SDK friction
- Actionable suggestion: Standard AWS developer documentation for `aws login` and AWS SDKs should clearly document that consuming login-based session credentials in Python requires `botocore[crt]` / `awscrt`.
- Would we build with it again? `YES`
### F-20260928-02 — AgentCore CLI Windows Argument Quoting & Non-Interactive Teardown Friction

- Date/time: 2026-09-28T19:10:14Z
- Exact task: P-01.04 — Prove minimal AgentCore runtime/deployment path or formally reject it with evidence
- Tool/API/SDK: Node.js `@aws/agentcore` CLI (v0.30.0) on Windows PowerShell
- Version/region/account mode: us-east-1 / AgentCore Runtime / CodeZip / Python 3.13 / profile: `stilldone-p01`
- Attempt: Invocation with JSON payload via `agentcore invoke --prompt '{"prompt": "PING"}'` and teardown via `agentcore remove all`
- Expected: CLI preserves JSON quotes or parses JSON string into payload; CLI allows scripted cleanup without interactive prompt
- Actual: On Windows PowerShell, the CLI unquoted the JSON argument and forwarded `"{prompt: PING}"` to the runtime entrypoint. Additionally, `agentcore remove all` failed by default with `Error: This command requires an interactive terminal` unless `-y` was provided, and `agentcore deploy --dry-run` failed when bootstrap was missing rather than continuing preview.
- Severity: `LOW`
- Workaround: Handled non-interactive teardown using `agentcore remove all -y` followed by `agentcore deploy -y -v`. For payload quoting, the authorized repair cycle bypassed CLI shell unquoting by using official AWS CLI `aws bedrock-agentcore invoke-agent-runtime --payload fileb://payload.json`, successfully proving deterministic remote acceptance (`AGENTCORE_OK`).
- Evidence: `docs/P01_04_LIVE_AGENTCORE_EVIDENCE.md`
- Was this operator error, StillDone bug, docs friction, platform bug, limitation, or unknown? CLI / shell argument quoting & non-interactive flag friction
- Actionable suggestion: AgentCore CLI should accept `--payload-json <json>` directly or parse string payloads cleanly across cross-platform shells (especially Windows PowerShell), and dry-run should preview resources without enforcing interactive bootstrap prerequisites.
- Would we build with it again? `YES`
- Secrets/PII check: `CLEAN`


