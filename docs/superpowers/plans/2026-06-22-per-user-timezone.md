# Per-User Timezone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Outlook event push and the `/schedule` endpoints timezone-correct by learning each user's IANA timezone (auto-detected from the browser) and using it instead of hardcoded UTC.

**Architecture:** Add a `timezone` column to `users` (auto-detected, saved via a small endpoint). `OutlookCalendarService` stamps the user's timezone on created events and can request events in the user's timezone; a `local_day_range(date, tz)` helper gives the user's local-day window so `/schedule` event math aligns with locally-stored block minutes.

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy, Microsoft Graph (native IANA tz support), `zoneinfo` + `tzdata`, vanilla JS. Tests: stdlib `unittest`.

Spec: `docs/superpowers/specs/2026-06-22-per-user-timezone-design.md`.

---

## File Structure

- **Modify** `src/models/user.py` — add `timezone` column.
- **Modify** `requirements.txt` — add `tzdata`.
- **Modify** `src/services/calendar_dates.py` — add `user_tz` + `local_day_range`.
- **Modify** `src/services/outlook_calendar_service.py` — `_event_body` takes a tz; `create_event` uses the user's tz; `get_events_in_range` gains `prefer_tz`.
- **Modify** `src/api/schedule.py` — use `local_day_range` + `prefer_tz` for the user's local day.
- **Modify** `src/api/settings.py` — `POST /settings/timezone`.
- **Modify** `src/static/index.html` — post the browser timezone on sign-in.
- **Create** `tests/test_timezone.py`.

---

## Task 1: User.timezone column + tzdata dependency

**Files:**
- Modify: `src/models/user.py`, `requirements.txt`
- Test: `tests/test_timezone.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_timezone.py`:

```python
"""Tests for per-user timezone handling (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_users_table_has_timezone_column(self):
        from src.models.user import User
        self.assertIn("timezone", User.__table__.columns)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it, expect failure**

Run: `./venv/Scripts/python.exe -m unittest tests.test_timezone -v`
Expected: FAIL (`AssertionError: 'timezone' not found`).

- [ ] **Step 3: Add the column**

In `src/models/user.py`, add this line immediately after the `ms_account_id` column line:

```python
    timezone = Column(String(64), default="UTC")            # IANA tz, auto-detected from the browser
```

- [ ] **Step 4: Add tzdata to requirements**

In `requirements.txt`, add a new line at the end:

```
tzdata
```

Then install it: `./venv/Scripts/python.exe -m pip install tzdata`

- [ ] **Step 5: Run the test, expect pass**

Run: `./venv/Scripts/python.exe -m unittest tests.test_timezone -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/models/user.py requirements.txt tests/test_timezone.py
git commit -m "feat: User.timezone column + tzdata dependency"
```

---

## Task 2: calendar_dates helpers — user_tz + local_day_range

**Files:**
- Modify: `src/services/calendar_dates.py`
- Test: `tests/test_timezone.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_timezone.py`, insert this class ABOVE the `if __name__ == "__main__":` block:

```python
class HelperTests(unittest.TestCase):
    def test_user_tz_defaults_to_utc(self):
        from src.services.calendar_dates import user_tz
        class U: timezone = None
        self.assertEqual(user_tz(U()), "UTC")

    def test_user_tz_returns_stored(self):
        from src.services.calendar_dates import user_tz
        class U: timezone = "Asia/Tokyo"
        self.assertEqual(user_tz(U()), "Asia/Tokyo")

    def test_local_day_range_edt(self):
        from src.services.calendar_dates import local_day_range
        # 2026-06-22 is in EDT (UTC-4): local midnight = 04:00 UTC
        start, end = local_day_range("2026-06-22", "America/New_York")
        self.assertEqual(start, "2026-06-22T04:00:00+00:00")
        self.assertEqual(end, "2026-06-23T04:00:00+00:00")

    def test_local_day_range_bad_tz_falls_back_utc(self):
        from src.services.calendar_dates import local_day_range
        start, end = local_day_range("2026-06-22", "Not/AZone")
        self.assertEqual(start, "2026-06-22T00:00:00+00:00")
        self.assertEqual(end, "2026-06-23T00:00:00+00:00")
