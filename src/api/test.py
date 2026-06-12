from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models.user import User
from src.api.deps import current_user
from src.services.outlook_mail_service import OutlookMailService
from src.services.email_preferences_service import get_tracked_categories
from src.workflows.trigger import process_new_email

router = APIRouter(prefix="/test", tags=["Testing"])


@router.post("/trigger")
async def trigger_latest_email(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Process the signed-in user's latest tracked Outlook email."""
    try:
        categories = await get_tracked_categories(db, user)
        message_id = await OutlookMailService.get_latest_message_id(user, classification=categories)
        if not message_id:
            return {"message": "No emails found in your tracked inbox."}

        thread_id = await process_new_email(user.email, message_id)
        return {
            "message": "Workflow paused for approval.",
            "email_id": message_id,
            "thread_id": thread_id,
        }
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
