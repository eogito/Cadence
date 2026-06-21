# Flexible Daily Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the throwaway "Plan my day" flow with a persistent, per-day, fully editable schedule rendered as a timeline with the day's Outlook events woven in.

**Architecture:** New `schedule_blocks` table + `ScheduleBlock` model (auto-created via `create_all`). A `schedule_ai` service holds pure time helpers and the LLM block generator (refactored from `daily_schedule.py`). A new `/schedule` router does CRUD + generate + push. The frontend day-detail renders a timeline (tap-to-edit, done, lock, conflicts, now-line) and computes conflicts/now-line/progress client-side.

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy, Groq (`llama-3.1-8b-instant`), Microsoft Graph, vanilla JS. Tests: stdlib `unittest` via `./venv/Scripts/python.exe -m unittest` (no pytest, no JS runner — frontend verified structurally + manually).

Spec: `docs/superpowers/specs/2026-06-20-flexible-schedule-design.md`.

---

## File Structure

- **Create** `src/models/schedule_block.py` — `ScheduleBlock` ORM model.
- **Create** `src/services/schedule_ai.py` — `parse_time_to_minute`, `free_gaps`, `generate_blocks`.
- **Create** `src/api/schedule.py` — `/schedule` router (GET/POST/PATCH/DELETE/generate/push).
- **Create** `tests/test_schedule.py` — pure-helper + mocked-handler tests.
- **Modify** `src/main.py` — import model, register router.
- **Modify** `src/static/index.html` — timeline UI; remove the old "Plan my day" card + `planDay`/`pushPlan`.
- **Modify** `src/api/daily_schedule.py` — remove the dead `GET ""` handler (keep `create-task-from-block`).

---

## Task 1: ScheduleBlock model

**Files:**
- Create: `src/models/schedule_block.py`
- Modify: `src/main.py`
- Test: `tests/test_schedule.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_schedule.py`:

```python
"""Tests for the flexible daily schedule (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_schedule_blocks_table_registered(self):
        import src.models.schedule_block  # noqa: F401
        from src.database import Base
        self.assertIn("schedule_blocks", Base.metadata.tables)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it, expect failure**

Run: `./venv/Scripts/python.exe -m unittest tests.test_schedule -v`
Expected: FAIL (`ModuleNotFoundError: src.models.schedule_block`).

- [ ] **Step 3: Create the model**

Create `src/models/schedule_block.py`:

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, Integer, Boolean, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class ScheduleBlock(Base):
    """A single editable time block in a user's daily schedule."""
    __tablename__ = "schedule_blocks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day = Column(Date, nullable=False, index=True)
    start_minute = Column(Integer, nullable=False)      # minutes from local midnight
    duration_minutes = Column(Integer, nullable=False, default=30)
    title = Column(String(500), nullable=False)
    notes = Column(Text, nullable=True)
    category = Column(String(20), default="manual")     # fixed_event/task/rule_based/suggested/manual
    importance = Column(Integer, nullable=True)
    done = Column(Boolean, default=False)
    locked = Column(Boolean, default=False)
    outlook_event_id = Column(String(255), nullable=True)
    source = Column(String(10), default="manual")       # ai / manual
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Register the model in main.py**

In `src/main.py`, after the line `import src.models.email_preferences  # noqa: F401`, add:

```python
import src.models.schedule_block  # noqa: F401
```

- [ ] **Step 5: Run the test, expect pass**

Run: `./venv/Scripts/python.exe -m unittest tests.test_schedule -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/models/schedule_block.py src/main.py tests/test_schedule.py
git commit -m "feat: ScheduleBlock model + table registration"
```

---

## Task 2: schedule_ai service (time helpers + generator)

**Files:**
- Create: `src/services/schedule_ai.py`
- Test: `tests/test_schedule.py`

- [ ] **Step 1: Add failing tests for the pure helpers**

Append to `tests/test_schedule.py` (above the `if __name__` block):

```python
class TimeHelperTests(unittest.TestCase):
    def test_parse_time_to_minute_variants(self):
        from src.services.schedule_ai import parse_time_to_minute
        self.assertEqual(parse_time_to_minute("9:00 AM"), 540)
        self.assertEqual(parse_time_to_minute("2:30 PM"), 870)
        self.assertEqual(parse_time_to_minute("12:00 AM"), 0)
        self.assertEqual(parse_time_to_minute("12:15 PM"), 735)
        self.assertEqual(parse_time_to_minute("14:30"), 870)  # 24h
        self.assertIsNone(parse_time_to_minute("whenever"))

    def test_free_gaps_basic(self):
        from src.services.schedule_ai import free_gaps
        # window 8:00(480)-12:00(720); busy 9:00-10:00 and 11:00-11:30
        gaps = free_gaps(480, 720, [(540, 600), (660, 690)])
        self.assertEqual(gaps, [(480, 540), (600, 660), (690, 720)])

    def test_free_gaps_merges_overlaps(self):
        from src.services.schedule_ai import free_gaps
        gaps = free_gaps(480, 720, [(500, 560), (550, 600)])
        self.assertEqual(gaps, [(480, 500), (600, 720)])
```

- [ ] **Step 2: Run, expect failure**

