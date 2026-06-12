# Microsoft Integration — Slice 1: Auth Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user sign in with any Microsoft account (MSAL), establish a server-side login session, and show who they are — without touching the mail/calendar features yet.

**Architecture:** Rewrite `auth.py` to use MSAL's confidential-client auth-code flow against the `common` authority; persist the MSAL token cache on the `User`; store `user_id` in a Starlette signed-cookie session; expose a `current_user` dependency and an `/auth/me` endpoint; add a "Sign in with Microsoft" control to the header. The existing Google services stay in place (inert for MS users) and are removed in a later slice.

**Tech Stack:** Python 3.12, FastAPI/Starlette, MSAL (`msal`), SQLAlchemy async (Postgres), vanilla JS. Tests use stdlib `unittest` (pytest is NOT installed): `./venv/Scripts/python.exe -m unittest <module>`.

**Scope note:** This is Slice 1 of the Microsoft-integration spec (`docs/superpowers/specs/2026-06-11-microsoft-account-integration-design.md`). Identity is read from the OAuth **id-token claims** (no Graph call yet — that arrives in Slice 2). Google settings/columns are kept additively and cleaned up in Slice 3.

---

## File Structure

- `requirements.txt` — add `msal`.
- `src/config.py` — add Microsoft + session settings (additive; Google settings kept for now).
- `src/models/user.py` — add `ms_token_cache`, `ms_account_id` columns (keep `google_oauth_tokens`).
- `src/api/deps.py` — **new**: `current_user` session dependency.
- `src/main.py` — add `SessionMiddleware`.
- `src/api/auth.py` — rewrite to MSAL login/callback/logout + `/auth/me`.
- `src/static/index.html` — header "Sign in with Microsoft" / signed-in indicator.
- `tests/test_outlook_auth.py` — **new**: unit tests for config, model columns, and `current_user`.

---

## Task 1: Add MSAL dependency and Microsoft/session config

**Files:**
- Modify: `requirements.txt`
- Modify: `src/config.py`
- Test: `tests/test_outlook_auth.py`

- [ ] **Step 1: Add the dependency and install it**

Append a line `msal` to `requirements.txt`, then install:

Run: `./venv/Scripts/python.exe -m pip install msal`
Then verify: `./venv/Scripts/python.exe -c "import msal; print('msal ok')"`
Expected: `msal ok`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_outlook_auth.py`:

```python
"""Tests for Microsoft auth foundation (stdlib unittest)."""
import unittest

from src.config import settings


class ConfigTests(unittest.TestCase):
    def test_ms_authority_defaults_to_common(self):
        self.assertTrue(settings.ms_authority.endswith("/common"))

    def test_session_secret_is_present(self):
        self.assertTrue(settings.session_secret.get_secret_value())

    def test_ms_redirect_uri_present(self):
        self.assertIn("/auth/callback", settings.ms_redirect_uri)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_auth -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'ms_authority'`.

- [ ] **Step 4: Implement the config**

In `src/config.py`, add these fields to the `Settings` class (after the existing `groq_api_key` line). They have safe dev defaults so the app/tests run before Azure is set up:

```python
    ms_client_id: str = ""
    ms_client_secret: SecretStr = SecretStr("")
    ms_authority: str = "https://login.microsoftonline.com/common"
    ms_redirect_uri: str = "http://localhost:8000/auth/callback"
    session_secret: SecretStr = SecretStr("dev-insecure-session-secret-change-me")
```

(`SecretStr` is already imported in `config.py`. Leave the existing Google settings in place for now.)

- [ ] **Step 5: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_auth -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/config.py tests/test_outlook_auth.py
git commit -m "feat: add MSAL dependency and Microsoft/session config"
```

---

## Task 2: Add Microsoft token columns to the User model

**Files:**
- Modify: `src/models/user.py`
- Test: `tests/test_outlook_auth.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_outlook_auth.py`:

```python
from src.models.user import User


class UserModelTests(unittest.TestCase):
    def test_user_has_ms_columns(self):
        cols = User.__table__.columns
        self.assertIn("ms_token_cache", cols)
        self.assertIn("ms_account_id", cols)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_auth -v`
Expected: FAIL — `AssertionError: 'ms_token_cache' not found`.

- [ ] **Step 3: Implement the columns**

In `src/models/user.py`, add `Text` to the sqlalchemy import:

```python
from sqlalchemy import Column, String, DateTime, Text
```

Add these two columns to the `User` class (after the existing `google_oauth_tokens` line):

```python
    ms_token_cache = Column(Text, nullable=True)            # serialized MSAL SerializableTokenCache
    ms_account_id = Column(String(255), nullable=True, index=True)  # MSAL account/object id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_auth -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/models/user.py tests/test_outlook_auth.py
git commit -m "feat: add ms_token_cache and ms_account_id to User"
```

---

## Task 3: current_user session dependency

