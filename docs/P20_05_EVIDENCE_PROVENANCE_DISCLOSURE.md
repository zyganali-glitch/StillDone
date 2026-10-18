# P-20.05 — Evidence Provenance & Simulation Disclosure

**Document ID**: `docs/P20_05_EVIDENCE_PROVENANCE_DISCLOSURE.md`  
**Task**: `P-20.05 — Build live/recorded/fixture/simulated disclosure`  
**Governing Authority**: `AGENTS.md` § 9 (Live-First Law), § 10 (Evidence Provenance), § 11 (AWS Truth Boundary); `plans/STILLDONE_MASTER_EXECUTION_PLAN.md` § P-20.05  
**Governing Principle**: Provenance is separate from result. Recorded-live is never promoted to current-live. Fixture is never promoted to live. Simulation is never concealed.  

---

## 1. System-Wide Provenance Taxonomy

StillDone categorizes every execution, test result, exhibit element, and architectural milestone into one of exactly **six canonical execution provenance values** (`AGENTS.md` § 10):

1. **`FIXTURE`**: Deterministic, offline execution using local simulated providers or pre-seeded test fixtures with zero network calls and zero credentials.
2. **`LOCAL_EXECUTION`**: Deterministic execution of pure domain, verification, cryptographic, or ledger algorithms on the local workstation / CI runner.
3. **`LIVE_AWS`**: Real, unsimulated execution against Amazon Bedrock Nova Micro or Bedrock AgentCore Runtime.
4. **`LIVE_GOOGLE`**: Real, unsimulated execution against Google Calendar v3 or Google Tasks v1 APIs under operator OAuth authorization.
5. **`LIVE_EXTERNAL`**: Real HTTP API call to external public endpoints (e.g., Open-Meteo weather API).
6. **`RECORDED_LIVE`**: Authentic, dated historical execution records with exact timestamps, raw provider responses, and hashes committed in `docs/`. Never promoted to fresh current-live calls.

### Distinct Presentation, Execution, and Observation Categories:
- **Client / Surface Disclosure**: `SIMULATED ALEXA+ EXPERIENCE` is a user-facing interface presentation disclosure, not an execution provenance enum.
- **Execution Statuses**: `NOT_RUN`, `BLOCKED`, `BLOCKED_LIVE`, and `BLOCKED_EXTERNAL` are operational execution states, not provenance values.
- **Evidence Observation Classification**: `OPERATOR_OBSERVED / SCREENSHOT` is a human observation classification for external platform deployments, not a runtime provenance enum.

```mermaid
flowchart TD
    subgraph Execution Provenance (Canonical Enums)
        F["FIXTURE (Deterministic Offline)"]
        LE["LOCAL_EXECUTION (Pure Algorithms / CI)"]
        LA["LIVE_AWS (Real Bedrock / AgentCore)"]
        LG["LIVE_GOOGLE (Real Calendar / Tasks)"]
        LX["LIVE_EXTERNAL (Real Weather API)"]
        RL["RECORDED_LIVE (Historical Immutable Records)"]
    end
    subgraph Distinct Disclosures & Statuses
        S["SIMULATED ALEXA+ EXPERIENCE (Client Surface Disclosure)"]
        NR["NOT_RUN / BLOCKED (Operational Safety Statuses)"]
        OO["OPERATOR_OBSERVED (External Platform Observation)"]
    end
```

---

## 2. Comprehensive Provenance Breakdown by Component

### 2.1 Amazon Web Services (Bedrock & AgentCore)

| Sub-Component | Provenance Tier | Operational Reality | Evidence Link / Log |
|---|---|---|---|
| **Bedrock Converse API (`amazon.nova-micro-v1:0`)** | `RECORDED_LIVE` | Executed live against real AWS Bedrock in `us-east-1` under operator credentials (`ASIA...`). Proved model reasoning and candidate plan output. Observed single live inference duration: 3.463s (in P-07.06 end-to-end execution, not a multi-run cold-start benchmark). | `docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md` `docs/P01_02_LIVE_BEDROCK_EVIDENCE.md` |
| **Strands Agents SDK (1.57.2)** | `RECORDED_LIVE` & `LOCAL_EXECUTION` | Executed live with Bedrock Nova Micro. Evaluated in dual-runtime isolated environment with 1,155 automated tests. | `tests/planning/test_strands_agent.py` `docs/P07_06_LIVE_BEDROCK_STRANDS_EVIDENCE.md` |
| **Bedrock AgentCore Serverless MicroVM** | `RECORDED_LIVE` | Deployed live to AWS Bedrock AgentCore Runtime (port 8000, CodeZip / container). Executed remote MCP `initialize`, `tools/list`, `mission_start` (bounded local `DRAFT` record creation), and `mission_status` (recorded state read); those two MCP tools do not themselves invoke the complete Strands → real-provider actions → independent verification → `READY` → `DRIFTED` pipeline. Torn down cleanly with `agentcore remove all -y`. | `docs/P05_06_LIVE_REMOTE_MCP_EVIDENCE.md` `docs/P01_04_LIVE_AGENTCORE_EVIDENCE.md` |
| **Current Live Remote AWS Endpoints** | `NOT_RUN` / `BLOCKED_LIVE` | Deliberately **not running** as an unmetered public cloud endpoint. Maintaining an active remote microVM would consume finite promotional credits and violate the Zero Personal Spend Law ($0.00). | `docs/P19_03_REMOTE_MCP_DEPLOYMENT_PREFLIGHT.md` |

