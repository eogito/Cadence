import asyncio
import msal
from sqlalchemy import update
from src.config import settings
from src.database import AsyncSessionLocal
from src.models.user import User
from src.services.crypto import encrypt_token, decrypt_token

# Delegated Graph scopes (MSAL adds reserved openid/profile/offline_access).
SCOPES = ["User.Read", "Mail.Read", "Mail.Send", "Calendars.ReadWrite"]


def build_msal_app(cache: msal.SerializableTokenCache | None = None) -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.ms_client_id,
        authority=settings.ms_authority,
        client_credential=settings.ms_client_secret.get_secret_value(),
        token_cache=cache,
    )


class MicrosoftAuthService:
    @staticmethod
    async def get_access_token(user: User) -> str:
        """Return a valid Graph access token for the user, refreshing silently.

        Persists a rotated token cache back to the DB. Raises PermissionError
        if the user must re-authenticate.
        """
        cache = msal.SerializableTokenCache()
        if user.ms_token_cache:
            raw = decrypt_token(user.ms_token_cache)
            if raw is None:
                raise PermissionError("Microsoft session expired — sign in again.")
            cache.deserialize(raw)
        app = build_msal_app(cache)

        accounts = app.get_accounts()
        if not accounts:
            raise PermissionError("No Microsoft account on file — sign in again.")
        result = await asyncio.to_thread(app.acquire_token_silent, SCOPES, account=accounts[0])
        if not result or "access_token" not in result:
            raise PermissionError("Microsoft session expired — sign in again.")

        if cache.has_state_changed:
            encrypted = encrypt_token(cache.serialize())
            user.ms_token_cache = encrypted
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(User).where(User.id == user.id).values(ms_token_cache=encrypted)
                )
                await db.commit()

        return result["access_token"]
