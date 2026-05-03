from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, Boolean, DateTime, JSON, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
import enum
from .database import Base

class TransactionType(str, enum.Enum):
    INCOME = "Income"
    EXPENSE = "Expense"
    TRANSFER = "Transfer"
    LIABILITY_PAYMENT = "LiabilityPayment"
    BORROWING = "Borrowing"
    CREDIT_EXPENSE = "CreditExpense"
    CREDIT_ASSET_PURCHASE = "CreditAssetPurchase"

class AccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    INCOME = "income"
    EXPENSE = "expense"

class AccountRole(str, enum.Enum):
    DEFENSE = "defense"
    GROWTH = "growth"
    EARMARKED = "earmarked"
    OPERATING = "operating"
    UNASSIGNED = "unassigned"

class Client(Base):
    """SaaS Client/User: Owns a subset of data. Matches VisionArk's User + UserSettings pattern."""
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True, nullable=True) # For login
    email = Column(String, unique=True, index=True, nullable=True)    # For login/recovery
    password_hash = Column(String, nullable=True)                    # Bcrypt hash
    ai_config = Column(JSON, default=dict)  # { "gemini_api_key": "...", "openai_api_key": "..." }
    general_settings = Column(JSON, default=dict) # { "currency": "JPY", "language": "ja" }
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    @property
    def gemini_api_key(self):
        """Automatically decrypt and return the Gemini API key. Pattern from VisionArk."""
        if not self.ai_config:
            return None
        encrypted_key = self.ai_config.get("gemini_api_key")
        if not encrypted_key:
            return None
        from .security import decrypt_key
        return decrypt_key(encrypted_key)

    # Relationships
    accounts = relationship("Account", back_populates="client")
    transactions = relationship("Transaction", back_populates="client")
    products = relationship("Product", back_populates="client")
    life_events = relationship("LifeEvent", back_populates="client")
    simulation_configs = relationship("SimulationConfig", back_populates="client")
    recurring_transactions = relationship("RecurringTransaction", back_populates="client")
    milestones = relationship("Milestone", back_populates="client")
    capsules = relationship("Capsule", back_populates="client")
    capsule_rules = relationship("CapsuleRule", back_populates="client")
    monthly_reviews = relationship("MonthlyReview", back_populates="client")
    period_reviews = relationship("PeriodReview", back_populates="client")
    monthly_actions = relationship("MonthlyAction", back_populates="client")

class Account(Base):
    """Double-entry accounting: Each account has a type and balance."""
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint('client_id', 'name', name='_client_account_uc'),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    account_type = Column(String)  # asset, liability, income, expense
    balance = Column(Float, default=0)
    parent_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    expected_return = Column(Float, default=0.0)  # Annual return rate % for asset accounts
    role = Column(String, default=AccountRole.UNASSIGNED.value, server_default=AccountRole.UNASSIGNED.value, nullable=False)
    role_target_amount = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    
    client = relationship("Client", back_populates="accounts")
    entries = relationship("JournalEntry", back_populates="account")

class JournalEntry(Base):
    """Double-entry: Each transaction creates debit and credit entries."""
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"))
    account_id = Column(Integer, ForeignKey("accounts.id"))
    debit = Column(Float, default=0)
    credit = Column(Float, default=0)
    
    account = relationship("Account", back_populates="entries")
    transaction = relationship("Transaction", back_populates="journal_entries")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    date = Column(Date)
    description = Column(String)
    amount = Column(Float)
    type = Column(String)
    category = Column(String, nullable=True)
    currency = Column(String, default='JPY')
    from_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    to_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    client = relationship("Client", back_populates="transactions")
    journal_entries = relationship("JournalEntry", back_populates="transaction")
    from_account_rel = relationship("Account", foreign_keys=[from_account_id])
    to_account_rel = relationship("Account", foreign_keys=[to_account_id])


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    category = Column(String)
    location = Column(String, nullable=True)
    last_unit_price = Column(Float)
    units_per_purchase = Column(Integer, nullable=True, default=1)
    frequency_days = Column(Integer, default=0)
    last_purchase_date = Column(Date, nullable=True)
    is_asset = Column(Boolean, default=False)
    lifespan_months = Column(Integer, nullable=True)
    # Depreciation tracking
    purchase_price = Column(Float, nullable=True)
    purchase_date = Column(Date, nullable=True)

    client = relationship("Client", back_populates="products")

