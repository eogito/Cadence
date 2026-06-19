from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models.user import User
from src.api.deps import current_user
from src.services.outlook_mail_service import OutlookMailService
from src.services.outlook_calendar_service import OutlookCalendarService
from src.services.email_preferences_service import get_tracked_categories
from src.services.briefing_ai import generate_briefing
import asyncio

router = APIRouter(prefix="/briefing", tags=["Briefing"])


@router.get("")
async def get_daily_briefing(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Generate a structured morning briefing with categorized unread mail."""
    categories = await get_tracked_categories(db, user)
    events, emails = await asyncio.gather(
        OutlookCalendarService.get_upcoming_events(user, days_ahead=1),
        OutlookMailService.get_unread_emails(user, max_results=15, classification=categories),
    )
    return await generate_briefing(emails, events)
