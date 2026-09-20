# Competition Strategy

## Positioning

Do NOT pitch StillDone as:
- “an AI family assistant”;
- “an Alexa to-do app”;
- “an MCP wrapper”;
- “an AI receipt generator”.

Those categories are crowded and easy to dismiss as obvious.

Pitch:

> **AI assistants can execute actions. StillDone keeps the outcome true.**

Secondary line:

> **Done, and still true.**

## Why the idea is stronger than action automation

Typical agent:
`tool returned success → assistant says done`

StillDone:
`intent → desired state → authority → execute → read-back → verify → later reconcile`

The final competition-defining moment:
a previously `READY` mission becomes `DRIFTED` after a real external change.

That visibly proves deterministic reality outranks model memory.

## Judging map

### Tech Implementation

Target proof:
- real MCP Streamable HTTP server;
- real AWS reasoning/agent/runtime;
- real Google Calendar write/read-back;
- real Google Tasks write/read-back;
- real Open-Meteo;
- typed mission contract;
- deterministic predicate evaluator;
- idempotency/retry;
- approval binding;
- cross-session persisted mission;
- drift reconciliation;
- clean tests and fresh reproduction.

### Design

Target experience:
- user states one outcome;
- system asks at most one meaningful approval;
- voice summary is short;
- visual receipt is compact;
- uncertainty is understandable;
- no technical evidence dump in the primary UX;
- detail remains inspectable.

### Potential Impact

Specific problem:
AI delegation becomes unreliable when work spans multiple systems and time.

Initial wedge:
household morning preparation.

Expansion:
- travel preparation;
- school logistics;
- personal admin;
- event preparation;
- client-visit readiness;
- recurring operational checklists.

The platform value is reliable delegation, not family organization itself.

### Quality of Idea

Differentiator:
**renewable completion**.

Receipt:
what was true then.

Reconciliation:
what is true now.

Creative Amazon fit:
- cross-service agentic workflow;
- durable state;
- real execution;
- human authority boundary;
- re-evaluation across sessions.

## Scope discipline

Do not add:
- a giant family dashboard;
- chat history features;
- generic notes;
- broad home automation;
- financial actions;
- health actions;
- shopping checkout;
- browser automation;
- dozens of service integrations.

Two real mutable systems + one real external observation are enough to prove the thesis.

## Canonical demo narrative

1. User states mission.
2. System reads current reality.
3. Real model proposes bounded plan.
4. Runtime compiles exact desired state.
5. Safe action executes.
6. One meaningful action pauses for approval.
7. Approval is granted.
8. Real state is mutated.
9. Independent read-back verifies.
10. Mission shows `READY`.
11. Operator changes Google Calendar directly.
12. User asks `Are we still ready?`
13. StillDone says `No` and identifies drift.

Closing line:

> **An assistant shouldn't get credit because it said “done.” Reality gets the final vote.**

## Submission media priority

Video first 20 seconds must show:
- user mission;
- one-line product thesis;
- live status movement.

Do not spend the opening on architecture diagrams.

Architecture appears only after the product value is obvious.

## Competitive red line

No screenshot-only pseudo-live story.

If a service is unavailable:
- show `NOT_RUN`;
- remove the claim; or
- change architecture.

Never fill a missing live proof with a mock and call it integrated.
