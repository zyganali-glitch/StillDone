# StillDone

> **Done, and still true.**

StillDone is a desired-state mission runtime for Alexa+ style assistants.

A normal agent can say an action succeeded because a tool returned success. StillDone uses a stricter rule:

> **An outcome is not complete until the resulting state is independently observed, and completion can be revoked if reality later drifts.**

## Canonical product thesis

StillDone turns a natural-language mission into a bounded desired-state contract, executes permitted actions across real services, independently reads back the resulting state, preserves partial failures and `NOT_RUN` honestly, and re-checks the mission later when the user asks whether it is **still done**.

### Canonical killer mission

> **“Get my family ready for tomorrow morning. We need to leave by 7:30.”**

The competition demo targets a dedicated disposable demo calendar and task list:

1. Read tomorrow’s real Google Calendar state.
2. Read real weather from Open-Meteo.
3. Read the real Google Tasks state.
4. Use a real AWS model/agent path to propose a typed mission plan.
5. Compile that plan into deterministic desired-state predicates.
6. Auto-execute safe reversible actions.
7. Ask for one bounded approval for the meaningful existing-calendar change.
8. Execute the approved action.
9. Perform independent read-back calls from the systems of record.
10. Report `READY` only when required predicates are verified.
11. Mutate the calendar externally.
12. Ask: **“Are we still ready?”**
13. Reconcile again and downgrade the mission to `DRIFTED` when reality no longer satisfies the contract.

The demo's wow moment is not that AI performs actions. It is that **the system withdraws its earlier claim when the real world changes.**

## Competition target

**Build, Ship, Shape: Amazon Developer Hackathon**

Primary:
- Alexa+ Track

Secondary:
- AWS Builder Mini Challenge
- Open Source Mini Challenge

Current rules snapshot: `2026-09-20`.

Canonical official rules:
- https://amazonappdev2026.devpost.com/rules
- https://amazonappdev2026.devpost.com/
- https://amazonappdev2026.devpost.com/resources

Alexa+ official developer docs:
- https://developer.amazon.com/docs/alexaplus/add-ons/home.html
- https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html
- https://developer.amazon.com/docs/alexaplus/add-ons/choose-the-proper-alexaplus-integration-approach.html

## Evidence law

StillDone separates **result state** from **evidence provenance**.

Result examples:
- `NOT_RUN`
- `EXECUTED_UNVERIFIED`
- `VERIFIED`
- `CONTRADICTED`
- `BLOCKED`
- `FAILED`
- `STALE`
- `DRIFTED`

Provenance examples:
- `FIXTURE`
- `LOCAL_EXECUTION`
- `LIVE_AWS`
- `LIVE_GOOGLE`
- `LIVE_EXTERNAL`
- `RECORDED_LIVE`

A model may interpret or propose. It may not rewrite deterministic facts.

## Zero-personal-spend policy

Target personal spend: **$0.00**.

Allowed:
- hackathon promotional credits;
- verified free tiers;
- free/open-source local tools;
- free APIs within documented limits.

Forbidden without explicit operator approval:
- paid subscriptions;
- pay-as-you-go continuation beyond promotional/free budget;
- automatic paid fallback;
- unmetered public endpoints that can drain credits.

See:
- `docs/COST_AND_ACCESS_POLICY.md`
- `docs/OPERATOR_REQUIREMENTS.md`

## Current status

**P-01 LIVE FEASIBILITY IN PROGRESS — P-01.01 PASS; P-01.02 PASS; P-01.03 PASS; P-01.04 PASS; P-01.05 DONE (AWAITING INDEPENDENT QA PASS)**

