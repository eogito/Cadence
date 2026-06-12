# Microsoft Integration — Slice 3: Calendar, Send, Meeting Prep, Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Google→Microsoft swap — create Outlook calendar events, send draft replies and run Meeting Prep via Graph, then delete all Google code so the whole email→calendar loop runs on Outlook.

**Architecture:** Add `OutlookCalendarService` (Graph `/me/events` + `/me/calendarView`) and extend `OutlookMailService` with `send_email` + `search_emails_from_sender`. Repoint the executor, briefing, meeting-prep, daily-schedule, and send-draft call sites at the Outlook services, then delete `google_auth.py`, `gmail_service.py`, `calendar_service.py` and their obsolete test. Endpoints keep their existing `email=` params (the full `current_user` sweep is the separate hardening sub-project); the services just need the `user` object, which those endpoints already load.

**Tech Stack:** Python 3.12, FastAPI, MSAL, `httpx`, SQLAlchemy async. Tests: stdlib `unittest` — `./venv/Scripts/python.exe -m unittest <module>`.

**Scope note:** Slice 3 (final) of `docs/superpowers/specs/2026-06-11-microsoft-account-integration-design.md`. Token encryption, `MemorySaver`→Postgres, scheduler-at-scale, Alembic, the full `current_user` sweep of pure-DB endpoints, and deployment are the later hardening/deploy sub-projects.

---

## File Structure

- `src/services/outlook_mail_service.py` — add `send_email`, `search_emails_from_sender`, `_graph_post`, `_sendmail_payload`.
- `src/services/outlook_calendar_service.py` — **new**: `OutlookCalendarService`.
- `src/workflows/agent.py` — executor uses `OutlookCalendarService.create_event`.
- `src/api/briefing.py` — calendar via `OutlookCalendarService`.
- `src/api/meeting_prep.py` — calendar + mail via Outlook; drop the Google re-fetch.
- `src/api/daily_schedule.py` — calendar via `OutlookCalendarService`.
- `src/api/approval.py` — send-draft via `OutlookMailService.send_email`.
- `src/config.py` — remove the Google settings.
- **Delete:** `src/services/google_auth.py`, `src/services/gmail_service.py`, `src/services/calendar_service.py`, `tests/test_gmail_body.py`.
- `tests/test_outlook_mail.py` — add `send_email`/calendar payload tests.

---

## Task 1: Outlook mail send + sender search

**Files:**
- Modify: `src/services/outlook_mail_service.py`
- Test: `tests/test_outlook_mail.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_outlook_mail.py`:

```python
class SendMailPayloadTests(unittest.TestCase):
    def test_sendmail_payload_shape(self):
        payload = OutlookMailService._sendmail_payload("a@b.com", "Hi", "Body text")
        self.assertEqual(payload["message"]["subject"], "Hi")
        self.assertEqual(payload["message"]["body"], {"contentType": "Text", "content": "Body text"})
        self.assertEqual(
            payload["message"]["toRecipients"],
            [{"emailAddress": {"address": "a@b.com"}}],
        )
        self.assertTrue(payload["saveToSentItems"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v`
Expected: FAIL — `AttributeError: ... has no attribute '_sendmail_payload'`.

- [ ] **Step 3: Implement**

In `src/services/outlook_mail_service.py`, add a `_graph_post` helper next to `_graph_get`:

```python
    @staticmethod
    async def _graph_post(user: User, path: str, json_body: dict) -> dict:
        token = await MicrosoftAuthService.get_access_token(user)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph error {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}
```

Add the pure payload builder and the two methods (after `get_unread_emails`):

```python
    @staticmethod
    def _sendmail_payload(to: str, subject: str, body: str) -> dict:
        return {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }

    @staticmethod
    async def send_email(user: User, to: str, subject: str, body: str) -> dict:
        await OutlookMailService._graph_post(user, "/me/sendMail", OutlookMailService._sendmail_payload(to, subject, body))
        return {"status": "sent"}

    @staticmethod
    async def search_emails_from_sender(user: User, sender_email: str, max_results: int = 5):
        # No $orderby here: Graph rejects $filter + $orderby on different properties.
        params = {
            "$filter": f"from/emailAddress/address eq '{sender_email}'",
            "$top": str(max_results),
            "$select": "subject,bodyPreview,receivedDateTime",
        }
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        return [
            {
                "subject": m.get("subject", "No Subject"),
                "date": m.get("receivedDateTime", ""),
                "snippet": m.get("bodyPreview", ""),
            }
            for m in data.get("value", [])
        ]
```

- [ ] **Step 4: Run test + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v` → PASS.
Run: `./venv/Scripts/python.exe -c "import src.services.outlook_mail_service; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/services/outlook_mail_service.py tests/test_outlook_mail.py
git commit -m "feat: Outlook mail send + sender search via Graph"
```

---

## Task 2: OutlookCalendarService

**Files:**
- Create: `src/services/outlook_calendar_service.py`
- Test: `tests/test_outlook_mail.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_outlook_mail.py`:

```python
from src.services.outlook_calendar_service import OutlookCalendarService


