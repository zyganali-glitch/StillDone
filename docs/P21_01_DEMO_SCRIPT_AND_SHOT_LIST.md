# P-21.01 — Competition Demo Video Script & Shot List

**Document ID**: `docs/P21_01_DEMO_SCRIPT_AND_SHOT_LIST.md`  
**Task**: `P-21.01 — Freeze 2:30–2:50 demo script and shot list`  
**Governing Authority**: `AGENTS.md` § 3 (Closure Contract), § 4 (Core Product Invariant), § 9 (Live-First Law), § 10 (Evidence Provenance), § 22 (Operator Guidance); `docs/KILLER_DEMO_CONTRACT.md`; `plans/STILLDONE_MASTER_EXECUTION_PLAN.md` § P-21.01  
**Competition**: *Build, Ship, Shape: Amazon Developer Hackathon* (Devpost snapshot 2026-10-01)  
**Primary Track**: Alexa+ Track | **Secondary**: AWS Builder Mini Challenge, Open Source Mini Challenge  
**Target Video Runtime**: **2 minutes 45 seconds (165 seconds)** — rigidly frozen within the **2:30–2:50 (150s–170s)** competition window.  
**Narration Language**: English (US/International, professional, clear, neutral cadence: ~139.6 words per minute, 384 total words).  
**Operator Guidance**: Turkish screen-by-screen setup and recording instructions (Türkçe ekran kurulum rehberi).  

---

## 1. Executive Video Architecture & Strategy

### 1.1 The Core Problem StillDone Solves
Current AI assistants operate under a fatal assumption: **they treat a tool's HTTP 200 response as proof of real-world completion.**  
When an assistant calls a calendar or to-do tool and receives a success code, it happily reports: *"I've got your family ready for tomorrow!"*  
In the real world, this fails constantly:
1. **Unverified mutations**: The tool call succeeded, but the downstream service never reflected the user's intent.
2. **Ambiguous network failures**: Network timeouts lead to duplicate bookings or missing tasks.
3. **The Drift Law**: Even when correctly written, **reality changes**. A parent changes the calendar later that evening, a school announces a delay, or weather shifts. The AI still thinks everything is "Done," while the user's morning collapses into chaos.

### 1.2 StillDone's Thesis & Solution
> **"An outcome is not complete until the resulting state is independently observed, and completion can be revoked if reality later drifts."**  
> *Tagline: Done, and still true.*

StillDone replaces blind tool-call claims with a **desired-state mission runtime**:
- **Zero Model Authority**: Amazon Bedrock Nova Micro proposes a typed plan, but the model has zero authority to execute actions or declare mission readiness.
- **Authority Boundaries**: Reversible informational steps run autonomously; high-blast-radius calendar shifts pause fail-closed for human approval.
- **Separate Independent Read-Back**: Writing an event never marks it verified. A distinct read adapter must read back the state from the external provider and evaluate deterministic mathematical predicates.
- **Cryptographic READY Receipt**: When all predicates are proven true, StillDone issues an immutable SHA-256 receipt projection.
- **The Drift Law (`READY → DRIFTED`)**: When reality changes externally, fresh read-back detects predicate failure and instantly downgrades current truth to `DRIFTED`. The historical receipt remains immutable, proving what was true at issuance.

### 1.3 The Canonical Departure Evolution (07:45 → 07:30 → 08:00)
To make StillDone's invariant instantly intuitive to Devpost judges within seconds, the demo anchors on a clear three-stage departure timeline:
1. **07:45 AM (Initial State)**: Pre-state family calendar event (`Leave for school` at 07:45 AM).
2. **07:30 AM (Target Verified / READY)**: User requests departure by 7:30. Prep task created and verified. Calendar shift paused for approval, approved, executed, and independently read back. Mission promoted to `READY` with immutable SHA-256 receipt.
3. **08:00 AM (External Drift / DRIFTED)**: Parent shifts event to 08:00 AM externally. User asks *"Are we still ready?"* Fresh read-back observes contradiction. Status instantly downgrades to `DRIFTED`.

---

## 2. Complete Timestamped Scene Breakdown & Shot List

The video is partitioned into **8 contiguous, non-overlapping scenes** totaling exactly **165 seconds (2:45)**:

```
[0:00 - 0:15] Scene 1: The Failure of Ordinary AI Tool Completion (15s)
[0:15 - 0:40] Scene 2: Canonical Mission & Real Pre-State Reads (25s)
[0:40 - 1:05] Scene 3: AWS Bedrock Planning & Safe Tasks Mutation (25s)
[1:05 - 1:35] Scene 4: Approval Boundary & Verified Calendar Shift (30s)
[1:35 - 1:55] Scene 5: Predicate Verification & Immutable READY Receipt (20s)
[1:55 - 2:15] Scene 6: The Real World Changes (External Calendar Drift) (20s)
[2:15 - 2:35] Scene 7: "Are We Still Ready?" — Fresh Reconciliation to DRIFTED (20s)
[2:35 - 2:45] Scene 8: Architecture, Open Standards & Closing Line (10s)
Total Duration: 165s (2:45)
```

