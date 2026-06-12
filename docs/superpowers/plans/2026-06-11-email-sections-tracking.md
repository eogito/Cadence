# Gmail Section Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users choose which Gmail sections (Primary/Social/Promotions/Updates/Forums) are included in email tracking, applied to Process Latest Email and the Morning Briefing.

**Architecture:** A new `EmailPreferences` table (auto-created by `create_all`) stores per-user tracked categories. A pure `build_category_filter` helper turns the selection into a Gmail search query, which the trigger and briefing apply when listing messages. A `/settings/email-sections` API and a card in the "My Rules" tab let the user view/edit the selection.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async (Postgres, JSONB), Gmail API, vanilla JS. Tests use stdlib `unittest` (pytest is NOT installed). Run tests with `./venv/Scripts/python.exe -m unittest <module>`.

---

## File Structure

- `src/models/email_preferences.py` — **new**: `EmailPreferences` model + `VALID_CATEGORIES` / `DEFAULT_CATEGORIES` constants (single source of truth).
- `src/services/email_preferences_service.py` — **new**: `get_tracked_categories`, `set_tracked_categories`, `invalid_categories`.
- `src/services/gmail_service.py` — add pure `build_category_filter`; add `categories` param to `get_unread_emails`.
- `src/api/settings.py` — **new**: GET/PUT `/settings/email-sections`.
- `src/api/test.py` — apply the filter to the trigger's `messages.list`.
- `src/api/briefing.py` — load prefs and pass them to `get_unread_emails`.
- `src/main.py` — register the new model for `create_all` and mount the settings router.
- `src/static/index.html` — "Email Sections to Track" card + load/save JS.
- `tests/test_email_sections.py` — **new**: unit tests for `build_category_filter` and `invalid_categories`.

---

## Task 1: EmailPreferences model and constants

**Files:**
- Create: `src/models/email_preferences.py`
- Test: `tests/test_email_sections.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_email_sections.py`:

```python
"""Tests for Gmail section tracking (stdlib unittest)."""
import unittest

from src.models.email_preferences import VALID_CATEGORIES, DEFAULT_CATEGORIES, EmailPreferences


class ConstantsTests(unittest.TestCase):
    def test_valid_categories(self):
        self.assertEqual(
            VALID_CATEGORIES, ["primary", "social", "promotions", "updates", "forums"]
        )

    def test_default_is_primary_and_updates(self):
        self.assertEqual(DEFAULT_CATEGORIES, ["primary", "updates"])

    def test_model_tablename(self):
        self.assertEqual(EmailPreferences.__tablename__, "email_preferences")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_sections -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.models.email_preferences'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/models/email_preferences.py` (mirrors the `User` model's Postgres UUID/JSONB pattern in `src/models/user.py`):

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.database import Base

VALID_CATEGORIES = ["primary", "social", "promotions", "updates", "forums"]
DEFAULT_CATEGORIES = ["primary", "updates"]


class EmailPreferences(Base):
    __tablename__ = "email_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), unique=True, index=True, nullable=False)
    tracked_categories = Column(JSONB, nullable=False, default=lambda: list(DEFAULT_CATEGORIES))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_sections -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/models/email_preferences.py tests/test_email_sections.py
git commit -m "feat: add EmailPreferences model and category constants"
```

---

## Task 2: build_category_filter helper

**Files:**
- Modify: `src/services/gmail_service.py`
- Test: `tests/test_email_sections.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_email_sections.py`:

```python
from src.services.gmail_service import GmailService


class CategoryFilterTests(unittest.TestCase):
    def test_empty_is_none_sentinel(self):
        self.assertEqual(GmailService.build_category_filter([]), "category:__none__")

    def test_single(self):
        self.assertEqual(GmailService.build_category_filter(["primary"]), "category:primary")

    def test_two(self):
        self.assertEqual(
            GmailService.build_category_filter(["primary", "updates"]),
            "(category:primary OR category:updates)",
        )

    def test_all_five_is_empty(self):
        self.assertEqual(GmailService.build_category_filter(VALID_CATEGORIES), "")

    def test_invalid_values_filtered_out(self):
        self.assertEqual(GmailService.build_category_filter(["primary", "bogus"]), "category:primary")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_sections -v`
Expected: FAIL — `AttributeError: type object 'GmailService' has no attribute 'build_category_filter'`.

- [ ] **Step 3: Write minimal implementation**

In `src/services/gmail_service.py`, add a top-level import near the existing imports (after `from src.models.user import User`):

```python
from src.models.email_preferences import VALID_CATEGORIES
```

Add this static method inside the `GmailService` class (e.g. directly after the `_decode_body` method):

```python
    @staticmethod
    def build_category_filter(categories) -> str:
        """Build a Gmail search filter for the selected inbox sections.

        - all valid sections selected -> "" (no filter, matches everything)
        - empty selection -> a sentinel query that matches no mail
        - otherwise -> 'category:X' or '(category:X OR category:Y ...)'
        """
        cats = [c for c in categories if c in VALID_CATEGORIES]
        if not cats:
            return "category:__none__"
        if set(cats) == set(VALID_CATEGORIES):
            return ""
        if len(cats) == 1:
            return f"category:{cats[0]}"
        return "(" + " OR ".join(f"category:{c}" for c in cats) + ")"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_sections -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/gmail_service.py tests/test_email_sections.py
git commit -m "feat: add build_category_filter Gmail query helper"
```

---

## Task 3: EmailPreferences service

**Files:**
- Create: `src/services/email_preferences_service.py`
- Test: `tests/test_email_sections.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_email_sections.py`:

```python
from src.services.email_preferences_service import invalid_categories


class ValidationTests(unittest.TestCase):
    def test_invalid_categories_detected(self):
        self.assertEqual(invalid_categories(["primary", "bogus", "x"]), ["bogus", "x"])

    def test_all_valid_returns_empty(self):
        self.assertEqual(invalid_categories(DEFAULT_CATEGORIES), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_sections -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.email_preferences_service'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/services/email_preferences_service.py`:

```python
from sqlalchemy import select
from src.models.email_preferences import EmailPreferences, DEFAULT_CATEGORIES, VALID_CATEGORIES


def invalid_categories(categories) -> list:
    """Return the subset of categories that are not valid Gmail sections."""
    return [c for c in categories if c not in VALID_CATEGORIES]


async def get_tracked_categories(db, user) -> list:
    """Return the user's tracked sections, or the default if none are saved."""
    result = await db.execute(
        select(EmailPreferences).where(EmailPreferences.user_id == user.id)
    )
    pref = result.scalars().first()
    if pref and pref.tracked_categories is not None:
        return pref.tracked_categories
    return list(DEFAULT_CATEGORIES)


async def set_tracked_categories(db, user, categories) -> list:
    """Upsert the user's tracked sections and return the saved list."""
    result = await db.execute(
        select(EmailPreferences).where(EmailPreferences.user_id == user.id)
    )
    pref = result.scalars().first()
    if pref:
        pref.tracked_categories = categories
    else:
        pref = EmailPreferences(user_id=user.id, tracked_categories=categories)
        db.add(pref)
    await db.commit()
    return categories
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_sections -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/email_preferences_service.py tests/test_email_sections.py
git commit -m "feat: add email preferences service (get/set/validate)"
```

---

## Task 4: Settings API and registration

**Files:**
- Create: `src/api/settings.py`
- Modify: `src/main.py`

- [ ] **Step 1: Create the settings router**

Create `src/api/settings.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.models.user import User
from src.models.email_preferences import VALID_CATEGORIES
from src.services.email_preferences_service import (
    get_tracked_categories,
    set_tracked_categories,
    invalid_categories,
)

router = APIRouter(prefix="/settings", tags=["Settings"])


class EmailSectionsRequest(BaseModel):
    email: str = "glenlin7813@gmail.com"
    tracked_categories: List[str]


@router.get("/email-sections")
async def get_email_sections(
    email: str = "glenlin7813@gmail.com", db: AsyncSession = Depends(get_db)
):
    """Return the user's tracked Gmail sections (default if unset)."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    cats = await get_tracked_categories(db, user)
    return {"tracked_categories": cats, "valid_categories": VALID_CATEGORIES}


@router.put("/email-sections")
async def put_email_sections(
    request: EmailSectionsRequest, db: AsyncSession = Depends(get_db)
):
    """Save which Gmail sections the user wants tracked."""
    bad = invalid_categories(request.tracked_categories)
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid categories: {bad}. Allowed: {VALID_CATEGORIES}",
        )
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    saved = await set_tracked_categories(db, user, request.tracked_categories)
    return {"tracked_categories": saved}
```

- [ ] **Step 2: Register the model and mount the router in main.py**

In `src/main.py`, add the model import next to the other `import src.models.*` lines (so `create_all` registers the table):

```python
import src.models.email_preferences  # noqa: F401
```

Add the router import next to the other `from src.api.* import router as *` lines:

```python
from src.api.settings import router as settings_router
```

And add this with the other `app.include_router(...)` calls:

```python
app.include_router(settings_router)
```

- [ ] **Step 3: Verify the app imports and table registers**

Run: `./venv/Scripts/python.exe -c "import src.main; from src.database import Base; print('email_preferences' in Base.metadata.tables)"`
Expected: prints `True`.

- [ ] **Step 4: Commit**

```bash
git add src/api/settings.py src/main.py
git commit -m "feat: add /settings/email-sections API and register table"
```

---

## Task 5: Apply the filter to Process Latest Email

**Files:**
- Modify: `src/api/test.py`

- [ ] **Step 1: Add imports**

In `src/api/test.py`, add to the imports at the top:

```python
from src.services.gmail_service import GmailService
from src.services.email_preferences_service import get_tracked_categories
```

- [ ] **Step 2: Build and apply the filter**

In `trigger_latest_email`, replace the block that currently reads (inside the `try:`):

```python
        service = await GoogleAuthService.get_gmail_service(user)
        response = await asyncio.to_thread(
            lambda: service.users().messages().list(userId='me', maxResults=1).execute()
        )
        messages = response.get('messages', [])
        if not messages:
            return {"message": "No emails found in inbox."}
```

with:

```python
        service = await GoogleAuthService.get_gmail_service(user)
        categories = await get_tracked_categories(db, user)
        q = GmailService.build_category_filter(categories)
        list_kwargs = {"userId": "me", "maxResults": 1}
        if q:
            list_kwargs["q"] = q
        response = await asyncio.to_thread(
            lambda: service.users().messages().list(**list_kwargs).execute()
        )
        messages = response.get('messages', [])
        if not messages:
            return {"message": "No emails found in your tracked sections."}
```

- [ ] **Step 3: Verify the app imports**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/api/test.py
git commit -m "feat: filter Process Latest Email by tracked sections"
```

---

## Task 6: Apply the filter to the Morning Briefing

**Files:**
- Modify: `src/services/gmail_service.py:80-100` (the `get_unread_emails` method)
- Modify: `src/api/briefing.py`

- [ ] **Step 1: Add a categories param to get_unread_emails**

In `src/services/gmail_service.py`, change the `get_unread_emails` signature and query. It currently is:

```python
    @staticmethod
    async def get_unread_emails(user: User, max_results: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent unread emails for the daily briefing."""
        service = await GoogleAuthService.get_gmail_service(user)
        response = await asyncio.to_thread(
            lambda: service.users().messages().list(
                userId="me", q="is:unread", maxResults=max_results
            ).execute()
        )
```

Replace those lines with:

```python
    @staticmethod
    async def get_unread_emails(user: User, max_results: int = 10, categories=None) -> List[Dict[str, Any]]:
        """Fetch recent unread emails for the daily briefing, optionally limited to sections."""
        service = await GoogleAuthService.get_gmail_service(user)
        q = "is:unread"
        if categories is not None:
            filt = GmailService.build_category_filter(categories)
            q = (q + " " + filt).strip()
        response = await asyncio.to_thread(
            lambda: service.users().messages().list(
                userId="me", q=q, maxResults=max_results
            ).execute()
        )
```

Leave the rest of the method body (the loop building `results`) unchanged.

- [ ] **Step 2: Load and pass prefs from the briefing endpoint**

In `src/api/briefing.py`, add the import near the other imports:

```python
from src.services.email_preferences_service import get_tracked_categories
```

Then, in `get_daily_briefing`, replace:

```python
    events, emails = await asyncio.gather(
        CalendarService.get_upcoming_events(user, days_ahead=1),
        GmailService.get_unread_emails(user, max_results=15)
    )
```

with:

```python
    categories = await get_tracked_categories(db, user)
    events, emails = await asyncio.gather(
        CalendarService.get_upcoming_events(user, days_ahead=1),
        GmailService.get_unread_emails(user, max_results=15, categories=categories)
    )
```

- [ ] **Step 3: Verify the app imports and tests still pass**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → expect `ok`.
Run: `./venv/Scripts/python.exe -m unittest tests.test_email_sections -v` → expect all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/services/gmail_service.py src/api/briefing.py
git commit -m "feat: filter Morning Briefing by tracked sections"
```

---

## Task 7: Frontend — Email Sections card

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Add the card markup to the My Rules tab**

In `src/static/index.html`, inside the `rulesTab` div, add this card immediately after the opening `<div id="rulesTab" class="tab">` line and before the "Add Personal Context" card:

```html
    <!-- Email sections to track -->
    <div class="card">
      <h2>Email Sections to Track</h2>
      <p class="subtitle">Choose which Gmail tabs the AI scans (Process Latest Email + Morning Briefing). Deselecting a section excludes it from tracking.</p>
      <div id="emailSectionsBoxes" style="display:flex;flex-wrap:wrap;gap:14px;margin-bottom:12px;font-size:.9rem">
        <label><input type="checkbox" value="primary"> Primary</label>
        <label><input type="checkbox" value="social"> Social</label>
        <label><input type="checkbox" value="promotions"> Promotions</label>
        <label><input type="checkbox" value="updates"> Updates</label>
        <label><input type="checkbox" value="forums"> Forums</label>
      </div>
      <button class="btn-primary" id="saveSectionsBtn" onclick="saveEmailSections()">Save Sections</button>
      <div id="sectionsStatus" class="status hidden"></div>
    </div>
```

- [ ] **Step 2: Add load/save JS functions**

In the `<script>` block, add these two functions (e.g. right before the existing `async function loadRulesTab()`):

```javascript
  async function loadEmailSections() {
    const email = document.getElementById('rulesEmail').value.trim();
    try {
      const res = await fetch(API + '/settings/email-sections?email=' + encodeURIComponent(email));
      const data = await res.json();
      if (!res.ok) return;
      const set = new Set(data.tracked_categories || []);
      document.querySelectorAll('#emailSectionsBoxes input[type=checkbox]').forEach(cb => {
        cb.checked = set.has(cb.value);
      });
    } catch (e) { /* leave boxes as-is on error */ }
  }

  async function saveEmailSections() {
    const email = document.getElementById('rulesEmail').value.trim();
    const cats = Array.from(document.querySelectorAll('#emailSectionsBoxes input[type=checkbox]'))
      .filter(cb => cb.checked).map(cb => cb.value);
    setLoading('saveSectionsBtn', true, 'Save Sections');
    try {
      const res = await fetch(API + '/settings/email-sections', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, tracked_categories: cats })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      showStatus('sectionsStatus', 'Saved! Tracking: ' + (cats.join(', ') || 'none'), 'success');
    } catch (e) {
      showStatus('sectionsStatus', 'Error: ' + e.message, 'error');
    } finally {
      setLoading('saveSectionsBtn', false, 'Save Sections');
    }
  }
```

- [ ] **Step 3: Load sections when the My Rules tab refreshes and on first page load**

In `loadRulesTab()`, add a call to `loadEmailSections()` as the first line of the function body (so the existing "Refresh" button also reloads the checkboxes).

Then, at the very end of the `<script>` block (just before `</script>`), add an initial load so the boxes reflect saved state on page open:

```javascript
  loadEmailSections();
```

- [ ] **Step 4: Structural verification**

Run these read-only checks:
- `grep -c "function saveEmailSections(" src/static/index.html` → expect `1`
- `grep -c "function loadEmailSections(" src/static/index.html` → expect `1`
- `grep -c "emailSectionsBoxes" src/static/index.html` → expect `3` (markup container + 2 JS querySelectorAll references)
- `grep -n "loadEmailSections();" src/static/index.html` → expect at least the initial-load call near the end

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html
git commit -m "feat: Email Sections to Track UI in My Rules tab"
```

---

## Final verification

- [ ] Run the test module: `./venv/Scripts/python.exe -m unittest tests.test_email_sections tests.test_email_routing tests.test_gmail_body -v` — expect all PASS.
- [ ] Confirm the app imports and the table is registered: `./venv/Scripts/python.exe -c "import src.main; from src.database import Base; print('email_preferences' in Base.metadata.tables)"` → `True`.
- [ ] Manual check (run the app): start `./venv/Scripts/python.exe -m uvicorn src.main:app --reload`, open the **My Rules** tab, confirm Primary + Updates are checked by default, uncheck Promotions/Social, click **Save Sections**, reload the page and confirm the selection persisted. Then run **Process Latest Email** and confirm it only surfaces mail from the selected sections.
