# StillDone — Judge-Period Availability & Financial-Safety Plan

**Task**: `P-18.07 — Verify judge-period availability plan and credit expiry`  
**Date**: `2026-10-13`  
**Governing Authority**: [AGENTS.md](../AGENTS.md) § 11–13, § 22; [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md); [COMPETITION_CONTRACT.md](COMPETITION_CONTRACT.md)  
**Status**: `IMPLEMENTED / QA_PENDING (Pre-Deployment Planning Only)`  

---

## 1. Executive Intent & Invariants

This plan defines the architectural, operational, and financial framework to ensure StillDone remains fully accessible, inspectable, and verifiable throughout the competition evaluation period without violating the **Zero Personal Spend Law** (`$0.00` personal spend target) or exposing unmetered paid endpoints to public traffic.

> [!IMPORTANT]
> **Planning Contract**:
> This task produces an **implemented architectural plan (QA pending)**, NOT deployed cloud infrastructure, published secrets, activated paid services, or public write-capable endpoints. No infrastructure is provisioned or altered during this task.

---

## 2. Competition Instructions & Requirements Analysis

### 2.1 Official Requirements vs. Recommendations & Assumptions

| Dimension | Official Competition Requirement (Devpost / Rules) | Platform Recommendation / Best Practice | Unverified Assumption (Rejected) |
|---|---|---|---|
| **Submission Deadline** | Friday, October 23, 2026 at 12:00 PM PDT (22:00 Europe/Istanbul, 19:00 UTC) | Video preparation by October 16, 2026 | "Judging requires 24/7 unmetered cloud uptime" (Rejected) |
| **Required Deliverables** | 1. Text description explaining function and architecture<br>2. Video demo (max 3 minutes) demonstrating working solution<br>3. Public code repository URL | Clear setup instructions for local evaluation | "Public judges must be able to trigger unlimited arbitrary paid Bedrock inferences" (Rejected) |
| **Evaluation Period** | November 9–20, 2026 (Winners announced December 2, 2026) | Providing live demo links where feasible | "Hosting must be on custom paid domain" (Rejected) |
| **AWS Usage** | Entrants are solely responsible for all AWS charges; credits requested by Oct 21 | Use promotional credits and free tier | "AWS credits guarantee zero personal spend automatically" (Rejected) |
| **Alexa+ Integration** | Solution addresses Alexa+ / smart assistant context | Model Context Protocol (MCP) Streamable HTTP transport | "Alexa+ partner production certification required before hackathon submission" (Rejected) |

### 2.2 Devpost FAQ vs. Community Forum Live-Hosting Conflict

A direct operational conflict exists between official Devpost FAQ guidance and organizer forum responses regarding whether the hosted MCP endpoint must remain continuously live through judging:

1. **Official Devpost FAQ Policy** ([Devpost FAQs](https://amazonappdev2026.devpost.com/details/faqs)):
   - Indicates that local repository inspection and recorded video demonstration (max 3 minutes) can suffice for judging evaluation.
   - States that hosted MCP endpoints are not mandatory to maintain online 24/7 post-submission.
2. **Devpost Community Forum Organizer Guidance**:
   - [Forum Topic 45493: Question related to production being live of the Alexa MCP server](https://amazonappdev2026.devpost.com/forum_topics/45493-question-related-to-production-being-live-of-the-alexa-mcp-server)
   - [Forum Topic 45411: Must the hosted MCP endpoint stay live through judging](https://amazonappdev2026.devpost.com/forum_topics/45411-must-the-hosted-mcp-endpoint-stay-live-through-judging)
   - In both discussions, organizer responses state that the MCP server needs to remain live and accessible through the end of the judging period (November 9–20, 2026).
3. **Operational Assessment & Unresolved Feasibility**:
   - **Hosting Feasibility Status**: `UNRESOLVED` pending Phase P-19 deployment decision and zero-personal-spend proof.
   - **Accessibility Reality**: On-demand operator-supervised sessions do not necessarily satisfy organizer continuous-accessibility expectations.
   - StillDone distinguishes the static read-only Cloudflare Pages exhibit from genuine remote MCP server availability.
   - Submission artifacts are sanitized of private credentials and tokens prior to the October 23, 2026 12:00 PM PDT deadline.

---

## 3. Historical AWS Credit Records & Balance Uncertainty

### 3.1 Historical Observation (Recorded Live Baseline)
From `docs/COST_AND_ACCESS_POLICY.md` and Phase P-01 evidence:
- **Credit Program**: Amazon Devices Global Hackathon - Teams A4 (`$150.00` promotional credit).
- **Granted Amount**: `$150.00 USD`.
- **Status at Checkpoint (2026-09-27)**: Active; `$0.00` used; `$150.00` remaining.
- **Expiration Date**:
  - AWS Billing detail expiration: `2028-09-01`.
  - Hackathon notification email wording: `2028-08-31`.
  - **Conservative Policy Boundary**: `2028-08-31` (earlier date enforced to prevent premature expiry surprise).
- **Covered Products**: Explicitly confirmed in live Billing "Applicable products" list:
  - `Amazon Bedrock Service`
  - `AmazonBedrockFoundationModels`
  - `Amazon Bedrock`
  - `Amazon Bedrock Managed Knowledge Base`
  - `Amazon Bedrock AgentCore`
- **Secondary Credit**: A separate AWS Free Tier signup credit of `$100.00` (expires `2027-09-27`) was observed, bringing total historical credit balance to `$250.00`.

### 3.2 Credit Balance Uncertainty & Strict Invariants
1. **Uncertainty Principle**: Historical receipts prove past status, NOT current live truth. Current remaining balance and account-wide monthly aggregation are `NOT_OBSERVED` offline.
2. **No Inferred Sufficiency**: An old receipt must never be used to claim guaranteed future credit sufficiency.
3. **No Automatic Hard Cap**: AWS promotional credits offset billed invoice lines; they do **NOT** act as a hard kill-switch or quota cap. If credits exhaust, AWS automatically transitions into pay-as-you-go billing.
4. **Zero Personal Spend Law**: Maximum personal spend is strictly `$0.00`. Unbounded or unmetered paid services are strictly forbidden.

---

## 4. Safe Dual-Surface Availability Architecture

StillDone separates public evaluation from live execution across two distinct surfaces:

```
+-------------------------------------------------------------------------+
| SURFACE 1: PUBLIC READ-ONLY EXHIBIT                                     |
| Cloudflare Pages Free (*.pages.dev)                                     |
| - $0.00 cost / No domain purchase / No billing exposure                 |
| - Static evidence, audit logs, receipt hashes, video walkthrough        |
| - Reproducible verification viewer & clean-checkout instructions        |
| - NO Python execution / NO live Bedrock calls / NO write operations     |
+-------------------------------------------------------------------------+
                                    |
                                    | (Completely decoupled)
                                    v
+-------------------------------------------------------------------------+
| SURFACE 2: AUTHENTICATED OPERATOR RUNTIME                               |
| Streamable HTTP MCP Server & Bedrock Runtime                            |
| - Operator authentication mandatory (SigV4 / OAuth token)               |
| - Enforced rate limits (P-18.04): Persistent SQLite fixed-window limiter |
| - Non-paid MCP tools: mission_start (DRAFT) and mission_status only      |
| - Middleware classifies incoming requests as NO_PAID_CAPABILITY         |
| - Paid-capable admission contracts tested; live wiring NOT_INTEGRATED   |
| - No AWS billing hard cap provided by internal admission limiter        |
| - Primary judge review via video & repository; on-demand execution only |
| - Endpoint protection gate: live_paid_path_enabled=False fails closed   |
| - NO public unmetered access / NO anonymous paid paths                  |
+-------------------------------------------------------------------------+
```

### 4.1 Surface 1: Public Read-Only Judge Exhibit (Cloudflare Pages Free)
- **Platform**: Cloudflare Pages (Free Tier).
- **Domain Strategy**: Default `*.pages.dev` subdomain. Zero domain purchase, zero renewal fees ($0.00 personal spend).
- **Execution Capability Boundary**:
  - Cloudflare Pages serves strictly static assets (HTML5, CSS, client-side JS, pre-rendered JSON receipts, Markdown evidence, video).
  - Cloudflare Pages does **NOT** execute the Python backend, Python runtimes, or Streamable HTTP MCP server.
  - Public visitors cannot initiate real AWS Bedrock inference, Google Calendar mutations, or Google Tasks mutations.
- **Judge Experience on Surface 1**:
  - Interactive mission walkthrough with pre-computed recorded live proofs.
  - Cryptographic verification of historical receipts (`receipt_hash` validation).
  - High-resolution demo video embedded.
  - Reproducibility guide with copy-paste terminal commands to run local fixture verification.

### 4.2 Surface 2: Authenticated Operator-Only Execution Runtime
- **Transport**: Streamable HTTP MCP server.
- **Admission Protection** (Enforced in `P-18.04`):
  - Current MCP tools are non-paid `mission_start` and `mission_status`.
  - Rate limits: Persistent SQLite fixed-window rate limiter (`RateLimitMiddleware`, `SqliteRateLimitStore`, configured profile default: `max_requests_per_window=10` per 60-second window fail-closed; general `MCPServerConfig` rate protection is optional unless explicitly configured).
  - Incoming requests are evaluated as `NO_PAID_CAPABILITY / PUBLIC_UNTRUSTED`.
  - Paid-capable admission contracts are tested, but actual paid runtime wiring remains `NOT_INTEGRATED / NOT_AUTHORIZED`.
  - No AWS billing hard cap is provided by these internal rate-limiting admission controls.
  - Atomic persistent SQLite tracking under concurrency.
  - Fail-closed behavior on missing or stale budget snapshots.
- **Judge Interaction Model**:
  - Official judging proceeds via public repository review and recorded video demonstration (max 3 minutes).
  - Runtime is NOT kept running 24/7 unmetered.
  - Hosting feasibility remains `UNRESOLVED` pending Phase P-19 deployment decision.
  - Supervised on-demand execution sessions do not necessarily satisfy organizer continuous-accessibility expectations.

---

## 5. Bounded Fallback Plan

If continuous cloud hosting or remote MCP execution cannot be proven 100% safe at `$0.00` personal spend:

1. **Fallback Tier 1 — Static Exhibit & Video (Always Available)**:
   - Cloudflare Pages static exhibit (`*.pages.dev`) remains online indefinitely at zero cost.
   - Demo video (max 3 minutes) serves as the primary visual proof of live technology.
   - Complete historical evidence logs (`docs/P*_EVIDENCE.md`) demonstrate technological implementation.

2. **Fallback Tier 2 — Clean-Checkout Local Reproduction**:
   - Judges or evaluators clone the repository: `git clone https://github.com/zyganali-glitch/StillDone.git`.
   - Setup requires Python 3.13 and installing project dependencies via pinned lockfile (`uv sync` or `pip install -e .`).
   - Run deterministic single-command offline reproduction: `python scripts/p18_benchmarks.py --all`.
   - 100% offline fixture verification passes with zero external credentials, zero network dependencies, and zero cost.

3. **Fallback Tier 3 — Operator-Assisted Live Verification Session**:
   - If an evaluator requests live interactive interaction with the Alexa+ / MCP endpoint, the operator schedules a bounded, time-limited live window.
   - Operator monitors live credit consumption in real time and terminates the instance immediately upon completion.

---

## 6. Pre-Submission Verification & Safety Checklist

- [x] Official Devpost hackathon rules rechecked regarding submission deliverables and dates.
- [x] Official AWS promotional credit terms rechecked; conservative expiry boundary set to `2028-08-31`.
- [x] Credit balance uncertainty acknowledged; current account charges marked `NOT_OBSERVED` offline.
- [x] Cloudflare Pages Free tier selected without domain purchase ($0.00).
- [x] Cloudflare Pages boundary verified: static-only exhibit, no Python backend execution.
- [x] Public read-only exhibit separated from authenticated operator-only execution.
- [x] Rate limits and endpoint protection verified (P-18.04).
- [x] Bounded three-tier fallback plan documented.
- [x] Zero infrastructure deployed; zero secrets committed; zero paid services activated in this task.
