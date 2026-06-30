# Multi-day Prep Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user click an upcoming Outlook event and auto-distribute study/prep blocks across the days before it, with a preview/confirm step and one-click removal of the whole plan.

**Architecture:** A pure, deterministic distributor (`prep_planner.py`) splits a time budget across days (ramping up toward the date) and packs each day's share into free gaps. Three `/schedule` endpoints (preview/commit/delete) drive it; blocks are tagged with a `plan_group` for set-removal. Frontend adds a "Plan prep" button to Outlook event rows and a removal button to the block editor.

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy, Microsoft Graph, vanilla JS. Tests: stdlib `unittest`. No LLM (distribution is arithmetic).

Spec: `docs/superpowers/specs/2026-06-29-prep-planner-design.md`.

---

## File Structure

- **Modify** `src/models/schedule_block.py` — add `plan_group` column.
- **Modify** `src/main.py` — `ALTER TABLE … ADD COLUMN IF NOT EXISTS plan_group`.
- **Create** `src/services/prep_planner.py` — `allocate_per_day`, `place_sessions`.
- **Modify** `src/api/schedule.py` — `_block_dict` adds `plan_group`; prep-plan request models + 3 endpoints.
- **Modify** `src/static/index.html` — "Plan prep" button on event rows + dialog + preview/commit JS; "Remove prep plan" in the block editor.
- **Create** `tests/test_prep_planner.py`.

---

## Task 1: plan_group column + migration

**Files:**
- Modify: `src/models/schedule_block.py`, `src/main.py`, `src/api/schedule.py`
- Test: `tests/test_prep_planner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prep_planner.py`:

```python
"""Tests for the multi-day prep planner (stdlib unittest)."""
import unittest


class ModelTests(unittest.TestCase):
    def test_schedule_blocks_has_plan_group(self):
        from src.models.schedule_block import ScheduleBlock
        self.assertIn("plan_group", ScheduleBlock.__table__.columns)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it, expect failure**

Run: `./venv/Scripts/python.exe -m unittest tests.test_prep_planner -v`
Expected: FAIL (`'plan_group' not found`).

- [ ] **Step 3: Add the column**

In `src/models/schedule_block.py`, add this line immediately after the `source = Column(...)` line:

```python
    plan_group = Column(String(120), nullable=True)         # groups blocks from one prep plan
```

- [ ] **Step 4: Add the migration**

In `src/main.py`, find:

```python
        # create_all does not add columns to pre-existing tables; backfill new columns idempotently
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT 'UTC'"))
```

Add immediately after it:

```python
        await conn.execute(text("ALTER TABLE schedule_blocks ADD COLUMN IF NOT EXISTS plan_group VARCHAR(120)"))
```

- [ ] **Step 5: Expose it in `_block_dict`**

In `src/api/schedule.py`, in `_block_dict`, change the return dict's last line from:

```python
        "done": b.done, "locked": b.locked, "pushed": bool(b.outlook_event_id), "source": b.source,
    }
```

to:

```python
        "done": b.done, "locked": b.locked, "pushed": bool(b.outlook_event_id), "source": b.source,
        "plan_group": b.plan_group,
    }
```

- [ ] **Step 6: Run the test + import**

Run:
```bash
./venv/Scripts/python.exe -m unittest tests.test_prep_planner -v
./venv/Scripts/python.exe -c "import src.main; print('ok')"
```
Expected: PASS and `ok`.

- [ ] **Step 7: Commit**

```bash
git add src/models/schedule_block.py src/main.py src/api/schedule.py tests/test_prep_planner.py
git commit -m "feat: schedule_blocks.plan_group column + migration"
```

---

## Task 2: prep_planner pure functions

**Files:**
- Create: `src/services/prep_planner.py`
- Test: `tests/test_prep_planner.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_prep_planner.py`, insert ABOVE the `if __name__ == "__main__":` block:

```python
class AllocateTests(unittest.TestCase):
    def test_ramps_up(self):
        from src.services.prep_planner import allocate_per_day
        # 4 days, 600 min, no cap: weights 1,2,3,4 (sum 10) -> 60,120,180,240
        self.assertEqual(allocate_per_day(4, 600, 1000, ramp=True), [60, 120, 180, 240])

    def test_respects_cap(self):
        from src.services.prep_planner import allocate_per_day
        self.assertTrue(all(x <= 120 for x in allocate_per_day(4, 600, 120, ramp=True)))

    def test_even_when_no_ramp(self):
        from src.services.prep_planner import allocate_per_day
        self.assertEqual(allocate_per_day(3, 180, 1000, ramp=False), [60, 60, 60])

    def test_zero_guards(self):
        from src.services.prep_planner import allocate_per_day
        self.assertEqual(allocate_per_day(0, 600, 60), [])
        self.assertEqual(allocate_per_day(3, 0, 60), [0, 0, 0])


