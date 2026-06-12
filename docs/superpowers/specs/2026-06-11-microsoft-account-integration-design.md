# Microsoft Account Integration — Design Spec

- **Date:** 2026-06-11
- **Status:** Approved design, pending spec review
- **Branch:** `feature/outlook` (off `main`)
- **Scope:** Sub-project #1 of the "public webapp" effort (provider swap + real login). Multi-tenant hardening and deployment are separate, later sub-projects.

## Problem / Motivation

The app is hardwired to one Google account: every endpoint identifies the user via an `email=` query param defaulting to a personal address, and all mail/calendar I/O goes through Gmail/Google Calendar. To let anyone use it — and to avoid Google's costly Gmail restricted-scope verification — this branch replaces Google with **Microsoft Graph (Outlook mail + calendar)** and introduces a real **login session** so the app knows who the signed-in user is.

The LangGraph/Groq AI workflow is provider-agnostic and stays unchanged; only the auth and I/O layer changes.

## Goals

- A user signs in with **any Microsoft account** (personal Outlook.com + work/school; `common` authority) and the app reads/writes **their** Outlook mail and calendar.
- All existing mail/calendar features work against Graph: Process Latest Email, Morning Briefing, Meeting Prep, calendar event creation, draft reply send.
- Requests identify the user from a **session**, not an `email=` param.
- The "sections to track" feature is reworked to Outlook's **Focused/Other** inbox model.

## Non-goals (later sub-projects)

- Token encryption at rest; `MemorySaver` → Postgres checkpointer; scheduler-at-scale; Alembic migrations.
- Public deployment (hosting, HTTPS, managed Postgres) and Microsoft production app verification.
- Supporting Google and Microsoft simultaneously (this branch is Outlook-only).

## Decisions (from brainstorming)

- **Replace** Google entirely with Microsoft Graph on this branch.
- **Account types:** personal + work/school (`common` authority).
- **Sections:** Focused/Other toggle (Focused default-on).
- **Graph access:** thin async `httpx` client + `msal` library (not the heavier `msgraph-sdk`).
- **Session:** Starlette `SessionMiddleware` (signed HttpOnly cookie holding `user_id`).

## Architecture

```
Browser ──(Sign in with Microsoft)──> /auth/login ──> Microsoft consent
   ^                                                        │
   └──────── session cookie (user_id) ◄── /auth/callback ◄──┘  (stores MSAL token cache)

Endpoints ──current_user──> MicrosoftAuthService.get_access_token(user)
                                   │ (acquire_token_silent, auto-refresh)
                                   ▼
                         OutlookMailService / OutlookCalendarService (httpx → graph.microsoft.com/v1.0)
                                   │
                                   ▼
                         (unchanged) LangGraph/Groq workflow
```

## Components

### 1. Auth & session — rewrite `src/api/auth.py`
- MSAL `ConfidentialClientApplication`, authority `https://login.microsoftonline.com/common`.
- Scopes: `User.Read Mail.Read Mail.Send Calendars.ReadWrite offline_access`.
- `GET /auth/login` → build the auth-code URL (CSRF state stored in `request.session`) → redirect.
- `GET /auth/callback` → `acquire_token_by_authorization_code`, read identity from `GET /me` (`id`, `mail`/`userPrincipalName`), upsert the `User`, persist the serialized MSAL token cache, set `request.session["user_id"]`, redirect to `/`.
- `GET /auth/logout` → clear the session.
- The in-memory `oauth_state_store` is removed (state lives in the session).
- `SessionMiddleware` is added in `src/main.py` using `settings.session_secret`.

### 2. Token provider — replace `src/services/google_auth.py`
New `src/services/ms_auth.py` with `MicrosoftAuthService`:
- `get_access_token(user) -> str`: build the MSAL app with the user's deserialized token cache, `acquire_token_silent(SCOPES, account)`, persist the (possibly refreshed) cache back to `user.ms_token_cache`, return the bearer token. Raises a clear error if silent acquisition fails (user must re-auth).

### 3. Graph services — replace `gmail_service.py` / `calendar_service.py`
New `src/services/outlook_mail_service.py` (`OutlookMailService`) and `src/services/outlook_calendar_service.py` (`OutlookCalendarService`), async via `httpx`, keeping the **same method names** the app already calls so the workflow/endpoints barely change:
- `get_email_content(user, message_id)` → `GET /me/messages/{id}` (returns `body.content` + `contentType`); reuse the existing `_html_to_text` stripper for HTML bodies.
- `get_unread_emails(user, max_results, classification=None)` → `GET /me/messages?$filter=isRead eq false[ and inferenceClassification eq 'focused']&$top=N&$orderby=receivedDateTime desc`.
- `search_emails_from_sender(user, sender, max_results)` → `$filter=from/emailAddress/address eq '<sender>'`.
- `send_email(user, to, subject, body)` → `POST /me/sendMail`.
- `get_upcoming_events(user, days_ahead)` → `GET /me/calendarView?startDateTime=…&endDateTime=…`.
- `create_event(user, summary, start_time, end_time)` → `POST /me/events` (returns `webLink`).
- A small shared `graph_request` helper attaches the bearer token and targets `https://graph.microsoft.com/v1.0`.
- The HTML→text helper (`_html_to_text` / `_HTMLTextExtractor`) is shared (moved to a small util or kept on the mail service) so HTML email bodies are stripped exactly as today.

### 4. Focused/Other — rework the sections feature
- Repurpose `EmailPreferences.tracked_categories` to store Outlook classifications, e.g. `["focused"]` (default) or `["focused","other"]`. Update `VALID_CATEGORIES`/`DEFAULT_CATEGORIES` to `["focused","other"]` / `["focused"]`.
- Replace `build_category_filter` with `build_classification_filter(classes) -> str` producing the Graph `$filter` fragment: one class → `inferenceClassification eq 'focused'`; both → `""` (no classification filter); empty → a sentinel meaning "fetch nothing" (callers short-circuit, as today).
- "My Rules" card: two checkboxes (Focused, Other) instead of five.

### 5. Endpoints use the session
- New `src/api/deps.py` with `current_user(request, db) -> User` dependency: read `request.session["user_id"]`, load the `User`, 401 if absent.
- Replace the `email=` param with `current_user` in the mail/calendar endpoints: `test.py`, `briefing.py`, `meeting_prep.py`, `settings.py`, and the user-scoped `tasks.py` / `context.py` reads. (A complete sweep of every endpoint is part of sub-project #2; #1 converts the endpoints it touches for the core flows.)
- Frontend (`index.html`): remove the email input fields; add a **"Sign in with Microsoft"** button and a logged-in indicator; calls rely on the session cookie.

### 6. Config & model
- `src/config.py`: add `ms_client_id`, `ms_client_secret: SecretStr`, `ms_authority` (default `https://login.microsoftonline.com/common`), `ms_redirect_uri`, `session_secret: SecretStr`. Remove the Google settings. Keep `groq_api_key`.
- `src/models/user.py`: replace `google_oauth_tokens` with `ms_token_cache` (JSONB/Text) and add `ms_account_id` (String).

## Data flow (Process Latest Email, post-change)
1. Browser (authenticated) → `POST /test/trigger` (no email param).
2. `current_user` resolves the user from the session.
3. `MicrosoftAuthService.get_access_token(user)` → bearer token.
4. `OutlookMailService.get_unread_emails`/latest with the Focused/Other `$filter` → newest message id.
5. Existing `process_new_email` workflow runs unchanged (LLM classify/extract → human review → calendar create via `OutlookCalendarService`).

## Error handling
- Silent token acquisition failure → 401 with "Microsoft session expired — sign in again."
- No session → 401 from `current_user`.
- Graph non-2xx → surface status + Graph error message (no silent swallowing).
- Empty Focused/Other selection → short-circuit to "no emails in your tracked inbox" (mirrors the existing sentinel pattern).

## Testing
- Unit tests (stdlib `unittest`, no network): `build_classification_filter` (focused / both / empty / unknown), and a Graph-message → body mapping using `_html_to_text` on sample `body.content`.
- Graph/network calls are mocked or covered by manual verification.

## Prerequisite (manual, before live testing)
An **Azure app registration**: client id + client secret, redirect URI `http://localhost:8000/auth/callback`, the listed delegated Graph scopes, and "Accounts in any organizational directory and personal Microsoft accounts" (`common`). Implementation will document the exact portal steps; the `.env` gets `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_REDIRECT_URI`, `MS_AUTHORITY`, `SESSION_SECRET`.

## Edge cases
- Work/school tenant that disables a scope → consent fails; surface a clear message.
- Personal account without Focused inbox enabled → treat all inbox mail as "focused".
- HTML-only Outlook message → `_html_to_text` strips it (same as Gmail path today).
- Existing rows with `google_oauth_tokens` are abandoned (this branch starts fresh accounts via Microsoft sign-in).
