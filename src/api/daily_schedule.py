from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import List, Optional
from src.database import get_db
from src.models.user import User
from src.models.task import Task
from src.models.recurring_rule import RecurringRule
from src.services.outlook_calendar_service import OutlookCalendarService
from src.services.user_context_service import list_all_context
from src.config import settings
from datetime import datetime, timezone
import json, asyncio

router = APIRouter(prefix="/daily-schedule", tags=["Daily Schedule"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class ScheduleBlock(BaseModel):
    time: str = Field(description="Time like '9:00 AM', '2:30 PM', or 'Flexible' / 'Evening'")
    title: str = Field(description="Short title for this block")
    category: str = Field(description="One of: fixed_event, task, rule_based, suggested")
    importance: int = Field(description="Importance 1-10 (10 = critical)")
    duration_minutes: int = Field(description="Recommended duration in minutes")
    rationale: str = Field(description="One sentence: why this matters or how long it should take")

class DailyScheduleOutput(BaseModel):
    date_label: str = Field(description="e.g. 'Monday, June 8'")
    summary: str = Field(description="2 sentence overview of today's priorities")
    blocks: List[ScheduleBlock]
    focus_areas: List[str] = Field(description="Top 3 things to focus on today, as short phrases")


# ── Create task from schedule block ───────────────────────────────────────────

class CreateTaskFromBlockRequest(BaseModel):
    email: str = "glenlin7813@gmail.com"
    title: str
    description: str = ""
    priority: str = "medium"
    duration_minutes: int = 30


@router.post("/create-task")
async def create_task_from_block(request: CreateTaskFromBlockRequest, db: AsyncSession = Depends(get_db)):
    """Create a task in the task list from a daily schedule block."""
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Map duration to urgency score: longer/more important = higher urgency
    urgency = min(10, max(1, request.duration_minutes // 30 + 3))
    priority_map = {"high": 8, "medium": 5, "low": 3}
    urgency = max(urgency, priority_map.get(request.priority, 5))

    task = Task(
        user_id=user.id,
        title=request.title,
        description=request.description or f"From daily schedule. Estimated {request.duration_minutes} min.",
        priority=request.priority,
        urgency_score=urgency,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return {"message": "Task created.", "task_id": str(task.id)}


# ── Main schedule endpoint ─────────────────────────────────────────────────────

@router.get("")
async def get_daily_schedule(
    email: str = "glenlin7813@gmail.com",
    db: AsyncSession = Depends(get_db)
):
    """Generate an AI daily schedule using calendar events, tasks, personal context and recurring rules."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Fetch data concurrently
    now = datetime.now(timezone.utc)
    today_label = now.strftime("%A, %B ") + str(now.day)  # e.g. "Monday, June 8"

    events_task = OutlookCalendarService.get_upcoming_events(user, days_ahead=1)

    tasks_query = (
        select(Task)
        .where(Task.user_id == user.id, Task.completed == False)
        .order_by(Task.urgency_score.desc(), Task.due_date.asc().nullslast())
        .limit(15)
    )
    rules_query = select(RecurringRule).where(
        RecurringRule.user_id == user.id, RecurringRule.active == True
    )

    events, tasks_result, rules_result = await asyncio.gather(
        events_task,
        db.execute(tasks_query),
        db.execute(rules_query),
    )

    tasks = tasks_result.scalars().all()
    rules = rules_result.scalars().all()
    context_items = list_all_context(str(user.id))

    # ── Build prompt sections ─────────────────────────────────────────────────
    events_text = (
        json.dumps(events, indent=2)
        if events
        else "No calendar events scheduled today."
    )

    tasks_text = (
        "\n".join(
            f"- [{t.priority.upper()} urgency={t.urgency_score}/10] {t.title}"
            + (f" (due {t.due_date.strftime('%b %d')})" if t.due_date else "")
            + (f": {t.description[:80]}" if t.description else "")
            for t in tasks
        )
        if tasks
        else "No open tasks."
    )

    # Filter rules that fire today
    dow_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    today_dow = now.weekday()
    active_rules_today = []
    for r in rules:
        dow = r.cron_day_of_week or "*"
        if dow == "*":
            active_rules_today.append(r)
        else:
            days = [d.strip() for d in dow.split(",")]
            if any(dow_map.get(d) == today_dow for d in days):
                active_rules_today.append(r)

    rules_text = (
        "\n".join(
            f"- {r.description} (fires at {r.cron_hour}:{r.cron_minute or '00'})"
            for r in active_rules_today
        )
        if active_rules_today
        else "No recurring tasks scheduled for today."
    )

    context_text = (
        "\n".join(f"- [{item['category']}] {item['text']}" for item in context_items)
        if context_items
        else "No personal context stored."
    )

    schema_str = (
        '{{\n'
        '  "date_label": string,\n'
        '  "summary": string,\n'
        '  "blocks": [\n'
        '    {{\n'
        '      "time": string,\n'
        '      "title": string,\n'
        '      "category": "fixed_event|task|rule_based|suggested",\n'
        '      "importance": number (1-10),\n'
        '      "duration_minutes": number,\n'
        '      "rationale": string\n'
        '    }}\n'
        '  ],\n'
        '  "focus_areas": [string, string, string]\n'
        '}}'
    )

    system_msg = (
        "You are an expert productivity coach and personal scheduler. "
        "Given a person's calendar events, open tasks, personal schedule rules, and recurring commitments, "
        "create a realistic, actionable daily schedule. "
        "Order blocks chronologically. For flexible items assign a recommended time slot. "
        "Assign importance 1-10 (fixed events are usually 8-10, tasks vary by urgency, "
        "suggested breaks/buffer time can be 3-5). "
        "Duration should reflect realistic effort: a focused deep work session = 90-120 min, "
        "quick tasks = 15-30 min, meetings = their actual length. "
        "Include brief buffer/transition time between blocks when appropriate. "
        "Return ONLY valid JSON matching this schema:\n" + schema_str
    )

    user_msg = (
        "Today is " + today_label + " (current time approx " + now.strftime("%I:%M %p") + " UTC).\n\n"
        "CALENDAR EVENTS TODAY:\n" + events_text + "\n\n"
        "OPEN TASKS (sorted by urgency):\n" + tasks_text + "\n\n"
        "RECURRING REMINDERS ACTIVE TODAY:\n" + rules_text + "\n\n"
        "PERSONAL CONTEXT (schedules, preferences, important dates):\n" + context_text + "\n\n"
        "Generate a complete daily schedule with specific time blocks, importance ratings, "
        "and realistic duration estimates for each item."
    )

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0.2,
        api_key=settings.groq_api_key.get_secret_value()
    )
    structured = llm.with_structured_output(DailyScheduleOutput, method="json_mode")

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("human", "{input}")
    ])
    chain = prompt | structured

    schedule: DailyScheduleOutput = await asyncio.to_thread(
        chain.invoke, {"input": user_msg}
    )

    # Attach source metadata so the frontend can show "Add to Tasks" only for non-fixed items
    blocks_out = []
    for b in schedule.blocks:
        blocks_out.append({
            "time": b.time,
            "title": b.title,
            "category": b.category,
            "importance": b.importance,
            "duration_minutes": b.duration_minutes,
            "rationale": b.rationale,
            "can_create_task": b.category in ("task", "rule_based", "suggested"),
        })

    return {
        "date_label": schedule.date_label,
        "summary": schedule.summary,
        "blocks": blocks_out,
        "focus_areas": schedule.focus_areas,
        "stats": {
            "total_blocks": len(blocks_out),
            "fixed_events": sum(1 for b in blocks_out if b["category"] == "fixed_event"),
            "open_tasks": len(tasks),
            "rules_today": len(active_rules_today),
        }
    }