class PlaceSessionsTests(unittest.TestCase):
    def test_avoids_busy_and_splits(self):
        from src.services.prep_planner import place_sessions
        # window 8:00-12:00 (480-720); busy 9:00-10:00 (540-600); want 120, max 90, min 30
        s = place_sessions(120, [(540, 600)], window=(480, 720), max_session=90, min_session=30)
        self.assertEqual(s, [(480, 60), (600, 60)])

    def test_shortfall_when_gaps_small(self):
        from src.services.prep_planner import place_sessions
        s = place_sessions(120, [(510, 720)], window=(480, 720), max_session=90, min_session=30)
        self.assertEqual(s, [(480, 30)])

    def test_returns_empty_below_min(self):
        from src.services.prep_planner import place_sessions
        self.assertEqual(place_sessions(20, [], window=(480, 720), min_session=30), [])
```

- [ ] **Step 2: Run, expect failure**

Run: `./venv/Scripts/python.exe -m unittest tests.test_prep_planner.AllocateTests tests.test_prep_planner.PlaceSessionsTests -v`
Expected: FAIL (`ModuleNotFoundError: src.services.prep_planner`).

- [ ] **Step 3: Implement**

Create `src/services/prep_planner.py`:

```python
"""Deterministic multi-day prep-plan distribution (pure, no LLM)."""
from typing import List, Tuple
from src.services.schedule_ai import free_gaps


def allocate_per_day(day_count: int, total_minutes: int, daily_cap: int, ramp: bool = True) -> List[int]:
    """Minutes to study on each of `day_count` days (index 0 = earliest).

    Ramps up toward the last day when `ramp` (later days weighted heavier); each day is
    capped at `daily_cap`; each value is floored to a 15-minute increment. The sum is at
    most `total_minutes` (floor + cap may leave a little unallocated — the caller reports it).
    """
    if day_count <= 0 or total_minutes <= 0 or daily_cap <= 0:
        return [0] * max(0, day_count)
    weights = list(range(1, day_count + 1)) if ramp else [1] * day_count
    total_weight = sum(weights)
    alloc = []
    for w in weights:
        minutes = int((total_minutes * w / total_weight) / 15) * 15  # floor to 15-min
        alloc.append(min(minutes, daily_cap))
    return alloc


def place_sessions(minutes: int, busy: List[Tuple[int, int]],
                   window: Tuple[int, int] = (8 * 60, 22 * 60),
                   max_session: int = 90, min_session: int = 30) -> List[Tuple[int, int]]:
    """Pack `minutes` of work into the free gaps of `window`, avoiding `busy`.

    Returns (start_minute, duration) sessions of length min_session..max_session, in order.
    If the gaps can't hold the full amount, returns what fits (the rest is shortfall).
    """
    if minutes < min_session:
        return []
    gaps = free_gaps(window[0], window[1], list(busy))
    sessions: List[Tuple[int, int]] = []
    remaining = minutes
    for gs, ge in gaps:
        cursor = gs
        while remaining >= min_session and ge - cursor >= min_session:
            dur = min(max_session, remaining, ge - cursor)
            sessions.append((cursor, dur))
            cursor += dur
            remaining -= dur
        if remaining < min_session:
            break
    return sessions
```

- [ ] **Step 4: Run tests, expect pass**

Run: `./venv/Scripts/python.exe -m unittest tests.test_prep_planner -v`
Expected: PASS (all classes).

- [ ] **Step 5: Commit**

```bash
git add src/services/prep_planner.py tests/test_prep_planner.py
git commit -m "feat: prep_planner allocate_per_day + place_sessions (pure)"
```

---

## Task 3: prep-plan endpoints

**Files:**
- Modify: `src/api/schedule.py`
- Test: `tests/test_prep_planner.py`

- [ ] **Step 1: Add imports + request models + endpoints**

In `src/api/schedule.py`, add to the existing `from src.services...` import area:

```python
from src.services.prep_planner import allocate_per_day, place_sessions
```

Append at the END of `src/api/schedule.py`:

```python
class PrepPreviewRequest(BaseModel):
    event_title: str
    exam_date: str            # YYYY-MM-DD
    total_minutes: int
    daily_cap_minutes: int = 120


class PrepCommitBlock(BaseModel):
    date: str
    start_minute: int
    duration_minutes: int
    title: str


class PrepCommitRequest(BaseModel):
    plan_label: str
    blocks: list[PrepCommitBlock]


@router.post("/prep-plan/preview")
async def prep_preview(req: PrepPreviewRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        exam = datetime.strptime(req.exam_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="exam_date must be YYYY-MM-DD")
    if req.total_minutes <= 0 or req.daily_cap_minutes <= 0:
        raise HTTPException(status_code=400, detail="total_minutes and daily_cap_minutes must be positive")

    tz = user_tz(user)
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(tz)).date() if _safe_zone(tz) else datetime.now(timezone.utc).date()
    days = []
    d = today + timedelta(days=1)
    while d < exam:
        days.append(d)
        d += timedelta(days=1)

    if not days:
        return {"plan_label": req.event_title, "requested_minutes": req.total_minutes,
                "placed_minutes": 0, "days": [], "shortfall_minutes": req.total_minutes}

    alloc = allocate_per_day(len(days), req.total_minutes, req.daily_cap_minutes, ramp=True)
    out_days, placed = [], 0
    for i, day in enumerate(days):
        iso = day.isoformat()
        blk_res = await db.execute(
            select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
        )
        busy = [(b.start_minute, b.start_minute + b.duration_minutes) for b in blk_res.scalars().all()]
        try:
            s_iso, e_iso = local_day_range(iso, tz)
            events = await OutlookCalendarService.get_events_in_range(user, s_iso, e_iso, prefer_tz=tz)
            for e in events:
                es, ee = _iso_to_minute(e.get("start"), tz), _iso_to_minute(e.get("end"), tz)
                if es is not None and ee is not None:
                    busy.append((es, ee))
        except PermissionError:
            raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
        except Exception as ex:  # noqa: BLE001 — one bad day shouldn't sink the whole preview
            print(f"[prep] events fetch failed for {iso}: {ex}")
        sessions = place_sessions(alloc[i], busy)
        if sessions:
            out_days.append({"date": iso, "sessions": [
                {"start_minute": st, "duration_minutes": du, "title": f"Study: {req.event_title}"}
                for st, du in sessions
            ]})
            placed += sum(du for _, du in sessions)

    return {"plan_label": req.event_title, "requested_minutes": req.total_minutes,
            "placed_minutes": placed, "days": out_days,
            "shortfall_minutes": max(0, req.total_minutes - placed)}


@router.post("/prep-plan/commit")
async def prep_commit(req: PrepCommitRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    created = 0
    for blk in req.blocks:
        db.add(ScheduleBlock(
            user_id=user.id, day=_parse_day(blk.date), start_minute=blk.start_minute,
            duration_minutes=max(5, blk.duration_minutes), title=blk.title,
            category="suggested", source="ai", plan_group=req.plan_label,
        ))
        created += 1
    await db.commit()
    return {"created": created}


@router.delete("/prep-plan")
async def prep_delete(label: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.plan_group == label)
    )
    blocks = res.scalars().all()
    for b in blocks:
        await db.delete(b)
    await db.commit()
    return {"deleted": len(blocks)}


def _safe_zone(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False
```

- [ ] **Step 2: Add data-isolation tests**

In `tests/test_prep_planner.py`, insert ABOVE the `if __name__ == "__main__":` block:

```python
class RequestModelTests(unittest.TestCase):
    def test_requests_have_no_email_field(self):
        from src.api.schedule import PrepPreviewRequest, PrepCommitRequest
        for model in (PrepPreviewRequest, PrepCommitRequest):
            self.assertNotIn("email", model.model_fields)
            self.assertNotIn("user_email", model.model_fields)
```

- [ ] **Step 3: Verify import + suites**

Run:
```bash
./venv/Scripts/python.exe -c "import src.main; print('ok')"
./venv/Scripts/python.exe -m unittest tests.test_prep_planner tests.test_schedule
```
Expected: `ok` and all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/api/schedule.py tests/test_prep_planner.py
git commit -m "feat: prep-plan preview/commit/delete endpoints"
```

---

## Task 4: Frontend — Plan prep button + dialog

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Add CSS**

Find the `.ag-now::before, .ag-now::after { ... }` CSS rule. Immediately AFTER it, add:

```css
    .ag-prep { flex:0 0 auto; align-self:center; font-size:.68rem; padding:3px 7px; }
    .prep-day { margin-top:8px; }
    .prep-day strong { font-family:var(--font-head); font-size:.9rem; }
```

- [ ] **Step 2: Add the "Plan prep" button to Outlook event rows**

In `renderSchedule`, find the event-row line:

```javascript
        rows += '<div class="ag-row ev"><span class="ag-time">' + esc(sbMinToHHMM(e.s)) + '</span>'
          + '<span class="ag-body"><strong>📅 ' + esc(e.summary || 'Busy') + '</strong>'
          + '<span class="ag-sub">' + esc(sbMinToHHMM(e.s)) + '–' + esc(sbMinToHHMM(e.e)) + ' · Outlook</span></span></div>';
```

Replace with:

```javascript
        rows += '<div class="ag-row ev"><span class="ag-time">' + esc(sbMinToHHMM(e.s)) + '</span>'
          + '<span class="ag-body"><strong>📅 ' + esc(e.summary || 'Busy') + '</strong>'
          + '<span class="ag-sub">' + esc(sbMinToHHMM(e.s)) + '–' + esc(sbMinToHHMM(e.e)) + ' · Outlook</span></span>'
          + '<button class="btn-sm ag-prep" data-title="' + esc(e.summary || 'Event') + '" data-date="' + S.iso + '" onclick="event.stopPropagation();openPrepFromBtn(this)">📚 Plan prep</button></div>';
```

- [ ] **Step 3: Add the prep dialog mount**

In `renderSchedule`, find:

```javascript
    html += '<div class="sb-pop" id="schedPopover"></div>';
    board.innerHTML = html;
```

Replace with:

```javascript
    html += '<div class="sb-pop" id="schedPopover"></div>';
    html += '<div class="sb-pop" id="prepDialog"></div>';
    board.innerHTML = html;
```

- [ ] **Step 4: Add the prep JS** (insert immediately BEFORE the final `checkAuth();` line)

```javascript
  function openPrepFromBtn(btn) { openPrepDialog(btn.dataset.title, btn.dataset.date); }

  function openPrepDialog(title, examDate) {
    window._prepTarget = { title: title, examDate: examDate };
    const box = document.getElementById('prepDialog');
    box.innerHTML = '<strong style="font-family:var(--font-head)">Plan prep for "' + esc(title) + '"</strong>'
      + '<p class="subtitle" style="margin:4px 0 8px">On ' + esc(examDate) + ' — study time spreads across the days before it.</p>'
      + '<div class="r"><div style="flex:1"><label>Total hours</label><input id="prepHours" type="number" value="6" min="0.5" step="0.5"></div>'
      + '<div style="flex:1"><label>Max hrs/day</label><input id="prepCap" type="number" value="2" min="0.5" step="0.5"></div></div>'
      + '<div class="r" style="margin-top:9px"><button class="btn-sm" onclick="prepPreview(this)">Preview plan</button>'
      + '<button class="btn-sm" onclick="closePrep()">Cancel</button></div>'
      + '<div id="prepBoard"></div><div id="prepStatus" class="status hidden"></div>';
    box.classList.add('open');
  }

  function closePrep() { const b = document.getElementById('prepDialog'); if (b) b.classList.remove('open'); }

  async function prepPreview(btn) {
    const t = window._prepTarget; if (!t) return;
    const totalMin = Math.round((parseFloat(document.getElementById('prepHours').value) || 0) * 60);
    const capMin = Math.round((parseFloat(document.getElementById('prepCap').value) || 0) * 60);
    const board = document.getElementById('prepBoard');
    try {
      await withBusy(btn, 'Planning…', async () => {
        const res = await fetch(API + '/schedule/prep-plan/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ event_title: t.title, exam_date: t.examDate, total_minutes: totalMin, daily_cap_minutes: capMin }) });
        const data = await calJson(res); if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
        window._prepProposal = data;
        if (!data.days.length) { board.innerHTML = '<p class="subtitle" style="margin-top:8px">No free time to schedule prep before this date.</p>'; return; }
        let html = data.days.map(d => '<div class="prep-day"><strong>' + esc(d.date) + '</strong>'
          + d.sessions.map(s => '<div class="ag-sub">• ' + esc(sbMinToHHMM(s.start_minute)) + ' · ' + s.duration_minutes + 'm</div>').join('') + '</div>').join('');
        const hrs = Math.round(data.placed_minutes / 60 * 10) / 10;
        const sh = data.shortfall_minutes ? ' (couldn\'t fit ' + (Math.round(data.shortfall_minutes / 60 * 10) / 10) + 'h)' : '';
        html += '<button class="btn-sm" style="margin-top:10px" onclick="prepCommit(this)">Add ' + hrs + 'h to my schedule' + sh + '</button>';
        board.innerHTML = html;
      });
    } catch (e) { showStatus('prepStatus', 'Error: ' + esc(e.message), 'error'); }
  }

  async function prepCommit(btn) {
    const p = window._prepProposal; if (!p) return;
    const blocks = [];
    p.days.forEach(d => d.sessions.forEach(s => blocks.push({ date: d.date, start_minute: s.start_minute, duration_minutes: s.duration_minutes, title: s.title })));
    try {
      await withBusy(btn, 'Adding…', async () => {
        const res = await fetch(API + '/schedule/prep-plan/commit', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plan_label: p.plan_label, blocks: blocks }) });
        const data = await calJson(res); if (!res.ok) throw new Error(data.detail || 'Failed');
        closePrep();
        showStatus('schedStatus', 'Added ' + data.created + ' study block(s).', 'success');
        await loadSchedule(window._sched.iso);
      });
    } catch (e) { showStatus('prepStatus', 'Error: ' + esc(e.message), 'error'); }
  }

```

- [ ] **Step 5: Structural verification**

Run:
```bash
cd "C:/Users/Glen Lin/ai-task-scheduler"
grep -c "function openPrepDialog(" src/static/index.html   # 1
grep -c "function prepPreview(" src/static/index.html      # 1
grep -c "function prepCommit(" src/static/index.html       # 1
grep -c "prep-plan/preview" src/static/index.html          # 1
```
Expected counts as shown. Then JS syntax check:
```bash
node --check <(./venv/Scripts/python.exe -c "import re;print(max(re.findall(r'<script>(.*?)</script>',open('src/static/index.html',encoding='utf-8').read(),re.S),key=len))") && echo "JS OK"
```
Expected: `JS OK` (if `node` is unavailable, skip this line).

- [ ] **Step 6: Commit**

```bash
git add src/static/index.html
git commit -m "feat: Plan-prep button on Outlook events + preview/commit dialog"
```

---

## Task 5: Remove-prep-plan in the block editor

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Add the removal button to the editor**

In `openBlockEditor`, find:

```javascript
      + '<button class="btn-sm" onclick="pushBlock(\'' + id + '\',this)">→ Outlook</button></div>'
      + '<div id="ebStatus" class="status hidden"></div>';
```

Replace with:

```javascript
      + '<button class="btn-sm" onclick="pushBlock(\'' + id + '\',this)">→ Outlook</button></div>'
      + (b.plan_group ? '<button class="btn-sm" style="color:var(--accent);margin-top:8px" onclick="removePrepPlan(\'' + id + '\')">Remove entire study plan</button>' : '')
      + '<div id="ebStatus" class="status hidden"></div>';
```

- [ ] **Step 2: Add the `removePrepPlan` function** (insert immediately BEFORE the final `checkAuth();` line)

```javascript
  async function removePrepPlan(blockId) {
    const b = (window._sched.blocks || []).find(x => x.id === blockId);
    if (!b || !b.plan_group) return;
    if (!confirm('Remove the whole "' + b.plan_group + '" study plan from every day?')) return;
    try {
      const res = await fetch(API + '/schedule/prep-plan?label=' + encodeURIComponent(b.plan_group), { method: 'DELETE' });
      const data = await calJson(res); if (!res.ok) throw new Error(data.detail || 'Failed');
      showStatus('schedStatus', 'Removed ' + data.deleted + ' study block(s).', 'success');
      await loadSchedule(window._sched.iso);
    } catch (e) { showStatus('ebStatus', 'Error: ' + esc(e.message), 'error'); }
  }

```

- [ ] **Step 3: Verify + commit**

Run:
```bash
cd "C:/Users/Glen Lin/ai-task-scheduler"
grep -c "function removePrepPlan(" src/static/index.html    # 1
./venv/Scripts/python.exe -c "import src.main; print('ok')"
```
Expected: `1` and `ok`.

```bash
git add src/static/index.html
git commit -m "feat: remove an entire prep plan from the block editor"
```

---

## Final verification

- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
- [ ] `./venv/Scripts/python.exe -m unittest discover -s tests` → all PASS.
- [ ] **Manual** (signed in): open a future day that has an Outlook event → click **📚 Plan prep** → set hours → **Preview** shows sessions spread across the days before, ramping up → **Add to my schedule** → study blocks appear on those days (titled `Study: …`) → open one → **Remove entire study plan** clears them all.
