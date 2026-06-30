# Multi-day Prep Planner — Design

**Date:** 2026-06-29
**Scope:** Let a user click an upcoming Outlook event (e.g. an exam) and auto-distribute study/prep blocks across the days leading up to it, with a preview/confirm step and one-click removal of the whole plan.

## Problem

`generate` only sees the day being planned, so it can't prepare for a future exam. Users want to point at an upcoming event and have study time spread across the days before it, fitting around existing commitments.

## Decisions (locked in brainstorming)

- **Trigger:** click an upcoming Outlook event → "Plan prep for this." User picks the exact event (no auto-detection).
- **Amount + distribution:** user gives a total time budget + a per-day cap; the planner spreads it across free time in the days before the exam, ramping up toward the date, skipping/avoiding already-busy time.
- **Review:** preview grouped by day → confirm → blocks are tagged to the exam and removable as a set (and individually editable).
- **Deterministic, no LLM:** distribution is arithmetic + gap-packing — reliable, testable, free.

## Data model

Add `plan_group` (`String(120)`, nullable) to `schedule_blocks`. Blocks from one prep plan share the same label (the event title). Auto-created at startup via `ALTER TABLE schedule_blocks ADD COLUMN IF NOT EXISTS plan_group VARCHAR(120)` (same idempotent pattern as `users.timezone`).

## Algorithm — `src/services/prep_planner.py` (pure, unit-tested)

- `allocate_per_day(day_count, total_minutes, daily_cap, ramp=True) -> List[int]`
  Returns minutes for each of `day_count` days (index 0 = earliest). Ramps up toward the exam (later days weighted heavier when `ramp`), each day capped at `daily_cap`, summing to at most `total_minutes`. Rounded to 15-minute increments.
- `place_sessions(minutes, busy, window=(8*60, 22*60), max_session=90, min_session=30) -> List[Tuple[int,int]]`
  Splits a day's `minutes` into sessions of `min_session..max_session`, placed into the free gaps of `window` (via existing `free_gaps`), never overlapping `busy`. Returns `(start_minute, duration)` sessions in order. Returns fewer/short if gaps can't hold the full amount.

## API (added to `src/api/schedule.py`)

- `POST /schedule/prep-plan/preview` — body `{event_title: str, exam_date: "YYYY-MM-DD", total_minutes: int, daily_cap_minutes: int}`.
  Days run from tomorrow (local) through the day before `exam_date`. For each day: fetch the user's `ScheduleBlock`s + Outlook events (busy, in the user's tz via `local_day_range`/`prefer_tz`), compute that day's allocation and sessions. Returns `{plan_label, requested_minutes, placed_minutes, days: [{date, sessions: [{start_minute, duration_minutes, title}]}], shortfall_minutes}`. Persists nothing.
- `POST /schedule/prep-plan/commit` — body `{plan_label: str, blocks: [{date, start_minute, duration_minutes, title}]}`.
  Writes each as a `ScheduleBlock` (`plan_group=plan_label`, `category="suggested"`, `source="ai"`). Returns `{created}`.
- `DELETE /schedule/prep-plan?label=…` — deletes all of the current user's blocks with that `plan_group`. Returns `{deleted}`.

All endpoints `current_user`-scoped; preview/commit reuse `user_tz` + `local_day_range`; Outlook auth errors → 401 (same pattern as the other schedule endpoints).

## Frontend (`src/static/index.html`)

- Read-only Outlook **event rows** in the agenda get a small **"📚 Plan prep"** button (`onclick` opens the dialog with that event's title + date).
- Dialog: total hours + max-per-day inputs → **Preview** (`POST …/preview`) → renders the per-day proposed sessions + any shortfall note → **"Add to my schedule"** (`POST …/commit`) → reloads the schedule.
- The **block editor popover** shows a **"Remove this prep plan"** button when the block has a `plan_group` (`DELETE …/prep-plan?label=`), then reloads.
- Prep blocks render like normal blocks in the agenda (with their `Study: …` titles); `_block_dict` includes `plan_group`.

## Error handling

- Invalid `exam_date` / non-positive budget → 400.
- Exam date in the past or today (no days before it) → empty plan with an explanatory `shortfall`/message.
- Outlook fetch failure → 401 (token) per existing pattern; a single day's fetch error is caught so one bad day doesn't sink the whole preview.

## Testing (stdlib `unittest`, new `tests/test_prep_planner.py`)

- `allocate_per_day`: ramps up (later ≥ earlier), respects `daily_cap`, sum ≤ `total_minutes`, 15-min rounding; `ramp=False` is even.
- `place_sessions`: avoids busy intervals, respects window + max/min session, returns shortfall when gaps are too small.
- Request models carry no email/user_email field (data isolation).

## Out of scope

LLM involvement; auto-detecting which events are exams; study content/topics; spreading across days *after* the exam; recurring/auto-refreshing plans.