---

### 2.2 Google Workspace Integrations (Calendar & Tasks)

| Sub-Component | Provenance Tier | Operational Reality | Evidence Link / Log |
|---|---|---|---|
| **Google Calendar API v3 Event Read** | `RECORDED_LIVE` | Real OAuth 2.0 read executed against dedicated disposable StillDone demo calendar. Verified pre-state departure at 07:45 AM. | `docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md` `docs/P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md` |
| **Google Calendar API v3 Event Mutation & Read-Back (P-06.08)** | `RECORDED_LIVE` (`LIVE_GOOGLE`) | P-06.08 historically evaluated a cryptographically bound `ApprovalGrant` (`AUTHORIZED_BY_BOUND_APPROVAL`) before executing a real OAuth 2.0 conditional `events.update` (07:45 AM → 07:30 AM) and separate independent `events.get` read-back on the dedicated StillDone demo calendar, achieving step-level `VERIFIED`. Does not establish P-11.06's later durable `ApprovalLedger` single-use consumption and replay-rejection lifecycle in that live run. | `docs/P06_08_LIVE_CALENDAR_VERIFIED_EVIDENCE.md` |
| **Cryptographic Approval & Replay-Prevention Lifecycle (P-11.05 / P-11.06)** | `LOCAL_EXECUTION` & `FIXTURE` | Durable single-use `ApprovalGrant` consumption (`ApprovalLedger`), replay rejection, and unapproved pause validated deterministically against `FakeGoogleCalendarTransport`. Real Google mutation in P-11.06 was `NOT_RUN / BLOCKED`; the complete P-11 consumption/replay lifecycle integrated with a real Google mutation has NOT been demonstrated live. | `docs/P11_05_CALENDAR_UPDATE_NOT_RUN_BEFORE_APPROVAL_EVIDENCE.md` `docs/P11_06_APPROVED_CALENDAR_UPDATE_EXECUTION_VERIFICATION_EVIDENCE.md` |
| **Google Tasks API v1 Task Creation** | `RECORDED_LIVE` | Real OAuth 2.0 task creation on dedicated StillDone demo task list. Created "Pack children backpacks". Read back and verified (`status=needsAction`). | `docs/P06_07_LIVE_TASKS_VERIFIED_EVIDENCE.md` |
| **Current Live Google Mutations** | `NOT_RUN` / `BLOCKED_LIVE` | Live Google mutations are only executed during supervised, operator-authorized recording sessions. The public exhibit and CI test suites execute 0 live Google writes. | `scripts/demo_resources.py` `docs/KILLER_DEMO_CONTRACT.md` |

---

### 2.3 External Weather Provider (Open-Meteo)

| Sub-Component | Provenance Tier | Operational Reality | Evidence Link / Log |
|---|---|---|---|
| **Open-Meteo Forecast API** | `RECORDED_LIVE` (`LIVE_EXTERNAL`) | Real HTTP GET calls executed against public non-commercial Open-Meteo endpoint (Berlin coordinates). Returned genuine temperature, precipitation, and attribution. | `docs/P06_06_LIVE_WEATHER_FINAL_CLOSURE_EVIDENCE.md` `docs/P01_06_LIVE_OPEN_METEO_EVIDENCE.md` |
| **Offline Weather Simulation** | `FIXTURE` | Pre-captured deterministic weather payload used during offline CI validation and static exhibit generation to guarantee hermetic execution with 0 network calls. | `src/stilldone/adapters/weather.py` `tests/test_weather_adapter.py` |

---

### 2.4 Killer Mission 7-Step Demonstration

