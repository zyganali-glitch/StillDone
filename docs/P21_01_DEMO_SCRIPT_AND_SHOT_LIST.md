# P-21.01 — Competition Demo Video Script & Shot List

**Document ID**: `docs/P21_01_DEMO_SCRIPT_AND_SHOT_LIST.md`  
**Task**: `P-21.01 — Freeze 2:30–2:50 demo script and shot list`  
**Governing Authority**: `AGENTS.md` § 3 (Closure Contract), § 4 (Core Product Invariant), § 9 (Live-First Law), § 10 (Evidence Provenance), § 22 (Operator Guidance); `docs/KILLER_DEMO_CONTRACT.md`; `plans/STILLDONE_MASTER_EXECUTION_PLAN.md` § P-21.01  
**Competition**: *Build, Ship, Shape: Amazon Developer Hackathon* (Devpost snapshot 2026-10-01)  
**Primary Track**: Alexa+ Track | **Secondary**: AWS Builder Mini Challenge, Open Source Mini Challenge  
**Official Competition Video Rule**: **Under 3 minutes (< 3:00 / < 180s)** per official Devpost rules.  
**StillDone Editorial Target**: **2 minutes 45 seconds (165 seconds)** - frozen within the internal project execution window of **2:30-2:50 (150s-170s)**.  

> **POST-SUBMISSION TRUTH RECORD (2026-10-18):** The final rendered and published video is **2:59 (179 seconds)** at https://youtu.be/c-c_cUzq1OM - verified by YouTube player metadata (`lengthSeconds`) and within the official < 180 s rule. The 2:45 (165 s) timeline in this document is the frozen **editorial script target**; its internal timecodes are NOT claimed as verified final edit cut points, and the chapter alignment values in the published YouTube description are the operator's post-edit values. This document is preserved as historical P-21.01 script/shot-list evidence.  
**Narration Language**: English (US/International, professional, clear, neutral cadence: ~129.5 words per minute, 356 total words).  
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
To make StillDone's invariant instantly intuitive to Devpost judges within seconds, the demo anchors on a clear three-stage departure timeline visible directly on the public exhibit:
1. **07:45 AM (Initial State)**: Pre-state family calendar event (`Leave for school` at 07:45 AM).
2. **07:30 AM (Target Verified / READY)**: User requests departure by 7:30. Prep task created and verified. Calendar shift paused for approval, approved, executed, and independently read back. Mission promoted to `READY` with immutable SHA-256 receipt.
3. **08:00 AM (External Drift / DRIFTED)**: External reschedule moves event to 08:00 AM. User asks *"Are we still ready?"* Fresh read-back observes contradiction. Status instantly downgrades to `DRIFTED`.

### 1.4 Canonical Capture & Production Directories
Per StillDone media conventions, capture destinations are strictly partitioned:
- **Lightweight Submission Screenshots**: `docs/assets/devpost/`
- **README Screenshots**: `docs/assets/readme/`
- **Raw Recording Media**: `_local_media/raw_clips/`
- **Voiceover Audio Tracks**: `_local_media/voiceover/`
- **Caption Files**: `_local_media/captions/`
- **Final Master Video Exports**: `_local_media/final_export/`

---

## 2. Complete Timestamped Scene Breakdown & Shot List

The video is partitioned into **8 contiguous, non-overlapping scenes** totaling exactly **165 seconds (2:45)**:

```
[0:00 - 0:15] Scene 1: The Failure of Ordinary AI Tool Completion (15s, 36 words)
[0:15 - 0:40] Scene 2: Canonical Mission & Real Pre-State Reads (25s, 52 words)
[0:40 - 1:05] Scene 3: AWS Bedrock Planning & Safe Tasks Mutation (25s, 54 words)
[1:05 - 1:35] Scene 4: Approval Boundary & Verified Calendar Shift (30s, 62 words)
[1:35 - 1:55] Scene 5: Predicate Verification & Immutable READY Receipt (20s, 44 words)
[1:55 - 2:15] Scene 6: The Real World Changes (External Calendar Drift) (20s, 43 words)
[2:15 - 2:35] Scene 7: "Are We Still Ready?" — Fresh Reconciliation to DRIFTED (20s, 43 words)
[2:35 - 2:45] Scene 8: Architecture, Open Standards & Closing Line (10s, 22 words)
Total Duration: 165s (2:45) | Total Words: 356 words | Speaking Cadence: ~129.5 WPM
```

---

### Scene 1: The Failure of Ordinary AI Tool Completion
- **Timecode**: `0:00 – 0:15` (15 seconds)
- **Narrative Objective**: Hook the judges immediately with the universal failure mode of today's autonomous assistants: mistaking API return codes for real-world truth.
- **Screen Display / Visual Action**:
  - File / URL: `artifacts/judge_exhibit/index.html` (or `https://stilldone-judge-exhibit.pages.dev`).
  - Target Section: Brand header (`.brand-header`), brand title (**"StillDone — Done, and still true."**), and evaluation provenance notice (`.fixture-notice`).
  - Operator Action: Open browser at top of page (100% zoom, full width 1920x1080). Hold steady on header, then gently scroll down to reveal the evaluation provenance notice. No clicking.
  - Optional Video Editing Graphic: Left third split-screen graphic displaying a generic chat bubble claiming *"All set! Scheduled your departure and packed backpacks!"* with a fake checkmark, contrasted with StillDone's core invariant badge: *An outcome is not complete until independently observed.*
  - Screenshot Target: `docs/assets/devpost/scene_01_header_thesis.png` (header banner + brand title).
- **On-Screen Text Callout**:
  - *"An API HTTP 200 is NOT verification."*
  - *"What happens when reality changes later?"*
