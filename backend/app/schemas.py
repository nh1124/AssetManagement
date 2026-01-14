from pydantic import BaseModel
from datetime import date
from typing import Optional, Literal

# Account Schemas
class AccountBase(BaseModel):
    name: str
    account_type: str
    balance: float = 0

class AccountCreate(AccountBase):
    pass

class Account(AccountBase):
    id: int

    class Config:
        from_attributes = True

# Asset Schemas
class AssetBase(BaseModel):
    name: str
    category: str
    value: float

class AssetCreate(AssetBase):
    pass

class Asset(AssetBase):
    id: int

    class Config:
        from_attributes = True

# Liability Schemas
class LiabilityBase(BaseModel):
    name: str
    category: str
    lender: Optional[str] = None
    total_borrowed: float = 0
    amount_repaid: float = 0
    balance: float

class LiabilityCreate(LiabilityBase):
    pass

class Liability(LiabilityBase):
    id: int

    class Config:
        from_attributes = True

# Transaction Schemas
class TransactionBase(BaseModel):
    date: date
    description: str
    amount: float
    type: str
    category: Optional[str] = None
    currency: str = 'JPY'
    from_account: Optional[str] = None
    to_account: Optional[str] = None

class TransactionCreate(TransactionBase):
    pass

class Transaction(TransactionBase):
    id: int

    class Config:
        from_attributes = True

# Life Event Schemas
class LifeEventBase(BaseModel):
    name: str
    target_date: date
    target_amount: float
    funded_amount: float = 0
    priority: Literal['high', 'medium', 'low'] = 'medium'
    allocated_asset_id: Optional[int] = None
    monthly_contribution: float = 0

class LifeEventCreate(LifeEventBase):
    pass

class LifeEvent(LifeEventBase):
    id: int

    class Config:
        from_attributes = True

# Product Schemas
class ProductBase(BaseModel):
    name: str
    category: str
    location: Optional[str] = None
    last_unit_price: float
    frequency_days: int = 0
    last_purchase_date: Optional[date] = None
    is_asset: bool = False
    lifespan_months: Optional[int] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[date] = None

class ProductCreate(ProductBase):
    pass

class Product(ProductBase):
    id: int

    class Config:
        from_attributes = True

# Budget Schemas
class BudgetBase(BaseModel):
    category: str
    proposed_amount: float
    current_spending: float = 0
    month: str
    derived_from: Optional[str] = None

class BudgetCreate(BudgetBase):
    pass

class Budget(BudgetBase):
    id: int

    class Config:
        from_attributes = True

# Simulation Config
class SimulationConfigBase(BaseModel):
    annual_return: float = 5.0
    tax_rate: float = 20.0
    is_nisa: bool = True
    monthly_savings: float = 100000

class SimulationConfigCreate(SimulationConfigBase):
    pass

class SimulationConfig(SimulationConfigBase):
    id: int

    class Config:
        from_attributes = True

# Analysis Response
class AnalysisSummary(BaseModel):
    net_worth: float
    monthly_pl: float
    liability_total: float
    goal_probability: float
    total_goal_amount: float
    total_funded: float
    effective_cash: Optional[float] = None
    cfo_briefing: Optional[str] = None