Run: `./venv/Scripts/python.exe -m unittest tests.test_schedule.TimeHelperTests -v`
Expected: FAIL (`ModuleNotFoundError: src.services.schedule_ai`).

- [ ] **Step 3: Create the service**

Create `src/services/schedule_ai.py`:

```python
"""Daily-schedule block generation + pure time helpers."""
import re
import json
import asyncio
from typing import List, Optional, Tuple
from datetime import datetime, timezone, date as date_cls

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.user import User
from src.models.task import Task
from src.models.recurring_rule import RecurringRule
from src.services.user_context_service import list_all_context


_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", re.IGNORECASE)


def parse_time_to_minute(time_str: str) -> Optional[int]:
    """'9:00 AM' / '14:30' -> minutes from midnight. None if unparseable."""
    if not time_str:
        return None
    m = _TIME_RE.search(time_str)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2))
    ap = (m.group(3) or "").upper()
    if ap == "PM" and h < 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def free_gaps(win_start: int, win_end: int, busy: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Return the free (start, end) gaps within [win_start, win_end) given busy intervals."""
    merged: List[Tuple[int, int]] = []
    for s, e in sorted(busy):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    gaps = []
    cursor = win_start
    for s, e in merged:
        if s > cursor:
            gaps.append((cursor, min(s, win_end)))
        cursor = max(cursor, e)
        if cursor >= win_end:
            break
    if cursor < win_end:
        gaps.append((cursor, win_end))
    return [(s, e) for s, e in gaps if e > s]


class _GenBlock(BaseModel):
    time: str = Field(description="Concrete clock start time like '9:00 AM' or '14:30' — NEVER 'Flexible'")
    title: str
    category: str = Field(description="One of: task, rule_based, suggested")
    importance: int = Field(description="1-10")
    duration_minutes: int


class _GenOutput(BaseModel):
    blocks: List[_GenBlock]


async def generate_blocks(
    user: User,
    db: AsyncSession,
    day: date_cls,
    intent: str = "",
    busy: Optional[List[Tuple[int, int]]] = None,
    events_text: str = "No calendar events.",
) -> List[dict]:
    """Generate schedule block dicts (start_minute/duration/title/category/importance).

    If `busy` is provided (fill-gaps mode), the prompt is told to schedule only in the free
    gaps and any block landing on a busy interval is dropped.
    """
    tasks_res = await db.execute(
        select(Task).where(Task.user_id == user.id, Task.completed == False)  # noqa: E712
        .order_by(Task.urgency_score.desc(), Task.due_date.asc().nullslast()).limit(15)
    )
    tasks = tasks_res.scalars().all()
    rules_res = await db.execute(
        select(RecurringRule).where(RecurringRule.user_id == user.id, RecurringRule.active == True)  # noqa: E712
    )
    rules = rules_res.scalars().all()
    context_items = list_all_context(str(user.id))

    tasks_text = "\n".join(
        f"- [{t.priority.upper()} urgency={t.urgency_score}/10] {t.title}"
        + (f" (due {t.due_date.strftime('%b %d')})" if t.due_date else "")
        for t in tasks
    ) or "No open tasks."
    rules_text = "\n".join(f"- {r.description}" for r in rules) or "No recurring reminders."
    context_text = "\n".join(f"- [{i['category']}] {i['text']}" for i in context_items) or "No personal context."

    gaps_text = ""
    if busy is not None:
        gaps = free_gaps(0, 24 * 60, busy)
        def lbl(m):
            h, mi = divmod(m, 60)
            return f"{h:02d}:{mi:02d}"
        gaps_text = (
            "\n\nIMPORTANT: Only schedule blocks inside these FREE time ranges (24h): "
            + ", ".join(f"{lbl(s)}-{lbl(e)}" for s, e in gaps)
            + ". Do not overlap times outside these ranges."
        )

    schema_str = (
        '{{ "blocks": [ {{ "time": string, "title": string, '
        '"category": "task|rule_based|suggested", "importance": number, "duration_minutes": number }} ] }}'
    )
    system_msg = (
        "You are an expert scheduler. Build a realistic, chronological daily schedule. "
        "Every block MUST have a concrete clock start time (e.g. '9:00 AM' or '14:30') — never 'Flexible' or 'Evening'. "
        "Deep work = 90-120 min, quick tasks = 15-30 min. "
        "Return ONLY valid JSON matching: " + schema_str
    )
    user_msg = (
        f"Day: {day.isoformat()}.\n\n"
        f"CALENDAR EVENTS (already fixed, do not duplicate):\n{events_text}\n\n"
        f"OPEN TASKS:\n{tasks_text}\n\n"
        f"RECURRING REMINDERS:\n{rules_text}\n\n"
        f"PERSONAL CONTEXT:\n{context_text}\n\n"
        + (f"USER'S INTENT: {intent}\n\n" if intent.strip() else "")
        + "Generate the day's blocks." + gaps_text
    )

    llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.2,
                   api_key=settings.groq_api_key.get_secret_value())
    structured = llm.with_structured_output(_GenOutput, method="json_mode")
    prompt = ChatPromptTemplate.from_messages([("system", system_msg), ("human", "{input}")])
    chain = prompt | structured
    out: _GenOutput = await asyncio.to_thread(chain.invoke, {"input": user_msg})

    busy_intervals = busy or []
    blocks = []
    for b in out.blocks:
        start = parse_time_to_minute(b.time)
        if start is None:
            continue
        dur = max(5, int(b.duration_minutes or 30))
        if any(start < be and bs < start + dur for bs, be in busy_intervals):
            continue  # respect locked/fixed time in fill-gaps mode
        blocks.append({
            "start_minute": start,
            "duration_minutes": dur,
            "title": b.title,
            "category": b.category if b.category in ("task", "rule_based", "suggested") else "suggested",
            "importance": int(b.importance) if b.importance else None,
        })
    return blocks
```