- **Spoken Voiceover Narration (English)**:
  > *"Today's AI assistants treat an API HTTP 200 as mission complete. But tool success is not real-world verification. Welcome to StillDone: an autonomous runtime where outcomes require independent observation, and completion is revoked if reality drifts."*
- **Word Count**: 36 words (~144.0 WPM for 15s).
- **Evidence Provenance**: `LOCAL_EXECUTION` / Presentation thesis.
- **Evidence Reference**: `docs/PRODUCT_CONTRACT.md` § 1; `docs/P20_03_EVIDENCE_MANIFEST.md` (Claim C-01).
- **Privacy & Redaction**: Zero personal data or credentials.

---

### Scene 2: Canonical Mission & Real Pre-State Reads
- **Timecode**: `0:15 – 0:40` (25 seconds)
- **Narrative Objective**: Introduce the canonical killer mission, connect over Streamable HTTP MCP, and demonstrate pre-state reading of Google Calendar and Open-Meteo weather without claiming visitor-side live execution.
- **Screen Display / Visual Action**:
  - File / URL: `artifacts/judge_exhibit/index.html`.
  - Target Section: Hero Intent section (`#intent-title`), Canonical Intent text, top badges (`SIMULATED ALEXA+ EXPERIENCE`, `FIXTURE PLAYBACK`), and Departure Lifecycle Tracker (`.departure-story-card`).
  - Operator Action:
    1. Scroll to Hero Intent: cursor highlights *"Get my family ready for tomorrow morning. We need to leave by 7:30."*
    2. Pan across Departure Lifecycle Tracker to highlight Node 1: `1. Initial State: 07:45 AM (Seeded on family calendar)`.
    3. Scroll to Step 1 card (`P-13.01 Seed Demo State & Verify Pre-State`), click `<summary>` to expand evidence table (`start_time: 07:45:00 UTC`, `prep_task_absent: True`).
    4. Scroll to Step 2 card (`P-13.02 Plan Intent & Observe Weather`), click `<summary>` to expand evidence table (`weather: mild/rainy`, `model_authority: ZERO`).
  - Screenshot Target: `docs/assets/devpost/scene_02_prestate_reads.png` (expanded Step 1 & Step 2 evidence tables).
  - Baseline vs Conditional Note: Baseline shot uses the static exhibit's recorded fixture playback. Authentic historical live reads are preserved in dated documentation (`docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md`, `docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md`).
- **Spoken Voiceover Narration (English)**:
  > *"Our mission: "Get my family ready for tomorrow morning. We need to leave by 7:30." In StillDone's Streamable HTTP MCP architecture, the runtime begins by observing ground truth. Replaying canonical pre-state observations, tomorrow's departure is scheduled for 7:45 AM, and weather indicates morning rain. StillDone requires real pre-state before proposing any action."*
- **Word Count**: 52 words (~124.8 WPM for 25s).
- **Evidence Provenance**:
  - Presentation: `SIMULATED ALEXA+ EXPERIENCE`.
  - Exhibit Playback: `FIXTURE`.
  - Historical Record: `RECORDED_LIVE` (`docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md`, `docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md`).
- **Privacy & Redaction**: Dedicated disposable demo resources only (`StillDone Demo` calendar, non-sensitive public coordinates).

---

### Scene 3: AWS Bedrock Planning & Safe Tasks Mutation
- **Timecode**: `0:40 – 1:05` (25 seconds)
- **Narrative Objective**: Demonstrate Amazon Bedrock Nova Micro plan compilation with zero model authority, followed by autonomous digital preparation task creation in Google Tasks with separate read-back verification.
- **Screen Display / Visual Action**:
  - File / URL: `artifacts/judge_exhibit/index.html`.
  - Target Section: Step 2 (`P-13.02 Plan Intent & Observe Weather`) and Step 3 (`P-13.03 Create & Verify Prep Task`).
  - Operator Action:
    1. Focus on Step 2 evidence table: cursor indicates `model_authority: ZERO`.
    2. Scroll down to Step 3 card (`P-13.03 Create & Verify Prep Task`).
    3. Click `<summary>` to expand Step 3 evidence table: highlight `task_title: Pack backpacks`, `status: needsAction`.
    4. Highlight metadata badges: `Writes: 1` and `Read-back: VERIFIED`.
  - Screenshot Target: `docs/assets/devpost/scene_03_tasks_prep_verified.png` (Step 3 expanded evidence table showing distinct read-back).
  - Baseline vs Conditional Note: Baseline shot demonstrates the digital task verification in the static exhibit. If P-21.02 is authorized and executed, conditional replacement shows real Google Tasks web tab alongside CLI.
- **On-Screen Text Callout**:
  - *"Zero Model Authority: Model proposes; deterministic code verifies."*
  - *"Digital Prep Task: Verified via distinct independent read-back."*
- **Spoken Voiceover Narration (English)**:
  > *"Amazon Bedrock Nova Micro compiles the intent into a typed proposal. But the model has zero execution authority. Replaying recorded live execution, StillDone creates a digital preparation task in Google Tasks: "Pack backpacks." Write success is never verification. A separate read adapter reads back the task list, verifying it is active before awarding progress."*
- **Word Count**: 54 words (~129.6 WPM for 25s).
- **Evidence Provenance**:
  - LLM Planning: `RECORDED_LIVE` (`LIVE_AWS` baseline record in `docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md`, dated 2026-10-05).
  - Tasks Mutation: `RECORDED_LIVE` (`LIVE_GOOGLE` baseline in `docs/P06_07_LIVE_TASKS_VERIFIED_EVIDENCE.md`) & `FIXTURE` (exhibit playback).
- **Privacy & Redaction**: Disposable demo IDs only. Zero personal task lists.

---

