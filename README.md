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

**PRE-BOOTSTRAP / NO PRODUCT CODE**

This starter pack intentionally contains governance, competition truth, architecture contracts, and the Master Plan only.

The first exact task is:

`P-00.01 — Bootstrap canonical StillDone repository from the frozen starter pack`

See:
- `plans/STILLDONE_MASTER_EXECUTION_PLAN.md`
- `docs/HANDOFF.md`
- `AGENTS.md`