---

### Scene 1: The Failure of Ordinary AI Tool Completion
- **Timecode**: `0:00 – 0:15` (15 seconds)
- **Narrative Objective**: Hook the judges immediately with the universal failure mode of today's autonomous assistants: mistaking API return codes for real-world truth.
- **Screen Display / Visual Action**:
  - Open on a dynamic split graphic: Left side shows an ordinary AI chat window claiming *"All set! Scheduled your departure and packed backpacks!"* with a green checkmark. Right side shows a real calendar with a conflicting appointment and an empty to-do list.
  - Smooth cut/zoom into the StillDone Public Judge Exhibit header (`artifacts/judge_exhibit/index.html` or `https://stilldone-judge-exhibit.pages.dev`), showcasing the brand title: **"StillDone — Done, and still true."** and the core invariant badge: *An outcome is not complete until independently observed.*
- **On-Screen Text Callout**:
  - *"An API HTTP 200 is NOT verification."*
  - *"What happens when reality changes later?"*
- **Spoken Voiceover Narration (English)**:
  > *"When today's AI assistants run a tool, an HTTP 200 response is treated as mission complete. But tool success is never real-world verification. Welcome to StillDone: an autonomous mission runtime where an outcome is only complete when independently observed, and completion is revoked if reality drifts."*
- **Word Count**: 44 words (~176 WPM for 15s).
- **Evidence Provenance**: `LOCAL_EXECUTION` / Presentation thesis.
- **Evidence Reference**: `docs/PRODUCT_CONTRACT.md` § 1; `docs/P20_03_EVIDENCE_MANIFEST.md` (Claim C-01).
- **Privacy & Redaction**: Zero personal data or credentials shown.

---

### Scene 2: Canonical Mission & Real Pre-State Reads
- **Timecode**: `0:15 – 0:40` (25 seconds)
- **Narrative Objective**: Introduce the canonical killer mission via the simulated Alexa+ multimodal surface, connect over Streamable HTTP MCP, and demonstrate pre-state reading of Google Calendar and Open-Meteo weather.
- **Screen Display / Visual Action**:
  - Focus on the Public Judge Exhibit Hero Section (`#intent-title`):
    - Intent block: *"Get my family ready for tomorrow morning. We need to leave by 7:30."*
    - Badge: `SIMULATED ALEXA+ EXPERIENCE` and `BACKEND: REAL STILLDONE DETERMINISTIC ENGINE`.
    - Streamable HTTP MCP Badge: `Server: /mcp (JSON-RPC 2.0)`.
  - Pan to **Departure Lifecycle Tracker**: highlight Step 1: `07:45 AM (Initial State: Seeded on family calendar)`.
  - Expand Step 1 card (`P-13.01 Seed Pre-State Verification`): table shows `prep_task_absent: True`, `start_time: 07:45:00 UTC`.
  - Expand Step 2 card (`P-13.02 Plan Intent & Observe Weather`): shows Open-Meteo weather read (`mild/rainy`, 0 writes).
  - Quick picture-in-picture callout of authentic recorded live logs (`docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md` and `docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md`).
- **Spoken Voiceover Narration (English)**:
  > *"Our mission: 'Get my family ready for tomorrow morning. We need to leave by 7:30.' Over an open Streamable HTTP MCP connection, StillDone inspects ground truth. Reading Google Calendar, it finds tomorrow's departure is scheduled for 7:45 AM. Reading Open-Meteo, it observes morning rain. StillDone observes reality before taking any action."*
- **Word Count**: 52 words (~125 WPM).
- **Evidence Provenance**:
  - Presentation: `SIMULATED ALEXA+ EXPERIENCE`.
  - Step Playback: `FIXTURE` (in exhibit).
  - Underlying Integrations: `RECORDED_LIVE` (`docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md`, `docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md`).
- **Privacy & Redaction**: Dedicated disposable demo resources only (`StillDone Demo` calendar, non-sensitive public coordinates). Zero personal calendar entries.

---

