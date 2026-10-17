from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean, DateTime, JSON, BigInteger, Float, CheckConstraint, UniqueConstraint, Index, text
from sqlalchemy.orm import relationship

from sqlalchemy.ext.hybrid import hybrid_property

from ..domain.money import Money
from .money import MinorUnits, major_expression, client_currency, client_currency_expression
from ..database import Base

class LifeEvent(Base):
    """Planned expenses and inflows for Personal ALM."""
    __tablename__ = "life_events"

    __table_args__ = (
        CheckConstraint("condition_mode IN ('all', 'any')", name="ck_life_events_condition_mode"),
        CheckConstraint("direction IN ('expense', 'income')", name="ck_life_events_direction"),
    )

    condition_mode = Column(String, nullable=False, default="all", server_default="all")
    direction = Column(String, nullable=False, default="expense", server_default="expense")
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    scenario_id = Column(Integer, ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    lineage = Column(String(36), nullable=False, index=True, default=lambda: str(uuid4()))
    name = Column(String, index=True)  # e.g., "Retirement", "House"
    start_date = Column(Date, nullable=True)
    target_date = Column(Date)
    target_amount_minor = Column(MinorUnits)
    priority = Column(Integer, default=2)  # 1=High, 2=Medium, 3=Low
    note = Column(String, nullable=True)
    active_plan_basis = Column(String, default="milestone", server_default="milestone", nullable=False)
    active_plan_label = Column(String, nullable=True)
    plan_status_override = Column(String, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="life_events")
    milestones = relationship("Milestone", back_populates="life_event", cascade="all, delete-orphan")
    capsules = relationship("Capsule", back_populates="life_event", cascade="all, delete-orphan")
    conditions = relationship("LifeEventCondition", cascade="all, delete-orphan")
    outgoing_links = relationship("LifeEventLink", foreign_keys="LifeEventLink.from_event_id", cascade="all, delete-orphan")
    incoming_links = relationship("LifeEventLink", foreign_keys="LifeEventLink.to_event_id", cascade="all, delete-orphan")

    @hybrid_property
    def target_amount(self) -> float | None:
        if self.target_amount_minor is None:
            return None
        return Money(self.target_amount_minor, client_currency(self)).to_float()

    @target_amount.expression
    def target_amount(cls):
        return major_expression(cls.target_amount_minor, client_currency_expression(cls))


class LifeEventLink(Base):
    __tablename__ = "life_event_links"
    __table_args__ = (
        UniqueConstraint("client_id", "from_event_id", "to_event_id", name="uq_life_event_links_pair"),
        CheckConstraint("kind = 'after'", name="ck_life_event_links_kind"),
    )

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    from_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False)
    to_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)
    offset_months = Column(Integer, nullable=False, default=0, server_default="0")
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


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


class HouseholdMember(Base):
    __tablename__ = "household_members"
    __table_args__ = (UniqueConstraint("client_id", "name", name="uq_household_members_name"),)

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String, nullable=False)
    relation = Column(String, nullable=True)
    birth_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class LifeEventCondition(Base):
    __tablename__ = "life_event_conditions"
    __table_args__ = (
        CheckConstraint("metric IN ('net_worth', 'free_cash', 'account_balance', 'capsule_claim', 'goal_progress', 'member_age', 'date_reached')", name="ck_life_event_conditions_metric"),
        CheckConstraint("comparator IN ('gte', 'lte', 'eq')", name="ck_life_event_conditions_comparator"),
    )

    # A flat all/any list is enough; a tree costs maintenance until a real case needs nesting.
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    life_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False, index=True)
    metric = Column(String, nullable=False)
    comparator = Column(String, nullable=False)
    threshold_minor = Column(BigInteger, nullable=True)
    threshold_number = Column(Float, nullable=True)
    threshold_date = Column(Date, nullable=True)
    # References intentionally have no FK: deleted facts remain reportable assumptions.
    reference_id = Column(Integer, nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LifeScenario(Base):
    __tablename__ = "life_scenarios"
    __table_args__ = (
        UniqueConstraint("client_id", "name", name="uq_life_scenarios_name"),
        CheckConstraint("horizon_years BETWEEN 1 AND 60", name="ck_life_scenarios_horizon_years"),
        Index("uq_life_scenarios_goal", "client_id", unique=True,
              postgresql_where=text("is_goal"), sqlite_where=text("is_goal")),
    )

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String, nullable=False)
    annual_return = Column(Float, nullable=False, default=5.0, server_default="5.0")
    inflation = Column(Float, nullable=False, default=2.0, server_default="2.0")
    horizon_years = Column(Integer, nullable=False, default=30, server_default="30")
    is_goal = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    events = relationship("LifeEvent", cascade="all, delete-orphan", passive_deletes=True)
    account_returns = relationship("LifeScenarioAccountReturn", cascade="all, delete-orphan")


class LifeScenarioAccountReturn(Base):
    __tablename__ = "life_scenario_account_returns"
    __table_args__ = (UniqueConstraint("scenario_id", "account_id", name="uq_life_scenario_account_returns_account"),)

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    annual_return = Column(Float, nullable=False)
