import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from src.database import Base

VALID_CATEGORIES = ["primary", "social", "promotions", "updates", "forums"]
DEFAULT_CATEGORIES = ["primary", "updates"]


class EmailPreferences(Base):
    __tablename__ = "email_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), unique=True, index=True, nullable=False)
    tracked_categories = Column(JSONB, nullable=False, default=lambda: list(DEFAULT_CATEGORIES))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