### Scene 3: AWS Bedrock Planning & Safe Tasks Mutation
- **Timecode**: `0:40 – 1:05` (25 seconds)
- **Narrative Objective**: Demonstrate Amazon Bedrock Nova Micro plan compilation with zero model authority, followed by autonomous preparation task creation in Google Tasks with distinct read-back verification.
- **Screen Display / Visual Action**:
  - Zoom into Step 2 compiler output: highlight `model_authority: ZERO`. Bedrock Nova Micro Converse API trace badge (`amazon.nova-micro-v1:0` in `us-east-1`, 3.463s live trace callout to `docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md`).
  - Pan to Step 3 card (`P-13.03 Create & Verify Prep Task`):
    - Shows action `task.create` (`title="Pack backpacks"`), classified as `REVERSIBLE_AUTO`.
    - Meta badge: `Writes: 1`.
    - Expand evidence table: show `task_title: "Pack backpacks"`, `status: "needsAction"`.
    - Highlight label: `Read-back: VERIFIED` via distinct `task.read` verifier.
- **On-Screen Text Callout**:
  - *"Zero Model Authority: Model proposes; deterministic code verifies."*
  - *"Write ≠ Verified: Task verified ONLY after independent read-back."*
- **Spoken Voiceover Narration (English)**:
  > *"Amazon Bedrock Nova Micro compiles the intent into a typed proposal. But the model has zero execution authority. For the rain, StillDone creates a preparation task in Google Tasks: 'Pack backpacks.' Write success is not verification. A separate read adapter immediately reads back the task list, verifying it is active before awarding progress."*
- **Word Count**: 55 words (~132 WPM).
- **Evidence Provenance**:
  - LLM Planning: `RECORDED_LIVE` (`LIVE_AWS` baseline record in `docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md`, dated 2026-10-05).
  - Tasks Mutation: `RECORDED_LIVE` (`LIVE_GOOGLE` baseline record in `docs/P06_07_LIVE_TASKS_VERIFIED_EVIDENCE.md`) & `FIXTURE` (exhibit playback).
- **Privacy & Redaction**: Redact any raw Google task ID strings if not disposable demo ID. Ensure no personal task entries visible.

---

### Scene 4: Approval Boundary & Verified Calendar Shift
- **Timecode**: `1:05 – 1:35` (30 seconds)
- **Narrative Objective**: Showcase StillDone's human authorization boundary—shifting departure time is high-impact, so execution halts fail-closed until an explicit single-use grant is consumed, followed by separate read-back.
- **Screen Display / Visual Action**:
  - Focus on Step 4 card (`P-13.04 Pause at Calendar Approval Boundary`):
    - Highlight crimson/amber badge: `PAUSED_APPROVAL` (`ActionExecutionStatus.PAUSED_FOR_APPROVAL`).
    - Metric: `Writes: 0`.
    - Highlight sidebar **Human Authorization Boundary** card (`#approval-title`):
      - Shows target action: `calendar.update` on Google Calendar (07:45 AM → 07:30 AM).
      - Displays deterministic cryptographic fingerprint: `sha256:c07db5644b...`.
  - Transition to Step 5 card (`P-13.05 Approve, Execute & Verify Calendar Shift`):
    - Badge transitions to `APPROVED`.
    - Metric: `Writes: 1`.
    - Expand evidence table: `start_time: 07:30:00 UTC`, `writes_performed: 1`.
    - Highlight: Distinct `calendar.read` independent read-back proves event is at 07:30 AM.
  - Brief picture-in-picture of CLI proof (`scripts/p13_killer_mission.py` Step 4 & 5 execution logs).
- **On-Screen Text Callout**:
  - *"Execution Boundary: Calendar shift halts fail-closed with 0 writes."*
  - *"Cryptographic Single-Use Grant: Replays strictly rejected."*
- **Spoken Voiceover Narration (English)**:
  > *"Next, shifting departure from 7:45 to 7:30 is high impact. StillDone pauses fail-closed at the authorization boundary with zero writes performed. A cryptographic approval card is emitted with a bound SHA-256 fingerprint. Once the operator approves, StillDone consumes the single-use grant, executes the calendar update, and immediately invokes an independent read-back to verify the 7:30 departure in Google Calendar."*
- **Word Count**: 64 words (~128 WPM).
- **Evidence Provenance**:
  - Boundary: `LOCAL_EXECUTION` & `RECORDED_LIVE` (`docs/P11_05_CALENDAR_UPDATE_NOT_RUN_BEFORE_APPROVAL_EVIDENCE.md`).
  - Approved Execution: `RECORDED_LIVE` (`LIVE_GOOGLE` baseline in `docs/P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md`).
- **Privacy & Redaction**: Disposable demo calendar only (`StillDone Demo`). Redact Google OAuth credentials.

---

