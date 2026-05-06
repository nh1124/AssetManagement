from pydantic import BaseModel, Field
from uuid import UUID
from datetime import date, datetime
from datetime import date as DateType
from typing import Any, Optional, Literal

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
    parent_id: Optional[int] = None
    expected_return: float = 0.0  # Annual return rate %
    role: Literal["defense", "growth", "earmarked", "operating", "unassigned"] = "unassigned"
    role_target_amount: Optional[float] = None

class AccountCreate(AccountBase):
    pass

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    expected_return: Optional[float] = None
    role: Optional[Literal["defense", "growth", "earmarked", "operating", "unassigned"]] = None
    role_target_amount: Optional[float] = None
    is_active: Optional[bool] = None

class Account(AccountBase):
    id: int
    is_active: bool = True

    class Config:
        from_attributes = True

# Transaction Schemas
class TransactionBase(BaseModel):
    date: date
    description: Optional[str] = ''
    amount: float
    type: TransactionTypeLiteral
    category: Optional[str] = None
    currency: str = 'JPY'
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None

class TransactionCreate(TransactionBase):
    pass

class TransactionUpdate(BaseModel):
    date: Optional[DateType] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    type: Optional[TransactionTypeLiteral] = None
    category: Optional[str] = None
    currency: Optional[str] = None
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None

class Transaction(TransactionBase):
    id: int
    from_account_name: Optional[str] = None
    to_account_name: Optional[str] = None

    class Config:
        from_attributes = True


class ExchangeRateBase(BaseModel):
    base_currency: str
    quote_currency: str
    rate: float = Field(gt=0)
    as_of_date: DateType
    source: str = "manual"


class ExchangeRateCreate(ExchangeRateBase):
    pass


class ExchangeRateUpdate(BaseModel):
    base_currency: Optional[str] = None
    quote_currency: Optional[str] = None
    rate: Optional[float] = Field(default=None, gt=0)
    as_of_date: Optional[DateType] = None
    source: Optional[str] = None


