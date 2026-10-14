# P-20.03 — Claim-by-Claim Evidence Manifest

**Document ID**: `docs/P20_03_EVIDENCE_MANIFEST.md`  
**Task**: `P-20.03 — Build claim-by-claim evidence manifest`  
**Governing Authority**: `AGENTS.md` § 3 (Closure Contract), § 4 (Core Product Invariant), § 10 (Evidence Provenance); `plans/STILLDONE_MASTER_EXECUTION_PLAN.md` § P-20.03  
**Source Commitment**: All claims bound to verified repository commit SHAs and durable evidence logs.  

---

## 1. Evidence Provenance Classification

Per `AGENTS.md` § 10, every technical claim is bound to one of six canonical provenance classes:

- **`LIVE_AWS`**: Real, unsimulated execution against Amazon Bedrock Nova Micro or Bedrock AgentCore Runtime.
- **`LIVE_GOOGLE`**: Real, unsimulated execution against Google Calendar v3 or Google Tasks v1 APIs under operator OAuth authorization.
- **`LIVE_EXTERNAL`**: Real HTTP API call to external public endpoints (e.g., Open-Meteo weather API).
- **`RECORDED_LIVE`**: Authentic, dated historical execution records with exact timestamps, raw provider responses, and hashes committed in `docs/`. Never promoted to fresh current-live calls.
- **`FIXTURE`**: Deterministic, offline execution using local simulated providers or pre-seeded test fixtures with zero network calls and zero credentials.
- **`LOCAL_EXECUTION`**: Deterministic execution of pure domain, verification, cryptographic, or ledger algorithms on the local workstation / CI runner.
- **`NOT_RUN` / `BLOCKED`**: Operations deliberately unexecuted to prevent unmetered billing or unauthorized cloud mutations.

---

## 2. Claim-by-Claim Audit Table

