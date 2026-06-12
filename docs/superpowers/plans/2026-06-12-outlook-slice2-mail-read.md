# Microsoft Integration — Slice 2: Outlook Mail (Read) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read the signed-in user's Outlook mailbox via Microsoft Graph — wire Process Latest Email and the Morning Briefing to their real inbox, filtered by Focused/Other.

**Architecture:** A `MicrosoftAuthService` turns the stored MSAL token cache into a live Graph access token (silent refresh). An `OutlookMailService` (async `httpx`) calls `graph.microsoft.com/v1.0/me/messages`, reusing a shared `html_to_text` helper. The email-sections feature is reworked from Gmail tabs to Outlook's Focused/Other. The trigger and briefing endpoints identify the user via the Slice-1 `current_user` session dependency.

**Tech Stack:** Python 3.12, FastAPI, MSAL, `httpx` (already installed), SQLAlchemy async. Tests use stdlib `unittest`: `./venv/Scripts/python.exe -m unittest <module>`.

**Scope note:** Slice 2 of `docs/superpowers/specs/2026-06-11-microsoft-account-integration-design.md`. Calendar writes, draft send, Meeting Prep, the full `current_user` sweep, and deleting the Google service files are **Slice 3**. The Google services remain importable here (still referenced by not-yet-converted endpoints).

---

## File Structure

- `src/services/text_utils.py` — **new**: shared `html_to_text` (HTML→plain text).
- `src/services/ms_auth.py` — **new**: `MicrosoftAuthService` + `SCOPES` + `build_msal_app`.
- `src/services/outlook_mail_service.py` — **new**: `OutlookMailService` (Graph mail read + `build_classification_filter`).
- `src/api/auth.py` — import `SCOPES`/`build_msal_app` from `ms_auth` (remove the local copies).
- `src/models/email_preferences.py` — constants → `focused`/`other`.
- `src/api/test.py` — trigger uses `current_user` + `OutlookMailService`.
- `src/workflows/trigger.py` — `process_new_email` reads via `OutlookMailService`.
- `src/api/briefing.py` — briefing uses `current_user` + `OutlookMailService`.
- `src/static/index.html` — Focused/Other checkboxes; drop the email inputs on the Email + Briefing tabs.
- `tests/test_email_sections.py` — update to the Focused/Other model.
- `tests/test_outlook_mail.py` — **new**: `build_classification_filter` + `MicrosoftAuthService` guard tests.

---

## Task 1: Shared html_to_text helper

**Files:**
- Create: `src/services/text_utils.py`
- Test: `tests/test_outlook_mail.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_outlook_mail.py`:

```python
"""Tests for Outlook mail read path (stdlib unittest)."""
import unittest

from src.services.text_utils import html_to_text


class HtmlToTextTests(unittest.TestCase):
    def test_strips_tags(self):
        out = html_to_text("<html><body><p>Hello <b>world</b></p></body></html>")
        self.assertIn("Hello", out)
        self.assertIn("world", out)
        self.assertNotIn("<", out)

    def test_drops_script_and_style(self):
        out = html_to_text("<style>.x{color:red}</style><p>Real</p><script>alert(1)</script>")
        self.assertEqual(out, "Real")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.text_utils'`.

- [ ] **Step 3: Implement it** (ported from the existing `gmail_service._html_to_text`)

Create `src/services/text_utils.py`:

```python
from html.parser import HTMLParser
from typing import List


class _HTMLTextExtractor(HTMLParser):
    """Strips tags from HTML, dropping <script>/<style> contents."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def html_to_text(html: str) -> str:
    """Convert an HTML body to readable plain text using only the stdlib."""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    lines = [ln.strip() for ln in parser.get_text().splitlines()]
    return "\n".join(ln for ln in lines if ln)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/services/text_utils.py tests/test_outlook_mail.py
git commit -m "feat: add shared html_to_text helper"
```

---

## Task 2: MicrosoftAuthService (token provider)

**Files:**
- Create: `src/services/ms_auth.py`
- Modify: `src/api/auth.py`
- Test: `tests/test_outlook_mail.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_outlook_mail.py`:

```python
import asyncio
from src.models.user import User
from src.services.ms_auth import MicrosoftAuthService


class TokenProviderTests(unittest.TestCase):
    def test_no_cache_raises_permission_error(self):
        u = User(email="x@example.com")
        u.ms_token_cache = None
        with self.assertRaises(PermissionError):
            asyncio.run(MicrosoftAuthService.get_access_token(u))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.ms_auth'`.

- [ ] **Step 3: Implement the service**

Create `src/services/ms_auth.py`:

```python
import asyncio
import msal
from sqlalchemy import update
from src.config import settings
from src.database import AsyncSessionLocal
from src.models.user import User

# Delegated Graph scopes (MSAL adds reserved openid/profile/offline_access).
SCOPES = ["User.Read", "Mail.Read", "Mail.Send", "Calendars.ReadWrite"]


def build_msal_app(cache: msal.SerializableTokenCache | None = None) -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.ms_client_id,
        authority=settings.ms_authority,
        client_credential=settings.ms_client_secret.get_secret_value(),
        token_cache=cache,
    )


class MicrosoftAuthService:
    @staticmethod
    async def get_access_token(user: User) -> str:
        """Return a valid Graph access token for the user, refreshing silently.

        Persists a rotated token cache back to the DB. Raises PermissionError
        if the user must re-authenticate.
        """
        cache = msal.SerializableTokenCache()
        if user.ms_token_cache:
            cache.deserialize(user.ms_token_cache)
        app = build_msal_app(cache)

        accounts = app.get_accounts()
        if not accounts:
            raise PermissionError("No Microsoft account on file — sign in again.")
        result = await asyncio.to_thread(app.acquire_token_silent, SCOPES, account=accounts[0])
        if not result or "access_token" not in result:
            raise PermissionError("Microsoft session expired — sign in again.")

        if cache.has_state_changed:
            new_cache = cache.serialize()
            user.ms_token_cache = new_cache
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(User).where(User.id == user.id).values(ms_token_cache=new_cache)
                )
                await db.commit()

        return result["access_token"]
```

- [ ] **Step 4: Point auth.py at the shared SCOPES/app builder**

In `src/api/auth.py`, remove the local `SCOPES = [...]` list and the `_build_msal_app` function, and import them instead. Change the import block to add:

```python
from src.services.ms_auth import SCOPES, build_msal_app
```

Then replace the two call sites: `_build_msal_app()` → `build_msal_app()` and `_build_msal_app(cache)` → `build_msal_app(cache)`.

- [ ] **Step 5: Run tests + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v` → expect PASS (3 tests).
Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 6: Commit**

```bash
git add src/services/ms_auth.py src/api/auth.py tests/test_outlook_mail.py
git commit -m "feat: add MicrosoftAuthService token provider; share MSAL app builder"
```

---

## Task 3: OutlookMailService (Graph mail read)

**Files:**
- Create: `src/services/outlook_mail_service.py`
- Test: `tests/test_outlook_mail.py`

- [ ] **Step 1: Write the failing test** (the pure filter builder)

Append to `tests/test_outlook_mail.py`:

```python
from src.services.outlook_mail_service import OutlookMailService


