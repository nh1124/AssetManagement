from datetime import datetime

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON, Text, UniqueConstraint, CheckConstraint

from ..database import Base


class Notification(Base):
    """Something that needs the user's attention, and what the user decided about it.

    Generators recompute the reasons from the data; this row keeps the decision:
    open, snoozed until a time (後で確認), dismissed (見送り) until the reasons change --
    changed reasons get a new dedupe_key and so a new row -- or done, when the
    action itself resolved it or the reasons went away.
    """
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("client_id", "dedupe_key", name="uq_notifications_client_key"),
        CheckConstraint("status IN ('open', 'snoozed', 'dismissed', 'done')", name="ck_notifications_status"),
    )

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)
    dedupe_key = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False, default="")
    payload = Column(JSON, nullable=False, default=dict)
    link = Column(String, nullable=True)
    status = Column(String, nullable=False, default="open", server_default="open")
    snoozed_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
