from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from src.database import get_db
from src.models.user import User
from src.models.user_context import UserContext
from src.models.recurring_rule import RecurringRule
from src.services.user_context_service import add_context, list_all_context, delete_context
from src.api.deps import current_user
import uuid

router = APIRouter(prefix="/context", tags=["Personal Context"])

VALID_CATEGORIES = ["schedule", "important_date", "recurring_rule", "preference"]


# ── Personal Context (Vector DB) ──────────────────────────────────────────────

class AddContextRequest(BaseModel):
    text: str               # e.g. "CS101 every Monday and Wednesday 9-11am"
    category: str           # schedule | important_date | recurring_rule | preference


@router.post("")
async def add_user_context(request: AddContextRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Save a personal rule, schedule, or preference to PostgreSQL + ChromaDB."""
    if request.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of: {VALID_CATEGORIES}")

    item_id = str(uuid.uuid4())

    # Persist to PostgreSQL (source of truth)
    db_item = UserContext(
        user_id=user.id,
        item_id=item_id,
        text=request.text,
        category=request.category,
    )
    db.add(db_item)
    await db.commit()

    # Sync to ChromaDB for semantic search
    add_context(str(user.id), request.text, request.category, item_id=item_id)
    return {"message": "Context saved.", "id": item_id, "category": request.category}


@router.get("")
async def get_user_context(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """List all personal context items stored for the user."""
    items = list_all_context(str(user.id))
    # Group by category for easier display
    grouped = {cat: [] for cat in VALID_CATEGORIES}
    for item in items:
        cat = item["category"] if item["category"] in grouped else "preference"
        grouped[cat].append(item)

    return {"items": grouped, "total": len(items)}


@router.delete("/{item_id}")
async def remove_context(item_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Delete a context item from PostgreSQL and ChromaDB."""
    # Delete from PostgreSQL
    db_result = await db.execute(
        select(UserContext).where(UserContext.item_id == item_id, UserContext.user_id == user.id)
    )
    db_item = db_result.scalars().first()
    if db_item:
        await db.delete(db_item)
        await db.commit()

    # Delete from ChromaDB
    delete_context(str(user.id), item_id)
    return {"message": "Deleted."}


# ── Recurring Rules (Scheduler) ───────────────────────────────────────────────

class AddRuleRequest(BaseModel):
    description: str        # e.g. "Send 5 cold emails every day at 4PM"
    task_title: str         # e.g. "Send 5 cold emails"
    task_priority: str = "medium"
    cron_hour: str          # e.g. "16" for 4PM
    cron_minute: str = "0"
    cron_day_of_week: Optional[str] = "*"  # e.g. "mon,wed" or "*" for every day


@router.post("/rules")
async def add_recurring_rule(request: AddRuleRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Add a recurring rule that auto-creates a task on a schedule."""
    rule = RecurringRule(
        user_id=user.id,
        description=request.description,
        task_title=request.task_title,
        task_priority=request.task_priority,
        cron_hour=request.cron_hour,
        cron_minute=request.cron_minute,
        cron_day_of_week=request.cron_day_of_week
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    # Register with the live scheduler
    from src.services.scheduler_service import register_rule
    register_rule(rule)

    # Also store description in vector DB so AI can reference it
    add_context(str(user.id), request.description, "recurring_rule", str(rule.id))

    return {"message": "Recurring rule created.", "id": str(rule.id)}


@router.get("/rules")
async def get_recurring_rules(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """List all recurring rules for the user."""
    result = await db.execute(
        select(RecurringRule).where(RecurringRule.user_id == user.id, RecurringRule.active == True)
    )
    rules = result.scalars().all()
    return {
        "rules": [
            {
                "id": str(r.id),
                "description": r.description,
                "task_title": r.task_title,
                "task_priority": r.task_priority,
                "schedule": f"Every day at {r.cron_hour}:{r.cron_minute.zfill(2)}" if r.cron_day_of_week == "*"
                            else f"{r.cron_day_of_week} at {r.cron_hour}:{r.cron_minute.zfill(2)}",
                "last_fired": r.last_fired.isoformat() if r.last_fired else "Never"
            }
            for r in rules
        ]
    }


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Deactivate one of the signed-in user's recurring rules."""
    result = await db.execute(
        select(RecurringRule).where(RecurringRule.id == uuid.UUID(rule_id), RecurringRule.user_id == user.id)
    )
    rule = result.scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found.")
    rule.active = False
    await db.commit()

    from src.services.scheduler_service import unregister_rule
    unregister_rule(rule_id)
    return {"message": "Rule deactivated."}
