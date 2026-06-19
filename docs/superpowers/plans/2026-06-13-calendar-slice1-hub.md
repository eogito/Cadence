# Calendar Home — Slice 1: Hub + Browsing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a month calendar the app's home; clicking any day shows that day's events + categorized email breakdown.

**Architecture:** A new `calendar` API router orchestrates existing services — adds date-range helpers to the Outlook services, refactors the briefing's LLM categorization into a shared function, and exposes `GET /calendar/month` (per-day counts) and `GET /calendar/day` (events + email breakdown). The single-page `index.html` gains a hand-drawn month grid as the default view, a "More" menu for the relocated tabs, and a day-detail renderer.

**Tech Stack:** Python 3.12, FastAPI, Microsoft Graph, Groq, async SQLAlchemy, vanilla JS. Tests: stdlib `unittest` — `./venv/Scripts/python.exe -m unittest <module>`.

**Scope note:** Slice 1 of `docs/superpowers/specs/2026-06-13-calendar-home-design.md`. Today's two action cards (batch email board, plan-my-day) are Slices 2 and 3 — in Slice 1, **today behaves like any other day** (read-only events + email breakdown). The absorbed tabs (Email→Calendar, Briefing, Daily Schedule) keep their DOM/JS for later reuse; only their nav buttons are removed.

---

## File Structure

- `src/services/calendar_dates.py` — **new**: pure date helpers (`month_range`, `day_range`, `parse_graph_dt`).
- `src/services/outlook_calendar_service.py` — add `get_events_in_range`; `get_upcoming_events` becomes a wrapper.
- `src/services/outlook_mail_service.py` — add `get_messages_in_range` + pure `_in_received_range`.
- `src/services/briefing_ai.py` — **new**: shared `generate_briefing(emails, events)` (+ models, moved from `briefing.py`).
- `src/api/briefing.py` — use the shared function.
- `src/api/calendar.py` — **new**: `GET /calendar/month`, `GET /calendar/day`.
- `src/main.py` — mount the calendar router.
- `src/static/index.html` — calendar home (grid + nav), "More" menu, day-detail renderer.
- `tests/test_calendar.py` — **new**: date helpers + received-range filter unit tests.

---

## Task 1: Pure date helpers + calendar range on the calendar service

**Files:**
- Create: `src/services/calendar_dates.py`
- Modify: `src/services/outlook_calendar_service.py`
- Test: `tests/test_calendar.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_calendar.py`:

```python
"""Tests for calendar date helpers + mail range filter (stdlib unittest)."""
import unittest
from src.services.calendar_dates import month_range, day_range, parse_graph_dt


class DateHelperTests(unittest.TestCase):
    def test_month_range_mid_year(self):
        self.assertEqual(
            month_range(2026, 6),
            ("2026-06-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00"),
        )

    def test_month_range_december_rolls_year(self):
        self.assertEqual(
            month_range(2026, 12),
            ("2026-12-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00"),
        )

    def test_day_range(self):
        self.assertEqual(
            day_range("2026-06-13"),
            ("2026-06-13T00:00:00+00:00", "2026-06-14T00:00:00+00:00"),
        )

    def test_parse_graph_dt_handles_z(self):
        dt = parse_graph_dt("2026-06-13T14:30:00Z")
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour), (2026, 6, 13, 14))

    def test_parse_graph_dt_bad_value(self):
        self.assertIsNone(parse_graph_dt("not-a-date"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_calendar -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.calendar_dates'`.

- [ ] **Step 3: Create the helpers**

Create `src/services/calendar_dates.py`:

```python
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple


def month_range(year: int, month: int) -> Tuple[str, str]:
    """UTC ISO [start, end): first of the month to first of next month."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 \
        else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start.isoformat(), end.isoformat()


def day_range(date_str: str) -> Tuple[str, str]:
    """UTC ISO [start, end) for a 'YYYY-MM-DD' day."""
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return d.isoformat(), (d + timedelta(days=1)).isoformat()


def parse_graph_dt(value: str) -> Optional[datetime]:
    """Parse a Graph datetime ('...Z' or offset) to an aware UTC datetime, or None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
```

- [ ] **Step 4: Add `get_events_in_range` and refactor `get_upcoming_events`**

In `src/services/outlook_calendar_service.py`, replace the `get_upcoming_events` method with a range method plus a thin wrapper (keeps the existing event-mapping; just parameterizes the window):

