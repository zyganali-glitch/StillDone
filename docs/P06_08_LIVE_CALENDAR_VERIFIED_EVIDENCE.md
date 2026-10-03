# P-06.08 Live Calendar Update → Read-Back → VERIFIED Evidence

## 1. Summary

- **Task**: `P-06.08 — Prove first live Calendar update → read-back → VERIFIED slice`
- **Execution UTC Timestamp**: `2026-10-03T13:40:01.836511+00:00`
- **Classification**: `RECORDED_LIVE`
- **Original Live Provenance**: `LIVE_GOOGLE`
- **System**: `google_calendar`
- **Dedicated Target Calendar**: Dedicated disposable calendar titled `StillDone Demo`
- **Sanitized Calendar ID**: `[REDACTED_CALENDAR_ID]`
- **Target Event Title**: `Leave for school`
- **Sanitized Event ID**: `[REDACTED_EVENT_ID]`
- **Pre-Update Start Time**: `2026-10-04T07:45:00+01:00` (pre-update 07:45 demo state)
- **Desired Start Time**: `2026-10-04T07:30:00+01:00` (rescheduled 07:30 demo state)
- **Observed Post-Update Start Time**: `2026-10-04T07:30:00+01:00`
- **Personal Spend Delta**: `$0.00` (Google Calendar API standard courtesy quota; 0 paid resources, 0 billing enablement)
- **Call Bounding**: Exactly 5 live API calls executed (1 calendar discovery, 1 preflight event discovery, 1 pre-write exact read, 1 conditional update mutation, 1 independent read-back)
- **Retries / Fallback Count**: Exactly 0 retries, 0 fallbacks, 0 secondary writes
- **Final Deterministic Step State**: `VERIFIED`
- **Mission Lifecycle State**: Mission `READY` was **STRICTLY NOT PRODUCED** (step-level evidence only; lifecycle/reconciliation/drift remains later phases)

---

## 2. Official Google Calendar Documentation & Quota Reconfirmation

Current facts verified against official Google Calendar Developer documentation on **2026-10-03**:

| Dimension | Specification / URL | Observed Status |
|---|---|---|
| **OAuth Scopes** | `https://www.googleapis.com/auth/calendar.calendarlist.readonly`<br>`https://www.googleapis.com/auth/calendar.events` | Narrowest least-privilege scope combination permitting calendar listing, event retrieval, and conditional event update. Broad `https://www.googleapis.com/auth/calendar` and Tasks/Gmail/Drive/Profile scopes were strictly avoided. |
| **calendarList.list** | `GET https://www.googleapis.com/calendar/v3/users/me/calendarList` | Used for single bounded discovery of dedicated `StillDone Demo` calendar. |
| **events.list** | `GET https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events` | Used for single bounded preflight discovery and safety check of existing synthetic demo event inside dedicated calendar only. |
| **events.get** | `GET https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events/{eventId}` | Used for pre-write ETag retrieval (by `GoogleCalendarUpdateAdapter`) and distinct independent read-back (by `GoogleCalendarReadbackVerifier`). |
| **events.update** | `PUT https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events/{eventId}` | Used for single conditional mutation with `If-Match: <etag>` and `sendUpdates="none"`. |
| **Quota & Billing** | Free tier under daily billing threshold (1,000,000 req/day; per-minute project/user rate limits) | Free tier; zero paid quota increases; zero billing attachments; $0.00 personal spend. |

---

## 3. Ephemeral Runtime & Package Environment

Executed strictly in an isolated ephemeral scratch environment (`google_p06_08_scratch`) outside the repository. No packages added to canonical `pyproject.toml` or `uv.lock`.

- **Python Version**: `3.13.14` (Windows AMD64)
- **Package Execution**: `uv run --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 python -u run_p06_08_live_proof.py`
- **Resolved Package Versions**:
  - `google-api-python-client`: `2.201.0`
  - `google-auth-oauthlib`: `1.5.0`
  - `google-auth-httplib2`: `0.4.4`

---

## 4. Live Call Ledger & Execution Chain