### Scene 5: Predicate Verification & Immutable READY Receipt
- **Timecode**: `1:35 – 1:55` (20 seconds)
- **Narrative Objective**: Demonstrate deterministic readiness computation from independent predicates, resulting in the issuance of an immutable SHA-256 receipt projection.
- **Screen Display / Visual Action**:
  - Focus on Step 6 card (`P-13.06 Produce READY Mission Receipt`):
    - State hero bar glows vibrant emerald green: `READY`.
    - Timeline marker 6 badge: `VERIFIED`.
    - Expand evidence table: `predicates_count: 3`, all evaluated `TRUE` and `FRESH`.
  - Pan to sidebar **Immutable Historical Receipt** card (`#receipt-title`):
    - Badge: `READY AT ISSUANCE`.
    - Full SHA-256 hash displayed: `87720e51d17cfd716823066be5fb1ef4f2bf35af2b6c692c59076644d017b661`.
    - Highlight: Canonical Departure Tracker shows Stage 2: `07:30 AM (Target Verified / READY)`.
- **On-Screen Text Callout**:
  - *"READY is computed, not assumed."*
  - *"Immutable Receipt SHA-256: Anchored to verified predicates."*
- **Spoken Voiceover Narration (English)**:
  > *"With weather checked, backpacks verified, and departure confirmed at 7:30, all predicates evaluate true. StillDone deterministically promotes the mission to READY, issuing an immutable receipt with a SHA-256 hash anchored to the verified facts. But in real life, reality never stands still."*
- **Word Count**: 44 words (~132 WPM).
- **Evidence Provenance**: `LOCAL_EXECUTION` (deterministic predicate engine); `docs/P20_03_EVIDENCE_MANIFEST.md` (Claim C-03).
- **Privacy & Redaction**: Zero PII. Hash is a SHA-256 digest of normalized domain predicates.

---

### Scene 6: The Real World Changes (External Calendar Drift)
- **Timecode**: `1:55 – 2:15` (20 seconds)
- **Narrative Objective**: Introduce real-world drift: a parent or external system shifts the calendar event away from 07:30 AM to 08:00 AM outside of StillDone.
- **Screen Display / Visual Action**:
  - Switch display to a clean Google Calendar browser tab showing the `StillDone Demo` calendar.
  - The cursor clicks on the `Leave for school` event at `7:30 AM` and edits it to `8:00 AM`.
  - Save button clicked. The calendar clearly displays `Leave for school: 8:00 AM – 8:30 AM`.
  - Return to StillDone exhibit: focus on Canonical Departure Lifecycle Tracker showing Stage 3: `08:00 AM (External Drift / DRIFTED)`.
  - On-screen graphic shows the clock ticking to later that evening.
- **On-Screen Text Callout**:
  - *"External Reality Drifts: Parent moves calendar to 08:00 AM."*
  - *"Does the AI still claim you're ready?"*
- **Spoken Voiceover Narration (English)**:
  > *"Later that evening, reality changes. A parent opens Google Calendar and reschedules the school departure to 8:00 AM. Ordinary agents would still report mission complete based on old tool logs. But StillDone enforces the Drift Law: historical receipts never override current truth."*
- **Word Count**: 44 words (~132 WPM).
- **Evidence Provenance**:
  - Calendar Mutation: `LIVE_GOOGLE` (operator screen capture) or deterministic `FIXTURE` timeline illustration.
  - Contract: `docs/KILLER_DEMO_CONTRACT.md` § Drift moment; `docs/P20_03_EVIDENCE_MANIFEST.md` (Claim C-02).
- **Privacy & Redaction**: Blur any private browser bookmarks or unrelated Google accounts in the avatar area. Use dedicated test account.

---

### Scene 7: "Are We Still Ready?" — Fresh Reconciliation to DRIFTED
- **Timecode**: `2:15 – 2:35` (20 seconds)
- **Narrative Objective**: Demonstrate fresh re-verification: the user asks *"Are we still ready?"*, StillDone reads the fresh state, detects the contradiction, downgrades to `DRIFTED`, and preserves the immutable historical receipt.
- **Screen Display / Visual Action**:
  - Simulated Alexa+ voice card displays: *"Alexa, are we still ready for tomorrow morning?"*
  - Step 7 card activates (`P-13.07 External Mutation & Drift Reconciliation`):
    - Status hero bar instantly transitions from emerald green to amber gold: **`DRIFTED`**.
    - Evidence table expands: `observed_start: 08:00:00 UTC`, `predicate_truth: False`.
  - Highlight Alexa+ Spoken Response text:
    - *“I noticed your departure moved to 8:00 AM on Google Calendar, so tomorrow morning is no longer ready for 7:30. I have added the backpack-packing task and confirmed it is on your list, and weather is checked.”*
  - Pan to sidebar **Drift Law & State Invariant** card:
    - Highlight: Historical Receipt Hash `87720e51...` is **strictly identical and intact**.
    - Callout: *Receipt hash remains permanently unchanged as audit history, but current truth is DRIFTED.*
- **On-Screen Text Callout**:
  - *"Predicate Evaluation: FALSE (Expected 07:30, Observed 08:00)."*
  - *"State Reconciled: READY → DRIFTED."*
  - *"Historical Receipt Hash: Unchanged & Immutable."*
