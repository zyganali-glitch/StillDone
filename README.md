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

Current rules snapshot: `2026-09-29` (re-verified against current official Devpost rules and resources).

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

**P-01 LIVE FEASIBILITY COMPLETED — P-01.01 through P-01.07 PASS; P-01.08 DONE (LIVE FEASIBILITY GO — AWAITING INDEPENDENT QA PASS)**

Foundation and live feasibility status:
- **Phase P-00 (Bootstrap & Governance Baseline)**: Complete and closed (`P-00.01` through `P-00.05`).
- **P-01.01 — Verify AWS account, hackathon credit, billing safety, region, and service-access reality**: Independently passed (`e3d5aa7`). AWS account, promotional credit coverage, billing-risk boundary, and region/service feasibility were reconciled.
- **P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt**: Independently passed (`67bf97a`). Following AWS Support account adjustments and verified `AUTHORIZED` preflight, real Converse inference succeeded against `amazon.nova-micro-v1:0` in `us-east-1` with genuine model response (`pong`, tokens: 11) and zero mutations.
- **P-01.03 — Prove minimal real Strands agent execution against the selected Bedrock model**: Independently passed (`bfa46d2`). Real Strands agent execution proven against `amazon.nova-micro-v1:0` via native `BedrockModel` with prompt `"Reply only with: STRANDS_OK"`, returning genuine response `"STRANDS_OK"` (elapsed: 1179ms).
- **P-01.04 — Prove minimal AgentCore runtime/deployment path or formally reject it with evidence**: Independently passed (`274187c`). Real Bedrock AgentCore Runtime deployed to `us-east-1` (serverless microVM, CodeZip build, Python 3.14, platform version V1). Deterministic acceptance proven in repair cycle via data-plane invoke returning HTTP 200 `{"result": "AGENTCORE_OK"}`. Full teardown completed. Retained CDK bootstrap infrastructure remediated to eliminate customer KMS key charges ($0 ongoing fee).
- **P-01.05 — Prove Google OAuth and live read-only access to dedicated demo Calendar and Tasks resources**: Independently passed (`191eb2b`). Desktop OAuth flow verified with test user. Least-privilege read scopes enforced. Dedicated secondary Calendar `StillDone Demo` and Task List `StillDone Demo` discovered and read. Strictly zero writes, zero token leakage, $0.00 personal spend.
- **P-01.06 — Execute first live Open-Meteo forecast call and record attribution/limit contract**: Independently passed (`0cfac5a`). Executed live Forecast API request against public demo coordinates (Seattle, WA). Received HTTP 200 with 3-day daily forecast arrays. Mandatory CC BY 4.0 display attribution contract recorded (`"Weather data by Open-Meteo.com — CC BY 4.0"`). Non-commercial evaluation tier confirmed.
- **P-01.07 — Validate MCP/Alexa+ current protocol requirements and build a minimal remote Streamable HTTP echo/health proof**: Independently passed (`87232f7`). Built isolated ephemeral MCP server (`@modelcontextprotocol/sdk` v1.31.0 in direct-JSON mode on `/mcp`) exposed over public HTTPS via ephemeral Cloudflare Quick Tunnel. Real MCP client connected, negotiated protocol `2025-11-25`, and called diagnostic `echo` tool with round-trip latency of 61.26ms (< 500ms threshold). Full teardown executed. Alexa+ two-tier auth model cataloged; partner access honestly classified as `NOT_ESTABLISHED`.
- **P-01.08 — Freeze architecture v1 and issue live feasibility GO/BLOCKED decision**: `DONE — LIVE FEASIBILITY GO — awaiting independent QA PASS`. Frozen Architecture v1 with proven AWS stack (Bedrock Nova Micro, Strands, AgentCore Runtime) and explicit rejected/deferred services; frozen Google Calendar/Tasks, Open-Meteo, and remote MCP external boundaries; audited zero-personal-spend feasibility (`ZERO_PERSONAL_SPEND_PATH = CREDIBLE_THROUGH_JUDGING`); broad P-Ω phase-boundary audit passed with zero defects; issued **LIVE FEASIBILITY GO**.
- **Discipline constraints**: Phase P-01 is complete and awaiting independent QA phase closure. Phase P-02 remains locked and `NOT_STARTED` (P-02 MUST NOT START).
- **Product code**: Product/runtime implementation remains intentionally at the minimal bootstrap skeleton; P-02 domain implementation has not started.

See:
- `plans/STILLDONE_MASTER_EXECUTION_PLAN.md`
- `docs/HANDOFF.md`
- `docs/ARCHITECTURE.md`
- `docs/P01_LIVE_FEASIBILITY.md`
- `docs/P_OMEGA_AUDIT_REPORT.md`
- `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md`
- `docs/P01_03_LIVE_STRANDS_EVIDENCE.md`
- `docs/P01_04_LIVE_AGENTCORE_EVIDENCE.md`
- `docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md`
- `docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md`
- `docs/P01_07_LIVE_REMOTE_MCP_EVIDENCE.md`
- `docs/COMPETITION_FEEDBACK_LOG.md`
- `AGENTS.md`
