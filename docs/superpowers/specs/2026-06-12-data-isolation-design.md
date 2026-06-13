# Data Isolation (Multi-Tenant Security) — Design Spec

- **Date:** 2026-06-12
- **Status:** Approved design, pending spec review
- **Branch:** `feature/data-isolation` (off `feature/outlook`)
- **Scope:** Sub-project #1 of the "fully public launch" program. The security foundation: every endpoint identifies the user from the session and only ever touches that user's data.

## Problem / Motivation

Most endpoints still identify the user via a `?email=` query param (or a `user_email`/`email` body field) defaulting to a hardcoded address. On a public URL, anyone could pass another person's email and read or write their data. Worse, two mutations look up resources by raw id with no ownership check — `complete_task` and `delete_rule` — so a signed-in user could act on anyone's task or rule by guessing an id. This is a hard blocker for any public exposure.

Slices 1–3 of the Outlook work already added a real login session and a `current_user` dependency (`src/api/deps.py`); the trigger and briefing already use it. This sub-project finishes the sweep across the remaining endpoints and adds resource-level ownership checks.

## Goals

- Every user-scoped endpoint derives the user from the session via `current_user` — no `email=` param anywhere.
- Every resource read/mutation is filtered by the current user's id; cross-user access returns 404.
- The frontend never sends an email to identify the user; unauthenticated users see only a sign-in prompt.

## Non-goals (later sub-projects)

- Token encryption, Postgres LangGraph checkpointer, scheduler hardening, rate limiting, deployment, Microsoft publisher verification.
- The internal `process_new_email(email_address, message_id)` keeps using email internally (the value comes from `current_user.email`, not user input) — harmless; optional cleanup later.

## Components

### 1. Convert endpoints to `current_user`
For each handler below: add `user: User = Depends(current_user)`, remove the `email`/`user_email` parameter, and delete the now-redundant `select(User).where(User.email == ...)` lookup + its 404 (since `current_user` already 401s when unauthenticated). Import `current_user` from `src.api.deps`.

- `src/api/settings.py` — `GET`/`PUT /settings/email-sections`
- `src/api/tasks.py` — `GET /tasks-list`, `GET /tasks-list/contacts`
- `src/api/context.py` — `GET`/`POST /context`, `DELETE /context/{item_id}`, `POST`/`GET /context/rules`
- `src/api/meeting_prep.py` — `GET /meeting-prep`
- `src/api/daily_schedule.py` — `GET /daily-schedule`, `POST /daily-schedule/create-task`
- `src/api/approval.py` — `POST /tasks/send-draft`

Remove the `email` / `user_email` field (and the `"glenlin7813@gmail.com"` default) from these request models: `EmailSectionsRequest`, `AddContextRequest`, `AddRuleRequest`, `CreateTaskFromBlockRequest`, `DraftSendRequest`.

### 2. Close the ownership holes
- `complete_task` (`tasks.py`): `select(Task).where(Task.id == uuid.UUID(task_id), Task.user_id == user.id)` → 404 if not found/owned.
- `delete_rule` (`context.py`): `select(RecurringRule).where(RecurringRule.id == uuid.UUID(rule_id), RecurringRule.user_id == user.id)` → 404 if not found/owned.
- `remove_context` (`context.py`) and `get_contacts` (`tasks.py`) are already user-scoped — leave them.
- Cross-user access returns **404** (not 403) so the API doesn't reveal that an id exists.

### 3. Frontend (`src/static/index.html`)
- Remove every remaining email input: `rulesEmail`, `tasksEmail`, `contactsEmail`, `prepEmail`, `scheduleEmail`, and any `email` sent in request bodies (`addContext`, `addRule`, `createTaskFromBlock`, `sendDraft`, `saveEmailSections`, `loadEmailSections`, `loadRulesTab`, `getTasks`, `getContacts`, `getMeetingPrep`, `getDailySchedule`). All calls rely on the session cookie.
- **Auth gating:** on load, `checkAuth()` already calls `/auth/me`. Extend it so that when unauthenticated, the `<main>` content (the tabs + nav) is hidden and only a centered "Sign in with Microsoft" prompt shows; once authenticated, reveal the app. Any data fetch returning 401 re-triggers the gate.

### 4. Data flow (example: complete a task)
1. Browser (authenticated) → `PATCH /tasks-list/{id}/complete` (no email).
2. `current_user` resolves the user from the session.
3. The query filters `Task.id == id AND Task.user_id == user.id`; if no row, 404.
4. Only the owner's task is ever mutated.

## Error handling
- Unauthenticated request to any converted endpoint → 401 (from `current_user`).
- Authenticated request for another user's resource id → 404.
- Frontend: a 401 from any call hides the app and shows the sign-in prompt.

## Testing
- The `current_user` dependency already has unit tests (`tests/test_outlook_auth.py`); those continue to guard the auth gate.
- Ownership filtering is DB-level SQL, which isn't meaningfully unit-testable without a live database, so it's verified by the manual cross-user test below.
- **Manual cross-user test:** sign in as user A (an Outlook account), create a task and a recurring rule. Sign in as user B (a different Outlook account); confirm B's lists show none of A's data, and that calling complete on A's task id / delete on A's rule id returns 404. Confirm the app is hidden until signed in.

## Edge cases
- A signed-in user with no data → empty lists (already handled), not an error.
- Stale session (user row deleted) → `current_user` clears the session and 401s; frontend re-prompts.
- Existing single-user data keyed to the old Google user is irrelevant on this branch (fresh Outlook accounts).
