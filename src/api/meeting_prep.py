from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from src.database import get_db
from src.models.user import User
from src.services.gmail_service import GmailService
from src.services.calendar_service import CalendarService
from src.config import settings
import re, asyncio, json

router = APIRouter(prefix="/meeting-prep", tags=["Meeting Prep"])

def _extract_emails(text: str):
    """Pull email addresses out of attendee strings like 'John Doe <john@example.com>'."""
    return re.findall(r"[\w.+-]+@[\w-]+\.[a-zA-Z]+", text or "")

@router.get("")
async def get_meeting_prep(
    email: str = "glenlin7813@gmail.com",
    db: AsyncSession = Depends(get_db)
):
    """Prep brief for the next upcoming calendar event: attendee context from Gmail."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    events = await CalendarService.get_upcoming_events(user, days_ahead=7)
    if not events:
        return {"message": "No upcoming events found in the next 7 days."}

    next_event = events[0]

    # Extract attendee emails from the raw event (CalendarService returns simplified dicts;
    # we re-fetch to get attendees)
    service_obj = None
    try:
        from src.services.google_auth import GoogleAuthService
        cal_service = await GoogleAuthService.get_calendar_service(user)
        raw_event = await asyncio.to_thread(
            lambda: cal_service.events().get(calendarId="primary", eventId=next_event["id"]).execute()
        )
        attendees_raw = raw_event.get("attendees", [])
        attendee_emails = [a["email"] for a in attendees_raw if a.get("email") and a.get("email") != email]
    except Exception:
        attendee_emails = []

    # Fetch recent emails from each attendee (up to 3 attendees, 3 emails each)
    email_context = {}
    fetch_tasks = {
        att: GmailService.search_emails_from_sender(user, att, max_results=3)
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
