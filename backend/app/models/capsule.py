from datetime import datetime

from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, CheckConstraint, case, cast, Float
from sqlalchemy.orm import relationship

from sqlalchemy.ext.hybrid import hybrid_property

from ..domain.money import Money
from .money import MinorUnits, BasisPoints, major_expression, client_currency, client_currency_expression
from ..database import Base

class Capsule(Base):
    __tablename__ = "capsules"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    life_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, index=True)
    target_amount_minor = Column(MinorUnits)
    monthly_contribution_minor = Column(MinorUnits)
    current_balance_minor = Column(MinorUnits, default=0)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    # The capsule decides whether its reservations need a decision; the vocabulary
    # deliberately matches RecurringTransaction.auto_post.
    auto_post = Column(Boolean, default=False, server_default="false", nullable=False)
    capsule_type = Column(String, default="manual", server_default="manual", nullable=False)
    target_amount_source = Column(String, default="manual", server_default="manual", nullable=False)
    monthly_contribution_source = Column(String, default="manual", server_default="manual", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="capsules")
    account = relationship("Account", foreign_keys=[account_id])
    life_event = relationship("LifeEvent", back_populates="capsules")
    holdings = relationship("CapsuleHolding", back_populates="capsule", cascade="all, delete-orphan")

    @hybrid_property
    def target_amount(self) -> float | None:
        if self.target_amount_minor is None:
            return None
        return Money(self.target_amount_minor, client_currency(self)).to_float()

    @target_amount.expression
    def target_amount(cls):
        return major_expression(cls.target_amount_minor, client_currency_expression(cls))

    @hybrid_property
    def monthly_contribution(self) -> float | None:
        if self.monthly_contribution_minor is None:
            return None
        return Money(self.monthly_contribution_minor, client_currency(self)).to_float()

    @monthly_contribution.expression
    def monthly_contribution(cls):
        return major_expression(cls.monthly_contribution_minor, client_currency_expression(cls))

    @hybrid_property
    def current_balance(self) -> float | None:
        if self.current_balance_minor is None:
            return None
        return Money(self.current_balance_minor, client_currency(self)).to_float()

    @current_balance.expression
    def current_balance(cls):
        return major_expression(cls.current_balance_minor, client_currency_expression(cls))


class CapsuleRule(Base):
    __tablename__ = "capsule_rules"
    __table_args__ = (CheckConstraint(
        "(amount_type = 'fixed' AND amount_minor IS NOT NULL AND percentage_bp IS NULL) OR "
        "(amount_type = 'percentage' AND amount_minor IS NULL AND percentage_bp IS NOT NULL)",
        name="ck_capsule_rule_amount_kind",
    ),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    capsule_id = Column(Integer, ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False)
    trigger_type = Column(String, nullable=False)
    trigger_category = Column(String, nullable=True)
    trigger_description = Column(String, nullable=True)
    source_mode = Column(String, default="transaction_account", nullable=False)
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    amount_type = Column(String, default="fixed", nullable=False)
    amount_minor = Column(MinorUnits, nullable=True)
    percentage_bp = Column(BasisPoints, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="capsule_rules")
    capsule = relationship("Capsule")
    source_account = relationship("Account", foreign_keys=[source_account_id])

    @hybrid_property
    def amount_value(self) -> float:
        if self.amount_type == "percentage":
            return self.percentage_bp / 100
        return Money(self.amount_minor, client_currency(self)).to_float()

    @amount_value.expression
    def amount_value(cls):
        return case(
            (cls.amount_type == "percentage", cast(cls.percentage_bp, Float) / 100),
            else_=major_expression(cls.amount_minor, client_currency_expression(cls)),
        )


class CapsuleHolding(Base):
    __tablename__ = "capsule_holdings"

    id = Column(Integer, primary_key=True, index=True)
    capsule_id = Column(Integer, ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    held_amount_minor = Column(MinorUnits, nullable=False, default=0)
    note = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    capsule = relationship("Capsule", back_populates="holdings")
    account = relationship("Account")

    @hybrid_property
    def held_amount(self) -> float | None:
        if self.held_amount_minor is None:
            return None
        return Money(self.held_amount_minor, client_currency(self)).to_float()

    @held_amount.expression
    def held_amount(cls):
        return major_expression(cls.held_amount_minor, client_currency_expression(cls))
