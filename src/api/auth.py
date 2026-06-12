import asyncio
import msal
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database import get_db
from src.models.user import User
from src.api.deps import current_user
from src.config import settings
from src.services.ms_auth import SCOPES, build_msal_app

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/login")
async def login(request: Request):
    app = build_msal_app()
    flow = await asyncio.to_thread(
        app.initiate_auth_code_flow, SCOPES, redirect_uri=settings.ms_redirect_uri
    )
    request.session["auth_flow"] = flow  # carries state + PKCE verifier
    return RedirectResponse(flow["auth_uri"])


@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    flow = request.session.pop("auth_flow", None)
    if not flow:
        return JSONResponse({"detail": "No auth flow in session. Start at /auth/login."}, status_code=400)

    cache = msal.SerializableTokenCache()
    app = build_msal_app(cache)
    result = await asyncio.to_thread(
        app.acquire_token_by_auth_code_flow, flow, dict(request.query_params)
    )
    if "error" in result:
        return JSONResponse(
            {"detail": result.get("error_description", result["error"])}, status_code=400
        )

    claims = result.get("id_token_claims", {})
    email = (claims.get("preferred_username") or claims.get("email") or "").lower()
    account_id = claims.get("oid") or claims.get("sub")
    if not email:
        return JSONResponse({"detail": "Could not read account email from Microsoft."}, status_code=400)

    res = await db.execute(select(User).where(User.email == email))
    user = res.scalars().first()
    if user is None:
        user = User(email=email)
        db.add(user)
    user.ms_token_cache = cache.serialize()
    user.ms_account_id = account_id
    await db.commit()
    await db.refresh(user)

    request.session["user_id"] = str(user.id)
    return RedirectResponse("/")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@router.get("/me")
async def me(user: User = Depends(current_user)):
    """Return the signed-in user's identity (used by the frontend to show login state)."""
    return {"authenticated": True, "email": user.email}
