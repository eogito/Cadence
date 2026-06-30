"""Deterministic multi-day prep-plan distribution (pure, no LLM)."""
from typing import List, Tuple
from src.services.schedule_ai import free_gaps


def allocate_per_day(day_count: int, total_minutes: int, daily_cap: int, ramp: bool = True) -> List[int]:
    """Minutes to study on each of `day_count` days (index 0 = earliest).

    Ramps up toward the last day when `ramp` (later days weighted heavier); each day is
    capped at `daily_cap`; each value is floored to a 15-minute increment. The sum is at
    most `total_minutes` (floor + cap may leave a little unallocated — the caller reports it).
    """
    if day_count <= 0 or total_minutes <= 0 or daily_cap <= 0:
        return [0] * max(0, day_count)
    weights = list(range(1, day_count + 1)) if ramp else [1] * day_count
    total_weight = sum(weights)
    alloc = []
    for w in weights:
        minutes = int((total_minutes * w / total_weight) / 15) * 15  # floor to 15-min
        alloc.append(min(minutes, daily_cap))
    return alloc


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