| Step | Operation | HTTP Method | Endpoint | Latency (ms) | Observed Status |
|---|---|---|---|---|---|
| 1 | `calendarList.list` (discovery) | `GET` | `/calendar/v3/users/me/calendarList` | `405.63` | Exactly 1 match for `StillDone Demo`; ID redacted as `[REDACTED_CALENDAR_ID]`; primary/default rejected. |
| 2 | `events.list` (preflight event check) | `GET` | `/calendar/v3/calendars/[REDACTED_CALENDAR_ID]/events` | `214.60` | Exactly 1 match for `Leave for school`; start confirmed at `07:45`; safety checks passed (0 attendees, no conferencing, no recurrence). |
| 3 | `events.get` (pre-write read) | `GET` | `/calendar/v3/calendars/[REDACTED_CALENDAR_ID]/events/[REDACTED_EVENT_ID]` | `186.28` | Pre-write exact read by `GoogleCalendarUpdateAdapter`; verified current start `07:45`, retrieved provider ETag. |
| 4 | `events.update` (single conditional mutation) | `PUT` | `/calendar/v3/calendars/[REDACTED_CALENDAR_ID]/events/[REDACTED_EVENT_ID]` | `457.53` | Conditional update with `If-Match: <etag>` and `sendUpdates="none"`; `CalendarUpdateStatus.UPDATED`, `writes_performed=1`. |
| 5 | `events.get` (independent read-back) | `GET` | `/calendar/v3/calendars/[REDACTED_CALENDAR_ID]/events/[REDACTED_EVENT_ID]` | `204.59` | Separate fresh read by `GoogleCalendarReadbackVerifier`; returned `CalendarReadbackStatus.MATCH`, `mismatches=[]`. |

- **Total Outbound Live Calls**: `5`
- **Total Round-Trip Latency**: `1468.63 ms`
- **Mutations Performed**: Exactly `1` (`events.update`)
- **Retries Performed**: `0`
- **Provider Fallbacks**: `0`

---

## 5. Verified StillDone Contracts & Invariants

### 5.1 Preflight Event Discovery & Synthetic Safety Gate
Preflight discovery was restricted strictly to the dedicated demo calendar:
- `events.list` returned exactly 1 non-cancelled candidate with summary `"Leave for school"`.
- Safety verification:
  - `attendees`: 0 (no external guests; zero risk of sending calendar invites/updates).
  - `conferenceData`: None (no video meeting attachment).
  - `recurringEventId`: None (non-recurring event; no series ambiguity).
- Precondition verification:
  - Event was confirmed to be timed (`dateTime` present).
  - Pre-update start time was verified to be `07:45` (`2026-10-04T07:45:00+01:00`).

### 5.2 Authority Classification & Exact Approval Binding
- Action type `ActionType.CALENDAR_UPDATE` was evaluated under `src/stilldone/authority_policy.py`.
- Authority class: `AuthorityClass.REVERSIBLE_APPROVAL_REQUIRED`.
- Bounded `ApprovalGrant` was constructed and cryptographically bound to the canonical action:
  - `action`: target system `google_calendar`, resource kind `CALENDAR_EVENT`, resource ID `[REDACTED_EVENT_ID]`, parent container `[REDACTED_CALENDAR_ID]`, parameters `{"start_time": "2026-10-04T07:30:00+01:00", "all_day": False}`.
  - Validity window: bounded to 15 minutes (`issued_at <= at < expires_at`).
  - `evaluate_authority(validated_action, approval=grant, at=eval_now)` evaluated to `AUTHORIZED_BY_BOUND_APPROVAL`.

### 5.3 Conditional Mutation via Reviewed Adapter
The mutation was executed via `GoogleCalendarUpdateAdapter.update_event`:
- Read-before-write retrieved current provider ETag.
- Verified event was not already at `07:30` (non-noop write required).
- Conditional `PUT` was issued with `req.headers["If-Match"] = current_etag` (strictly zero wildcard `*`).
- Side-effect suppression: `sendUpdates="none"`.
- Event duration was strictly preserved (shifted from 07:45-08:15 to 07:30-08:00).
- Outcome: `CalendarUpdateStatus.UPDATED` with `writes_performed = 1`.

