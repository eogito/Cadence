# Email Classification & Review Redesign — Design Spec

- **Date:** 2026-06-11
- **Status:** Approved design, pending spec review
- **Area:** "Process Latest Email" workflow (Email → Calendar tab)

## Problem / Motivation

The current `extract_and_plan` planner ([src/workflows/agent.py](../../../src/workflows/agent.py)) always tries to extract tasks and propose calendar events from every email, and **persists tasks to the DB eagerly** (before any approval). This produces unwanted tasks from emails that warrant no action (newsletters, notifications, confirmations). The user wants the service to first **classify** each email and only take action when appropriate.

## Goals

- Classify every processed email and route it into one of four outcomes.
- Only create tasks/calendar events for genuinely actionable emails, and only **after** user approval.
- Surface the **full email body** (readable text) for every result.
- Display proposed event times in **local, human-readable** form rather than raw ISO 8601 UTC.

## Non-goals (out of scope for v1)

- Header/sender heuristics (e.g. `List-Unsubscribe`) — may be added later as a cheap fast-path.
- Importance ranking *within* notifications.
- Batch processing of multiple emails (still one-at-a-time).
- Rendering styled HTML email (we show stripped plain text only — safe, matches what the model sees).

## Categories & behavior

Classification is **multi-label with constraints**: the primary bucket is one of `actionable | notification | promotion`. Within `actionable`, the email may independently warrant a **Calendar Task** and/or a **Response Draft**.

| Category | Trigger | Action | Workflow |
|----------|---------|--------|----------|
| **Calendar Task** (within actionable) | Clear task **and** date — meeting, "fix by X date", a call | Propose a Google Calendar **event** + a Tasks-list **entry** (both created on approval) | Pause for review |
| **Response Draft** (within actionable) | Typical person-to-person communication needing a reply | Generate a suggested reply (editable, sendable) | Pause for review |
| **Notification** | Automated-but-relevant: LinkedIn messages, "an application opened", alerts | None — surfaced so the user can read/dismiss | Pause to surface, Dismiss |
| **Promotion / Confirmation** | Marketing, promos, booking/receipt confirmations | None | Auto-finish, label only (no pause) |

An actionable email can be Calendar Task **and** Response Draft together. Notification and Promotion are standalone (no task/draft).

## Architecture (LangGraph)

Replace the single `planner` entry point with a classify-first pipeline:

```
classifier ──route_after_classification──┐
   promotion ────────────────────────────┴──► END            (no pause, label only)
   notification ──► notification_review (interrupt) ──► END   (pause, Dismiss)
   actionable ───► extractor ──► human_review (interrupt) ──► route_after_human_review
                                                                ├─ approved → executor → END
                                                                ├─ modified → extractor (re-plan)
                                                                └─ rejected → END
```

Nodes:
- **`classifier`** — one cheap LLM call (Groq `llama-3.1-8b-instant`). Returns the primary bucket + a one-line reason. No task extraction.
- **`extractor`** — the refocused current `extract_and_plan`; runs only for actionable mail. Decides `needs_task` (event + task entry, *only if clear task AND date*) and `needs_reply` (draft). Does **not** persist tasks.
- **`notification_review`** — interrupt that surfaces the notification; resume routes to END (acknowledge only, no executor).
- **`human_review`** — existing interrupt for the actionable approval decision.
- **`executor`** — extended: on approve, create the calendar event(s) **and** persist the Tasks-list entries.

Routing functions are pure (state in → string out), so they are unit-testable without a network.

## Data model (src/workflows/state.py)

- **`EmailClassification`** (new): `category: Literal["actionable","notification","promotion"]`, `reason: str`.
- **`EmailAnalysis`** (existing, refocused): `needs_task: bool`, `tasks: list[TaskExtraction]`, `events: list[CalendarProposal]`, `needs_reply: bool`, `suggested_reply: str`. Routing no longer depends on `is_actionable`; `urgency_score` remains on tasks.
- **`AgentState`** gains `classification: Optional[dict]` alongside `analysis`.

## API changes (src/api/approval.py)

`GET /tasks/pending/{thread_id}` becomes category-aware and always returns the full email, even when the graph finished without pausing:

```json
{
  "thread_id": "...",
  "category": "actionable | notification | promotion",
  "reason": "...",
  "status": "pending_approval | notification | no_action",
  "proposed_plan": { ...EmailAnalysis... },          // actionable only
  "email": { "subject": "...", "sender": "...", "body": "<full decoded text>" }
}
```

- `body` is the complete extracted text from the HTML-aware `_decode_body` (not a snippet).
- `POST /tasks/approve` is reused. For notifications, any resume value simply finishes the graph.

`process_new_email` already places `email_content`, `email_subject`, and `sender_email` into the initial state, so the full email is available for all paths.

## Frontend changes (src/static/index.html, Email → Calendar tab)

`loadPlan()` branches on `category`, always showing (a) a category badge and (b) a collapsible full-email panel:

- **Full-email panel** — a `<details>`-style "View full email" section (collapsed by default, scrollable, preserves line breaks) rendered above the category-specific content, for **all** categories.
- **actionable** → existing plan card (tasks/events) + draft box if `needs_reply`.
- **notification** → notification card (sender, subject, reason) with a single **Dismiss** button.
- **promotion** → inline badge "Promotion — no action needed" + reason. No card, no buttons.

**Local time formatting:** add a small JS helper `fmtTime(iso)` using `new Date(iso).toLocaleString()` with readable options (e.g. `Sun Jun 15, 2:00 PM`). Apply it wherever proposed event `start_time`/`end_time` are rendered (currently raw ISO at [index.html:416](../../../src/static/index.html)). Falls back to the raw string if the date is unparseable.

## Persistence change (the core fix)

Move task persistence **out of the planner and into `executor`**, so tasks are written **only when the user approves**. Rejected or non-actionable emails never create tasks. Contact-memory update stays on the actionable (extractor) path only.

## Error handling

- **Empty body guard** (existing): an empty/text-less email short-circuits to `promotion` / no-action without calling the LLM — preserves the no-hallucination guarantee.
- **LLM failures** in `classifier`/`extractor` propagate as a real error to the API/UI (no silent swallowing).

## Testing

- Unit tests (stdlib `unittest`, no network) for the pure routing functions `route_after_classification` and `route_after_human_review` across all categories/decisions.
- Unit test confirming the empty-body guard routes to no-action.
- Existing `tests/test_gmail_body.py` continues to cover body extraction.

## Edge cases

- Empty body → `promotion` / no-action (no LLM call).
- Actionable email with no clear date → `needs_task` false; may still produce a draft if `needs_reply`.
- Notification with no readable body → still surfaced with subject/sender and reason.
- Unparseable event time string → displayed verbatim (helper fallback).