- [ ] **Step 4: Run helper tests, expect pass**

Run: `./venv/Scripts/python.exe -m unittest tests.test_schedule.TimeHelperTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/schedule_ai.py tests/test_schedule.py
git commit -m "feat: schedule_ai service — time helpers + LLM block generator"
```

---

## Task 3: /schedule API router

**Files:**
- Create: `src/api/schedule.py`
- Modify: `src/main.py`
- Test: `tests/test_schedule.py`

- [ ] **Step 1: Create the router**

Create `src/api/schedule.py`:

```python
from datetime import datetime, date as date_cls, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.user import User
from src.models.schedule_block import ScheduleBlock
from src.api.deps import current_user
from src.services.calendar_dates import day_range
from src.services.outlook_calendar_service import OutlookCalendarService
from src.services.schedule_ai import generate_blocks, parse_time_to_minute  # noqa: F401

router = APIRouter(prefix="/schedule", tags=["Schedule"])


def _parse_day(s: str) -> date_cls:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")


def _block_dict(b: ScheduleBlock) -> dict:
    return {
        "id": str(b.id), "start_minute": b.start_minute, "duration_minutes": b.duration_minutes,
        "title": b.title, "notes": b.notes, "category": b.category, "importance": b.importance,
        "done": b.done, "locked": b.locked, "pushed": bool(b.outlook_event_id), "source": b.source,
    }


async def _get_owned(db: AsyncSession, user: User, block_id: str) -> ScheduleBlock:
    res = await db.execute(select(ScheduleBlock).where(ScheduleBlock.id == block_id))
    b = res.scalars().first()
    if not b or str(b.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="Block not found")
    return b


class CreateBlockRequest(BaseModel):
    date: str
    start_minute: int
    duration_minutes: int = 30
    title: str
    notes: Optional[str] = None


class UpdateBlockRequest(BaseModel):
    title: Optional[str] = None
    start_minute: Optional[int] = None
    duration_minutes: Optional[int] = None
    notes: Optional[str] = None
    done: Optional[bool] = None
    locked: Optional[bool] = None


class GenerateRequest(BaseModel):
    date: str
    intent: str = ""
    mode: str = "replace"  # replace | fill_gaps


@router.get("")
async def get_schedule(date: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    day = _parse_day(date)
    res = await db.execute(
        select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
        .order_by(ScheduleBlock.start_minute.asc())
    )
    blocks = [_block_dict(b) for b in res.scalars().all()]
    start_iso, end_iso = day_range(date)
    events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso)
    return {"day": date, "blocks": blocks, "events": events}


@router.post("/block")
async def create_block(req: CreateBlockRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    b = ScheduleBlock(
        user_id=user.id, day=_parse_day(req.date), start_minute=req.start_minute,
        duration_minutes=max(5, req.duration_minutes), title=req.title, notes=req.notes,
        category="manual", source="manual",
    )
    db.add(b)
    await db.commit()
    await db.refresh(b)
    return _block_dict(b)


@router.patch("/block/{block_id}")
async def update_block(block_id: str, req: UpdateBlockRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    b = await _get_owned(db, user, block_id)
    for field in ("title", "start_minute", "duration_minutes", "notes", "done", "locked"):
        val = getattr(req, field)
        if val is not None:
            setattr(b, field, val)
    await db.commit()
    await db.refresh(b)
    return _block_dict(b)


@router.delete("/block/{block_id}")
async def delete_block(block_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    b = await _get_owned(db, user, block_id)
    await db.delete(b)
    await db.commit()
    return {"deleted": True}


@router.post("/generate")
async def generate(req: GenerateRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    day = _parse_day(req.date)
    start_iso, end_iso = day_range(req.date)
    events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso)

    existing_res = await db.execute(
        select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
    )
    existing = existing_res.scalars().all()

    # busy = events + (for fill_gaps, all kept blocks; for replace, only locked blocks)
    def ev_minutes(e):
        s = _iso_to_minute(e.get("start"))
        en = _iso_to_minute(e.get("end"))
        return (s, en) if s is not None and en is not None else None
    busy = [m for m in (ev_minutes(e) for e in events) if m]

    if req.mode == "fill_gaps":
        for b in existing:
            busy.append((b.start_minute, b.start_minute + b.duration_minutes))
    else:  # replace: drop non-locked blocks, keep locked
        for b in existing:
            if b.locked:
                busy.append((b.start_minute, b.start_minute + b.duration_minutes))
            else:
                await db.delete(b)
        await db.flush()

    events_text = "\n".join(f"- {e.get('summary','(busy)')}" for e in events) or "No calendar events."
    new_blocks = await generate_blocks(user, db, day, req.intent, busy=busy, events_text=events_text)

    for nb in new_blocks:
        db.add(ScheduleBlock(
            user_id=user.id, day=day, start_minute=nb["start_minute"],
            duration_minutes=nb["duration_minutes"], title=nb["title"],
            category=nb["category"], importance=nb["importance"], source="ai",
        ))
    await db.commit()

    res = await db.execute(
        select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
        .order_by(ScheduleBlock.start_minute.asc())
    )
    return {"created": len(new_blocks), "blocks": [_block_dict(b) for b in res.scalars().all()]}


def _iso_to_minute(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.hour * 60 + dt.minute


def _block_to_iso(day: date_cls, start_minute: int, duration: int):
    base = datetime(day.year, day.month, day.day)
    s = base + timedelta(minutes=start_minute)
    e = s + timedelta(minutes=duration)
    fmt = "%Y-%m-%dT%H:%M:%S"
    return s.strftime(fmt), e.strftime(fmt)


@router.post("/block/{block_id}/push")
async def push_block(block_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    b = await _get_owned(db, user, block_id)
    if b.outlook_event_id:
        return {"pushed": False, "already": True}
    start_iso, end_iso = _block_to_iso(b.day, b.start_minute, b.duration_minutes)
    res = await OutlookCalendarService.create_event(user, b.title, start_iso, end_iso)
    b.outlook_event_id = res.get("id") or res.get("event_id") or "pushed"
    await db.commit()
    return {"pushed": True, "link": res.get("link")}


@router.post("/push")
async def push_all(date: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    day = _parse_day(date)
    res = await db.execute(
        select(ScheduleBlock).where(
            ScheduleBlock.user_id == user.id, ScheduleBlock.day == day,
            ScheduleBlock.outlook_event_id.is_(None),
        )
    )
    blocks = res.scalars().all()
    pushed, failed = 0, 0
    for b in blocks:
        try:
            start_iso, end_iso = _block_to_iso(b.day, b.start_minute, b.duration_minutes)
            ev = await OutlookCalendarService.create_event(user, b.title, start_iso, end_iso)
            b.outlook_event_id = ev.get("id") or ev.get("event_id") or "pushed"
            pushed += 1
        except Exception as e:  # noqa: BLE001
            print(f"[schedule push] failed '{b.title}': {e}")
            failed += 1
    await db.commit()
    return {"pushed": pushed, "failed": failed}
```

