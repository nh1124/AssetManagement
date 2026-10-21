from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from datetime import date, datetime
from datetime import date as DateType
from typing import Any, List, Optional, Literal
from .domain.money import Money

# What a capsule rule's trigger describes, as a statement about an entry's
# legs: Income is a credit leg on an income account, Expense a debit leg on an
# expense account funded from an asset, CreditExpense the same funded from a
# liability, Transfer asset to asset. See capsule_service._TRIGGER_LEGS.
CapsuleTriggerLiteral = Literal['Income', 'Expense', 'CreditExpense', 'Transfer']
ProductBudgetTreatmentLiteral = Literal["auto", "expense_only", "reserve_allocation", "asset_replacement"]
MonthlyPlanCashTreatmentLiteral = Literal["auto", "cash", "non_cash"]
LiabilityPaymentPolicyLiteral = Literal["full", "minimum", "fixed", "installment", "revolving"]
AiOperationRiskLiteral = Literal["low", "medium", "high", "critical"]
AiOperationModeLiteral = Literal["deny", "allow_read", "require_approval", "allow_execute"]
AiOperationDecisionLiteral = Literal["allowed", "denied", "approval_required", "applied", "failed"]
AiOperationSourceLiteral = Literal["frontend", "mcp_http", "mcp_stdio", "backend"]
AiChangeRequestStatusLiteral = Literal["draft", "pending", "approved", "applied", "rejected", "expired", "failed"]
AiDataClassificationLiteral = Literal["normal", "sensitive", "secret"]
AiMcpWriteModeLiteral = Literal["direct_write", "change_request"]

AccountTypeLiteral = Literal["asset", "liability", "income", "expense"]

# Account Schemas
class AccountBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    account_type: AccountTypeLiteral
    balance: float = 0
    is_active: bool = True
    liability_closing_day: Optional[int] = Field(default=None, ge=1, le=31)
    liability_payment_day: Optional[int] = Field(default=None, ge=1, le=31)
    liability_payment_month_offset: int = Field(default=0, ge=0, le=24)
    liability_payment_policy: LiabilityPaymentPolicyLiteral = "full"
    liability_minimum_payment: Optional[float] = Field(default=None, ge=0)
    liability_fixed_payment_amount: Optional[float] = Field(default=None, ge=0)
    liability_installment_months: Optional[int] = Field(default=None, ge=1, le=120)
    liability_revolving_rate: Optional[float] = Field(default=None, ge=0)

class AccountCreate(AccountBase):
    pass

class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    liability_closing_day: Optional[int] = Field(default=None, ge=1, le=31)
    liability_payment_day: Optional[int] = Field(default=None, ge=1, le=31)
    liability_payment_month_offset: Optional[int] = Field(default=None, ge=0, le=24)
    liability_payment_policy: Optional[LiabilityPaymentPolicyLiteral] = None
    liability_minimum_payment: Optional[float] = Field(default=None, ge=0)
    liability_fixed_payment_amount: Optional[float] = Field(default=None, ge=0)
    liability_installment_months: Optional[int] = Field(default=None, ge=1, le=120)
    liability_revolving_rate: Optional[float] = Field(default=None, ge=0)
    is_active: Optional[bool] = None

class Account(AccountBase):
    id: int
    is_active: bool = True

    class Config:
        from_attributes = True


class AiOperationPolicyBase(BaseModel):
    ai_client_id: Optional[int] = None
    resource: str
    action: str
    risk: AiOperationRiskLiteral
    mode: AiOperationModeLiteral
    threshold_amount: Optional[float] = None
    threshold_count: Optional[int] = None
    require_mfa: bool = False


class AiOperationPolicyCreate(AiOperationPolicyBase):
    pass