### 5.4 UPDATED != VERIFIED Proof
Immediately following successful `events.update`:
- Step evidence state was recorded as `StepEvidenceState.EXECUTED_UNVERIFIED`.
- Explicit proof verified:
  ```python
  assert intermediate_state != StepEvidenceState.VERIFIED
  ```
- Mutation response alone was strictly prohibited from producing `VERIFIED` or promoting mission state.

### 5.5 Distinct Independent Read-Back Verification
Verification was executed via a separate `events.get` call using `GoogleCalendarReadbackVerifier`:
- The update response payload was **NOT reused** as verification evidence.
- Distinct fresh external observation obtained through `GoogleCalendarReadAdapter`.
- Expected state:
  - `start_time`: `"2026-10-04T07:30:00+01:00"`
  - `all_day`: `False`
- Observed state:
  - `start_time`: `"2026-10-04T07:30:00+01:00"`
  - `all_day`: `False`
- Temporal ordering verified:
  - `readback_res.verified_at >= readback_res.observation.observed_at`
  - `readback_res.observation.observed_at >= update_res.updated_at`
- Outcome: `CalendarReadbackStatus.MATCH` with zero mismatches (`mismatches = ()`).

### 5.6 Deterministic Step Predicate Evaluation
The final step state `StepEvidenceState.VERIFIED` was assigned strictly through the conjunction of all required conditions:
```python
update_result.status == CalendarUpdateStatus.UPDATED
and update_result.writes_performed == 1
and readback_result.status == CalendarReadbackStatus.MATCH
and len(readback_result.mismatches) == 0
```
All conditions evaluated to `True`.
Final step state: `StepEvidenceState.VERIFIED`.
Mission lifecycle state: Mission `READY` was **STRICTLY NOT PRODUCED**.

---

## 6. Security, Privacy & Resource Cleanup

| Item | Requirement | Observed Status |
|---|---|---|
| **OAuth Client Credentials** | Kept outside repo (`C:\Users\MEHMET\Downloads`) | **PRESERVED_OUTSIDE_REPO** |
| **OAuth Token Storage** | Ephemeral only; deleted immediately after proof completion | **DELETED / ZERO_COMMITTED_TOKENS** |
| **Ephemeral Auth URL** | Written to `auth_url.txt` for operator consent; deleted immediately after token exchange | **DELETED** |
| **External Resource IDs** | Redacted in durable evidence (`[REDACTED_CALENDAR_ID]`, `[REDACTED_EVENT_ID]`) | **REDACTED** |
| **Event Content** | Synthetic non-personal demo text only (`Leave for school`) | **SYNTHETIC_DEMO_DATA** |
| **Approval Secrets** | Cryptographic digest and approval token values unexposed | **PROTECTED** |
| **Personal Spend Delta** | Target `$0.00` | **$0.00 USD** |

---

## 7. Evidence Provenance Transition

- **At Moment of External Observation**: `LIVE_GOOGLE`
- **Committed Document Classification**: `RECORDED_LIVE` (lineage traces to genuine Google Calendar API calls against live account)
- **Rule Preserved**: `LIVE_GOOGLE != VERIFIED`. Verified status was earned exclusively via independent read-back predicate match.

---

## 8. Explicit NOT_RUN Ledger

The following activities were strictly **NOT_RUN** during P-06.08:
1. Event creation mutation: **NOT_RUN** (P-06.08 strictly authorized update only; synthetic event was pre-existing).
2. Broad `calendar` write scope: **NOT_RUN** (restricted to least-privilege `calendar.events` and `calendar.calendarlist.readonly`).
3. Primary / Default personal calendar access: **NOT_RUN** (strictly targeted dedicated `StillDone Demo` calendar).
4. Unconditional overwrite (`If-Match: *`): **NOT_RUN** (exact ETag precondition enforced).
5. External notifications / attendee communications: **NOT_RUN** (`sendUpdates="none"` enforced).
6. Google SDK additions to `pyproject.toml` or `uv.lock`: **NOT_RUN**.
7. Model-directed planning or generic P-09 predicate engine: **NOT_RUN**.
8. Mission `READY` state promotion: **NOT_RUN** (lifecycle remains unpromoted).
9. Phase P-07 tasks: **NOT_RUN / PENDING / NOT AUTHORIZED**.