- [ ] **Step 2: Register the router in main.py**

In `src/main.py`, after `from src.api.settings import router as settings_router`, add:

```python
from src.api.schedule import router as schedule_router
```

And after `app.include_router(settings_router)`, add:

```python
app.include_router(schedule_router)
```

- [ ] **Step 3: Add API tests (data isolation + push idempotency)**

Append to `tests/test_schedule.py` (above `if __name__`):

```python
from unittest.mock import AsyncMock, patch


class RequestModelTests(unittest.TestCase):
    def test_requests_have_no_email_field(self):
        from src.api.schedule import CreateBlockRequest, UpdateBlockRequest, GenerateRequest
        for model in (CreateBlockRequest, UpdateBlockRequest, GenerateRequest):
            self.assertNotIn("email", model.model_fields)
            self.assertNotIn("user_email", model.model_fields)


class BlockIsoTests(unittest.TestCase):
    def test_block_to_iso(self):
        from src.api.schedule import _block_to_iso
        from datetime import date
        s, e = _block_to_iso(date(2026, 6, 20), 540, 90)  # 9:00 + 90m
        self.assertEqual(s, "2026-06-20T09:00:00")
        self.assertEqual(e, "2026-06-20T10:30:00")

    def test_iso_to_minute(self):
        from src.api.schedule import _iso_to_minute
        self.assertEqual(_iso_to_minute("2026-06-20T14:30:00Z"), 870)
        self.assertIsNone(_iso_to_minute(None))


class PushIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_push_block_skips_when_already_pushed(self):
        from src.api import schedule as sched

        class FakeBlock:
            outlook_event_id = "abc"
        with patch.object(sched, "_get_owned", new=AsyncMock(return_value=FakeBlock())), \
             patch.object(sched.OutlookCalendarService, "create_event", new=AsyncMock()) as ce:
            out = await sched.push_block("id", user=object(), db=object())
        self.assertEqual(out, {"pushed": False, "already": True})
        ce.assert_not_called()
```

- [ ] **Step 4: Run all schedule tests + import check**

Run:
```bash
./venv/Scripts/python.exe -c "import src.main; print('ok')"
./venv/Scripts/python.exe -m unittest tests.test_schedule -v
```
Expected: `ok`, and all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/schedule.py src/main.py tests/test_schedule.py
git commit -m "feat: /schedule CRUD + generate (replace/fill_gaps) + push endpoints"
```

---

## Task 4: Frontend timeline UI

**Files:**
- Modify: `src/static/index.html`

Context: `selectDay(iso)` currently (around lines 1187-1231) builds, for `data.is_today`, a "Today's emails" card and a "Plan my day" card, then a read-only "Schedule" section. We keep the emails card, REPLACE the "Plan my day" card and the read-only Schedule list with the timeline, and remove the now-dead `planDay`/`pushPlan`/`planTimeToIso`/`setIntent` functions.

- [ ] **Step 1: Add timeline CSS**

In `src/static/index.html`, find the help-modal CSS line `#helpClose { ... }` block end (the `#helpClose` rule). Immediately AFTER the `#helpClose {...}` rule, add:

```css
    .sb-ctrl { border:2px solid var(--pencil); border-radius:var(--wobbly-md); background:var(--white); padding:12px; margin-bottom:12px; }
    .sb-ctrl input.sb-intent { width:100%; padding:7px 9px; border:1.5px solid var(--pencil); border-radius:7px; margin-bottom:8px; }
    .sb-ctrl .row { gap:7px; flex-wrap:wrap; }
    .sb-prog { display:flex; align-items:center; gap:8px; margin-top:10px; font-size:.8rem; color:rgba(45,45,45,.6); }
    .sb-prog .bar { flex:1; height:8px; background:#eee; border-radius:5px; overflow:hidden; }
    .sb-prog .bar i { display:block; height:100%; background:#3a9c84; }
    .sb-tl { display:flex; gap:8px; }
    .sb-axis { width:48px; font-size:.62rem; color:rgba(45,45,45,.45); }
    .sb-canvas { flex:1; position:relative; border:2px solid var(--pencil); border-radius:var(--wobbly-md); background:var(--white); overflow:hidden; }
    .sb { position:absolute; left:7px; right:7px; border-radius:7px; padding:3px 8px; font-size:.78rem; font-weight:600; box-sizing:border-box; overflow:hidden; cursor:pointer; }
    .sb small { font-weight:400; opacity:.85; font-size:.66rem; }
    .sb.mine { background:var(--blue); color:#fff; }
    .sb.ev { background:repeating-linear-gradient(45deg,#eef2fb,#eef2fb 6px,#e3e9f7 6px,#e3e9f7 12px); color:#2d3e63; border:1.5px dashed #9bb0d8; cursor:default; }
    .sb.done { background:#bcd; color:#456; text-decoration:line-through; }
    .sb.conflict { box-shadow:0 0 0 2.5px var(--accent); }
    .sb .sb-chk { float:right; margin-left:6px; }
    .sb-now { position:absolute; left:0; right:0; height:0; border-top:2px solid var(--accent); z-index:6; }
    .sb-pop { border:2px solid var(--pencil); border-radius:var(--wobbly-md); background:var(--postit); padding:12px; margin-top:12px; box-shadow:var(--shadow-hard); display:none; }
    .sb-pop.open { display:block; }
    .sb-pop label { font-size:.7rem; color:rgba(45,45,45,.6); display:block; margin-top:6px; }
    .sb-pop input { width:100%; padding:5px 7px; border:1.5px solid var(--pencil); border-radius:6px; }
    .sb-pop .r { display:flex; gap:6px; }
```

- [ ] **Step 2: Replace the Plan-my-day card + read-only schedule with the timeline mount**

In `selectDay`, find this block (the Plan-my-day card, around lines 1201-1214):

```javascript
        html += '<div class="card" style="margin-bottom:14px"><strong style="font-family:var(--font-head);font-size:1.2rem">Plan my day</strong>'
          + '<p class="subtitle" style="margin:6px 0 10px">How do you want today to go?</p>'
          + '<input type="text" id="planIntent" placeholder="e.g. deep-work morning, errands after 3pm, keep it light" style="width:100%;margin-bottom:8px">'
          + '<div class="row" style="gap:6px;margin-bottom:10px">'
          + '<button class="btn-sm" style="flex:0 0 auto" onclick="setIntent(\'A focused, deep-work day with minimal meetings\')">Focused</button>'
          + '<button class="btn-sm" style="flex:0 0 auto" onclick="setIntent(\'A light day, protect free time and energy\')">Light</button>'
          + '<button class="btn-sm" style="flex:0 0 auto" onclick="setIntent(\'A catch-up day to clear the backlog of tasks\')">Catch-up</button>'
          + '</div><button onclick="planDay()">Generate today\'s schedule</button>'
          + '<div id="planBoard"></div></div>';
      }
      html += '<div class="section-header">Schedule</div>';
      html += (data.events && data.events.length)
        ? data.events.map(e => '<div class="event-card"><strong>' + esc(e.summary) + '</strong><span>' + esc(fmtTime(e.start)) + ' – ' + esc(fmtTime(e.end)) + '</span></div>').join('')
        : '<p style="color:rgba(45,45,45,.5)">No events.</p>';
```

Replace that entire span (from `html += '<div class="card" ... Plan my day ...` through the `data.events ... 'No events.'` block, i.e. the lines shown above) with:

```javascript
      }
      html += '<div class="section-header">Schedule</div><div id="scheduleBoard"></div>';
```

(Leave the closing `}` that ended the `if (data.is_today)` exactly where it was — the snippet above keeps it. The "Email breakdown" section that follows is unchanged.)

- [ ] **Step 3: Trigger the timeline load after the day renders**

Still in `selectDay`, find:

```javascript
      panel.innerHTML = html;
    } catch (e) {
      panel.innerHTML = '<div class="status error">Error: ' + esc(e.message) + '</div>';
    }
  }
```

Replace with:

```javascript
      panel.innerHTML = html;
      loadSchedule(iso);
    } catch (e) {
      panel.innerHTML = '<div class="status error">Error: ' + esc(e.message) + '</div>';
    }
  }
```

- [ ] **Step 4: Remove the dead plan functions**

In `src/static/index.html`, delete these four functions entirely: `setIntent`, `planTimeToIso`, `planDay`, `pushPlan` (they span from `function setIntent(t) { ... }` through the end of `async function pushPlan(btn) { ... }`). They are replaced by the schedule functions added next.

- [ ] **Step 5: Add the timeline JS**

Insert this block immediately BEFORE the final `checkAuth();` line at the end of the `<script>`:

```javascript
  // ── Flexible daily schedule (timeline) ────────────────────────────────────
  const SB_PXMIN = 0.8;
  function sbMinToHHMM(m) { let h = Math.floor(m / 60), mi = m % 60; const ap = h >= 12 ? 'PM' : 'AM'; let h12 = h % 12; if (h12 === 0) h12 = 12; return h12 + ':' + String(mi).padStart(2, '0') + ' ' + ap; }
  function sbHHMMToMin(s) { const m = (s || '').match(/(\d{1,2}):(\d{2})\s*(AM|PM)?/i); if (!m) return null; let h = +m[1], mi = +m[2], ap = (m[3] || '').toUpperCase(); if (ap === 'PM' && h < 12) h += 12; if (ap === 'AM' && h === 12) h = 0; if (h > 23 || mi > 59) return null; return h * 60 + mi; }
  function sbIsoToMin(iso) { const d = new Date(iso); if (isNaN(d.getTime())) return null; return d.getHours() * 60 + d.getMinutes(); }

  async function loadSchedule(iso) {
    const board = document.getElementById('scheduleBoard');
    if (!board) return;
    board.innerHTML = '<p class="subtitle"><span class="spinner"></span>Loading schedule…</p>';
    try {
      const res = await fetch(API + '/schedule?date=' + encodeURIComponent(iso));
      const data = await calJson(res);
      if (!res.ok) throw new Error(data.detail || 'Failed');
      window._sched = { iso: iso, blocks: data.blocks || [], events: data.events || [] };
      renderSchedule();
    } catch (e) {
      board.innerHTML = '<div class="status error">Error: ' + esc(e.message) + '</div>';
    }
  }

  function renderSchedule() {
    const S = window._sched, board = document.getElementById('scheduleBoard');
    if (!S || !board) return;
    const blocks = S.blocks;
    const evs = S.events.map(e => ({ summary: e.summary, s: sbIsoToMin(e.start), e: sbIsoToMin(e.end) })).filter(x => x.s != null && x.e != null);

    let starts = [7 * 60], ends = [22 * 60];
    blocks.forEach(b => { starts.push(b.start_minute); ends.push(b.start_minute + b.duration_minutes); });
    evs.forEach(e => { starts.push(e.s); ends.push(e.e); });
    const winStart = Math.max(0, Math.floor(Math.min.apply(null, starts) / 60) * 60);
    const winEnd = Math.min(1440, Math.ceil(Math.max.apply(null, ends) / 60) * 60);
    const H = Math.max(120, (winEnd - winStart) * SB_PXMIN);

    function ov(a1, a2, b1, b2) { return a1 < b2 && b1 < a2; }
    const conflict = {};
    blocks.forEach((b, i) => {
      const bs = b.start_minute, be = b.start_minute + b.duration_minutes;
      blocks.forEach((o, j) => { if (i !== j && ov(bs, be, o.start_minute, o.start_minute + o.duration_minutes)) conflict[b.id] = 1; });
      evs.forEach(e => { if (ov(bs, be, e.s, e.e)) conflict[b.id] = 1; });
    });

    const done = blocks.filter(b => b.done).length, total = blocks.length;
    const pct = total ? Math.round(done / total * 100) : 0;

    let axis = '';
    for (let m = winStart; m <= winEnd; m += 60) axis += '<div style="height:' + (60 * SB_PXMIN) + 'px">' + sbMinToHHMM(m).replace(':00', '') + '</div>';

    let canvas = '';
    evs.forEach(e => {
      const top = (e.s - winStart) * SB_PXMIN, h = Math.max(18, (e.e - e.s) * SB_PXMIN);
      canvas += '<div class="sb ev" style="top:' + top + 'px;height:' + h + 'px">' + esc(e.summary || 'Busy') + ' <small>Outlook</small></div>';
    });
    blocks.forEach(b => {
      const top = (b.start_minute - winStart) * SB_PXMIN, h = Math.max(22, b.duration_minutes * SB_PXMIN);
      const cls = 'sb mine' + (b.done ? ' done' : '') + (conflict[b.id] ? ' conflict' : '');
      canvas += '<div class="' + cls + '" style="top:' + top + 'px;height:' + h + 'px" onclick="openBlockEditor(\'' + b.id + '\')">'
        + '<input type="checkbox" class="sb-chk" ' + (b.done ? 'checked' : '') + ' onclick="event.stopPropagation();toggleDone(\'' + b.id + '\',this.checked)">'
        + (b.locked ? '🔒 ' : '') + esc(b.title) + ' <small>' + sbMinToHHMM(b.start_minute) + ' · ' + b.duration_minutes + 'm' + (b.pushed ? ' · ✓Outlook' : '') + '</small></div>';
    });
    let nowLine = '';
    const todayIso = isoDate(new Date());
    if (S.iso === todayIso) {
      const now = new Date(); const nm = now.getHours() * 60 + now.getMinutes();
      if (nm >= winStart && nm <= winEnd) nowLine = '<div class="sb-now" style="top:' + ((nm - winStart) * SB_PXMIN) + 'px"></div>';
    }

    let html = '<div class="sb-ctrl"><input class="sb-intent" id="schedIntent" placeholder="How do you want this day to go? (optional)">'
      + '<div class="row">'
      + '<button class="btn-sm" onclick="generateDay(\'replace\',this)">✨ Generate day</button>'
      + '<button class="btn-sm" onclick="generateDay(\'fill_gaps\',this)">＋ Fill the gaps</button>'
      + '<button class="btn-sm" onclick="pushAllSchedule(this)">📅 Push all to Outlook</button>'
      + '<button class="btn-sm" onclick="addSlot()">＋ Add slot</button>'
      + '</div>'
      + (total ? '<div class="sb-prog"><span>' + done + ' of ' + total + ' done</span><div class="bar"><i style="width:' + pct + '%"></i></div></div>' : '')
      + '<div id="schedStatus" class="status hidden"></div></div>';
    html += '<div class="sb-tl"><div class="sb-axis">' + axis + '</div>'
      + '<div class="sb-canvas" style="height:' + H + 'px" onclick="if(event.target===this)addSlotFromClick(event,' + winStart + ')">' + canvas + nowLine + '</div></div>';
    html += '<div class="sb-pop" id="schedPopover"></div>';
    if (!total) html += '<p class="subtitle" style="margin-top:8px">No blocks yet — Generate a day, or tap the timeline to add one.</p>';
    board.innerHTML = html;
  }

  function openBlockEditor(id) {
    const b = (window._sched.blocks || []).find(x => x.id === id);
    if (!b) return;
    const box = document.getElementById('schedPopover');
    box.innerHTML = '<strong style="font-family:var(--font-head)">Edit block</strong>'
      + '<label>Title</label><input id="ebTitle" value="' + esc(b.title) + '">'
      + '<div class="r"><div style="flex:1"><label>Start</label><input id="ebStart" value="' + sbMinToHHMM(b.start_minute) + '"></div>'
      + '<div style="flex:1"><label>Minutes</label><input id="ebDur" type="number" value="' + b.duration_minutes + '"></div></div>'
      + '<label>Notes</label><input id="ebNotes" value="' + esc(b.notes || '') + '">'
      + '<label style="display:flex;gap:6px;align-items:center"><input id="ebLock" type="checkbox" ' + (b.locked ? 'checked' : '') + '> Lock (keep when regenerating)</label>'
      + '<div class="r" style="margin-top:9px"><button class="btn-sm" onclick="saveBlock(\'' + id + '\',this)">Save</button>'
      + '<button class="btn-sm" style="color:var(--accent)" onclick="deleteBlock(\'' + id + '\')">Delete</button>'
      + '<button class="btn-sm" onclick="pushBlock(\'' + id + '\',this)">→ Outlook</button></div>'
      + '<div id="ebStatus" class="status hidden"></div>';
    box.classList.add('open');
  }

  async function saveBlock(id, btn) {
    const start = sbHHMMToMin(document.getElementById('ebStart').value);
    if (start == null) { showStatus('ebStatus', 'Start must look like 9:00 AM.', 'error'); return; }
    const body = { title: document.getElementById('ebTitle').value, start_minute: start,
      duration_minutes: Math.max(5, parseInt(document.getElementById('ebDur').value) || 30),
      notes: document.getElementById('ebNotes').value, locked: document.getElementById('ebLock').checked };
    try {
      await withBusy(btn, 'Saving…', async () => {
        const res = await fetch(API + '/schedule/block/' + id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const data = await calJson(res); if (!res.ok) throw new Error(data.detail || 'Failed');
        await loadSchedule(window._sched.iso);
      });
    } catch (e) { showStatus('ebStatus', 'Error: ' + esc(e.message), 'error'); }
  }

  async function deleteBlock(id) {
    try {
      const res = await fetch(API + '/schedule/block/' + id, { method: 'DELETE' });
      const data = await calJson(res); if (!res.ok) throw new Error(data.detail || 'Failed');
      await loadSchedule(window._sched.iso);
    } catch (e) { showStatus('schedStatus', 'Error: ' + esc(e.message), 'error'); }
  }

  async function toggleDone(id, done) {
    try {
      const res = await fetch(API + '/schedule/block/' + id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ done: done }) });
      const data = await calJson(res); if (!res.ok) throw new Error(data.detail || 'Failed');
      await loadSchedule(window._sched.iso);
    } catch (e) { showStatus('schedStatus', 'Error: ' + esc(e.message), 'error'); }
  }

  async function addSlot(minute) {
    const m = (typeof minute === 'number') ? minute : 9 * 60;
    try {
      const res = await fetch(API + '/schedule/block', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: window._sched.iso, start_minute: m, duration_minutes: 30, title: 'New block' }) });
      const data = await calJson(res); if (!res.ok) throw new Error(data.detail || 'Failed');
      await loadSchedule(window._sched.iso);
      openBlockEditor(data.id);
    } catch (e) { showStatus('schedStatus', 'Error: ' + esc(e.message), 'error'); }
  }

  function addSlotFromClick(ev, winStart) {
    const minute = Math.round((winStart + ev.offsetY / SB_PXMIN) / 15) * 15;
    addSlot(Math.max(0, Math.min(1440 - 30, minute)));
  }

  async function generateDay(mode, btn) {
    const intent = (document.getElementById('schedIntent') || {}).value || '';
    try {
      await withBusy(btn, mode === 'fill_gaps' ? 'Filling…' : 'Generating…', async () => {
        const res = await fetch(API + '/schedule/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ date: window._sched.iso, intent: intent, mode: mode }) });
        const data = await calJson(res); if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
        await loadSchedule(window._sched.iso);
      });
    } catch (e) { showStatus('schedStatus', 'Error: ' + esc(e.message), 'error'); }
  }

  async function pushBlock(id, btn) {
    try {
      await withBusy(btn, 'Pushing…', async () => {
        const res = await fetch(API + '/schedule/block/' + id + '/push', { method: 'POST' });
        const data = await calJson(res); if (!res.ok) throw new Error(data.detail || 'Failed');
        showStatus('ebStatus', data.already ? 'Already on Outlook.' : 'Added to Outlook.', 'success');
        await loadSchedule(window._sched.iso);
      });
    } catch (e) { showStatus('ebStatus', 'Error: ' + esc(e.message), 'error'); }
  }

  async function pushAllSchedule(btn) {
    try {
      await withBusy(btn, 'Pushing…', async () => {
        const res = await fetch(API + '/schedule/push?date=' + encodeURIComponent(window._sched.iso), { method: 'POST' });
        const data = await calJson(res); if (!res.ok) throw new Error(data.detail || 'Failed');
        const failed = data.failed ? ' (' + data.failed + ' failed)' : '';
        showStatus('schedStatus', 'Pushed ' + data.pushed + ' block(s) to Outlook' + failed + '.', data.pushed ? 'success' : 'error');
        await loadSchedule(window._sched.iso);
      });
    } catch (e) { showStatus('schedStatus', 'Error: ' + esc(e.message), 'error'); }
  }

```

