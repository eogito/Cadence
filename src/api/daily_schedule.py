from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from src.database import get_db
from src.models.user import User
from src.models.task import Task
from src.api.deps import current_user

router = APIRouter(prefix="/daily-schedule", tags=["Daily Schedule"])


# ── Create task from schedule block ───────────────────────────────────────────

class CreateTaskFromBlockRequest(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    duration_minutes: int = 30


@router.post("/create-task")
async def create_task_from_block(request: CreateTaskFromBlockRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Create a task in the task list from a daily schedule block."""

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
