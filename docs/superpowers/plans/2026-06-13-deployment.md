# Deployment (Render) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the artifacts and config to run the app on Render as a single HTTPS web instance + managed Postgres, and document the manual deploy runbook.

**Architecture:** A `Dockerfile` builds the app; a `render.yaml` blueprint declares a one-instance web service + Postgres and wires env vars. A `RUN_SCHEDULER` gate keeps the in-process scheduler safe, and a `DATABASE_URL` normalizer accepts Render's `postgresql://` form. The live deploy itself is a manual dashboard runbook.

**Tech Stack:** Python 3.12, FastAPI, Docker, Render (Docker runtime + managed Postgres), asyncpg. Tests: stdlib `unittest` — `./venv/Scripts/python.exe -m unittest <module>`.

**Sequencing note:** Render builds from a GitHub branch (recommended `main`). Before the manual runbook, consolidate this branch (and the prior launch slices) to `main` and push. The code tasks below can be built/tested first; the runbook is performed after merge + push.

---

## File Structure

- `src/config.py` — add `run_scheduler` setting.
- `src/database.py` — normalize the DB URL to the asyncpg driver.
- `src/main.py` — gate the scheduler on `run_scheduler`.
- `Dockerfile` — **new** (repo root).
- `.dockerignore` — **new** (repo root).
- `render.yaml` — **new** (repo root).
- `tests/test_deployment_config.py` — **new**: URL normalizer + scheduler-default unit tests.

---

## Task 1: Config flag + DB URL normalizer

**Files:**
- Modify: `src/config.py`
- Modify: `src/database.py`
- Test: `tests/test_deployment_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_deployment_config.py`:

```python
"""Deployment config: DB URL normalization + scheduler default (stdlib unittest)."""
import unittest

from src.database import _normalize_async_url
from src.config import settings


class DeploymentConfigTests(unittest.TestCase):
    def test_plain_postgres_url_gets_asyncpg_driver(self):
        self.assertEqual(
            _normalize_async_url("postgresql://u:p@host:5432/db"),
            "postgresql+asyncpg://u:p@host:5432/db",
        )

    def test_asyncpg_url_unchanged(self):
        url = "postgresql+asyncpg://u:p@host:5432/db"
        self.assertEqual(_normalize_async_url(url), url)

    def test_run_scheduler_defaults_true(self):
        self.assertTrue(settings.run_scheduler)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m unittest tests.test_deployment_config -v`
Expected: FAIL — `_normalize_async_url` doesn't exist / `run_scheduler` missing.

- [ ] **Step 3: Add the config flag**

In `src/config.py`, add to `Settings` (near `environment`):

```python
    run_scheduler: bool = True
```

- [ ] **Step 4: Add the normalizer and use it**

In `src/database.py`, add the helper above the engine creation and wrap the URL:

```python
def _normalize_async_url(url: str) -> str:
    """Render/managed Postgres gives 'postgresql://'; SQLAlchemy+asyncpg needs the
    '+asyncpg' driver. Rewrite the scheme so either form works."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url
```

Then change the engine line from `create_async_engine(settings.database_url, ...)` to use `_normalize_async_url(settings.database_url)`:

```python
engine = create_async_engine(
    _normalize_async_url(settings.database_url),
    echo=(settings.environment == "development"),
    future=True,
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `./venv/Scripts/python.exe -m unittest tests.test_deployment_config -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/config.py src/database.py tests/test_deployment_config.py
git commit -m "feat: add run_scheduler flag and DATABASE_URL normalizer"
```

---

## Task 2: Gate the scheduler

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Gate scheduler start/shutdown**

In `src/main.py` `lifespan`, wrap the scheduler calls. Change the startup section:

```python
    # Start scheduler and load saved recurring rules
    scheduler.start()
    await load_all_rules()
    await rebuild_chroma_from_db()
```

to:

```python
    # Start scheduler and load saved recurring rules (single-process only)
    if settings.run_scheduler:
        scheduler.start()
        await load_all_rules()
    await rebuild_chroma_from_db()
```

And change the shutdown line `scheduler.shutdown(wait=False)` to:

```python
    if settings.run_scheduler:
        scheduler.shutdown(wait=False)
```

(`settings` is already imported in `main.py`.)

- [ ] **Step 2: Verify import**

Run: `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: gate scheduler behind RUN_SCHEDULER"
```

---

## Task 3: Dockerfile + .dockerignore

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create the Dockerfile**

Create `Dockerfile` at the repo root:

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install Python dependencies first for layer caching
COPY requirements.txt .
RUN pip install -r requirements.txt

# App code
COPY src/ ./src/

EXPOSE 8000
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
```

