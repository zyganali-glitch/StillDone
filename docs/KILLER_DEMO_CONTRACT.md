# Killer Demo Contract

## Canonical mission

> **“Get my family ready for tomorrow morning. We need to leave by 7:30.”**

## Demo resources

Use dedicated disposable resources:
- Google Calendar: `StillDone Demo`
- Google Task List: `StillDone Demo`

Do not use unrelated personal calendar/task content in video.

## Initial state

Preconditions:
- tomorrow contains `Leave for school` at `07:45`;
- required weather-preparation task is absent;
- real weather can be fetched for the configured demo location.

The demo location must be non-sensitive and can be a public city selection.

## Runtime

1. Simulated Alexa+ surface captures the mission.
2. Remote MCP server receives it.
3. Real AWS model/Strands path proposes a typed mission plan.
4. Deterministic compiler validates supported actions and desired predicates.
5. Calendar read confirms 07:45.
6. Open-Meteo provides current tomorrow forecast.
7. Tasks read confirms preparation task absent.
8. Runtime creates one weather-appropriate task.
9. Separate Tasks read-back verifies exact resource exists.
10. Calendar update is classified `REVERSIBLE_APPROVAL_REQUIRED`.
11. User grants one approval.
12. Runtime updates event to 07:30.
13. Separate Calendar read-back verifies exact start time/resource.
14. Mission becomes `READY`.

## Drift moment

15. Operator opens real Google Calendar and changes the event away from 07:30.
16. User asks: **“Are we still ready?”**
17. StillDone performs fresh read-back.
18. Calendar predicate fails.
19. Mission becomes `DRIFTED`.
20. UI says exactly what changed.

## Weather action

The model may choose a weather-preparation task only from a bounded supported action vocabulary and structured weather facts.

The runtime must not let free-form model text silently become arbitrary external actions.

Examples:
- umbrella/rain gear;
- warmer layer;
- water/sun protection.

Exact behavior is frozen and tested later.

## Required live proof

The final competition demo must visibly prove:
- AWS model invocation completed;
- MCP path is real;
- Calendar mutation is real;
- Tasks mutation is real;
- read-backs are separate calls;
- duplicate/retry behavior is safe;
- approval boundary is real;
- external manual drift is real;
- reconciliation downgrades state.

## Timing target

Target final video:
`2:30–2:50`

Suggested cut:
- 0:00–0:15 problem/thesis
- 0:15–0:45 mission + live reads
- 0:45–1:15 plan + safe mutation + verification
- 1:15–1:40 approval + calendar mutation + verification
- 1:40–1:55 READY receipt
- 1:55–2:15 external calendar drift
- 2:15–2:35 “Are we still ready?” → DRIFTED
- 2:35–2:50 architecture/closing line

## Failure rule

If a live call fails during recording:
show the failure truth or re-record after fixing it.

Never replace a failed live step with a hidden fixture.