```

- [ ] **Step 2: Run, expect failure**

Run: `./venv/Scripts/python.exe -m unittest tests.test_timezone.HelperTests -v`
Expected: FAIL (`ImportError: cannot import name 'user_tz'`).

- [ ] **Step 3: Implement the helpers**

In `src/services/calendar_dates.py`, change the import line at the top from:

```python
from datetime import datetime, timezone, timedelta
```

to:

```python
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
```

Then append at the end of the file:

```python
def user_tz(user) -> str:
    """The user's IANA timezone, or 'UTC' if unset."""
    return getattr(user, "timezone", None) or "UTC"


def local_day_range(date_str: str, tz: str) -> Tuple[str, str]:
    """UTC ISO instants bounding the user's LOCAL day for a 'YYYY-MM-DD' date.

    Falls back to UTC if `tz` is not a known IANA zone.
    """
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = timezone.utc
    start_local = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=zone)
    end_local = start_local + timedelta(days=1)  # next local midnight (wall-clock add)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )
```

- [ ] **Step 4: Run tests, expect pass**

Run: `./venv/Scripts/python.exe -m unittest tests.test_timezone.HelperTests -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/calendar_dates.py tests/test_timezone.py
git commit -m "feat: user_tz + local_day_range helpers"
```

---

## Task 3: create_event stamps the user's timezone

**Files:**
- Modify: `src/services/outlook_calendar_service.py`
- Test: `tests/test_timezone.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_timezone.py`, insert ABOVE the `if __name__ == "__main__":` block:

```python
class EventBodyTests(unittest.TestCase):
    def test_event_body_stamps_tz_and_strips_z(self):
        from src.services.outlook_calendar_service import OutlookCalendarService
        body = OutlookCalendarService._event_body(
            "Meet", "2026-06-22T09:00:00Z", "2026-06-22T10:00:00", "America/New_York"
        )
        self.assertEqual(body["start"], {"dateTime": "2026-06-22T09:00:00", "timeZone": "America/New_York"})
        self.assertEqual(body["end"], {"dateTime": "2026-06-22T10:00:00", "timeZone": "America/New_York"})
        self.assertEqual(body["subject"], "Meet")
```

- [ ] **Step 2: Run, expect failure**

Run: `./venv/Scripts/python.exe -m unittest tests.test_timezone.EventBodyTests -v`
Expected: FAIL (`TypeError: _event_body() takes 3 positional arguments but 4 were given`).

- [ ] **Step 3: Implement**

In `src/services/outlook_calendar_service.py`:

(a) Add an import near the top (after `from src.services.ms_auth import MicrosoftAuthService`):

```python
from src.services.calendar_dates import user_tz
```

(b) Replace the `_event_body` method with:

```python
    @staticmethod
    def _event_body(summary: str, start_time: str, end_time: str, tz: str = "UTC") -> dict:
        return {
            "subject": summary,
            "start": {"dateTime": start_time.rstrip("Z"), "timeZone": tz},
            "end": {"dateTime": end_time.rstrip("Z"), "timeZone": tz},
        }
```

(c) Replace the `create_event` method with:

```python
    @staticmethod
    async def create_event(user: User, summary: str, start_time: str, end_time: str) -> dict:
        data = await OutlookCalendarService._graph_request(
            user, "POST", "/me/events",
            json_body=OutlookCalendarService._event_body(summary, start_time, end_time, user_tz(user)),
        )
        return {"event_id": data.get("id"), "link": data.get("webLink")}
```

- [ ] **Step 4: Run tests, expect pass**

Run: `./venv/Scripts/python.exe -m unittest tests.test_timezone.EventBodyTests -v`
Expected: PASS. Also confirm no import cycle: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/services/outlook_calendar_service.py tests/test_timezone.py
git commit -m "feat: create_event stamps the user's timezone (fixes wrong-time push)"
```

---

## Task 4: get_events_in_range prefer_tz + schedule uses local day

**Files:**
- Modify: `src/services/outlook_calendar_service.py`, `src/api/schedule.py`

- [ ] **Step 1: Add `prefer_tz` to get_events_in_range**

In `src/services/outlook_calendar_service.py`, replace the `get_events_in_range` signature line and its `Prefer` header. Change:

```python
    @staticmethod
    async def get_events_in_range(user: User, start_iso: str, end_iso: str):
```

to:

```python
    @staticmethod
    async def get_events_in_range(user: User, start_iso: str, end_iso: str, prefer_tz: str = "UTC"):
```

And change:

```python
            extra_headers={"Prefer": 'outlook.timezone="UTC"'},
```

to:

```python
            extra_headers={"Prefer": f'outlook.timezone="{prefer_tz}"'},
```

- [ ] **Step 2: Use the user's local day in schedule.py**