class SimulationConfig(Base):
    __tablename__ = "simulation_configs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    user_id = Column(Integer, default=1)
    annual_return = Column(Float, default=5.0)
    tax_rate = Column(Float, default=20.0)
    is_nisa = Column(Boolean, default=True)
    monthly_savings = Column(Float, default=100000)
    volatility = Column(Float, default=15.0)
    inflation_rate = Column(Float, default=2.0)

    client = relationship("Client", back_populates="simulation_configs")

class RecurringTransaction(Base):
    __tablename__ = "recurring_transactions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    amount = Column(Float)
    type = Column(String)  # Income, Expense, Transfer, LiabilityPayment, Borrowing, CreditExpense, CreditAssetPurchase
    from_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    to_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    frequency = Column(String)  # Monthly, Yearly
    day_of_month = Column(Integer, default=1)
    month_of_year = Column(Integer, nullable=True)  # For Yearly frequency
    next_due_date = Column(Date, nullable=True)  # Calculated by system
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="recurring_transactions")
    from_account = relationship("Account", foreign_keys=[from_account_id])
    to_account = relationship("Account", foreign_keys=[to_account_id])

class LifeEvent(Base):
    """Future liabilities/goals for Personal ALM (Asset Liability Management)."""
    __tablename__ = "life_events"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)  # e.g., "Retirement", "House"
    target_date = Column(Date)
    target_amount = Column(Float)
    priority = Column(Integer, default=2)  # 1=High, 2=Medium, 3=Low
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="life_events")
    allocations = relationship("GoalAllocation", back_populates="life_event", cascade="all, delete-orphan")
    milestones = relationship("Milestone", back_populates="life_event", cascade="all, delete-orphan")

class GoalAllocation(Base):
    """Links assets to life events (the 'buckets' for funding goals)."""
    __tablename__ = "goal_allocations"
    __table_args__ = (UniqueConstraint("life_event_id", "account_id", name="_goal_allocation_event_account_uc"),)

    id = Column(Integer, primary_key=True, index=True)
    life_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"))
    account_id = Column(Integer, ForeignKey("accounts.id"))
    allocation_percentage = Column(Float)  # 0.0 - 100.0

    life_event = relationship("LifeEvent", back_populates="allocations")
    account = relationship("Account")

class MonthlyBudget(Base):
    """Tracks budgets per month for expense accounts."""
    __tablename__ = "monthly_budgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(Integer, ForeignKey("clients.id"))
    account_id = Column(Integer, ForeignKey("accounts.id"))
    target_period = Column(String)  # Format: "YYYY-MM"
    amount = Column(Float)

    __table_args__ = (UniqueConstraint('account_id', 'target_period', name='_account_period_uc'),)

    client = relationship("Client")
    account = relationship("Account")

class MonthlyReview(Base):
    """PDCA review notes for a specific month."""
    __tablename__ = "monthly_reviews"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    target_period = Column(String, nullable=False)  # Format: "YYYY-MM"
    reflection = Column(Text, default="")
    next_actions = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("client_id", "target_period", name="_client_review_period_uc"),)

    client = relationship("Client", back_populates="monthly_reviews")


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

class Milestone(Base):
    __tablename__ = "milestones"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    life_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"), nullable=True)
    date = Column(Date)
    target_amount = Column(Float)
    note = Column(String, nullable=True)
    source = Column(String, default="manual", server_default="manual", nullable=False)
    source_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="milestones")
    life_event = relationship("LifeEvent", back_populates="milestones")

class Capsule(Base):
    __tablename__ = "capsules"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    life_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="SET NULL"), nullable=True)
    name = Column(String, index=True)
    target_amount = Column(Float)
    monthly_contribution = Column(Float)
    current_balance = Column(Float, default=0.0)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="capsules")
    account = relationship("Account", foreign_keys=[account_id])
    life_event = relationship("LifeEvent")


class CapsuleRule(Base):
    __tablename__ = "capsule_rules"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    capsule_id = Column(Integer, ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False)
    trigger_type = Column(String, nullable=False)
    trigger_category = Column(String, nullable=True)
    trigger_description = Column(String, nullable=True)
    source_mode = Column(String, default="transaction_account", nullable=False)
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    amount_type = Column(String, default="fixed", nullable=False)
    amount_value = Column(Float, default=0.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="capsule_rules")
    capsule = relationship("Capsule")
    source_account = relationship("Account", foreign_keys=[source_account_id])