- [ ] **Step 2: Create .dockerignore**

Create `.dockerignore` at the repo root:

```
venv/
.venv/
__pycache__/
*.pyc
.git/
.gitignore
data/
docs/
tests/
.env
*.md
.pytest_cache/
htmlcov/
```

- [ ] **Step 3: Verify the Dockerfile parses (optional — only if Docker is installed locally)**

If Docker is available: `docker build -t cadence .` should succeed. If Docker isn't installed locally, skip — Render builds the image. Confirm the files exist:
`ls Dockerfile .dockerignore`

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat: add Dockerfile and .dockerignore for containerized deploy"
```

---

## Task 4: render.yaml blueprint

**Files:**
- Create: `render.yaml`

- [ ] **Step 1: Create render.yaml**

Create `render.yaml` at the repo root:

```yaml
services:
  - type: web
    name: cadence
    runtime: docker
    dockerfilePath: ./Dockerfile
    plan: free          # bump to "starter" for an always-on launch
    numInstances: 1
    healthCheckPath: /health
    startCommand: uvicorn src.main:app --host 0.0.0.0 --port $PORT --workers 1
    envVars:
      - key: ENVIRONMENT
        value: production
      - key: RUN_SCHEDULER
        value: "true"
      - key: MS_AUTHORITY
        value: https://login.microsoftonline.com/common
      - key: DATABASE_URL
        fromDatabase:
          name: cadence-db
          property: connectionString
      - key: MS_CLIENT_ID
        sync: false
      - key: MS_CLIENT_SECRET
        sync: false
      - key: MS_REDIRECT_URI
        sync: false
      - key: SESSION_SECRET
        sync: false
      - key: TOKEN_ENCRYPTION_KEY
        sync: false
      - key: GROQ_API_KEY
        sync: false

databases:
  - name: cadence-db
    plan: free          # free Postgres expires ~90 days; bump for a real launch
```

- [ ] **Step 2: Validate YAML parses**

Run: `./venv/Scripts/python.exe -c "import yaml; yaml.safe_load(open('render.yaml')); print('render.yaml ok')"`
Expected: `render.yaml ok`. (PyYAML is already installed.)

- [ ] **Step 3: Commit**

```bash
git add render.yaml
git commit -m "feat: add Render blueprint (web service + Postgres)"
```

---

## Final verification

### Automated
- [ ] `./venv/Scripts/python.exe -m unittest tests.test_deployment_config tests.test_crypto tests.test_outlook_mail tests.test_outlook_auth tests.test_data_isolation tests.test_email_sections tests.test_email_routing -v` → all PASS.
- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
- [ ] `ls Dockerfile .dockerignore render.yaml` → all present.

### Consolidate to main (do before the runbook)
```bash
git checkout main
git merge --ff-only feature/deployment   # brings deployment + token-encryption (its parent) onto main
git push origin main
# optional cleanup of fully-merged branches:
git branch -d feature/outlook feature/data-isolation feature/token-encryption feature/deployment
```

### Manual deploy runbook (Render + Entra dashboards)
1. **Render → New → Blueprint** → connect the GitHub repo (`main`). Render reads `render.yaml` and creates the **web service** + **cadence-db** Postgres.
2. When prompted, set the `sync: false` secrets:
   - `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `GROQ_API_KEY` — your existing values.
   - `SESSION_SECRET` and `TOKEN_ENCRYPTION_KEY` — **generate fresh** for prod: `python -c "import secrets;print(secrets.token_urlsafe(48))"` and `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`.
   - `MS_REDIRECT_URI` — set after step 4 (you need the app URL first); temporarily leave blank or use a placeholder, then update.
3. Let the first build/deploy run; note the URL `https://<app>.onrender.com`.
4. **Entra → your app registration → Authentication →** add redirect URI `https://<app>.onrender.com/auth/callback`. Set the `MS_REDIRECT_URI` env var on Render to the exact same value; trigger a redeploy.
5. **Smoke test on the live URL:** open it → signed out shows the sign-in splash → sign in with a real Outlook account → **Run AI** on an email → **Approve** → confirm the event appears in your Outlook calendar.
6. Spot-check `https://<app>.onrender.com/health` returns `{"status":"healthy"}`.

### Notes
- Free web service sleeps when idle (first hit after sleep is slow); free Postgres expires (~90 days). Use the `starter` plans for a real launch (edit `render.yaml` `plan:` values).
- If the Docker build OOMs on `onnxruntime`, raise the service plan or build resources.