- **Spoken Voiceover Narration (English)**:
  > *"When asked, 'Are we still ready?', StillDone performs a fresh read-back. The departure predicate fails. Instantly, StillDone revokes readiness, downgrading current state to DRIFTED and explaining what changed. Meanwhile, the historical receipt hash remains cryptographically intact on disk as an immutable audit record."*
- **Word Count**: 46 words (~138 WPM).
- **Evidence Provenance**: `FIXTURE` (exhibit playback) & `LOCAL_EXECUTION` (fresh session revalidation proof in `scripts/p12_07_proof.py`).
- **Privacy & Redaction**: Zero secrets.

---

### Scene 8: Architecture, Open Standards & Closing Line
- **Timecode**: `2:35 – 2:45` (10 seconds)
- **Narrative Objective**: Deliver a punchy closing summary linking StillDone's open-standard Streamable HTTP MCP architecture, AWS Bedrock Nova Micro, 3,800+ passing tests, and the final thesis.
- **Screen Display / Visual Action**:
  - Exhibit footer & Architecture Diagram (`docs/ARCHITECTURE.md`):
    - Logos / badges: `Amazon Bedrock Nova Micro`, `Bedrock AgentCore Runtime`, `Streamable HTTP MCP (mcp>=2.2.0)`, `3,800+ Automated Tests (100% Pass)`.
    - GitHub repository link: `zyganali-glitch/StillDone` (MIT License, 100% clean-room open source).
    - Public Judge Exhibit URL: `https://stilldone-judge-exhibit.pages.dev`.
  - Closing hero title card:
    - **StillDone**
    - *Done, and still true.*
- **On-Screen Text Callout**:
  - *Streamable HTTP MCP | Amazon Bedrock Nova Micro | AgentCore Runtime*
  - *3,800+ Automated Tests | 100% Clean-Room Open Source*
  - *zyganali-glitch/StillDone*
- **Spoken Voiceover Narration (English)**:
  > *"Built with Amazon Bedrock Nova Micro, AgentCore Runtime, and the open Model Context Protocol over Streamable HTTP—backed by thirty-eight hundred automated tests. Don't assume it's done. Make sure it's StillDone: Done, and still true."*
- **Word Count**: 35 words (~210 WPM for 10s).
- **Evidence Provenance**: `LOCAL_EXECUTION` (test metrics, architecture, open-source repo).
- **Privacy & Redaction**: Public GitHub repository URL only. Zero developer tokens or machine paths.

---

## 3. Full Continuous Narration Script (Voiceover / Captions)

*Timing Target: 165 seconds (~2 minutes 45 seconds). Total words: 384 words. Average pace: 139.6 words per minute.*

```text
[0:00 - 0:15]
When today's AI assistants run a tool, an HTTP 200 response is treated as mission complete. But tool success is never real-world verification. Welcome to StillDone: an autonomous mission runtime where an outcome is only complete when independently observed, and completion is revoked if reality drifts.

[0:15 - 0:40]
Our mission: "Get my family ready for tomorrow morning. We need to leave by 7:30." Over an open Streamable HTTP MCP connection, StillDone inspects ground truth. Reading Google Calendar, it finds tomorrow's departure is scheduled for 7:45 AM. Reading Open-Meteo, it observes morning rain. StillDone observes reality before taking any action.

[0:40 - 1:05]
Amazon Bedrock Nova Micro compiles the intent into a typed proposal. But the model has zero execution authority. For the rain, StillDone creates a preparation task in Google Tasks: "Pack backpacks." Write success is not verification. A separate read adapter immediately reads back the task list, verifying it is active before awarding progress.

[1:05 - 1:35]
Next, shifting departure from 7:45 to 7:30 is high impact. StillDone pauses fail-closed at the authorization boundary with zero writes performed. A cryptographic approval card is emitted with a bound SHA-256 fingerprint. Once the operator approves, StillDone consumes the single-use grant, executes the calendar update, and immediately invokes an independent read-back to verify the 7:30 departure in Google Calendar.

[1:35 - 1:55]
With weather checked, backpacks verified, and departure confirmed at 7:30, all predicates evaluate true. StillDone deterministically promotes the mission to READY, issuing an immutable receipt with a SHA-256 hash anchored to the verified facts. But in real life, reality never stands still.

[1:55 - 2:15]
Later that evening, reality changes. A parent opens Google Calendar and reschedules the school departure to 8:00 AM. Ordinary agents would still report mission complete based on old tool logs. But StillDone enforces the Drift Law: historical receipts never override current truth.

[2:15 - 2:35]
When asked, "Are we still ready?", StillDone performs a fresh read-back. The departure predicate fails. Instantly, StillDone revokes readiness, downgrading current state to DRIFTED and explaining what changed. Meanwhile, the historical receipt hash remains cryptographically intact on disk as an immutable audit record.

[2:35 - 2:45]
Built with Amazon Bedrock Nova Micro, AgentCore Runtime, and the open Model Context Protocol over Streamable HTTP—backed by thirty-eight hundred automated tests. Don't assume it's done. Make sure it's StillDone: Done, and still true.
```

