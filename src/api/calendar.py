from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.models.user import User
from src.models.task import Task
from src.api.deps import current_user
from src.services.calendar_dates import month_range, day_range, parse_graph_dt
from src.services.outlook_calendar_service import OutlookCalendarService
from src.services.outlook_mail_service import OutlookMailService
from src.services.briefing_ai import generate_briefing

router = APIRouter(prefix="/calendar", tags=["Calendar"])


@router.get("/month")
async def calendar_month(year: int, month: int,
                         user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Per-day activity counts for a month: events + tasks due."""
    start_iso, end_iso = month_range(year, month)
    events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso)

    days: dict = {}
    for e in events:
        dt = parse_graph_dt(e.get("start", ""))
        if dt:
            key = dt.date().isoformat()
            days.setdefault(key, {"events": 0, "tasks_due": 0})["events"] += 1

    result = await db.execute(
        select(Task).where(Task.user_id == user.id, Task.due_date.isnot(None))
    )
    for t in result.scalars().all():
        if t.due_date and t.due_date.year == year and t.due_date.month == month:
            key = t.due_date.date().isoformat()
            days.setdefault(key, {"events": 0, "tasks_due": 0})["tasks_due"] += 1

    return {"year": year, "month": month, "days": days}


@router.get("/day")
async def calendar_day(date: str,
                       user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """A single day's events + categorized email breakdown."""
    try:
        start_iso, end_iso = day_range(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso)
    emails = await OutlookMailService.get_messages_in_range(user, start_iso, end_iso)
    breakdown = await generate_briefing(emails, events) if emails else {
        "calendar_summary": "", "events": events, "categorized_emails": {}, "stats": {}
    }
    is_today = date == datetime.now(timezone.utc).date().isoformat()
    return {"date": date, "is_today": is_today, "events": events, "email_breakdown": breakdown}
