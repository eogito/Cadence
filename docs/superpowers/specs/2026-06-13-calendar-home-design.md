# Calendar-Centred Home — Design Spec

- **Date:** 2026-06-13
- **Status:** Approved design, pending spec review
- **Branch:** `feature/calendar-home` (off `main`)
- **Scope:** Re-centre the app around a month calendar. The calendar is the home; clicking a day shows that day's detail. Today gets two actions — batch-process today's emails, and "plan my day". Built in three delivery slices.

## Problem / Motivation

Today the app is a set of 7 parallel tabs (Email→Calendar, Briefing, Meeting Prep, Tasks, Contacts, My Rules, Daily Schedule). There's no single time-oriented home. Making a **month calendar the hub** gives the product a natural spine: browse any day to see its schedule and email activity, and on *today* take the two actions that matter — clear the inbox into the calendar, and plan the day.

The feature mostly **orchestrates and re-presents existing capabilities**: the LangGraph email workflow, `OutlookCalendarService`, the briefing's LLM categorization, and the daily-schedule generator all already exist.

## Decisions (from brainstorming)

- **Navigation:** the calendar becomes the **home**. Email→Calendar, Briefing, and Daily Schedule are absorbed into the day-detail (their tabs removed). Meeting Prep, Tasks, Contacts, My Rules move to a compact **"More"** menu (kept as-is).
- **Today's emails:** **combined review board** — triage all unread-today at once, then one screen of proposed tasks/events grouped by email. Approval is **per-email** (each email's proposed tasks+events are approved together by resuming its workflow thread), with an **"approve all"**. Per-individual-item toggling is out of scope because the executor commits an email's plan as a unit.
- **Plan my day:** generate a timeline **and** let the user push chosen blocks to Outlook (real events + tasks). **Today only** — other days are read-only.
- **Styling:** Hand-Drawn system (the calendar grid is pencil-ruled wobbly cells; today is a post-it; activity shows as dot/tape marks; day-detail reuses the existing hand-drawn cards).

## Architecture

```
Calendar home (month grid)  ──click day──▶  Day detail
  · prev / today / next                       ├─ TODAY → [Today's emails] + [Plan my day]
  · day cells with activity dots              └─ OTHER → [Schedule] + [Email breakdown]  (read-only)
Top nav: Calendar  ·  More ▾ (Meeting Prep · Tasks · Contacts · My Rules)
```

A new `src/api/calendar.py` router provides the calendar-specific endpoints; everything else reuses existing services. The frontend remains the single `src/static/index.html`.

## Backend endpoints (new `calendar` router unless noted)

- `GET /calendar/month?year=&month=` → `{ days: { "YYYY-MM-DD": { events: int, tasks_due: int } } }`. Events come from `OutlookCalendarService.get_upcoming_events` over the month range (extended to accept an explicit start/end); tasks from `Task.due_date` within the month for the current user.
- `GET /calendar/day?date=YYYY-MM-DD` → `{ events: [...], email_breakdown: { categorized... } }`. Events for that date; email breakdown = emails **received that date** (`OutlookMailService.get_messages_in_range`, new) run through the briefing's existing categorization prompt.
- `POST /calendar/today/emails/triage` → for every unread email received today: run `process_new_email` (the existing LangGraph graph). Return `{ proposals: [ { thread_id, subject, sender, tasks, events } ], notifications: int, promotions: int }` — only actionable emails produce proposals (the classifier already filters).
- `POST /calendar/today/emails/approve` → body `{ thread_ids: [...] }`; resume each selected thread with the approve decision (reuses `approve_plan`/the executor) → creates events + tasks. Returns a summary. (Triaged-but-unapproved threads simply expire from the in-memory checkpointer.)
- `POST /daily-schedule` (extend the existing endpoint) → accept optional `intent: str` (free text) and fold today's open + email-derived tasks into the generation prompt. Returns the timeline (existing shape).
- `POST /calendar/schedule/push` → body `{ blocks: [ { title, start, end, ... } ] }` → create Outlook events via `OutlookCalendarService.create_event` (+ tasks where appropriate). Returns created links.

All endpoints use the `current_user` session dependency.

## Reused components

- **LangGraph workflow** (`src/workflows/`) — one thread per email; the combined board aggregates the paused `analysis` of each; bulk-approve resumes the chosen threads. No change to the graph itself.
- **`OutlookCalendarService`** — add a `get_events_in_range(user, start, end)` (generalize `get_upcoming_events`) and reuse `create_event`.
- **`OutlookMailService`** — add `get_messages_in_range(user, start, end, unread_only=False)` for date-scoped mail (client-side date filtering to avoid Graph's `$filter`+`$orderby` limit).
- **Briefing categorization** (`src/api/briefing.py`) — factor its LLM categorization into a reusable helper used by both the briefing and `/calendar/day`.
- **Daily-schedule generator** (`src/api/daily_schedule.py`) — extended with `intent` + email-derived tasks; `create-task` already exists, add the calendar push.

## Delivery slices

1. **Calendar hub + browsing** — month grid (hand-drawn) + prev/today/next + activity dots; fold the kept features into a "More" menu; remove the absorbed tabs; **other-day** day-detail (read-only schedule + email breakdown). Ships `GET /calendar/month`, `GET /calendar/day`, the `OutlookCalendarService`/`OutlookMailService` range helpers, and the briefing-categorizer refactor.
2. **Today's emails** — combined review board: `POST /calendar/today/emails/triage` + `/approve`, and the board UI (proposals list, per-item + approve-all).
3. **Plan my day** — intent prompt + Focused/Light/Catch-up presets; extend `/daily-schedule` with `intent`; `POST /calendar/schedule/push`; the generate→review→push UI.

## Data flow — "Process today's emails" (slice 2)
1. Browser → `POST /calendar/today/emails/triage`.
2. Backend lists unread emails received today, runs each through `process_new_email` (classify → extract → pause at human_review), collects the actionable analyses + `thread_id`s.
3. Board renders all proposed tasks/events grouped by email; user selects items / "approve all".
4. Browser → `POST /calendar/today/emails/approve` with the chosen `thread_id`s → each resumes → executor creates Outlook events + persists tasks → calendar grid refreshes.

## Error handling
- No mailbox / Graph error → friendly message in the relevant card (per existing patterns).
- A single email's triage failing doesn't abort the batch — it's skipped with a noted count.
- `current_user` 401 → the existing sign-in gate.
- Empty results (no events / no emails that day) → empty-state copy, not an error.

## Testing
- Unit (stdlib `unittest`): month-grid date math (build the weeks for a given year/month, leading/trailing blanks), the "received today / in range" filter, and the block→event payload mapper. Pure functions.
- The LLM/Graph batch + categorization paths are mocked where practical and covered by the manual smoke test (process a day's inbox; plan a day; push a block; browse a past day).

## Non-goals / later
- Plan-my-day for non-today days (today only for now).
- Week/agenda views, drag-to-reschedule, recurring-event editing.
- Real-time calendar push notifications / webhooks.
- The deferred horizontal-scaling work (single instance).