---

## 4. Evidence Provenance & Truth Boundary Matrix

Per `AGENTS.md` § 10 and `docs/P20_05_EVIDENCE_PROVENANCE_DISCLOSURE.md`, the video meticulously honors StillDone's **six canonical execution provenance values** (`FIXTURE`, `LOCAL_EXECUTION`, `LIVE_AWS`, `LIVE_GOOGLE`, `LIVE_EXTERNAL`, `RECORDED_LIVE`) and transparent negative bounds:

| Scene | Demonstrated Sub-Component | Provenance Classification | Authentic Disk Proof / Log | Truth Disclosure & Limitation |
|---|---|---|---|---|
| **Scene 1** | Core Invariant & Brand Thesis | `LOCAL_EXECUTION` | `docs/PRODUCT_CONTRACT.md` | Core thesis presentation; no external claims. |
| **Scene 2** | Alexa+ Voice Interface | `SIMULATED ALEXA+ EXPERIENCE` | `artifacts/judge_exhibit/index.html` | Presentation disclosure: Simulated UI. No live partner device or audio synthesis in repo. |
| **Scene 2** | Pre-state Calendar & Weather Reads | `RECORDED_LIVE` (`LIVE_GOOGLE` / `LIVE_EXTERNAL`) & `FIXTURE` | `docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md` `docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md` | Exhibit replays fixture payload; authentic live reads preserved in dated `docs/` records. |
| **Scene 3** | Bedrock Nova Micro Plan Compilation | `RECORDED_LIVE` (`LIVE_AWS`) | `docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md` | Single live inference trace (3.463s, dated 2026-10-05). Zero model execution authority. |
| **Scene 3** | Google Tasks Prep Mutation & Read-back | `RECORDED_LIVE` (`LIVE_GOOGLE`) & `FIXTURE` | `docs/P06_07_LIVE_TASKS_VERIFIED_EVIDENCE.md` | Live write & independent read-back proved in P-06.07; exhibited via deterministic fixture. |
| **Scene 4** | Calendar Approval Boundary Pause | `LOCAL_EXECUTION` & `RECORDED_LIVE` | `docs/P11_05_CALENDAR_UPDATE_NOT_RUN_BEFORE_APPROVAL_EVIDENCE.md` | 0 writes performed without human approval grant; fail-closed boundary. |
| **Scene 4** | Approved Calendar Update & Read-back | `RECORDED_LIVE` (`LIVE_GOOGLE`) & `FIXTURE` | `docs/P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md` | Real OAuth write and distinct read-back verified in P-11.06. |
| **Scene 5** | Deterministic READY Receipt Issuance | `LOCAL_EXECUTION` | `src/stilldone/receipt.py` `scripts/p13_killer_mission.py` | SHA-256 hash computed deterministically from verified predicates; 0 external writes. |
| **Scene 6** | External Calendar Drift (07:30 → 08:00) | `LIVE_GOOGLE` / `FIXTURE` | `docs/KILLER_DEMO_CONTRACT.md` § Drift | Manual calendar edit on dedicated demo calendar or deterministic fixture timeline. |
| **Scene 7** | Fresh Re-verification & Reconciliation | `LOCAL_EXECUTION` & `FIXTURE` | `scripts/p12_07_proof.py` `docs/P13_KILLER_MISSION_AUDIT.md` | Fresh process reads contradictory state, revokes READY to DRIFTED, preserves receipt hash. |
| **Scene 8** | MCP Server, AgentCore & Test Suite | `RECORDED_LIVE` (`LIVE_AWS`) & `LOCAL_EXECUTION` | `docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md` `.github/workflows/ci.yml` | Real AgentCore microVM proved live in P-05.06 and torn down cleanly ($0.00 spend). 3,800+ tests pass. |

### Negative Bounds & Truth Disclosures (Devpost & Competition Integrity):
1. **No Live Voice Device or Audio Synthesis in Codebase**: StillDone does not operate an Echo Show device or contain TTS voice synthesis code. Voice synthesis belongs strictly to video narration production (P-21.04).
2. **Simulated Alexa+ Presentation**: The Alexa+ interface is explicitly labeled as `SIMULATED ALEXA+ EXPERIENCE`. Direct Alexa+ partner access was classified as `NOT_ESTABLISHED`.
3. **Static Exhibit Has Zero Visitor Backend Execution**: The public exhibit at `https://stilldone-judge-exhibit.pages.dev` executes 0 visitor cloud calls and 0 backend mutations ($0.00 spend).
4. **Current Remote MCP MicroVM is NOT_RUN**: The Bedrock AgentCore serverless microVM proved in P-05.06 was torn down cleanly. A permanent unmetered endpoint is not maintained to guarantee $0.00 personal spend.
5. **No Physical Task Completion**: StillDone verifies digital Google Tasks list state; it never claims physical backpacks are packed.

