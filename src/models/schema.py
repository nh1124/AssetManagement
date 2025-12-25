"""
Asset Management System - Database Schema
SQLAlchemy ORM models and Pydantic schemas based on DataModel.md
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class TaxType(str, Enum):
    """Tax classification for accounts"""
    TAXABLE = "TAXABLE"  # 特定口座・一般口座
    NISA = "NISA"  # NISA口座 (非課税)
    IDECO = "IDECO"  # 確定拠出年金
    CASH = "CASH"  # 現金 (原則非課税)


class TransactionType(str, Enum):
    """Transaction types"""
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    TRANSFER = "TRANSFER"
    BUY = "BUY"
    SELL = "SELL"
    DEPRECIATION = "DEPRECIATION"


class AssetStatus(str, Enum):
    """Asset lifecycle status"""
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    DISPOSED = "DISPOSED"


class Priority(str, Enum):
    """Goal priority levels"""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class CostUnit(str, Enum):
    """Standard cost unit types"""
    PER_DAY = "PER_DAY"
    PER_MONTH = "PER_MONTH"
    PER_YEAR = "PER_YEAR"


# =============================================================================
# SQLAlchemy Base
# =============================================================================

class Base(DeclarativeBase):
    """SQLAlchemy declarative base"""
    pass


# =============================================================================
# Master Data Models
# =============================================================================

class AssetClass(Base):
    """Asset classification (CASH, STOCK, DURABLE, CRYPTO)"""
    __tablename__ = "asset_class"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_depreciable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_market_linked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    positions: Mapped[List["AssetPosition"]] = relationship(back_populates="asset_class")


class Currency(Base):
    """Currency definitions"""
    __tablename__ = "currency"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(5), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=True)


class TransactionCategory(Base):
    """Transaction categories for expense classification"""
    __tablename__ = "transaction_category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_essential: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("transaction_category.id"), nullable=True
    )

    # Relationships
    parent: Mapped[Optional["TransactionCategory"]] = relationship(
        "TransactionCategory", remote_side=[id], backref="children"
    )
    transactions: Mapped[List["Transaction"]] = relationship(back_populates="category")


# =============================================================================
# Account & Holdings Models
# =============================================================================

class Account(Base):
    """Financial accounts (bank, brokerage, etc.)"""
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    institution: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tax_type: Mapped[str] = mapped_column(String(20), default=TaxType.TAXABLE.value)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    positions: Mapped[List["AssetPosition"]] = relationship(back_populates="account")


class AssetPosition(Base):
    """Unified asset model for all holdings (stocks, cash, durable goods)"""
    __tablename__ = "asset_position"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("account.id"), nullable=False)
    asset_class_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("asset_class.code"), nullable=False
    )
    ticker_symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    acquisition_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    lifespan_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salvage_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), default="JPY")
    status: Mapped[str] = mapped_column(String(20), default=AssetStatus.ACTIVE.value)
    origin_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("transaction.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    account: Mapped["Account"] = relationship(back_populates="positions")
    asset_class: Mapped["AssetClass"] = relationship(back_populates="positions")
    snapshots: Mapped[List["BalanceSnapshot"]] = relationship(back_populates="position")
    goal_allocations: Mapped[List["GoalAllocation"]] = relationship(back_populates="position")


# =============================================================================
# Time Series / Market Models
# =============================================================================

class MarketPrice(Base):
    """Historical market price data"""
    __tablename__ = "market_price"

    ticker_symbol: Mapped[str] = mapped_column(String(50), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), default="USD")


class ExchangeRate(Base):
    """Currency exchange rates"""
    __tablename__ = "exchange_rate"

    from_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    to_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)


# =============================================================================
# History / Snapshot Models
# =============================================================================

class Transaction(Base):
    """Transaction records for P/L and balance tracking"""
    __tablename__ = "transaction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_account_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("account.id"), nullable=True
    )
    to_account_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("account.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), default="JPY")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("transaction_category.id"), nullable=True
    )
    asset_position_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("asset_position.id"), nullable=True
    )
    is_logical_only: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    category: Mapped[Optional["TransactionCategory"]] = relationship(
        back_populates="transactions"
    )


class BalanceSnapshot(Base):
    """Point-in-time asset valuations"""
    __tablename__ = "balance_snapshot"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    position_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("asset_position.id"), primary_key=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price_raw: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    valuation_jpy: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cost_basis_jpy: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estimated_tax_jpy: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    # Relationships
    position: Mapped["AssetPosition"] = relationship(back_populates="snapshots")


# =============================================================================
# Strategy / Planning Models
# =============================================================================

class LifeGoal(Base):
    """Financial life goals (retirement, housing, etc.)"""
    __tablename__ = "life_goal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    priority: Mapped[str] = mapped_column(String(10), default=Priority.MEDIUM.value)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    allocations: Mapped[List["GoalAllocation"]] = relationship(back_populates="goal")


class GoalAllocation(Base):
    """Mapping assets to goals (virtual buckets)"""
    __tablename__ = "goal_allocation"

    goal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("life_goal.id"), primary_key=True
    )
    position_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("asset_position.id"), primary_key=True
    )
    allocation_ratio: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)

    # Relationships
    goal: Mapped["LifeGoal"] = relationship(back_populates="allocations")
    position: Mapped["AssetPosition"] = relationship(back_populates="goal_allocations")


class StandardCostParam(Base):
    """Micro-costing parameters for expense modeling"""
    __tablename__ = "standard_cost_param"

    category_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source_file: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


# =============================================================================
# Pydantic Schemas (for API/Validation)
# =============================================================================

class AssetClassSchema(BaseModel):
    """Pydantic schema for AssetClass"""
    code: str
    name: str
    is_depreciable: bool = False
    is_market_linked: bool = False

    class Config:
        from_attributes = True


class CurrencySchema(BaseModel):
    """Pydantic schema for Currency"""
    code: str
    symbol: str
    name: Optional[str] = None

    class Config:
        from_attributes = True


class AccountSchema(BaseModel):
    """Pydantic schema for Account"""
    id: Optional[int] = None
    name: str
    institution: Optional[str] = None
    tax_type: TaxType = TaxType.TAXABLE
    description: Optional[str] = None

    class Config:
        from_attributes = True


class AssetPositionSchema(BaseModel):
    """Pydantic schema for AssetPosition"""
    id: Optional[int] = None
    account_id: int
    asset_class_code: str
    ticker_symbol: str
    name: str
    quantity: Decimal
    acquisition_price: Decimal
    acquisition_date: date
    lifespan_days: Optional[int] = None
    salvage_value: Optional[Decimal] = None
    currency_code: str = "JPY"
    status: AssetStatus = AssetStatus.ACTIVE

    class Config:
        from_attributes = True


class TransactionSchema(BaseModel):
    """Pydantic schema for Transaction"""
    id: Optional[int] = None
    transaction_date: date
    type: TransactionType
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None
    amount: Decimal
    currency_code: str = "JPY"
    description: Optional[str] = None
    category_id: Optional[int] = None
    asset_position_id: Optional[int] = None
    is_logical_only: bool = False

    class Config:
        from_attributes = True


class LifeGoalSchema(BaseModel):
    """Pydantic schema for LifeGoal"""
    id: Optional[int] = None
    name: str
    target_amount: Decimal
    target_date: date
    priority: Priority = Priority.MEDIUM
    description: Optional[str] = None

    class Config:
        from_attributes = True


class StandardCostParamSchema(BaseModel):
    """Pydantic schema for StandardCostParam"""
    category_key: str
    unit_cost: Decimal
    unit: CostUnit
    description: Optional[str] = None
    source_file: Optional[str] = None

    class Config:
        from_attributes = True
