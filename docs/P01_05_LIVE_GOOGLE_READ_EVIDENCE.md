# P-01.05 Live Google Calendar & Tasks Read-Only Feasibility Evidence

**Date & Time (UTC)**: `2026-09-29T06:09:46Z`  
**Local Timestamp**: `2026-09-29T09:09:46+03:00`  
**Governing Rules**: [AGENTS.md](../AGENTS.md) § 1–24; [COST_AND_ACCESS_POLICY.md](COST_AND_ACCESS_POLICY.md); [KILLER_DEMO_CONTRACT.md](KILLER_DEMO_CONTRACT.md); [SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md)  
**Task**: `P-01.05 — Prove Google OAuth and live read-only access to dedicated demo Calendar and Tasks resources`  
**Status**: `DONE — awaiting independent QA PASS`  

---

## 1. Official Google Documentation & Quota / Pricing Reality

Current facts verified against official Google Developer documentation on **2026-09-29**:

| Dimension | Official Authority / URL | Verified Observation |
|---|---|---|
| **Google Calendar API Quotas & Pricing** | `https://developers.google.com/workspace/calendar/api/guides/quota` | Rate limits enforced per-minute: 10,000 requests/min per project, 600 requests/min per user per project. Standard use operates at no additional cost under daily billing thresholds (1,000,000 requests/day). |
| **Google Tasks API Limits** | `https://developers.google.com/workspace/tasks/limits` | Courtesy quota: 50,000 queries per day at no cost. |
| **Calendar OAuth Scopes** | `https://developers.google.com/workspace/calendar/api/guides/auth` | Supports least-privilege read scopes: `calendar.calendarlist.readonly` (view calendar list entries) and `calendar.events.readonly` (view events). |
| **Tasks OAuth Scopes** | `https://developers.google.com/workspace/tasks/auth` | Supports least-privilege read scope: `tasks.readonly` (view tasks and task lists). |
| **Desktop App Authorization Flow** | `https://developers.google.com/workspace/calendar/api/quickstart/python` | Recommends `google_auth_oauthlib.flow.InstalledAppFlow` using local loopback server (`run_local_server`) for desktop/installed clients. |
| **Testing / Unverified App Behavior** | `https://support.google.com/cloud/answer/10311687` | In "Testing" publishing status, authorization is restricted strictly to explicitly configured test users (100 user cap); displays standard unverified-app screen bypassable via "Advanced" -> "Go to [App] (unsafe)". |

---

## 2. Zero-Spend & Quota Gate

- **Authorized API Requests**: Exactly 4 read-only data queries across Calendar and Tasks.
- **Paid Quota / Quota Increases Requested**: **0** (strictly prohibited).
- **Cloud Billing Attachment**: **0** (no billing account required or attached for standard courtesy usage).
- **Personal Spend Incurred**: **$0.00 USD**.
- **Financial & Quota Gate**: **`PASS`**.

---

## 3. Scope Minimization & Security Boundary

### 3.1 Minimum Scope Contract
Only the strictly necessary read-only OAuth scopes were authorized and requested:

```text
https://www.googleapis.com/auth/calendar.calendarlist.readonly
https://www.googleapis.com/auth/calendar.events.readonly
https://www.googleapis.com/auth/tasks.readonly
```

Forbidden scopes strictly avoided:
- `https://www.googleapis.com/auth/calendar` (full write: **NOT REQUESTED**)
- `https://www.googleapis.com/auth/calendar.events` (events write: **NOT REQUESTED**)
- `https://www.googleapis.com/auth/tasks` (tasks write: **NOT REQUESTED**)
- `gmail.*`, `drive.*`, `contacts.*`, `profile`, `email` (**NOT REQUESTED**)

### 3.2 Privacy & Sensitive Data Minimization
- **In-Memory Filtering**: Calendar lists and task lists retrieved from Google APIs were filtered in volatile memory. Unrelated personal calendars, unrelated task lists, attendee identities, and personal event summaries were neither logged nor persisted.
- **No Credentials Committed**: Zero OAuth client IDs, client secrets, access tokens, refresh tokens, or account email addresses are logged or committed in repository artifacts.
- **Sanitized Identifiers**: Real external resource IDs are redacted in durable documentation as `[REDACTED_CALENDAR_ID]` and `[REDACTED_TASKLIST_ID]`.

---

## 4. Ephemeral Runtime & Package Environment

Executed strictly in an isolated ephemeral scratch environment (`google_p01_05_scratch`) outside the repository. No packages added to canonical `pyproject.toml` or `uv.lock`.

