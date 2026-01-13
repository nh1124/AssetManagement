from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, Text
from sqlalchemy.orm import relationship
import enum
from .database import Base

class TransactionType(str, enum.Enum):
    INCOME = "Income"
    EXPENSE = "Expense"
    TRANSFER = "Transfer"

class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String)  # Cash, Stock, etc.
    value = Column(Float)
    
    # Asset-Goal mappings
    goal_mappings = relationship("AssetGoalMapping", back_populates="asset")

class Liability(Base):
    __tablename__ = "liabilities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String)  # CreditCard, Loan, etc.
    lender = Column(String, nullable=True)
    total_borrowed = Column(Float, default=0)
    amount_repaid = Column(Float, default=0)
    balance = Column(Float)  # Remaining balance

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date)
    description = Column(String)
    amount = Column(Float)
    type = Column(String)  # INCOME, EXPENSE, TRANSFER
    category = Column(String, nullable=True)
    
    # Double-entry support
    source_account_id = Column(Integer, nullable=True)
    destination_account_id = Column(Integer, nullable=True)
    
    # Legacy fields (for backward compatibility)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)
    liability_id = Column(Integer, ForeignKey("liabilities.id"), nullable=True)

class LifeEvent(Base):
    __tablename__ = "life_events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    target_date = Column(Date)
    target_amount = Column(Float)
    
    # Goal mappings
    asset_mappings = relationship("AssetGoalMapping", back_populates="life_event")

class AssetGoalMapping(Base):
    """Maps assets to life events (buckets) with allocation percentage"""
    __tablename__ = "asset_goal_mappings"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"))
    life_event_id = Column(Integer, ForeignKey("life_events.id"))
    allocation_pct = Column(Float)  # 0-100
    
    asset = relationship("Asset", back_populates="goal_mappings")
    life_event = relationship("LifeEvent", back_populates="asset_mappings")

class Product(Base):
    """Product inventory for unit economics tracking"""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String)
    last_price = Column(Float)
    frequency_days = Column(Integer)  # How often purchased
    last_purchase_date = Column(Date, nullable=True)

class Budget(Base):
    """Budget categories with proposed vs actual spending"""
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, index=True)
    proposed_amount = Column(Float)
    current_spending = Column(Float, default=0)
    month = Column(String)  # YYYY-MM format
    ai_suggestion = Column(Text, nullable=True)
