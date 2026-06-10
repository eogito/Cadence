import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base

class RecurringRule(Base):
    """
    Stores user-defined recurring actions, e.g.:
      - "Every day at 4PM: remind me to send 5 cold emails"
      - "Every Monday at 9AM: check school deadlines"
    """
    __tablename__ = "recurring_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    description = Column(String(500), nullable=False)  # human-readable label
    cron_hour = Column(String(10), nullable=True)       # e.g. "16" for 4PM
    cron_minute = Column(String(10), default="0")
    cron_day_of_week = Column(String(20), nullable=True)  # e.g. "mon,wed" or "*"

    # What to create when this fires
    task_title = Column(String(500), nullable=False)    # e.g. "Send 5 cold emails"
    task_priority = Column(String(20), default="medium")

    active = Column(Boolean, default=True)
    last_fired = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