| # | Material Submission Claim | Provenance Class | Source Code Location | Automated Test Suite | Durable Evidence / Script | Negative Bound / Limitation |
|---|---|---|---|---|---|---|
| **C-01** | **Core Invariant**: Execution success does not equal verification; mutations require independent read-back and predicate evaluation. | `LOCAL_EXECUTION` & `RECORDED_LIVE` | `src/stilldone/verifier/` `src/stilldone/domain/` | `tests/test_verifier_predicates.py` `tests/test_verifier_readiness.py` | `docs/EVIDENCE_AND_STATE_CONTRACT.md` `scripts/p11_06_proof.py` | A tool success HTTP 200 never sets `is_verified=True`. |
| **C-02** | **Drift Law**: Mission `READY` state can be revoked and downgraded to `DRIFTED` if external reality later contradicts intent. | `LOCAL_EXECUTION` & `RECORDED_LIVE` | `src/stilldone/drift.py` `src/stilldone/verifier/reconciliation.py` | `tests/test_verifier_reconciliation.py` `tests/test_phase_p12_04_calendar_drift.py` | `docs/P13_KILLER_MISSION_AUDIT.md` `docs/PRODUCT_CONTRACT.md` | Historical receipt remains immutable; current state reflects reality. |
| **C-03** | **Immutable Receipt**: Issuance produces a domain-separated SHA-256 receipt projection permanently bound to verified predicates. | `LOCAL_EXECUTION` | `src/stilldone/receipt.py` `src/stilldone/domain/lifecycle.py` | `tests/test_receipt.py` `tests/test_phase_p03_adversarial.py` | `docs/EVIDENCE_AND_STATE_CONTRACT.md` § 4 | Unverified or contradictory steps fail closed with `UNISSUED`. |
| **C-04** | **Human Approval Boundary**: High-impact calendar mutations halt at execution boundary; require single-use cryptographic grant. | `LOCAL_EXECUTION` & `RECORDED_LIVE` | `src/stilldone/authority_policy.py` `src/stilldone/domain/authority.py` | `tests/test_phase_p11_02_pending_approval.py` `tests/test_phase_p11_03_approval_binding.py` | `docs/P11_05_CALENDAR_UPDATE_NOT_RUN_BEFORE_APPROVAL_EVIDENCE.md` | Plaintext "yes" in chat cannot authorize without bound grant object. |
| **C-05** | **Zero Personal Spend ($0.00)**: All development, testing, and judge exhibits executed with zero personal expenditure. | `RECORDED_LIVE` & `LOCAL_EXECUTION` | `scripts/validate.py` `src/stilldone/config.py` | `tests/test_phase_p18_04_budget_rate_limits.py` `tests/test_phase_p18_05_quota_safety.py` | `docs/COST_AND_ACCESS_POLICY.md` `docs/P19_03_OPERATOR_AWS_OBSERVATIONS_2026-10-14.md` | AWS usage covered by promotional credit; Google within free quotas. |
| **C-06** | **Open Streamable HTTP MCP Server**: Real MCP server conforming to Model Context Protocol specification over Streamable HTTP on `/mcp`. | `LOCAL_EXECUTION` & `RECORDED_LIVE` | `src/stilldone/mcp/server.py` `src/stilldone/mcp/protocol.py` | `tests/test_mcp_server.py` `tests/test_mcp_mission_start.py` `tests/test_mcp_mission_status.py` | `docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md` `docs/P01_07_LIVE_REMOTE_MCP_EVIDENCE.md` | Tested locally on loopback; deployed microVM torn down immediately. |
| **C-07** | **Real Amazon Bedrock Nova Micro Inference**: Real Converse API execution with Amazon Nova Micro in `us-east-1` for multi-step proposal compilation. | `RECORDED_LIVE` (`LIVE_AWS`) | `src/stilldone/planning/bedrock.py` `src/stilldone/planning/strands_agent.py` | `tests/planning/test_bedrock_adapter.py` `tests/planning/test_strands_agent.py` | `docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md` (Dated 2026-10-06) | Zero model authority; proposals strictly parsed deterministically. |
| **C-08** | **Dual-Runtime Environment Isolation**: Core/MCP runtime (`mcp==2.2.0`) and Strands Planner runtime (`strands-agents==1.57.2`) isolated with 0 resolver overrides. | `LOCAL_EXECUTION` | `pyproject.toml` `runtimes/strands_planner/pyproject.toml` | `scripts/validate.py` `.github/workflows/ci.yml` | `docs/HANDOFF.md` § Architecture Truth — Dependency Isolation | Resolves upstream `mcp<2.2` pinning without dependency tampering. |
| **C-09** | **Real Google Calendar & Tasks Integration**: Real OAuth mutations and independent read-backs against dedicated StillDone demo resources. | `RECORDED_LIVE` (`LIVE_GOOGLE`) | `src/stilldone/adapters/calendar.py` `src/stilldone/adapters/tasks.py` | `tests/test_calendar_read_adapter.py` `tests/test_calendar_update_adapter.py` `tests/test_tasks_read_create_adapter.py` | `docs/P06_07_LIVE_TASKS_VERIFIED_EVIDENCE.md` `docs/P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md` | Bounded to dedicated test calendars; no production data touched. |
| **C-10** | **Simulated Alexa+ Surface & Public Judge Exhibit**: Accessible static exhibit deployed on Cloudflare Pages (`*.pages.dev`) with WCAG AA contrast. | `FIXTURE` & `OPERATOR_OBSERVED` | `src/stilldone/judge_ux/` `scripts/p19_04_build_judge_exhibit.py` | `tests/test_phase_p15_judge_ux.py` `tests/test_phase_p19_04_public_judge_exhibit.py` | `https://stilldone-judge-exhibit.pages.dev` `docs/P19_04_PUBLIC_JUDGE_EXHIBIT.md` | Labeled `SIMULATED ALEXA+ EXPERIENCE`; no live backend on static site. |
| **C-11** | **Idempotent Mutation & Deduplication**: Safe retry policies; ambiguous timeouts trigger read-before-retry to prevent duplicate calendar/task entries. | `LOCAL_EXECUTION` | `src/stilldone/recovery/` `src/stilldone/domain/execution.py` | `tests/test_recovery_idempotency.py` `tests/test_recovery_campaign.py` | `docs/KILLER_DEMO_CONTRACT.md` `docs/HANDOFF.md` § Phase P-10 | Crash-resilient durable file ledger with replay rejection. |
| **C-12** | **Privacy Minimization**: Zero secrets committed; emails, tokens, and PII automatically sanitized and redacted. | `LOCAL_EXECUTION` | `src/stilldone/evidence.py` `src/stilldone/redaction.py` | `tests/test_redaction.py` `tests/test_phase_p04_security_audit.py` | `docs/SECURITY_AND_PRIVACY.md` `docs/P04_SECURITY_THREAT_MODEL_AUDIT.md` | Hostile credential discovery blocked via environment stripping. |
| **C-13** | **Zero Donor Code Import**: 100% clean-room reimplemented; 0 donor source lines imported. | `LOCAL_EXECUTION` | `src/stilldone/` (entire tree) | `tests/test_phase_p20_claim_audit.py` | `docs/DONOR_PROVENANCE.md` (P-00.03 through P-20.06) | All 9 donor repositories remain strictly `CONCEPT_ONLY`. |

---

## 3. Negative Claims & Explicit Non-Capabilities

In compliance with competition integrity rules, StillDone explicitly disclaims the following non-capabilities:

1. **No Live Backend on Public Exhibit**:
   The deployed site at `https://stilldone-judge-exhibit.pages.dev` is a **100% read-only, client-side static HTML exhibit**. Web visitors cannot trigger live Google Calendar writes, AWS Bedrock inferences, or AgentCore invocations from their browser.
2. **Alexa+ Partner Access is NOT_ESTABLISHED**:
   Direct internal Amazon Alexa+ partner client access was not granted during the hackathon. The Alexa+ interface is provided as a faithful **simulated client experience** clearly labeled as `SIMULATED ALEXA+ EXPERIENCE`.
3. **Current Remote Deployment is BLOCKED / NOT_RUN**:
   While the Bedrock AgentCore serverless microVM was proved live in P-05.06 and torn down cleanly, a permanent, unmetered public cloud endpoint is deliberately **not maintained** in order to enforce the Zero Personal Spend Law ($0.00).
4. **Complete 7-Step Killer Demo in Exhibit is FIXTURE Playback**:
   The 7-step sequence shown in `artifacts/judge_exhibit/index.html` replays the canonical killer mission outcome in deterministic **FIXTURE regression mode**, verified against authentic contract invariants. Authentic live calls are preserved separately in `docs/` as `RECORDED_LIVE`.

---

*Verified claim manifest committed under P-20.03.*
