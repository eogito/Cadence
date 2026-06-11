# Email Classification & Review Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify each processed email into actionable / notification / promotion, extract tasks+drafts only for actionable mail, persist tasks only on approval, surface the full email body, and render event times in local form.

**Architecture:** A LangGraph classify-first pipeline. A `classifier` node buckets the email; routing sends promotions to END (label only), notifications to a pause-and-dismiss node, and actionable mail to the existing extractor → human review → executor path. Task persistence moves from the extractor into the executor so tasks are written only on approval. The frontend renders category-aware results with a collapsible full-email panel and local time formatting.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, langchain-groq (Groq `llama-3.1-8b-instant`), SQLAlchemy async, vanilla JS frontend. Tests use the stdlib `unittest` runner (pytest is not installed). Run tests with `./venv/Scripts/python.exe -m unittest <module>`.

---

## File Structure

- `src/workflows/state.py` — add `EmailClassification`, add `needs_task` to `EmailAnalysis`, add `classification` to `AgentState`.
- `src/workflows/agent.py` — add `_empty_body_classification`, `classify_email`, `route_after_classification`, `notification_review`; refactor `extract_and_plan` (drop eager persistence + empty guard, add `needs_task` prompt); move task persistence into `execute_plan`; rewire `build_agent_graph`.
- `src/api/approval.py` — make `get_pending_plan` category-aware and return the full email.
- `src/static/index.html` — add `fmtTime`, branch `loadPlan` on category, full-email panel, notification card, promotion label, dismiss action.
- `tests/test_email_routing.py` — unit tests for the pure routing/guard functions and graph wiring.

---

## Task 1: Classification schema and state

**Files:**
- Modify: `src/workflows/state.py`
- Test: `tests/test_email_routing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_email_routing.py`:

```python
"""Tests for email classification schema, routing, and graph wiring (stdlib unittest)."""
import unittest

from src.workflows.state import EmailClassification, EmailAnalysis


class SchemaTests(unittest.TestCase):
    def test_classification_defaults(self):
        c = EmailClassification(category="notification")
        self.assertEqual(c.category, "notification")
        self.assertEqual(c.reason, "")

    def test_analysis_has_needs_task(self):
        a = EmailAnalysis()
        self.assertFalse(a.needs_task)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_routing -v`
Expected: FAIL — `ImportError: cannot import name 'EmailClassification'`.

- [ ] **Step 3: Write minimal implementation**

In `src/workflows/state.py`, change the imports line `from typing import TypedDict, List, Optional` to add `Literal`:

```python
from typing import TypedDict, List, Optional, Literal
```

Add this class after `EmailAnalysis` (after line 24):

```python
class EmailClassification(BaseModel):
    category: Literal["actionable", "notification", "promotion"] = Field(
        description="Primary triage bucket for the email"
    )
    reason: str = Field(default="", description="One-line justification for the chosen category")
```

In `EmailAnalysis`, add a `needs_task` field directly after the `is_actionable` field (line 19):

```python
    needs_task: bool = Field(default=False, description="True only if there is a clear task AND a date warranting a calendar event")
```

In `AgentState`, add a `classification` field directly after the `analysis` field (line 34):

```python
    classification: Optional[dict]  # Will store the EmailClassification dict
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_routing -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/workflows/state.py tests/test_email_routing.py
git commit -m "feat: add EmailClassification schema and needs_task field"
```

---

## Task 2: Empty-body guard and classification routing

**Files:**
- Modify: `src/workflows/agent.py`
- Test: `tests/test_email_routing.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_email_routing.py` (add imports at top: `from langgraph.graph import END` and `from src.workflows import agent`):

```python
from langgraph.graph import END
from src.workflows import agent


class RoutingTests(unittest.TestCase):
    def test_empty_body_classified_as_promotion(self):
        self.assertEqual(
            agent._empty_body_classification({"email_content": "   "}),
            {"category": "promotion", "reason": "Email had no readable text content."},
        )

    def test_non_empty_body_returns_none(self):
        self.assertIsNone(agent._empty_body_classification({"email_content": "Hi there"}))

    def test_route_actionable(self):
        state = {"classification": {"category": "actionable"}}
        self.assertEqual(agent.route_after_classification(state), "extract")

    def test_route_notification(self):
        state = {"classification": {"category": "notification"}}
        self.assertEqual(agent.route_after_classification(state), "notify")

    def test_route_promotion_ends(self):
        state = {"classification": {"category": "promotion"}}
        self.assertEqual(agent.route_after_classification(state), END)

    def test_route_missing_classification_ends(self):
        self.assertEqual(agent.route_after_classification({}), END)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_routing -v`
