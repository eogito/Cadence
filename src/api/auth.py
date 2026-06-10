import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests
from src.database import get_db
from src.config import settings
from src.models.user import User

# Allow HTTP traffic for local development testing
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

router = APIRouter(prefix="/auth", tags=["Authentication"])

# MVP in-memory store for OAuth state
oauth_state_store = {}

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events"
]

def get_google_flow() -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret.get_secret_value(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri
    )

@router.get("/login")
async def login():
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    
    # Save the generated code verifier so the callback can prove who it is
    oauth_state_store[state] = getattr(flow, 'code_verifier', None)
    
    return RedirectResponse(url=authorization_url)


@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    flow = get_google_flow()
    
    # Retrieve the code verifier using the state parameter returned by Google
    state = request.query_params.get("state")
    if state in oauth_state_store:
        flow.code_verifier = oauth_state_store.pop(state)
        
    flow.fetch_token(authorization_response=str(request.url))
    credentials = flow.credentials
    
    # Extract the user's real email from the Google ID token securely
    token_request = requests.Request()
    id_info = id_token.verify_oauth2_token(
        id_token=credentials.id_token, 
        request=token_request, 
        audience=settings.google_client_id
    )
    user_email = id_info.get("email")
    
    creds_dict = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }

    # Safely check if user already exists
    result = await db.execute(select(User).where(User.email == user_email))
    user = result.scalars().first()

    if user:
        # Update existing user's tokens
        user.google_oauth_tokens = creds_dict
    else:
        # Create new user
        user = User(email=user_email, google_oauth_tokens=creds_dict)
        db.add(user)
        
    await db.commit()
    
    return {"message": f"Successfully authenticated as {user_email}", "user_id": str(user.id)}