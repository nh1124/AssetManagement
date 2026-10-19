export interface TransactionLeg {
    account_id: number;
    debit?: number;
    credit?: number;
    memo?: string | null;
    capsule_id?: number | null;
}

export interface TransactionLegRead extends TransactionLeg {
    id: number;
    account_name?: string | null;
    account_type?: string | null;
}

export interface Transaction {
    id: number;
    date: string;
    description: string;
    amount: number;
    currency: string;
    /** The legs, when a payment splits across more than two accounts. Sending
     *  legs makes from/to derived: they are filled only when a single leg sits
     *  on that side. */
    legs?: TransactionLeg[] | TransactionLegRead[];
    from_account_id?: number;
    to_account_id?: number;
    batch_id?: number | null;
    from_account_name?: string;
    to_account_name?: string;
    /** Set when the list was filtered by account: what this transaction moved
     *  on that account, which for a compound entry is not its total. */
    matched_debit?: number | null;
    matched_credit?: number | null;
    /** Set when the entry carries a fixed asset's write-down; the ledger opens it as one. */
    depreciation?: { id: number; product_id: number; product_name: string | null; period: string } | null;
}

/** What recording a product's next write-down by hand would propose. */
export interface DepreciationPreview {
    product_id: number;
    product_name: string;
    currency: string;
    next_period: string | null;
    due: number;
    book_value: number;
    expense_account_id: number | null;
    asset_account_id: number | null;
    blocked_reason: string | null;
}

export interface TransactionProposal {
    id: number;
    client_id: number;
    origin: string;
    origin_ref: Record<string, unknown>;
    date: string;
    description: string;
    amount: number;
    currency: string;
    legs: TransactionLeg[];
    trigger_transaction_id?: number | null;
    status: string;
    posted_transaction_id?: number | null;
    idempotency_key: string;
    note?: string | null;
    created_at?: string | null;
    decided_at?: string | null;
    decided_by_client_id?: number | null;
}

export type LiabilityPaymentPolicy = 'full' | 'minimum' | 'fixed' | 'installment' | 'revolving';


export interface Account {
    id: number;
    name: string;
    account_type: 'asset' | 'liability' | 'income' | 'expense';
    balance: number;
    liability_closing_day?: number | null;
    liability_payment_day?: number | null;
    liability_payment_month_offset?: number;
    liability_payment_policy?: LiabilityPaymentPolicy;
    liability_minimum_payment?: number | null;
    liability_fixed_payment_amount?: number | null;
    liability_installment_months?: number | null;
    liability_revolving_rate?: number | null;
    is_active: boolean;
}

export interface ExchangeRate {
    id: number;
    base_currency: string;
    quote_currency: string;
    rate: number;
    as_of_date: string;
    source: string;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface ExchangeRateAutoUpdateResult {
    target_currency: string;
    updated: ExchangeRate[];
    errors: Array<Pick<ExchangeRate, 'base_currency' | 'quote_currency'> & { error: string }>;
}

export interface LoginResult {
    access_token?: string | null;
    token_type: 'bearer' | 'mfa' | string;
    client_id: number;
    name: string;
    mfa_required: boolean;
    mfa_token?: string | null;
}

export interface MfaStatus {
    enabled: boolean;
    enabled_at?: string | null;
    last_verified_at?: string | null;
    recovery_codes_remaining: number;
}

export interface MfaSetupStart {
    otpauth_uri: string;
    manual_entry_key: string;
}

export interface MfaRecoveryCodes {
    recovery_codes: string[];
}

export type AiOperationRisk = 'low' | 'medium' | 'high' | 'critical';
export type AiOperationMode = 'deny' | 'allow_read' | 'require_approval' | 'allow_execute';
export type AiOperationDecision = 'allowed' | 'denied' | 'approval_required' | 'applied' | 'failed';
export type AiOperationSource = 'frontend' | 'mcp_http' | 'mcp_stdio' | 'backend';
export type AiChangeRequestStatus = 'draft' | 'pending' | 'approved' | 'applied' | 'rejected' | 'expired' | 'failed';
export type AiMcpWriteMode = 'direct_write' | 'change_request';

export interface AiExecutionSettings {
    mcp_write_mode: AiMcpWriteMode;
    supported_change_request_operations: string[];
}

export interface AiOperationPolicy {
    id: number;
    client_id: number;
    ai_client_id?: number | null;
    resource: string;
    action: string;
    risk: AiOperationRisk;
    mode: AiOperationMode;
    threshold_amount?: number | null;
    threshold_count?: number | null;
    require_mfa: boolean;
    created_at: string;
    updated_at: string;
}

export type AiOperationPolicyPayload = Omit<AiOperationPolicy, 'id' | 'client_id' | 'created_at' | 'updated_at'>;

export interface AiAuditLog {
    id: number;
    client_id: number;
    actor_client_id?: number | null;
    ai_client_id?: number | null;
    mcp_client_id?: string | null;
    source: AiOperationSource;
    tool_name?: string | null;
    resource: string;
    action: string;
    risk: AiOperationRisk;
    decision: AiOperationDecision;
    request_summary: Record<string, unknown>;
    diff_summary: Record<string, unknown>;
    result_summary: Record<string, unknown>;
    approval_request_id?: number | null;
    mfa_verified: boolean;
    ip_address?: string | null;
    user_agent?: string | null;
    created_at: string;
}

export interface AiChangeRequestPreview {
    resource: string;
    action: string;
    risk: AiOperationRisk;
    target_ref: Record<string, unknown>;
    input_payload: Record<string, unknown>;
    before_snapshot: Record<string, unknown>;
    after_snapshot: Record<string, unknown>;
    diff: Record<string, unknown>;
    validation: Record<string, unknown>;
    precondition_hash?: string | null;
    requires_mfa: boolean;
}

export interface AiChangeRequest extends AiChangeRequestPreview {
    id: number;
    client_id: number;
    created_by_client_id?: number | null;
    ai_client_id?: number | null;
    mcp_client_id?: string | null;
    source: AiOperationSource;
    tool_name?: string | null;
    status: AiChangeRequestStatus;
    idempotency_key: string;
    approved_by_client_id?: number | null;
    approved_at?: string | null;
    applied_at?: string | null;
    expires_at?: string | null;
    result: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}


/** A story fact of a scenario. Funding progress comes only from /life-events/with-progress. */
export interface LifeEvent {
    id: number;
    scenario_id: number;
    lineage: string;
    direction: 'expense' | 'income';
    account_id: number | null;
    condition_mode: 'all' | 'any';
    name: string;
    target_date: string;
    target_amount: number;
    priority: 1 | 2 | 3;
    note: string | null;
    created_at?: string | null;
}

/** An earmark counted toward a goal event (実績管理の設定), with the percent that counts. */
export interface GoalEarmarkLink {
    capsule_id: number;
    capsule_name?: string;
    share: number;
}

export interface LifeEventProgress extends LifeEvent {
    current_funded: number;
    gap: number;
    progress_percentage: number;
    months_remaining: number;
    earmarks: GoalEarmarkLink[];
}

export type DepreciationMethod = 'none' | 'straight_line' | 'declining_balance';
export type DepreciationInterval = 'monthly' | 'yearly';

export interface Product {
    id: number;
    name: string;
    category: string;
    location?: string;
    last_unit_price: number;
    units_per_purchase: number;
    unit_cost: number;
    frequency_days: number;
    last_purchase_date?: string;
    is_asset: boolean;
    lifespan_months?: number;
    budget_account_id?: number | null;
    budget_account_name?: string | null;
    funding_capsule_id?: number | null;
    funding_capsule_name?: string | null;
    budget_treatment?: 'auto' | 'expense_only' | 'reserve_allocation' | 'asset_replacement';
    effective_budget_treatment?: string;
    reserve_target_amount?: number;
    recommended_monthly_reserve?: number;
    purchase_price?: number;
    purchase_date?: string;
    auto_depreciation?: boolean;
    depreciation_method?: DepreciationMethod;
    depreciation_annual_rate?: number | null;
    depreciation_interval?: DepreciationInterval;
    depreciation_start_date?: string | null;
    depreciation_expense_account_id?: number | null;
    depreciation_asset_account_id?: number | null;
    monthly_cost: number;
    next_purchase_date?: string;
}

export type AutoTransactionKind = 'income' | 'expense' | 'debt' | 'transfer';
export type AutoFrequency = 'Monthly' | 'Yearly' | 'EveryNDays';
export interface AutoTransactionInput {
    name: string;
    kind: AutoTransactionKind;
    amount: number;
    currency: string;
    source_account_id: number | null;
    destination_account_id: number | null;
    budget_account_id: number | null;
    repeat_mode: 'once' | 'count' | 'indefinite';
    frequency: AutoFrequency | null;
    frequency_days: number | null;
    day_of_month: number | null;
    month_of_year: number | null;
    start_date: string;
    end_date: string | null;
    repeat_count: number | null;
    budget_active: boolean;
    is_active: boolean;
    note: string | null;
}
export interface AutoTransaction extends AutoTransactionInput {
    id: number;
    next_due_date: string | null;
    source_account_name: string | null;
    destination_account_name: string | null;
    budget_account_name: string | null;
}

export type MonthlyPlanLineType = 'income' | 'expense' | 'allocation' | 'debt_payment' | 'borrowing' | 'drawdown';
export type MonthlyPlanTargetType = 'account' | 'capsule' | 'product' | 'manual';
export type MonthlyPlanCashTreatment = 'auto' | 'cash' | 'non_cash';

export interface MonthlyPlanLine {
    id?: number | null;
    target_period: string;
    line_type: MonthlyPlanLineType;
    target_type: MonthlyPlanTargetType;
    target_id?: number | null;
    account_id?: number | null;
    source_account_id?: number | null;
    name?: string | null;
    target_name?: string | null;
    account_name?: string | null;
    amount: number;
    budget_amount?: number;
    cash_treatment?: MonthlyPlanCashTreatment;
    actual?: number;
    variance?: number;
    recurring_amount?: number;
    suggested_amount?: number;
    suggested_source?: 'product_reserve' | string | null;
    suggested_items?: Array<{
        id: number;
        name: string;
        amount: number;
        source?: string;
    }>;
    suggested_status?: 'synced' | 'diff' | null;
    sync_status?: 'synced' | 'missing' | 'diff' | null;
    registry_amount?: number;
    registry_entry_ids?: number[];
    registry_items?: Array<{
        id: number;
        name: string;
        amount: number;
        source?: string;
        kind?: AutoTransactionKind;
    }>;
    is_active?: boolean;
    source?: string;
    source_kind?: string;
    manual_override?: boolean;
}


export interface AnalysisSummary {
    net_worth: number;
    monthly_pl: number;
    liability_total: number;
    goal_probability: number;
    total_goal_amount: number;
    total_funded: number;
    effective_cash?: number;
    logical_balance?: number;
    cfo_briefing?: string;
    savings_rate?: number;
    liquidity_coverage_ratio?: number;
    runway_months?: number;
    roadmap_progression?: 'On Track' | 'At Risk' | 'Off Track';
    monthly_transaction_count?: number;
    total_goal_count?: number;
    budget_usage_rate?: number;
}

export interface ActionProposal {
    id: string;
    kind: 'allocate_to_goal' | 'transfer_to_capsule' | 'increase_savings' | 'review_budget' | 'extend_target_date';
    type?: string;
    description: string;
    amount?: number | null;
    target_id?: number | null;
    target_life_event_id?: number | null;
    auto_executable: boolean;
    action_status?: 'pending' | 'applied' | 'skipped' | 'failed';
    applied?: boolean;
    monthly_action_id?: number | null;
    navigation_target?: string;
}

export interface MonthlyAction {
    id: number;
    source_period: string;
    target_period?: string | null;
    proposal_id: string;
    kind: string;
    description: string;
    amount?: number | null;
    target_id?: number | null;
    payload: Record<string, unknown>;
    result: Record<string, unknown>;
    status: 'pending' | 'applied' | 'skipped' | 'failed';
    applied_at?: string | null;
    created_at?: string | null;
}

export type ReviewActionKind = 'set_budget' | 'add_auto_transaction' | 'stop_auto_transaction' | 'change_capsule_contribution';

export interface ReviewActionCreate {
    source_period: string;
    target_period?: string | null;
    kind: ReviewActionKind;
    description?: string;
    payload: Record<string, unknown>;
}

export interface MonthlyReport {
    period: string;
    start_date?: string;
    end_date?: string;
    summary: {
        net_worth: number;
        net_worth_change?: number;
        net_worth_change_pct?: number;
        monthly_pl: number;
        period_pl?: number;
        savings_rate: number;
    };
    goal_progress: Array<Record<string, unknown>>;
    anomalies: Array<Record<string, any>>;
    action_proposals: ActionProposal[];
}

export interface PeriodReview {
    id: number;
    start_date: string;
    end_date: string;
    label: string;
    reflection: string;
    next_actions: string;
    created_at: string;
    updated_at?: string | null;
}

export interface NetWorthHistoryPoint {
    period: string;
    net_worth: number;
    assets: number;
    liabilities: number;
}

export type AccountFlowGrain = 'day' | 'week' | 'month' | 'quarter';

export interface AccountFlowBucket {
    key: string;
    label: string;
    start_date?: string;
    end_date?: string;
    debit: number;
    credit: number;
    net_movement: number;
    normal_balance_delta: number;
    transaction_count: number;
}

export interface AccountFlowRow {
    account_id: number;
    account_name: string;
    account_type: Account['account_type'];
    total_debit: number;
    total_credit: number;
    net_movement: number;
    normal_balance_delta: number;
    transaction_count: number;
    buckets: AccountFlowBucket[];
}

export interface AccountFlowAnalysis {
    period: string;
    start_date: string;
    end_date: string;
    grain: AccountFlowGrain;
    currency: string;
    account_types: string[];
    buckets: Array<Pick<AccountFlowBucket, 'key' | 'label' | 'start_date' | 'end_date'>>;
    accounts: AccountFlowRow[];
    totals: {
        debit: number;
        credit: number;
        net_movement: number;
        normal_balance_delta: number;
        account_count: number;
    };
}

export interface AccountFlowTransaction {
    entry_id: number;
    transaction_id: number;
    date: string;
    description: string;
    currency: string;
    amount: number;
    raw_amount: number;
    account_id: number;
    account_name: string;
    account_type: Account['account_type'];
    debit: number;
    credit: number;
    raw_debit: number;
    raw_credit: number;
    normal_balance_delta: number;
    counterpart_accounts: Array<{
        account_id: number;
        account_name?: string | null;
        account_type?: string | null;
        debit: number;
        credit: number;
    }>;
    from_account_id?: number | null;
    from_account_name?: string | null;
    to_account_id?: number | null;
    to_account_name?: string | null;
}

export interface AccountFlowTransactionPage {
    account: Pick<Account, 'id' | 'name' | 'account_type'>;
    period: string;
    start_date: string;
    end_date: string;
    currency: string;
    items: AccountFlowTransaction[];
    total: number;
}

export type CapsuleDrawdownKind = 'as_intended' | 'diverted';

export interface CapsuleDrawdownInput {
    amount: number;
    from_account_id: number;
    to_account_id: number;
    kind: CapsuleDrawdownKind;
    date: string;
    description: string;
    note?: string;
}

export interface CapsuleDrawdown {
    id: number;
    client_id: number;
    capsule_id: number;
    transaction_id: number;
    kind: CapsuleDrawdownKind;
    amount_minor: number;
    amount: number;
    currency: string;
    date: string;
    description: string;
    note: string | null;
    created_at: string;
}

export interface CapsuleDrawdownResult {
    transaction: Transaction;
    drawdown: CapsuleDrawdown;
}

export interface AccountEarmark {
    capsule_id: number;
    capsule_name: string;
    claimed: number;
    claimed_minor: number;
    currency: string;
    max_share_bp: number | null;
}

export interface CapsuleFundingSource {
    id: number;
    account_id: number;
    account_name?: string | null;
    target_amount: number;
    max_share_bp: number | null;
    sort_order: number;
}

export type CapsuleFundingSourceInput = Pick<CapsuleFundingSource, 'account_id' | 'target_amount' | 'max_share_bp' | 'sort_order'>;

export interface Capsule {
    id: number;
    name: string;
    target_amount: number;
    monthly_contribution: number;
    current_balance: number;
    capsule_type?: string;
    target_amount_source?: string;
    monthly_contribution_source?: string;
    recommended_monthly_contribution?: number;
    linked_products?: Array<{
        id: number;
        name: string;
        is_asset: boolean;
        reserve_target_amount: number;
        recommended_monthly_reserve: number;
    }>;
    funding_sources?: CapsuleFundingSource[];
}

/** What a capsule rule fires on. It reads as a statement about an entry's
 *  legs -- CreditExpense means the expense was funded by a liability -- and
 *  is the rule's own vocabulary, not a field on the transaction. */
export type CapsuleTriggerKind = 'Income' | 'Expense' | 'CreditExpense' | 'Transfer';

export interface CapsuleRule {
    id: number;
    capsule_id: number;
    capsule_name?: string | null;
    trigger_type: CapsuleTriggerKind;
    trigger_category?: string | null;
    trigger_description?: string | null;
    trigger_account_id?: number | null;
    source_mode: 'transaction_account' | 'fixed_account';
    source_account_id?: number | null;
    source_account_name?: string | null;
    destination_account_id?: number | null;
    amount_type: 'fixed' | 'percentage';
    amount_value: number;
    is_active: boolean;
    created_at: string;
}

export interface DataHealthIssue {
    code: string;
    severity: 'ok' | 'warning' | 'error';
    title: string;
    detail: string;
    count: number;
    repairable: boolean;
    items: Array<Record<string, unknown>>;
}

export interface DataHealthResult {
    status: 'ok' | 'issues_found' | 'repaired';
    total_issues: number;
    repairable_groups: number;
    issues: DataHealthIssue[];
}

export interface DataRepairResult {
    status: 'repaired';
    actions: Array<{ code: string; updated: number }>;
    health: DataHealthResult;
}

export type { ReconciliationAdjustment, ReconciliationComparison } from './reconciliation';

/** Fixed-asset schedules shown beside automatic transactions. */
export interface AutomaticDepreciationRecording {
    product_id: number;
    name: string;
    method: DepreciationMethod;
    interval: DepreciationInterval;
    next_period: string | null;
    next_amount: number;
    book_value: number;
    currency: string;
    auto_depreciation: boolean;
}

export interface GeneratedTransaction {
    id: number; date: string; description: string; amount: number; currency: string; source: string;
}

/** One scheduled occurrence or write-down in a month, valued in the client currency. */
export interface ScheduledTransaction {
    kind: 'automatic_transaction' | 'depreciation';
    entry_id: number | null;
    product_id: number | null;
    name: string;
    line_type: MonthlyPlanLineType | null;
    amount: number;
    date: string;
    frequency: string | null;
    posted: boolean;
    in_budget: boolean;
    /** The account or subject whose budget the movement is. */
    account_id: number | null;
    counter_account_id: number | null;
}

export interface ScheduledTransactions {
    period: string;
    currency: string;
    items: ScheduledTransaction[];
}


export interface FxTrackedCurrency {
    currency: string;
    created_at: string;
}