- [ ] **Step 6: Structural verification**

Run:
```bash
cd "C:/Users/Glen Lin/ai-task-scheduler"
grep -c 'function renderSchedule(' src/static/index.html      # 1
grep -c 'function loadSchedule(' src/static/index.html        # 1
grep -c 'id="scheduleBoard"' src/static/index.html            # 1
grep -c 'function planDay(' src/static/index.html             # 0
grep -c 'function pushPlan(' src/static/index.html            # 0
grep -c 'id="planIntent"' src/static/index.html               # 0
```
Expected: counts shown in comments.

- [ ] **Step 7: Commit**

```bash
git add src/static/index.html
git commit -m "feat: timeline schedule UI (tap-edit, done, lock, conflicts, now-line); remove plan-my-day card"
```

---

## Task 5: Remove the dead GET /daily-schedule

**Files:**
- Modify: `src/api/daily_schedule.py`

- [ ] **Step 1: Delete the ephemeral GET handler**

In `src/api/daily_schedule.py`, delete the entire `@router.get("")` handler `get_daily_schedule` (from the `# ── Main schedule endpoint ──` comment / the `@router.get("")` decorator through the end of that function — the final `return { ... "rules_today": ... } }` block). Also remove now-unused imports it alone used: `ChatGroq`, `ChatPromptTemplate`, `OutlookCalendarService`, `list_all_context`, `RecurringRule`, `json`, `asyncio` IF no other code in the file references them (the remaining `create_task_from_block` uses only `Task`, `User`, `current_user`, `get_db`, `BaseModel`, `select`/`AsyncSession`). Keep `create_task_from_block`, `CreateTaskFromBlockRequest`, and the router definition intact.

