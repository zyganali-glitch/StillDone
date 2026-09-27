# HANDOFF — StillDone

## Canonical repository

Intended repo: `zyganali-glitch/StillDone`
Branch: `main`

Current repository state: **BOOTSTRAPPED**

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

`P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt`

Status:
`BLOCKED — AWS Bedrock Converse returned ValidationException: Operation not allowed`

## Last independently VERIFIED baseline SHA

`e3d5aa79d8569ebe7e20e48300060b15ba30c187`

## Next safe action

Independent QA evaluation and authorization required before any future bounded execution cycle of the SAME P-01.02 task (`P-01.02 — Execute first real Bedrock model inference with a sanitized minimal prompt`).

Operator/QA investigation is required on why AWS Bedrock returned `ValidationException: Operation not allowed` on direct invocation of `amazon.nova-micro-v1:0` (e.g. verifying Bedrock Console -> Model Access for Amazon Nova models or checking inference profile requirements). A later third execution cycle of P-01.02 requires fresh independent QA authorization. Within that future execution cycle: exactly one inference attempt, no retry/fallback, and the same zero-spend boundary.

Task P-01.03 (`Prove minimal real Strands agent execution against the selected Bedrock model`) is strictly locked and MUST NOT start before P-01.02 achieves real live execution and independent QA PASS.
