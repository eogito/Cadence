# Deployment (Render) — Design Spec

- **Date:** 2026-06-13
- **Status:** Approved design, pending spec review
- **Branch:** `feature/deployment` (off `feature/token-encryption`)
- **Scope:** Sub-project #5 of the public-launch program: get the app live on Render as a single web instance backed by managed Postgres, over HTTPS, with Microsoft sign-in working against the production URL.

## Problem / Motivation

The app runs only on localhost. To be usable by anyone it needs a public, HTTPS URL with a managed database and the production OAuth redirect registered. This slice produces the deploy artifacts (Dockerfile, `render.yaml`), the small code/config needed for a hosted single instance, and a manual runbook for the parts that happen in the Render and Entra dashboards.

## Goals

- The app is reachable at a public HTTPS URL on Render, backed by Render managed Postgres.
- Microsoft sign-in works against the production redirect URI; the end-to-end flow (sign in → Run AI → approve → Outlook event) works in production.
- Single web instance, single worker — so the in-process scheduler and `MemorySaver` stay correct.
- Repeatable deploys from GitHub (`render.yaml` blueprint + Dockerfile).

## Non-goals (later)

- Horizontal scaling / multi-instance (single instance by decision).
- Alembic migrations (`create_all` on startup is sufficient for now), rate limiting (#4), Microsoft publisher verification + privacy policy (#6), custom domain, CI/CD pipelines.

## Decisions (from brainstorming)

- **Host:** Render. **Build:** Dockerfile (reproducible given the heavy `chromadb`/`onnxruntime` deps), referenced by a `render.yaml` blueprint. **Topology:** one web service (1 worker) + one managed Postgres.

## Components

### 1. `Dockerfile` (new, repo root)
- `FROM python:3.12-slim`; set workdir `/app`.
- Install OS build deps only if needed: `apt-get install -y --no-install-recommends build-essential` (some wheels), then clean apt lists. (If the build succeeds without it, omit to keep the image small.)
- `COPY requirements.txt` → `pip install --no-cache-dir -r requirements.txt` → `COPY src/ ./src/`.
- `EXPOSE 8000`; default `CMD` runs uvicorn (overridden by `render.yaml` start command): `uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1`.

### 2. `render.yaml` (new, repo root) — blueprint
- A `pserv`/`web` service: `runtime: docker`, `dockerfilePath: ./Dockerfile`, `healthCheckPath: /health`, `startCommand: uvicorn src.main:app --host 0.0.0.0 --port $PORT --workers 1`, `numInstances: 1`.
- A `databases:` entry for managed Postgres.
- `envVars:` declares the keys; secrets are set in the dashboard (`sync: false`), and `DATABASE_URL` is wired `fromDatabase` to the Postgres instance. `ENVIRONMENT=production` and `RUN_SCHEDULER=true` set inline.

### 3. Scheduler gate — `src/config.py` + `src/main.py`
- Add `run_scheduler: bool = True` to `Settings` (env `RUN_SCHEDULER`).
- In the `lifespan`, only call `scheduler.start()` and `await load_all_rules()` when `settings.run_scheduler` is true. (`rebuild_chroma_from_db()` and `create_all` always run.)

### 4. DATABASE_URL normalization — `src/database.py`
Render's `DATABASE_URL` is `postgresql://…`; SQLAlchemy + asyncpg needs `postgresql+asyncpg://…`. Normalize at engine creation:
```python
url = settings.database_url
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
engine = create_async_engine(url, ...)
```
Use Render's **internal** database URL (same region → no SSL parameters needed). This makes the app accept either URL form, removing a manual-conversion footgun.

### 5. Production config already in place
- `https_only` cookies switch on via `environment == "production"` (token-encryption slice).
- `TOKEN_ENCRYPTION_KEY`, `SESSION_SECRET` read from env — set fresh values in Render.
- `/health` endpoint already exists for Render's health check.
- Chroma writes to ephemeral `data/chroma`; rebuilt from Postgres on each startup — no persistent disk required.

## Environment variables (set in Render)
`DATABASE_URL` (fromDatabase, internal), `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_REDIRECT_URI` = `https://<app>.onrender.com/auth/callback`, `MS_AUTHORITY` = `https://login.microsoftonline.com/common`, `SESSION_SECRET` (fresh), `TOKEN_ENCRYPTION_KEY` (fresh, `Fernet.generate_key()`), `GROQ_API_KEY`, `ENVIRONMENT=production`, `RUN_SCHEDULER=true`. (`OPENAI_API_KEY` only if still referenced.)

## Manual runbook (dashboard steps; documented in the plan)
1. Ensure the deploy artifacts are merged to the branch Render builds (`main` recommended).
2. Render → **New → Blueprint** → connect the GitHub repo → it reads `render.yaml`, creating the web service + Postgres.
3. Set the secret env vars (generate fresh `SESSION_SECRET` and `TOKEN_ENCRYPTION_KEY`).
4. Wait for the first deploy; note the app URL `https://<app>.onrender.com`.
5. Entra → app registration → **Authentication** → add redirect URI `https://<app>.onrender.com/auth/callback`; set `MS_REDIRECT_URI` env to match; redeploy if changed.
6. Open the URL → sign in with Microsoft → smoke test: Run AI on an Outlook email → approve → confirm the event in Outlook calendar.

## Error handling / gotchas
- **Redirect URI mismatch** → Microsoft error; the Entra redirect URI must exactly equal `MS_REDIRECT_URI` (https, no trailing slash).
- **Wrong DB URL form** → handled by the normalizer.
- **Free tier**: web service sleeps when idle (cold starts) and free Postgres expires (~90 days); use a paid tier for a real launch. (Operational, not code.)
- **First request after deploy** runs `create_all` + `rebuild_chroma_from_db` (empty on a fresh DB) — expected.

## Testing
- Unit (extend an existing test or add `tests/test_deployment_config.py`): the DATABASE_URL normalizer turns `postgresql://x` into `postgresql+asyncpg://x` and leaves an already-`+asyncpg` URL unchanged; `run_scheduler` defaults to true.
- Local import check: `import src.main` still works (Docker not required to validate the Python).
- **Manual production smoke test:** the runbook step 6 — sign in and complete an email→calendar cycle on the live URL.

## Edge cases
- `RUN_SCHEDULER=false` (e.g., if a separate scheduler process is added later) → web instance skips scheduler start; rule registration calls would no-op against a non-started scheduler (acceptable; only relevant in the future multi-process setup).
- Render build memory limits with `onnxruntime` — if the Docker build OOMs on a small plan, bump the build instance or the service plan (documented).
