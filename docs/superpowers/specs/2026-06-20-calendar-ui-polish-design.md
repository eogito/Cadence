# Calendar UI Polish & Dynamic Schedule Edits — Design

**Date:** 2026-06-20
**Scope:** Frontend-only (`src/static/index.html`). No backend changes.

## Problem

Two issues reported on the calendar/schedule UI:

1. **Editing schedule blocks "takes forever / isn't dynamic."** Every block mutation (`saveBlock`, `toggleDone`, `deleteBlock`, `addSlot`, `pushBlock`, `pushAllSchedule`) ends with `loadSchedule(iso)`, which re-fetches `GET /schedule` — and that endpoint makes a **live Microsoft Graph call** for Outlook events on every request. So each edit waits on a Microsoft round-trip.
2. **Month grid is cramped and jittery.** `cal-cell` uses `aspect-ratio:1`, so on narrow widths cells become tiny and the date number + dots overflow. The hover transform `rotate(-1deg) translate(-1px,-1px)` makes cells jump and overlap neighbors.

## Design

### Part 1 — Optimistic / local schedule edits
The mutation endpoints already return the data needed, so we update the in-memory `window._sched.blocks` from each response and re-`renderSchedule()` **without** a GET:

- `addSlot`: `POST /schedule/block` returns the new block → push to `window._sched.blocks`, `renderSchedule()`, then open its editor.
- `saveBlock` / `toggleDone`: `PATCH` returns the updated block → replace by `id` in `window._sched.blocks`, `renderSchedule()`.
- `deleteBlock`: `DELETE` → remove by `id`, `renderSchedule()`.
- `generateDay`: `POST /schedule/generate` returns `{created, blocks:[...]}` → set `window._sched.blocks = data.blocks`, `renderSchedule()` (no second fetch).
- `pushBlock` / `pushAllSchedule`: on success, set the affected blocks' `pushed=true` locally, `renderSchedule()`.

Outlook events are fetched **once** when a day opens (`selectDay` → `loadSchedule`) and cached in `window._sched.events`. `loadSchedule` remains only for the initial open. Net effect: edits are instant; the only Graph call is opening a day.

A small helper `_replaceBlock(updated)` / `_removeBlock(id)` keeps `window._sched.blocks` in sync.

### Part 2 — Month grid polish
- **Cells:** replace `aspect-ratio:1` with `min-height: 64px` (and a sensible `padding`) so the date + dots always fit and never overflow on narrow widths; date number top-left, dots below wrapping cleanly; `.cal-dot` slightly smaller.
- **Hover:** replace `rotate(-1deg) translate(...)` with a stable lift — `transform: translate(-1px,-1px)` + `box-shadow: var(--shadow-hard)` only (no rotation), so the grid doesn't jump.
- **Cohesion:** keep today = `--postit` background + bold number; selected = `--accent` ring (`box-shadow: 0 0 0 2px var(--accent)` so it doesn't shift layout); weekday header stays muted pencil. Add a small legend under the grid: "● events ● tasks" using `.cal-dot.ev` / `.cal-dot.tk` colors.

## Testing
Frontend-only, no JS test runner: structural grep that the mutation functions no longer unconditionally call `loadSchedule` after writes, plus manual verification (edits feel instant; grid cells fit; hover is stable). The existing `unittest` suite must still pass (no backend change).

## Out of scope
Backend/API changes, the timezone follow-up (tracked separately), drag-and-drop.