**Files:**
- Create: `src/api/deps.py`
- Test: `tests/test_outlook_auth.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_outlook_auth.py` (add `import asyncio`, `import uuid`, and the Starlette/FastAPI imports at the top of the file or inline here):

```python
import asyncio
import uuid
from starlette.requests import Request
from fastapi import HTTPException


def _make_request(session: dict) -> Request:
    return Request({"type": "http", "headers": [], "session": session})


class _FakeResult:
    def __init__(self, obj): self._obj = obj
    def scalars(self): return self
    def first(self): return self._obj


class _FakeDB:
    def __init__(self, obj): self._obj = obj
    async def execute(self, *args, **kwargs): return _FakeResult(self._obj)


class CurrentUserTests(unittest.TestCase):
    def test_no_session_raises_401(self):
        from src.api.deps import current_user
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(current_user(_make_request({}), db=_FakeDB(None)))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_user_raises_401(self):
        from src.api.deps import current_user
        sess = {"user_id": str(uuid.uuid4())}
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(current_user(_make_request(sess), db=_FakeDB(None)))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_session_returns_user(self):
        from src.api.deps import current_user
        u = User(email="x@example.com")
        u.id = uuid.uuid4()
        result = asyncio.run(current_user(_make_request({"user_id": str(u.id)}), db=_FakeDB(u)))
        self.assertIs(result, u)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_auth -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.api.deps'`.

- [ ] **Step 3: Implement the dependency**

Create `src/api/deps.py`:

```python
import uuid
from fastapi import Request, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.models.user import User


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Resolve the signed-in user from the session cookie, or raise 401."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Sign in with Microsoft.")
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalars().first()
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session invalid. Sign in again.")
    return user
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_outlook_auth -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/api/deps.py tests/test_outlook_auth.py
git commit -m "feat: add current_user session dependency"
```

---

## Task 4: Add SessionMiddleware

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Add the middleware**

In `src/main.py`, add an import near the other imports:

```python
from starlette.middleware.sessions import SessionMiddleware
from src.config import settings
```

Immediately after the `app = FastAPI(...)` construction, add:

```python
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret.get_secret_value(),
    same_site="lax",
    https_only=False,  # set True behind HTTPS in deployment (sub-project #3)
)
```

- [ ] **Step 2: Verify the app imports**

Run: `./venv/Scripts/python.exe -c "import src.main; print('app import ok')"`
Expected: `app import ok`.

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: add signed-cookie SessionMiddleware"
```

---

## Task 5: Rewrite auth.py to MSAL

**Files:**
- Modify: `src/api/auth.py` (full rewrite)

- [ ] **Step 1: Replace the file contents**

Replace the entire contents of `src/api/auth.py` with:

```python
import asyncio
import msal
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.config import settings
from src.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Delegated Microsoft Graph scopes. MSAL adds the reserved openid/profile/offline_access.
SCOPES = ["User.Read", "Mail.Read", "Mail.Send", "Calendars.ReadWrite"]


def _build_msal_app(cache: msal.SerializableTokenCache | None = None) -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.ms_client_id,
        authority=settings.ms_authority,
        client_credential=settings.ms_client_secret.get_secret_value(),
        token_cache=cache,
    )


@router.get("/login")
async def login(request: Request):
    app = _build_msal_app()
    flow = await asyncio.to_thread(
        app.initiate_auth_code_flow, SCOPES, redirect_uri=settings.ms_redirect_uri
    )
    request.session["auth_flow"] = flow  # carries state + PKCE verifier
    return RedirectResponse(flow["auth_uri"])


@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    flow = request.session.pop("auth_flow", None)
    if not flow:
        return JSONResponse({"detail": "No auth flow in session. Start at /auth/login."}, status_code=400)

    cache = msal.SerializableTokenCache()
    app = _build_msal_app(cache)
    result = await asyncio.to_thread(
        app.acquire_token_by_auth_code_flow, flow, dict(request.query_params)
    )
    if "error" in result:
        return JSONResponse(
            {"detail": result.get("error_description", result["error"])}, status_code=400
        )

    claims = result.get("id_token_claims", {})
    email = (claims.get("preferred_username") or claims.get("email") or "").lower()
    account_id = claims.get("oid") or claims.get("sub")
    if not email:
        return JSONResponse({"detail": "Could not read account email from Microsoft."}, status_code=400)

    res = await db.execute(select(User).where(User.email == email))
    user = res.scalars().first()
    if user is None:
        user = User(email=email)
        db.add(user)
    user.ms_token_cache = cache.serialize()
    user.ms_account_id = account_id
    await db.commit()
    await db.refresh(user)

    request.session["user_id"] = str(user.id)
    return RedirectResponse("/")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
