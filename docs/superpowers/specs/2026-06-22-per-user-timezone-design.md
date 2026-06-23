# Per-User Timezone — Design

**Date:** 2026-06-22
**Scope:** Make the schedule feature and Outlook event push timezone-correct for non-UTC users. Bounded to avoid destabilizing the mail and month-grid paths.

## Problem

The app is UTC-anchored. `OutlookCalendarService._event_body` hardcodes `timeZone: "UTC"`, so a schedule block at local 9:00 (sent as naive `...T09:00:00`) is written to Outlook as **9:00 UTC** — wrong clock time for any non-UTC user. Additionally, `get_events_in_range` requests events in UTC, so `schedule.py`'s `_iso_to_minute` yields UTC minutes while blocks are stored as minutes-from-local-midnight — the AI `generate` gap/busy math is shifted, and woven-in events sit at the wrong timeline position. Microsoft Graph accepts IANA timezone names natively, so the fix is to learn each user's timezone and stop saying "UTC."

## Decisions

- **Timezone source:** auto-detect the browser's IANA timezone (`Intl.DateTimeFormat().resolvedOptions().timeZone`) and save it to the user record on load. No manual picker.
- **Bounded scope:** fix push + the `/schedule` endpoints' event handling. Leave the mail received-time filter (`get_messages_in_range` / `_in_received_range`) and the month-grid event dots on their current UTC-day basis — not made worse, and touching them risks the mail path.

## Design

### 1. Store the timezone
- Add `timezone = Column(String(64), default="UTC")` to `src/models/user.py` (auto-created via `create_all`).
- `src/api/settings.py`: `POST /settings/timezone` with body `{ "timezone": str }` → validates it's a real IANA zone (constructable via `zoneinfo.ZoneInfo`) and saves it on `current_user`. Invalid → 400.
- Helper `user_tz(user) -> str` (in `src/services/calendar_dates.py`): returns `user.timezone or "UTC"`.
- Frontend (`index.html`): in `checkAuth()` after sign-in success, read `Intl.DateTimeFormat().resolvedOptions().timeZone` and `POST /settings/timezone` (fire-and-forget; ignore failures).

### 2. Fix the push
- `OutlookCalendarService.create_event(user, summary, start_iso, end_iso)`: `_event_body` stamps `timeZone: user_tz(user)` (not "UTC") and sends the naive local wall-clock (`.rstrip("Z")` unchanged). `_event_body` becomes an instance-aware helper that takes the tz (signature `_event_body(summary, start, end, tz)`).
- Effect: the schedule push (`_block_to_iso` already emits naive local wall-clock) lands at the correct local time. Email→calendar executor events also become local-correct.

### 3. Fix schedule event alignment + gap math
- `get_events_in_range(user, start_iso, end_iso, prefer_tz="UTC")`: the `Prefer` header becomes `outlook.timezone="<prefer_tz>"`. Returned event `dateTime`s are then in `prefer_tz` wall-clock.
- New `local_day_range(date_str, tz) -> (start_utc_iso, end_utc_iso)` in `calendar_dates.py`: builds local midnight and local next-midnight in `ZoneInfo(tz)`, converts to UTC instants, returns their ISO. Passed as the calendarView window (absolute instants) alongside `prefer_tz=tz` so the window is the user's local day and events come back in local wall-clock.
- `src/api/schedule.py` `get_schedule` and `generate`: replace `day_range(date)` + default events fetch with `local_day_range(date, user_tz(user))` + `get_events_in_range(..., prefer_tz=user_tz(user))`. Now `_iso_to_minute` on events yields local minutes matching blocks.

### 4. Dependency
- Add `tzdata` to `requirements.txt` (Windows has no system tz database, so `zoneinfo.ZoneInfo("America/New_York")` raises `ZoneInfoNotFoundError` without it; Render/Linux already has system tz data but pinning `tzdata` is harmless and portable).

## Out of scope
- Mail received-time filtering and month-grid event dots (stay UTC-day).
- Manual timezone override UI.
- Backfilling existing blocks (they're already stored as local-minutes; only push/display interpretation changes).

## Testing (stdlib `unittest`)
- `user_tz`: returns `"UTC"` when unset, the stored value otherwise.
- `local_day_range("2026-06-22", "America/New_York")` → `("2026-06-22T04:00:00+00:00", "2026-06-23T04:00:00+00:00")` (EDT = UTC-4).
- `_event_body` stamps the passed tz and strips the trailing `Z`, keeping the naive wall-clock.
- `POST /settings/timezone` request model has no email/user_email field (data isolation), and an invalid zone is rejected.