### Scene 4: Approval Boundary & Verified Calendar Shift
- **Timecode**: `1:05 – 1:35` (30 seconds)
- **Narrative Objective**: Showcase StillDone's human authorization boundary—shifting departure time is high-impact, so execution halts fail-closed until an explicit single-use grant is consumed, followed by separate read-back.
- **Screen Display / Visual Action**:
  - File / URL: `artifacts/judge_exhibit/index.html`.
  - Target Section: Step 4 card (`P-13.04 Pause at Calendar Approval Boundary`), Step 5 card (`P-13.05 Approve, Execute & Verify Calendar Shift`), and sidebar Human Authorization Boundary card (`#approval-title`).
  - Operator Action:
    1. Scroll to Step 4 card, click `<summary>` to expand: highlight `approval_required: True`, `calendar_writes: 0`, badge `PAUSED_APPROVAL`.
    2. Pan camera / scroll slightly to bring sidebar **Human Authorization Boundary** card (`#approval-title`) into clear view: highlight target action `calendar.update` on Google Calendar (07:45 AM → 07:30 AM) and cryptographic fingerprint (`sha256:...`).
    3. Scroll to Step 5 card, click `<summary>` to expand: highlight `start_time: 07:30:00 UTC`, `writes_performed: 1`, badge `APPROVED`, and `Read-back: VERIFIED`.
  - Screenshot Target: `docs/assets/devpost/scene_04_approval_boundary.png` (sidebar approval card side-by-side with Step 4 and Step 5 cards).
  - Baseline vs Conditional Note: The static exhibit displays the static record of the paused boundary and approved shift. Live CLI execution of `p13_killer_mission.py` is reserved for conditional P-21.02 replacement.
- **On-Screen Text Callout**:
  - *"Execution Boundary: Calendar shift halts fail-closed with 0 writes."*
  - *"Single-Use Approval Grant: Replays strictly rejected."*
- **Spoken Voiceover Narration (English)**:
  > *"Next, shifting departure from 7:45 to 7:30 is high impact. StillDone pauses fail-closed at the human authorization boundary with zero writes performed. A bound cryptographic approval card is emitted with an immutable SHA-256 fingerprint. Once the operator approves, StillDone consumes the single-use grant, executes the calendar update, and immediately invokes an independent read-back, verifying the 7:30 departure with recorded Google Calendar proof."*
- **Word Count**: 62 words (~124.0 WPM for 30s).
- **Post-Submission Provenance Clarification (2026-10-18)**:
  - The historical voiceover narration above is preserved verbatim as a record of the submitted video script.
  - The complete displayed scene in the video and public exhibit (`artifacts/judge_exhibit/index.html`) is deterministic `FIXTURE` playback.
  - **P-06.08** (`docs/P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md`, `RECORDED_LIVE` / `LIVE_GOOGLE`) contains the historical real Google Calendar provider mutation (`07:45 → 07:30`), cryptographically bound `ApprovalGrant` authorization evaluation (`AUTHORIZED_BY_BOUND_APPROVAL`), and independent `events.get` read-back.
  - **P-11.06** (`docs/P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md`, `LOCAL_EXECUTION` / `FIXTURE`) separately proves durable single-use approval consumption (`ApprovalLedger`) and replay rejection through local fixtures (`FakeGoogleCalendarTransport`, with live Google mutation `NOT_RUN / BLOCKED`).
  - Their full combined live execution (the complete P-11 durable single-use consumption/replay lifecycle integrated with a real Google Calendar mutation) is **not established**.
- **Evidence Provenance**:
  - Boundary: `LOCAL_EXECUTION` & `FIXTURE` (`docs/P11_05_CALENDAR_UPDATE_NOT_RUN_BEFORE_APPROVAL_EVIDENCE.md`; live mutation `NOT_RUN / BLOCKED`).
  - Approved Execution & Read-back: **P-06.08** (`RECORDED_LIVE` / `LIVE_GOOGLE` in `docs/P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md`) historically evaluated a cryptographically bound `ApprovalGrant` (`AUTHORIZED_BY_BOUND_APPROVAL`) before a real Google Calendar update (`07:45 → 07:30`) and independent `events.get` provider read-back; **P-11.06** (`LOCAL_EXECUTION` & `FIXTURE` in `docs/P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md`) separately validated durable single-use `ApprovalGrant` consumption (`ApprovalLedger`) and replay prevention on `FakeGoogleCalendarTransport` (live mutation `NOT_RUN / BLOCKED`; full combined live execution not established).
- **Privacy & Redaction**: Disposable demo calendar only (`StillDone Demo`).

---

### Scene 5: Predicate Verification & Immutable READY Receipt
- **Timecode**: `1:35 – 1:55` (20 seconds)
- **Narrative Objective**: Demonstrate deterministic readiness computation from independent predicates, resulting in the issuance of an immutable SHA-256 receipt projection, without fabricating an animated UI transition.
- **Screen Display / Visual Action**:
  - File / URL: `artifacts/judge_exhibit/index.html`.
  - Target Section: Step 6 card (`P-13.06 Produce READY Mission Receipt`), Departure Lifecycle Tracker Node 2 (`07:30 AM - Target Verified / READY`), and sidebar Immutable Historical Receipt card (`#receipt-title`).
  - Operator Action:
    1. Scroll to Step 6 card, click `<summary>` to expand evidence table: highlight `predicates_count: 3`, badge `VERIFIED`.
    2. Pan to sidebar **Immutable Historical Receipt** card (`#receipt-title`): highlight badge `READY AT ISSUANCE` and full canonical receipt SHA-256 hash.
    3. Scroll up briefly to Departure Lifecycle Tracker Node 2: highlight `2. Target Verified (READY) - 07:30 AM`.
  - Chronological Storytelling Callout: An on-screen editing graphic or subtle zoom highlights the `READY AT ISSUANCE` milestone badge and SHA-256 fingerprint. The operator does NOT attempt to click or trigger an interactive state change.
  - Screenshot Target: `docs/assets/devpost/scene_05_ready_receipt.png` (sidebar Receipt Card with `READY AT ISSUANCE` badge and SHA-256 hash).
