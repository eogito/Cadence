# Gmail Section Tracking — Design Spec

- **Date:** 2026-06-11
- **Status:** Approved design, pending spec review
- **Area:** Email-fetching (Process Latest Email + Morning Briefing)

## Problem / Motivation

Gmail sorts inbox mail into tabs/categories — Primary, Social, Promotions, Updates, Forums. Today the app's email-fetching ignores these: "Process latest email" grabs the absolute latest message and the Morning Briefing scans all unread mail, so promotions and social noise get processed alongside real mail. Users should be able to choose which sections the app tracks.

## Goals

- Let the user select which Gmail sections to include in email tracking.
- Apply the selection to both inbox-scan operations: Process Latest Email and Morning Briefing.
- Persist the preference per user, with a sensible noise-reducing default.

## Non-goals

- Filtering Meeting Prep (a targeted search by a specific sender — stays unfiltered).
- Per-operation section settings (one global selection applies to all in-scope scans).
- Gmail sub-categories beyond the five standard tabs (e.g. Purchases, Reservations).

## Decisions (from brainstorming)

- **Scope:** Process Latest Email + Morning Briefing. Meeting Prep unchanged.
- **Default (when unset):** `["primary", "updates"]`.
- **Valid sections:** `["primary", "social", "promotions", "updates", "forums"]`.

## Storage

The app auto-creates tables via `Base.metadata.create_all` on startup, which creates missing tables but does NOT alter existing ones, and there is no Alembic. Adding a column to the existing `users` table would not take effect for the current user. Therefore use a **new table** (auto-created cleanly).

New model `EmailPreferences` in `src/models/email_preferences.py`:
- `id` (UUID PK)
- `user_id` (UUID, unique — one row per user)
- `tracked_categories` (JSONB, list of strings)
- `updated_at` (timestamp)

When no row exists for a user, callers treat the preference as the default `["primary", "updates"]`. Import the model in `src/main.py` (next to the other `import src.models.*` lines) so `create_all` registers it.

## Gmail query building

A pure helper `build_category_filter(categories: list[str]) -> str` (in `src/services/gmail_service.py`):

| Input | Output |
|-------|--------|
| `["primary"]` | `category:primary` |
| `["primary","updates"]` | `(category:primary OR category:updates)` |
| all five categories | `""` (no filter — matches everything) |
| `[]` (empty) | `"category:__none__"` (a sentinel that matches no mail) |

Rationale: selecting every section is equivalent to no filter, so we emit an empty string to avoid over-constraining. An empty selection is an explicit "track nothing" choice, so we emit a query guaranteed to return zero results.

Callers compose it:
- Trigger: `q = build_category_filter(cats)` passed to `messages.list` (skip the `q` kwarg entirely when the filter is `""`).
- Briefing: combine with unread → `("is:unread " + filter).strip()`, e.g. `is:unread (category:primary OR category:updates)`; when filter is `""`, just `is:unread`.

## Integration points

1. **Process Latest Email** (`src/api/test.py`): load the user's `tracked_categories` (or default), build the filter, and pass it as the `q` to `messages.list(userId='me', maxResults=1, q=<filter>)`. If the list returns no messages, return the existing "No emails found" style message (worded for tracked sections).
2. **Morning Briefing** (`src/services/gmail_service.py` `get_unread_emails`): add an optional `categories: Optional[list[str]] = None` parameter. When provided, build the combined `is:unread <filter>` query; when `None`, keep current `q="is:unread"`. The briefing endpoint (`src/api/briefing.py`) loads the user's prefs and passes them.
3. **Meeting Prep**: unchanged.

## API

New router `src/api/settings.py` (mounted in `src/main.py`), prefix `/settings`:
- `GET /settings/email-sections?email=<email>` → `{ "tracked_categories": [...] }`. Returns the stored list, or the default `["primary","updates"]` if no row exists. 404 if the user does not exist.
- `PUT /settings/email-sections` → body `{ email, tracked_categories: [...] }`. Validates every value is in the allowed set (else 400). Upserts the `EmailPreferences` row. Returns the saved list.

## Frontend

In `src/static/index.html`, add an **"Email Sections to Track"** card to the existing **"My Rules"** tab:
- Five checkboxes (Primary, Social, Promotions, Updates, Forums).
- A short helper line: deselecting a section excludes it from what the AI scans.
- A **Save** button calling `PUT /settings/email-sections`.
- On tab load (within the existing `loadRulesTab()` flow, or a dedicated loader), fetch `GET /settings/email-sections` and check the boxes accordingly.

## Testing

- Unit tests (stdlib `unittest`, no network) for `build_category_filter`: empty, single, two, all-five, and an unknown-order input; plus the briefing composition (`is:unread (...)` and the `""` → `is:unread` case).
- Validation: a `PUT` with an invalid category returns 400 (can be checked by reading the validation helper; full HTTP test optional given no test client is set up).

## Edge cases

- Empty selection → `category:__none__` sentinel → scans return zero emails; the trigger/briefing surface a friendly "no emails in your tracked sections" message rather than an error.
- Unknown category in `PUT` → 400 with the allowed list.
- All five selected → no filter (everything), identical to today's behavior.
- Missing `EmailPreferences` row → default `["primary","updates"]` everywhere.
