"""Deterministic multi-day prep-plan distribution (pure, no LLM)."""
from typing import List, Tuple
from src.services.schedule_ai import free_gaps


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
    for _ in range(n + 2):
        open_idx = [i for i in range(n) if assigned[i] < day_caps[i]]
        if not open_idx or remaining < 15:
            break
        weights = {i: (i + 1 if ramp else 1) for i in open_idx}
        wsum = sum(weights.values())
        progressed = False
        for i in open_idx:
            headroom = day_caps[i] - assigned[i]
            want = int((remaining * weights[i] / wsum) / 15) * 15
            give = min(want, headroom)
            if give >= 15:
                assigned[i] += give
                progressed = True
        remaining = total - sum(assigned)
        if not progressed:
            break
    while remaining >= 15:
        open_idx = [i for i in range(n) if assigned[i] < day_caps[i]]
        if not open_idx:
            break
        pick = max(open_idx, key=lambda i: (i if ramp else 0))
        assigned[pick] += 15
        remaining -= 15
    return assigned


def place_sessions(minutes: int, busy: List[Tuple[int, int]],
                   window: Tuple[int, int] = (8 * 60, 22 * 60),
                   max_session: int = 90, min_session: int = 30) -> List[Tuple[int, int]]:
    """Pack `minutes` of work into the free gaps of `window`, avoiding `busy`.

    Returns (start_minute, duration) sessions of length min_session..max_session, in order.
    If the gaps can't hold the full amount, returns what fits (the rest is shortfall).
    """
    if minutes < min_session:
        return []
    gaps = free_gaps(window[0], window[1], list(busy))
    sessions: List[Tuple[int, int]] = []
    remaining = minutes
    for gs, ge in gaps:
        cursor = gs
        while remaining >= min_session and ge - cursor >= min_session:
            dur = min(max_session, remaining, ge - cursor)
            sessions.append((cursor, dur))
            cursor += dur
            remaining -= dur
        if remaining < min_session:
            break
    return sessions
