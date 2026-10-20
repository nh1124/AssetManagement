from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean, DateTime, JSON, BigInteger, Float, CheckConstraint, UniqueConstraint, Index, text
from sqlalchemy.orm import relationship

from sqlalchemy.ext.hybrid import hybrid_property

from ..domain.money import Money
from .money import MinorUnits, major_expression, client_currency, client_currency_expression
from ..database import Base

class LifeEvent(Base):
    """A planned expense, inflow, borrowing or repayment in one scenario's story.

    The event names no account: what an account gives toward it is a 積立設定 record
    of the simulation settings (ScenarioContributionPlan.life_event_id). A repayment
    names its borrowing and pays target_amount a month for repeat_count months; a
    borrowing carries its yearly interest_rate.
    """
    __tablename__ = "life_events"

    __table_args__ = (
        CheckConstraint("condition_mode IN ('all', 'any')", name="ck_life_events_condition_mode"),
        CheckConstraint("direction IN ('expense', 'income', 'borrowing', 'repayment')", name="ck_life_events_direction"),
    )

    condition_mode = Column(String, nullable=False, default="all", server_default="all")
    direction = Column(String, nullable=False, default="expense", server_default="expense")
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    scenario_id = Column(Integer, ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    lineage = Column(String(36), nullable=False, index=True, default=lambda: str(uuid4()))
    name = Column(String, index=True)  # e.g., "Retirement", "House"
    target_date = Column(Date)
    target_amount_minor = Column(MinorUnits)
    priority = Column(Integer, default=2)  # 1=High, 2=Medium, 3=Low
    note = Column(String, nullable=True)
    interest_rate = Column(Float, nullable=True)
    borrowing_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="SET NULL"), nullable=True)
    repeat_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="life_events")
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
    # The yield of an account whose contribution plan names none.
    annual_return = Column(Float, nullable=False, default=5.0, server_default="5.0")
    inflation = Column(Float, nullable=False, default=2.0, server_default="2.0")
    horizon_years = Column(Integer, nullable=False, default=30, server_default="30")
    is_goal = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client")
    events = relationship("LifeEvent", cascade="all, delete-orphan", passive_deletes=True)
    contribution_plans = relationship("ScenarioContributionPlan", cascade="all, delete-orphan", passive_deletes=True)


class ScenarioContributionPlan(Base):
    """積立設定: one record of a scenario's simulation settings (WP23).

    kind says what the record moves, amount_minor (never negative) how much each time:
    - contribution (積立): into account_id; annual_return, when set, is the account's
      yield from start_period until a later record of the account names another;
    - transfer (口座振替): from account_id to to_account_id;
    - withdrawal (ライフイベントへの取り崩し): from account_id toward life_event_id, an
      expense of the same scenario (e.g. 証券口座 ¥750,000 in 2028-10 for 結婚, or
      貯蓄口座 ¥100,000 every month from 2051-01, 360 times, for 老後生活).
    The schedule starts in start_period: once when interval_months is null, else every
    interval_months months (1 monthly, 12 yearly) until repeat_count times or
    end_period (inclusive) -- whichever comes first -- or the end of the simulation.
    Records add up; none replaces another. on_shortage says what a transfer or a
    withdrawal does when the account holds less than it moves: skip (取引を発生させない)
    or partial (ある分だけで取引する). Nothing is moved in from elsewhere.
    The accounts records name are the scenario's 使用口座, the only ones the simulation grows.
    """
    __tablename__ = "scenario_contribution_plans"
    __table_args__ = (
        CheckConstraint("kind IN ('contribution', 'transfer', 'withdrawal')", name="ck_scenario_contribution_plans_kind"),
        CheckConstraint("on_shortage IS NULL OR on_shortage IN ('skip', 'partial')", name="ck_scenario_contribution_plans_on_shortage"),
    )

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False, default="contribution", server_default="contribution")
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    to_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    start_period = Column(String(7), nullable=False)
    amount_minor = Column(BigInteger, nullable=False, default=0, server_default="0")
    interval_months = Column(Integer, nullable=True)
    repeat_count = Column(Integer, nullable=True)
    end_period = Column(String(7), nullable=True)
    on_shortage = Column(String(16), nullable=True)
    annual_return = Column(Float, nullable=True)
    note = Column(String, nullable=True)
    life_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("LifeEvent")
    account = relationship("Account", foreign_keys=[account_id])
    to_account = relationship("Account", foreign_keys=[to_account_id])


class GoalBudgetReflection(Base):
    """One applied goal-to-plan reflection: its months, scenario and what it wrote."""
    __tablename__ = "goal_budget_reflections"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    scenario_id = Column(Integer, ForeignKey("life_scenarios.id", ondelete="SET NULL"), nullable=True)
    applied_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    start_period = Column(String(7), nullable=False)
    end_period = Column(String(7), nullable=False)
    summary = Column(JSON, nullable=False)
