# Welcome & Help Section — Design

**Date:** 2026-06-20
**Scope:** Pure-frontend addition to `src/static/index.html`. No backend, no DB, no new dependencies.

## Problem

The calendar redesign made Cadence less self-explanatory. A new user lands on a month grid with no guidance: the per-email triage board, "Plan my day" (which pushes real events to Outlook), and four features behind the "More" dropdown (Meeting Prep, Tasks, Contacts, My Rules) are invisible until discovered by clicking around. There is also a trust gap — users connect a real Outlook inbox and grant mail/calendar permissions with no in-app explanation of what the app does or touches.

Goal (user picked "both"): a welcome moment for first-time users **and** an always-available help reference.

## Design

One overlay modal serves both jobs.

### 1. Trigger & first-run logic
- A **?** button in the top bar (next to "More") opens the modal on demand.
- In `checkAuth()`, after a successful auth load, if `localStorage['cadence_welcome_seen']` is unset: auto-open the modal and set the flag. So new users get a welcome moment once; everyone can reopen anytime.
- **Decision:** first-run state lives in `localStorage`, not a `users` column. Rationale: zero backend/migration cost. Trade-off: re-shows after clearing storage or on a new device — acceptable for a welcome modal. (A per-account flag is a possible later upgrade: one column + endpoint.)

### 2. Modal structure
- `#helpModal` overlay (fixed, dimmed backdrop) + `#helpCard` content, dismissible via a close button, backdrop click, and Esc.
- `showHelp()` / `closeHelp()` functions; the **?** button and first-run check both call `showHelp()`.

### 3. Content (Hand-Drawn styled, matching existing cards/post-its)
- **What Cadence is** — one line + core promise: *nothing touches your calendar without your approval*.
- **The calendar is home** — dots = events/tasks; click any day to see its schedule + email breakdown.
- **Today's powers** — "Process today's emails" (triage board) and "Plan my day" (generates a schedule, pushes timed blocks to Outlook).
- **The More menu** — pointer to Meeting Prep, Tasks, Contacts, My Rules.
- **Privacy & trust** — Microsoft sign-in; reads mail + calendar; tokens encrypted at rest; every action is user-approved.
- **FAQ** (3 items): "Why Microsoft only?", "Does it auto-create events?" (no), "How do I choose Focused vs Other inbox sections?".

### 4. Styling
Reuse existing Hand-Drawn CSS variables and patterns (`--paper`, `--pencil`, `--wobbly`, `--shadow-hard`, Kalam/Patrick Hand). Add only the minimal overlay/backdrop CSS not already present.

## Out of scope
- Interactive element-highlighting tour (explicitly rejected: high maintenance, fragile, annoys returning users).
- Per-account server-side "seen" flag.
- Any backend/API/DB change.

## Verification
- Structural grep: `#helpModal`, `showHelp(`, `closeHelp(`, the **?** button, and the `localStorage` first-run check each present once.
- Manual: fresh session (cleared storage) auto-opens the modal once; **?** reopens it; close persists (no re-open on reload within the same storage).
