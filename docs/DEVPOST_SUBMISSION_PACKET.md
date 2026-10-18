# DEVPOST SUBMISSION PACKET — StillDone

**Document ID**: `docs/DEVPOST_SUBMISSION_PACKET.md`
**Purpose**: THIS document is the ONE place from which the operator and independent QA obtain all final Devpost materials for the *Build, Ship, Shape: Amazon Developer Hackathon*. No reconstruction of previous conversations is needed.
**Competition**: Build, Ship, Shape: Amazon Developer Hackathon — https://amazonappdev2026.devpost.com
**Primary Track**: Alexa+ | **Mini Challenges**: AWS Builder; Open Source (conditional — see § G)
**Packet prepared**: 2026-10-18 (Türkiye time) by the coding agent; single consolidated submission-preparation batch (P-21 + P-22).
**Canonical candidate SHA**: `da7a518b463f08d15e8787eaf4a1aa0a4e04d3b4` at packet preparation start; final packet commit SHA recorded in § M.
**Status of this packet**: `COMPLETED` except items explicitly marked `OPERATOR_ACTION_REQUIRED`, `NOT_RUN`, or `UNCONFIRMED`.

---

## A. OPERATOR QUICK-START — WHAT TO PASTE FIRST

You only need to do copy/paste work. Do not rewrite any block unless your own written English is good and the truth does not change.

1. Log in at https://amazonappdev2026.devpost.com (or create the free Devpost account). Press **Join hackathon** if not already joined.
2. From the hackathon page, click **Enter a Submission**. Devpost will show its own form. The exact labels Devpost uses in the form have not been observed by the coding agent (the form is login-protected), so ALL field mappings in this packet are **PROVISIONAL suggestions only** — match each block to the form element whose description it fits. Nothing here requires you to type new English.
3. Paste in this order:
   - **Project title** → § D.1
   - **Short description / elevator pitch** → § D.2 (172 characters)
   - **Submission video link** → `https://youtu.be/c-c_cUzq1OM`
   - **GitHub repository URL** → `https://github.com/zyganali-glitch/StillDone`
   - **Primary track selection** → **Alexa+**
   - **Mini Challenge selection** → **AWS Builder** (definitely) and **Open Source** (ONLY if § G eligibility gate is confirmed — otherwise skip Open Source)
   - **Long story / about fields** → § D.3–§ D.11 (split across the story fields)
   - **Alexa+ supplemental answer** → § E (into any field that asks about the Alexa+ track / MCP — used inside the story if no dedicated box exists)
   - **AWS Builder answer** → § F + the "AWS services used and how" block of § H.1 (the rules require the services description inside Product Feedback — see § H.1)
   - **Open Source answer** → § G (ONLY if the gate is confirmed)
   - **Product Feedback** → § H.1–§ H.5
   - **Friction log entries** → § H.7 (optional, bonus up to 10%)
   - **Optional feature requests** → § H.8
   - **Screenshots** → upload the 8 files listed in § I, one caption each
   - **Testing instructions** → § J (`Copy-ready judge testing instructions`)
4. Before clicking Submit, walk the § M checklist with your independent QA person.
5. Judge access needs NO credentials: repository is public, Apache-2.0; the judge exhibit link is public. Nothing in the form should contain secrets, tokens, keys, or personal files.

**English**: All copy in this packet is ready English. You do not need to write English anywhere except simple form selections.

---

## B. OFFICIAL REQUIREMENTS & GO/NO-GO MATRIX

**Source observed**: current official rules page https://amazonappdev2026.devpost.com/rules — **observed 2026-10-18** (Turkey time) via a logged-out browser session; the same page also displays the hackathon deadline banner (`23 Eki 2026 @ 10:00pm GMT+3`). Full rules text was extracted in-session; key facts below were read from the live page. The Devpost *submission form* itself is login-gated; form field labels remain **PROVISIONAL** until you observe them during entry.

| # | Official requirement (rules text) | StillDone status | Evidence | Go/No-Go |
|---|---|---|---|---|
| 1 | Deadline October 23, 2026, 12:00 pm PT | Deadline confirmed; submission not yet made | Rules page (§ M.1) | **NO-GO until you submit on time** |
| 2 | Project video **less than 3 minutes**, publicly visible on YouTube or Vimeo | YouTube video public & playable; **player-reported length 179 s = 2:59 < 3:00** | § K (verified 2026-10-18) | **GO** |
| 3 | Video shows project functioning on the intended platform | Video shows the StillDone deterministic exhibit (the judge-facing product surface) with simulated Alexa+ labeling; actual content composition operator-reported, not independently frame-reviewed | § K limitations | **GO (with stated limitation)** |
| 4 | No third-party trademarks / copyrighted music without permission | Metadata-level safety only; visual/audio review not performed by agent; narration & visuals are operator-produced originals operating on a public web page | § K limitations | **GO (limitation recorded)** |
| 5 | All materials in English | Video narration English (operator-reported); description title/description English; repo docs English | § K | **GO** |
| 6 | Text description explaining features & functionality | § D complete | This packet | **GO** |
| 7 | Public GitHub repo with open-source license, license visible in About section | Public repo, Apache-2.0, license detected by GitHub API (`apache-2.0`) | § C.3, § L | **GO** (optional About polish in § M.2) |
| 8 | Repo contains all source, assets, and setup/run instructions | `docs/REPRODUCTION.md` + `README.md` Quick Start; clean-checkout repro verified today | § J, § L | **GO** |
| 9 | Runtime-technology hook (Alexa+): Agent Skill or **self-hosted MCP server implementing MCP spec ≥ 2025-11-25 over Streamable HTTP**, imported and actually called at runtime — **or** the simulated-Alexa+ alternate path (exempt from runtime hook; simulation source in repo; video clearly shows simulated experience) | Both paths covered: (a) real Streamable HTTP MCP server spine in code (`src/stilldone/mcp/server.py`), proven live incl. protocol `2025-11-25` handshake (RECORDED_LIVE); (b) clearly labeled **SIMULATED ALEXA+ EXPERIENCE** in exhibit + video, full source in repo | § E, docs/P20_03, P20_05 | **GO** |
| 10 | AWS Builder Mini Challenge: project incorporates AWS services with documented integrations; services described in Product Feedback | Bedrock Nova Micro + Strands 1.57.2 + AgentCore Runtime integration, documented & dated | § F, § H.1 | **GO** |
| 11 | Open Source Mini Challenge: NEW additional open-source project or contribution to an existing public repo **during the hackathon window**; requires contribution URL, project repo URL, GitHub username, what/how/why | Gate UNCONFIRMED — no publication of `mcp-verify`; one plausible qualifying candidate (`Basebreak`) exists; operator decision required | § G | **CONDITIONAL** |
| 12 | Product Feedback (5 sub-questions) | § H.1–§ H.5 complete | This packet; docs/P20_01 | **GO** |
| 13 | Optional friction logs (up to 10% bonus) | § H.7 ready; full authentic log preserved in repo | docs/COMPETITION_FEEDBACK_LOG.md | **GO** |
| 14 | Optional feature requests with priority rating | § H.8 ready | This packet | **GO (optional)** |
| 15 | Project accessible to judges free of charge until Judging Period ends (Nov 9–20, 2026) | Public repo + public YouTube + public exhibit; offline repro needs no credentials; judge-period uptime of hosted exhibit NOT GUARANTEED (disclosed) | § J, § L | **GO** |
| 16 | Judging: Stage 1 pass/fail viability → Stage 2 four criteria 25% each; tie-break priority | Criteria copy aligned in § D/F/G | docs/P20_04 | **GO** |
| 17 | AWS promotional credit requests | Not needed; official update states codes exhausted since Oct 7 — no action | Rules page | N/A |

