import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base

class UserContext(Base):
    """Personal context items (schedules, preferences, important dates) stored in PostgreSQL."""
    __tablename__ = "user_context"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(String(255), nullable=False, unique=True)  # stable ChromaDB-compatible ID
    text = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)  # schedule | important_date | recurring_rule | preference
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