- **On-Screen Text Callout**:
  - *"READY is computed, not assumed."*
  - *"Immutable Receipt SHA-256: Anchored to verified predicates."*
- **Spoken Voiceover Narration (English)**:
  > *"With weather checked, digital prep task verified, and departure confirmed at 7:30, all predicates evaluate true. StillDone deterministically promotes the mission to READY, issuing an immutable receipt with a SHA-256 hash anchored to the verified facts. But in real life, reality never stands still."*
- **Word Count**: 44 words (~132.0 WPM for 20s).
- **Evidence Provenance**: `LOCAL_EXECUTION` (deterministic predicate engine); `docs/P20_03_EVIDENCE_MANIFEST.md` (Claim C-03).
- **Privacy & Redaction**: Zero PII. Hash is a SHA-256 digest of normalized domain predicates.

---

### Scene 6: The Real World Changes (External Calendar Drift)
- **Timecode**: `1:55 – 2:15` (20 seconds)
- **Narrative Objective**: Introduce real-world external drift using the static exhibit's labeled deterministic departure tracker and Drift Law explanation section, without unapproved live calendar edits.
- **Screen Display / Visual Action**:
  - File / URL: `artifacts/judge_exhibit/index.html`.
  - Target Section: Departure Story Tracker Node 3 (`08:00 AM - External Drift / DRIFTED`) and sidebar Drift Law & State Invariant card (`#drift-title`).
  - Operator Action:
    1. Scroll to Departure Lifecycle Tracker, focusing directly on Node 3: `3. External Drift (DRIFTED) - 08:00 AM (Moved externally -> Ready revoked)`.
    2. Pan to sidebar **Drift Law & State Invariant** card (`#drift-title`): cursor highlights the section title *"Why is current truth DRIFTED while the receipt was READY?"*.
    3. Slowly scroll through the explanation card highlighting: *"In Step 7, an external change moved the calendar departure to 08:00 AM. StillDone detected the contradiction during independent read-back and downgraded the mission to DRIFTED."*
  - Baseline vs Conditional Note: The baseline recording uses the static exhibit's labeled departure tracker and explanation card. Live capture of the operator manually dragging an event in `calendar.google.com` is strictly CONDITIONAL (only if P-21.03 is authorized and executed).
  - Screenshot Target: `docs/assets/devpost/scene_06_departure_drift_tracker.png` (Departure Story Card Node 3 + Drift Law sidebar card).
- **On-Screen Text Callout**:
  - *"External Reality Drifts: Reschedule moves departure to 08:00 AM."*
  - *"Drift Law: Historical receipts never override current truth."*
- **Spoken Voiceover Narration (English)**:
  > *"Later that evening, reality changes. As tracked in our departure lifecycle, an external reschedule moves departure to 8:00 AM. Ordinary agents would still report mission complete based on old execution logs. But StillDone enforces the Drift Law: historical receipts never override current truth."*
- **Word Count**: 43 words (~129.0 WPM for 20s).
- **Evidence Provenance**: `FIXTURE` (exhibit departure tracker) & `LOCAL_EXECUTION` (Drift Law contract); `docs/KILLER_DEMO_CONTRACT.md` § Drift moment; `docs/P20_03_EVIDENCE_MANIFEST.md` (Claim C-02).
- **Privacy & Redaction**: Zero external browsing or private accounts shown in baseline.

---

### Scene 7: "Are We Still Ready?" — Fresh Reconciliation to DRIFTED
- **Timecode**: `2:15 – 2:35` (20 seconds)
- **Narrative Objective**: Demonstrate fresh re-verification: the user asks *"Are we still ready?"*, StillDone reads the fresh state, detects the contradiction, downgrades to `DRIFTED`, and preserves the immutable historical receipt.
- **Screen Display / Visual Action**:
  - File / URL: `artifacts/judge_exhibit/index.html`.
  - Target Section: Top Hero Status Bar (`.status-hero-bar.drifted`), Alexa+ Voice Summary Card (`.voice-card`), and Step 7 card (`P-13.07 External Mutation & Drift Reconciliation`).
  - Operator Action:
    1. Scroll up to the Hero Status Bar: cursor highlights the prominent amber **`DRIFTED`** status pill (`Current System-of-Record Truth: DRIFTED`).
    2. Focus on the Alexa+ Voice Card (`.voice-card`): highlight spoken response: *“I noticed your departure moved to 8:00 AM on Google Calendar, so tomorrow morning is no longer ready for 7:30...”*
    3. Scroll down to Step 7 card (`P-13.07`), click `<summary>` to expand: highlight `observed_start: 08:00:00 UTC`, `predicate_truth: False`, badge `DRIFT_DETECTED`.
    4. Pan to sidebar Receipt Card: point out that the canonical receipt hash `87720e51...` is **strictly identical and intact**.
  - Screenshot Target: `docs/assets/devpost/scene_07_reconciliation_drifted.png` (amber DRIFTED hero status pill alongside Alexa+ voice response).
- **On-Screen Text Callout**:
  - *"Predicate Evaluation: FALSE (Expected 07:30, Observed 08:00)."*
  - *"State Reconciled: READY → DRIFTED."*
  - *"Historical Receipt Hash: Unchanged & Immutable."*
- **Spoken Voiceover Narration (English)**:
  > *"When asked, "Are we still ready?", StillDone evaluates fresh read-back proof. The departure predicate fails. Instantly, StillDone revokes readiness, downgrading current state to DRIFTED and explaining what changed. Meanwhile, the historical receipt hash remains cryptographically intact on disk as an immutable audit record."*