Foundation and live feasibility status:
- **Phase P-00 (Bootstrap & Governance Baseline)**: Complete and closed (`P-00.01` through `P-00.05`).
- **P-01.01 — Verify AWS account, hackathon credit, billing safety, region, and service-access reality**: Independently passed. AWS account, promotional credit coverage, billing-risk boundary, and region/service feasibility were reconciled. Live Bedrock model discovery and account-specific availability diagnosis occurred later under P-01.02.
- **P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt**: Independently passed (Verified SHA: `67bf97a26e3c5a1cea9cb90929cfa390c43b9995`). Following AWS Support account adjustments and verified `AUTHORIZED` preflight, the third bounded execution cycle succeeded with a genuine Amazon Nova Micro response (`pong`), valid token/stopReason metadata, and zero mutations.
- **P-01.03 — Prove minimal real Strands agent execution against the selected Bedrock model**: Independently passed (Verified SHA: `bfa46d24f20c69557f1e747500e874082f1406ed`). Minimal real Strands agent execution proven against `amazon.nova-micro-v1:0` via native `BedrockModel` with synthetic prompt `"Reply only with: STRANDS_OK"`. Model returned genuine response `"STRANDS_OK"` (`stop_reason="end_turn"`, tokens: in=8, out=5, total=13, elapsed=1179ms).
- **P-01.04 — Prove minimal AgentCore runtime/deployment path or formally reject it with evidence**: Independently passed (Verified SHA: `274187c19538e9e9f5f18fe3e2f372a8465cbc91`). Real Bedrock AgentCore Runtime deployed to `us-east-1` (serverless microVM, CodeZip build, Python 3.14, platform version V1) via official `@aws/agentcore` CLI and AWS CLI. Reconciled shared CDK bootstrap infrastructure. Reached `READY` state. Deterministic acceptance proven in authorized repair cycle via official data-plane invocation with binary payload (`{"prompt":"PING"}`), returning HTTP 200 and exact response `{"result": "AGENTCORE_OK"}`. Strictly zero models or LLMs called inside runtime. Complete teardown verified: runtime, CloudFormation stack, and S3 CodeZip asset deleted. Shared CDK bootstrap infrastructure was remediated via official `cdk bootstrap --no-bootstrap-customer-key` to eliminate ongoing customer-managed KMS key charges (transitioned to `PendingDeletion`; no active customer-managed bootstrap key attributable to P-01.04; continuing gross storage cost < $0.000001/mo; actual personal-spend delta `NOT_OBSERVED / UNKNOWN`). All identifiers and private paths sanitized.
- **P-01.05 — Prove Google OAuth and live read-only access to dedicated demo Calendar and Tasks resources**: `DONE — awaiting independent QA PASS`. Desktop app OAuth flow verified with test user over local loopback server (`port 65389`). Minimum read scopes strictly enforced (`calendar.calendarlist.readonly`, `calendar.events.readonly`, `tasks.readonly`). Dedicated disposable secondary Calendar `StillDone Demo` discovered (1 match) and read (0 events). Dedicated disposable Task List `StillDone Demo` discovered (1 match) and read (0 tasks). Strictly zero write operations, zero retries, zero billing/quota changes ($0.00 personal spend). In-memory filtering enforced, zero credentials or tokens committed. Ephemeral tokens deleted from local scratch immediately (`ephemeral_token.json` deleted; remote grant `NOT_REVOKED`).
- **Discipline constraints**: Downstream task `P-01.06` (Open-Meteo weather live read) remains `PENDING / NOT_STARTED` until P-01.05 receives independent QA PASS.
- **Product code**: Product/runtime implementation remains intentionally at the minimal bootstrap skeleton; P-02 domain implementation has not started.

See:
- `plans/STILLDONE_MASTER_EXECUTION_PLAN.md`
- `docs/HANDOFF.md`
- `docs/P01_LIVE_FEASIBILITY.md`
- `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md`
- `docs/P01_03_LIVE_STRANDS_EVIDENCE.md`
- `docs/P01_04_LIVE_AGENTCORE_EVIDENCE.md`
- `docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md`
- `docs/COMPETITION_FEEDBACK_LOG.md`
- `AGENTS.md`
