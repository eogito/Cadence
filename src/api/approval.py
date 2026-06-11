from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.models.user import User
from src.workflows.agent import build_agent_graph
from src.workflows.trigger import memory_checkpointer
from src.services.gmail_service import GmailService

router = APIRouter(prefix="/tasks", tags=["Approvals"])

class ApprovalRequest(BaseModel):
    thread_id: str  # The unique workflow ID
    action: str     # 'approved', 'rejected', 'modified'
    feedback: str = "" # If modified, what should change?

@router.get("/pending/{thread_id}")
async def get_pending_plan(thread_id: str):
    """Return the paused/finished workflow state, category-aware, with the full email."""
    app = build_agent_graph(memory_checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await app.aget_state(config)

    values = snapshot.values if snapshot else {}
    classification = values.get("classification") or {}
    category = classification.get("category", "promotion")
    paused = bool(snapshot and snapshot.next)

    if category == "actionable" and paused:
        status = "pending_approval"
    elif category == "notification" and paused:
        status = "notification"
    else:
        status = "no_action"

    return {
        "thread_id": thread_id,
        "category": category,
        "reason": classification.get("reason", ""),
        "status": status,
        "proposed_plan": values.get("analysis") if category == "actionable" else None,
        "email": {
            "subject": values.get("email_subject", ""),
            "sender": values.get("sender_email", ""),
            "body": values.get("email_content", ""),
        },
    }

@router.post("/approve")
async def approve_plan(request: ApprovalRequest):
    """Resumes the graph with the human's decision."""
    app = build_agent_graph(memory_checkpointer)
    config = {"configurable": {"thread_id": request.thread_id}}

    # Only paused workflows can be resumed
    snapshot = await app.aget_state(config)
    if not (snapshot and snapshot.next):
        raise HTTPException(status_code=409, detail="Workflow is not paused; nothing to resume.")

    # Resume the interrupted human_review / notification_review node with the decision
    await app.ainvoke(
        Command(resume={"action": request.action, "feedback": request.feedback}),
        config
    )
    return {"message": f"Plan {request.action} successfully."}


class DraftSendRequest(BaseModel):
    thread_id: str
    to: str
    subject: str
    body: str
    user_email: str = "glenlin7813@gmail.com"

@router.post("/send-draft")
async def send_draft_reply(request: DraftSendRequest, db: AsyncSession = Depends(get_db)):
    """Send an AI-drafted email reply after human approval."""
    result = await db.execute(select(User).where(User.email == request.user_email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    sent = await GmailService.send_email(user, to=request.to, subject=request.subject, body=request.body)
    return {"message": "Email sent successfully.", "gmail_message_id": sent.get("message_id")}