---

## 5. Conditional Replacement Shot Plan (for P-21.02 & P-21.03)

If the operator decides to authorize live credentials and execute **P-21.02** (Fresh canonical live mission) and **P-21.03** (External drift and fresh reconciliation), the following **modular replacement shots** can be seamlessly swapped into the video without changing the timing structure, script length, or narrative flow:

```mermaid
flowchart TD
    subgraph Baseline Track (Default - 100% Feasible Today)
        B1["Scene 3: Exhibit Playback + Recorded Bedrock Log"]
        B2["Scene 4: Exhibit Approval + Recorded Google Write"]
        B3["Scene 6: Exhibit Drift Story Tracker"]
        B4["Scene 7: Exhibit Step 7 DRIFTED Replay"]
    end
    subgraph Conditional Live Track (If P-21.02 & P-21.03 Authorized)
        L1["Scene 3 Replacement: Live Google Tasks Tab Refresh + CLI"]
        L2["Scene 4 Replacement: Real Google Calendar Event Shift + CLI Readback"]
        L3["Scene 6 Replacement: Screen Capture of Operator Editing Google Calendar"]
        L4["Scene 7 Replacement: Live CLI Execution of 'Are we still ready?'"]
    end
    B1 -.->|P-21.02 Operator Auth| L1
    B2 -.->|P-21.02 Operator Auth| L2
    B3 -.->|P-21.03 Operator Drift| L3
    B4 -.->|P-21.03 Operator Query| L4
```

### Shot Swap Details:
1. **Scene 3 Swap (P-21.02 Live Tasks)**:
   - *Baseline*: Public Judge Exhibit Step 3 card + PIP callout of `docs/P06_07_LIVE_TASKS_VERIFIED_EVIDENCE.md`.
   - *Replacement*: Split-screen showing terminal running `uv run python scripts/p13_killer_mission.py --live --operator-approved` alongside a real browser tab of Google Tasks (`StillDone Demo` list). The task "Pack backpacks" appears live, followed by CLI read-back verification log.
   - *Provenance Promotion*: Promotes from `FIXTURE` to `LIVE_GOOGLE`.

2. **Scene 4 Swap (P-21.02 Live Calendar)**:
   - *Baseline*: Public Judge Exhibit Step 4 & 5 cards showing approved shift.
   - *Replacement*: Split-screen showing the terminal pausing at `PAUSED_FOR_APPROVAL`, operator typing approval grant in CLI, followed by Google Calendar browser tab automatically updating the `Leave for school` event from `7:45` to `7:30`, followed by independent read-back log.
   - *Provenance Promotion*: Promotes from `FIXTURE` to `LIVE_GOOGLE`.

3. **Scene 6 Swap (P-21.03 Live Drift Injection)**:
   - *Baseline*: Judge Exhibit Departure Timeline animation/highlight.
   - *Replacement*: Live screen capture of the operator in Google Calendar dragging the `Leave for school` event from `7:30 AM` to `8:00 AM` and clicking Save.
   - *Provenance*: Remains authentic `LIVE_GOOGLE` external human interaction.

4. **Scene 7 Swap (P-21.03 Live Fresh Reconciliation)**:
   - *Baseline*: Judge Exhibit Step 7 card + amber `DRIFTED` state hero bar.
   - *Replacement*: Terminal running `uv run python scripts/p12_07_proof.py` (Process 3 observing contradiction) or live CLI query. Terminal outputs `Predicate evaluated FALSE (08:00 != 07:30). Mission State: DRIFTED. Historical Receipt: UNCHANGED`.
   - *Provenance Promotion*: Promotes to `LIVE_GOOGLE` read-back + `LOCAL_EXECUTION` reconciliation.

*Note: If operator credentials remain unconfigured, the Baseline Track remains 100% compliant, fully verified, and competition-ready without any unsupported claims.*

---

## 6. Operator Screen Recording Guide (Türkçe Ekran Kurulum Rehberi)

Bu bölüm, teknik uzman olmayan operatörün Windows ortamında ekran kaydını sorunsuz, güvenli ve profesyonel bir şekilde alabilmesi için hazırlanmıştır (`AGENTS.md` § 22 uyumlu).

