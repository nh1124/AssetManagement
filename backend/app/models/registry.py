from datetime import datetime

from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean, DateTime, Text
from sqlalchemy.orm import relationship

from sqlalchemy.ext.hybrid import hybrid_property

from ..domain.money import Money
from .money import MinorUnits, major_expression
from ..database import Base

class RecurringTransaction(Base):
    __tablename__ = "recurring_transactions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    amount_minor = Column(MinorUnits)
    currency = Column(String, default="JPY", server_default="JPY", nullable=False)
    from_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    to_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    frequency = Column(String)  # Monthly, Yearly
    day_of_month = Column(Integer, default=1)
    month_of_year = Column(Integer, nullable=True)  # For Yearly frequency
    next_due_date = Column(Date, nullable=True)  # Calculated by system
    start_period = Column(String, nullable=True)  # Format: "YYYY-MM"; included from this month
    end_period = Column(String, nullable=True)  # Format: "YYYY-MM"; included through this month
    auto_post = Column(Boolean, default=True, server_default="true", nullable=False)
    is_active = Column(Boolean, default=True)
    # The registry is the only writer and owns the definition. The router deletes
    # it first; CASCADE also supports the import's bulk registry wipe.
    source_registry_entry_id = Column(
        Integer,
        ForeignKey("registry_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="recurring_transactions")
    from_account = relationship("Account", foreign_keys=[from_account_id])
    to_account = relationship("Account", foreign_keys=[to_account_id])
    source_registry_entry = relationship("RegistryEntry", foreign_keys=[source_registry_entry_id])

    @hybrid_property
    def amount(self) -> float | None:
        if self.amount_minor is None:
            return None
        return Money(self.amount_minor, self.currency).to_float()

    @amount.expression
    def amount(cls):
        return major_expression(cls.amount_minor, cls.currency)


class RegistryEntry(Base):
    """Primary registry for recurring cash-flow assumptions."""
    __tablename__ = "registry_entries"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String, index=True, nullable=False)
    entry_type = Column(String, nullable=False, default="service")
    category = Column(String, nullable=True)
    amount_minor = Column(MinorUnits, nullable=False, default=0)
    currency = Column(String, default="JPY", server_default="JPY", nullable=False)
    frequency = Column(String, default="Monthly", server_default="Monthly", nullable=False)
    frequency_days = Column(Integer, nullable=True)
    day_of_month = Column(Integer, default=1, server_default="1", nullable=False)
    month_of_year = Column(Integer, nullable=True)
    line_type = Column(String, nullable=False, default="expense")
    budget_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    source_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    destination_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    funding_capsule_id = Column(Integer, ForeignKey("capsules.id", ondelete="SET NULL"), nullable=True)
    budget_treatment = Column(String, nullable=False, default="expense_only")
    generate_recurring = Column(Boolean, default=False, server_default="false", nullable=False)
    budget_active = Column(Boolean, default=True, server_default="true", nullable=False)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    source_product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    source_recurring_transaction_id = Column(Integer, ForeignKey("recurring_transactions.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=True)
    start_period = Column(String, nullable=True)
    end_period = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="registry_entries")
    budget_account = relationship("Account", foreign_keys=[budget_account_id])
    source_account = relationship("Account", foreign_keys=[source_account_id])
    destination_account = relationship("Account", foreign_keys=[destination_account_id])
    funding_capsule = relationship("Capsule", foreign_keys=[funding_capsule_id])
    source_product = relationship("Product", foreign_keys=[source_product_id])

    @hybrid_property
    def amount(self) -> float | None:
        if self.amount_minor is None:
            return None
        return Money(self.amount_minor, self.currency).to_float()

    @amount.expression
    def amount(cls):
        return major_expression(cls.amount_minor, cls.currency)
