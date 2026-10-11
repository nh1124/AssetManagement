from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, DateTime, JSON, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ..database import Base

class PeriodReview(Base):
    """PDCA review notes for an explicit accounting period."""
    __tablename__ = "period_reviews"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    label = Column(String, nullable=False, default="")
    reflection = Column(Text, default="")
    next_actions = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("client_id", "start_date", "end_date", name="_client_review_range_uc"),)

    client = relationship("Client", back_populates="period_reviews")


class MonthlyAction(Base):
    """Auditable decision/action record generated from monthly reports or reviews."""
    __tablename__ = "monthly_actions"
    __table_args__ = (
        UniqueConstraint("client_id", "idempotency_key", name="_client_action_idempotency_uc"),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    source_period = Column(String, nullable=False)
    target_period = Column(String, nullable=True)
    proposal_id = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    description = Column(Text, default="")
    amount = Column(Float, nullable=True)
    target_id = Column(Integer, nullable=True)
    payload = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    status = Column(String, default="pending")  # pending / applied / skipped / failed
    idempotency_key = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    applied_at = Column(DateTime, nullable=True)

    client = relationship("Client", back_populates="monthly_actions")