- **Word Count**: 43 words (~129.0 WPM for 20s).
- **Evidence Provenance**: `FIXTURE` (exhibit playback) & `LOCAL_EXECUTION` (fresh session revalidation proof in `scripts/p12_07_proof.py`).
- **Privacy & Redaction**: Zero secrets.

---

### Scene 8: Architecture, Open Standards & Closing Line
- **Timecode**: `2:35 – 2:45` (10 seconds)
- **Narrative Objective**: Deliver a punchy closing summary linking StillDone's open-standard Streamable HTTP MCP architecture, AWS Bedrock Nova Micro, comprehensive automated tests, and the final thesis.
- **Screen Display / Visual Action**:
  - File / URL: `artifacts/judge_exhibit/index.html`.
  - Target Section: Evidence Provenance Breakdown card (`#prov-title`), page footer (`footer`), and GitHub evidence-links section. Exhibit footage ONLY (no separate closing title card).
  - Operator Action:
    1. Scroll to the Evidence Provenance Breakdown card (`#prov-title`): highlight explanatory sections showing recorded Bedrock inference, recorded AgentCore Streamable HTTP MCP execution, and fixture playback.
    2. Scroll to page footer: highlight text showing *Zero Personal Spend ($0.00) • Verified Provenance • No unmetered cloud endpoints*.
    3. Conclude directly on the public exhibit's GitHub evidence-links section and footer showing:
       - **StillDone — Done, and still true.**
       - *github.com/zyganali-glitch/StillDone*
       - *Exhibit footage ONLY; no separate title card.*
  - Visual Note: Scene 08 ends strictly on actual recorded public exhibit footage (`#prov-title`, footer, and open-source links). No separate StillDone closing title card is generated or appended.
  - Screenshot Target: `docs/assets/devpost/scene_08_architecture_closing.png` (provenance card, footer, and GitHub evidence links; filename is historical and does not imply a separate title card).
- **On-Screen Text Callout**:
  - *Streamable HTTP MCP | Amazon Bedrock Nova Micro | AgentCore Runtime*
  - *Comprehensive Automated Tests | 100% Clean-Room Open Source*
  - *zyganali-glitch/StillDone*
- **Spoken Voiceover Narration (English)**:
  > *"Built with Amazon Bedrock, AgentCore, and Streamable HTTP MCP, backed by comprehensive automated tests. Make sure it's StillDone: Done, and still true."*
- **Word Count**: 22 words (~132.0 WPM for 10s).
- **Evidence Provenance**: `LOCAL_EXECUTION` (test metrics, architecture, open-source repository).
- **Privacy & Redaction**: Public GitHub repository URL only. Zero developer tokens or machine paths.

---

## 3. Full Continuous Narration Script (Voiceover / Captions)

*Timing Target: 165 seconds (~2 minutes 45 seconds). Authoritative Word Count: 356 words. Average Speaking Cadence: ~129.5 words per minute.*

```text
[0:00 - 0:15]
Today's AI assistants treat an API HTTP 200 as mission complete. But tool success is not real-world verification. Welcome to StillDone: an autonomous runtime where outcomes require independent observation, and completion is revoked if reality drifts.

[0:15 - 0:40]
Our mission: "Get my family ready for tomorrow morning. We need to leave by 7:30." In StillDone's Streamable HTTP MCP architecture, the runtime begins by observing ground truth. Replaying canonical pre-state observations, tomorrow's departure is scheduled for 7:45 AM, and weather indicates morning rain. StillDone requires real pre-state before proposing any action.

[0:40 - 1:05]
Amazon Bedrock Nova Micro compiles the intent into a typed proposal. But the model has zero execution authority. Replaying recorded live execution, StillDone creates a digital preparation task in Google Tasks: "Pack backpacks." Write success is never verification. A separate read adapter reads back the task list, verifying it is active before awarding progress.

[1:05 - 1:35]
Next, shifting departure from 7:45 to 7:30 is high impact. StillDone pauses fail-closed at the human authorization boundary with zero writes performed. A bound cryptographic approval card is emitted with an immutable SHA-256 fingerprint. Once the operator approves, StillDone consumes the single-use grant, executes the calendar update, and immediately invokes an independent read-back, verifying the 7:30 departure with recorded Google Calendar proof.

[1:35 - 1:55]
With weather checked, digital prep task verified, and departure confirmed at 7:30, all predicates evaluate true. StillDone deterministically promotes the mission to READY, issuing an immutable receipt with a SHA-256 hash anchored to the verified facts. But in real life, reality never stands still.

[1:55 - 2:15]
Later that evening, reality changes. As tracked in our departure lifecycle, an external reschedule moves departure to 8:00 AM. Ordinary agents would still report mission complete based on old execution logs. But StillDone enforces the Drift Law: historical receipts never override current truth.

[2:15 - 2:35]
When asked, "Are we still ready?", StillDone evaluates fresh read-back proof. The departure predicate fails. Instantly, StillDone revokes readiness, downgrading current state to DRIFTED and explaining what changed. Meanwhile, the historical receipt hash remains cryptographically intact on disk as an immutable audit record.

[2:35 - 2:45]
Built with Amazon Bedrock, AgentCore, and Streamable HTTP MCP, backed by comprehensive automated tests. Make sure it's StillDone: Done, and still true.
```