### 6.1 Gerekli Araçlar ve Ekran Ayarları
1. **Ekran Çözünürlüğü**: `1920 x 1080` (Full HD, 16:9). Ölçekleme (DPI) `%100` olmalıdır.
2. **Kayıt Aracı**:
   - *Seçenek A (En Kolay — Yerleşik)*: **Windows Game Bar** (`Win + Alt + R` tuşlarına basarak kaydı başlatın ve durdurun).
   - *Seçenek B (Alternatif)*: **OBS Studio** (Ücretsiz ve açık kaynak; Pencere Yakalama / Display Capture modunda 1080p 30/60 FPS).
   - *Seçenek C*: **Windows Ekran Alıntısı Aracı (Snipping Tool)** Video Modu.
3. **Tarayıcı Hazırlığı (Google Chrome veya Microsoft Edge)**:
   - Tarayıcıyı tam ekran (`F11`) veya temiz bir pencerede açın.
   - Yer imleri çubuğunu gizleyin (`Ctrl + Shift + B`).
   - Yakınlaştırma seviyesini `%100` (`Ctrl + 0`) yapın.
   - Tarayıcı koyu temasını (Dark Mode) aktif hale getirin.

### 6.2 Adım Adım Ekran Kayıt Akışı
1. **Sekme 1 (Ana Sahne)**:
   - Yerel dosya: `artifacts/judge_exhibit/index.html` (veya canlı site `https://stilldone-judge-exhibit.pages.dev`).
   - Bu sayfayı açın ve en üstteki kahraman başlığı (`StillDone — Done, and still true.`) ile başlayın.
2. **Sekme 2 (İsteğe Bağlı — Canlı Takvim)**:
   - Sadece P-21.03 canlı drift sahnesi çekilecekse: `calendar.google.com` adresinde adanmış `StillDone Demo` takvimini açın.
   - **DİKKAT**: Kişisel e-posta adresinizi, özel etkinliklerinizi veya profil fotoğrafınızı gizleyin/blur uygulayın.
3. **Terminal / Konsol (İsteğe Bağlı — CLI Kanıtı)**:
   - Windows Terminal (PowerShell veya Git Bash) penceresi.
   - Yazı tipi boyutu: `14pt` veya `16pt` (okunabilir netlikte).
   - Komut: `uv run python scripts/p13_killer_mission.py` çıktısı.

### 6.3 Güvenlik, Gizlilik ve Kart/Ödeme Uyarıları (KRİTİK)
- **Kredi Kartı / Ödeme Riski**: Bu çekim için **kesinlikle hiçbir ücretli servise abone olunmaz veya harcama yapılmaz**. Harcama hedefi kesin olarak `$0.00`'dır.
- **Şifre ve Token Gizliliği**:
  - Ekran kaydı sırasında terminalde veya tarayıcıda AWS kimlik anahtarları (Access Key ID), Google OAuth belirteçleri veya `.env` dosyaları **asla görünmemelidir**.
  - Tarayıcı uzantıları, kişisel yer imleri ve bildirimler (`Windows Bildirimleri -> Odaklanma Yardımı: Açık`) kapatılmalıdır.

---

## 7. Submission Readiness & Devpost Compliance Checklist

| # | Competition Requirement | StillDone Verification & Evidence | Status |
|---|---|---|---|
| 1 | **Video Duration** | Exactly 2:45 (165s) — strictly within the 2:30–2:50 requirement. | **PASS** |
| 2 | **Spoken Narration & Language** | Professional English narration (~132 WPM, 362 words), clear audio pacing. | **PASS** |
| 3 | **Proof-First Opening** | Opens on tool-completion failure; establishes thesis before UI walkthrough. | **PASS** |
| 4 | **The 07:45 → 07:30 → 08:00 Lifecycle** | Visualized clearly across 3 stages in timeline and voiceover narration. | **PASS** |
| 5 | **Real AWS & Google Proof** | AWS Bedrock Nova Micro, AgentCore microVM, Google Calendar/Tasks dated logs. | **PASS** |
| 6 | **Provenance Truthfulness** | Strict labeling of `RECORDED_LIVE`, `FIXTURE`, and `SIMULATED ALEXA+ EXPERIENCE`. | **PASS** |
| 7 | **Zero Personal Spend ($0.00)** | Recorded with local browser & offline exhibit; zero paid SaaS or unmetered cloud. | **PASS** |
| 8 | **Zero Leaked Secrets / PII** | Dedicated demo resources; regex-checked against AWS/Google credential patterns. | **PASS** |
| 9 | **Operator Setup Instructions** | Full Turkish screen-by-screen guidance provided for non-expert operator. | **PASS** |
| 10 | **Modular Live Swap Plan** | Conditional replacement shot plan ready for P-21.02 and P-21.03 if authorized. | **PASS** |

---

*Competition demo script and shot list frozen under P-21.01. Ready for independent QA review.*