class ClassificationFilterTests(unittest.TestCase):
    def test_focused_only(self):
        self.assertEqual(
            OutlookMailService.build_classification_filter(["focused"]),
            "inferenceClassification eq 'focused'",
        )

    def test_both_is_empty(self):
        self.assertEqual(OutlookMailService.build_classification_filter(["focused", "other"]), "")

    def test_empty_is_sentinel(self):
        self.assertEqual(
            OutlookMailService.build_classification_filter([]),
            OutlookMailService.NO_MAIL_FILTER,
        )

    def test_unknown_values_ignored(self):
        self.assertEqual(
            OutlookMailService.build_classification_filter(["focused", "bogus"]),
            "inferenceClassification eq 'focused'",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.outlook_mail_service'`.

- [ ] **Step 3: Implement the service**

Create `src/services/outlook_mail_service.py`:

```python
import httpx
from typing import Any, Dict, List, Optional
from src.models.user import User
from src.models.email_preferences import VALID_CATEGORIES
from src.services.ms_auth import MicrosoftAuthService
from src.services.text_utils import html_to_text

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookMailService:
    # A $filter that matches no mail — used when the user tracks no classifications.
    NO_MAIL_FILTER = "id eq 'NONE'"

    @staticmethod
    def build_classification_filter(classes) -> str:
        """Graph $filter fragment for Focused/Other selection.

        - both selected -> "" (no classification filter)
        - one selected  -> inferenceClassification eq '<class>'
        - none selected -> NO_MAIL_FILTER (matches nothing)
        Unknown values are dropped.
        """
        valid = [c for c in classes if c in VALID_CATEGORIES]
        if not valid:
            return OutlookMailService.NO_MAIL_FILTER
        if set(valid) == set(VALID_CATEGORIES):
            return ""
        return f"inferenceClassification eq '{valid[0]}'"

    @staticmethod
    async def _graph_get(user: User, path: str, params: dict) -> dict:
        token = await MicrosoftAuthService.get_access_token(user)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GRAPH_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph error {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    @staticmethod
    def _body_text(message: dict) -> str:
        body = message.get("body", {})
        content = body.get("content", "") or ""
        if body.get("contentType", "").lower() == "html":
            return html_to_text(content)
        return content

    @staticmethod
    def _sender(message: dict) -> str:
        return (message.get("from", {}) or {}).get("emailAddress", {}).get("address", "Unknown")

    @staticmethod
    async def get_latest_message_id(user: User, classification=None) -> Optional[str]:
        params = {"$top": "1", "$orderby": "receivedDateTime desc", "$select": "id"}
        if classification is not None:
            filt = OutlookMailService.build_classification_filter(classification)
            if filt == OutlookMailService.NO_MAIL_FILTER:
                return None
            if filt:
                params["$filter"] = filt
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        items = data.get("value", [])
        return items[0]["id"] if items else None

    @staticmethod
    async def get_email_content(user: User, message_id: str) -> Optional[Dict[str, Any]]:
        params = {"$select": "subject,from,body,receivedDateTime"}
        message = await OutlookMailService._graph_get(user, f"/me/messages/{message_id}", params)
        if not message:
            return None
        return {
            "message_id": message_id,
            "subject": message.get("subject", "No Subject"),
            "sender": OutlookMailService._sender(message),
            "date": message.get("receivedDateTime", ""),
            "body": OutlookMailService._body_text(message).strip(),
        }

    @staticmethod
    async def get_unread_emails(user: User, max_results: int = 10, classification=None) -> List[Dict[str, Any]]:
        params = {
            "$filter": "isRead eq false",
            "$top": str(max_results),
            "$orderby": "receivedDateTime desc",
            "$select": "subject,from,bodyPreview,body,receivedDateTime",
        }
        if classification is not None:
            filt = OutlookMailService.build_classification_filter(classification)
            if filt == OutlookMailService.NO_MAIL_FILTER:
                return []
            if filt:
                params["$filter"] = f"isRead eq false and {filt}"
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        results = []
        for m in data.get("value", []):
            results.append({
                "message_id": m.get("id"),
                "subject": m.get("subject", "No Subject"),
                "sender": OutlookMailService._sender(m),
                "date": m.get("receivedDateTime", ""),
                "snippet": m.get("bodyPreview", ""),
                "body": OutlookMailService._body_text(m).strip()[:500],
            })
        return results
```

- [ ] **Step 4: Run tests + verify import**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail -v` → expect PASS (7 tests).
Run: `./venv/Scripts/python.exe -c "import src.services.outlook_mail_service; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/services/outlook_mail_service.py tests/test_outlook_mail.py
git commit -m "feat: add OutlookMailService Graph mail read"
```

---

## Task 4: Rework sections to Focused/Other

**Files:**
- Modify: `src/models/email_preferences.py`
- Modify: `tests/test_email_sections.py`

- [ ] **Step 1: Update the constants**

In `src/models/email_preferences.py`, change the two constants:

```python
VALID_CATEGORIES = ["focused", "other"]
DEFAULT_CATEGORIES = ["focused"]
```

(Leave the `EmailPreferences` table/columns unchanged — `tracked_categories` now holds Focused/Other values.)

- [ ] **Step 2: Update the obsolete Gmail tests**

In `tests/test_email_sections.py`, the `ConstantsTests` and `CategoryFilterTests` reference the old Gmail tabs. Replace the `ConstantsTests` class body with:

```python
class ConstantsTests(unittest.TestCase):
    def test_valid_categories_are_focused_other(self):
        self.assertEqual(set(VALID_CATEGORIES), {"focused", "other"})

    def test_default_is_focused(self):
        self.assertEqual(DEFAULT_CATEGORIES, ["focused"])

    def test_default_is_subset_of_valid(self):
        self.assertTrue(set(DEFAULT_CATEGORIES).issubset(set(VALID_CATEGORIES)))
```

Then **delete the entire `CategoryFilterTests` class** (it tested the Gmail `GmailService.build_category_filter`, which is superseded by `OutlookMailService.build_classification_filter`, covered in `tests/test_outlook_mail.py`). Also remove the now-unused `from src.services.gmail_service import GmailService` import line in that test file. Leave `ValidationTests` (it uses `invalid_categories`, which now validates Focused/Other automatically).

- [ ] **Step 3: Run tests**

Run: `./venv/Scripts/python.exe -m unittest tests.test_email_sections tests.test_outlook_mail -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/models/email_preferences.py tests/test_email_sections.py
git commit -m "feat: rework email sections to Outlook Focused/Other"
```

---

## Task 5: Wire Process Latest Email to Outlook

**Files:**
- Modify: `src/api/test.py` (rewrite the handler)
- Modify: `src/workflows/trigger.py`

- [ ] **Step 1: Rewrite the trigger endpoint**

Replace the entire contents of `src/api/test.py` with:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models.user import User
from src.api.deps import current_user
from src.services.outlook_mail_service import OutlookMailService
from src.services.email_preferences_service import get_tracked_categories
from src.workflows.trigger import process_new_email

router = APIRouter(prefix="/test", tags=["Testing"])


@router.post("/trigger")
async def trigger_latest_email(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Process the signed-in user's latest tracked Outlook email."""
    try:
        categories = await get_tracked_categories(db, user)
        message_id = await OutlookMailService.get_latest_message_id(user, classification=categories)
        if not message_id:
            return {"message": "No emails found in your tracked inbox."}

        thread_id = await process_new_email(user.email, message_id)
        return {
            "message": "Workflow paused for approval.",
            "email_id": message_id,
            "thread_id": thread_id,
        }
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 2: Read email content via Outlook in the workflow**

In `src/workflows/trigger.py`, change the import on line 6 from:

```python
from src.services.gmail_service import GmailService
```

to:

```python
from src.services.outlook_mail_service import OutlookMailService
```

And change the call on line 26 from `await GmailService.get_email_content(user, message_id)` to:

```python
    email_data = await OutlookMailService.get_email_content(user, message_id)
```

- [ ] **Step 3: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/api/test.py src/workflows/trigger.py
git commit -m "feat: Process Latest Email reads from Outlook via session"
```

---

## Task 6: Wire the Morning Briefing to Outlook

**Files:**
- Modify: `src/api/briefing.py`

- [ ] **Step 1: Switch to current_user + OutlookMailService**

In `src/api/briefing.py`:
- Change the import `from src.services.gmail_service import GmailService` to `from src.services.outlook_mail_service import OutlookMailService`.
- Add imports: `from src.api.deps import current_user` and `from src.models.user import User`.
- Change the endpoint signature from `email: str = "glenlin7813@gmail.com", db: AsyncSession = Depends(get_db)` to:

```python
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
```

- Delete the now-redundant user lookup block (the `select(User).where(User.email == email)` + the 404). `current_user` already provides `user`.
- Change the emails fetch to use Outlook with the tracked classification (note the parameter is `classification`):

```python
    categories = await get_tracked_categories(db, user)
    events, emails = await asyncio.gather(
        CalendarService.get_upcoming_events(user, days_ahead=1),
        OutlookMailService.get_unread_emails(user, max_results=15, classification=categories),
    )
```

(`get_tracked_categories` import is already present from Slice 1; if not, add `from src.services.email_preferences_service import get_tracked_categories`.) `CalendarService` stays Google for now — it is replaced in Slice 3; the briefing's calendar half may be empty/error until then, which is acceptable WIP.

- [ ] **Step 2: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/api/briefing.py
git commit -m "feat: Morning Briefing reads unread Outlook mail by classification"
```

---

## Task 7: Frontend — Focused/Other + session-based fetches

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Replace the section checkboxes with Focused/Other**

In `src/static/index.html`, find the `#emailSectionsBoxes` block (five Gmail checkboxes) and replace its inner checkboxes with two:

```html
      <div id="emailSectionsBoxes" style="display:flex;flex-wrap:wrap;gap:14px;margin-bottom:12px;font-size:.9rem">
        <label><input type="checkbox" value="focused"> Focused</label>
        <label><input type="checkbox" value="other"> Other</label>
      </div>
```

Also update that card's subtitle text to read: `Choose which part of your Outlook inbox the AI scans. Focused is your important mail; Other is everything else.`

- [ ] **Step 2: Drop the email input on the Email-to-Calendar tab and stop sending it**

In the Email tab card, delete the `<input type="email" id="emailInput" ...>` line. Then in `triggerWorkflow()`, remove the line reading `emailInput` and change the fetch from `fetch(API + '/test/trigger?email=' + encodeURIComponent(email), { method: 'POST' })` to:

```javascript
      const res = await fetch(API + '/test/trigger', { method: 'POST' });
```

(Remove the now-unused `const email = ...` line at the top of `triggerWorkflow`.)

- [ ] **Step 3: Drop the email input on the Briefing tab and stop sending it**

In the Briefing tab card, delete `<input type="email" id="briefingEmail" ...>`. In `getBriefing()`, remove the `const email = ...` line and change the fetch from `fetch(API + '/briefing?email=' + encodeURIComponent(email))` to:

```javascript
      const res = await fetch(API + '/briefing');
```

- [ ] **Step 4: Structural verification**

Run these read-only checks:
- `grep -c "value=\"focused\"" src/static/index.html` → expect `1`
- `grep -c "value=\"other\"" src/static/index.html` → expect `1`
- `grep -c "id=\"emailInput\"" src/static/index.html` → expect `0`
- `grep -c "/test/trigger?email=" src/static/index.html` → expect `0`
- `grep -c "/briefing?email=" src/static/index.html` → expect `0`

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html
git commit -m "feat: Focused/Other UI and session-based mail fetches"
```

---

## Final verification

### Automated
- [ ] `./venv/Scripts/python.exe -m unittest tests.test_outlook_mail tests.test_email_sections tests.test_outlook_auth tests.test_email_routing tests.test_gmail_body -v` → all PASS.
- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

### Manual (signed in from Slice 1)
- [ ] Start the app: `./venv/Scripts/python.exe -m uvicorn src.main:app --reload`; ensure you're signed in (header shows your email).
- [ ] **My Rules** tab → the sections card now shows **Focused / Other**, with **Focused** checked by default; saving persists.
- [ ] **Email to Calendar** tab → click **Run AI** (no email box now). It should fetch your latest Focused Outlook email, run the AI, and show the review plan with the real email subject/body in "View full email".
- [ ] **Morning Briefing** → Generate; the unread list reflects your Outlook inbox (Focused). (The calendar summary may be empty/errored until Slice 3 wires Outlook Calendar — expected.)
- [ ] Sign out → **Run AI** returns 401 (handled by the error status), confirming the session gate.
