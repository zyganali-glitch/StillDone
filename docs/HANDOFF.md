# HANDOFF — StillDone

## Canonical repository

Intended repo: `zyganali-glitch/StillDone`
Branch: `main`

Current repository state: **P-01 LIVE FEASIBILITY IN PROGRESS — P-01.01 PASS; P-01.02 PASS; P-01.03 PASS; P-01.04 PASS; P-01.05 DONE (AWAITING INDEPENDENT QA PASS)**

Canonical remote truth begins with the P-00.01 bootstrap commit.

## Product

Name: **StillDone**

Tagline:
`Done, and still true.`

Thesis:

> An AI assistant should not get credit for finishing an outcome unless the resulting state is independently observed—and if reality drifts, completion must be revoked.

Canonical user problem:
people increasingly delegate multi-step real-world work to AI, but a tool success response does not prove the user's intended outcome is actually true or remains true.

## Competition

Build, Ship, Shape: Amazon Developer Hackathon

Primary:
- Alexa+ Track

Secondary:
- AWS Builder Mini Challenge
- Open Source Mini Challenge

Rules snapshot date:
`2026-09-20`

## Canonical killer mission

> “Get my family ready for tomorrow morning. We need to leave by 7:30.”

Preferred first live service set:
- Google Calendar
- Google Tasks
- Open-Meteo

Preferred AWS target:
- real Bedrock reasoning path;
- real Strands agent path;
- real AgentCore/runtime path if live feasibility and zero-cost constraints are proven;
- final AWS service map remains UNFROZEN until P-01 closes.

## Frozen constraints

- Zero personal spend target: `$0.00`.
- No paid SaaS dependency required for the core judge path.
- Real MCP server over Streamable HTTP for the strongest Alexa+ path.
- Direct Alexa+ partner access is optional and must not block qualification.
- Simulated Alexa+ client surface must be visibly labeled if used.
- Real backend actions must not be presented as simulated.
- Execute response ≠ verification.
- Independent read-back required for mutable step verification.
- Mission `READY` may downgrade to `DRIFTED`.
- Partial failure, blocked, stale, failed, and NOT_RUN are first-class states.
- Model cannot override deterministic facts.
- Competition-defining donor logic is clean-room by default.
- No silent fallback from required live path to fixture.
- Dedicated demo calendar/task list preferred.
- Gmail is not part of the canonical critical path.
- No product code before the applicable Master Plan task.

## Current exact task

`P-01.05 — Prove Google OAuth and live read-only access to dedicated demo Calendar and Tasks resources`

Status:
`DONE — awaiting independent QA PASS`

## Last independently VERIFIED baseline SHA

`274187c19538e9e9f5f18fe3e2f372a8465cbc91`

## Next exact task after independent QA PASS

`P-01.06 — Execute first live Open-Meteo forecast call and record attribution/limit contract`

## Next safe action

Await independent QA PASS for P-01.05.

P-01.05 successfully proved live read-only Google Calendar and Tasks integration:
- Verified official Google Developer documentation on 2026-09-29 for Calendar quotas, Tasks limits, OAuth scopes, and Desktop flow.
- Enforced minimum scope contract: `calendar.calendarlist.readonly`, `calendar.events.readonly`, and `tasks.readonly` only.
- Executed Desktop app OAuth authorization flow via ephemeral local loopback server (`65389`) with explicit test user configuration.
- Located dedicated disposable secondary Calendar `StillDone Demo` (exactly 1 match; 0 events found; canonical `Leave for school` absent).
- Located dedicated disposable Task List `StillDone Demo` (exactly 1 match; 0 tasks found).
- Strictly zero write operations executed (`calendar_writes = 0`, `tasks_writes = 0`).
- Strictly zero API retries (`api_retries = 0`).
- Strictly zero billing or paid quota alterations ($0.00 personal spend).
- In-memory filtering enforced: zero unrelated personal calendar/task names stored, zero emails or tokens committed.
- Ephemeral tokens deleted from local scratch immediately (`ephemeral_token.json` deleted; remote OAuth grant `NOT_REVOKED`).
- Durable evidence recorded in `docs/P01_05_LIVE_GOOGLE_READ_EVIDENCE.md`.

Task P-01.06 (`Execute first live Open-Meteo forecast call and record attribution/limit contract`) remains PENDING / NOT_STARTED and MUST NOT start before P-01.05 receives independent QA PASS.