class CalendarPayloadTests(unittest.TestCase):
    def test_event_body_strips_trailing_z(self):
        body = OutlookCalendarService._event_body("Sync", "2026-06-15T14:00:00Z", "2026-06-15T15:00:00Z")
        self.assertEqual(body["subject"], "Sync")
        self.assertEqual(body["start"], {"dateTime": "2026-06-15T14:00:00", "timeZone": "UTC"})
        self.assertEqual(body["end"], {"dateTime": "2026-06-15T15:00:00", "timeZone": "UTC"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.outlook_calendar_service'`.

- [ ] **Step 3: Implement the service**

Create `src/services/outlook_calendar_service.py`:

```python
import httpx
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from src.models.user import User
from src.services.ms_auth import MicrosoftAuthService

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookCalendarService:
    @staticmethod
    async def _graph_request(user: User, method: str, path: str, params: dict = None, json_body: dict = None, extra_headers: dict = None) -> dict:
        token = await MicrosoftAuthService.get_access_token(user)
        headers = {"Authorization": f"Bearer {token}"}
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, f"{GRAPH_BASE}{path}", headers=headers, params=params, json=json_body)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph error {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    @staticmethod
    def _event_body(summary: str, start_time: str, end_time: str) -> dict:
        return {
            "subject": summary,
            "start": {"dateTime": start_time.rstrip("Z"), "timeZone": "UTC"},
            "end": {"dateTime": end_time.rstrip("Z"), "timeZone": "UTC"},
        }

    @staticmethod
    async def get_upcoming_events(user: User, days_ahead: int = 7) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        params = {
            "startDateTime": now.isoformat(),
            "endDateTime": (now + timedelta(days=days_ahead)).isoformat(),
            "$orderby": "start/dateTime",
            "$select": "subject,start,end,attendees",
            "$top": "50",
        }
        data = await OutlookCalendarService._graph_request(
            user, "GET", "/me/calendarView", params=params,
            extra_headers={"Prefer": 'outlook.timezone="UTC"'},
        )
        events = []
        for e in data.get("value", []):
            attendees = [
                (a.get("emailAddress", {}) or {}).get("address", "")
                for a in e.get("attendees", [])
            ]
            events.append({
                "id": e.get("id"),
                "summary": e.get("subject", "Busy"),
                "start": (e.get("start", {}) or {}).get("dateTime", ""),
                "end": (e.get("end", {}) or {}).get("dateTime", ""),
                "attendees": [a for a in attendees if a],
            })
        return events

    @staticmethod
    async def create_event(user: User, summary: str, start_time: str, end_time: str) -> dict:
        data = await OutlookCalendarService._graph_request(
            user, "POST", "/me/events", json_body=OutlookCalendarService._event_body(summary, start_time, end_time)
        )
        return {"event_id": data.get("id"), "link": data.get("webLink")}
```

- [ ] **Step 4: Run test + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v` → PASS.
Run: `./venv/Scripts/python.exe -c "import src.services.outlook_calendar_service; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/services/outlook_calendar_service.py tests/test_outlook_mail.py
git commit -m "feat: add OutlookCalendarService (events via Graph)"
```

---

## Task 3: Executor creates Outlook events

**Files:**
- Modify: `src/workflows/agent.py`

- [ ] **Step 1: Repoint the executor**

In `src/workflows/agent.py`, inside `execute_plan`, change the calendar import from `from src.services.calendar_service import CalendarService` to:

```python
    from src.services.outlook_calendar_service import OutlookCalendarService
```

and change the call `await CalendarService.create_event(...)` to `await OutlookCalendarService.create_event(...)` (same keyword arguments: `user`, `summary`, `start_time`, `end_time`).

- [ ] **Step 2: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.workflows.agent; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/workflows/agent.py
git commit -m "feat: executor schedules events in Outlook Calendar"
```

---

## Task 4: Briefing calendar via Outlook

**Files:**
- Modify: `src/api/briefing.py`

- [ ] **Step 1: Swap the calendar service**

In `src/api/briefing.py`, change the import `from src.services.calendar_service import CalendarService` to:

```python
from src.services.outlook_calendar_service import OutlookCalendarService
```

and in `get_daily_briefing` change `CalendarService.get_upcoming_events(user, days_ahead=1)` to `OutlookCalendarService.get_upcoming_events(user, days_ahead=1)`.

- [ ] **Step 2: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/api/briefing.py
git commit -m "feat: briefing reads Outlook calendar"
```

---

## Task 5: Meeting Prep via Outlook

**Files:**
- Modify: `src/api/meeting_prep.py`

- [ ] **Step 1: Swap services and use attendees from the event**

In `src/api/meeting_prep.py`:
- Change imports: replace `from src.services.gmail_service import GmailService` and `from src.services.calendar_service import CalendarService` with:

```python
from src.services.outlook_mail_service import OutlookMailService
from src.services.outlook_calendar_service import OutlookCalendarService
```

- Change `await CalendarService.get_upcoming_events(user, days_ahead=7)` to `await OutlookCalendarService.get_upcoming_events(user, days_ahead=7)`.
- Replace the entire Google re-fetch block (the `service_obj = None` / `try:` block that calls `GoogleAuthService.get_calendar_service` and builds `attendee_emails`) with a single line using the attendees the calendar service now returns:

```python
    attendee_emails = [a for a in next_event.get("attendees", []) if a and a != email]
```

- Change the sender search to `OutlookMailService.search_emails_from_sender(user, att, max_results=3)` in the `fetch_tasks` dict.

- [ ] **Step 2: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/api/meeting_prep.py
git commit -m "feat: Meeting Prep uses Outlook calendar + mail"
```

---

## Task 6: Daily Schedule calendar via Outlook

**Files:**
- Modify: `src/api/daily_schedule.py`

- [ ] **Step 1: Swap the calendar service**

In `src/api/daily_schedule.py`, change `from src.services.calendar_service import CalendarService` to:

```python
from src.services.outlook_calendar_service import OutlookCalendarService
```

Then find the call to `CalendarService.get_upcoming_events(...)` in the schedule-generation endpoint and change it to `OutlookCalendarService.get_upcoming_events(...)` (same arguments).

- [ ] **Step 2: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/api/daily_schedule.py
git commit -m "feat: daily schedule reads Outlook calendar"
```

---

## Task 7: Send draft reply via Outlook

**Files:**
- Modify: `src/api/approval.py`

- [ ] **Step 1: Swap the mail service**

In `src/api/approval.py`:
- Change `from src.services.gmail_service import GmailService` to `from src.services.outlook_mail_service import OutlookMailService`.
- In `send_draft_reply`, change `sent = await GmailService.send_email(...)` to `sent = await OutlookMailService.send_email(user, to=request.to, subject=request.subject, body=request.body)`.
- Change the return to `return {"message": "Email sent successfully.", "status": sent.get("status")}`.

- [ ] **Step 2: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/api/approval.py
git commit -m "feat: send draft replies via Outlook"
```

---

## Task 8: Delete the Google code

**Files:**
- Delete: `src/services/google_auth.py`, `src/services/gmail_service.py`, `src/services/calendar_service.py`, `tests/test_gmail_body.py`
- Modify: `src/config.py`

- [ ] **Step 1: Confirm nothing still imports the Google services**

Run: `grep -rn "gmail_service\|calendar_service\|google_auth\|GmailService\|CalendarService\|GoogleAuthService" src/ tests/`
Expected: **no matches** (every call site was repointed in Tasks 3–7). If anything remains, fix that file before deleting.

- [ ] **Step 2: Delete the files**

```bash
git rm src/services/google_auth.py src/services/gmail_service.py src/services/calendar_service.py tests/test_gmail_body.py
```

- [ ] **Step 3: Remove the Google settings from config**

In `src/config.py`, delete the three Google fields from `Settings`:

```python
    google_client_id: str
    google_client_secret: SecretStr
    google_redirect_uri: str
```

(Leave `secret_key`, `openai_api_key`, `groq_api_key`, and the Microsoft/session settings. The `.env` may keep its `GOOGLE_*` lines — `extra="ignore"` skips them. The `User.google_oauth_tokens` column stays as an abandoned column; removing it is deferred to the hardening sub-project.)

- [ ] **Step 4: Verify import + full test suite**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail tests.test_outlook_auth tests.test_email_sections tests.test_email_routing -v` → all PASS (note: `tests.test_gmail_body` is intentionally gone).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove Google services and config (fully on Outlook)"
```

---

## Final verification

### Automated
- [ ] `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail tests.test_outlook_auth tests.test_email_sections tests.test_email_routing -v` → all PASS.
- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
- [ ] `grep -rn "google\|gmail\|Google\|Gmail" src/` → only incidental/comment matches, no live imports or calls.

### Manual (signed in with Microsoft)
- [ ] `./venv/Scripts/python.exe -m uvicorn src.main:app --reload`.
- [ ] **Email to Calendar → Run AI** on a real Outlook email that implies a meeting/deadline → review the plan → **Approve and Schedule** → confirm the event appears in your **Outlook calendar** (and the success status shows a `webLink`).
- [ ] If the AI proposes a reply, use **Send Reply** → confirm it sends from your Outlook account (check Sent Items).
- [ ] **Meeting Prep** → returns a brief for your next Outlook event with attendee context.
- [ ] **Morning Briefing** and **Daily Schedule** → show your Outlook calendar events.
- [ ] After this slice, the branch `feature/outlook` is a complete Outlook app — ready to review and merge.
