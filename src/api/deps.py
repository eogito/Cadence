import uuid
from fastapi import Request, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.models.user import User


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Resolve the signed-in user from the session cookie, or raise 401."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Sign in with Microsoft.")
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalars().first()
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session invalid. Sign in again.")
    return user
