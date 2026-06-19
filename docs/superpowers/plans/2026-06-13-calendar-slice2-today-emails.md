# Calendar Home — Slice 2: Today's Emails Board — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On today's day-detail, batch-triage every unread email received today and present one combined board of proposed tasks/events, approved per-email (or all at once), which creates the Outlook events.

**Architecture:** Two new endpoints on the existing `calendar` router reuse the LangGraph workflow: `triage` runs `process_new_email` per unread-today email and aggregates each paused thread's proposal; `approve` resumes the selected threads (the executor creates events + tasks). The frontend adds a "Today's emails" board to `selectDay` when the day is today.

**Tech Stack:** Python 3.12, FastAPI, LangGraph (existing graph), Microsoft Graph, vanilla JS. Tests: stdlib `unittest`.

**Scope note:** Slice 2 of `docs/superpowers/specs/2026-06-13-calendar-home-design.md`. Approval is **per-email** (resume that email's thread); "approve all" selects every proposal. Plan-my-day is Slice 3.

---

## File Structure

- `src/api/calendar.py` — add `POST /calendar/today/emails/triage` + `POST /calendar/today/emails/approve` (+ `ApproveTodayRequest`).
- `src/static/index.html` — a "Today's emails" board in the today day-detail (`triageToday` / `approveToday`).

The triage/approve endpoints reuse `process_new_email` + `memory_checkpointer` + `build_agent_graph` (the same machinery the single-email flow and `/tasks/pending` + `/tasks/approve` already use).

---

## Task 1: Triage + approve endpoints

**Files:**
- Modify: `src/api/calendar.py`

- [ ] **Step 1: Add imports + request model**

In `src/api/calendar.py`, add to the imports:

```python
from typing import List
from pydantic import BaseModel
from langgraph.types import Command
from src.workflows.trigger import process_new_email, memory_checkpointer
from src.workflows.agent import build_agent_graph
```

After the `router = APIRouter(...)` line, add:

```python
class ApproveTodayRequest(BaseModel):
    thread_ids: List[str]
```

- [ ] **Step 2: Add the triage endpoint**

Append to `src/api/calendar.py`:

```python
@router.post("/today/emails/triage")
async def triage_today_emails(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Run every unread email received today through the workflow; aggregate the actionable proposals."""
    today = datetime.now(timezone.utc).date().isoformat()
    start_iso, end_iso = day_range(today)
    msgs = await OutlookMailService.get_messages_in_range(user, start_iso, end_iso, unread_only=True, max_fetch=60)

    app = build_agent_graph(memory_checkpointer)
    proposals, notifications, promotions = [], 0, 0
    for m in msgs[:15]:  # cap LLM work per run
        try:
            thread_id = await process_new_email(user.email, m["message_id"])
        except Exception as e:
            print(f"[triage] skipped {m.get('message_id')}: {e}")
            continue
        if not thread_id:
            continue
        snapshot = await app.aget_state({"configurable": {"thread_id": thread_id}})
        values = snapshot.values if snapshot else {}
        category = (values.get("classification") or {}).get("category", "promotion")
        if category == "actionable":
            analysis = values.get("analysis") or {}
            proposals.append({
                "thread_id": thread_id,
                "subject": m["subject"],
                "sender": m["sender"],
                "tasks": analysis.get("tasks", []),
                "events": analysis.get("events", []),
                "needs_reply": analysis.get("needs_reply", False),
            })
        elif category == "notification":
            notifications += 1
        else:
            promotions += 1

    return {"scanned": len(msgs), "proposals": proposals,
            "notifications": notifications, "promotions": promotions}
```

- [ ] **Step 3: Add the approve endpoint**

Append to `src/api/calendar.py`:

```python
@router.post("/today/emails/approve")
async def approve_today_emails(request: ApproveTodayRequest, user: User = Depends(current_user)):
    """Resume the chosen email threads — the executor creates their events + tasks."""
    app = build_agent_graph(memory_checkpointer)
    approved = 0
    for tid in request.thread_ids:
        config = {"configurable": {"thread_id": tid}}
        snapshot = await app.aget_state(config)
        if not (snapshot and snapshot.next):
            continue  # already resolved / unknown
        await app.ainvoke(Command(resume={"action": "approved", "feedback": ""}), config)
        approved += 1
    return {"approved": approved}
```

- [ ] **Step 4: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/api/calendar.py
git commit -m "feat: today's-emails batch triage + per-thread approve endpoints"
```

---

## Task 2: Frontend — Today's emails board

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Show the board on today's day-detail**

In `selectDay(iso)` (in the `<script>`), after the line that sets `let html = '<h2>' + esc(iso) + ...`, insert a today-only action card at the top of the detail. Add right after that `html` is initialized:

```javascript
      if (data.is_today) {
        html += '<div class="card" style="margin-bottom:14px"><div style="display:flex;align-items:center;justify-content:space-between;gap:10px"><strong style="font-family:var(--font-head);font-size:1.2rem">Today\'s emails</strong>'
          + '<button class="btn-sm" style="flex:0 0 auto" onclick="triageToday()">Process today\'s emails</button></div>'
          + '<div id="triageBoard"></div></div>';
      }
```

- [ ] **Step 2: Add the triage + approve JS**

In the `<script>`, just before the final `checkAuth();` call, add:

```javascript
  async function triageToday() {
    const board = document.getElementById('triageBoard');
    if (!board) return;
    board.innerHTML = '<p class="subtitle"><span class="spinner"></span>Reading today\'s inbox — this can take a moment…</p>';
    try {
      const res = await fetch(API + '/calendar/today/emails/triage', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      window._triageProposals = data.proposals || [];
      let html = '<p class="subtitle">Scanned ' + data.scanned + ' · ' + (data.proposals || []).length
        + ' actionable · ' + data.notifications + ' notifications · ' + data.promotions + ' promotions</p>';
      if (!(data.proposals || []).length) {
        board.innerHTML = html + '<p style="color:rgba(45,45,45,.5)">Nothing actionable to schedule.</p>';
        return;
      }
      html += data.proposals.map((p, i) => {
        const tasks = (p.tasks || []).map(t => '<div class="plan-item"><strong>' + esc(t.title) + '</strong>' + esc(t.description || '') + '</div>').join('');
        const events = (p.events || []).map(e => '<div class="plan-item"><strong>' + esc(e.summary) + '</strong>' + esc(fmtTime(e.start_time)) + ' – ' + esc(fmtTime(e.end_time)) + '</div>').join('');
        return '<div class="plan-item" style="background:var(--paper)"><label style="display:flex;gap:8px;align-items:flex-start;cursor:pointer">'
          + '<input type="checkbox" class="triage-pick" data-i="' + i + '" checked style="flex:0 0 auto;margin-top:4px">'
          + '<span style="flex:1"><strong>' + esc(p.subject) + '</strong><span style="font-size:.85rem;color:rgba(45,45,45,.6)">' + esc(p.sender) + '</span>'
          + '<div class="section-header">Tasks</div>' + (tasks || '<span style="color:rgba(45,45,45,.5)">none</span>')
          + '<div class="section-header">Events</div>' + (events || '<span style="color:rgba(45,45,45,.5)">none</span>')
          + '</span></label></div>';
      }).join('');
      html += '<div class="row" style="margin-top:12px"><button onclick="approveToday()">Approve &amp; schedule selected</button></div>';
      html += '<div id="triageStatus" class="status hidden"></div>';
      board.innerHTML = html;
    } catch (e) {
      board.innerHTML = '<div class="status error">Error: ' + esc(e.message) + '</div>';
    }
  }

  async function approveToday() {
    const picks = Array.from(document.querySelectorAll('.triage-pick')).filter(c => c.checked);
    const ids = picks.map(c => (window._triageProposals[+c.dataset.i] || {}).thread_id).filter(Boolean);
    if (!ids.length) { showStatus('triageStatus', 'Select at least one email.', 'error'); return; }
    showStatus('triageStatus', 'Scheduling…', 'info');
    try {
      const res = await fetch(API + '/calendar/today/emails/approve', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_ids: ids })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      showStatus('triageStatus', 'Scheduled ' + data.approved + ' email(s) to your calendar.', 'success');
      renderMonth();
    } catch (e) {
      showStatus('triageStatus', 'Error: ' + esc(e.message), 'error');
    }
  }
```

- [ ] **Step 3: Structural verification**

- `grep -c "function triageToday(" src/static/index.html` → `1`
- `grep -c "function approveToday(" src/static/index.html` → `1`
- `grep -c "/calendar/today/emails/triage" src/static/index.html` → `1`
- `grep -c "/calendar/today/emails/approve" src/static/index.html` → `1`

- [ ] **Step 4: Commit**

```bash
git add src/static/index.html
git commit -m "feat: today's-emails combined review board"
```

---

## Final verification

### Automated
- [ ] `./venv/Scripts/python.exe -m unittest tests.test_calendar tests.test_outlook_mail tests.test_outlook_auth tests.test_crypto tests.test_data_isolation tests.test_email_sections tests.test_email_routing -v` → all PASS (no new unit tests; existing suite still green).
- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

### Manual (signed in)
- [ ] Open the calendar, click **today** → a **Today's emails** card appears with a "Process today's emails" button.
- [ ] Click it → it scans today's unread, shows a count line and a board of actionable emails, each with its proposed tasks/events and a checkbox (checked by default).
- [ ] Uncheck any you don't want, click **Approve & schedule selected** → confirms how many were scheduled; the month grid refreshes (event dots update).
- [ ] Check your Outlook calendar → the approved events are there.
- [ ] A day with no actionable unread email shows "Nothing actionable to schedule."