> [!NOTE]
> **Post-Submission Provenance Clarification for Scene 4 `[1:05 - 1:35]` Narration (2026-10-18)**:
> The historical narration block `[1:05 - 1:35]` above is preserved verbatim as a record of the submitted video script. To prevent conflating historical live execution with deterministic fixture playback:
> 1. The complete displayed Scene 4 sequence in the video and public exhibit (`artifacts/judge_exhibit/index.html`) is deterministic `FIXTURE` playback.
> 2. **P-06.08** (`docs/P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md`, `RECORDED_LIVE` / `LIVE_GOOGLE`) contains the historical real Google Calendar provider mutation (`07:45 → 07:30`), cryptographically bound `ApprovalGrant` authorization evaluation (`AUTHORIZED_BY_BOUND_APPROVAL`), and independent `events.get` read-back.
> 3. **P-11.06** (`docs/P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md`, `LOCAL_EXECUTION` / `FIXTURE`) separately proves durable single-use approval consumption (`ApprovalLedger`) and replay rejection through local fixtures (`FakeGoogleCalendarTransport`, with live Google mutation `NOT_RUN / BLOCKED`).
> 4. Their full combined live execution (the complete P-11 durable single-use consumption/replay lifecycle integrated with a real Google Calendar API mutation) is **not established**.

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
| **Scene 4** | Calendar Approval Boundary Pause | `LOCAL_EXECUTION` & `FIXTURE` | `docs/P11_05_CALENDAR_UPDATE_NOT_RUN_BEFORE_APPROVAL_EVIDENCE.md` | 0 writes performed without human approval grant; fail-closed boundary (`FakeGoogleCalendarTransport`; live mutation `NOT_RUN / BLOCKED`). |
| **Scene 4** | Approved Calendar Update & Read-back | `RECORDED_LIVE` (`LIVE_GOOGLE`, P-06.08) & `LOCAL_EXECUTION` / `FIXTURE` (P-11.06) | `docs/P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md` `docs/P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md` | P-06.08 historically evaluated a cryptographically bound `ApprovalGrant` (`AUTHORIZED_BY_BOUND_APPROVAL`) before the real OAuth calendar update and separate read-back; P-11.06 separately validated durable single-use `ApprovalGrant` consumption (`ApprovalLedger`) and replay rejection in local fixtures (`FakeGoogleCalendarTransport`, live mutation `NOT_RUN / BLOCKED`; full combined live execution not established). |
| **Scene 5** | Deterministic READY Receipt Issuance | `LOCAL_EXECUTION` | `src/stilldone/receipt.py` `scripts/p13_killer_mission.py` | SHA-256 hash computed deterministically from verified predicates; 0 external writes. |
| **Scene 6** | External Calendar Drift (07:30 → 08:00) | `FIXTURE` (baseline) / `LIVE_GOOGLE` (conditional) | `docs/KILLER_DEMO_CONTRACT.md` § Drift | Baseline uses static exhibit departure story tracker; live calendar edit is conditional. |
| **Scene 7** | Fresh Re-verification & Reconciliation | `LOCAL_EXECUTION` & `FIXTURE` | `scripts/p12_07_proof.py` `docs/P13_KILLER_MISSION_AUDIT.md` | Fresh process reads contradictory state, revokes READY to DRIFTED, preserves receipt hash. |
| **Scene 8** | MCP Server, AgentCore & Test Suite | `RECORDED_LIVE` (`LIVE_AWS`) & `LOCAL_EXECUTION` | `docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md` `.github/workflows/ci.yml` | Real AgentCore microVM proved live in P-05.06 and torn down cleanly ($0.00 spend). Dual-runtime tests pass. |

### Negative Bounds & Truth Disclosures (Devpost & Competition Integrity):
1. **No Live Voice Device or Audio Synthesis in Codebase**: StillDone does not operate an Echo Show device or contain TTS voice synthesis code. Voice synthesis belongs strictly to video narration production (P-21.04).
2. **Simulated Alexa+ Presentation**: The Alexa+ interface is explicitly labeled as `SIMULATED ALEXA+ EXPERIENCE`. Direct Alexa+ partner access was classified as `NOT_ESTABLISHED`.
3. **Static Exhibit Has Zero Visitor Backend Execution**: The public exhibit at `https://stilldone-judge-exhibit.pages.dev` executes 0 visitor cloud calls and 0 backend mutations ($0.00 spend).
4. **Current Remote MCP MicroVM is NOT_RUN**: The Bedrock AgentCore serverless microVM proved in P-05.06 was torn down cleanly. A permanent unmetered endpoint is not maintained to guarantee $0.00 personal spend.
5. **No Physical Task Completion**: StillDone verifies digital Google Tasks list state; it never claims physical backpacks were packed.

---

## 5. Conditional Replacement Shot Plan (for P-21.02 & P-21.03)

If the operator decides to authorize live credentials and execute **P-21.02** (Fresh canonical live mission) and **P-21.03** (External drift and fresh reconciliation), the following **modular replacement shots** can be seamlessly swapped into the video without changing the timing structure, script length, or narrative flow:

```mermaid
flowchart TD
    subgraph Baseline Track (Default - 100% Feasible Today)
        B1["Scene 3: Exhibit Playback + Recorded Bedrock Log"]
        B2["Scene 4: Exhibit Approval + Recorded Google Write"]
        B3["Scene 6: Exhibit Departure Story Tracker"]
        B4["Scene 7: Exhibit Step 7 DRIFTED Card + Voice Pill"]
    end
    subgraph Conditional Live Track (If P-21.02 & P-21.03 Authorized)
        L1["Scene 3 Replacement: Live Google Tasks Tab Refresh + CLI"]
        L2["Scene 4 Replacement: Real Google Calendar Event Shift + CLI Readback"]
        L3["Scene 6 Replacement: Screen Capture of Operator Editing Google Calendar"]
        L4["Scene 7 Replacement: Live CLI Execution of 'Are we still ready?'"]
    end
    B1 -.->|P-21.02 Operator Auth & Creds| L1
    B2 -.->|P-21.02 Operator Auth & Creds| L2
    B3 -.->|P-21.03 Operator Manual Drift| L3
    B4 -.->|P-21.03 Operator Query| L4
```

