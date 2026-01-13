from pydantic import BaseModel, Field
from datetime import date
from typing import List, Optional
from enum import Enum

class AssetCategory(str, Enum):
    CASH = "Cash"
    STOCK = "Stock"
    CRYPTO = "Crypto"
    DURABLE = "Durable"

class Asset(BaseModel):
    id: str
    name: str
    category: AssetCategory
    value_jpy: float
    acquisition_date: date
    ticker: Optional[str] = None

class TransactionType(str, Enum):
    INCOME = "Income"
    EXPENSE = "Expense"
    TRANSFER = "Transfer"

class Transaction(BaseModel):
    id: str
    date: date
    amount: float
    category: str
    description: str
    type: TransactionType

class LifeGoal(BaseModel):
    id: str
    name: str
    target_amount: float
    target_date: date
    current_progress: float = 0.0
    priority: int = 1