Expected: FAIL — `AttributeError: module 'src.workflows.agent' has no attribute '_empty_body_classification'`.

- [ ] **Step 3: Write minimal implementation**

In `src/workflows/agent.py`, add these two functions just below the imports (after line 6, before `# --- Nodes ---`):

```python
def _empty_body_classification(state) -> dict | None:
    """If the email has no readable text, classify as promotion (no action) without an LLM call."""
    if not (state.get("email_content") or "").strip():
        return {"category": "promotion", "reason": "Email had no readable text content."}
    return None


def route_after_classification(state) -> str:
    """Route from the classifier: actionable -> extract, notification -> notify, else END."""
    category = (state.get("classification") or {}).get("category", "promotion")
    if category == "actionable":
        return "extract"
    if category == "notification":
        return "notify"
    return END
```

`END` is already importable — confirm the top of the file has `from langgraph.graph import StateGraph, END` (it does, line 1).

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_routing -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/workflows/agent.py tests/test_email_routing.py
git commit -m "feat: add empty-body guard and classification routing"
```

---

## Task 3: Classifier node

**Files:**
- Modify: `src/workflows/agent.py`

No unit test (the node calls the Groq API; its routing is already covered by Task 2 and it is exercised in the end-to-end manual check at the end).

- [ ] **Step 1: Add the classifier node**

In `src/workflows/agent.py`, add this function immediately after the `route_after_classification` function from Task 2. It must import `EmailClassification`; update the existing import on line 5 from `from src.workflows.state import AgentState, EmailAnalysis` to `from src.workflows.state import AgentState, EmailAnalysis, EmailClassification`.

```python
async def classify_email(state: AgentState) -> AgentState:
    """First pass: bucket the email into actionable / notification / promotion."""
    skip = _empty_body_classification(state)
    if skip is not None:
        print(f"Classifier: empty body -> promotion (no action).")
        return {"classification": skip}

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0,
        api_key=settings.groq_api_key.get_secret_value(),
    )
    structured_llm = llm.with_structured_output(EmailClassification, method="json_mode")

    system_msg = (
        "You are an email triage assistant. Classify the email into EXACTLY ONE category:\n"
        "- 'actionable': a person is communicating with the user and it may need a reply, a task, "
        "or scheduling (meeting requests, deadlines, calls, direct questions from real people).\n"
        "- 'notification': automated but relevant updates the user should see "
        "(LinkedIn messages, account/app notifications, system alerts).\n"
        "- 'promotion': marketing, promotions, newsletters, or pure confirmations/receipts "
        "(booking confirmations, order receipts) that need no action.\n\n"
        "Respond ONLY with valid JSON matching this schema:\n"
        '{{"category": "actionable|notification|promotion", "reason": "one short sentence"}}'
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("user", "Subject: {subject}\nFrom: {sender}\n\nBody:\n{body}"),
    ])
    chain = prompt | structured_llm

    print("Calling Groq API for email classification...")
    result = await chain.ainvoke({
        "subject": state.get("email_subject", ""),
        "sender": state.get("sender_email", ""),
        "body": state["email_content"][:2000],
    })
    print(f"Classifier: category={result.category} ({result.reason})")
    return {"classification": result.model_dump()}
```

Note the `{{` / `}}` escaping in `system_msg` — `ChatPromptTemplate` treats single braces as variables, so literal JSON braces must be doubled (the existing `extract_and_plan` uses the same pattern).

- [ ] **Step 2: Verify the module still imports**

Run: `./venv/Scripts/python.exe -c "from src.workflows import agent; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 3: Commit**

```bash
git add src/workflows/agent.py
git commit -m "feat: add classifier node for email triage"
```

---

## Task 4: Notification node and refocus the extractor

**Files:**
- Modify: `src/workflows/agent.py`

- [ ] **Step 1: Add the notification node**

In `src/workflows/agent.py`, add this function just before the existing `human_review` function (currently line 147):

```python
async def notification_review(state: AgentState) -> AgentState:
    """Surface a notification and pause until the user dismisses it."""
    interrupt(state.get("classification", {}))
    return {"approval_status": "acknowledged"}
```

- [ ] **Step 2: Remove the empty-body guard from the extractor**

In `extract_and_plan`, delete the empty-body guard block added in a previous PR (the classifier now owns this). Remove these lines (currently lines 12-18):

```python
    # Guard: never ask the LLM to extract tasks from an empty body — it will
    # hallucinate. An email with no readable text is simply not actionable.
    if not (state.get("email_content") or "").strip():
        print("Email body empty after extraction — marking non-actionable, skipping LLM.")
        empty = EmailAnalysis(is_actionable=False, urgency_score=1)
        return {"analysis": empty.model_dump(), "approval_status": "pending"}

```

- [ ] **Step 3: Teach the extractor about `needs_task`**

In `extract_and_plan`, update the `json_schema` string (currently lines 43-52) to include `needs_task` and adjust the instructions. Replace the `json_schema` assignment with:

```python
    json_schema = (
        '{{\n'
        '  "is_actionable": boolean,\n'
        '  "needs_task": boolean,\n'
        '  "urgency_score": integer (1-10),\n'
        '  "tasks": [{{"title": string, "description": string, "priority": "low|medium|high", "due_date": "ISO8601 or empty string"}}],\n'
        '  "events": [{{"summary": string, "start_time": "ISO8601", "end_time": "ISO8601", "rationale": string}}],\n'
        '  "needs_reply": boolean,\n'
        '  "suggested_reply": string\n'
        '}}'
    )
```

In the same function, in the `system_msg` assignment (currently lines 56-66), add a sentence about `needs_task` by inserting this line into the string, immediately after the `"Extract actionable tasks..."` line:

```python
        "Set needs_task=true and populate tasks/events ONLY when there is a clear task AND a date "
        "(a deadline, meeting, or call with a time). Otherwise leave needs_task=false and tasks/events empty.\n"
```

- [ ] **Step 4: Verify the module still imports**

Run: `./venv/Scripts/python.exe -c "from src.workflows import agent; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 5: Commit**

```bash
git add src/workflows/agent.py
git commit -m "feat: add notification node and refocus extractor on needs_task"
```

---

## Task 5: Move task persistence into the executor

**Files:**
- Modify: `src/workflows/agent.py`

- [ ] **Step 1: Remove eager task persistence from the extractor**

In `extract_and_plan`, delete the entire "Persist tasks to DB" try/except block (currently lines 86-117, beginning `# Persist tasks to DB` and ending at the `print(f"Task persistence failed (non-fatal): {e}")` handler). Leave the contact-memory update block intact. After this removal, the `try:` body around the Groq call should: call the chain, then run the contact-memory update, then `return {"analysis": analysis.model_dump(), "approval_status": "pending"}`.

- [ ] **Step 2: Restructure the executor to persist tasks first, then schedule events**

The current `execute_plan` early-returns when there are no events, which would skip task persistence for task-only emails. Replace everything from `analysis = state.get("analysis", {})` (currently line 166) to the end of the function (`return state`, line 196) with:

```python
    analysis = state.get("analysis", {})

    # 1. Fetch the user once (needed for both task persistence and calendar)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == uuid.UUID(state['user_id'])))
        user = result.scalars().first()
        if not user:
            print("Error: User not found in DB.")
            return state

        # 2. Persist approved tasks to the DB (only happens on approval)
        from src.models.task import Task
        from datetime import datetime as _dt
        analysis_tasks = analysis.get("tasks", [])
        for t in analysis_tasks:
            due = None
            if t.get("due_date"):
                try:
                    due = _dt.fromisoformat(t["due_date"].replace("Z", "+00:00"))
                except Exception:
                    pass
            db.add(Task(
                user_id=user.id,
                email_id=state.get("email_id"),
                title=t.get("title", ""),
                description=t.get("description", ""),
                priority=t.get("priority", "medium"),
                due_date=due,
                urgency_score=analysis.get("urgency_score", 5),
            ))
        if analysis_tasks:
            await db.commit()
            print(f"Persisted {len(analysis_tasks)} approved task(s) to DB.")

    # 3. Create each proposed event via Google Calendar API
    events_to_schedule = analysis.get("events", [])
    if not events_to_schedule:
        print("No events to schedule.")
        return state

    for event in events_to_schedule:
        try:
            print(f"Scheduling: {event['summary']} from {event['start_time']} to {event['end_time']}")
            result = await CalendarService.create_event(
                user=user,
                summary=event['summary'],
                start_time=event['start_time'],
                end_time=event['end_time'],
            )
            print(f"Success! Event link: {result['link']}")
        except Exception as e:
            print(f"Failed to schedule event {event['summary']}. Error: {e}")

    return state
```

Note: `execute_plan` already imports `AsyncSessionLocal`, `User`, `select`, `CalendarService`, and `uuid` at the top of the function (lines 157-161), so those are in scope. This replaces the old early-return-on-no-events logic.

- [ ] **Step 3: Verify the module still imports**

Run: `./venv/Scripts/python.exe -c "from src.workflows import agent; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 4: Commit**

```bash
git add src/workflows/agent.py
git commit -m "feat: persist tasks only on approval in executor"
```

---

## Task 6: Rewire the graph

**Files:**
- Modify: `src/workflows/agent.py`
- Test: `tests/test_email_routing.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_email_routing.py`:

```python
class GraphWiringTests(unittest.TestCase):
    def test_graph_has_expected_nodes(self):
        graph = agent.build_agent_graph()
        node_names = set(graph.get_graph().nodes.keys())
        for expected in ("classifier", "extractor", "notification_review", "human_review", "executor"):
            self.assertIn(expected, node_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_routing.GraphWiringTests -v`
Expected: FAIL — node `classifier` not found (graph still starts at `planner`).

- [ ] **Step 3: Rewire `build_agent_graph`**

Replace the body of `build_agent_graph` (currently lines 211-234) with:

```python
def build_agent_graph(checkpointer=None):
    workflow = StateGraph(AgentState)

    # Nodes
    workflow.add_node("classifier", classify_email)
    workflow.add_node("extractor", extract_and_plan)
    workflow.add_node("notification_review", notification_review)
    workflow.add_node("human_review", human_review)
    workflow.add_node("executor", execute_plan)

    # Entry: classify first
    workflow.set_entry_point("classifier")
    workflow.add_conditional_edges(
        "classifier",
        route_after_classification,
        {
            "extract": "extractor",
            "notify": "notification_review",
            END: END,
        },
    )

    # Notifications pause then end
    workflow.add_edge("notification_review", END)

    # Actionable: extract -> human review -> execute / re-plan / end
    workflow.add_edge("extractor", "human_review")
    workflow.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "execute": "executor",
            "re_plan": "extractor",
            END: END,
        },
    )
    workflow.add_edge("executor", END)

    return workflow.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: Run all tests**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_routing -v`
Expected: PASS (all tests, including `test_graph_has_expected_nodes`).

- [ ] **Step 5: Commit**

```bash
git add src/workflows/agent.py tests/test_email_routing.py
git commit -m "feat: rewire graph to classify-first pipeline"
```

---

## Task 7: Surface workflow errors (stop swallowing)

**Files:**
- Modify: `src/workflows/trigger.py:44-50`

The classifier/extractor can raise (bad LLM output, rate limits). Today `process_new_email` catches and swallows that, returning a `thread_id` with no `classification`, which the UI would misread as a promotion. Let it propagate so `test.py` returns a real 500 with the error detail. A normal `interrupt()` pause does **not** raise, so this only surfaces genuine failures.

- [ ] **Step 1: Remove the swallowing try/except**

In `src/workflows/trigger.py`, replace the block (currently lines 44-50):

```python
    print(f"4. Triggering AI workflow {thread_id} for {email_address}...")
    try:
        await app.ainvoke(initial_state, config)
        print(f"5. Done! Workflow {thread_id} paused for approval.")
        print(f"   Fetch the plan at: GET /tasks/pending/{thread_id}")
    except Exception as e:
        print(f"ERROR in workflow: {type(e).__name__}: {e}")
    return thread_id
```

with:

```python
    print(f"4. Triggering AI workflow {thread_id} for {email_address}...")
    await app.ainvoke(initial_state, config)
    print(f"5. Done! Workflow {thread_id} is at a stopping point.")
    print(f"   Fetch the result at: GET /tasks/pending/{thread_id}")
    return thread_id
```

- [ ] **Step 2: Verify the module still imports**

Run: `./venv/Scripts/python.exe -c "from src.workflows import trigger; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 3: Commit**

```bash
git add src/workflows/trigger.py
git commit -m "fix: stop swallowing workflow errors so failures surface to the UI"
```

---

## Task 8: Category-aware pending endpoint

**Files:**
- Modify: `src/api/approval.py:19-33`

- [ ] **Step 1: Rewrite `get_pending_plan`**

Replace the `get_pending_plan` function (lines 19-33) with:

```python
@router.get("/pending/{thread_id}")
async def get_pending_plan(thread_id: str):
    """Return the paused/finished workflow state, category-aware, with the full email."""
    app = build_agent_graph(memory_checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await app.aget_state(config)

    values = snapshot.values if snapshot else {}
    classification = values.get("classification") or {}
    category = classification.get("category", "promotion")
    paused = bool(snapshot and snapshot.next)

    if category == "actionable" and paused:
        status = "pending_approval"
    elif category == "notification" and paused:
        status = "notification"
    else:
        status = "no_action"

    return {
        "thread_id": thread_id,
        "category": category,
        "reason": classification.get("reason", ""),
        "status": status,
        "proposed_plan": values.get("analysis") if category == "actionable" else None,
        "email": {
            "subject": values.get("email_subject", ""),
            "sender": values.get("sender_email", ""),
            "body": values.get("email_content", ""),
        },
    }
```

- [ ] **Step 2: Verify the app imports**

Run: `./venv/Scripts/python.exe -c "import src.main; print('app import ok')"`
Expected: `app import ok`.

- [ ] **Step 3: Commit**

```bash
git add src/api/approval.py
git commit -m "feat: category-aware pending endpoint returning full email"
```

---

## Task 9: Local time formatting in the frontend

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Add the `fmtTime` helper**

In `src/static/index.html`, add this function immediately after the `esc` function (currently ends line 373):

```javascript
  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;  // unparseable -> show raw
    return d.toLocaleString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit'
    });
  }
```

- [ ] **Step 2: Use it for event times**

In `renderPlan`, change the events mapping (currently line 416) from:

```javascript
      '<div class="plan-item"><strong>' + esc(e.summary) + '</strong>' + esc(e.start_time) + ' to ' + esc(e.end_time) +
```

to:

```javascript
      '<div class="plan-item"><strong>' + esc(e.summary) + '</strong>' + esc(fmtTime(e.start_time)) + ' to ' + esc(fmtTime(e.end_time)) +
```

- [ ] **Step 3: Manual check**

Run: `./venv/Scripts/python.exe -c "open('src/static/index.html').read().index('function fmtTime'); print('helper present')"`
Expected: `helper present`.

- [ ] **Step 4: Commit**

```bash
git add src/static/index.html
git commit -m "feat: render proposed event times in local format"
```

---

## Task 10: Category-aware rendering and full-email panel

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Add markup for category badge, full-email panel, and notification card**

In `src/static/index.html`, inside the `planCard` div, replace the `<h2>Step 2 — Review AI Plan</h2>` and its subtitle (currently lines 146-147) with:

```html
      <h2>Step 2 — Review Email</h2>
      <div id="categoryBadge" style="margin-bottom:10px"></div>
      <details id="fullEmailPanel" style="margin-bottom:14px;border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px">
        <summary style="cursor:pointer;font-size:.82rem;color:#4f46e5;font-weight:600">View full email</summary>
        <div id="fullEmailMeta" style="font-size:.8rem;color:#6b7280;margin:8px 0"></div>
        <pre id="fullEmailBody" style="white-space:pre-wrap;font-size:.84rem;line-height:1.5;color:#374151;max-height:320px;overflow:auto;font-family:inherit;margin:0"></pre>
      </details>
      <p class="subtitle" id="planSubtitle">The AI proposed tasks and calendar events from your email.</p>
```

- [ ] **Step 2: Rewrite `loadPlan` to branch on category**

Replace the `loadPlan` function (currently lines 395-406) with:

```javascript
  async function loadPlan(threadId) {
    const res = await fetch(API + '/tasks/pending/' + threadId);
    const data = await res.json();
    document.getElementById('planCard').style.display = 'block';
    document.getElementById('threadTag').textContent = 'thread: ' + threadId;
    hideStatus('approvalStatus');

    // Full email panel (all categories)
    const email = data.email || {};
    document.getElementById('fullEmailMeta').innerHTML =
      '<strong>' + esc(email.subject || '(no subject)') + '</strong><br/>' + esc(email.sender || '');
    document.getElementById('fullEmailBody').textContent = email.body || '(no readable text)';

    // Category badge
    const badges = {
      actionable:   { label: 'Actionable',   bg: '#fef3c7', color: '#92400e' },
      notification: { label: 'Notification', bg: '#dbeafe', color: '#1e40af' },
      promotion:    { label: 'Promotion',    bg: '#f3f4f6', color: '#6b7280' },
    };
    const b = badges[data.category] || badges.promotion;
    document.getElementById('categoryBadge').innerHTML =
      '<span class="badge" style="background:' + b.bg + ';color:' + b.color + '">' + b.label + '</span>' +
      (data.reason ? '<span style="font-size:.8rem;color:#6b7280;margin-left:8px">' + esc(data.reason) + '</span>' : '');

    const planContent = document.getElementById('planContent');
    const approvalActions = document.querySelector('#planCard .approval-actions');
    const modifyRow = document.getElementById('modifyRow');
    const draftBox = document.getElementById('draftBox');

    if (data.category === 'actionable' && data.status === 'pending_approval') {
      document.getElementById('planSubtitle').style.display = 'block';
      approvalActions.style.display = 'flex';
      renderPlan(data.proposed_plan);
    } else if (data.category === 'notification') {
      document.getElementById('planSubtitle').style.display = 'none';
      approvalActions.style.display = 'none';
      modifyRow.style.display = 'none';
      draftBox.style.display = 'none';
      planContent.innerHTML =
        '<p style="font-size:.9rem;color:#374151">This is a notification. No action needed.</p>' +
        '<button class="btn-outline btn-sm" onclick="submitDecision(\'acknowledged\')">Dismiss</button>';
    } else {
      // promotion / no_action
      document.getElementById('planSubtitle').style.display = 'none';
      approvalActions.style.display = 'none';
      modifyRow.style.display = 'none';
      draftBox.style.display = 'none';
      planContent.innerHTML =
        '<p style="font-size:.9rem;color:#6b7280">Promotion / confirmation — no action needed.</p>';
    }
  }
```

- [ ] **Step 3: Make `submitDecision` tolerate the notification "acknowledged" action**

In `submitDecision`, the success-message map (currently line 448) only has `approved/rejected/modified`. Replace that line:

```javascript
      const msgs = { approved: 'Approved! Calendar event is being created.', rejected: 'Plan rejected.', modified: 'Changes submitted.' };
```

with:

```javascript
      const msgs = { approved: 'Approved! Calendar event is being created.', rejected: 'Plan rejected.', modified: 'Changes submitted.', acknowledged: 'Notification dismissed.' };
```

And change the next line so non-modify actions hide the card (currently `if (action !== 'modified')`) — it already hides for `acknowledged` since that is not `'modified'`, so no change is needed there.

- [ ] **Step 4: Manual verification (run the app)**

Start the server and exercise all four outcomes against real inbox emails:

```bash
./venv/Scripts/python.exe -m uvicorn src.main:app --reload
```

Then in a browser at the served URL (default `http://localhost:8000`), open the "Email to Calendar" tab and click "Run AI". Verify, across several emails:
- A promotion (e.g. Uber Eats) shows the **Promotion** badge, "no action needed", and the full email under "View full email" — and **no task is created** (check the Tasks tab).
- A notification (e.g. LinkedIn) shows the **Notification** badge and a **Dismiss** button.
- An actionable email with a clear date shows tasks/events with **local-formatted times**, and approving it creates the task only then.
- The full-email panel appears for every category.

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html
git commit -m "feat: category-aware review UI with full-email panel"
```

---

## Final verification

- [ ] Run the full test module: `./venv/Scripts/python.exe -m unittest tests.test_email_routing tests.test_gmail_body -v` — expected: all PASS.
- [ ] Confirm the app imports: `./venv/Scripts/python.exe -c "import src.main; print('ok')"`.
- [ ] Complete the manual checks in Task 10 Step 4.
