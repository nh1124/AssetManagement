from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, Boolean, DateTime, JSON, UniqueConstraint
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

class AccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    INCOME = "income"
    EXPENSE = "expense"

class Priority(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

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
    budgets = relationship("Budget", back_populates="client")
    simulation_configs = relationship("SimulationConfig", back_populates="client")
    recurring_transactions = relationship("RecurringTransaction", back_populates="client")

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
    budget_limit = Column(Float, nullable=True)  # Monthly budget for expense accounts
    expected_return = Column(Float, default=0.0)  # Annual return rate % for asset accounts
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

class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String)
    value = Column(Float)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)


class Liability(Base):
    __tablename__ = "liabilities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String)
    lender = Column(String, nullable=True)
    total_borrowed = Column(Float, default=0)
    amount_repaid = Column(Float, default=0)
    balance = Column(Float)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

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
    from_account = Column(String, nullable=True)
    to_account = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    client = relationship("Client", back_populates="transactions")
    journal_entries = relationship("JournalEntry", back_populates="transaction")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    category = Column(String)
    location = Column(String, nullable=True)
    last_unit_price = Column(Float)
    frequency_days = Column(Integer, default=0)
    last_purchase_date = Column(Date, nullable=True)
    is_asset = Column(Boolean, default=False)
    lifespan_months = Column(Integer, nullable=True)
    # Depreciation tracking
    purchase_price = Column(Float, nullable=True)
    purchase_date = Column(Date, nullable=True)

    client = relationship("Client", back_populates="products")

class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    category = Column(String, index=True)
    proposed_amount = Column(Float)
    current_spending = Column(Float, default=0)
    month = Column(String)  # Format: YYYY-MM
    derived_from = Column(String, nullable=True)

    client = relationship("Client", back_populates="budgets")

class SimulationConfig(Base):
    __tablename__ = "simulation_configs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    user_id = Column(Integer, default=1)
    annual_return = Column(Float, default=5.0)
    tax_rate = Column(Float, default=20.0)
    is_nisa = Column(Boolean, default=True)
    monthly_savings = Column(Float, default=100000)

    client = relationship("Client", back_populates="simulation_configs")

class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, default=1)
    gemini_api_key = Column(String, nullable=True)
    default_currency = Column(String, default='JPY')
    language = Column(String, default='ja')

class RecurringTransaction(Base):
    __tablename__ = "recurring_transactions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    amount = Column(Float)
    type = Column(String)  # Income, Expense, Transfer, Debt
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

class GoalAllocation(Base):
    """Links assets to life events (the 'buckets' for funding goals)."""
    __tablename__ = "goal_allocations"

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
