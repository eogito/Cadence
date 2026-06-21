import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, Integer, Boolean, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class ScheduleBlock(Base):
    """A single editable time block in a user's daily schedule."""
    __tablename__ = "schedule_blocks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day = Column(Date, nullable=False, index=True)
    start_minute = Column(Integer, nullable=False)      # minutes from local midnight
    duration_minutes = Column(Integer, nullable=False, default=30)
    title = Column(String(500), nullable=False)
    notes = Column(Text, nullable=True)
    category = Column(String(20), default="manual")     # fixed_event/task/rule_based/suggested/manual
    importance = Column(Integer, nullable=True)
    done = Column(Boolean, default=False)
    locked = Column(Boolean, default=False)
    outlook_event_id = Column(String(255), nullable=True)
    source = Column(String(10), default="manual")       # ai / manual
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