**Rule texts actually observed (verbatim key excerpts, 2026-10-18)**:
- Submission Period: *Monday, August 31, 2026 (10:15 am Pacific Time) – Friday, October 23, 2026 (12:00 pm Pacific Time).*
- Judging Period: *Monday, November 9, 2026 (12:00 pm Pacific Time) – Friday, November 20, 2026 (12:00 pm Pacific Time).*
- Video: *"...should be less than three (3) minutes... must be uploaded to and made publicly visible on YouTube or Vimeo... and must not include third party trademarks, or copyrighted music or other material unless the Entrant has permission..."*
- Language: *"All Submission materials (demo video, written description, and code documentation) must be in English or, if not in English, the Entrant must provide an English translation..."*
- Repository: *"Provide a URL to your code repository for judging and testing on GitHub... public and open source by including an open source license file... For public repositories: this license should be detectable and visible at the top of the repository page (in the About section)."*
- Alexa+: *"A working Agent Skill or a self-hosted MCP server, implementing MCP spec version 2025-11-25 (or a later version, once confirmed) over Streamable HTTP. Alternatively, entrants may submit a simulated Alexa+ experience instead... This alternate path is exempt from the runtime-technology-hook requirement above; the code repository must still include the simulation's source code, and the demo video must clearly show the simulated experience."*
- Open Source: *"Create a new, additional open-source project or contribute to an existing public repository during the hackathon window, alongside a primary track submission. Contributions can be a new repo (with open-source license), a branch, a fork, or a pull request. PRs do not need to be merged; share your forked version if unmerged. Required: contribution URL, project repository URL, GitHub username, and a description of what you did, how it works, and why it matters."*

---

## C. PUBLIC LINKS (all verified reachable; details in § K)

1. **Submission video (YouTube)**: https://youtu.be/c-c_cUzq1OM
   - Equivalents: https://www.youtube.com/watch?v=c-c_cUzq1OM · embed: https://www.youtube.com/embed/c-c_cUzq1OM
   - Channel (video author): Mehmet Aydoğan — https://www.youtube.com/@mehmetaydogan9261
2. **Live judge exhibit (Cloudflare Pages)**: https://stilldone-judge-exhibit.pages.dev
   - Local clone fallback: `artifacts/judge_exhibit/index.html` and single-file `artifacts/stilldone_judge_exhibit.html`
3. **Source repository**: https://github.com/zyganali-glitch/StillDone (public, Apache-2.0, branch `main`)
4. **Judge reproduction guide**: https://github.com/zyganali-glitch/StillDone/blob/main/docs/REPRODUCTION.md
5. **Evidence manifest (claim-by-claim)**: https://github.com/zyganali-glitch/StillDone/blob/main/docs/P20_03_EVIDENCE_MANIFEST.md
6. **Provenance disclosure (fixture/live/simulated)**: https://github.com/zyganali-glitch/StillDone/blob/main/docs/P20_05_EVIDENCE_PROVENANCE_DISCLOSURE.md
7. **Dated live integration evidence (RECORDED_LIVE)**:
   - Bedrock Nova Micro + Strands: https://github.com/zyganali-glitch/StillDone/blob/main/docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md (also `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md`)
   - AgentCore Runtime remote MCP: https://github.com/zyganali-glitch/StillDone/blob/main/docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md
   - Google Calendar approved update + read-back: https://github.com/zyganali-glitch/StillDone/blob/main/docs/P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md
   - Google Calendar not-run-before-approval proof: https://github.com/zyganali-glitch/StillDone/blob/main/docs/P11_05_CALENDAR_UPDATE_NOT_RUN_BEFORE_APPROVAL_EVIDENCE.md
   - Google Calendar live read: `docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md` · `docs/P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md`
   - Google Tasks verified: https://github.com/zyganali-glitch/StillDone/blob/main/docs/P06_07_LIVE_TASKS_VERIFIED_EVIDENCE.md
   - Open-Meteo: https://github.com/zyganali-glitch/StillDone/blob/main/docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md · `docs/P06_06_LIVE_WEATHER_FINAL_CLOSURE_EVIDENCE.md`
8. **Product feedback & friction log**: https://github.com/zyganali-glitch/StillDone/blob/main/docs/P20_01_AWS_PRODUCT_FEEDBACK.md · https://github.com/zyganali-glitch/StillDone/blob/main/docs/COMPETITION_FEEDBACK_LOG.md
9. **Screenshot galleries (committed on main)**: `docs/assets/devpost/` (8 files, § I) and `docs/assets/readme/` (10 files)
10. **Judging-criteria map**: `docs/P20_04_JUDGING_CRITERIA_MAP.md` · **Canonical demo script**: `docs/P21_01_DEMO_SCRIPT_AND_SHOT_LIST.md` · **Media registry**: `docs/DEMO_MEDIA_AND_SUBMISSION_COPY.md`

---

## D. COMPLETE DEVPOST ENGLISH COPY (PROJECT FIELDS)

### D.1 Project title

```text
StillDone — Done, and still true.
```

(If the form prefers a descriptive title, use: `StillDone — Verified AI Missions, Even After Drift`)

### D.2 Short description / elevator pitch (172 characters, ≤ 200)

```text
StillDone verifies outcomes instead of trusting agent claims. It executes approved actions, reads reality back independently, issues durable receipts, and reconciles drift.
```

### D.3 Elevator pitch (longer variant for fields asking "what is it in one paragraph?")

```text
Today's AI assistants report "done" the moment a tool call returns success. StillDone is a desired-state mission runtime for Alexa+-style assistants that refuses to award completion until the real external state has been independently read back and checked against deterministic predicates — and that revokes completion and reports DRIFTED when reality later drifts.
```

### D.4 Story — Inspiration

```text
StillDone started from a simple observation: AI trust is inverted. An assistant gets a "200 OK" from a calendar API and immediately tells the user "You're all set!" — but the event may not exist, may be a duplicate, or may silently move from 7:30 to 8:00 later that evening. Ordinary agents verify the protocol, never the world.

The canonical scenario is every parent's morning: "Get my family ready for tomorrow morning. We need to leave by 7:30." A tool success does not prove the family is ready, and 12 hours later the proof that was true at midnight can be false at breakfast. We wanted an assistant that treats "done" as a claim to be proven now and re-proven later — which is why the tagline is: Done, and still true.
```

### D.5 Story — What it does

```text
StillDone turns a natural-language mission into a bounded desired-state contract with deterministic predicates and freshness rules. It observes ground truth first (Google Calendar, Google Tasks, Open-Meteo weather), asks Amazon Bedrock Nova Micro to propose a typed plan with ZERO execution authority, executes only what the frozen authority policy allows (safe reversible actions auto-run; the high-impact calendar change pauses fail-closed for one single-use human approval), then performs a separate independent read-back from the systems of record and evaluates mathematical predicates. Only verified evidence can promote a mission to READY, producing an immutable SHA-256 receipt.

The wow moment is not that the AI performs actions — it is that StillDone withdraws its earlier claim. When someone externally moves the departure to 8:00 AM, asking "Are we still ready?" triggers a fresh read-back, detects the contradiction, downgrades current truth to DRIFTED, explains exactly what changed, and leaves the historical READY receipt untouched as immutable audit evidence.
```

### D.6 Story — How we built it

```text
StillDone pairs a real AWS reasoning path with a deterministic authority core, connected by an open standard:

- Model Context Protocol: a self-hosted MCP server over Streamable HTTP built with the official mcp 2.2.0 Python SDK — typed mission_start/mission_status tools, RFC 9728 Protected Resource Metadata, SQLite-WAL-backed rate limiting, and an Alexa+ 401-header-compatibility middleware. It successfully negotiated MCP protocol version 2025-11-25 over public HTTPS, and ran live on a Bedrock AgentCore Runtime serverless microVM in us-east-1 where mission_start/mission_status and tools/list executed remotely (authenticated with MCP Inspector via a SigV4 signing bridge), then was torn down cleanly to preserve $0.00 spend.
- Amazon Bedrock: real inference with amazon.nova-micro-v1:0 in us-east-1 via the Converse API, orchestrated through the Strands Agents SDK (1.57.2) in a strictly separated planner environment. The model proposes plans; it can never verify facts, mutate state, or declare READY ("The Model Proves Nothing" law).
- Google Calendar + Google Tasks: real OAuth integrations against dedicated disposable demo resources — reads, one approved update (7:45 → 7:30), task creation ("Pack backpacks"), each verified through independent read-backs.
- Open-Meteo: real weather reads within its free, non-commercial terms.
- Deterministic core: desired-state predicates, freshness contracts, idempotent mutations with read-before-retry on ambiguous timeouts, append-only evidence ledger with content-addressed SHA-256 evidence IDs, and a five-class fail-closed authority table (READ_ONLY / REVERSIBLE_AUTO / REVERSIBLE_APPROVAL_REQUIRED / EXTERNAL_COMMUNICATION / IRREVERSIBLE).
- Evidence culture: everything on a judge-side page is provenance-labeled - FIXTURE (deterministic offline replay of the exhibit), LOCAL_EXECUTION (local deterministic code runs), RECORDED_LIVE (dated, hash-preserved live AWS/Google/Open-Meteo runs committed in docs/), and SIMULATED ALEXA+ EXPERIENCE (the clearly labeled simulated client surface the rules permit). Nothing live is presented as freshly live; nothing simulated is hidden.
- Verification engineering debt: 3,700+ automated tests pass across two isolated Python runtimes (Core/MCP with mcp 2.2.0; Strands planner with strands-agents 1.57.2 with its transitive mcp 2.1.1 — no resolver overrides), including adversarial campaigns for replay, tampering, timeout-after-write duplicates, prompt injection against plan compilation, approval forgery, and Unicode collision attacks.
```