```

- [ ] **Step 2: Verify the app imports**

Run: `./venv/Scripts/python.exe -c "import src.main; print('app import ok')"`
Expected: `app import ok`.

- [ ] **Step 3: Commit**

```bash
git add src/api/auth.py
git commit -m "feat: rewrite auth to MSAL login/callback/logout"
```

---

## Task 6: Add the /auth/me identity endpoint

**Files:**
- Modify: `src/api/auth.py`

- [ ] **Step 1: Add the endpoint**

In `src/api/auth.py`, add an import for the dependency near the top:

```python
from src.api.deps import current_user
```

Add this route at the end of the file:

```python
@router.get("/me")
async def me(user: User = Depends(current_user)):
    """Return the signed-in user's identity (used by the frontend to show login state)."""
    return {"authenticated": True, "email": user.email}
```

- [ ] **Step 2: Verify the app imports**

Run: `./venv/Scripts/python.exe -c "import src.main; print('app import ok')"`
Expected: `app import ok`.

- [ ] **Step 3: Commit**

```bash
git add src/api/auth.py
git commit -m "feat: add /auth/me identity endpoint"
```

---

## Task 7: Frontend sign-in control

**Files:**
- Modify: `src/static/index.html`

- [ ] **Step 1: Add the auth area to the header**

In `src/static/index.html`, the `<nav>` block ends with the Daily Schedule button. Add an auth span immediately before `</nav>`:

```html
    <span id="authArea" style="margin-left:16px;font-size:.8rem;display:flex;align-items:center"></span>
```

- [ ] **Step 2: Add the checkAuth function and call it on load**

In the `<script>` block, add this function right after the existing `esc(...)` function:

```javascript
  async function checkAuth() {
    const el = document.getElementById('authArea');
    try {
      const res = await fetch(API + '/auth/me');
      if (res.ok) {
        const data = await res.json();
        el.innerHTML = 'Signed in as ' + esc(data.email) +
          ' &middot; <a href="/auth/logout" style="color:#93c5fd">Sign out</a>';
      } else {
        el.innerHTML = '<a href="/auth/login" style="color:#93c5fd;font-weight:600">Sign in with Microsoft</a>';
      }
    } catch (e) {
      el.innerHTML = '<a href="/auth/login" style="color:#93c5fd;font-weight:600">Sign in with Microsoft</a>';
    }
  }
```

Then, at the very end of the `<script>` block (just before `</script>`), add:

```javascript
  checkAuth();
```

- [ ] **Step 3: Structural verification**

Run these read-only checks:
- `grep -c "function checkAuth(" src/static/index.html` → expect `1` (the definition)
- `grep -c "authArea" src/static/index.html` → expect `2` (the `id="authArea"` markup + the `getElementById('authArea')` reference)
- `grep -c "^  checkAuth();" src/static/index.html` → expect `1` (the trailing call on its own line)

- [ ] **Step 4: Commit**

```bash
git add src/static/index.html
git commit -m "feat: add Sign in with Microsoft control to header"
```

---

## Final verification

### Automated
- [ ] `./venv/Scripts/python.exe -m unittest tests.test_outlook_auth -v` → all PASS (7 tests).
- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

### Prerequisite — Azure app registration (manual, one-time)
1. portal.azure.com → **Microsoft Entra ID** → **App registrations** → **New registration**.
2. Supported account types: **"Accounts in any organizational directory and personal Microsoft accounts"**.
3. Redirect URI → platform **Web** → `http://localhost:8000/auth/callback`. Register.
4. Copy **Application (client) ID** → `MS_CLIENT_ID`.
5. **Certificates & secrets** → **New client secret** → copy the **Value** → `MS_CLIENT_SECRET`.
6. **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated**: `User.Read`, `Mail.Read`, `Mail.Send`, `Calendars.ReadWrite`.
7. Add to `.env`:
   ```
   MS_CLIENT_ID=<client id>
   MS_CLIENT_SECRET=<secret value>
   MS_REDIRECT_URI=http://localhost:8000/auth/callback
   SESSION_SECRET=<any long random string>
   ```

### Reset the dev schema (no migrations yet)
The `users` table needs the new `ms_*` columns and `create_all` cannot alter an existing table. Since this branch starts fresh accounts, drop and recreate the dev tables once. Create `reset_schema.py` at the repo root:

```python
import asyncio
from src.database import engine, Base
import src.main  # registers all models

async def go():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("schema reset")

asyncio.run(go())
```
Run: `./venv/Scripts/python.exe reset_schema.py` → `schema reset`. Then delete the file.

### Manual login test
- [ ] Start the app: `./venv/Scripts/python.exe -m uvicorn src.main:app --reload`.
- [ ] Open `http://localhost:8000` → header shows **"Sign in with Microsoft"**.
- [ ] Click it → complete the Microsoft consent screen → you're redirected back to `/`.
- [ ] Header now shows **"Signed in as &lt;your email&gt; · Sign out"**; `GET /auth/me` returns `{"authenticated": true, "email": "…"}`.
- [ ] Click **Sign out** → header returns to the sign-in link; `/auth/me` returns 401.