### Preflight Requirements for Conditional Live Execution:
Live execution of `scripts/p13_killer_mission.py` requires all of the following explicit conditions:
1. Operator consent flag (`--operator-approved`);
2. Exact 40-character commit SHA (`--source-sha <SHA>`);
3. Writable durable storage directory (`--storage-dir <DIR>`);
4. Dedicated demo calendar container ID (`--demo-calendar-id <ID>`, never primary or default);
5. Dedicated demo task list ID (`--demo-task-list-id <ID>`, never primary or default);
6. Target mission date (`--demo-date <YYYY-MM-DD>`);
7. Valid AWS Bedrock credentials and Google OAuth token established in environment.

*Passing `--live --operator-approved` alone will halt fail-closed if container IDs or source SHA are missing.*

### Shot Swap Details:
1. **Scene 3 Swap (P-21.02 Live Tasks)**:
   - *Baseline*: Public Judge Exhibit Step 3 card + PIP callout of `docs/P06_07_LIVE_TASKS_VERIFIED_EVIDENCE.md`.
   - *Replacement*: Split-screen showing terminal running `uv run python scripts/p13_killer_mission.py --live ...` with full preflight arguments alongside a real browser tab of Google Tasks (`StillDone Demo` list). The task "Pack backpacks" appears live, followed by CLI read-back verification log.
   - *Provenance Promotion*: Promotes from `FIXTURE` to `LIVE_GOOGLE`.

2. **Scene 4 Swap (P-21.02 Live Calendar)**:
   - *Baseline*: Public Judge Exhibit Step 4 & 5 cards showing approved shift.
   - *Replacement*: Split-screen showing the terminal pausing at `PAUSED_FOR_APPROVAL`, operator providing approval grant, followed by Google Calendar browser tab automatically updating the `Leave for school` event from `7:45` to `7:30`, followed by independent read-back log.
   - *Provenance Promotion*: Promotes from `FIXTURE` to `LIVE_GOOGLE`.

3. **Scene 6 Swap (P-21.03 Live Drift Injection)**:
   - *Baseline*: Judge Exhibit Departure Timeline Node 3 highlight (`08:00 AM - External Drift`) and Drift Law explanation card (`#drift-title`).
   - *Replacement*: Live screen capture of the operator in Google Calendar manually dragging the `Leave for school` event from `7:30 AM` to `8:00 AM` and clicking Save.
   - *Provenance*: Remains authentic `LIVE_GOOGLE` external human interaction.

4. **Scene 7 Swap (P-21.03 Live Fresh Reconciliation)**:
   - *Baseline*: Judge Exhibit Step 7 card + amber `DRIFTED` state hero bar.
   - *Replacement*: Terminal running fresh session proof or live CLI query. Terminal outputs contradictory read-back (`start_time=08:00:00 UTC`), predicate evaluating FALSE, and mission state reconciling to `DRIFTED`.
   - *Provenance Promotion*: Promotes to `LIVE_GOOGLE` read-back + `LOCAL_EXECUTION` reconciliation.

*Note: If operator credentials remain unconfigured, the Baseline Track remains 100% compliant, fully verified, and competition-ready without any unsupported claims.*

---

## 6. Operator Screen Recording Guide (Türkçe Ekran Kurulum Rehberi)

Bu bölüm, teknik uzman olmayan operatörün Windows ortamında ekran kaydını sorunsuz, güvenli ve profesyonel bir şekilde alabilmesi için hazırlanmıştır (`AGENTS.md` § 22 uyumlu).

### 6.1 Gerekli Araçlar ve Ekran Ayarları
1. **Ekran Çözünürlüğü**: `1920 x 1080` (Full HD, 16:9). Windows görüntü ölçekleme (DPI) ayarı `%100` olmalıdır.
2. **Kayıt Aracı**:
   - *Seçenek A (En Kolay — Yerleşik)*: **Windows Game Bar** (`Win + Alt + R` tuşlarına basarak kaydı başlatın ve durdurun).
   - *Seçenek B (Alternatif)*: **OBS Studio** (Ücretsiz ve açık kaynak; Pencere Yakalama / Display Capture modunda 1080p 30/60 FPS).
   - *Seçenek C*: **Windows Ekran Alıntısı Aracı (Snipping Tool)** Video Modu.
3. **Tarayıcı Hazırlığı (Google Chrome veya Microsoft Edge)**:
   - Tarayıcıyı tam ekran (`F11`) veya temiz bir pencerede açın.
   - Yer imleri çubuğunu gizleyin (`Ctrl + Shift + B`).
   - Yakınlaştırma seviyesini `%100` (`Ctrl + 0`) yapın.
   - Tarayıcı koyu temasını (Dark Mode) aktif hale getirin.

### 6.2 Adım Adım Ekran Kayıt Akışı (Varsayılan Statik Sergi Modu)
1. **Başlangıç (Scene 1 — 0:00 - 0:15)**:
   - Yerel dosya: `artifacts/judge_exhibit/index.html` (veya canlı yayın `https://stilldone-judge-exhibit.pages.dev`).
   - En üstteki kahraman başlığı (`StillDone — Done, and still true.`) ve altındaki kanıt bildirim kutusunu gösterin. Tıklama yapmayın.
2. **Görev ve Ön Durum (Scene 2 — 0:15 - 0:40)**:
   - Doğal dil komutunu gösterin (`Get my family ready...`).
   - Kalkış zaman çizelgesinde 1. Düğümü (`07:45 AM - Initial State`) vurgulayın.
   - Adım 1 ve Adım 2 kartlarındaki detay özetlerine (`<summary>`) tıklayarak kanıt tablolarını açın.
3. **Planlama ve Görev Doğrulama (Scene 3 — 0:40 - 1:05)**:
   - Adım 2'deki `model_authority: ZERO` satırını gösterin.
   - Adım 3 kartına kaydırın, özet kutusuna tıklayarak açın. `Pack backpacks` görevinin oluşturulduğunu ve ayrı okuma ile doğrulandığını (`VERIFIED`) gösterin.