In `src/api/schedule.py`, change the import line:

```python
from src.services.calendar_dates import day_range
```

to (this task removes the last `day_range` uses in the file, so drop it from the import):

```python
from src.services.calendar_dates import local_day_range, user_tz
```

In `get_schedule`, replace:

```python
    start_iso, end_iso = day_range(date)
    try:
        events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso)
    except PermissionError:
        raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
```

with:

```python
    tz = user_tz(user)
    start_iso, end_iso = local_day_range(date, tz)
    try:
        events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso, prefer_tz=tz)
    except PermissionError:
        raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
```

In `generate`, replace:

```python
    day = _parse_day(req.date)
    start_iso, end_iso = day_range(req.date)
    try:
        events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso)
    except PermissionError:
        raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
```

with:

```python
    day = _parse_day(req.date)
    tz = user_tz(user)
    start_iso, end_iso = local_day_range(req.date, tz)
    try:
        events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso, prefer_tz=tz)
    except PermissionError:
        raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
```


- [ ] **Step 3: Verify import + full schedule/timezone suites**

Run:
```bash
./venv/Scripts/python.exe -c "import src.main; print('ok')"
./venv/Scripts/python.exe -m unittest tests.test_timezone tests.test_schedule tests.test_calendar
```
Expected: `ok` and all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/services/outlook_calendar_service.py src/api/schedule.py
git commit -m "feat: schedule fetches events in the user's local day + timezone"
```

---

## Task 5: POST /settings/timezone + browser auto-detect

**Files:**
- Modify: `src/api/settings.py`, `src/static/index.html`
- Test: `tests/test_timezone.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_timezone.py`, insert ABOVE the `if __name__ == "__main__":` block:

```python
class TimezoneEndpointTests(unittest.TestCase):
    def test_request_has_no_email_field(self):
        from src.api.settings import TimezoneRequest
        self.assertNotIn("email", TimezoneRequest.model_fields)
        self.assertNotIn("user_email", TimezoneRequest.model_fields)
```

- [ ] **Step 2: Run, expect failure**

Run: `./venv/Scripts/python.exe -m unittest tests.test_timezone.TimezoneEndpointTests -v`
Expected: FAIL (`ImportError: cannot import name 'TimezoneRequest'`).

- [ ] **Step 3: Add the endpoint**

In `src/api/settings.py`, add an import at the top (after the existing imports):

```python
from zoneinfo import ZoneInfo
```

Then append at the end of the file:

```python
class TimezoneRequest(BaseModel):
    timezone: str


@router.post("/timezone")
async def set_timezone(
    request: TimezoneRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save the signed-in user's IANA timezone (auto-detected from the browser)."""
    try:
        ZoneInfo(request.timezone)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    user.timezone = request.timezone
    await db.commit()
    return {"timezone": request.timezone}
```

- [ ] **Step 4: Run test, expect pass**

Run: `./venv/Scripts/python.exe -m unittest tests.test_timezone.TimezoneEndpointTests -v`
Expected: PASS.

- [ ] **Step 5: Post the browser timezone on sign-in**

In `src/static/index.html`, find this block inside `checkAuth()`:

```javascript
        main.style.display = '';
        splash.style.display = 'none';
        calInit();
```

Replace with:

```javascript
        main.style.display = '';
        splash.style.display = 'none';
        calInit();
        try {
          const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
          if (tz) fetch(API + '/settings/timezone', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ timezone: tz }) });
        } catch (e) { /* tz detection unsupported — leave default */ }
```

- [ ] **Step 6: Verify + commit**

Run:
```bash
./venv/Scripts/python.exe -c "import src.main; print('ok')"
./venv/Scripts/python.exe -m unittest tests.test_timezone
grep -c "settings/timezone" src/static/index.html
```
Expected: `ok`, all timezone tests PASS, and grep returns `1`.

```bash
git add src/api/settings.py src/static/index.html tests/test_timezone.py
git commit -m "feat: auto-detect + save the browser timezone on sign-in"
```

---

## Final verification

- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
- [ ] `./venv/Scripts/python.exe -m unittest discover -s tests` → all PASS.
- [ ] **Manual** (signed in, on the running app, as a non-UTC user):
  - Open today → add a 9:00 block → **→ Outlook**; confirm the event lands at **9:00 your local time** in Outlook (not shifted).
  - Confirm your real Outlook meetings appear at the correct local positions on the timeline.
  - `generate` with meetings present schedules around them at the right local times.
