from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
import enum
from .database import Base

class TransactionType(str, enum.Enum):
    INCOME = "Income"
    EXPENSE = "Expense"
    TRANSFER = "Transfer"

class Priority(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String)
    value = Column(Float)
    
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

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date)
    description = Column(String)
    amount = Column(Float)
    type = Column(String)
    category = Column(String, nullable=True)
    currency = Column(String, default='JPY')
    from_account = Column(String, nullable=True)
    to_account = Column(String, nullable=True)
    
    # Legacy fields
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)
    liability_id = Column(Integer, ForeignKey("liabilities.id"), nullable=True)

class LifeEvent(Base):
    __tablename__ = "life_events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    target_date = Column(Date)
    target_amount = Column(Float)
    funded_amount = Column(Float, default=0)
    priority = Column(String, default="medium")
    allocated_asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)
    
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
    name = Column(String, index=True)
    category = Column(String)
    location = Column(String, nullable=True)
    last_unit_price = Column(Float)
    frequency_days = Column(Integer, default=0)
    last_purchase_date = Column(Date, nullable=True)
    is_asset = Column(Boolean, default=False)
    lifespan_months = Column(Integer, nullable=True)

class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, index=True)
    proposed_amount = Column(Float)
    current_spending = Column(Float, default=0)
    month = Column(String)
    derived_from = Column(String, nullable=True)

class SimulationConfig(Base):
    __tablename__ = "simulation_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, default=1)
    annual_return = Column(Float, default=5.0)
    tax_rate = Column(Float, default=20.0)
    is_nisa = Column(Boolean, default=True)

class Settings(Base):
    """User settings including API keys"""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, default=1)
    gemini_api_key = Column(String, nullable=True)
    default_currency = Column(String, default='JPY')
    language = Column(String, default='ja')
