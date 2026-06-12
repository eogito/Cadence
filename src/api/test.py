from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.models.user import User
from src.services.google_auth import GoogleAuthService
from src.services.gmail_service import GmailService
from src.services.email_preferences_service import get_tracked_categories
from src.workflows.trigger import process_new_email
import asyncio

router = APIRouter(prefix="/test", tags=["Testing"])

@router.post("/trigger")
async def trigger_latest_email(
    email: str = "glenlin7813@gmail.com",
    db: AsyncSession = Depends(get_db)
):
    # 1. Find your user in the database
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Visit /auth/login first.")
    
    # 2. Ask Google for your latest email ID
    try:
        service = await GoogleAuthService.get_gmail_service(user)
        categories = await get_tracked_categories(db, user)
        q = GmailService.build_category_filter(categories)
        list_kwargs = {"userId": "me", "maxResults": 1}
        if q:
            list_kwargs["q"] = q
        response = await asyncio.to_thread(
            lambda: service.users().messages().list(**list_kwargs).execute()
        )
        messages = response.get('messages', [])
        if not messages:
            return {"message": "No emails found in your tracked sections."}
            
        latest_message_id = messages[0]['id']
        print(f"Found latest email ID: {latest_message_id}")
        
        # 3. Run workflow and return thread_id so the frontend can poll for the plan
        thread_id = await process_new_email(email, latest_message_id)
        
        return {
            "message": "Workflow paused for approval.",
            "email_id": latest_message_id,
            "thread_id": thread_id
        }
        
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))