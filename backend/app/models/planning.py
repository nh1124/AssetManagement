from datetime import datetime

from sqlalchemy import Column, Integer, String, Date, ForeignKey, DateTime, JSON, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from sqlalchemy.ext.hybrid import hybrid_property

from ..domain.money import Money
from .money import MinorUnits, major_expression, client_currency, client_currency_expression
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


class PeriodClose(Base):
    """A review marker; journal corrections remain permitted after closing."""
    __tablename__ = "period_closes"
    __table_args__ = (UniqueConstraint("client_id", "period", name="uq_period_closes_client_period"),)

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    period = Column(String(7), nullable=False)
    closed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    note = Column(String, nullable=True)