4. **Onay Sınırı ve Takvim Değişimi (Scene 4 — 1:05 - 1:35)**:
   - Adım 4'teki onay bekleyen duraklamayı (`PAUSED_APPROVAL`) gösterin.
   - Yan paneldeki İnsan Yetkilendirme Sınırı kartına (`Human Authorization Boundary`) odaklanın.
   - Adım 5'e kaydırıp detayını açın: Takvimin 07:30'a güncellendiğini ve bağımsız okuma ile doğrulandığını gösterin.
5. **READY Makbuzu (Scene 5 — 1:35 - 1:55)**:
   - Adım 6 kartına kaydırıp detayını açın: 3 yüklemin doğrulandığını ve SHA-256 makbuzunun üretildiğini gösterin.
   - Yan paneldeki `Immutable Historical Receipt` kartındaki `READY AT ISSUANCE` yeşil rozetini gösterin. Tıklama ile animasyon yapmaya çalışmayın; sayfa zaten son durumu göstermektedir.
6. **Gerçek Dünyada Sapma (Scene 6 — 1:55 - 2:15)**:
   - Kalkış zaman çizelgesindeki 3. Düğüme (`08:00 AM - External Drift`) odaklanın.
   - Yan paneldeki `Drift Law & State Invariant` kartını göstererek durumun neden DRIFTED olduğunu ekranda vurgulayın.
7. **Sapma Uzlaşması (Scene 7 — 2:15 - 2:35)**:
   - Sayfanın en üstüne kaydırın: Turuncu renkli `DRIFTED` durum çubuğunu ve Alexa+ sesli yanıt metnini gösterin.
   - Adım 7 kartını açarak 08:00 sapmasının tespit edildiğini gösterin. Orijinal makbuz özetinin değişmediğini belirtin.
8. **Kapanış ve Mimari (Scene 8 — 2:35 - 2:45)**:
   - Sayfa altındaki kanıt kartına (`#prov-title`), alt bilgiye ve GitHub açık kaynak bağlantılarına odaklanıp videoyu doğrudan sergi görüntüsüyle bitirin (ayrı bir StillDone kapanış kartı eklenmez; sadece gerçek sergi görüntüleri kullanılır).

### 6.3 Güvenlik, Gizlilik ve Kart/Ödeme Uyarıları (KRİTİK)
- **Kredi Kartı / Ödeme Riski**: Bu çekim için **kesinlikle hiçbir ücretli servise abone olunmaz veya harcama yapılmaz**. Harcama hedefi kesin olarak `$0.00`'dır.
- **Şifre ve Belirteç Gizliliği**:
  - Ekran kaydı sırasında terminalde veya tarayıcıda AWS kimlik anahtarları, Google OAuth belirteçleri veya `.env` dosyaları **asla görünmemelidir**.
  - Tarayıcı uzantıları, kişisel yer imleri ve bildirimler (`Windows Bildirimleri -> Odaklanma Yardımı: Açık`) kapatılmalıdır.

---

## 7. Submission Readiness & Honest Phase Status

Per StillDone's honesty contract (`AGENTS.md` § 3), planned future production gates are clearly separated from completed script/planning deliverables:

| # | Item / Gate | Classification | Evidence / Source | Current Phase Status |
|---|---|---|---|---|
| 1 | **Video Duration Target** | Internal Editorial Target | 165s (2:45), strictly within Devpost rule (< 3:00) and plan window (2:30–2:50). | **SCRIPT_FROZEN** |
| 2 | **Authoritative Spoken Narration** | Script Deliverable | 356 words (~129.5 WPM across 8 contiguous scenes). | **SCRIPT_FROZEN** |
| 3 | **Departure Lifecycle Narrative** | Story Architecture | Visualized across 3 stages (07:45 → 07:30 → 08:00) using static exhibit elements. | **SCRIPT_FROZEN** |
| 4 | **UI Shot-List Parity** | Recording Plan | Every baseline shot maps to static visible sections and details/summary controls. | **DOCUMENTED_AND_VERIFIED** |
| 5 | **Provenance Truthfulness** | Evidence Integrity | Strict labeling of FIXTURE, RECORDED_LIVE, LOCAL_EXECUTION, SIMULATED ALEXA+. | **DOCUMENTED_AND_VERIFIED** |
| 6 | **Zero Personal Spend ($0.00)** | Cost Boundary | Baseline recording uses local browser and static exhibit ($0.00 spend). | **POLICY_VERIFIED** |
| 7 | **Targeted Credential Scan** | Security Audit | Targeted substring assertions confirm absence of AWS and Google credential prefixes. | **VERIFIED_TARGETED_SCAN** |
| 8 | **Operator Setup Guidance** | Operator Support | Comprehensive Turkish screen-by-screen recording instructions provided. | **DOCUMENTED_AND_VERIFIED** |
| 9 | **Modular Live Swap Plan** | Fallback & Execution | Explicit preflights and swap instructions defined for P-21.02/P-21.03 if authorized. | **DOCUMENTED_AND_VERIFIED** |
| 10 | **Video Screen Recording** | Production Execution | Screen capture execution belongs to Phase P-21.02 / P-21.03. | **PLANNED / NOT_RUN** |
| 11 | **Audio TTS / Voiceover & Captions** | Audio Production | Spoken audio file generation and caption alignment belong to Phase P-21.04. | **PLANNED / NOT_RUN** |
| 12 | **Public Video Playback & Submission** | Release Verification | Final video duration and public playback check belong to Phase P-21.05 / P-22. | **PLANNED / NOT_RUN** |

---

*Competition demo script and shot list frozen under P-21.01. Ready for independent QA review.*
