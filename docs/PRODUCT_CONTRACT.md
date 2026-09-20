# StillDone Product Contract

## 1. Product category

StillDone is **not**:
- a generic chatbot;
- a to-do list;
- a family organizer;
- a model-generated receipt dashboard;
- an AI that merely calls tools.

StillDone is a **desired-state mission runtime**.

The user delegates an outcome. StillDone converts it into machine-checkable predicates, performs bounded actions, independently observes the real systems of record, and maintains an honest answer to:

> **Is the outcome actually true right now?**

## 2. Product thesis

> **An AI assistant should not get credit for finishing an outcome unless the resulting state is independently observed—and if reality drifts, completion must be revoked.**

Supporting principle:

> **Completion is an observable, renewable state—not model prose.**

## 3. User value

The problem is not “AI cannot call APIs.”

The problem is:
- a multi-step mission crosses several services;
- some actions may succeed and others fail;
- a successful tool response may not equal the desired state;
- retries can duplicate effects;
- permissions may block only part of the mission;
- the world can change after completion;
- conversational memory can preserve an outdated claim.

StillDone compresses that uncertainty into a small truthful state.

## 4. Canonical mission

User:

> “Get my family ready for tomorrow morning. We need to leave by 7:30.”

Initial demo state:
- dedicated demo calendar contains a `Leave for school` event at 07:45;
- dedicated demo task list has no required weather-preparation task;
- tomorrow's real forecast is fetched live.

StillDone should:
1. inspect calendar;
2. inspect task list;
3. inspect weather;
4. use the real model path to propose a bounded typed plan;
5. compile it into deterministic desired-state predicates;
6. auto-create the safe reversible preparation task;
7. require one bounded approval to modify the existing calendar commitment;
8. update the event after approval;
9. read both systems back independently;
10. return `READY` only after predicates match;
11. later re-read them when asked whether the mission is still ready.

Demo drift:
- operator changes the event externally in Google Calendar;
- StillDone did not cause the drift;
- user asks: `Are we still ready?`;
- StillDone read-backs current state;
- mission becomes `DRIFTED`;
- the response names the mismatching predicate.

## 5. Desired-state examples

Illustrative only; exact schema is defined in P-02:

```yaml
mission:
  target_date: 2026-10-01
  desired_state:
    - predicate: calendar_event.start_time == "07:30"
      required: true
      freshness: current
    - predicate: weather_preparation_task.exists == true
      required: true
      freshness: current
    - predicate: weather_observation.age_minutes <= 60
      required: true
```

## 6. Model boundary

Model owns:
- language understanding;
- proposed decomposition;
- bounded semantic interpretation;
- user-facing explanation.

Deterministic runtime owns:
- IDs;
- hashes;
- authority state;
- execution results;
- timestamps;
- read-back results;
- predicate evaluation;
- verification;
- mission status.

## 7. Mission lifecycle

Initial target vocabulary:

- `DRAFT`
- `PLANNED`
- `EXECUTING`
- `NEEDS_APPROVAL`
- `VERIFYING`
- `READY`
- `PARTIAL`
- `FAILED`
- `DRIFTED`
- `CANCELLED`

Exact schema must be frozen in P-02.

## 8. Step evidence lifecycle

Initial target vocabulary:

- `NOT_RUN`
- `EXECUTED_UNVERIFIED`
- `VERIFIED`
- `CONTRADICTED`
- `BLOCKED`
- `FAILED`
- `STALE`

A step can never move directly from `NOT_RUN` to `VERIFIED` solely because the model claims it should.

## 9. Competition-defining innovation

The key novelty is not the receipt.

It is **renewable completion**:

> Receipt proves what was observed then. Reconciliation proves what is true now.

## 10. Scope exclusions for the hackathon

Not required for the core:
- banking or payments;
- health/medical decisions;
- safety-critical emergency response;
- autonomous purchases;
- unrestricted email sending;
- general browser automation;
- arbitrary shell execution;
- arbitrary third-party MCP discovery;
- full household knowledge graph;
- always-on background surveillance.

These can create risk without improving the killer proof.
