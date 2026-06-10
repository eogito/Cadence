from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import List
from src.database import get_db
from src.models.user import User
from src.services.gmail_service import GmailService
from src.services.calendar_service import CalendarService
from src.config import settings
import json, asyncio

router = APIRouter(prefix="/briefing", tags=["Briefing"])

CATEGORIES = ["urgent_reply", "action_required", "fyi", "news_newsletter", "spam_promo", "other"]

class EmailCategory(BaseModel):
    message_id: str 
    subject: str
    sender: str
    snippet: str
    category: str = Field(description="One of: urgent_reply, action_required, fyi, news_newsletter, spam_promo, other")
    reason: str = Field(description="One sentence explaining why this category was assigned")

class BriefingAnalysis(BaseModel):
    calendar_summary: str = Field(description="2-3 sentence summary of today's schedule")
    categorized_emails: List[EmailCategory]

@router.get("")
async def get_daily_briefing(
    email: str = "glenlin7813@gmail.com",
    db: AsyncSession = Depends(get_db)
):
    """Generate a structured morning briefing with categorized emails."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    events, emails = await asyncio.gather(
        CalendarService.get_upcoming_events(user, days_ahead=1),
        GmailService.get_unread_emails(user, max_results=15)
    )

    events_text = json.dumps(events, indent=2) if events else "No events today."
    emails_list = "\n\n".join(
        f"[{i}] message_id={e['message_id']}\nFrom: {e['sender']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}"
        for i, e in enumerate(emails)
    ) if emails else "No unread emails."

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0,
        api_key=settings.groq_api_key.get_secret_value()
    )

    schema_str = (
        '{{\n'
        '  "calendar_summary": string,\n'
        '  "categorized_emails": [\n'
        '    {{\n'
        '      "message_id": string,\n'
        '      "subject": string,\n'
        '      "sender": string,\n'
        '      "snippet": string,\n'
        '      "category": "urgent_reply|action_required|fyi|news_newsletter|spam_promo|other",\n'
        '      "reason": string\n'
        '    }}\n'
        '  ]\n'
        '}}'
    )

    system_msg = (
        "You are an AI executive assistant. Categorize each email into exactly one of these categories:\n"
        "- urgent_reply: needs a response today, sender is waiting\n"
        "- action_required: requires a task or decision but not necessarily a reply\n"
        "- fyi: informational only, no action needed\n"
        "- news_newsletter: newsletters, digests, blog posts\n"
        "- spam_promo: marketing, promotions, spam\n"
        "- other: doesn't fit above\n\n"
        "Respond ONLY with valid JSON matching this exact schema:\n" + schema_str
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("user", "TODAY'S CALENDAR:\n{events}\n\nUNREAD EMAILS:\n{emails}")
    ])

    structured_llm = llm.with_structured_output(BriefingAnalysis, method="json_mode")
    chain = prompt | structured_llm
    analysis: BriefingAnalysis = await chain.ainvoke({"events": events_text, "emails": emails_list})

    # Group by category
    grouped = {cat: [] for cat in CATEGORIES}
    for item in analysis.categorized_emails:
        cat = item.category if item.category in grouped else "other"
        grouped[cat].append(item.model_dump())

    return {
        "calendar_summary": analysis.calendar_summary,
        "events": events,
        "categorized_emails": grouped,
        "stats": {
            "events_today": len(events),
            "unread_emails": len(emails),
            "urgent": len(grouped["urgent_reply"]),
            "action_required": len(grouped["action_required"]),
        }
    }