```python
    @staticmethod
    async def get_events_in_range(user: User, start_iso: str, end_iso: str):
        params = {
            "startDateTime": start_iso,
            "endDateTime": end_iso,
            "$orderby": "start/dateTime",
            "$select": "subject,start,end,attendees",
            "$top": "200",
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
    async def get_upcoming_events(user: User, days_ahead: int = 7):
        now = datetime.now(timezone.utc)
        return await OutlookCalendarService.get_events_in_range(
            user, now.isoformat(), (now + timedelta(days=days_ahead)).isoformat()
        )
```

(`datetime`, `timezone`, `timedelta` are already imported at the top of the file.)

- [ ] **Step 5: Run tests + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_calendar -v` → PASS (5 tests).
Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 6: Commit**

```bash
git add src/services/calendar_dates.py src/services/outlook_calendar_service.py tests/test_calendar.py
git commit -m "feat: calendar date helpers + get_events_in_range"
```

---

## Task 2: Date-scoped mail on the mail service

**Files:**
- Modify: `src/services/outlook_mail_service.py`
- Test: `tests/test_calendar.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_calendar.py`:

```python
from src.services.outlook_mail_service import OutlookMailService


class ReceivedRangeTests(unittest.TestCase):
    def _msgs(self):
        return [
            {"id": "a", "receivedDateTime": "2026-06-13T09:00:00Z"},
            {"id": "b", "receivedDateTime": "2026-06-12T23:59:00Z"},
            {"id": "c", "receivedDateTime": "2026-06-14T00:00:00Z"},
        ]

    def test_filters_to_the_day(self):
        kept = OutlookMailService._in_received_range(
            self._msgs(), "2026-06-13T00:00:00+00:00", "2026-06-14T00:00:00+00:00"
        )
        self.assertEqual([m["id"] for m in kept], ["a"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_calendar -v`
Expected: FAIL — `AttributeError: ... has no attribute '_in_received_range'`.

- [ ] **Step 3: Implement the filter + range fetch**

In `src/services/outlook_mail_service.py`, add a top-level import `from src.services.calendar_dates import parse_graph_dt`, then add these methods to `OutlookMailService`:

```python
    @staticmethod
    def _in_received_range(messages, start_iso: str, end_iso: str):
        start, end = parse_graph_dt(start_iso), parse_graph_dt(end_iso)
        out = []
        for m in messages:
            r = parse_graph_dt(m.get("receivedDateTime", ""))
            if r is not None and start <= r < end:
                out.append(m)
        return out

    @staticmethod
    async def get_messages_in_range(user: User, start_iso: str, end_iso: str,
                                    unread_only: bool = False, max_fetch: int = 80):
        """Messages received within [start, end). Filtered client-side to avoid Graph's
        $filter + $orderby restriction."""
        params = {
            "$top": str(max_fetch),
            "$orderby": "receivedDateTime desc",
            "$select": "subject,from,bodyPreview,receivedDateTime,isRead",
        }
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        msgs = data.get("value", [])
        if unread_only:
            msgs = [m for m in msgs if not m.get("isRead", True)]
        msgs = OutlookMailService._in_received_range(msgs, start_iso, end_iso)
        return [{
            "message_id": m.get("id"),
            "subject": m.get("subject", "No Subject"),
            "sender": OutlookMailService._sender(m),
            "snippet": m.get("bodyPreview", ""),
            "date": m.get("receivedDateTime", ""),
        } for m in msgs]
```

- [ ] **Step 4: Run tests + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_calendar -v` → PASS (6 tests).
Run: `./venv/Scripts/python.exe -c "import src.services.outlook_mail_service; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/services/outlook_mail_service.py tests/test_calendar.py
git commit -m "feat: get_messages_in_range (date-scoped mail)"
```

---

## Task 3: Share the briefing categorizer

**Files:**
- Create: `src/services/briefing_ai.py`
- Modify: `src/api/briefing.py`

- [ ] **Step 1: Create the shared module**

Create `src/services/briefing_ai.py` by moving the briefing's models + LLM logic into a reusable function:

```python
import json
from typing import List
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from src.config import settings

CATEGORIES = ["urgent_reply", "action_required", "fyi", "news_newsletter", "spam_promo", "other"]


class EmailCategory(BaseModel):
    message_id: str
    subject: str
    sender: str
    snippet: str
    category: str = Field(description="One of: urgent_reply, action_required, fyi, news_newsletter, spam_promo, other")
    reason: str = Field(description="One sentence explaining why this category was assigned")


class BriefingAnalysis(BaseModel):
    calendar_summary: str = Field(description="2-3 sentence summary of the day's schedule")
    categorized_emails: List[EmailCategory]


async def generate_briefing(emails: list, events: list) -> dict:
    """Categorize a set of emails and summarize a set of calendar events.

    Returns {calendar_summary, events, categorized_emails(grouped), stats}.
    Used by the morning briefing (today's unread) and the calendar day view (a day's mail).
    """
    events_text = json.dumps(events, indent=2) if events else "No events."
    emails_list = "\n\n".join(
        f"[{i}] message_id={e['message_id']}\nFrom: {e['sender']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}"
        for i, e in enumerate(emails)
    ) if emails else "No emails."

    schema_str = (
        '{{\n  "calendar_summary": string,\n  "categorized_emails": [\n    {{\n'
        '      "message_id": string,\n      "subject": string,\n      "sender": string,\n'
        '      "snippet": string,\n'
        '      "category": "urgent_reply|action_required|fyi|news_newsletter|spam_promo|other",\n'
        '      "reason": string\n    }}\n  ]\n}}'
    )
    system_msg = (
        "You are an AI executive assistant. Categorize each email into exactly one of these categories:\n"
        "- urgent_reply: needs a response today, sender is waiting\n"
        "- action_required: requires a task or decision but not necessarily a reply\n"
        "- fyi: informational only, no action needed\n"
        "- news_newsletter: newsletters, digests, blog posts\n"
        "- spam_promo: marketing, promotions, spam\n"
        "- other: doesn't fit above\n\n"
        "Respond ONLY with valid JSON matching this exact schema:\n" + schema_str
    )
    llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0,
                   api_key=settings.groq_api_key.get_secret_value())
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("user", "CALENDAR:\n{events}\n\nEMAILS:\n{emails}"),
    ])
    chain = prompt | llm.with_structured_output(BriefingAnalysis, method="json_mode")
    analysis: BriefingAnalysis = await chain.ainvoke({"events": events_text, "emails": emails_list})

    grouped = {cat: [] for cat in CATEGORIES}
    for item in analysis.categorized_emails:
        cat = item.category if item.category in grouped else "other"
        grouped[cat].append(item.model_dump())

    return {
        "calendar_summary": analysis.calendar_summary,
        "events": events,
        "categorized_emails": grouped,
        "stats": {
            "events_today": len(events),
            "unread_emails": len(emails),
            "urgent": len(grouped["urgent_reply"]),
            "action_required": len(grouped["action_required"]),
        },
    }
```

- [ ] **Step 2: Slim `briefing.py` to use it**

Replace the body of `get_daily_briefing` (everything after the `categories = await get_tracked_categories(...)` line) and remove the now-duplicated `CATEGORIES`, `EmailCategory`, `BriefingAnalysis`, and the LLM imports from `briefing.py`. The endpoint becomes:

```python
from src.services.briefing_ai import generate_briefing

@router.get("")
async def get_daily_briefing(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Generate a structured morning briefing with categorized unread mail."""
    categories = await get_tracked_categories(db, user)
    events, emails = await asyncio.gather(
        OutlookCalendarService.get_upcoming_events(user, days_ahead=1),
        OutlookMailService.get_unread_emails(user, max_results=15, classification=categories),
    )
    return await generate_briefing(emails, events)
```

Leave the other imports (`asyncio`, `get_tracked_categories`, the services, `current_user`, `get_db`, `User`) that are still used.

- [ ] **Step 3: Verify import + briefing still importable**

Run: `./venv/Scripts/python.exe -c "import src.main; from src.services.briefing_ai import generate_briefing; print('ok')"` → `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/services/briefing_ai.py src/api/briefing.py
git commit -m "refactor: share briefing categorizer via briefing_ai.generate_briefing"
```

---

## Task 4: Calendar API router

**Files:**
- Create: `src/api/calendar.py`
- Modify: `src/main.py`

- [ ] **Step 1: Create the router**

Create `src/api/calendar.py`:

```python
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.models.user import User
from src.models.task import Task
from src.api.deps import current_user
from src.services.calendar_dates import month_range, day_range, parse_graph_dt
from src.services.outlook_calendar_service import OutlookCalendarService
from src.services.outlook_mail_service import OutlookMailService
from src.services.briefing_ai import generate_briefing

router = APIRouter(prefix="/calendar", tags=["Calendar"])


@router.get("/month")
async def calendar_month(year: int, month: int,
                         user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Per-day activity counts for a month: events + tasks due."""
    start_iso, end_iso = month_range(year, month)
    events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso)

    days: dict = {}
    for e in events:
        dt = parse_graph_dt(e.get("start", ""))
        if dt:
            key = dt.date().isoformat()
            days.setdefault(key, {"events": 0, "tasks_due": 0})["events"] += 1

    result = await db.execute(
        select(Task).where(Task.user_id == user.id, Task.due_date.isnot(None))
    )
    for t in result.scalars().all():
        if t.due_date and t.due_date.year == year and t.due_date.month == month:
            key = t.due_date.date().isoformat()
            days.setdefault(key, {"events": 0, "tasks_due": 0})["tasks_due"] += 1

    return {"year": year, "month": month, "days": days}


@router.get("/day")
async def calendar_day(date: str,
                       user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """A single day's events + categorized email breakdown."""
    try:
        start_iso, end_iso = day_range(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso)
    emails = await OutlookMailService.get_messages_in_range(user, start_iso, end_iso)
    breakdown = await generate_briefing(emails, events) if emails else {
        "calendar_summary": "", "events": events, "categorized_emails": {}, "stats": {}
    }
    is_today = date == datetime.now(timezone.utc).date().isoformat()
    return {"date": date, "is_today": is_today, "events": events, "email_breakdown": breakdown}
```

- [ ] **Step 2: Mount the router**

In `src/main.py`, add `from src.api.calendar import router as calendar_router` near the other router imports, and `app.include_router(calendar_router)` with the other `include_router` calls.

- [ ] **Step 3: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/api/calendar.py src/main.py
git commit -m "feat: /calendar/month and /calendar/day endpoints"
```

---

## Task 5: Frontend — calendar home grid + navigation

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Add the Calendar tab markup as the first tab**

In `index.html`, immediately after `<main id="appMain" ...>` and before the existing `<!-- TAB 1: Email to Calendar -->`, insert:

```html
  <!-- TAB 0: Calendar (home) -->
  <div id="calendarTab" class="tab active">
    <div class="card">
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:14px">
        <h2 id="calLabel" style="margin:0">Calendar</h2>
        <div class="row" style="flex:0 0 auto;gap:8px">
          <button class="btn-sm" style="flex:0 0 auto" onclick="calShift(-1)">&larr;</button>
          <button class="btn-sm" style="flex:0 0 auto" onclick="calToday()">Today</button>
          <button class="btn-sm" style="flex:0 0 auto" onclick="calShift(1)">&rarr;</button>
        </div>
      </div>
      <div id="calWeekdays" style="display:grid;grid-template-columns:repeat(7,1fr);gap:6px;font-size:.85rem;color:rgba(45,45,45,.6);margin-bottom:6px">
        <div>Mon</div><div>Tue</div><div>Wed</div><div>Thu</div><div>Fri</div><div>Sat</div><div>Sun</div>
      </div>
      <div id="calGrid" style="display:grid;grid-template-columns:repeat(7,1fr);gap:6px"></div>
    </div>
    <div id="dayDetail" class="card" style="display:none"></div>
  </div>
```

Also change the existing Email tab so it is no longer the default: change `<div id="emailTab" class="tab active">` to `<div id="emailTab" class="tab">`.

- [ ] **Step 2: Add calendar styles**

In the `<style>` block, just before `</style>`, add:

```css
    .cal-cell { aspect-ratio: 1; border: 2px solid var(--pencil); border-radius: var(--wobbly-md);
                background: var(--white); padding: 6px; cursor: pointer; font-size: .9rem;
                transition: transform .1s ease, box-shadow .1s ease; }
    .cal-cell:hover { transform: rotate(-1deg) translate(-1px,-1px); box-shadow: var(--shadow-hard); }
    .cal-cell.empty { border: none; background: transparent; cursor: default; }
    .cal-cell.today { background: var(--postit); box-shadow: var(--shadow-hard); }
    .cal-cell.selected { border-color: var(--accent); }
    .cal-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; margin: 1px; }
    .cal-dot.ev { background: var(--blue); } .cal-dot.tk { background: var(--accent); }
```

- [ ] **Step 3: Add the calendar JS**

In the `<script>` block, just before the final `checkAuth();` call, add:

```javascript
  let calYear, calMonth, calSelected = null;
  function calInit() { const n = new Date(); calYear = n.getFullYear(); calMonth = n.getMonth() + 1; renderMonth(); }
  function calShift(d) { calMonth += d; if (calMonth < 1) { calMonth = 12; calYear--; } if (calMonth > 12) { calMonth = 1; calYear++; } renderMonth(); }
  function calToday() { const n = new Date(); calYear = n.getFullYear(); calMonth = n.getMonth() + 1; renderMonth(); selectDay(isoDate(n)); }
  function isoDate(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }

  async function renderMonth() {
    const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    document.getElementById('calLabel').textContent = MONTHS[calMonth - 1] + ' ' + calYear;
    let data = { days: {} };
    try { const res = await fetch(API + '/calendar/month?year=' + calYear + '&month=' + calMonth); if (res.ok) data = await res.json(); } catch (e) {}
    const first = new Date(calYear, calMonth - 1, 1);
    const lead = (first.getDay() + 6) % 7; // Monday-first
    const daysIn = new Date(calYear, calMonth, 0).getDate();
    const todayIso = isoDate(new Date());
    let html = '';
    for (let i = 0; i < lead; i++) html += '<div class="cal-cell empty"></div>';
    for (let d = 1; d <= daysIn; d++) {
      const iso = calYear + '-' + String(calMonth).padStart(2, '0') + '-' + String(d).padStart(2, '0');
      const info = data.days[iso] || { events: 0, tasks_due: 0 };
      let dots = '';
      for (let k = 0; k < Math.min(info.events, 3); k++) dots += '<span class="cal-dot ev"></span>';
      for (let k = 0; k < Math.min(info.tasks_due, 3); k++) dots += '<span class="cal-dot tk"></span>';
      const cls = 'cal-cell' + (iso === todayIso ? ' today' : '') + (iso === calSelected ? ' selected' : '');
      html += '<div class="' + cls + '" onclick="selectDay(\'' + iso + '\')"><div style="font-weight:600">' + d + '</div><div style="margin-top:4px">' + dots + '</div></div>';
    }
    document.getElementById('calGrid').innerHTML = html;
  }
```

- [ ] **Step 4: Initialize the calendar after login**

In `checkAuth()`, in the branch where the user IS authenticated (after `main.style.display = ''`), add a call `calInit();` so the month renders once signed in.

- [ ] **Step 5: Structural verification**

- `grep -c "id=\"calGrid\"" src/static/index.html` → `1`
- `grep -c "function renderMonth(" src/static/index.html` → `1`
- `grep -c "class=\"tab active\"" src/static/index.html` → `1` (only `calendarTab` is default-active now)

- [ ] **Step 6: Commit**

```bash
git add src/static/index.html
git commit -m "feat: hand-drawn month calendar home + navigation"
```

---

## Task 6: Frontend — day detail + "More" menu + remove absorbed tabs

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Add the day-detail renderer JS**

In the `<script>` block, after `renderMonth`, add:

```javascript
  const CAL_CATS = {
    urgent_reply: 'Respond ASAP', action_required: 'Action required', fyi: 'FYI',
    news_newsletter: 'News & newsletters', spam_promo: 'Spam & promos', other: 'Other'
  };
  async function selectDay(iso) {
    calSelected = iso; renderMonth();
    const panel = document.getElementById('dayDetail');
    panel.style.display = 'block';
    panel.innerHTML = '<p class="subtitle">Loading ' + esc(iso) + '…</p>';
    try {
      const res = await fetch(API + '/calendar/day?date=' + encodeURIComponent(iso));
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed');
      let html = '<h2>' + esc(iso) + (data.is_today ? ' · Today' : '') + '</h2>';
      html += '<div class="section-header">Schedule</div>';
      html += (data.events && data.events.length)
        ? data.events.map(e => '<div class="event-card"><strong>' + esc(e.summary) + '</strong><span>' + esc(fmtTime(e.start)) + ' – ' + esc(fmtTime(e.end)) + '</span></div>').join('')
        : '<p style="color:rgba(45,45,45,.5)">No events.</p>';
      html += '<div class="section-header">Email breakdown</div>';
      const grouped = (data.email_breakdown && data.email_breakdown.categorized_emails) || {};
      let any = false;
      for (const key of Object.keys(CAL_CATS)) {
        const items = grouped[key] || [];
        if (!items.length) continue;
        any = true;
        html += '<div class="cat-section"><div class="cat-header"><span class="cat-badge cat-other">' + esc(CAL_CATS[key]) + '</span><span style="font-size:.8rem;color:rgba(45,45,45,.5)">' + items.length + '</span></div>';
        html += items.map(e => '<div class="email-row"><span class="sender">' + esc(e.sender) + '</span><span class="subject">' + esc(e.subject) + '</span><span class="reason">' + esc(e.reason || '') + '</span></div>').join('');
        html += '</div>';
      }
      if (!any) html += '<p style="color:rgba(45,45,45,.5)">No emails on this day.</p>';
      panel.innerHTML = html;
    } catch (e) {
      panel.innerHTML = '<div class="status error">Error: ' + esc(e.message) + '</div>';
    }
  }
```

- [ ] **Step 2: Replace the nav: Calendar + a "More" menu**

In `index.html`, replace the seven existing `<nav>` tab buttons (Email to Calendar … Daily Schedule) with a Calendar button and a "More" dropdown holding the kept features. Replace the buttons (keep the trailing `<span id="authArea" …>`):

```html
    <button onclick="showTab('calendarTab', this)" class="active">Calendar</button>
    <span style="position:relative">
      <button type="button" onclick="document.getElementById('moreMenu').classList.toggle('hidden')">More &#9662;</button>
      <span id="moreMenu" class="hidden" style="position:absolute;top:110%;right:0;background:var(--white);border:2px solid var(--pencil);border-radius:var(--wobbly-md);box-shadow:var(--shadow-hard);padding:6px;display:flex;flex-direction:column;gap:4px;z-index:20;min-width:150px">
        <button onclick="showTab('prepTab', this);document.getElementById('moreMenu').classList.add('hidden')">Meeting Prep</button>
        <button onclick="showTab('tasksTab', this);document.getElementById('moreMenu').classList.add('hidden')">Tasks</button>
        <button onclick="showTab('contactsTab', this);document.getElementById('moreMenu').classList.add('hidden')">Contacts</button>
        <button onclick="showTab('rulesTab', this);document.getElementById('moreMenu').classList.add('hidden')">My Rules</button>
      </span>
    </span>
```

The Email/Briefing/Daily-Schedule tab `<div>`s stay in the DOM (their logic is reused in Slices 2-3) — only their nav buttons are removed.

- [ ] **Step 3: Make `showTab` tolerate the menu button**

The existing `showTab(id, btn)` calls `btn.classList.add('active')`. The "More" submenu buttons pass `this`; that's fine. No change needed, but confirm `showTab` doesn't assume a fixed button set (it iterates `nav button` — the submenu buttons are inside `nav`, so they get the active class too; acceptable).

- [ ] **Step 4: Structural verification**

- `grep -c "id=\"moreMenu\"" src/static/index.html` → `1`
- `grep -c "function selectDay(" src/static/index.html` → `1`
- `grep -c "showTab('emailTab'" src/static/index.html` → `0` (Email nav button removed)

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html
git commit -m "feat: day detail view + More menu, calendar as home"
```

---

## Final verification

### Automated
- [ ] `./venv/Scripts/python.exe -m unittest tests.test_calendar tests.test_outlook_mail tests.test_outlook_auth tests.test_crypto tests.test_data_isolation tests.test_email_sections tests.test_email_routing -v` → all PASS.
- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

### Manual (signed in)
- [ ] Start the app; after sign-in the **Calendar** is the home view: a hand-drawn month grid, today highlighted as a post-it, blue dots = events / red dots = tasks due.
- [ ] Prev/Today/Next navigate months.
- [ ] Click a day → the day-detail card shows that day's **Schedule** (events) and **Email breakdown** (that day's mail, categorized). An empty day shows friendly empty states.
- [ ] The **More** menu opens Meeting Prep / Tasks / Contacts / My Rules (still working).
- [ ] (Slices 2 & 3 will add Today's two action cards — for now today shows the same read-only detail.)
