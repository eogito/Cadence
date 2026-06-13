from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models.user import User
from src.models.email_preferences import VALID_CATEGORIES
from src.services.email_preferences_service import (
    get_tracked_categories,
    set_tracked_categories,
    invalid_categories,
)
from src.api.deps import current_user

router = APIRouter(prefix="/settings", tags=["Settings"])


class EmailSectionsRequest(BaseModel):
    tracked_categories: List[str]


@router.get("/email-sections")
async def get_email_sections(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Return the signed-in user's tracked Gmail sections (default if unset)."""
    cats = await get_tracked_categories(db, user)
    return {"tracked_categories": cats, "valid_categories": VALID_CATEGORIES}


@router.put("/email-sections")
async def put_email_sections(
    request: EmailSectionsRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save which sections the signed-in user wants tracked."""
    bad = invalid_categories(request.tracked_categories)
    if bad:
        raise HTTPException(status_code=400, detail=f"Invalid categories: {bad}. Allowed: {VALID_CATEGORIES}")
    saved = await set_tracked_categories(db, user, request.tracked_categories)
    return {"tracked_categories": saved}
