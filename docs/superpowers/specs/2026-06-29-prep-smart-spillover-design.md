# Prep Planner — Smart Spillover — Design

**Date:** 2026-06-29
**Scope:** Make the prep planner actually spend the requested time budget by distributing capacity-aware and re-flowing leftover minutes onto days that still have room. Backend-only (`src/services/prep_planner.py` + the `prep_preview` endpoint).

## Problem

Budget leaks in two places today:
1. `allocate_per_day` floors each day's share to 15 minutes and caps it; leftover budget is never reassigned.
2. A busy day can't fit its assigned share in its free gaps, and that unfitted time is silently lost.

Both surface as `shortfall_minutes` even when *other* days had free capacity. Users asking for a modest budget over several days can see most of it dropped.

## Design

Distribution becomes capacity-aware, and leftover minutes spill to days with remaining room.

### New pure helpers (in `src/services/prep_planner.py`)

- `day_capacity(gaps, daily_cap, min_session=30) -> int`
  The real minutes a day can absorb: `min(daily_cap, sum(length for (s, e) in gaps if length := e - s >= min_session))`. Gaps too small to hold one session don't count. `gaps` are the free (start, end) intervals from `free_gaps`.

- `distribute(total_minutes, day_caps, ramp=True) -> List[int]`
  Hands out `total_minutes` across days whose per-day ceilings are `day_caps` (index 0 = earliest). Weighted toward later days when `ramp` (later = closer to the exam). No day exceeds its cap; overflow re-flows onto not-yet-full days, preferring later days (ramp-preserving), repeating until the budget is spent or every day is at capacity. Values are multiples of 15. Returns per-day minutes summing to `min(total_minutes, sum(day_caps))`.

  Algorithm: iterate — compute weights (`i+1` for ramp, else `1`) over days that still have headroom (`assigned[i] < day_caps[i]`); allocate the remaining budget proportionally, clamped to each day's headroom and floored to 15; stop when the remaining budget can no longer place a 15-minute increment on any open day.

`allocate_per_day` is removed (superseded by `distribute`); its tests are removed.

### `prep_preview` endpoint rewire (`src/api/schedule.py`)

For each day in the window (unchanged: tomorrow → day-before-exam, ≤60-day cap):
1. Build `busy` = that day's stored blocks + Outlook events (unchanged).
2. `gaps = free_gaps(window[0], window[1], busy)` where `window = (8*60, 22*60)`.
3. `caps.append(day_capacity(gaps, req.daily_cap_minutes))`.

Then `assigned = distribute(req.total_minutes, caps, ramp=True)`, and for each day `place_sessions(assigned[i], busy)` (guaranteed to fit since `assigned[i] <= caps[i]`). `placed_minutes` = sum of placed durations; `shortfall_minutes = max(0, total - placed)` — now only nonzero when the free time genuinely can't hold the budget.

The response shape is unchanged (`plan_label`, `requested_minutes`, `placed_minutes`, `days: [{date, sessions:[…]}]`, `shortfall_minutes`), so the frontend needs no change.

## Testing (`tests/test_prep_planner.py`)

Replace the `allocate_per_day` tests with:
- `distribute` fully spends the budget when caps allow, ramp-preserving (later ≥ earlier): `distribute(600, [1000,1000,1000,1000]) == [60,120,180,240]` (same as before when uncapped).
- `distribute` respects caps and spills overflow to days with room: e.g. `distribute(600, [60, 1000, 1000])` places the full 600 with day 0 capped at 60 and the rest re-flowed to days 1–2.
- `distribute` returns `sum == min(total, sum(caps))` when capacity is the binding constraint (e.g. `distribute(600, [60, 60, 60]) sums to 180`).
- zero/empty guards: `distribute(0, [...]) -> all zeros`, `distribute(x, []) -> []`.
- `day_capacity`: sums only gaps ≥ `min_session`, clamps to `daily_cap`.

`place_sessions` tests are unchanged.

## Out of scope

Editing the proposal before commit; refreshing a plan when the calendar changes; study preferences; any frontend change.