- [ ] **Step 2: Verify import + full suite**

Run:
```bash
./venv/Scripts/python.exe -c "import src.main; print('ok')"
./venv/Scripts/python.exe -m unittest tests.test_schedule tests.test_calendar tests.test_data_isolation tests.test_outlook_mail tests.test_crypto tests.test_email_routing
```
Expected: `ok` and all tests PASS (note `test_data_isolation` still references `CreateTaskFromBlockRequest`, which remains).

- [ ] **Step 3: Commit**

```bash
git add src/api/daily_schedule.py
git commit -m "chore: remove dead ephemeral GET /daily-schedule (superseded by /schedule)"
```

---

## Final verification

- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
- [ ] `./venv/Scripts/python.exe -m unittest discover -s tests` → all PASS.
- [ ] **Manual** (start server, sign in, open today):
  - Timeline renders with the day's Outlook events (dashed) and a now-line at the current time.
  - **Generate day** fills the timeline with blocks; **Fill the gaps** only adds around existing/locked blocks and meetings.
  - Tap a block → edit title/start/minutes/notes/lock → Save updates it; Delete removes it; → Outlook adds it (and shows ✓Outlook, no dupe on a second push).
  - Tick a block's checkbox → it greys out and the progress bar advances.
  - Create an overlapping block → both show the red conflict outline.
  - Tap empty timeline → a new 30-min block appears at that time and opens the editor.
  - Open a different (non-today) day → blocks for that day load and edit independently; no now-line.
