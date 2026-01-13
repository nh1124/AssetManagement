from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, Enum
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

class Liability(Base):
    __tablename__ = "liabilities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String)  # CreditCard, Loan, etc.
    balance = Column(Float)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date)
    description = Column(String)
    amount = Column(Float)
    type = Column(String)  # INCOME, EXPENSE, TRANSFER
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)
    liability_id = Column(Integer, ForeignKey("liabilities.id"), nullable=True)

class LifeEvent(Base):
    __tablename__ = "life_events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    target_date = Column(Date)
    target_amount = Column(Float)