class ExchangeRate(ExchangeRateBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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
    logical_balance: Optional[float] = None
    cfo_briefing: Optional[str] = None
    savings_rate: Optional[float] = None
    idle_money_rate: Optional[float] = None
    idle_money: Optional[float] = None
    idle_money_by_role: Optional[list[dict]] = None
    liquidity_coverage_ratio: Optional[float] = None
    runway_months: Optional[float] = None
    roadmap_progression: Optional[Literal["On Track", "At Risk", "Off Track"]] = None
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

# ========== Life Events ==========

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


class PeriodReviewBase(BaseModel):
    start_date: date
    end_date: date
    label: str = ""
    reflection: str = ""
    next_actions: str = ""


class PeriodReviewCreate(PeriodReviewBase):
    pass


class PeriodReview(PeriodReviewBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class LifeEventBase(BaseModel):
    name: str
    start_date: Optional[date] = None
    target_date: date
    target_amount: float
    priority: Literal[1, 2, 3] = 2
    note: Optional[str] = None

class LifeEventCreate(LifeEventBase):
    pass

class LifeEventUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    target_date: Optional[date] = None
    target_amount: Optional[float] = None
    priority: Optional[Literal[1, 2, 3]] = None
    note: Optional[str] = None

class LifeEvent(LifeEventBase):
    id: int
    created_at: Optional[datetime] = None

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
    life_event_id: Optional[int] = None
    date: date
    target_amount: float
    note: Optional[str] = None
    source: str = "manual"
    source_snapshot: Optional[dict[str, Any]] = None

class MilestoneCreate(MilestoneBase):
    pass

class MilestoneUpdate(BaseModel):
    note: Optional[str] = None
    target_amount: Optional[float] = None
    date: Optional[DateType] = None

class Milestone(MilestoneBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ========== Simulation Scenarios ==========

class SimulationScenarioBase(BaseModel):
    life_event_id: int
    name: str
    description: Optional[str] = None
    annual_return: float
    inflation: float
    monthly_savings: Optional[float] = None
    contribution_schedule: list[dict[str, Any]] = Field(default_factory=list)
    allocation_mode: Literal["weighted", "direct"] = "direct"


class SimulationScenarioCreate(SimulationScenarioBase):
    pass


class SimulationScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    annual_return: Optional[float] = None
    inflation: Optional[float] = None
    monthly_savings: Optional[float] = None
    contribution_schedule: Optional[list[dict[str, Any]]] = None
    allocation_mode: Optional[Literal["weighted", "direct"]] = None


class SimulationScenario(SimulationScenarioBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SimulationScenarioCompareRequest(BaseModel):
    life_event_id: int
    scenario_ids: list[int] = Field(min_length=2, max_length=2)


class SimulationScenarioCompareItem(BaseModel):
    scenario_id: int
    scenario_name: str
    target_amount: float
    years_remaining: float
    probability: float
    percentiles: MonteCarloPercentiles
    year_by_year: MonteCarloYearByYear
    deterministic_yearly: list[dict[str, Any]]

class CapsuleBase(BaseModel):
    name: str
    target_amount: float
    monthly_contribution: float
    current_balance: float = 0.0
    life_event_id: Optional[int] = None

class CapsuleCreate(CapsuleBase):
    pass

class CapsuleUpdate(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[float] = None
    monthly_contribution: Optional[float] = None
    current_balance: Optional[float] = None
    life_event_id: Optional[int] = None

class Capsule(CapsuleBase):
    id: int
    account_id: Optional[int] = None
    created_at: datetime
    holdings: list["CapsuleHolding"] = []

    class Config:
        from_attributes = True


class CapsuleRuleBase(BaseModel):
    capsule_id: int
    trigger_type: TransactionTypeLiteral
    trigger_category: Optional[str] = None
    trigger_description: Optional[str] = None
    source_mode: Literal["transaction_account", "fixed_account"] = "transaction_account"
    source_account_id: Optional[int] = None
    amount_type: Literal["fixed", "percentage"] = "fixed"
    amount_value: float = Field(ge=0)
    is_active: bool = True


class CapsuleRuleCreate(CapsuleRuleBase):
    pass


class CapsuleRuleUpdate(BaseModel):
    capsule_id: Optional[int] = None
    trigger_type: Optional[TransactionTypeLiteral] = None
    trigger_category: Optional[str] = None
    trigger_description: Optional[str] = None
    source_mode: Optional[Literal["transaction_account", "fixed_account"]] = None
    source_account_id: Optional[int] = None
    amount_type: Optional[Literal["fixed", "percentage"]] = None
    amount_value: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class CapsuleRule(CapsuleRuleBase):
    id: int
    capsule_name: Optional[str] = None
    source_account_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CapsuleHoldingBase(BaseModel):
    account_id: int
    held_amount: float = Field(ge=0)
    note: Optional[str] = None


class CapsuleHoldingCreate(CapsuleHoldingBase):
    pass


class CapsuleHoldingUpdate(BaseModel):
    held_amount: Optional[float] = Field(default=None, ge=0)
    note: Optional[str] = None


class CapsuleHolding(CapsuleHoldingBase):
    id: int
    capsule_id: int
    account_name: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ContributionScheduleItem(BaseModel):
    kind: Literal["monthly", "yearly", "one_time"] = "monthly"
    amount: float = Field(ge=0)
    month: Optional[int] = Field(default=None, ge=1, le=12)
    date: Optional[DateType] = None
    note: Optional[str] = None


class MilestoneSimulationRequest(BaseModel):
    basis: Literal["annual_plan", "deterministic", "p10", "p50", "p90"] = "p50"
    interval: Literal["annual", "semiannual", "quarterly", "target_only"] = "annual"
    mode: Literal["add", "replace"] = "replace"
    n_simulations: int = Field(default=1000, ge=100, le=10000)
    annual_return: Optional[float] = None
    inflation: Optional[float] = None
    monthly_savings: Optional[float] = None
    contribution_schedule: list[ContributionScheduleItem] = Field(default_factory=list)
    allocation_mode: Literal["weighted", "direct"] = "weighted"


class MilestoneSimulationPreview(BaseModel):
    life_event_id: int
    basis: str
    interval: str
    mode: str
    existing_count: int
    items: list[MilestoneCreate]