class AiOperationPolicy(AiOperationPolicyBase):
    id: int
    client_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AiAuditLog(BaseModel):
    id: int
    client_id: int
    actor_client_id: Optional[int] = None
    ai_client_id: Optional[int] = None
    mcp_client_id: Optional[str] = None
    source: AiOperationSourceLiteral
    tool_name: Optional[str] = None
    resource: str
    action: str
    risk: AiOperationRiskLiteral
    decision: AiOperationDecisionLiteral
    request_summary: dict[str, Any] = Field(default_factory=dict)
    diff_summary: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    approval_request_id: Optional[int] = None
    mfa_verified: bool = False
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AiOperationEvaluateRequest(BaseModel):
    source: AiOperationSourceLiteral = "backend"
    tool_name: Optional[str] = None
    resource: str
    action: str
    risk: AiOperationRiskLiteral = "low"
    ai_client_id: Optional[int] = None
    mcp_client_id: Optional[str] = None
    request_summary: dict[str, Any] = Field(default_factory=dict)
    diff_summary: dict[str, Any] = Field(default_factory=dict)
    mfa_verified: bool = False
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AiOperationEvaluateResponse(BaseModel):
    decision: str
    mode: AiOperationModeLiteral
    resource: str
    action: str
    risk: AiOperationRiskLiteral
    require_mfa: bool = False
    reason: str


class AiExecutionSettings(BaseModel):
    mcp_write_mode: AiMcpWriteModeLiteral = "direct_write"
    supported_change_request_operations: list[str] = Field(default_factory=list)


class AiContextResourceDescriptor(BaseModel):
    resource: str
    title: str
    description: str
    classification: AiDataClassificationLiteral
    available: bool
    risk: AiOperationRiskLiteral
    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    default_limit: Optional[int] = None


class AiContextResponse(BaseModel):
    resource: str
    classification: AiDataClassificationLiteral
    generated_at: datetime
    data: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AiChangeRequestBase(BaseModel):
    source: AiOperationSourceLiteral = "backend"
    tool_name: Optional[str] = None
    resource: str
    action: str
    risk: AiOperationRiskLiteral = "medium"
    ai_client_id: Optional[int] = None
    mcp_client_id: Optional[str] = None
    target_ref: dict[str, Any] = Field(default_factory=dict)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    expires_at: Optional[datetime] = None
    mfa_verified: bool = False


class AiChangeRequestPreviewRequest(AiChangeRequestBase):
    pass


class AiChangeRequestCreate(AiChangeRequestBase):
    status: Literal["draft", "pending"] = "pending"


class AiChangeRequestActionRequest(BaseModel):
    step_up_token: Optional[str] = None


class AiChangeRequestPreview(BaseModel):
    resource: str
    action: str
    risk: AiOperationRiskLiteral
    target_ref: dict[str, Any] = Field(default_factory=dict)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)
    diff: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    precondition_hash: Optional[str] = None
    requires_mfa: bool = False


class AiChangeRequest(AiChangeRequestPreview):
    id: int
    client_id: int
    created_by_client_id: Optional[int] = None
    ai_client_id: Optional[int] = None
    mcp_client_id: Optional[str] = None
    source: AiOperationSourceLiteral
    tool_name: Optional[str] = None
    status: AiChangeRequestStatusLiteral
    idempotency_key: str
    approved_by_client_id: Optional[int] = None
    approved_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Transaction Schemas
class TransactionBase(BaseModel):
    date: date
    description: Optional[str] = ''
    amount: float
    currency: str | None = None
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None
    batch_id: Optional[int] = None

class TransactionLeg(BaseModel):
    """One side of an entry. Exactly one of debit or credit is above zero."""

    account_id: int
    debit: float = 0.0
    credit: float = 0.0
    memo: Optional[str] = None
    capsule_id: Optional[int] = None


class TransactionCreate(TransactionBase):
    # Given legs, the transaction is a compound entry and from/to are derived
    # from them. Left out, from_account_id and to_account_id describe the two
    # legs as they always have.
    legs: Optional[List[TransactionLeg]] = None

class TransactionUpdate(BaseModel):
    legs: Optional[List[TransactionLeg]] = None
    date: Optional[DateType] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None
    batch_id: Optional[int] = None

class TransactionLegRead(TransactionLeg):
    id: int
    account_name: Optional[str] = None
    account_type: Optional[str] = None


class TransactionDepreciation(BaseModel):
    """The write-down an entry carries, so the ledger opens it as a depreciation."""
    id: int
    product_id: int
    product_name: Optional[str] = None
    period: str


class DepreciationRecord(BaseModel):
    """A write-down recorded by hand; left out, the amount and date follow the schedule."""
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    date: Optional[DateType] = None
    expense_account_id: int | None = Field(default=None, gt=0)
    asset_account_id: int | None = Field(default=None, gt=0)


PlanRecordSection = Literal["allocation", "drawdown", "expense", "income", "debt_payment", "borrowing"]


