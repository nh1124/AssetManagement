from pydantic import BaseModel
from uuid import UUID
from datetime import date, datetime
from typing import Optional, Literal

TransactionTypeLiteral = Literal[
    'Income',
    'Expense',
    'Transfer',
    'LiabilityPayment',
    'Borrowing',
    'CreditExpense',
    'CreditAssetPurchase',
]

# Account Schemas
class AccountBase(BaseModel):
    name: str
    account_type: str
    balance: float = 0
    expected_return: float = 0.0  # Annual return rate %

class AccountCreate(AccountBase):
    pass

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    expected_return: Optional[float] = None
    is_active: Optional[bool] = None

class Account(AccountBase):
    id: int
    is_active: bool = True

    class Config:
        from_attributes = True

# Transaction Schemas
class TransactionBase(BaseModel):
    date: date
    description: str
    amount: float
    type: TransactionTypeLiteral
    category: Optional[str] = None
    currency: str = 'JPY'
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None

class TransactionCreate(TransactionBase):
    pass

class Transaction(TransactionBase):
    id: int
    from_account_name: Optional[str] = None
    to_account_name: Optional[str] = None

    class Config:
        from_attributes = True

# Product Schemas
class ProductBase(BaseModel):
    name: str
    category: str
    location: Optional[str] = None
    last_unit_price: float
    units_per_purchase: int = 1
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
    unit_cost: float = 0.0
    monthly_cost: float = 0.0
    next_purchase_date: Optional[str] = None

    class Config:
        from_attributes = True

# Simulation Config
class SimulationConfigBase(BaseModel):
    annual_return: float = 5.0
    tax_rate: float = 20.0
    is_nisa: bool = True
    monthly_savings: float = 100000
    volatility: float = 15.0
    inflation_rate: float = 2.0

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
    savings_rate: Optional[float] = None
    idle_money_rate: Optional[float] = None
    liquidity_coverage_ratio: Optional[float] = None
    runway_months: Optional[float] = None
    monthly_transaction_count: Optional[int] = None
    total_goal_count: Optional[int] = None
    budget_usage_rate: Optional[float] = None

# Recurring Transaction Schemas
class RecurringTransactionBase(BaseModel):
    name: str
    amount: float
    type: TransactionTypeLiteral
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


class MonthlyBudgetWithAccount(MonthlyBudget):
    account_name: str
    account_type: str
    actual_spending: float = 0.0
    variance: float = 0.0


class MonthlyReviewBase(BaseModel):
    target_period: str
    reflection: str = ""
    next_actions: str = ""


class MonthlyReviewCreate(MonthlyReviewBase):
    pass


class MonthlyReview(MonthlyReviewBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class LifeEventBase(BaseModel):
    name: str
    target_date: date
    target_amount: float
    priority: Literal[1, 2, 3] = 2
    note: Optional[str] = None

class LifeEventCreate(LifeEventBase):
    pass

class LifeEventUpdate(BaseModel):
    name: Optional[str] = None
    target_date: Optional[date] = None
    target_amount: Optional[float] = None
    priority: Optional[Literal[1, 2, 3]] = None
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


class MonteCarloPercentiles(BaseModel):
    p10: float
    p50: float
    p90: float


class MonteCarloYearByYear(BaseModel):
    p10: list[float]
    p50: list[float]
    p90: list[float]


class MonteCarloResult(BaseModel):
    life_event_id: int
    life_event_name: str
    target_amount: float
    years_remaining: float
    probability: float
    percentiles: MonteCarloPercentiles
    year_by_year: MonteCarloYearByYear
    n_simulations: int

# ========== Roadmap & Capsules ==========

class MilestoneBase(BaseModel):
    date: date
    target_amount: float
    note: Optional[str] = None

class MilestoneCreate(MilestoneBase):
    pass

class Milestone(MilestoneBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class CapsuleBase(BaseModel):
    name: str
    target_amount: float
    monthly_contribution: float
    current_balance: float = 0.0

class CapsuleCreate(CapsuleBase):
    pass

class CapsuleUpdate(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[float] = None
    monthly_contribution: Optional[float] = None
    current_balance: Optional[float] = None

class Capsule(CapsuleBase):
    id: int
    account_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True
