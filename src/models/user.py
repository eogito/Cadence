import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    google_oauth_tokens = Column(JSONB, nullable=True)
    ms_token_cache = Column(Text, nullable=True)            # serialized MSAL SerializableTokenCache
    ms_account_id = Column(String(255), nullable=True, index=True)  # MSAL account/object id

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))