from pydantic import BaseModel
from datetime import date
from typing import Optional, List

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
    source_account_id: Optional[int] = None
    destination_account_id: Optional[int] = None
    asset_id: Optional[int] = None
    liability_id: Optional[int] = None

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

class LifeEventCreate(LifeEventBase):
    pass

class LifeEvent(LifeEventBase):
    id: int

    class Config:
        from_attributes = True

# Asset-Goal Mapping (Buckets)
class AssetGoalMappingBase(BaseModel):
    asset_id: int
    life_event_id: int
    allocation_pct: float

class AssetGoalMappingCreate(AssetGoalMappingBase):
    pass

class AssetGoalMapping(AssetGoalMappingBase):
    id: int

    class Config:
        from_attributes = True

# Product Schemas
class ProductBase(BaseModel):
    name: str
    category: str
    location: Optional[str] = None
    last_price: float
    frequency_days: int
    last_purchase_date: Optional[date] = None
    is_asset: bool = False
    lifespan_months: Optional[int] = None

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
    ai_suggestion: Optional[str] = None

class BudgetCreate(BudgetBase):
    pass

class Budget(BudgetBase):
    id: int

    class Config:
        from_attributes = True

# Simulation Config Schemas
class SimulationConfigBase(BaseModel):
    annual_return: float = 5.0
    monthly_savings: float = 100000
    tax_rate: float = 20.0
    is_nisa: bool = True

class SimulationConfigCreate(SimulationConfigBase):
    pass

class SimulationConfig(SimulationConfigBase):
    id: int

    class Config:
        from_attributes = True

# Analysis Schemas
class AnalysisSummary(BaseModel):
    net_worth: float
    monthly_pl: float
    liability_total: float
    effective_cash: Optional[float] = None
    cfo_briefing: Optional[str] = None

# Date Filter Schema
class DateRange(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
