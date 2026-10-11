from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean, DateTime, UniqueConstraint, Index, and_
from sqlalchemy.orm import relationship

from ..database import Base

class BudgetPlan(Base):
    """Named cash-flow planning scenario for comparing budget strategies."""
    __tablename__ = "budget_plans"
    __table_args__ = (UniqueConstraint("client_id", "name", name="_client_budget_plan_name_uc"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_default = Column(Boolean, default=False, server_default="false", nullable=False)
    sort_order = Column(Integer, default=0, server_default="0", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="budget_plans")
    plan_lines = relationship("MonthlyPlanLine", back_populates="budget_plan")


class MonthlyPlanLine(Base):
    """Cash-flow planning line for one month.

    Represents income assumptions, spending, asset allocations, debt payments,
    borrowing, and planned drawdowns.
    """
    __tablename__ = "monthly_plan_lines"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    target_period = Column(String, nullable=False)  # Format: "YYYY-MM"
    line_type = Column(String, nullable=False)  # income, expense, allocation, debt_payment, borrowing, drawdown
    target_type = Column(String, default="manual", server_default="manual", nullable=False)
    target_id = Column(Integer, nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    name = Column(String, nullable=True)
    amount = Column(Float, default=0.0, nullable=False)
    source = Column(String, default="manual", server_default="manual", nullable=False)
    source_kind = Column(String, default="manual", server_default="manual", nullable=False)
    identity_key = Column(String, default="", server_default="", nullable=False)
    manual_override = Column(Boolean, default=False, server_default="false", nullable=False)
    cash_treatment = Column(String, default="auto", server_default="auto", nullable=False)  # auto, cash, non_cash
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plan_id = Column(Integer, ForeignKey("budget_plans.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        Index(
            "uq_monthly_plan_lines_active_identity",
            "client_id",
            "identity_key",
            unique=True,
            sqlite_where=and_(is_active.is_(True), identity_key != ""),
            postgresql_where=and_(is_active.is_(True), identity_key != ""),
        ),
    )

    client = relationship("Client", back_populates="monthly_plan_lines")
    account = relationship("Account", foreign_keys=[account_id])
    source_account = relationship("Account", foreign_keys=[source_account_id])
    budget_plan = relationship("BudgetPlan", back_populates="plan_lines")
