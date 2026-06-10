import asyncio
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from src.models.user import User

class GoogleAuthService:
    @staticmethod
    def _build_credentials(token_data: dict) -> Credentials:
        return Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes")
        )

    @classmethod
    async def get_gmail_service(cls, user: User):
        creds = cls._build_credentials(user.google_oauth_tokens)
        service = await asyncio.to_thread(build, "gmail", "v1", credentials=creds)
        return service

    @classmethod
    async def get_calendar_service(cls, user: User):
        creds = cls._build_credentials(user.google_oauth_tokens)
        service = await asyncio.to_thread(build, "calendar", "v3", credentials=creds)
        return service