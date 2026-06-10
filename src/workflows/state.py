from typing import TypedDict, List, Optional
from pydantic import BaseModel, Field

# --- Pydantic Models for LLM Extraction ---

class TaskExtraction(BaseModel):
    title: str = Field(description="Short title of the task extracted from the email")
    description: str = Field(description="Detailed explanation of what needs to be done")
    priority: str = Field(description="'high', 'medium', or 'low'")
    due_date: str = Field(default="", description="Inferred due date in ISO 8601 UTC format, or empty string if not mentioned")

class CalendarProposal(BaseModel):
    summary: str = Field(description="Title of the calendar event")
    start_time: str = Field(description="ISO 8601 start time in UTC")
    end_time: str = Field(description="ISO 8601 end time in UTC")
    rationale: str = Field(description="Why this time was proposed based on the email context")

class EmailAnalysis(BaseModel):
    is_actionable: bool = Field(description="True if the email contains tasks or scheduling requests")
    urgency_score: int = Field(default=5, description="Urgency score 1-10: 10=needs reply today, 1=can ignore")
    tasks: List[TaskExtraction] = Field(default_factory=list, description="Extracted tasks")
    events: List[CalendarProposal] = Field(default_factory=list, description="Proposed calendar events")
    needs_reply: bool = Field(default=False, description="True if a reply to this email is needed")
    suggested_reply: str = Field(default="", description="A draft reply to send, if needs_reply is true")

# --- LangGraph State Definition ---

class AgentState(TypedDict):
    user_id: str
    email_id: str
    email_content: str
    
    # AI Outputs
    analysis: Optional[dict]  # Will store the EmailAnalysis dict
    
    # Human-in-the-loop
    approval_status: Optional[str] # 'pending', 'approved', 'rejected', 'modified'
    human_feedback: Optional[str]  # Instructions if the user modifying the plan

    # Email draft
    draft_approved: Optional[bool]  # Whether the user approved the suggested reply
    sender_email: Optional[str]     # Who to reply to
    email_subject: Optional[str]    # Original subject (for reply subject line)