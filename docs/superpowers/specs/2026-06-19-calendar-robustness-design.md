# Calendar Robustness Pass — Design

**Date:** 2026-06-19
**Scope:** Polish/edge-case hardening of the calendar home feature (Slices 1–3). Contained to `src/api/calendar.py` and `src/static/index.html`.

## Problem

The calendar feature works but has five rough edges that will affect real users:

1. **Session expiry produces cryptic errors.** Every calendar fetch calls `await res.json()` unconditionally; an expired session returns a 401 HTML page, so the parse throws `Unexpected token '<'…`.
2. **Double-submit creates duplicates.** Action buttons stay enabled in-flight; double-clicking Approve or Add-to-Outlook creates duplicate Outlook events.
3. **Misleading scan count.** `triage_today_emails` reports `scanned: len(msgs)` (up to 60) but only runs the workflow on `msgs[:15]`.
4. **Re-triage is not idempotent.** `process_new_email` uses a random `uuid4` thread_id, so re-running triage spawns fresh threads/proposals and re-spends LLM calls.
5. **Push hides total failure.** `push_schedule` swallows per-block errors and returns HTTP 200 even when every block fails ("Added 0 block(s)" reads as success).

## Design

### 1. Session-expiry handling (frontend)
Add a shared `calJson(res)` helper that throws a friendly error on 401 or non-JSON responses, and route the five calendar fetches (`triageToday`, `approveToday`, `planDay`, `pushPlan`, `selectDay`) through it.

### 2. Double-submit guards (frontend)
Give each action button a stable id; disable + swap its label to a "…working" state while its request is in flight, restored in a `finally`.

### 3. Accurate scan count (backend)
Triage response returns `processed` (count actually run, ≤15) and `total_unread` (len of the fetched messages). Frontend shows "Triaged X of Y unread today".

### 4. Re-triage idempotency (backend)
Module-level cache `_TRIAGE_THREADS[(user.email, message_id)] = thread_id`. Before calling `process_new_email`, reuse a cached thread if its checkpoint state still exists; otherwise process and cache. In-memory, matching the existing `MemorySaver` lifetime.

### 5. Surface push failures (backend + frontend)
`push_schedule` returns `created`, `failed`, and `errors[]`. Frontend treats `created === 0 && requested > 0` as an error status and appends "(N failed)" when some succeed.

## Testing
`unittest` cases covering: triage response includes `processed`/`total_unread`; the idempotency cache reuses a thread for a repeated `(email, message_id)`; `push_schedule` reports `failed`/`errors` when `create_event` raises.

## Out of scope
12h/24h time-parse ambiguity and UTC-vs-local "today" (tracked separately as the "time & timezone" bucket).
