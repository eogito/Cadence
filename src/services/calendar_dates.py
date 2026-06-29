from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Tuple


def month_range(year: int, month: int) -> Tuple[str, str]:
    """UTC ISO [start, end): first of the month to first of next month."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 \
        else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start.isoformat(), end.isoformat()


def day_range(date_str: str) -> Tuple[str, str]:
    """UTC ISO [start, end) for a 'YYYY-MM-DD' day."""
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return d.isoformat(), (d + timedelta(days=1)).isoformat()


def parse_graph_dt(value: str) -> Optional[datetime]:
    """Parse a Graph datetime ('...Z' or offset) to an aware UTC datetime, or None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def user_tz(user) -> str:
    """The user's IANA timezone, or 'UTC' if unset."""
    return getattr(user, "timezone", None) or "UTC"


def local_day_range(date_str: str, tz: str) -> Tuple[str, str]:
    """UTC ISO instants bounding the user's LOCAL day for a 'YYYY-MM-DD' date.

    Falls back to UTC if `tz` is not a known IANA zone.
    """
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = timezone.utc
    start_local = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=zone)
    end_local = start_local + timedelta(days=1)  # next local midnight (wall-clock add)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )
