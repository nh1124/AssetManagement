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
RegistryEntryTypeLiteral = Literal["asset", "item", "service", "income", "allocation", "debt"]
RegistryFrequencyLiteral = Literal["Monthly", "Yearly", "EveryNDays", "Irregular"]
RegistryLineTypeLiteral = Literal["income", "expense", "allocation", "debt_payment", "borrowing", "drawdown"]
MonthlyPlanCashTreatmentLiteral = Literal["auto", "cash", "non_cash"]
LiabilityPaymentPolicyLiteral = Literal["full", "minimum", "fixed", "installment", "revolving"]
AiOperationRiskLiteral = Literal["low", "medium", "high", "critical"]
AiOperationModeLiteral = Literal["deny", "allow_read", "require_approval", "allow_execute"]
AiOperationDecisionLiteral = Literal["allowed", "denied", "approval_required", "applied", "failed"]
AiOperationSourceLiteral = Literal["frontend", "mcp_http", "mcp_stdio", "backend"]
AiChangeRequestStatusLiteral = Literal["draft", "pending", "approved", "applied", "rejected", "expired", "failed"]
AiDataClassificationLiteral = Literal["normal", "sensitive", "secret"]
AiMcpWriteModeLiteral = Literal["direct_write", "change_request"]

AccountInstitutionLiteral = Literal["none", "nisa_tsumitate", "nisa_growth", "ideco", "dc_corporate", "tokutei_withholding", "tokutei_self", "general"]

# Account Schemas
class AccountBase(BaseModel):
    name: str
    account_type: str
    balance: float = 0
    parent_id: Optional[int] = None
    institution: AccountInstitutionLiteral = "none"
    withdrawable_from_age: int | None = Field(default=None, ge=0)
    expected_return: float | None = 0.0  # Annual return rate %
    role: Literal["defense", "growth", "earmarked", "operating", "unassigned"] = "unassigned"
    role_target_amount: Optional[float] = None
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
    name: Optional[str] = None
    parent_id: Optional[int] = None
    institution: AccountInstitutionLiteral | None = None
    withdrawable_from_age: int | None = Field(default=None, ge=0)
    expected_return: Optional[float] = None
    role: Optional[Literal["defense", "growth", "earmarked", "operating", "unassigned"]] = None
    role_target_amount: Optional[float] = None
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


class Transaction(TransactionBase):
    id: int
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


class QuickTemplateBase(BaseModel):
    tray: str
    name: str
    template_kind: str
    description: Optional[str] = None
    category: Optional[str] = None
    default_currency: str | None = None
    default_from_account_id: Optional[int] = None
    default_to_account_id: Optional[int] = None
    config: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0
    is_active: bool = True


class QuickTemplateCreate(QuickTemplateBase):
    pass


class QuickTemplateUpdate(BaseModel):
    tray: Optional[str] = None
    name: Optional[str] = None
    template_kind: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    default_currency: Optional[str] = None
    default_from_account_id: Optional[int] = None
    default_to_account_id: Optional[int] = None
    config: Optional[dict[str, Any]] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class QuickTemplate(QuickTemplateBase):
    id: int
    default_from_account_name: Optional[str] = None
    default_to_account_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TransactionBatchCreate(BaseModel):
    quick_template_id: Optional[int] = None
    label: Optional[str] = None
    source: str = "quick"
    input_payload: dict[str, Any] = Field(default_factory=dict)
    transactions: list[TransactionCreate]


class TransactionBatch(BaseModel):
    id: int
    quick_template_id: Optional[int] = None
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
    depreciation_method: Optional[DepreciationMethodLiteral] = None
    depreciation_annual_rate: Optional[float] = Field(default=None, ge=0, le=100)
    depreciation_interval: Optional[DepreciationIntervalLiteral] = None
    depreciation_start_date: Optional[date] = None
    depreciation_expense_account_id: Optional[int] = None
    depreciation_asset_account_id: Optional[int] = None

    model_config = ConfigDict(extra="forbid")

class DepreciationPostRequest(BaseModel):
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

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
    name: str
    entry_type: RegistryEntryTypeLiteral = "service"
    category: Optional[str] = None
    amount: float = 0.0
    currency: str | None = None
    frequency: RegistryFrequencyLiteral = "Monthly"
    frequency_days: Optional[int] = None
    day_of_month: int = 1
    month_of_year: Optional[int] = None
    line_type: RegistryLineTypeLiteral = "expense"
    budget_account_id: Optional[int] = None
    source_account_id: Optional[int] = None
    destination_account_id: Optional[int] = None
    funding_capsule_id: Optional[int] = None
    budget_treatment: ProductBudgetTreatmentLiteral = "expense_only"
    generate_recurring: bool = False
    budget_active: bool = True
    is_active: bool = True
    source_product_id: Optional[int] = None
    source_recurring_transaction_id: Optional[int] = None
    note: Optional[str] = None
    start_period: Optional[str] = None
    end_period: Optional[str] = None


class RegistryEntryCreate(RegistryEntryBase):
    model_config = ConfigDict(extra="forbid")


class RegistryEntry(RegistryEntryBase):
    id: int
    budget_account_name: Optional[str] = None
    source_account_name: Optional[str] = None
    destination_account_name: Optional[str] = None
    funding_capsule_name: Optional[str] = None
    recurring_transaction_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Simulation Config
class SimulationConfigBase(BaseModel):
    horizon_years: int = Field(default=30, ge=1, le=60)
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

class LockedAccount(BaseModel):
    account_id: int
    name: str
    withdrawable_from_age: int
    available_on: date
    balances_minor: dict[str, int]


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
    locked_until_age_minor: dict[str, int] = Field(default_factory=dict)
    locked_accounts: list[LockedAccount] = Field(default_factory=list)
    locked_as_of: date | None = None
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
    currency: str | None = None
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None
    frequency: Literal['Monthly', 'Yearly']
    day_of_month: int = 1
    month_of_year: Optional[int] = None  # Used for Yearly frequency
    next_due_date: Optional[date] = None  # Calculated by system
    start_period: Optional[str] = None
    end_period: Optional[str] = None
    auto_post: bool = True
    is_active: bool = True
    source_registry_entry_id: Optional[int] = None

class RecurringTransactionCreate(RecurringTransactionBase):
    model_config = ConfigDict(extra="forbid")


class RecurringTransactionUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None
    frequency: Optional[Literal['Monthly', 'Yearly']] = None
    day_of_month: Optional[int] = None
    month_of_year: Optional[int] = None
    next_due_date: Optional[date] = None
    start_period: Optional[str] = None
    end_period: Optional[str] = None
    auto_post: Optional[bool] = None
    is_active: Optional[bool] = None
    source_registry_entry_id: Optional[int] = None

    model_config = ConfigDict(extra="forbid")

class RecurringTransaction(RecurringTransactionBase):
    id: int
    source_registry_entry_name: Optional[str] = None

    class Config:
        from_attributes = True

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
    "life_event",
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
    plan_id: Optional[int] = None


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
    plan_id: Optional[int] = None


class MonthlyPlanLine(MonthlyPlanLineBase):
    # The registry entry supplies this link rather than a plan-line column.
    recurring_transaction_id: Optional[int] = None
    id: int
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

class BudgetPlanCreate(BaseModel):
    name: str
    description: Optional[str] = None
    sort_order: int = 0
    model_config = ConfigDict(extra="forbid")


class BudgetPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


class BudgetPlan(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_default: bool
    sort_order: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CopyPeriodRequest(BaseModel):
    source_period: str
    target_period: str
    plan_id: Optional[int] = None


class BudgetPlanCashFlowRow(BaseModel):
    period: str
    ending_cash: float
    net_cash: float


class BudgetPlanCompareResult(BaseModel):
    plan_id: int
    plan_name: str
    cash_flow: list[BudgetPlanCashFlowRow]


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


class LifeEventBase(BaseModel):
    direction: Literal["expense", "income"] = "expense"
    account_id: Optional[int] = None
    condition_mode: Literal["all", "any"] = "all"
    name: str
    start_date: Optional[date] = None
    target_date: date
    target_amount: float
    priority: Literal[1, 2, 3] = 2
    note: Optional[str] = None
    active_plan_basis: str = "milestone"
    active_plan_label: Optional[str] = None
    plan_status_override: Optional[str] = None
    budget_reflection: Optional[Literal["firm", "conditional", "simulation_only"]] = None

class LifeEventCreate(LifeEventBase):
    model_config = ConfigDict(extra="forbid")
    scenario_id: int

class LifeEventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["expense", "income"] = "expense"
    account_id: Optional[int] = None
    condition_mode: Literal["all", "any"] = "all"
    name: Optional[str] = None
    start_date: Optional[date] = None
    target_date: Optional[date] = None
    target_amount: Optional[float] = None
    priority: Optional[Literal[1, 2, 3]] = None
    note: Optional[str] = None
    active_plan_basis: Optional[str] = None
    active_plan_label: Optional[str] = None
    plan_status_override: Optional[str] = None
    budget_reflection: Optional[Literal["firm", "conditional", "simulation_only"]] = None

class GoalArchiveRequest(BaseModel):
    capsule_action: Literal["keep", "stop_rules", "release", "detach"] = "keep"
    transfer_account_id: Optional[int] = None

class LifeEvent(LifeEventBase):
    id: int
    scenario_id: int
    lineage: str
    archived_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    budget_reflection_effective: Literal["firm", "conditional", "simulation_only"] = "firm"

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
    funded_percentage: float = 0.0
    plan_expected_amount: float = 0.0
    plan_gap: float = 0.0
    plan_status: str = "No Plan"
    plan_progress_percentage: float = 0.0
    plan_previous_milestone: Optional[dict[str, Any]] = None
    plan_next_milestone: Optional[dict[str, Any]] = None

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
    is_active_plan: bool = True

class MilestoneCreate(MilestoneBase):
    pass

class MilestoneUpdate(BaseModel):
    note: Optional[str] = None
    target_amount: Optional[float] = None
    date: Optional[DateType] = None
    is_active_plan: Optional[bool] = None

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
    auto_post: bool = False
    name: str
    target_amount: float
    monthly_contribution: float
    life_event_id: Optional[int] = None
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
    life_event_id: Optional[int] = None
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


class ContributionScheduleItem(BaseModel):
    kind: Literal["monthly", "yearly", "one_time"] = "monthly"
    amount: float = Field(ge=0)
    month: Optional[int] = Field(default=None, ge=1, le=12)
    date: Optional[DateType] = None
    start_date: Optional[DateType] = None
    end_date: Optional[DateType] = None
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


class CapsuleTransactionPreviewRequest(BaseModel):
    description: Optional[str] = ""
    amount: float
    date: date
    legs: List[TransactionLeg]


class CapsuleTransferPreview(BaseModel):
    capsule_id: int
    rule_id: int
    capsule_name: str
    source_account_id: int
    destination_account_id: int
    amount: float
    auto_post: bool


class ReconciliationAccount(BaseModel):
    id: int
    name: str
    account_type: str


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
    # null returns the scenario to the client-wide simulation setting.
    monthly_savings: float | None = None

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
        savings = values.get("monthly_savings")
        if savings is not None and (type(savings) not in (int, float) or not math.isfinite(savings) or savings < 0):
            raise ValueError("月の積立額は0以上の数値で指定してください。")
        return values


class LifeScenarioGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_detach: bool = False


class LifeScenarioAccountReturn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: int
    annual_return: float

    @model_validator(mode="before")
    @classmethod
    def validate_rate(cls, values):
        return LifeScenarioUpdate.validate_assumptions(values)


class LifeScenarioAccountReturns(BaseModel):
    model_config = ConfigDict(extra="forbid")
    returns: list[LifeScenarioAccountReturn]
