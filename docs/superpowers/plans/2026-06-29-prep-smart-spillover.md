# Prep Planner Smart Spillover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the prep planner spend the full requested time budget by distributing capacity-aware and re-flowing leftover minutes onto days that still have room (ramp-preserving).

**Architecture:** Replace `allocate_per_day` with two pure functions — `day_capacity` (a day's real placeable minutes) and `distribute` (water-filling allocation that respects per-day caps and spills overflow toward later days). Rewire the `prep_preview` endpoint to compute each day's capacity from its free gaps and call them.

**Tech Stack:** Python 3.12, FastAPI, stdlib `unittest`. Pure functions, no LLM.

Spec: `docs/superpowers/specs/2026-06-29-prep-smart-spillover-design.md`.

---

## File Structure

- **Modify** `src/services/prep_planner.py` — remove `allocate_per_day`; add `day_capacity` + `distribute`.
- **Modify** `src/api/schedule.py` — `prep_preview` uses `free_gaps` + `day_capacity` + `distribute`; fix the import line.
- **Modify** `tests/test_prep_planner.py` — replace `AllocateTests` with `DistributeTests` + `DayCapacityTests`.

---

## Task 1: day_capacity + distribute (replace allocate_per_day)

**Files:**
- Modify: `src/services/prep_planner.py`, `tests/test_prep_planner.py`

- [ ] **Step 1: Replace the allocate tests**

In `tests/test_prep_planner.py`, find the entire `class AllocateTests(unittest.TestCase):` block (its 4 test methods) and REPLACE it with:

```python
class DistributeTests(unittest.TestCase):
    def test_uncapped_ramp_matches_ideal(self):
        from src.services.prep_planner import distribute
        # caps large -> pure ramp: weights 1,2,3,4 (sum 10) of 600 -> 60,120,180,240
        self.assertEqual(distribute(600, [1000, 1000, 1000, 1000], ramp=True), [60, 120, 180, 240])

    def test_spills_full_budget_when_a_day_is_tight(self):
        from src.services.prep_planner import distribute
        out = distribute(600, [60, 1000, 1000], ramp=True)
        self.assertEqual(sum(out), 600)     # whole budget still placed
        self.assertEqual(out[0], 60)        # tight day capped, rest re-flowed
        self.assertTrue(out[2] >= out[1])   # ramp shape preserved among open days

    def test_capacity_is_the_binding_limit(self):
        from src.services.prep_planner import distribute
        out = distribute(600, [60, 60, 60], ramp=True)
        self.assertEqual(sum(out), 180)     # can't place more than total capacity
        self.assertTrue(all(x <= 60 for x in out))

    def test_even_when_no_ramp(self):
        from src.services.prep_planner import distribute
        self.assertEqual(distribute(180, [1000, 1000, 1000], ramp=False), [60, 60, 60])

    def test_zero_and_empty_guards(self):
        from src.services.prep_planner import distribute
        self.assertEqual(distribute(0, [100, 100]), [0, 0])
        self.assertEqual(distribute(100, []), [])
        self.assertTrue(all(v % 15 == 0 for v in distribute(600, [60, 1000, 1000])))


class DayCapacityTests(unittest.TestCase):
    def test_sums_usable_gaps(self):
        from src.services.prep_planner import day_capacity
        # gaps 60 min + 120 min, cap large -> 180
        self.assertEqual(day_capacity([(480, 540), (600, 720)], 1000), 180)

    def test_ignores_gaps_below_min_session(self):
        from src.services.prep_planner import day_capacity
        # 20-min gap excluded, 120-min kept
        self.assertEqual(day_capacity([(480, 500), (600, 720)], 1000), 120)

    def test_clamps_to_daily_cap(self):
        from src.services.prep_planner import day_capacity
        # one 240-min gap is fully usable but the cap is 90
        self.assertEqual(day_capacity([(480, 720)], 90), 90)

    def test_tail_below_min_is_not_counted(self):
        from src.services.prep_planner import day_capacity
        # a 100-min gap packs as one 90-min session; the trailing 10 min is unusable
        self.assertEqual(day_capacity([(480, 580)], 1000), 90)
```

- [ ] **Step 2: Run, expect failure**

Run: `./venv/Scripts/python.exe -m unittest tests.test_prep_planner.DistributeTests tests.test_prep_planner.DayCapacityTests -v`
Expected: FAIL (`cannot import name 'distribute'` / `'day_capacity'`).

- [ ] **Step 3: Replace `allocate_per_day` with the new functions**

In `src/services/prep_planner.py`, DELETE the entire `def allocate_per_day(...)` function and REPLACE it with:

```python
def day_capacity(gaps: List[Tuple[int, int]], daily_cap: int,
                 max_session: int = 90, min_session: int = 30) -> int:
    """Minutes a day can actually absorb: the placeable time in its free gaps, capped.

    Mirrors how `place_sessions` packs each gap (chunks of min_session..max_session), so a
    trailing sliver shorter than min_session doesn't count. Result is clamped to daily_cap.
    """
    usable = 0
    for s, e in gaps:
        length = e - s
        used = 0
        while length - used >= min_session:
            used += min(max_session, length - used)
        usable += used
    return min(daily_cap, usable)


def distribute(total_minutes: int, day_caps: List[int], ramp: bool = True) -> List[int]:
    """Spread `total_minutes` across days whose per-day ceilings are `day_caps`.

    Weighted toward later days when `ramp` (later = closer to the exam). No day exceeds its
    cap; overflow re-flows onto days that still have headroom (preferring later days), until
    the budget is spent or every day is full. Values are multiples of 15; the returned list
    sums to min(total_minutes, sum(day_caps)).
    """
    n = len(day_caps)
    if n == 0 or total_minutes <= 0:
        return [0] * n
    total = min(total_minutes, sum(day_caps))
    assigned = [0] * n
    remaining = total
    # smooth water-filling passes
    for _ in range(n + 2):
        open_idx = [i for i in range(n) if assigned[i] < day_caps[i]]
        if not open_idx or remaining < 15:
            break
        weights = {i: (i + 1 if ramp else 1) for i in open_idx}
        wsum = sum(weights.values())
        progressed = False
        for i in open_idx:
            headroom = day_caps[i] - assigned[i]
            want = int((remaining * weights[i] / wsum) / 15) * 15  # floor to 15
            give = min(want, headroom)
            if give >= 15:
                assigned[i] += give
                progressed = True
        remaining = total - sum(assigned)
        if not progressed:
            break
    # crumb pass: place any leftover 15-min increments, later days first
    while remaining >= 15:
        open_idx = [i for i in range(n) if assigned[i] < day_caps[i]]
        if not open_idx:
            break
        pick = max(open_idx, key=lambda i: (i if ramp else 0))
        assigned[pick] += 15
        remaining -= 15
    return assigned
```

(Leave `place_sessions` and `free_gaps`/`parse_time_to_minute` imports unchanged. The `List`/`Tuple` imports at the top of the file are already present.)

- [ ] **Step 4: Run tests, expect pass**

Run: `./venv/Scripts/python.exe -m unittest tests.test_prep_planner -v`
Expected: PASS (DistributeTests, DayCapacityTests, PlaceSessionsTests, ModelTests, RequestModelTests).

- [ ] **Step 5: Commit**

```bash
git add src/services/prep_planner.py tests/test_prep_planner.py
git commit -m "feat: capacity-aware distribute + day_capacity (replaces allocate_per_day)"
```

---

## Task 2: Rewire prep_preview to use capacity + spillover

**Files:**
- Modify: `src/api/schedule.py`

- [ ] **Step 1: Fix the import line**

In `src/api/schedule.py`, change:

```python
from src.services.prep_planner import allocate_per_day, place_sessions
```

to:

```python
from src.services.prep_planner import day_capacity, distribute, place_sessions
from src.services.schedule_ai import free_gaps
```

- [ ] **Step 2: Compute per-day capacity, distribute, then place**

In `prep_preview`, find this block:

```python
    alloc = allocate_per_day(len(days), req.total_minutes, req.daily_cap_minutes, ramp=True)
    out_days, placed = [], 0
    for i, day in enumerate(days):
        iso = day.isoformat()
        blk_res = await db.execute(
            select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
        )
        busy = [(b.start_minute, b.start_minute + b.duration_minutes) for b in blk_res.scalars().all()]
        try:
            s_iso, e_iso = local_day_range(iso, tz)
            events = await OutlookCalendarService.get_events_in_range(user, s_iso, e_iso, prefer_tz=tz)
            for e in events:
                es, ee = _iso_to_minute(e.get("start"), tz), _iso_to_minute(e.get("end"), tz)
                if es is not None and ee is not None:
                    busy.append((es, ee))
        except PermissionError:
            raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
        except Exception as ex:  # noqa: BLE001 — one bad day shouldn't sink the whole preview
            print(f"[prep] events fetch failed for {iso}: {ex}")
        sessions = place_sessions(alloc[i], busy)
        if sessions:
            out_days.append({"date": iso, "sessions": [
                {"start_minute": st, "duration_minutes": du, "title": f"Study: {req.event_title}"}
                for st, du in sessions
            ]})
            placed += sum(du for _, du in sessions)
```

Replace it with (two passes: gather each day's busy + capacity, then distribute + place):

```python
    WINDOW = (8 * 60, 22 * 60)
    day_busy = []
    caps = []
    for day in days:
        iso = day.isoformat()
        blk_res = await db.execute(
            select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
        )
        busy = [(b.start_minute, b.start_minute + b.duration_minutes) for b in blk_res.scalars().all()]
        try:
            s_iso, e_iso = local_day_range(iso, tz)
            events = await OutlookCalendarService.get_events_in_range(user, s_iso, e_iso, prefer_tz=tz)
            for e in events:
                es, ee = _iso_to_minute(e.get("start"), tz), _iso_to_minute(e.get("end"), tz)
                if es is not None and ee is not None:
                    busy.append((es, ee))
        except PermissionError:
            raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
        except Exception as ex:  # noqa: BLE001 — one bad day shouldn't sink the whole preview
            print(f"[prep] events fetch failed for {iso}: {ex}")
        day_busy.append((iso, busy))
        caps.append(day_capacity(free_gaps(WINDOW[0], WINDOW[1], busy), req.daily_cap_minutes))

    assigned = distribute(req.total_minutes, caps, ramp=True)
    out_days, placed = [], 0
    for (iso, busy), minutes in zip(day_busy, assigned):
        sessions = place_sessions(minutes, busy, window=WINDOW)
        if sessions:
            out_days.append({"date": iso, "sessions": [
                {"start_minute": st, "duration_minutes": du, "title": f"Study: {req.event_title}"}
                for st, du in sessions
            ]})
            placed += sum(du for _, du in sessions)
```

- [ ] **Step 3: Verify import + suites**

Run:
```bash
./venv/Scripts/python.exe -c "import src.main; print('ok')"
./venv/Scripts/python.exe -m unittest tests.test_prep_planner tests.test_schedule
```
Expected: `ok` and all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/api/schedule.py
git commit -m "feat: prep_preview distributes capacity-aware with spillover"
```

---

## Final verification

- [ ] `./venv/Scripts/python.exe -c "import src.main; print('ok')"` → `ok`.
- [ ] `./venv/Scripts/python.exe -m unittest discover -s tests` → all PASS.
- [ ] Confirm no stale references: `grep -rn "allocate_per_day" src/ tests/` → no matches.
- [ ] **Manual** (signed in): click **📚 Plan prep** on an event with a busy day or two in the range → the preview should now place (close to) the full budget you asked for, front-loading onto free days and later days, with `shortfall` only when your free time genuinely can't hold it.