| Sub-Component | Provenance Tier | Operational Reality | Evidence Link / Log |
|---|---|---|---|
| **Step 1: Pre-State Seeding** | `FIXTURE` | Pre-state seeding executed in deterministic fixture environment (0 live writes). Confirms initial calendar event at 07:45 AM. | `src/stilldone/killer_mission.py` `tests/test_phase_p13_killer_mission.py` |
| **Step 2: Intent Planning & Weather** | `FIXTURE` | Proposal compiled from canonical specification (0 model authority). Weather evaluated from fixture payload (0 writes). | `src/stilldone/killer_mission.py` `tests/test_phase_p13_killer_mission.py` |
| **Step 3: Prep Task Creation & Read-back** | `FIXTURE` | Task created in memory; verified via independent read-back verifier (`1` write performed). | `src/stilldone/killer_mission.py` `tests/test_phase_p13_killer_mission.py` |
| **Step 4: Approval Boundary Pause** | `FIXTURE` | Execution halts at calendar update gate (`0` writes performed). Generates fixture-derived explanatory digest. | `src/stilldone/killer_mission.py` `tests/test_phase_p13_killer_mission.py` |
| **Step 5: Approved Calendar Shift & Read-back** | `FIXTURE` | Single-use grant consumed; calendar shifted to 07:30 AM; verified via independent read-back (`1` write performed). | `src/stilldone/killer_mission.py` `tests/test_phase_p13_killer_mission.py` |
| **Step 6: READY Receipt Issuance** | `FIXTURE` | All predicates verified; promoted to `READY`; issued canonical immutable SHA-256 receipt hash. | `src/stilldone/killer_mission.py` `tests/test_phase_p13_killer_mission.py` |
| **Step 7: Drift Reconciliation** | `FIXTURE` | Calendar departure externally altered to 08:00 AM; independent read-back detects mismatch; mission reconciled to `DRIFTED`. | `src/stilldone/killer_mission.py` `tests/test_phase_p13_killer_mission.py` |

> [!IMPORTANT]
> **Complete 7-Step Exhibit Status**: The 7-step sequence displayed on the public judge exhibit (`artifacts/judge_exhibit/index.html`) is **FIXTURE playback**. It proves the complete mathematical state transitions, independent read-back evaluation, and drift reconciliation of the StillDone engine offline. It is **not** claimed as an unmonitored fresh live Google/AWS run for web visitors. Recorded AWS and Google live executions are historical records preserved separately in `docs/` (`RECORDED_LIVE`).

---

### 2.5 User-Facing Interfaces & Client Surfaces

| Surface | Classification | Truth & Disclosure |
|---|---|---|
| **Alexa+ Client Interface** | **`SIMULATED ALEXA+ EXPERIENCE`** | Direct internal Amazon Alexa+ partner client access was not established. StillDone provides a simulated Alexa+ multimodal presentation surface: `src/stilldone/judge_ux/builder.py` creates voice-ready English text and estimated speaking duration ($< 8$s), and `src/stilldone/judge_ux/html_renderer.py` renders the visual cards and text. The public static HTML contains no audio player, speech synthesis implementation, live Alexa+/Echo Show device connection, or visitor backend execution. Prominently labeled with `SIMULATED ALEXA+ EXPERIENCE` badge. |
| **Public Judge Exhibit** | **`STATIC READ-ONLY EXHIBIT`** | 100% self-contained static HTML deployed to Cloudflare Pages (`https://stilldone-judge-exhibit.pages.dev`). Executes **zero backend code for visitors**. No external JavaScript, no unmetered API calls, $0.00 spend. |
| **Automated CLI Reproduction** | **`LOCAL_EXECUTION (HERMETIC)`** | Automated clean-checkout reproduction via `python scripts/reproduce.py` executed from a pristine temporary archive (`git archive`) with environment variables stripped. Executes 507 smoke tests offline with 0 cloud calls. |

---

## 3. Disclosure Verification Checklist

- [x] **No False Live Claims**: Historical live calls are explicitly labeled `RECORDED_LIVE` and dated; never passed off as current-live.
- [x] **Simulated Alexa+ Labeling**: `SIMULATED ALEXA+ EXPERIENCE` is prominently displayed in HTML headers, view models, and documentation.
- [x] **Static Exhibit Disclosure**: Clearly explains that the web page is a static snapshot with 0 active backend execution for visitors.
- [x] **Truthful Voice Surface & No Audio Synthesis**: VoiceSummary produces voice-ready English text and calculated duration; no speech synthesis or live Alexa+/Echo Show hardware execution is claimed or implemented.
- [x] **Zero Personal Spend Maintained**: $0.00 personal spend verified across all active accounts and runs.
- [x] **Clean Donor Isolation**: All donor repositories remain strictly `CONCEPT_ONLY`; 0 lines imported.

---

*Verified evidence provenance disclosure committed under P-20.05.*
