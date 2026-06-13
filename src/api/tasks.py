from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from src.database import get_db
from src.models.user import User
from src.models.task import Task
from src.models.contact import Contact
from src.api.deps import current_user
import uuid

router = APIRouter(prefix="/tasks-list", tags=["Tasks"])

@router.get("")
async def get_tasks(
    include_completed: bool = False,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db)
):
    """Return all tasks for the user, sorted by urgency and due date. Flags overdue tasks."""

    query = select(Task).where(Task.user_id == user.id)
    if not include_completed:
        query = query.where(Task.completed == False)
    query = query.order_by(Task.urgency_score.desc(), Task.due_date.asc().nullslast())

    result = await db.execute(query)
    tasks = result.scalars().all()

    now = datetime.now(timezone.utc)
    return {
        "tasks": [
            {
                "id": str(t.id),
                "title": t.title,
                "description": t.description,
                "priority": t.priority,
                "urgency_score": t.urgency_score,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "overdue": bool(t.due_date and t.due_date < now and not t.completed),
                "completed": t.completed,
                "email_id": t.email_id,
                "created_at": t.created_at.isoformat()
            }
            for t in tasks
        ],
        "stats": {
            "total": len(tasks),
            "overdue": sum(1 for t in tasks if t.due_date and t.due_date < now and not t.completed),
            "high_priority": sum(1 for t in tasks if t.priority == "high"),
        }
    }


@router.patch("/{task_id}/complete")
async def complete_task(task_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Mark one of the signed-in user's tasks completed."""
    result = await db.execute(
        select(Task).where(Task.id == uuid.UUID(task_id), Task.user_id == user.id)
    )
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    task.completed = True
    await db.commit()
    return {"message": "Task marked as completed."}


@router.get("/contacts")
async def get_contacts(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db)
):
    """Return all contact memories for the user."""

    result = await db.execute(
        select(Contact)
        .where(Contact.user_id == user.id)
        .order_by(Contact.interaction_count.desc())
    )
    contacts = result.scalars().all()
    return {
        "contacts": [
            {
                "id": str(c.id),
                "email": c.email,
                "name": c.name,
                "summary": c.summary,
                "interaction_count": c.interaction_count,
                "last_interaction": c.last_interaction.isoformat() if c.last_interaction else None
            }
            for c in contacts
        ]
    }
