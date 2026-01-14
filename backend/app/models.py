from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, Boolean, DateTime, JSON
from sqlalchemy.orm import relationship
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

class Account(Base):
    """Double-entry accounting: Each account has a type and balance."""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    account_type = Column(String)  # asset, liability, income, expense
    balance = Column(Float, default=0)
    parent_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    budget_limit = Column(Float, nullable=True)  # Monthly budget for expense accounts
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
    
    goal_mappings = relationship("AssetGoalMapping", back_populates="asset")

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

class LifeEvent(Base):
    """Life Events = Future Liabilities (Goals)"""
    __tablename__ = "life_events"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    target_date = Column(Date)
    target_amount = Column(Float)
    funded_amount = Column(Float, default=0)
    priority = Column(String, default="medium")
    allocated_asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)
    monthly_contribution = Column(Float, default=0)
    
    client = relationship("Client", back_populates="life_events")
    asset_mappings = relationship("AssetGoalMapping", back_populates="life_event")
    allocated_asset = relationship("Asset", foreign_keys=[allocated_asset_id])

class AssetGoalMapping(Base):
    __tablename__ = "asset_goal_mappings"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"))
    life_event_id = Column(Integer, ForeignKey("life_events.id"))
    allocation_pct = Column(Float)
    
    asset = relationship("Asset", back_populates="goal_mappings")
    life_event = relationship("LifeEvent", back_populates="asset_mappings")

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