### D.7 Story — Challenges and how we solved them

```text
1. Unsolvable dependency math: strands-agents 1.57.2 requires mcp < 2.2 while StillDone's server required mcp >= 2.2. Instead of hacky overrides, we hard-partitioned the repo into two isolated uv environments with zero resolver overrides and full CI validation of both.
2. "Verification without trust in the model": the tempting shortcut is to let the LLM self-certify. We replaced it with verifiers that are mathematically separated from executors — a write success is never verification; a distinct read adapter must read back the external state and predicates evaluate deterministically.
3. Ambiguous failures cause duplicates: a timeout after a write can cause double bookings on naive retries. StillDone's idempotency design (natural in-place calendar updates, client-token deduplication for tasks, read-before-retry, durable append-only JSONL ledger with crash recovery) prevents the second effect.
4. Approval fatigue vs. safety: endless confirmations are unusable; silent auto-execution is dangerous. A five-class authority policy compresses human attention into exactly one bounded, single-use approval for the one high-impact action, cryptographically bound to mission, action, parameters, target, and expiry — replays are strictly rejected.
5. Zero-cost discipline: everything was built and verified within hackathon promotional credits and free tiers; after proving the live remote MCP path we deliberately tore it down rather than leaving a metered endpoint running.
```

### D.8 Story — Accomplishments (what works)

```text
- A real, dated, hash-preserved live integration trail: live Bedrock Nova Micro inference through a bounded Strands planner; live AgentCore microVM serving the MCP server over Streamable HTTP; live Google Calendar/Tasks mutations each independently read back and VERIFIED; live Open-Meteo reads — all preserved as RECORDED_LIVE evidence in the repository, never inflated into fresh-live claims.
- A complete deterministic demonstration: the full 7-step mission (pre-state → plan → task creation → approval pause → approved verified calendar shift → READY with SHA-256 receipt → DRIFT epoch and fresh reconciliation) runs as a public, offline fixture exhibit that any judge can open in a browser in under two minutes.
- A developer artifact extracted from the thesis: mcp-verify, a zero-dependency Apache-2.0 middleware package that enforces the same Execute → Independent Read-back → Predicate → VERIFIED chain for any MCP tool.
```

### D.9 Story — What we learned

```text
- Truth needs plumbing, not prose: separating "the tool said ok" from "the world matches intent" forced us to invent real primitives — content-addressed evidence IDs, domain-separated receipt hashes, freshness contracts, and drift reconciliation. The insights generalize far beyond calendars: any delegated real-world work needs an independent read-back chain.
- The drift problem is the overlooked half of agent autonomy: everyone designs for the moment of mutation; almost nobody designs for the moment the world changes afterward. Making READY revocable turned out to be the most original part of the product.
- Nice layers cost nothing if they are bounded: Bedrock Nova Micro's fractions-of-a-cent pricing and fast planner latency (recorded 264 ms model latency on the live Strands planner call, ~1.2 s end-to-end wall clock in the live probe) make "model proposes, code disposes" completely practical.
- and AWS friction is real (see our friction log): onboarding holds, generic authorization errors, dependency pinning conflicts, and Windows CLI quoting taught us to design with evidence, not optimism.
```

### D.10 Story — What's next (future — not current features)

```text
Clear future ideas (not yet built): more verifiable resource kinds (location presence, email drafts behind explicit approval clauses, smart-home device state); a cross-device Alexa+ client path when direct partner access becomes available; heavier reconciliation scheduling with heartbeat freshness; and harder anti-drift properties such as proof-of-control for delegated identities.
```

### D.11 New-project explanation (required by rules only for pre-existing projects — provided anyway for clarity)

```text
StillDone is a newly created project: its public GitHub repository (zyganali-glitch/StillDone) was first committed 2026-09-20, inside the Hackathon Submission Period (Aug 31 – Oct 23, 2026). All development, integration proofs, and testing occurred within the submission window. No pre-existing product was carried over.
```

### D.12 Truthfulness statement (suggested inclusion in the story if a slot is available)

```text
Honest disclosure: the browser exhibit and demo video replay a deterministic offline fixture that is clearly labeled (SIMULATED ALEXA+ EXPERIENCE / FIXTURE PLAYBACK). It never performs live cloud calls for visitors. The live AWS Bedrock, AgentCore, Google Calendar, Google Tasks, and Open-Meteo integrations were executed and preserved as dated RECORDED_LIVE evidence committed in the repository (docs/P01_*.md, P05_*.md, P07_*.md, P06_*.md, P11_*.md). The full seven-step sequence is not represented as one current live end-to-end execution.
```

---

## E. PRIMARY ALEXA+ TRACK SUBMISSION ANSWER

```text
StillDone qualifies for the Alexa+ track on BOTH official routes:

1) The self-hosted MCP server route (runtime requirement): StillDone implements a real Model Context Protocol server over Streamable HTTP (src/stilldone/mcp/server.py, built on the official mcp 2.2.0 Python SDK). It exposes typed mission_start and mission_status tools with strict JSON schemas over the /mcp endpoint — not just named in a README: it is imported, exercised by CI tests and proof scripts, negotiated MCP protocol version 2025-11-25 over public HTTPS (docs/P01_07_LIVE_REMOTE_MCP_EVIDENCE.md), and was deployed live to a Bedrock AgentCore Runtime serverless microVM in us-east-1 where real remote tool calls executed and returned real MCP responses (docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md, RECORDED_LIVE), then torn down cleanly to enforce the $0.00 spend limit. The server additionally implements Alexa+-specific compatibility engineering: RFC 9728 Protected Resource Metadata, OAuth resource-server boundaries, atomic SQLite/WAL rate limiting, and an Alexa 401 header suppression middleware aligned with Alexa+ discovery rules.

2) The simulated Alexa+ experience route (explicitly permitted alternate path): the public judge exhibit at https://stilldone-judge-exhibit.pages.dev presents a clearly labeled SIMULATED ALEXA+ EXPERIENCE — a multimodal one-screen presentation with voice-ready English responses (< 8 s speaking bounds) which the demo video shows directly. Its full source (src/stilldone/judge_ux/) is in the repository, prominently labeled and never disguised as live.

The two routes are explicitly separated in all materials: the deterministic engine, the verifier design, and the approval boundary are the real system; the Alexa+ client surface is simulation because direct Alexa+ partner access was not established during the build period (recorded honestly as NOT_ESTABLISHED, nowhere claimed as live device integration). The killer mission ("Get my family ready for tomorrow morning. We need to leave by 7:30.") is carried end-to-end across the real integration surface (Google Calendar, Google Tasks, Open-Meteo, Bedrock, AgentCore - each leg proved and preserved as dated live evidence at its own verified point in time, not as one current single-session execution) so the Alexa+ track requirements for meaningful agentic delegation and cross-service orchestration are met with actual technology, and the video demonstrates the product working on its intended surface.
```

Why this satisfies originality ("creative, not obvious" guidance): StillDone is not a single-turn Q&A bot nor a thin MCP wrapper — it is an agentic runtime that orchestrates across services autonomously, maintains state across sessions (durable mission ledger, fresh-session "Are we still ready?" revalidation), and introduces an approval workflow bound to cryptographic single-use grants with drift reconciliation.

---

