import re
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from src.models.contact import Contact
from src.models.user import User
from src.config import settings


def extract_email_address(sender_string: str) -> str:
    """Pull bare email address from strings like 'John Doe <john@example.com>'."""
    match = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z]+", sender_string or "")
    return match.group(0).lower() if match else sender_string.lower()


def extract_name(sender_string: str) -> str:
    """Extract display name from 'John Doe <john@example.com>', fallback to email."""
    match = re.match(r'^"?([^"<]+)"?\s*<', sender_string or "")
    return match.group(1).strip() if match else extract_email_address(sender_string)


async def get_contact_context(db: AsyncSession, user: User, sender_raw: str) -> str:
    """Return the stored memory summary for a contact, or empty string if new."""
    sender_email = extract_email_address(sender_raw)
    result = await db.execute(
        select(Contact).where(Contact.user_id == user.id, Contact.email == sender_email)
    )
    contact = result.scalars().first()
    if contact and contact.summary:
        return (
            f"Contact memory for {contact.name or sender_email} ({sender_email}):\n"
            f"{contact.summary}\n"
            f"(Interaction #{contact.interaction_count}, last seen {contact.last_interaction.strftime('%Y-%m-%d')})"
        )
    return ""


async def update_contact_memory(
    db: AsyncSession,
    user: User,
    sender_raw: str,
    email_subject: str,
    email_snippet: str,
    existing_summary: str
) -> None:
    """Ask the LLM to update the contact summary, then upsert into DB."""
    sender_email = extract_email_address(sender_raw)
    sender_name = extract_name(sender_raw)

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0,
        api_key=settings.groq_api_key.get_secret_value()
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You maintain a contact memory card for an executive assistant. "
         "Given the existing summary and a new email interaction, write an updated 2-4 sentence summary "
         "covering: who this person is, their relationship to the user, topics discussed, and communication tone. "
         "Be concise. Only output the summary text, no labels or headers."),
        ("user",
         "Existing summary:\n{existing}\n\n"
         "New email — Subject: {subject}\nSnippet: {snippet}\n\n"
         "Write the updated contact summary.")
    ])

    chain = prompt | llm
    response = await chain.ainvoke({
        "existing": existing_summary or "No prior history.",
        "subject": email_subject,
        "snippet": email_snippet[:300]
    })
    new_summary = response.content.strip()

    # Upsert contact
    result = await db.execute(
        select(Contact).where(Contact.user_id == user.id, Contact.email == sender_email)
    )
    contact = result.scalars().first()
    if contact:
        contact.summary = new_summary
        contact.interaction_count += 1
        contact.last_interaction = datetime.now(timezone.utc)
        if not contact.name:
            contact.name = sender_name
    else:
        db.add(Contact(
            user_id=user.id,
            email=sender_email,
            name=sender_name,
            summary=new_summary,
            interaction_count=1
        ))
    await db.commit()
