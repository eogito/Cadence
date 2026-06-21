"""Daily-schedule block generation + pure time helpers."""
import re
import asyncio
from typing import List, Optional, Tuple
from datetime import date as date_cls

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.user import User
from src.models.task import Task
from src.models.recurring_rule import RecurringRule
from src.services.user_context_service import list_all_context


_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", re.IGNORECASE)


def parse_time_to_minute(time_str: str) -> Optional[int]:
    """'9:00 AM' / '14:30' -> minutes from midnight. None if unparseable."""
    if not time_str:
        return None
    m = _TIME_RE.search(time_str)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2))
    ap = (m.group(3) or "").upper()
    if ap == "PM" and h < 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def free_gaps(win_start: int, win_end: int, busy: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Return the free (start, end) gaps within [win_start, win_end) given busy intervals."""
    merged: List[Tuple[int, int]] = []
    for s, e in sorted(busy):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    gaps = []
    cursor = win_start
    for s, e in merged:
        if s > cursor:
            gaps.append((cursor, min(s, win_end)))
        cursor = max(cursor, e)
        if cursor >= win_end:
            break
    if cursor < win_end:
        gaps.append((cursor, win_end))
    return [(s, e) for s, e in gaps if e > s]


class _GenBlock(BaseModel):
    time: str = Field(description="Concrete clock start time like '9:00 AM' or '14:30' — NEVER 'Flexible'")
    title: str
    category: str = Field(description="One of: task, rule_based, suggested")
    importance: int = Field(description="1-10")
    duration_minutes: int


class _GenOutput(BaseModel):
    blocks: List[_GenBlock]


async def generate_blocks(
    user: User,
    db: AsyncSession,
    day: date_cls,
    intent: str = "",
    busy: Optional[List[Tuple[int, int]]] = None,
    events_text: str = "No calendar events.",
) -> List[dict]:
    """Generate schedule block dicts (start_minute/duration/title/category/importance).

    If `busy` is provided (fill-gaps mode), the prompt is told to schedule only in the free
    gaps and any block landing on a busy interval is dropped.
    """
    tasks_res = await db.execute(
        select(Task).where(Task.user_id == user.id, Task.completed == False)  # noqa: E712
        .order_by(Task.urgency_score.desc(), Task.due_date.asc().nullslast()).limit(15)
    )
    tasks = tasks_res.scalars().all()
    rules_res = await db.execute(
        select(RecurringRule).where(RecurringRule.user_id == user.id, RecurringRule.active == True)  # noqa: E712
    )
    rules = rules_res.scalars().all()
    context_items = list_all_context(str(user.id))

    tasks_text = "\n".join(
        f"- [{t.priority.upper()} urgency={t.urgency_score}/10] {t.title}"
        + (f" (due {t.due_date.strftime('%b %d')})" if t.due_date else "")
        for t in tasks
    ) or "No open tasks."
    rules_text = "\n".join(f"- {r.description}" for r in rules) or "No recurring reminders."
    context_text = "\n".join(f"- [{i['category']}] {i['text']}" for i in context_items) or "No personal context."

    gaps_text = ""
    if busy is not None:
        gaps = free_gaps(0, 24 * 60, busy)
        def lbl(m):
            h, mi = divmod(m, 60)
            return f"{h:02d}:{mi:02d}"
        gaps_text = (
            "\n\nIMPORTANT: Only schedule blocks inside these FREE time ranges (24h): "
            + ", ".join(f"{lbl(s)}-{lbl(e)}" for s, e in gaps)
            + ". Do not overlap times outside these ranges."
        )

    schema_str = (
        '{{ "blocks": [ {{ "time": string, "title": string, '
        '"category": "task|rule_based|suggested", "importance": number, "duration_minutes": number }} ] }}'
    )
    system_msg = (
        "You are an expert scheduler. Build a realistic, chronological daily schedule. "
        "Every block MUST have a concrete clock start time (e.g. '9:00 AM' or '14:30') — never 'Flexible' or 'Evening'. "
        "Deep work = 90-120 min, quick tasks = 15-30 min. "
        "Return ONLY valid JSON matching: " + schema_str
    )
    user_msg = (
        f"Day: {day.isoformat()}.\n\n"
        f"CALENDAR EVENTS (already fixed, do not duplicate):\n{events_text}\n\n"
        f"OPEN TASKS:\n{tasks_text}\n\n"
        f"RECURRING REMINDERS:\n{rules_text}\n\n"
        f"PERSONAL CONTEXT:\n{context_text}\n\n"
        + (f"USER'S INTENT: {intent}\n\n" if intent.strip() else "")
        + "Generate the day's blocks." + gaps_text
    )

    llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.2,
                   api_key=settings.groq_api_key.get_secret_value())
    structured = llm.with_structured_output(_GenOutput, method="json_mode")
    prompt = ChatPromptTemplate.from_messages([("system", system_msg), ("human", "{input}")])
    chain = prompt | structured
    out: _GenOutput = await asyncio.to_thread(chain.invoke, {"input": user_msg})

    busy_intervals = busy or []
    blocks = []
    for b in out.blocks:
        start = parse_time_to_minute(b.time)
        if start is None:
            continue
        dur = max(5, int(b.duration_minutes or 30))
        if any(start < be and bs < start + dur for bs, be in busy_intervals):
            continue  # respect locked/fixed time in fill-gaps mode
        blocks.append({
            "start_minute": start,
            "duration_minutes": dur,
            "title": b.title,
            "category": b.category if b.category in ("task", "rule_based", "suggested") else "suggested",
            "importance": int(b.importance) if b.importance else None,
        })
    return blocks