## F. AWS BUILDER MINI CHALLENGE ANSWER

```text
StillDone showcases a multi-service AWS agent architecture with documented, dated integrations (docs/P20_03_EVIDENCE_MANIFEST.md; P20_05 provenance disclosure; RECORDED_LIVE classification):

- Amazon Bedrock (amazon.nova-micro-v1:0, us-east-1): real Converse API inference used to compile the natural-language mission into a typed candidate plan. Dated live proof with token metrics and cost estimate (~$0.00000070 gross request cost) in docs/P01_02_LIVE_BEDROCK_EVIDENCE.md (tokens in=8/out=3), and an end-to-end bounded Strands planning session engaged at 3.463 s in docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md. The model is deliberately given zero mutation and zero verdict authority — model output must survive deterministic parsing (parse_candidate_plan_for_input) before any action is considered.
- Strands Agents SDK (1.57.2): orchestrates the Bedrock planning call inside a strictly isolated second runtime environment; 18-field planner runtime metadata is cryptographically bound into evidence records so every plan proposal is traceable and non-authoritative.
- Amazon Bedrock AgentCore Runtime: the full MCP server was containerized and deployed live as a serverless CodeZip microVM in us-east-1 (port 8000, Streamable HTTP / SSE on the data plane); MCP Inspector interoperated via a SigV4 signing bridge; the mission_status and mission_start tools executed remotely; the deployment was removed cleanly (agentcore remove all -y) — proving the serverless path works without leaving unbounded spend.
- Operations and honesty: rate limiting deployed in the container (HTTP 429), per-observation cost truth fields ("NOT_DETERMINISTICALLY_OBSERVED" where metrics were not emitted), and a CloudWatch EMF observation harness designed (P-16.02) as readiness work for judge-period observability.

The purpose of the AWS stack in StillDone is architectural: reasoning (Bedrock), standards-based tool transport (MCP over AgentCore), and deterministic governance (in-repo code). The detailed "which AWS services we used and how" narrative required for this mini challenge is included verbatim inside the Product Feedback answer (§ H.1).
```

---

## G. OPEN SOURCE MINI CHALLENGE ANSWER (ELIGIBILITY GATE — CONDITIONAL)

### G.1 Gate status — read this first

**OPEN_SOURCE_ELIGIBILITY_UNCONFIRMED as of 2026-10-18.** Facts established by this batch:

- The intended subproject `mcp-verify` (packages\mcp_verify, v0.1.0, Apache-2.0, zero dependencies, wheel + installation smoke verified locally) has **never been published** to public PyPI or to a standalone public repository (Master Plan P-17.05 = `BLOCKED_EXTERNAL / NOT_RUN` — unchanged).
- The existing PyPI package named `mcp-verify` (v0.0.2, "SquatGuard MCP Template for Python") is an **unrelated third-party package** — it must NOT be referenced as StillDone's publication.
- The StillDone root repository alone does **not** automatically satisfy the "new, ADDITIONAL open-source project or contribution" requirement.
- `basebreak-demo-target` (created 2026-10-05) has **no license**, so it cannot be the qualifying repo as-is.

**Plausible qualifying candidate (discovered 2026-10-18, not yet verified as belonging to this competition's plan):**
- `https://github.com/zyganali-glitch/Basebreak` — public repo, **Apache-2.0**, Python, created **2026-09-12** (inside the hackathon window that started 2026-08-31), still actively developed during the window (pushes through 2026-10-18). README thesis: causal verification runtime for AI-written patches — "If the patch matters, the base must break" — fail-on-base / pass-on-candidate / counterfactual re-check, replacing "green tests" with causal proof. This matches the official requirement's first branch ("a new repo (with open-source license)… during the hackathon window").

### G.2 OPERATOR ACTION REQUIRED (pick exactly one path before submitting)

- **Path 1 (recommended if acceptable to you)**: Confirm that **Basebreak is your own new additional open-source project made during the hackathon window** and use the § G.3 copy. Before pasting, you must be comfortable that (a) the repo is genuinely a new, additional project relative to your primary track submission, (b) it satisfies "original work" and the IP rules, and (c) you can personally vouch for the what/how/why description below correcting any inaccuracy.
- **Path 2 (requires publishing action you have NOT authorized yet)**: publish `mcp-verify` as a standalone public GitHub repo under your account (with the existing Apache-2.0 LICENSE and README), then replace § G.3's data with the new repo URL. The coding agent did NOT and will NOT publish anything without your explicit authorization.
- **Path 3**: do not select the Open Source mini challenge — leave it empty (safe and fully allowed; the mini challenges are optional).

**Do not invent this rule field:** the Open Source form needs contribution URL, project repository URL, GitHub username, and what/how/why. If you choose Path 1 and everything above is confirmed, use:

### G.3 Copy-ready Open Source answer (Path 1 draft — CONDITIONAL on § G.2 confirmation)

```text
Contribution URL: https://github.com/zyganali-glitch/Basebreak
Project repository URL: https://github.com/zyganali-glitch/Basebreak
GitHub username: zyganali-glitch

What I did: I created and developed Basebreak, a new Apache-2.0 open-source project created during this hackathon window (repository created 2026-09-12, with active development through the submission deadline). Basebreak is an independent complement to my StillDone (Alexa+ Track) submission: it applies StillDone's core belief — success claims must be independently verified against reality — to the AI-written-software workflow.

How it works: Basebreak challenges an AI patch causally instead of accepting green tests. Its rule: "If the patch matters, the base must break" — a claimed behavior fix must FAIL on the trusted base revision under an independent witness, PASS on the candidate revision under the exact same witness, and (counterfactual check) FAIL again when the patch delta is removed. Without that transition, there is no causal evidence that the AI-written change caused the fix. The repository is under active development (planned runtime architecture, contract design, and verification documentation) in English and is licensed Apache-2.0.

Why it matters: every AI coding agent today self-certifies through "tests are green," which admits vacuous passes, weakened assertions, and coincidental fixes. Basebreak turns patch acceptance into an evidence procedure — the same trust-inversion StillDone brings to personal assistant missions, applied to agent-written software.
```

**QA gate before selecting the Open Source mini challenge**: your independent QA must confirm the repository facts above (URL, license, dates) directly on GitHub, and you must personally confirm the development story ("what I did") is accurate.

---

## H. PRODUCT FEEDBACK, FRICTION LOGS & FEATURE REQUESTS

### H.1 Which developer tools, APIs and SDKs did you use, and for what?

```text
Amazon Bedrock (amazon.nova-micro-v1:0, us-east-1, Converse API; with Strands Agents SDK 1.57.2): reasoning layer that compiles the natural-language mission "Get my family ready for tomorrow morning. We need to leave by 7:30." into a typed candidate plan. Executed live during the window (dated proof in docs/P01_02_LIVE_BEDROCK_EVIDENCE.md and docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md); strictly non-authoritative.
AWS Bedrock AgentCore Runtime (+ @aws/agentcore CLI v0.30.0): hosted StillDone's real Streamable HTTP MCP server as a serverless microVM in us-east-1; executed remote MCP initialize/tools-list/mission_status with a SigV4-signed MCP Inspector bridge (docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md, RECORDED_LIVE); torn down cleanly.
AWS CLI v2 incl. aws login: operator authentication with short-lived ASIA... session credentials; zero static keys in the repo.
Model Context Protocol (official Python SDK mcp>=2.2.0; TypeScript SDK v1.31.0 for protocol validation): the open-standards transport for the mission tools; implemented RFC 9728 PRM, rate limiting, and Alexa 401-header compatibility.
Alexa+ MCP developer documentation: integration target for protocol version requirements (simulated client surface, labeled SIMULATED ALEXA+ EXPERIENCE per rules).
Google Calendar API v3 + Google Tasks API v1: disposable demo resource reads, one calendar approval-gated update (07:45→07:30), and one task creation, each verified by independent read-backs (dated docs/P06_07, P06_08, P11_05, P11_06 evidence files, RECORDED_LIVE).
Open-Meteo API (free non-commercial): real weather reads used for mission predicates (docs/P01_06, docs/P06_06; CC BY 4.0 attribution honored).
Microsoft Clipchamp: demo video production. GitHub Actions CI: dual-runtime regression of 3,700+ tests on every push.
```

### H.2 What worked well?

```text
- Bedrock Nova Micro Converse API: clean normalized JSON, sub-cent pricing for small planning requests (doc-level estimate ~$0.0000007 gross for an 11-token probe), stable latency once account-level access is granted (3.463 s observed for a full bounded Strands planning session).
- AgentCore Runtime serverless path: real MCP protocol behavior survived in a real container runtime (SSE/Streamable HTTP data plane, HTTP 429 rate limiting observed live); the @aws/agentcore CLI handles deploy/remove from CLI once flags are known.
- Strands Agents: clean abstractions — the agentSession integrates with the Bedrock runtime path; agent.tools == [] gave us a precise no-external-tools invariant to assert.
- MCP python SDK 2.2.0: solid Streamable HTTP server implementation; standards-based behavior made the Alexa 401-header compatibility engineering tractable.
- aws login loopback flow: reliable, short-lived session credentials, no static key hazard.
```

### H.3 What needs work? (What needs improvement)

```text
- Onboarding holds surface-class errors as runtime exceptions: first inference returned "AccessDeniedException: Your account is currently being verified..." without a console hint, and a later generic "ValidationException: Operation not allowed" hid a missing Bedrock model authorization state while related entitlements read AVAILABLE. Only an AWS Support case resolved it.
- Protocol version fragmentation across official docs: Alexa+ docs sections reference 2024-11-05 / 2025-03-26 / 2025-11-25 inconsistently; AgentCore docs did not state the mandatory composite "Accept: application/json, text/event-stream" for SSE-mode runtime invocation (a plain JSON Accept header yields 406 Not Acceptable).
- Dependency pressure: strands-agents 1.57.2 pins mcp < 2.2, so modern MCP server projects must either fork dependencies or duplicate environments (we built a dual-runtime architecture rather than overriding the resolver).
- Windows CLI ergonomics: agentcore invoke --prompt '{"prompt": "PING"}' loses JSON quotes in PowerShell; dry-run demands bootstrap; remove all demands -y; and inspecting IAM/SigV4-protected runtime endpoints requires a custom signing bridge.
- aws login --remote mode is fragile with pasted base64 redirects (sensitive to line wrapping/whitespace).
```

### H.4 How was your onboarding experience (zero to hello world)?

```text
Sign-up and token-free survey-based credit redemption were straightforward. "Getting to first inference" was where the friction concentrated: after joining, our first Bedrock call hit the account-verification hold (resolved only via time and AWS Support), then a model authorization mismatch (not visible in entitlement checks, fixed by AWS Support case). Once authorized, Converse-to-Strands to AgentCore took hours, not days: our repo went from API ping to a real deployed MCP microVM with remote tool execution in one further sprint window. Summary: content after access is excellent; access-state signals during onboarding need productization (§ H.8).
```

### H.5 Would you build with these devices and services again? Yes/No + why

```text
Amazon Bedrock Nova Micro — YES: excellent price/latency for deterministic propose-only planning; needs better onboarding error signals.
Strands Agents SDK — YES (with our two-runtime split): strong agent model; we would build with it again if the mcp dependency ceiling is loosened.
AgentCore Runtime — YES: the serverless MCP microVM path worked for a real, costed proof; we recommend official Windows quoting and SigV4-bridge tooling before wide adoption.
AWS CLI (aws login) — YES: standard loopback flow is reliable short-lived auth.
Alexa+ Streamable HTTP MCP direction — YES: open-standards MCP tooling for voice assistants is the right architectural bet; protocol-version documentation harmonization is the main ask.
```

### H.6 (Rule requirement cross-reference) — "Describe which AWS service(s) you used and how, in your Product Feedback answer."

```text
We used: (1) Amazon Bedrock nova-micro-v1:0 via Converse API for mission plan compilation, under zero authority; (2) Strands Agents SDK 1.57.2 to drive the planner; (3) AgentCore Runtime to host the StillDone MCP server as a serverless CodeZip microVM in us-east-1 (remote MCP initialize/tools-list/mission_status proven live, then removed) — see § H.1 and § F for full dated evidence links.
```

### H.7 Friction log entries (Devpost-ready, strongest entries; full authentic log preserved at https://github.com/zyganali-glitch/StillDone/blob/main/docs/COMPETITION_FEEDBACK_LOG.md)

**F-1 — Bedrock onboarding: account verification hold returned as runtime AccessDeniedException (BLOCKER→resolved)**

- Date: 2026-09-27 (during P-01.02 first Bedrock inference attempt)
- Task attempted: first real Bedrock model inference through AWS CLI `aws bedrock-runtime converse`
- Steps taken: authenticated via aws login profile; invoked Converse API with sanitized prompt
- Expected: HTTP 200 response (or standard model rejection) after credits activated
- Actual: `AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours...` while the console showed access configured
- Severity: `BLOCKER` (unblocked by waiting beyond the AWS-disclosed interval)
- Workaround: stopped all retries immediately; preserved the failure observation; re-attempted after the disclosed verification window elapsed
- Actionable suggestion: surface account verification holds directly in the AWS Console Bedrock dashboard; inject the verification state header into error payloads
- Would we build with it again? `YES`

**F-2 — Bedrock model entitlement confusion: generic "Operation not allowed" masks NOT_AUTHORIZED model authorization (BLOCKER→resolved)**

- Date: 2026-09-27 → remediation 2026-09-28
- Task attempted: same inference attempt (Cycle 2) + read-only entitlement diagnostics
- Steps taken: reran Converse; ran `aws bedrock get-foundation-model-availability` read-only diagnostics
- Expected: either success, or error naming the missing prerequisite
- Actual: `ValidationException: Operation not allowed` with zero causality; diagnostics later revealed `authorizationStatus = NOT_AUTHORIZED` while agreement/entitlement/region all read AVAILABLE; root cause unestablished via public APIs; resolved after an AWS Support case
- Severity: `BLOCKER` functionally remediated
- Workaround: halted inference attempts (attempt cap enforced), opened AWS Support case, waited for account-level fix; re-verified authorizationStatus = AUTHORIZED before the successful Cycle 3 inference (tokens in=8/out=3)
- Actionable suggestion: make ValidationException payloads carry a machine-actionable reason (missing model authorization grant) and expose the authorization state in entitlement disclosure surfaces
- Would we build with it again? `YES`

**F-3 — Strands Agents SDK upstream MCP dependency pins irreconcilable with modern MCP servers (HIGH, designed around)**

- Date: 2026-10-05 (runtime integration boundary validation)
- Task attempted: install strands-agents 1.57.2 and mcp>=2.2.0 in one environment (uv sync)
- Expected: compatible resolution
- Actual: strands-agents officially requires `mcp>=1.23.0,<2.2`; StillDone's MCP server requires `mcp>=2.2.0`; version sets do not intersect; resolver fails for the joint environment
- Severity: `HIGH`
- Workaround: architected two strictly isolated dependency environments with zero resolver overrides and full dual-runtime CI
- Actionable suggestion: relax the strands-agents mcp requirement upper bound (e.g. <3.0 or optional extra) so modern Streamable HTTP MCP stacks can coexist in one environment
- Would we build with it again? `YES` (with our clean isolation pattern)

**F-4 — AgentCore invoke rejects accepted-header subset with 406; JSON-only Accept fails on SSE-configured runtimes (LOW)**

- Date: 2026-10-01 (P-05.06 remote deployment validation)
- Task attempted: remote invocation of the containerized MCP runtime via `aws bedrock-agentcore invoke-agent-runtime`
- Expected: JSON or event-stream payload returned 200
- Actual: `ValidationException: 406 Not Acceptable` when invoked with `--accept "application/json"`
- Severity: `LOW`
- Workaround: invoked with `--accept "application/json, text/event-stream"` (mandatory for SSE/streamable MCP runtimes)
- Actionable suggestion: document the mandatory composite Accept header for streaming MCP runtimes in AgentCore docs
- Would we build with it again? `YES`

**F-5 — Alexa+ MCP protocol-version documentation inconsistencies across schema/deprecation sections (LOW)**

- Date: 2026-09-29 (P-01.07 protocol validation)
- Task attempted: validate current Alexa+ MCP protocol requirements; prove remote Streamable HTTP handshake
- Expected: one authoritative protocol version in docs
- Actual: official Alexa+ docs cite 2024-11-05 (schemas), 2025-03-26 (initialize), 2025-11-25 (deprecation notice); MCP TypeScript SDK level standardizes 2025-11-25 with back-compat to 2024-10-07
- Severity: `LOW`
- Workaround: negotiated 2025-11-25 successfully over public HTTPS with direct-JSON response mode (needed because free Quick Tunnels buffer SSE)
- Actionable suggestion: publish a single Alexa+ MCP compatibility matrix (supported protocol versions + transport modes), including a statement on whether discovery stages tolerate RFC 6750 WWW-Authenticate challenge headers or demand suppression (as our Wi-Fi middleware prod implemented)
- Would we build with it again? `YES`

*(Supporting additional entries — F-20260928-01 botocore[crt] requirement; F-20260928-02 Windows quoting/dry-run/remove friction; F-20260929-01 DNS/transport tunnel limitations; F-20261001-02 aws login --remote manual-paste fragility; F-20261014-01 SigV4 proxy session-isolation hardening need; F-20261014-02 *.pages.dev connectivity on some home networks — are all preserved verbatim with full detail in the repository log linked above.)*

### H.8 Feature requests (optional, with required priority ratings)

```text
1. Surface Bedrock account/access lifecycle states in the AWS Console (Critical)
   Why it matters: onboarding holds replicate as runtime AccessDenied exceptions that no dashboard explains; hackathon windows are short and a single dashboard banner would save days.
2. Machine-actionable Bedrock ValidationException payloads with missing-prerequisite remediation (Critical)
   Why it matters: "Operation not allowed" Cost us an AWS Support cycle; naming the missing grant service-side avoids Conway-level debugging under deadline.
3. Loosen strands-agents mcp dependency ceiling (Important)
   Why it matters: modern MCP servers build on mcp>=2.2; the current <2.2 pin forces dual-runtime architectures for standard agent projects.
4. Document the mandatory composite Accept header for AgentCore streaming (SSE) runtimes (Important)
   Why it matters: plain JSON Accept produces HTTP 406 without docs mention; a one-line doc fix prevents hours of experimentation.
5. @aws/agentcore CLI: --payload-json flag + non-interactive dry-run + robust Windows quoting (Important)
   Why it matters: CI/cross-platform scripting of deploy and invoke is currently fragile in PowerShell.
6. Official AgentCore-local SigV4 signing bridge with session isolation (Important)
   Why it matters: standard MCP clients cannot natively call IAM-authorized AgentCore endpoints without a custom bridge; a reference bridge (we had to harden ours to fail-closed boundaries) would be an ecosystem-level accelerant.
7. aws login --remote input sanitation + hero-slot loopback flow in docs (Nice-to-have)
   Why it matters: base64 redirect pasting fails on wrapped terminals; standard loopback handles it today headless-to-head with manual paste.
8. One authoritative Alexa+ MCP protocol-version compatibility table (Important)
   Why it matters: three protocol versions across three doc sections confuse builders; businesses that must support the Alexa+) surface need one truth.
9. Clarify RFC 6750 WWW-Authenticate behavior for Alexa+ discovery stages (Important)
   Why it matters: standard OAuth BB-protocol behavior conflicts with documented discovery rules; both implementations should be converged.
```

---

## I. SCREENSHOT GALLERY UPLOAD ORDER & CAPTIONS (exact, from the committed media registry)

Upload these 8 files from `docs/assets/devpost/` **in this order**, one caption each (caption lengths ≤ 200 chars; encoded lengths verified in tests):

| # | Upload file | Caption (paste exactly) |
|---|---|---|
| 1 | scene_01_header_thesis.png | StillDone's public exhibit: a simulated Alexa+ experience with deterministic fixture playback and transparent evidence provenance. |
| 2 | scene_02_prestate_reads.png | Pre-state evidence shows a 7:45 departure, an absent preparation task, and rainy weather before the mission's actions. |
| 3 | scene_03_tasks_prep_verified.png | The model proposes; deterministic code controls execution. A digital Google Tasks entry is verified through separate read-back. |
| 4 | scene_04_approval_boundary.png | Calendar mutation pauses at a human approval boundary. The exhibit records zero calendar writes before authorization. |
| 5 | scene_05_ready_receipt.png | Three verified predicates produce a historical READY receipt. Its SHA-256 hash stays intact even after later drift. |
| 6 | scene_06_departure_drift_tracker.png | The deterministic exhibit illustrates departure changing from verified 7:30 to 8:00, invalidating current readiness. |
| 7 | scene_07_reconciliation_drifted.png | Fresh fixture reconciliation marks current truth DRIFTED while preserving the historical READY receipt and simulated Alexa+ response. |
| 8 | scene_08_architecture_closing.png | The provenance card separates historical recorded-live AWS and Google integration evidence from offline fixture playback. |

Advanced: if the form supports 10 or 12 screenshots, you may add the README set (`docs/assets/readme/…`: stilldone_overview, prestate_verification, task_verification, calendar_verified_update, immutable_ready_receipt, drift_law_explanation, current_truth_drifted, architecture_provenance, fresh_reconciliation_evidence, evidence_reproduction_links). Their captions live in `docs/DEMO_MEDIA_AND_SUBMISSION_COPY.md` § 6 and `README.md` § Demo Gallery. **All 18 assets are verifiably committed on `main`** (verified 2026-10-18 via git ls-tree).

**NOTE — canonical receipt hash**: all screenshots show the canonical, committed receipt SHA-256 `9fb635837d6f03a46ea9571f1c99f9373d656c0ee985d6c40a9fa427b05559b6`. A stray local exhibit re-generation with a different auto-hash (`be96f5c0…`) occurred today outside QA scope and was **discarded**; the exhibit was restored to the QA-verified committed state. If you ever regenerate the exhibit in the future, do not do so mid-submission without QA — exhibit, screenshots, captions, and evidence docs must all keep matching this hash.

---

## J. ENGLISH TESTING & REPRODUCIBILITY INSTRUCTIONS (paste-ready)

```text
JUDGE TESTING INSTRUCTIONS — StillDone (no credentials needed, $0.00)

PATH A — No-install browser review (under 2 minutes):
1. Open the live exhibit: https://stilldone-judge-exhibit.pages.dev
   (fully self-contained static page; zero backend calls). If your network cannot reach *.pages.dev, open the committed local copy artifacts/judge_exhibit/index.html from the repository instead, or use the single-file artifacts/stilldone_judge_exhibit.html.
2. What you will see: the canonical mission "Get my family ready for tomorrow morning. We need to leave by 7:30." at the top; a clearly labeled SIMULATED ALEXA+ EXPERIENCE with voice-ready responses; the 7-step desired-state timeline with expandable evidence details (<details> drawers); the human authorization boundary showing zero calendar writes before approval and the single-use cryptographic grant; the immutable SHA-256 READY receipt; the Departure Lifecycle (07:45 → 07:30 → external 08:00 → DRIFTED) with the fresh reconciliation that revokes readiness while preserving the historical receipt.

PATH B — Single-command local reproduction (Windows/macOS/Linux):
1. git clone https://github.com/zyganali-glitch/StillDone.git && cd StillDone
2. python scripts/reproduce.py            (quick verification, ~10 s)
   or: python scripts/reproduce.py --full (full dual-runtime test suite, a few minutes)
   Requires: Python >= 3.11 and Astral uv. No cloud credentials. Test provenance: FIXTURE / LOCAL_EXECUTION (offline; 0 external API calls). First run downloads pinned open-source packages from PyPI via uv lockfile sync — this is package installation, not cloud usage.
3. The judge evidence trail lives in docs/: P20_03_EVIDENCE_MANIFEST.md (claim-by-claim), P20_05_EVIDENCE_PROVENANCE_DISCLOSURE.md (what is FIXTURE vs RECORDED_LIVE vs SIMULATED), and dated live integration files under docs/P01/P05/P06/P07/P11_*.md.

NO PAID ACCESS IS REQUIRED. The exhibit performs zero backend execution; historical live AWS/Google/Open-Meteo evidence is preserved as RECORDED_LIVE in the repository, and no fresh live calls are needed for judging.
```

---

## K. VIDEO DURATION / PUBLICATION / PRIVACY / RIGHTS STATUS (P-21.05 verified record)

**Verification date**: 2026-10-18 (read-only, no video playback performed by the agent).

| Item | Result | Evidence |
|---|---|---|
| URL publicly accessible | **VERIFIED** — oEmbed HTTP 200; watch page HTTP 200 | YouTube oEmbed + watch-page fetch |
| Public visibility / playability | **VERIFIED** — `playabilityStatus: OK`, view count ≥ 1, present on the site's index; publishDate = upload date = 2026-10-18 03:45:29 UTC-7 (= 13:45:29 Türkiye), exactly matching the scheduled publication. `isFamilySafe: true`; availableCountries = 249 | ytInitialPlayerResponse |
| Title | **VERIFIED** — "StillDone — Verified AI Missions, Even After Drift \| Amazon Developer Hackathon" (matches canonical copy) | oEmbed |
| Displayed duration | **VERIFIED — 179 seconds (2:59)**, satisfying "< 3 minutes" (< 180 s). Margin: 1 second. Operator-reported duration was 2:58 (178 s); the canonical, observed player value is **179 seconds**. DO NOT re-upload; the current value is compliant. | `lengthSeconds: 179` |
| Description | **VERIFIED** — published description matches the canonical registry copy (incl. exhibit/repo links and the fixture/simulation disclosure). Cosmetic difference: the published text retains literal `**` markdown emphasis markers; optional cosmetic cleanup possible via YouTube's own edit surface (operator-only; no deadline impact since descriptions can be edited while keeping the same video URL). | shortDescription |
| Chapter timeline alignment | **NEEDS_OPERATOR_CONFIRMATION** — the description's scene-timestamp lines (00:00 → 02:35) were written for the 2:45 script; the final edit is 2:59 and scene timings may differ. Non-blocking; visual-only fix if desired by editing the description. | media registry § 2 vs § K |
| Captions | YouTube **auto-generated English (ASR)** track present; **no manually-uploaded caption track** observed. Suggested optional operator polish: upload the prepared `.srt`/`.vtt` caption file if one exists locally (improves accessibility and narration legibility). Not a published-file prerequisite. | captionTracks |
| Copyright / trademark audio risk | **Metadata-based GO**: video is operator-produced; no music metadata flags; **visual inspection of every frame was NOT performed** — if any stock music/appearance is present right in the video, you must be sure it is licensed/unowned-free/copyright-safe before submission (operator attestation). | rules text |
| Privacy/state check | Video metadata exposes only the public channel identity (operator's own name/channel) and public URLs of the exhibit/repository; no tokens, private calendar IDs, personal files, or credentials observed in title/description. Individual video content frames were not audited. | description/title fetch |
| Visual/content review of footage | **NOT_PERFORMED** (no playback inspection). The eight-scene structure and narration completeness are **operator-reported**. YouTube processing/thumbnail pipeline is complete (maxresdefault thumbnail available at 1280×720), consistent with a fully processed public upload. | K |

**Master Plan task P-21.04 (TTS/captions/PII) final status**: `OPERATOR_REPORTED_COMPLETED / CONTENT_NOT_INDEPENDENTLY_VERIFIED` — the upload itself is machine-verified (§ K table); narration/visual/audio composition remains operator-attested. Local disk inspection this batch found the 8 raw scene clips present (`_local_media/raw_clips/`), and **no** local voiceover MP3, caption file, or master export staged under `_local_media/` (the final master was not retained in the canonical local folder). Nothing was regenerated or edited.

**P-21.02 final status**: `BLOCKED_LIVE / NOT_RUN` — no fresh live AWS/Google campaign executed (out of scope by operator directive). Historical alternatives preserved as dated RECORDED_LIVE evidence documents (see § C.7).
**P-21.03 final status**: `BLOCKED_LIVE / NOT_RUN` — no fresh external-drift mutation executed; deterministic FIXTURE drift evidence and historical receipts are correctly separated (P20_05 § 2.4).
**P-21.06 final status**: `COMPLETED / VERIFIED` — all 8 Devpost screenshots + 10 README screenshots present on `origin/main` at the candidate SHA (git ls-tree verified 2026-10-18); captions unchanged in the registry.

---

## L. FINAL TEST / CI / EVIDENCE MATRIX (P-22.02 + P-22.05)

**Candidate truth chain**
- Working tree at the start of this batch: clean at `da7a518b463f08d15e8787eaf4a1aa0a4e04d3b4` (equals `origin/main`; remote re-checked).
- One stray artifact deviation found mid-batch and **restored** (details recorded in § I note and in the final report): two committed exhibit HTML files had been locally regenerated today with a different auto-computed receipt hash; `git checkout -- artifacts/judge_exhibit/index.html artifacts/stilldone_judge_exhibit.html` executed; working tree clean again; canonical hash stands at `9fb63583…`.

**Local consolidated verification campaign (executed 2026-10-18)**
- Command: `python scripts/reproduce.py --full` — **Exit code 0**
- Core/MCP runtime: **2,724 passed** (199.98 s)
- Strands Planner runtime: **1,027 passed** (7.40 s)
- mcp-verify wheel smoke: **PASSED** (built mcp_verify-0.1.0-py3-none-any.whl, installed into an isolated venv outside the source tree, verification contract `status=VERIFIED`)
- Totals: **3,751 passed, 0 failed, 0 errors.** (The older criteria-map prose says "3,800+"; today's exact, snapshot count is 3,751 — recorded honestly; historical docs refresh deferred.)
- Provenance: FIXTURE / LOCAL_EXECUTION; 0 cloud calls; no credentials; $0.00 spend.
- Clean-checkout assurance: GitHub Actions **CI on push at exactly this SHA: success** (run 38805956502, 2026-10-15T20:56:17Z, https://github.com/zyganali-glitch/StillDone/actions/runs/38805956502), plus the verified dual-runtime sync from pinned lockfiles in today's run. Live smoke: **NOT_RUN** (no fresh provider executions authorized; nothing billable).

**P-22.05 — judge-period availability (Nov 9–20, 2026)**
- Public exhibit reachable today from an independent network vantage point (HTTP 200, content verified: "StillDone — Judge Exhibit & Simulated Alexa+ Surface", fixture disclosure, 7-step timeline). Local operator network had tunnel/DNS trouble reaching `*.pages.dev` at one moment (same class as F-20261014-02); DNS resolves via DoH (Cloudflare 188.114.96.7 / .97.7) and independent fetch succeeded — a local-path issue, not a site outage.
- Offline reproducibility for judges: **VERIFIED** via `scripts/reproduce.py` (§ J).
- Future uptime of the hosted exhibit: **NOT GUARANTEED** (static Cloudflare Pages from a free-tier deploy; no persistent AgentCore infrastructure is maintained by design).
- AWS/Google budget status: **NOT_FRESHLY_OBSERVED** — no authorized read path for billing was used this batch. All personal spend to date is $0.00 under the documented policy; remaining credit coverage was last observed 2026-10-14 (operator observation doc) and is **history, not current truth**.
- Judge privacy/uncomfortables: no login walls; repo public; nothing expires mid-judging except the hosted exhibit's voluntary uptime (mitigated by local exhibit files in the repo).

**P-22.04 — public repo / license / About / links verification (read-only, 2026-10-18)**
- GitHub API: `"private": false, "visibility": "public", default branch `main`, license `apache-2.0`, pushed 2026-10-15 (at this batch's candidate), first commit 2026-09-20 (git).
- LICENSE file content: Apache License 2.0. Repo root contains README.md, pyproject.toml, AGENTS.md, artifacts/, docs/, packages/, scripts/, .github/.
- Repo **description / homepage / topics were unset** — not a rule violation (license chip is auto-detected and visible in the About row on the repo page). **Updated 2026-10-18, post-submission freeze:** About metadata was set via the authenticated GitHub API and independently read back — description `Verified AI missions through independent read-back, immutable evidence, and drift reconciliation.`, website `https://stilldone-judge-exhibit.pages.dev`, topics `ai-agents`, `mcp`, `amazon-bedrock`, `agentcore`, `verification`, `python`, `alexa`, `open-source`. The originally recommended polish (line below) is preserved as history.
  **Recommended operator polish (2 minutes, purely optional)**: on the GitHub repo page → ⚙️ gear icon next to About → Description: `Verifies AI mission outcomes via independent read-back; revokes DONE when reality drifts.` → Website: `https://stilldone-judge-exhibit.pages.dev` → Add topics: `mcp`, `aws`, `bedrock`, `agentcore`, `strands-agents`, `google-calendar`, `google-tasks`, `verification`, `agents`.
- All external links named in README/docs resolve today (verified by direct fetches in this batch).

---

## M. OPERATOR-ONLY FINAL SUBMISSION CHECKLIST

### M.1 Pre-submit (walk with independent QA)

1. [ ] Confirm Devpost login works; hackathon shows **Deadline Friday, October 23, 2026, 12:00 pm Pacific / 22:00 Türkiye** on the rules page (last verified 2026-10-18).
2. [ ] Paste § D fields (title, short description, story, challenges, accomplishments, learnings, what's next).
3. [ ] Video link: paste `https://youtu.be/c-c_cUzq1OM`. Confirm the form renders the video.
4. [ ] Watch the video yourself once front-to-back (this is the content review the agent cannot perform). Confirm: narration is English and complete; no third-party trademark/unalicensed music; scenes match the natural captions of the story. If any chapter timestamps in the description feel wrong for the final edit (2:59), edit the YouTube description (allowed any time; do NOT re-upload).
5. [ ] Track selection: **Alexa+** primary. Mini challenges: **AWS Builder** always; **Open Source** only after § G.2 gate decision.
6. [ ] Paste § E into any Alexa+-track narrative slot (and reference in the story if no dedicated slot).
7. [ ] Paste § F + § H.6 into the AWS Builder answer / feedback area per rules.
8. [ ] If Open Source gate confirmed → paste § G.3 (contribution URL / repo URL / username / what-how-why).
9. [ ] Paste § H.1–§ H.5 Product Feedback; paste § H.7 friction entries (or attach log) and § H.8 feature requests.
10. [ ] Upload the 8 screenshots per § I with captions.
11. [ ] Paste § J into testing instructions.
12. [ ] Re-read the disclosure sentences in § D.12 and the YouTube description's disclosure paragraph — they must remain in the final story.
13. [ ] Complete the human flows the agent did NOT: YouTube playback check (§ K row 2), GitHub About polish (§ L), and Basebreak gate confirmation if chosen (§ G.2).
14. [ ] Independent QA signs off on the candidate, including the final packet commit SHA (see below), before you press Submit.

### M.2 Final candidate SHA & tagging procedure (P-22.06 — EXECUTED 2026-10-18 on the annotated tag `devpost-submission-2026`)

- **Status: EXECUTED** — during the post-submission freeze, no tag existed yet, so the recommended tag name `devpost-submission-2026` (from the post-submission mission directive) was created instead of the provisional `devpost-submission-2026-10` name below; both were checked against the remote tag list before creation (no conflict, no force-move).
- Tag created ONLY after: all scoped/full validation succeeded, exact-SHA GitHub CI succeeded, remote `main` equaled the intended candidate SHA, no material security/provenance/submission-truth blocker remained, and the working tree was clean. Independent remote re-verification performed. Tag creation does NOT constitute independent QA certification. Original prepared procedure preserved below.
- Provisional (pre-submission) tag name prepared earlier: `devpost-submission-2026-10`
- Exact command sequence (run only after QA + operator authorization, from a clean tree on `main`):
  ```powershell
  git fetch origin main
  git rev-parse origin/main                     # confirm == the final packet commit SHA from the QA report
  git status --short                            # must print nothing (clean)
  git tag -a devpost-submission-2026-10 <FINAL_SHA> -m "Devpost submission candidate: Build, Ship, Shape: Amazon Developer Hackathon. Exhibit: https://stilldone-judge-exhibit.pages.dev Video: https://youtu.be/c-c_cUzq1OM Task: P-22.06"
  git push origin devpost-submission-2026-10
  git fetch origin --tags                       # independent re-check that the tag exists remotely
  ```
- Status after QA+operator action: EXECUTED (record the pushed tag reference in the QA evidence).

### M.3 Devpost submission (P-22.07 — SUBMITTED / OPERATOR_CONFIRMED)

- **Status: SUBMITTED / OPERATOR_CONFIRMED** — public entry URL: https://devpost.com/software/stilldone (public page reachability observed 2026-10-18: HTTP 200, title "StillDone | Devpost"). The operator completed all applicable and optional submission fields; independently observed form-field values/platform receipt: NOT_INDEPENDENTLY_OBSERVED.
- Post-submit evidence checklist (archive privately per the original guidance):
  1. Screenshot of the submission page showing "Submitted" status + timestamp (Türkiye + PT).
  2. The final submitted URL of your entry (shareable link from Devpost).
  3. Video link as recorded in the submitted entry.
  4. Screenshot of the screenshot gallery as uploaded.
  5. Confirmation email from Devpost (if received).
  - Store all of this OUTSIDE the public repository (privacy); then optionally record only the shareable public link + submission time in a short note for the post-submission documentation sync (§ N).
- After the Submission Period ends, Devpost rules **prohibit changing the submission** (except sponsor-permitted removals of infringing/PII content). Edit only BEFORE October 23, 2026, 22:00 Türkiye.

---

## N. DEFERRED POST-SUBMISSION DOCUMENTATION-SYNC QUEUE (EXECUTED 2026-10-18 by the final post-submission batch)

Per the batch directive, the broad documentation synchronization was explicitly deferred until AFTER successful Devpost submission. **The submission happened (SUBMITTED / OPERATOR_CONFIRMED) and this queue has now been executed in the final post-submission consolidation batch; execution evidence and outcomes are recorded in `docs/SUBMISSION_FREEZE_2026-10-18.md`.** Original queue preserved below for historical traceability.

1. `README.md` — add the 2:59 canonical video duration + YouTube link into the demo section; optionally refresh "3,700+ tests" wording to the exact 3,751 snapshot count; nothing else.
2. `docs/HANDOFF.md` — update current-state block to P-21 (video verification facts) and P-22 statuses recorded in this packet (including the final submission link and tag reference).
3. `plans/STILLDONE_MASTER_EXECUTION_PLAN.md` — set statuses: P-21.01 (completed; video truth recorded in packet), P-21.02 BLOCKED_LIVE/NOT_RUN, P-21.03 BLOCKED_LIVE/NOT_RUN, P-21.04 OPERATOR_REPORTED_COMPLETED / CONTENT_NOT_INDEPENDENTLY_VERIFIED, P-21.05 VERIFIED (179 s), P-21.06 COMPLETED/VERIFIED; P-22.01 COMPLETED (2026-10-18 rule re-verification pointer in packet), P-22.02 COMPLETED (§ L record), P-22.03 COMPLETED (this packet), P-22.04 COMPLETED (§ L), P-22.05 COMPLETED (§ L), P-22.06 PREPARED/NOT_RUN (or EXECUTED after operator), P-22.07 NOT_RUN (or actioned after operator evidence).
4. `docs/DEMO_MEDIA_AND_SUBMISSION_COPY.md` — replace the "Target Video Duration 165s (2:45)" header with the canonical 2:59 (179 s) verification record and pointer to this packet's § K (currently says PENDING_OPERATOR_ACTION for upload — update Publication Status to PUBLISHED with the URL).
5. `docs/P21_01_DEMO_SCRIPT_AND_SHOT_LIST.md` — add a single note at the top: the final rendered video is 2:59 (179 s); shot-list internal timecodes describe the 2:45 script target and were interchangeable during editing; chapter alignments in the published YouTube description are the operator's post-edit values.
6. `docs/HANDOFF.md` build-period prose — correct/reconcile the "September 27, 2026 bootstrap" statement with the git-authoritative first-commit date 2026-09-20 (also `created_at` 2026-09-20 11:21 UTC).
7. Post-submit evidence artifact: store the shareable Devpost URL + submission timestamp + operator screenshots (private, not in the public repo).
8. Optionally refresh `docs/P20_04_JUDGING_CRITERIA_MAP.md` test-count wording to the final snapshot count.

**Not deferred (critical-truth discipline)**: security claims, eligibility facts, legal/pricing risk statements live in this packet now; any later breach-of-truth discovery in those areas must be fixed IMMEDIATELY by patch commit — not parked in the queue.
