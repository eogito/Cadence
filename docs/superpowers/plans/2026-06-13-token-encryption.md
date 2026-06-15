# Token Encryption at Rest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encrypt each user's Outlook MSAL token cache at rest with Fernet, and make session cookies `Secure` in production.

**Architecture:** A small `crypto` helper (Fernet, keyed by `settings.token_encryption_key`) encrypts `ms_token_cache` on write (OAuth callback + token refresh) and decrypts on read (`get_access_token`). Undecryptable values are treated as an expired session → the user re-signs in. Session cookies set `https_only` when `environment == "production"`.

**Tech Stack:** Python 3.12, `cryptography` (Fernet, already installed), FastAPI/Starlette, MSAL. Tests: stdlib `unittest` — `./venv/Scripts/python.exe -m unittest <module>`.

---

## File Structure

- `src/config.py` — add `token_encryption_key` (dev default; prod overrides via env).
- `src/services/crypto.py` — **new**: `encrypt_token` / `decrypt_token`.
- `src/api/auth.py` — encrypt the cache in the OAuth callback.
- `src/services/ms_auth.py` — decrypt on read, encrypt on refresh-persist.
- `src/main.py` — `SessionMiddleware` `https_only` gated on environment.
- `tests/test_crypto.py` — **new**: round-trip + failure-mode unit tests.

---

## Task 1: Config key + crypto helper

**Files:**
- Modify: `src/config.py`
- Create: `src/services/crypto.py`
- Test: `tests/test_crypto.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_crypto.py`:

```python
"""Tests for token encryption (stdlib unittest)."""
import unittest

from src.services.crypto import encrypt_token, decrypt_token


class CryptoTests(unittest.TestCase):
    def test_round_trip(self):
        secret = '{"AccessToken": {"x": "y"}}'
        self.assertEqual(decrypt_token(encrypt_token(secret)), secret)

    def test_ciphertext_differs_from_plaintext(self):
        secret = "sensitive-token-cache"
        self.assertNotEqual(encrypt_token(secret), secret)

    def test_decrypt_garbage_returns_none(self):
        self.assertIsNone(decrypt_token("not-a-valid-fernet-token"))

    def test_decrypt_legacy_plaintext_returns_none(self):
        self.assertIsNone(decrypt_token('{"AccessToken": {}}'))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_crypto -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.crypto'`.

- [ ] **Step 3: Add the config field**

In `src/config.py`, add this field to `Settings` (after the session/MS settings; `SecretStr` is already imported). The default is a real, valid Fernet key for **dev only — production must override `TOKEN_ENCRYPTION_KEY`**:

```python
    token_encryption_key: SecretStr = SecretStr("WAApm14ZalIw7D8_oYAH5nw1NW0cOqUCBv4qXyV8I5M=")  # dev-only; override in prod
```

- [ ] **Step 4: Create the crypto helper**

Create `src/services/crypto.py`:

```python
from cryptography.fernet import Fernet, InvalidToken
from src.config import settings


def _fernet() -> Fernet:
    return Fernet(settings.token_encryption_key.get_secret_value().encode())


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token-cache string for storage at rest."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str | None:
    """Decrypt a stored token cache. Returns None if it can't be decrypted
    (wrong/rotated key, corruption, or a legacy plaintext value)."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_crypto -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/config.py src/services/crypto.py tests/test_crypto.py
git commit -m "feat: add Fernet token encryption helper and config key"
```

---

## Task 2: Encrypt on write, decrypt on read

**Files:**
- Modify: `src/api/auth.py`
- Modify: `src/services/ms_auth.py`

- [ ] **Step 1: Encrypt in the OAuth callback**

In `src/api/auth.py`, add the import `from src.services.crypto import encrypt_token`. In the `callback` handler, change the line that stores the cache:

```python
    user.ms_token_cache = cache.serialize()
```

to:

```python
    user.ms_token_cache = encrypt_token(cache.serialize())
```

- [ ] **Step 2: Decrypt on read + encrypt on refresh in ms_auth.py**

In `src/services/ms_auth.py`, add the import `from src.services.crypto import encrypt_token, decrypt_token`. In `MicrosoftAuthService.get_access_token`:

Replace the cache-load block:

```python
        cache = msal.SerializableTokenCache()
        if user.ms_token_cache:
            cache.deserialize(user.ms_token_cache)
        app = build_msal_app(cache)
```

with:

```python
        cache = msal.SerializableTokenCache()
        if user.ms_token_cache:
            raw = decrypt_token(user.ms_token_cache)
            if raw is None:
                raise PermissionError("Microsoft session expired — sign in again.")
            cache.deserialize(raw)
        app = build_msal_app(cache)
```

Replace the refresh-persist block:

```python
        if cache.has_state_changed:
            new_cache = cache.serialize()
            user.ms_token_cache = new_cache
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(User).where(User.id == user.id).values(ms_token_cache=new_cache)
                )
                await db.commit()
```

with:

```python
        if cache.has_state_changed:
            encrypted = encrypt_token(cache.serialize())
            user.ms_token_cache = encrypted
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(User).where(User.id == user.id).values(ms_token_cache=encrypted)
                )
                await db.commit()
```

- [ ] **Step 3: Verify import + tests still pass**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
Run: `./venv/Scripts/python.exe -m unittest tests.test_crypto tests.test_outlook_mail tests.test_outlook_auth -v` → all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/api/auth.py src/services/ms_auth.py
git commit -m "feat: encrypt ms_token_cache at rest"
```

---

## Task 3: Secure session cookies in production

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Gate https_only on environment**

In `src/main.py`, change the `SessionMiddleware` registration (added in the Outlook work) from `https_only=False` to:

```python
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret.get_secret_value(),
    same_site="lax",
    https_only=(settings.environment == "production"),
)
```

- [ ] **Step 2: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: secure session cookies in production"
```

---

## Final verification

### Automated
- [ ] `./venv/Scripts/python.exe -m unittest tests.test_crypto tests.test_outlook_mail tests.test_outlook_auth tests.test_data_isolation tests.test_email_sections tests.test_email_routing -v` → all PASS.
- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

### Manual
- [ ] Set `.env` `TOKEN_ENCRYPTION_KEY` to a freshly generated key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) — or leave the dev default for local testing.
- [ ] Sign in with a Microsoft account, then inspect the row in Postgres: `select left(ms_token_cache, 40) from users;` → the value is opaque Fernet ciphertext (starts with `gAAAAA`), **not** readable JSON.
- [ ] Use the app (Run AI / read mail) → it still works (the decrypt → refresh → re-encrypt path runs).
- [ ] Sign out and back in → still works.
- [ ] (Key-rotation behavior) Change `TOKEN_ENCRYPTION_KEY` to a different key and restart → the next request returns 401 / prompts re-sign-in (old cache no longer decryptable), and signing in again stores a fresh encrypted cache. Restore your key afterward if you want to keep sessions.
