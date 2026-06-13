from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from src.database import get_db
from src.models.user import User
from src.services.outlook_mail_service import OutlookMailService
from src.services.outlook_calendar_service import OutlookCalendarService
from src.api.deps import current_user
from src.config import settings
import re, asyncio, json

router = APIRouter(prefix="/meeting-prep", tags=["Meeting Prep"])

def _extract_emails(text: str):
    """Pull email addresses out of attendee strings like 'John Doe <john@example.com>'."""
    return re.findall(r"[\w.+-]+@[\w-]+\.[a-zA-Z]+", text or "")

@router.get("")
async def get_meeting_prep(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db)
):
    """Prep brief for the next upcoming calendar event: attendee context from Gmail."""
    events = await OutlookCalendarService.get_upcoming_events(user, days_ahead=7)
    if not events:
        return {"message": "No upcoming events found in the next 7 days."}

    next_event = events[0]

    attendee_emails = [a for a in next_event.get("attendees", []) if a and a != user.email]

    # Fetch recent emails from each attendee (up to 3 attendees, 3 emails each)
    email_context = {}
    fetch_tasks = {
        att: OutlookMailService.search_emails_from_sender(user, att, max_results=3)
        for att in attendee_emails[:3]
    }
    if fetch_tasks:
        results = await asyncio.gather(*fetch_tasks.values(), return_exceptions=True)
        for att, res in zip(fetch_tasks.keys(), results):
            if isinstance(res, list):
                email_context[att] = res

    # Build context string for LLM
    context_parts = []
    for att, msgs in email_context.items():
        for m in msgs:
            context_parts.append(f"From {att} — {m['subject']}: {m['snippet']}")
    context_str = "\n".join(context_parts) if context_parts else "No recent email history with attendees found."

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0.3,
        api_key=settings.groq_api_key.get_secret_value()
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an AI executive assistant. Write a concise meeting prep brief. "
         "Include: what the meeting is about, key context from recent emails, "
         "and 3 suggested talking points or questions. Keep it under 250 words."),
        ("user",
         "MEETING: {event_summary}\n"
         "TIME: {event_start}\n"
         "ATTENDEES: {attendees}\n\n"
         "RECENT EMAIL HISTORY WITH ATTENDEES:\n{context}\n\n"
         "Write a meeting prep brief.")
    ])

    chain = prompt | llm
    response = await chain.ainvoke({
        "event_summary": next_event.get("summary", "Untitled Meeting"),
        "event_start": next_event.get("start", "Unknown"),
        "attendees": ", ".join(attendee_emails) if attendee_emails else "No attendees listed",
        "context": context_str
    })

    return {
        "event": next_event,
        "attendees": attendee_emails,
        "prep_brief": response.content
    }
