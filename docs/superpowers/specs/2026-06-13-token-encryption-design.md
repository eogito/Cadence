# Token Encryption at Rest — Design Spec

- **Date:** 2026-06-13
- **Status:** Approved design, pending spec review
- **Branch:** `feature/token-encryption` (off `main`)
- **Scope:** Sub-project #3 (first slice) of the public-launch program: encrypt stored Outlook OAuth tokens at rest, and make session cookies secure in production. Alembic migrations are a separate later slice.

## Problem / Motivation

Each signed-in user's MSAL token cache — which contains their Outlook **refresh token** (long-lived mailbox access) — is stored in `users.ms_token_cache` as **plaintext**. For a public app holding many users' tokens, a database leak would expose every user's mailbox. Tokens must be encrypted at rest. Separately, session cookies are currently sent with `https_only=False`, which is unsafe over real HTTPS in production.

## Goals

- `ms_token_cache` is encrypted before it touches the database and decrypted only in memory when needed.
- A leaked database dump does not reveal usable tokens without the separate encryption key.
- Session cookies set the `Secure` flag in production.
- Dev and tests keep working without external setup (a documented insecure default key).

## Non-goals (later slices)

- Alembic migrations (separate slice).
- Encrypting other columns, key rotation tooling, or a secrets manager (env var is sufficient for now).
- Deployment itself (#5).

## Approach

Use **Fernet** symmetric encryption from the `cryptography` package (already a dependency, `cryptography==48.0.1`). Fernet gives authenticated encryption with a simple `encrypt(bytes) -> token` / `decrypt(token) -> bytes` API and a standard key format (32 url-safe-base64 bytes).

The token cache is written in two places and read in one; we wrap all three with a small crypto helper so encryption is centralized.

## Components

### 1. Config — `src/config.py`
Add a `token_encryption_key: SecretStr` field whose **default is one valid Fernet key generated once** (via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) and pasted in as the literal default — clearly commented as **dev-only, insecure**. This lets the app and tests run without setup; production overrides it via the `TOKEN_ENCRYPTION_KEY` env var. (The implementation plan will contain the actual generated literal.)

### 2. Crypto helper — `src/services/crypto.py` (new)
```python
from cryptography.fernet import Fernet, InvalidToken
from src.config import settings

def _fernet() -> Fernet:
    return Fernet(settings.token_encryption_key.get_secret_value().encode())

def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()

def decrypt_token(ciphertext: str) -> str | None:
    """Return the decrypted string, or None if it can't be decrypted
    (wrong key, corrupted, or a legacy plaintext value)."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None
```

### 3. Encrypt on write
- `src/api/auth.py` callback: change `user.ms_token_cache = cache.serialize()` → `user.ms_token_cache = encrypt_token(cache.serialize())`.
- `src/services/ms_auth.py` refresh-persist: encrypt the serialized cache before the `UPDATE` and before setting `user.ms_token_cache`.

### 4. Decrypt on read
- `src/services/ms_auth.py` `get_access_token`: when loading, `raw = decrypt_token(user.ms_token_cache)`; if `raw` is None (undecryptable / legacy plaintext) raise `PermissionError("Microsoft session expired — sign in again.")` so the user re-authenticates and a fresh, encrypted cache is stored. Otherwise `cache.deserialize(raw)`.

### 5. Secure cookies — `src/main.py`
Change the `SessionMiddleware` to set `https_only` based on environment:
```python
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret.get_secret_value(),
    same_site="lax",
    https_only=(settings.environment == "production"),
)
```

## Data flow (sign-in → API call)
1. OAuth callback serializes the MSAL cache → `encrypt_token(...)` → stored ciphertext in `ms_token_cache`.
2. A later request needs Graph → `get_access_token` reads `ms_token_cache` → `decrypt_token(...)` → deserialized in memory → silent token refresh → re-encrypt + persist if the cache rotated.
3. The plaintext token never rests on disk.

## Error handling
- Undecryptable `ms_token_cache` (legacy plaintext, wrong/rotated key) → treated as "no valid session" → 401 → user re-signs in, producing a fresh encrypted cache.
- Missing `TOKEN_ENCRYPTION_KEY` in production is an operational mistake; the insecure default still functions but must be overridden (documented).

## Testing
- Unit (`tests/test_crypto.py`, stdlib `unittest`): `decrypt_token(encrypt_token(s)) == s` round-trip; `encrypt_token(s) != s` (actually encrypted); `decrypt_token("not-a-token")` and `decrypt_token(<plaintext>)` return `None`.
- Manual: sign in fresh; inspect `users.ms_token_cache` in Postgres → it is opaque ciphertext, not readable JSON; the app still reads mail/calendar (decrypt path works); sign out/in still works.

## Edge cases
- Existing dev rows with plaintext caches → first `get_access_token` returns None on decrypt → 401 → re-login re-stores encrypted. No migration script needed.
- Rotating the key later invalidates all stored caches → everyone re-authenticates once (acceptable; documented as the rotation behavior).
