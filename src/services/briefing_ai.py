import json
from typing import List
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from src.config import settings

CATEGORIES = ["urgent_reply", "action_required", "fyi", "news_newsletter", "spam_promo", "other"]


class EmailCategory(BaseModel):
    message_id: str
    subject: str
    sender: str
    snippet: str
    category: str = Field(description="One of: urgent_reply, action_required, fyi, news_newsletter, spam_promo, other")
    reason: str = Field(description="One sentence explaining why this category was assigned")


class BriefingAnalysis(BaseModel):
    calendar_summary: str = Field(description="2-3 sentence summary of the day's schedule")
    categorized_emails: List[EmailCategory]


async def generate_briefing(emails: list, events: list) -> dict:
    """Categorize a set of emails and summarize a set of calendar events.

    Returns {calendar_summary, events, categorized_emails(grouped), stats}.
    Used by the morning briefing (today's unread) and the calendar day view (a day's mail).
    """
    events_text = json.dumps(events, indent=2) if events else "No events."
    emails_list = "\n\n".join(
        f"[{i}] message_id={e['message_id']}\nFrom: {e['sender']}\nSubject: {e['subject']}\nSnippet: {e['snippet']}"
        for i, e in enumerate(emails)
    ) if emails else "No emails."

    schema_str = (
        '{{\n  "calendar_summary": string,\n  "categorized_emails": [\n    {{\n'
        '      "message_id": string,\n      "subject": string,\n      "sender": string,\n'
        '      "snippet": string,\n'
        '      "category": "urgent_reply|action_required|fyi|news_newsletter|spam_promo|other",\n'
        '      "reason": string\n    }}\n  ]\n}}'
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
    llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0,
                   api_key=settings.groq_api_key.get_secret_value())
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("user", "CALENDAR:\n{events}\n\nEMAILS:\n{emails}"),
    ])
    chain = prompt | llm.with_structured_output(BriefingAnalysis, method="json_mode")
    analysis: BriefingAnalysis = await chain.ainvoke({"events": events_text, "emails": emails_list})

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
        },
    }