class PlanRecordAutomatic(BaseModel):
    """自動扱い (WP27): the record becomes an automatic transaction from start_period, every month or year,
    until end_period (open when null). counter_account_id is the other side (where it is paid from, where
    it arrives); records_transactions also posts it on its day, otherwise it only budgets."""
    model_config = ConfigDict(extra="forbid")
    frequency: Literal["Monthly", "Yearly"] = "Monthly"
    day_of_month: int = Field(default=1, ge=1, le=31)
    start_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    end_period: Optional[str] = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    counter_account_id: int | None = Field(default=None, gt=0)
    records_transactions: bool = False


class PlanRecordCreate(BaseModel):
    """A user's record in an account's month on the plan page (WP19); several per section, one per name (WP27)."""
    model_config = ConfigDict(extra="forbid")
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    account_id: int = Field(gt=0)
    section: PlanRecordSection
    amount: float = Field(ge=0, allow_inf_nan=False)
    name: Optional[str] = Field(default=None, max_length=200)
    automatic: PlanRecordAutomatic | None = None


class PlanRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float = Field(ge=0, allow_inf_nan=False)
    name: Optional[str] = Field(default=None, max_length=200)


class DepreciationAmend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float = Field(gt=0, allow_inf_nan=False)
    date: Optional[DateType] = None
    expense_account_id: int | None = Field(default=None, gt=0)


class Transaction(TransactionBase):
    id: int
    depreciation: Optional[TransactionDepreciation] = None
    from_account_name: Optional[str] = None
    to_account_name: Optional[str] = None
    legs: Optional[List[TransactionLegRead]] = None
    # Set when the list was filtered by account: the amount this transaction
    # moved on that account, which for a compound entry is not its total.
    matched_debit: Optional[float] = None
    matched_credit: Optional[float] = None

    class Config:
        from_attributes = True


class TransactionProposal(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def major_legs(cls, value):
        # Proposal JSON belongs to the integer ledger; only its response is major units.
        if hasattr(value, "amount_minor"):
            data = {name: getattr(value, name) for name in cls.model_fields}
            data["legs"] = [{
                **leg,
                "debit": Money(leg["debit"], value.currency).to_float(),
                "credit": Money(leg["credit"], value.currency).to_float(),
            } for leg in value.legs]
            return data
        return value

    id: int
    client_id: int
    origin: str
    origin_ref: dict[str, Any]
    date: DateType
    description: str
    amount: float
    currency: str
    legs: list[TransactionLeg]
    trigger_transaction_id: Optional[int] = None
    status: str
    posted_transaction_id: Optional[int] = None
    idempotency_key: str
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    decided_by_client_id: Optional[int] = None


class TransactionProposalDecision(BaseModel):
    note: Optional[str] = None


class TransactionBatchCreate(BaseModel):
    label: Optional[str] = None
    source: str = "quick"
    input_payload: dict[str, Any] = Field(default_factory=dict)
    transactions: list[TransactionCreate]


class TransactionBatch(BaseModel):
    id: int
    label: Optional[str] = None
    source: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    transactions: list[Transaction] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ExchangeRateBase(BaseModel):
    base_currency: str
    quote_currency: str
    rate: float = Field(gt=0)
    as_of_date: DateType
    source: str = "manual"


class ExchangeRate(ExchangeRateBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Product Schemas
DepreciationMethodLiteral = Literal["none", "straight_line", "declining_balance"]
DepreciationIntervalLiteral = Literal["monthly", "yearly"]


class ProductBase(BaseModel):
    name: str
    category: str = "Uncategorized"
    location: Optional[str] = None
    last_unit_price: float
    units_per_purchase: int = 1
    frequency_days: int = 0
    last_purchase_date: Optional[date] = None
    is_asset: bool = False
    lifespan_months: Optional[int] = None
    budget_account_id: Optional[int] = None
    funding_capsule_id: Optional[int] = None
    budget_treatment: ProductBudgetTreatmentLiteral = "auto"
    purchase_price: Optional[float] = None
    purchase_date: Optional[date] = None
    auto_depreciation: bool = False
    depreciation_method: DepreciationMethodLiteral = "none"
    depreciation_annual_rate: Optional[float] = Field(default=None, ge=0, le=100)
    depreciation_interval: DepreciationIntervalLiteral = "monthly"
    depreciation_start_date: Optional[date] = None
    depreciation_expense_account_id: Optional[int] = None
    depreciation_asset_account_id: Optional[int] = None

class ProductCreate(ProductBase):
    model_config = ConfigDict(extra="forbid")


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    last_unit_price: Optional[float] = None
    units_per_purchase: Optional[int] = None
    frequency_days: Optional[int] = None
    last_purchase_date: Optional[date] = None
    is_asset: Optional[bool] = None
    lifespan_months: Optional[int] = None
    budget_account_id: Optional[int] = None
    funding_capsule_id: Optional[int] = None
    budget_treatment: Optional[ProductBudgetTreatmentLiteral] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[date] = None
    auto_depreciation: bool = False
    depreciation_method: Optional[DepreciationMethodLiteral] = None
    depreciation_annual_rate: Optional[float] = Field(default=None, ge=0, le=100)
    depreciation_interval: Optional[DepreciationIntervalLiteral] = None
    depreciation_start_date: Optional[date] = None
    depreciation_expense_account_id: Optional[int] = None
    depreciation_asset_account_id: Optional[int] = None

    model_config = ConfigDict(extra="forbid")

class Product(ProductBase):
    id: int
    unit_cost: float = 0.0
    monthly_cost: float = 0.0
    next_purchase_date: Optional[str] = None
    budget_account_name: Optional[str] = None
    funding_capsule_name: Optional[str] = None
    effective_budget_treatment: str = "expense_only"
    reserve_target_amount: float = 0.0
    recommended_monthly_reserve: float = 0.0

    class Config:
        from_attributes = True


class RegistryEntryBase(BaseModel):
    name: str = Field(min_length=1)
    kind: Literal["income", "expense", "debt", "transfer"] = "expense"
    amount: float = Field(default=0, ge=0, allow_inf_nan=False)
    currency: str | None = None
    source_account_id: int | None = None
    destination_account_id: int | None = None
    budget_account_id: int | None = None
    repeat_mode: Literal["once", "count", "indefinite"] = "indefinite"
    frequency: Literal["Monthly", "Yearly", "EveryNDays"] | None = None
    frequency_days: int | None = Field(default=None, ge=1)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    month_of_year: int | None = Field(default=None, ge=1, le=12)
    start_date: date
    end_date: date | None = None
    repeat_count: int | None = Field(default=None, ge=1, le=100000)
    budget_active: bool = True
    is_active: bool = True
    # 取引も記録する: false for one that only budgets each month and never posts (WP27).
    records_transactions: bool = True
    note: str | None = None


class RegistryEntryCreate(RegistryEntryBase):
    model_config = ConfigDict(extra="forbid")


class RegistryEntry(RegistryEntryBase):
    id: int
    next_due_date: date | None = None
    budget_account_name: str | None = None
    source_account_name: str | None = None
    destination_account_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


# Simulation Config
class SimulationConfigBase(BaseModel):
    horizon_years: int = Field(default=30, ge=1, le=60)
    annual_return: float = 5.0
    tax_rate: float = 20.0
    is_nisa: bool = True
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
    liquidity_coverage_ratio: Optional[float] = None
    runway_months: Optional[float] = None
    roadmap_progression: Optional[Literal["On Track", "At Risk", "Off Track"]] = None
    monthly_transaction_count: Optional[int] = None
    total_goal_count: Optional[int] = None
    budget_usage_rate: Optional[float] = None

# ========== Life Events ==========

MonthlyPlanLineType = Literal[
    "income",
    "expense",
    "allocation",
    "debt_payment",
    "borrowing",
    "drawdown",
]

MonthlyPlanTargetType = Literal[
    "account",
    "capsule",
    "product",
    "manual",
]


class MonthlyPlanLineBase(BaseModel):
    target_period: str
    line_type: MonthlyPlanLineType
    target_type: MonthlyPlanTargetType = "manual"
    target_id: Optional[int] = None
    account_id: Optional[int] = None
    source_account_id: Optional[int] = None
    name: Optional[str] = None
    amount: float = 0.0
    source: str = "manual"
    source_kind: str = "manual"
    identity_key: str = ""
    manual_override: bool = False
    cash_treatment: MonthlyPlanCashTreatmentLiteral = "auto"
    is_active: bool = True


class MonthlyPlanLineCreate(MonthlyPlanLineBase):
    model_config = ConfigDict(extra="forbid")


class MonthlyPlanLineBatchUpdate(MonthlyPlanLineBase):
    model_config = ConfigDict(extra="forbid")

    id: int


class MonthlyPlanLineUpdate(BaseModel):
    target_period: Optional[str] = None
    line_type: Optional[MonthlyPlanLineType] = None
    target_type: Optional[MonthlyPlanTargetType] = None
    target_id: Optional[int] = None
    account_id: Optional[int] = None
    source_account_id: Optional[int] = None
    name: Optional[str] = None
    amount: Optional[float] = None
    source: Optional[str] = None
    source_kind: Optional[str] = None
    identity_key: Optional[str] = None
    manual_override: Optional[bool] = None
    cash_treatment: Optional[MonthlyPlanCashTreatmentLiteral] = None
    is_active: Optional[bool] = None


class MonthlyPlanLine(MonthlyPlanLineBase):
    id: int
    plan_id: Optional[int] = None
    target_name: Optional[str] = None
    account_name: Optional[str] = None
    actual: float = 0.0
    variance: float = 0.0
    recurring_amount: float = 0.0
    suggested_amount: float = 0.0
    suggested_source: Optional[str] = None
    suggested_items: Optional[list[dict[str, Any]]] = None
    suggested_status: Optional[str] = None
    registry_amount: Optional[float] = None
    registry_entry_ids: Optional[list[int]] = None
    registry_items: Optional[list[dict[str, Any]]] = None
    sync_status: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== Budget Plans ==========

class CopyPeriodRequest(BaseModel):
    source_period: str
    target_period: str


# ========== Monthly Reviews ==========

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


class LifeEventLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_event_id: int
    to_event_id: int
    kind: Literal["after"]

    @field_validator("kind", mode="before")
    @classmethod
    def validate_kind(cls, value):
        if value != "after":
            raise ValueError("接続は「必ず続く」のみです。")
        return value

    offset_months: int = 0
    note: str | None = None


class LifeEventLink(LifeEventLinkCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    created_at: datetime | None = None


LifeEventKind = Literal["expense", "income", "borrowing", "repayment"]


class LifeEventBase(BaseModel):
    """target_amount is the amount; for a repayment, the monthly payment."""
    direction: LifeEventKind = "expense"
    condition_mode: Literal["all", "any"] = "all"
    name: str
    target_date: date
    target_amount: float
    priority: Literal[1, 2, 3] = 2
    note: Optional[str] = None
    interest_rate: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    borrowing_event_id: Optional[int] = None
    repeat_count: Optional[int] = Field(default=None, ge=1, le=1200)

class LifeEventCreate(LifeEventBase):
    model_config = ConfigDict(extra="forbid")
    scenario_id: int

class LifeEventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Optional[LifeEventKind] = None
    condition_mode: Optional[Literal["all", "any"]] = None
    name: Optional[str] = None
    target_date: Optional[date] = None
    target_amount: Optional[float] = None
    priority: Optional[Literal[1, 2, 3]] = None
    note: Optional[str] = None
    interest_rate: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    borrowing_event_id: Optional[int] = None
    repeat_count: Optional[int] = Field(default=None, ge=1, le=1200)

class LifeEvent(LifeEventBase):
    id: int
    scenario_id: int
    lineage: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class CapsuleBase(BaseModel):
    auto_post: bool = False
    name: str
    target_amount: float
    monthly_contribution: float
    capsule_type: str = "manual"
    target_amount_source: str = "manual"
    monthly_contribution_source: str = "manual"

class CapsuleCreate(CapsuleBase):
    # Compatibility shorthand: one funding source for the capsule's whole target.
    account_id: Optional[int] = None

class CapsuleUpdate(BaseModel):
    auto_post: bool = False
    name: Optional[str] = None
    target_amount: Optional[float] = None
    monthly_contribution: Optional[float] = None
    capsule_type: Optional[str] = None
    target_amount_source: Optional[str] = None
    monthly_contribution_source: Optional[str] = None

class CapsuleFundingSourceInput(BaseModel):
    account_id: int = Field(gt=0)
    target_amount: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    max_share_bp: Optional[int] = Field(default=None, ge=0, le=10000, strict=True)
    sort_order: int = 0

    class Config:
        extra = "forbid"


class CapsuleFundingSource(CapsuleFundingSourceInput):
    id: int
    client_id: int
    capsule_id: int
    # Supplied by capsule_to_dict so the plan can be shown without a second
    # request; absent when the row is serialized straight from the ORM.
    account_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Capsule(CapsuleBase):
    id: int
    # Computed journal claim, never a stored balance.
    current_balance: float = 0.0
    recommended_monthly_contribution: float = 0.0
    linked_products: list[dict[str, Any]] = []
    created_at: datetime
    funding_sources: list[CapsuleFundingSource] = Field(default_factory=list)
    # The earmark made for a goal event; is_goal when that event is in the current goal.
    goal_event_id: Optional[int] = None
    is_goal: bool = False

    class Config:
        from_attributes = True


class CapsuleAccountClaimRequest(BaseModel):
    account_id: int
    target_amount: float = Field(allow_inf_nan=False)

    class Config:
        extra = "forbid"


class CapsuleDrawdownRequest(BaseModel):
    amount: float = Field(gt=0, allow_inf_nan=False)
    from_account_id: int
    to_account_id: int
    kind: Literal["as_intended", "diverted"]
    date: date
    description: str
    note: Optional[str] = None

    class Config:
        extra = "forbid"


class CapsuleDrawdown(BaseModel):
    id: int
    client_id: int
    capsule_id: int
    transaction_id: int
    kind: Literal["as_intended", "diverted"]
    amount_minor: int
    amount: float
    currency: str
    date: date
    description: str
    note: Optional[str] = None
    created_at: datetime


class CapsuleDrawdownResult(BaseModel):
    transaction: Transaction
    drawdown: CapsuleDrawdown


class CapsuleRuleBase(BaseModel):
    capsule_id: int
    trigger_type: CapsuleTriggerLiteral
    trigger_category: Optional[str] = None
    trigger_description: Optional[str] = None
    trigger_account_id: Optional[int] = None
    source_mode: Literal["transaction_account", "fixed_account"] = "transaction_account"
    source_account_id: Optional[int] = None
    destination_account_id: Optional[int] = None
    amount_type: Literal["fixed", "percentage"] = "fixed"
    amount_value: float = Field(ge=0)
    is_active: bool = True


class CapsuleRuleCreate(CapsuleRuleBase):
    pass


class CapsuleRuleUpdate(BaseModel):
    capsule_id: Optional[int] = None
    trigger_type: Optional[CapsuleTriggerLiteral] = None
    trigger_category: Optional[str] = None
    trigger_description: Optional[str] = None
    trigger_account_id: Optional[int] = None
    source_mode: Optional[Literal["transaction_account", "fixed_account"]] = None
    source_account_id: Optional[int] = None
    destination_account_id: Optional[int] = None
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


class ReconciliationAccount(BaseModel):
    id: int
    name: str
    account_type: AccountTypeLiteral


class ReconciliationClaim(BaseModel):
    capsule_id: int
    capsule_name: str
    claimed_minor: int


class ReconciliationComparison(BaseModel):
    account: ReconciliationAccount
    as_of: DateType
    ledger_minor: int
    statement_minor: int
    difference_minor: int
    currency: str
    capsule_claims: list[ReconciliationClaim]


class ReconciliationAdjustment(BaseModel):
    as_of: DateType
    statement: Decimal = Field(allow_inf_nan=False)
    counter_account_id: int
    capsule_id: int | None = None
    note: str | None = None
    currency: str | None = None
    expected_ledger_minor: int | None = None


class HouseholdMemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    relation: str | None = None
    birth_date: date


class HouseholdMemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1)
    relation: str | None = None
    birth_date: date | None = None


class HouseholdMember(HouseholdMemberCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: int
    created_at: datetime | None = None


class LifeEventConditionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal["net_worth", "free_cash", "account_balance", "capsule_claim", "goal_progress", "member_age", "date_reached"]
    comparator: Literal["gte", "lte", "eq"] = "gte"
    threshold_minor: int | None = Field(default=None, strict=True, ge=-(2**63), le=2**63 - 1)
    threshold_number: float | None = Field(default=None, allow_inf_nan=False)
    threshold_date: date | None = None
    reference_id: int | None = Field(default=None, gt=0)
    note: str | None = None

    @model_validator(mode="after")
    def check_shape(self):
        money = self.metric in {"net_worth", "free_cash", "account_balance", "capsule_claim"}
        numeric = self.metric in {"goal_progress", "member_age"}
        if (self.threshold_minor is not None) != money or (self.threshold_number is not None) != numeric or (self.threshold_date is not None) != (self.metric == "date_reached"):
            raise ValueError("指標に合う条件値を一つ指定してください。")
        referenced = self.metric in {"account_balance", "capsule_claim", "goal_progress", "member_age"}
        if (self.reference_id is not None) != referenced:
            raise ValueError("指標に合う対象を指定してください。")
        return self


class LifeEventCondition(LifeEventConditionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: int
    life_event_id: int
    created_at: datetime | None = None


class LifeScenarioName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str

    @model_validator(mode="before")
    @classmethod
    def validate_name(cls, values):
        if isinstance(values, dict) and (not isinstance(values.get("name"), str) or not values["name"].strip()):
            raise ValueError("シナリオ名を入力してください。")
        return values


class LifeScenarioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    annual_return: float | None = None
    inflation: float | None = None
    horizon_years: int | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_assumptions(cls, values):
        import math
        if not isinstance(values, dict):
            return values
        if "name" in values and (not isinstance(values["name"], str) or not values["name"].strip()):
            raise ValueError("シナリオ名を入力してください。")
        for field in ("annual_return", "inflation"):
            if field in values and (type(values[field]) not in (int, float) or not math.isfinite(values[field])):
                raise ValueError("利率は有限の数値で指定してください。")
        if "horizon_years" in values and (type(values["horizon_years"]) is not int or not 1 <= values["horizon_years"] <= 60):
            raise ValueError("試算期間は1〜60年で指定してください。")
        return values


class GoalChange(BaseModel):
    """What happens to the old goal's earmarks when another scenario becomes the goal (R11)."""
    model_config = ConfigDict(extra="forbid")
    earmarks: Literal["keep", "replace", "carry"] = "keep"


class ContributionPlanInput(BaseModel):
    """A 積立設定 record (WP23); fields left out keep their value on update.

    kind: contribution (積立 into account_id), transfer (口座振替 from account_id to to_account_id)
    or withdrawal (ライフイベントへの取り崩し from account_id toward life_event_id). amount is what
    moves each time. Once when interval_months is null, else every interval_months months
    from start_period, repeat_count times or until end_period. on_shortage (transfer, withdrawal):
    skip or partial when the account holds less.
    """
    model_config = ConfigDict(extra="forbid")
    kind: Literal["contribution", "transfer", "withdrawal"] | None = None
    account_id: int | None = Field(default=None, gt=0)
    to_account_id: int | None = Field(default=None, gt=0)
    start_period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    interval_months: int | None = Field(default=None, ge=1, le=120)
    repeat_count: int | None = Field(default=None, ge=1, le=1200)
    end_period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    on_shortage: Literal["skip", "partial"] | None = None
    annual_return: float | None = Field(default=None, allow_inf_nan=False)
    note: str | None = None
    life_event_id: int | None = Field(default=None, gt=0)


class AssumptionPeriodInput(BaseModel):
    """期間ごとの前提 (§8-11): the default yield and the inflation from start_period to end_period
    (inclusive; open when null). A null rate keeps what applies without the record; fields left out
    keep their value on update."""
    model_config = ConfigDict(extra="forbid")
    start_period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    end_period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    annual_return: float | None = Field(default=None, allow_inf_nan=False)
    inflation: float | None = Field(default=None, allow_inf_nan=False)
    note: str | None = None


class ReflectionGoalSettings(BaseModel):
    """How the goal is written into the plan: 基準 (remaining: 残り期間に合わせる; goal_setting: 積立設定から決まる額),
    確保済みの引き方 (even / recent) and 遅れの取り返し (even / recent / none)."""
    model_config = ConfigDict(extra="forbid")
    base: Literal["remaining", "goal_setting"] | None = None
    held: Literal["even", "recent"] | None = None
    catch_up: Literal["even", "recent", "none"] | None = None


class ReflectionProductSettings(BaseModel):
    """How earmarks with linked products are written: base (remaining / saved: 取り置きの月額), held (even / recent)."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    base: Literal["remaining", "saved"] | None = None
    held: Literal["even", "recent"] | None = None


class ReflectionSettingsPatch(BaseModel):
    """計画への反映の設定 (WP27); fields left out keep their value. enabled: 自動反映."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    goal: ReflectionGoalSettings | None = None
    products: ReflectionProductSettings | None = None


class FxTrackedCurrencyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")


class FxTrackedCurrency(FxTrackedCurrencyCreate):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime
