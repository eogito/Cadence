# Data Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every endpoint derive the user from the session (`current_user`) and only ever touch that user's data — removing all `email=` params and closing two resource-ownership holes.

**Architecture:** Convert each remaining handler to depend on `current_user` (from `src/api/deps.py`, built in the Outlook work) and drop its `email` parameter + `select(User).where(User.email == ...)` lookup. Add `Task.user_id == user.id` / `RecurringRule.user_id == user.id` to the two unscoped mutations. Strip every email input from the frontend and gate the UI behind sign-in.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, vanilla JS. Tests: stdlib `unittest` — `./venv/Scripts/python.exe -m unittest <module>`. Most verification is import checks + a manual cross-user test (DB-level ownership isn't unit-testable without a live DB); request-model field removals get cheap unit guards.

---

## File Structure

- `src/api/settings.py`, `src/api/tasks.py`, `src/api/context.py`, `src/api/meeting_prep.py`, `src/api/daily_schedule.py`, `src/api/approval.py` — convert handlers to `current_user`; close ownership holes in `tasks.py` + `context.py`.
- `src/static/index.html` — remove email inputs, drop `email` from fetches, gate UI on auth.
- `tests/test_data_isolation.py` — **new**: assert request models no longer expose an `email`/`user_email` field.

A shared pattern for every backend conversion: **add** `from src.api.deps import current_user` to the imports, **replace** the `email: str = "glenlin7813@gmail.com"` parameter with `user: User = Depends(current_user)`, and **delete** the handler's `result = await db.execute(select(User).where(User.email == email)); user = result.scalars().first(); if not user: raise HTTPException(404, ...)` block (current_user already 401s when unauthenticated). `User` and `Depends` are already imported in each of these files.

---

## Task 1: settings.py → current_user

**Files:**
- Modify: `src/api/settings.py`
- Test: `tests/test_data_isolation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_isolation.py`:

```python
"""Request models must not expose an email/user_email field (data isolation)."""
import unittest


class RequestModelTests(unittest.TestCase):
    def test_email_sections_request_has_no_email(self):
        from src.api.settings import EmailSectionsRequest
        self.assertNotIn("email", EmailSectionsRequest.model_fields)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_data_isolation -v`
Expected: FAIL — `email` is still a field.

- [ ] **Step 3: Convert the endpoints**

In `src/api/settings.py`: add `from src.api.deps import current_user` to the imports. Replace the `EmailSectionsRequest` model and both handlers:

```python
class EmailSectionsRequest(BaseModel):
    tracked_categories: List[str]


@router.get("/email-sections")
async def get_email_sections(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Return the signed-in user's tracked Gmail sections (default if unset)."""
    cats = await get_tracked_categories(db, user)
    return {"tracked_categories": cats, "valid_categories": VALID_CATEGORIES}


@router.put("/email-sections")
async def put_email_sections(
    request: EmailSectionsRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save which sections the signed-in user wants tracked."""
    bad = invalid_categories(request.tracked_categories)
    if bad:
        raise HTTPException(status_code=400, detail=f"Invalid categories: {bad}. Allowed: {VALID_CATEGORIES}")
    saved = await set_tracked_categories(db, user, request.tracked_categories)
    return {"tracked_categories": saved}
```

- [ ] **Step 4: Run test + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_data_isolation -v` → PASS.
Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/api/settings.py tests/test_data_isolation.py
git commit -m "feat: settings endpoints use current_user"
```

---

## Task 2: tasks.py → current_user + ownership

**Files:**
- Modify: `src/api/tasks.py`

- [ ] **Step 1: Convert both GET endpoints**

In `src/api/tasks.py`: add `from src.api.deps import current_user`. For `get_tasks` (the `GET ""` handler) and `get_contacts` (`GET "/contacts"`), replace the `email: str = "glenlin7813@gmail.com"` parameter with `user: User = Depends(current_user)` and delete each handler's `select(User).where(User.email == email)` lookup + its 404. The rest of each body already uses `user.id`.

- [ ] **Step 2: Close the ownership hole in complete_task**

In `complete_task` (the `PATCH "/{task_id}/complete"` handler), add the `current_user` dependency and scope the lookup to the owner. Replace the handler with:

```python
@router.patch("/{task_id}/complete")
async def complete_task(task_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Mark one of the signed-in user's tasks completed."""
    result = await db.execute(
        select(Task).where(Task.id == uuid.UUID(task_id), Task.user_id == user.id)
    )
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    task.completed = True
    await db.commit()
    return {"message": "Task marked as completed."}
```

- [ ] **Step 3: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/api/tasks.py
git commit -m "feat: tasks endpoints use current_user and enforce ownership"
```

---

## Task 3: context.py → current_user + ownership

**Files:**
- Modify: `src/api/context.py`
- Test: `tests/test_data_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_data_isolation.py`:

```python
    def test_context_requests_have_no_email(self):
        from src.api.context import AddContextRequest, AddRuleRequest
        self.assertNotIn("email", AddContextRequest.model_fields)
        self.assertNotIn("email", AddRuleRequest.model_fields)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_data_isolation -v`
Expected: FAIL — `email` still present.

- [ ] **Step 3: Convert the endpoints + drop email fields**

In `src/api/context.py`: add `from src.api.deps import current_user`.
- Remove the `email: str = "glenlin7813@gmail.com"` field from `AddContextRequest` and `AddRuleRequest`.
- For `add_user_context`, `get_user_context`, `remove_context`, `add_recurring_rule`, `get_recurring_rules`: replace the `email` parameter with `user: User = Depends(current_user)` and delete each handler's `select(User).where(User.email == ...)` lookup + 404. For the POST handlers that read `request.email`, use `user` instead.

- [ ] **Step 4: Close the ownership hole in delete_rule**

Replace the `delete_rule` handler (`DELETE "/rules/{rule_id}"`) with:

```python
@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Deactivate one of the signed-in user's recurring rules."""
    result = await db.execute(
        select(RecurringRule).where(RecurringRule.id == uuid.UUID(rule_id), RecurringRule.user_id == user.id)
    )
    rule = result.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found.")
    rule.active = False
    await db.commit()

    from src.services.scheduler_service import unregister_rule
    unregister_rule(rule_id)
    return {"message": "Rule deactivated."}
```

- [ ] **Step 5: Run test + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_data_isolation -v` → PASS.
Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 6: Commit**

```bash
git add src/api/context.py tests/test_data_isolation.py
git commit -m "feat: context/rules endpoints use current_user and enforce ownership"
```

---

## Task 4: meeting_prep.py → current_user

**Files:**
- Modify: `src/api/meeting_prep.py`

- [ ] **Step 1: Convert the endpoint**

In `src/api/meeting_prep.py`: add `from src.api.deps import current_user`. In `get_meeting_prep`, replace the `email: str = "glenlin7813@gmail.com"` parameter with `user: User = Depends(current_user)` and delete the `select(User).where(User.email == email)` lookup + 404. The attendee self-exclusion currently uses `email`; change it to use `user.email`:

```python
    attendee_emails = [a for a in next_event.get("attendees", []) if a and a != user.email]
```

- [ ] **Step 2: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/api/meeting_prep.py
git commit -m "feat: meeting prep uses current_user"
```

---

## Task 5: daily_schedule.py → current_user

**Files:**
- Modify: `src/api/daily_schedule.py`
- Test: `tests/test_data_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_data_isolation.py`:

```python
    def test_create_task_from_block_request_has_no_email(self):
        from src.api.daily_schedule import CreateTaskFromBlockRequest
        self.assertNotIn("email", CreateTaskFromBlockRequest.model_fields)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_data_isolation -v`
Expected: FAIL — `email` still present.

- [ ] **Step 3: Convert both endpoints + drop the email field**

In `src/api/daily_schedule.py`: add `from src.api.deps import current_user`.
- Remove the `email: str = "glenlin7813@gmail.com"` field from `CreateTaskFromBlockRequest`.
- For `get_daily_schedule` (`GET ""`) and `create_task_from_block` (`POST "/create-task"`): replace the `email` parameter with `user: User = Depends(current_user)` and delete each handler's `select(User).where(User.email == ...)` lookup + 404. The POST handler that read `request.email` uses `user` instead.

- [ ] **Step 4: Run test + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_data_isolation -v` → PASS.
Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/api/daily_schedule.py tests/test_data_isolation.py
git commit -m "feat: daily schedule uses current_user"
```

---

## Task 6: approval.py send-draft → current_user

**Files:**
- Modify: `src/api/approval.py`
- Test: `tests/test_data_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_data_isolation.py`:

```python
    def test_draft_send_request_has_no_user_email(self):
        from src.api.approval import DraftSendRequest
        self.assertNotIn("user_email", DraftSendRequest.model_fields)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_data_isolation -v`
Expected: FAIL — `user_email` still present.

- [ ] **Step 3: Convert the endpoint**

In `src/api/approval.py`: add `from src.api.deps import current_user` (the file already imports `User`, `get_db`, `select`). Remove the `user_email: str = "glenlin7813@gmail.com"` field from `DraftSendRequest`. Replace `send_draft_reply` with:

```python
@router.post("/send-draft")
async def send_draft_reply(
    request: DraftSendRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send an AI-drafted reply from the signed-in user's Outlook account."""
    sent = await OutlookMailService.send_email(user, to=request.to, subject=request.subject, body=request.body)
    return {"message": "Email sent successfully.", "status": sent.get("status")}
```

- [ ] **Step 4: Run test + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_data_isolation -v` → PASS.
Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/api/approval.py tests/test_data_isolation.py
git commit -m "feat: send-draft uses current_user"
```

---

## Task 7: Frontend — remove email inputs + gate on auth

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Remove the email input elements**

Delete these `<input>` elements (each is a `type="email"` with the given id) and the surrounding `.row` wrapper if it leaves an empty row with just a button — keep the button: `rulesEmail`, `tasksEmail`, `contactsEmail`, `prepEmail`, `scheduleEmail`. (The `emailInput`/`briefingEmail` were already removed in the Outlook work.)

- [ ] **Step 2: Drop `email` from every fetch**

In the `<script>`, remove the `email` query param and request-body field from these functions so each call relies on the session cookie. For each, delete the `const email = document.getElementById('...Email').value...` line and change the URL/body:
- `loadEmailSections`: `fetch(API + '/settings/email-sections')`
- `saveEmailSections`: body `{ tracked_categories: cats }`
- `loadRulesTab`: `fetch(API + '/context')` and `fetch(API + '/context/rules')`
- `addContext`: body `{ text, category }`
- `addRule`: body without `email` (`{ description, task_title, cron_hour, cron_minute, cron_day_of_week }`)
- `getTasks`: `fetch(API + '/tasks-list')`
- `getContacts`: `fetch(API + '/tasks-list/contacts')`
- `getMeetingPrep`: `fetch(API + '/meeting-prep')`
- `getDailySchedule`: `fetch(API + '/daily-schedule')`
- `createTaskFromBlock`: body without `email`
- `deleteContext`: `fetch(API + '/context/' + itemId, { method: 'DELETE' })`

(Leave `sendDraft`'s prompts for `to`/`subject` — those are the *recipient*, not the user identity — but remove `user_email` from its body.)

- [ ] **Step 3: Gate the UI on authentication**

Replace the existing `checkAuth()` function so it shows/hides the app. Add an id to `<main>` first: change `<main>` to `<main id="appMain" style="display:none">`, and add a sign-in splash right after `<body>`:

```html
<div id="signinSplash" style="display:none;text-align:center;margin-top:80px">
  <h2 style="font-weight:600;margin-bottom:12px">AI Personal Secretary</h2>
  <p style="color:#6b7280;margin-bottom:20px">Sign in with your Microsoft account to continue.</p>
  <a href="/auth/login" class="btn-primary" style="display:inline-block;text-decoration:none;padding:10px 20px;border-radius:8px">Sign in with Microsoft</a>
</div>
```

Then replace `checkAuth()` with:

```javascript
  async function checkAuth() {
    const main = document.getElementById('appMain');
    const splash = document.getElementById('signinSplash');
    const authArea = document.getElementById('authArea');
    try {
      const res = await fetch(API + '/auth/me');
      if (res.ok) {
        const data = await res.json();
        main.style.display = '';
        splash.style.display = 'none';
        authArea.innerHTML = 'Signed in as ' + esc(data.email) +
          ' &middot; <a href="/auth/logout" style="color:#93c5fd">Sign out</a>';
        return;
      }
    } catch (e) { /* fall through to signed-out */ }
    main.style.display = 'none';
    splash.style.display = 'block';
    authArea.innerHTML = '';
  }
```

`checkAuth()` is already called on load. Keep that call.

- [ ] **Step 4: Structural verification**

Run these read-only checks:
- `grep -c "type=\"email\"" src/static/index.html` → expect `0`
- `grep -c "?email=" src/static/index.html` → expect `0`
- `grep -c "user_email" src/static/index.html` → expect `0`
- `grep -c "id=\"signinSplash\"" src/static/index.html` → expect `1`
- `grep -c "id=\"appMain\"" src/static/index.html` → expect `1`

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html
git commit -m "feat: remove email inputs and gate UI behind Microsoft sign-in"
```

---

## Final verification

### Automated
- [ ] `./venv/Scripts/python.exe -m unittest tests.test_data_isolation tests.test_outlook_auth tests.test_outlook_mail tests.test_email_sections tests.test_email_routing -v` → all PASS.
- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
- [ ] `grep -rn "glenlin7813@gmail.com" src/api/` → no matches.

### Manual cross-user test (needs two Outlook accounts)
- [ ] Start the app; open `http://localhost:8000` while signed out → only the **sign-in splash** shows (no tabs/data).
- [ ] Sign in as **user A** → create a task (mark from a schedule block or via the workflow) and a recurring rule.
- [ ] Note A's task id and rule id (from the network tab or DB). Sign out, sign in as **user B** (a different Outlook account).
- [ ] Confirm B's Tasks / Contacts / Rules show **none** of A's data.
- [ ] With B signed in, `PATCH /tasks-list/<A's task id>/complete` and `DELETE /context/rules/<A's rule id>` → both return **404** (B cannot touch A's resources).
