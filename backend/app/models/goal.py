from datetime import datetime

from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean, DateTime, JSON
from sqlalchemy.orm import relationship

from sqlalchemy.ext.hybrid import hybrid_property

from ..domain.money import Money
from .money import MinorUnits, major_expression, client_currency, client_currency_expression
from ..database import Base

class LifeEvent(Base):
    """Future liabilities/goals for Personal ALM (Asset Liability Management)."""
    __tablename__ = "life_events"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)  # e.g., "Retirement", "House"
    start_date = Column(Date, nullable=True)
    target_date = Column(Date)
    target_amount_minor = Column(MinorUnits)
    priority = Column(Integer, default=2)  # 1=High, 2=Medium, 3=Low
    note = Column(String, nullable=True)
    active_plan_basis = Column(String, default="milestone", server_default="milestone", nullable=False)
    active_plan_label = Column(String, nullable=True)
    plan_status_override = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="life_events")
    milestones = relationship("Milestone", back_populates="life_event", cascade="all, delete-orphan")
    capsules = relationship("Capsule", back_populates="life_event", cascade="all, delete-orphan")

    @hybrid_property
    def target_amount(self) -> float | None:
        if self.target_amount_minor is None:
            return None
        return Money(self.target_amount_minor, client_currency(self)).to_float()

    @target_amount.expression
    def target_amount(cls):
        return major_expression(cls.target_amount_minor, client_currency_expression(cls))


class Milestone(Base):
    __tablename__ = "milestones"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    life_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"), nullable=True)
    date = Column(Date)
    target_amount_minor = Column(MinorUnits)
    note = Column(String, nullable=True)
    source = Column(String, default="manual", server_default="manual", nullable=False)
    source_snapshot = Column(JSON, nullable=True)
    is_active_plan = Column(Boolean, default=True, server_default="true", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="milestones")
    life_event = relationship("LifeEvent", back_populates="milestones")

    @hybrid_property
    def target_amount(self) -> float | None:
        if self.target_amount_minor is None:
            return None
        return Money(self.target_amount_minor, client_currency(self)).to_float()

    @target_amount.expression
    def target_amount(cls):
        return major_expression(cls.target_amount_minor, client_currency_expression(cls))
