from pydantic import BaseModel
from uuid import UUID
from datetime import date, datetime
from typing import Optional, Literal

# Account Schemas
class AccountBase(BaseModel):
    name: str
    account_type: str
    balance: float = 0
    budget_limit: Optional[float] = None
    expected_return: float = 0.0  # Annual return rate %

class AccountCreate(AccountBase):
    pass

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    budget_limit: Optional[float] = None
    expected_return: Optional[float] = None
    is_active: Optional[bool] = None

class Account(AccountBase):
    id: int
    is_active: bool = True

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

# Recurring Transaction Schemas
class RecurringTransactionBase(BaseModel):
    name: str
    amount: float
    type: Literal['Income', 'Expense', 'Transfer', 'Debt']
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None
    frequency: Literal['Monthly', 'Yearly']
    day_of_month: int = 1
    month_of_year: Optional[int] = None  # Used for Yearly frequency
    next_due_date: Optional[date] = None  # Calculated by system
    is_active: bool = True

class RecurringTransactionCreate(RecurringTransactionBase):
    pass

class RecurringTransaction(RecurringTransactionBase):
    id: int

    class Config:
        from_attributes = True

# ========== Life Events & Allocations ==========

class GoalAllocationBase(BaseModel):
    account_id: int
    allocation_percentage: float  # 0.0 - 100.0

class GoalAllocationCreate(GoalAllocationBase):
    pass

class GoalAllocation(GoalAllocationBase):
    id: int
    life_event_id: int
    account_name: Optional[str] = None  # Populated when returning
    account_balance: Optional[float] = None

    class Config:
        from_attributes = True

class MonthlyBudgetBase(BaseModel):
    account_id: int
    target_period: str  # "YYYY-MM"
    amount: float

class MonthlyBudgetCreate(MonthlyBudgetBase):
    pass

class MonthlyBudget(MonthlyBudgetBase):
    id: UUID

    class Config:
        from_attributes = True

class LifeEventBase(BaseModel):
    name: str
    target_date: date
    target_amount: float
    priority: int = 2  # 1=High, 2=Medium, 3=Low
    note: Optional[str] = None

class LifeEventCreate(LifeEventBase):
    pass

class LifeEventUpdate(BaseModel):
    name: Optional[str] = None
    target_date: Optional[date] = None
    target_amount: Optional[float] = None
    priority: Optional[int] = None
    note: Optional[str] = None

class LifeEvent(LifeEventBase):
    id: int
    created_at: Optional[datetime] = None
    allocations: list[GoalAllocation] = []

    class Config:
        from_attributes = True

# ========== Strategy Dashboard ==========

class LifeEventWithProgress(LifeEvent):
    """Extended LifeEvent with calculated progress fields."""
    current_funded: float = 0.0
    projected_amount: float = 0.0
    gap: float = 0.0
    status: str = "Not Started"  # "On Track", "At Risk", "Off Track"
    progress_percentage: float = 0.0
    years_remaining: float = 0.0

class StrategyDashboard(BaseModel):
    events: list[LifeEventWithProgress]
    unallocated_assets: list[dict]
    total_allocated: float
    total_unallocated: float
    simulation_params: dict