- **Python Version**: `3.13.14` (Windows AMD64)
- **Resolved Package Versions**:
  - `google-api-python-client`: `2.200.0`
  - `google-auth-oauthlib`: `1.4.1`
  - `google-auth-httplib2`: `0.4.2`
- **Execution Mechanism**: `uv run --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 python run_google_proof.py`

---

## 5. Live Read Cycle & Observed Evidence

### 5.1 OAuth Authorization Flow
- **Client Type**: Desktop app (`InstalledAppFlow.run_local_server(port=0)`).
- **Authorization Flow**: Local loopback server bound to ephemeral localhost port (`65389`).
- **Operator Consent**: Interactive browser consent completed by operator with configured test user account.
- **Grant State**: Token successfully exchanged for access token via code grant.

### 5.2 Calendar Discovery (1 Call)
- **Endpoint**: `GET /calendar/v3/users/me/calendarList`
- **Read Attempts**: Exactly `1`.
- **Target Display Name Searched**: `StillDone Demo`
- **In-Memory Match Count**: Exactly `1`.
- **Sanitized Calendar ID**: `[REDACTED_CALENDAR_ID]`
- **Status**: **`PASS`** (zero fallback to primary calendar).

### 5.3 Calendar Events Read (1 Call)
- **Endpoint**: `GET /calendar/v3/calendars/[REDACTED_CALENDAR_ID]/events?maxResults=10&singleEvents=True`
- **Read Attempts**: Exactly `1`.
- **Observed Event Count**: `0`.
- **Canonical `Leave for school` Event Present**: `false` (target disposable calendar confirmed empty).
- **Status**: **`PASS`**.

### 5.4 Tasks List Discovery (1 Call)
- **Endpoint**: `GET /tasks/v1/users/@me/lists`
- **Read Attempts**: Exactly `1`.
- **Target Display Name Searched**: `StillDone Demo`
- **In-Memory Match Count**: Exactly `1`.
- **Sanitized Task List ID**: `[REDACTED_TASKLIST_ID]`
- **Status**: **`PASS`** (zero fallback to default task list).

### 5.5 Tasks Read (1 Call)
- **Endpoint**: `GET /tasks/v1/lists/[REDACTED_TASKLIST_ID]/tasks?maxResults=10`
- **Read Attempts**: Exactly `1`.
- **Observed Task Count**: `0`.
- **Status**: **`PASS`**.

---

## 6. Zero-Mutation, Zero-Retry & Cleanup Audit

| Safety Metric | Authorized Limit | Observed Actual | Status |
|---|---|---|---|
| Calendar Write Mutations | `0` | `0` | **PASS** |
| Tasks Write Mutations | `0` | `0` | **PASS** |
| API Call Retries | `0` | `0` | **PASS** |
| Unrelated Personal Data Retained | `0` | `0` | **PASS** |
| Paid Quota Alterations | `0` | `0` | **PASS** |
| Ephemeral Token File (`ephemeral_token.json`) | Deleted immediately | `DELETED` | **PASS** |
| Ephemeral Auth URL File (`auth_url.txt`) | Deleted immediately | `DELETED` | **PASS** |
| Remote OAuth Authorization Grant | Account-managed | `NOT_REVOKED` | **VERIFIED** |
| Original Client Secret JSON | Stored in local Downloads only | `PRESERVED_OUTSIDE_REPO` | **VERIFIED** |

---

## 7. Evidence Provenance

- **Calendar Integration**: `LIVE_GOOGLE_CALENDAR`
- **Tasks Integration**: `LIVE_GOOGLE_TASKS`
- **Validation Class**: `RECORDED_LIVE` for downstream audit.

---

## 8. Explicit NOT_RUN Boundary

The following activities were strictly **NOT_RUN** during this task:
1. `calendar.events.insert / update / delete`: **NOT_RUN** (no mutations authorized in P-01.05).
2. `tasks.insert / update / delete`: **NOT_RUN** (no mutations authorized in P-01.05).
3. Primary / Default personal calendar discovery or event reads: **NOT_RUN**.
4. Default personal task list tasks reads: **NOT_RUN**.
5. Secondary retry cycles: **NOT_RUN**.
6. Google SDK dependency modification in `pyproject.toml` or `uv.lock`: **NOT_RUN**.
7. Subsequent task `P-01.06` (Open-Meteo weather): **NOT_RUN / NOT_STARTED**.
