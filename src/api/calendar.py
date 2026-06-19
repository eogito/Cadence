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
from typing import List
from pydantic import BaseModel
from langgraph.types import Command
from src.workflows.trigger import process_new_email, memory_checkpointer
from src.workflows.agent import build_agent_graph

router = APIRouter(prefix="/calendar", tags=["Calendar"])


class ApproveTodayRequest(BaseModel):
    thread_ids: List[str]


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


@router.post("/today/emails/triage")
async def triage_today_emails(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Run every unread email received today through the workflow; aggregate the actionable proposals."""
    today = datetime.now(timezone.utc).date().isoformat()
    start_iso, end_iso = day_range(today)
    msgs = await OutlookMailService.get_messages_in_range(user, start_iso, end_iso, unread_only=True, max_fetch=60)

    app = build_agent_graph(memory_checkpointer)
    proposals, notifications, promotions = [], 0, 0
    for m in msgs[:15]:  # cap LLM work per run
        try:
            thread_id = await process_new_email(user.email, m["message_id"])
        except Exception as e:
            print(f"[triage] skipped {m.get('message_id')}: {e}")
            continue
        if not thread_id:
            continue
        snapshot = await app.aget_state({"configurable": {"thread_id": thread_id}})
        values = snapshot.values if snapshot else {}
        category = (values.get("classification") or {}).get("category", "promotion")
        if category == "actionable":
            analysis = values.get("analysis") or {}
            proposals.append({
                "thread_id": thread_id,
                "subject": m["subject"],
                "sender": m["sender"],
                "tasks": analysis.get("tasks", []),
                "events": analysis.get("events", []),
                "needs_reply": analysis.get("needs_reply", False),
            })
        elif category == "notification":
            notifications += 1
        else:
            promotions += 1

    return {"scanned": len(msgs), "proposals": proposals,
            "notifications": notifications, "promotions": promotions}


@router.post("/today/emails/approve")
async def approve_today_emails(request: ApproveTodayRequest, user: User = Depends(current_user)):
    """Resume the chosen email threads — the executor creates their events + tasks."""
    app = build_agent_graph(memory_checkpointer)
    approved = 0
    for tid in request.thread_ids:
        config = {"configurable": {"thread_id": tid}}
        snapshot = await app.aget_state(config)
        if not (snapshot and snapshot.next):
            continue  # already resolved / unknown
        await app.ainvoke(Command(resume={"action": "approved", "feedback": ""}), config)
        approved += 1
    return {"approved": approved}
