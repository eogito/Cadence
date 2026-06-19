# Calendar Home — Slice 3: Plan My Day — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Checkbox (`- [ ]`) steps.

**Goal:** On today's day-detail, a "Plan my day" card takes a free-text intent (+ Focused/Light/Catch-up presets), generates a schedule from the intent + today's calendar/tasks/rules/context, and lets the user push timed blocks to Outlook as real events.

**Architecture:** Extend the existing `GET /daily-schedule` generator with an optional `intent` query param (folded into the LLM prompt). Add `POST /calendar/schedule/push` that creates Outlook events from a list of `{summary, start_time, end_time}` (reuses `OutlookCalendarService.create_event`). Frontend adds the card to `selectDay` (today only) and computes ISO times from the generated blocks.

**Tech:** FastAPI, Groq, Microsoft Graph, vanilla JS. Tests: stdlib `unittest`. Slice 3 of `docs/superpowers/specs/2026-06-13-calendar-home-design.md` (final slice).

---

## Task 1: Backend — intent param + push endpoint

**Files:** `src/api/daily_schedule.py`, `src/api/calendar.py`

- [ ] **Step 1: Add `intent` to the daily-schedule generator**

In `src/api/daily_schedule.py`, the `get_daily_schedule` handler (`@router.get("")`): add an `intent: str = ""` query parameter to its signature (alongside `user`/`db`). Then in the `user_msg` string (the block that starts `"Today is " + today_label ...`), insert the intent right before the final `"Generate a complete daily schedule..."` line:

```python
        + ("USER'S INTENT FOR TODAY: " + intent + "\n\n" if intent.strip() else "")
        + "Generate a complete daily schedule with specific time blocks, importance ratings, "
        "and realistic duration estimates for each item. Respect the user's stated intent for the day."
```

(Replace the existing final two-line `"Generate a complete daily schedule ..."` fragment with the version above so the intent is appended just before it.)

- [ ] **Step 2: Add the push endpoint to `calendar.py`**

Append to `src/api/calendar.py` (the `ApproveTodayRequest` import block already has `BaseModel`/`List`):

```python
class ScheduleBlockPush(BaseModel):
    summary: str
    start_time: str  # ISO 8601
    end_time: str    # ISO 8601


class PushScheduleRequest(BaseModel):
    blocks: List[ScheduleBlockPush]


@router.post("/schedule/push")
async def push_schedule(request: PushScheduleRequest, user: User = Depends(current_user)):
    """Create Outlook calendar events from chosen schedule blocks."""
    created = []
    for b in request.blocks:
        try:
            res = await OutlookCalendarService.create_event(user, b.summary, b.start_time, b.end_time)
            created.append({"summary": b.summary, "link": res.get("link")})
        except Exception as e:
            print(f"[push] failed '{b.summary}': {e}")
    return {"created": len(created), "events": created}
```

- [ ] **Step 3: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/api/daily_schedule.py src/api/calendar.py
git commit -m "feat: plan-my-day intent + push schedule blocks to Outlook"
```

---

## Task 2: Frontend — Plan my day card

**Files:** `src/static/index.html`

- [ ] **Step 1: Add the card to today's day-detail**

In `selectDay(iso)`, in the `if (data.is_today) { ... }` block (the one that adds the Today's-emails card), append a second card right after it (inside the same `if`):

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
```

- [ ] **Step 2: Add the plan JS** (before the final `checkAuth();`)

```javascript
  function setIntent(t) { const el = document.getElementById('planIntent'); if (el) el.value = t; }

  function planTimeToIso(timeStr, durationMin) {
    const m = (timeStr || '').match(/(\d{1,2}):(\d{2})\s*(AM|PM)?/i);
    if (!m) return null;
    let h = parseInt(m[1], 10); const min = parseInt(m[2], 10); const ap = (m[3] || '').toUpperCase();
    if (ap === 'PM' && h < 12) h += 12; if (ap === 'AM' && h === 12) h = 0;
    const d = new Date(); d.setHours(h, min, 0, 0);
    const end = new Date(d.getTime() + (durationMin || 30) * 60000);
    const iso = x => x.getFullYear() + '-' + String(x.getMonth()+1).padStart(2,'0') + '-' + String(x.getDate()).padStart(2,'0') + 'T' + String(x.getHours()).padStart(2,'0') + ':' + String(x.getMinutes()).padStart(2,'0') + ':00';
    return { start: iso(d), end: iso(end) };
  }

  async function planDay() {
    const board = document.getElementById('planBoard');
    const intent = (document.getElementById('planIntent') || {}).value || '';
    board.innerHTML = '<p class="subtitle"><span class="spinner"></span>Planning your day…</p>';
    try {
      const res = await fetch(API + '/daily-schedule?intent=' + encodeURIComponent(intent));
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      window._planBlocks = data.blocks || [];
      let html = '<div class="section-header">' + esc(data.date_label || 'Today') + '</div>';
      html += '<p class="subtitle">' + esc(data.summary || '') + '</p>';
      html += (data.blocks || []).map(b => '<div class="plan-item"><strong>' + esc(b.time) + ' · ' + esc(b.title) + '</strong>'
        + '<span style="font-size:.82rem;color:rgba(45,45,45,.55)">' + esc(b.rationale || '') + '</span></div>').join('');
      html += '<div class="row" style="margin-top:12px"><button onclick="pushPlan()">Add timed blocks to Outlook</button></div>';
      html += '<div id="planStatus" class="status hidden"></div>';
      board.innerHTML = html;
    } catch (e) {
      board.innerHTML = '<div class="status error">Error: ' + esc(e.message) + '</div>';
    }
  }

  async function pushPlan() {
    const blocks = (window._planBlocks || []).map(b => {
      const t = planTimeToIso(b.time, b.duration_minutes);
      return t ? { summary: b.title, start_time: t.start, end_time: t.end } : null;
    }).filter(Boolean);
    if (!blocks.length) { showStatus('planStatus', 'No timed blocks to push (only items with a clock time can be added).', 'error'); return; }
    showStatus('planStatus', 'Adding to Outlook…', 'info');
    try {
      const res = await fetch(API + '/calendar/schedule/push', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ blocks })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      showStatus('planStatus', 'Added ' + data.created + ' block(s) to your Outlook calendar.', 'success');
      renderMonth();
    } catch (e) {
      showStatus('planStatus', 'Error: ' + esc(e.message), 'error');
    }
  }
```

- [ ] **Step 3: Structural verification**

- `grep -c "function planDay(" src/static/index.html` → 1
- `grep -c "function pushPlan(" src/static/index.html` → 1
- `grep -c "/calendar/schedule/push" src/static/index.html` → 1
- `grep -c "id=\"planIntent\"" src/static/index.html` → 1

- [ ] **Step 4: Commit**

```bash
git add src/static/index.html
git commit -m "feat: plan-my-day card with intent presets + push to Outlook"
```

---

## Final verification

- [ ] `./venv/Scripts/python.exe -m unittest tests.test_calendar tests.test_outlook_mail tests.test_outlook_auth tests.test_crypto tests.test_data_isolation tests.test_email_sections tests.test_email_routing -v` → all PASS.
- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
- [ ] Manual: today → **Plan my day** → type/preset an intent → **Generate** → a timeline appears → **Add timed blocks to Outlook** → events with clock times land in Outlook; the grid refreshes.
