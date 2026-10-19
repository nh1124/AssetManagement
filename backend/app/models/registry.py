from datetime import datetime

from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean, DateTime, Text
from sqlalchemy.orm import relationship

from sqlalchemy.ext.hybrid import hybrid_property

from ..domain.money import Money
from .money import MinorUnits, major_expression
from ..database import Base

class RegistryEntry(Base):
    """Automatic transactions and their posting cursor."""
    __tablename__ = "registry_entries"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String, index=True, nullable=False)
    kind = Column(String, nullable=False, default="expense")
    amount_minor = Column(MinorUnits, nullable=False, default=0)
    currency = Column(String, default="JPY", server_default="JPY", nullable=False)
    source_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    destination_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    budget_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    repeat_mode = Column(String, nullable=False, default="indefinite")
    frequency = Column(String, nullable=True)
    frequency_days = Column(Integer, nullable=True)
    day_of_month = Column(Integer, nullable=True)
    month_of_year = Column(Integer, nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    repeat_count = Column(Integer, nullable=True)
    next_due_date = Column(Date, nullable=True)
    budget_active = Column(Boolean, default=True, server_default="true", nullable=False)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="registry_entries")
    budget_account = relationship("Account", foreign_keys=[budget_account_id])
    source_account = relationship("Account", foreign_keys=[source_account_id])
    destination_account = relationship("Account", foreign_keys=[destination_account_id])

    @hybrid_property
    def amount(self) -> float | None:
        if self.amount_minor is None:
            return None
        return Money(self.amount_minor, self.currency).to_float()

    @amount.expression
    def amount(cls):
        return major_expression(cls.amount_minor, cls.currency)
