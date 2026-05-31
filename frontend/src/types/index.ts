export interface Transaction {
    id: number;
    date: string;
    description: string;
    amount: number;
    type: 'Income' | 'Expense' | 'Transfer' | 'LiabilityPayment' | 'Borrowing' | 'CreditExpense' | 'CreditAssetPurchase';
    category?: string;
    currency: string;
    from_account_id?: number;
    to_account_id?: number;
    batch_id?: number | null;
    from_account_name?: string;
    to_account_name?: string;
}

export interface QuickTemplate {
    id: number;
    tray: string;
    name: string;
    template_kind: string;
    description?: string | null;
    category?: string | null;
    default_currency: string;
    default_from_account_id?: number | null;
    default_to_account_id?: number | null;
    default_from_account_name?: string | null;
    default_to_account_name?: string | null;
    config: Record<string, unknown>;
    sort_order: number;
    is_active: boolean;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface TransactionBatch {
    id: number;
    quick_template_id?: number | null;
    label?: string | null;
    source: string;
    input_payload: Record<string, unknown>;
    created_at: string;
    transactions: Transaction[];
}

export type AccountRole = 'defense' | 'growth' | 'earmarked' | 'operating' | 'unassigned';
export type LiabilityPaymentPolicy = 'full' | 'minimum' | 'fixed' | 'installment' | 'revolving';

export interface Account {
    id: number;
    name: string;
    account_type: 'asset' | 'liability' | 'income' | 'expense';
    balance: number;
    rollup_balance?: number;
    parent_id?: number | null;
    expected_return: number;
    role: AccountRole;
    role_target_amount?: number | null;
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

export interface AccountTreeNode extends Account {
    rollup_balance: number;
    children: AccountTreeNode[];
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
    detected_pairs: Array<Pick<ExchangeRate, 'base_currency' | 'quote_currency'>>;
    updated: ExchangeRate[];
    skipped: Array<Pick<ExchangeRate, 'base_currency' | 'quote_currency'> & { reason: string }>;
    errors: Array<Pick<ExchangeRate, 'base_currency' | 'quote_currency'> & { error: string }>;
}


export interface RoadmapEntry {
    year: number;
    label?: string;
    start_balance: number;
    contribution: number;
    investment_gain: number;
    end_balance: number;
    goal_coverage: number;
}

export interface LifeEvent {
    id: number;
    name: string;
    start_date?: string | null;
    target_date: string;
    target_amount: number;
    priority: 1 | 2 | 3;
    note?: string | null;
    active_plan_basis?: string;
    active_plan_label?: string | null;
    plan_status_override?: string | null;
    created_at?: string;
    current_funded?: number;
    projected_amount?: number;
    gap?: number;
    weighted_return?: number;
    status?: 'On Track' | 'At Risk' | 'Off Track' | 'Achieved' | 'Missed' | 'Not Started';
    progress_percentage?: number;
    funded_percentage?: number;
    plan_expected_amount?: number;
    plan_gap?: number;
    plan_status?: 'Ahead' | 'On Track' | 'Watch' | 'Behind' | 'No Plan' | string;
    plan_progress_percentage?: number;
    plan_previous_milestone?: MilestonePlanSummary | null;
    plan_next_milestone?: MilestonePlanSummary | null;
    years_remaining?: number;
    roadmap?: RoadmapEntry[];
}

export interface MilestonePlanSummary {
    id: number;
    date: string;
    target_amount: number;
    note?: string | null;
    source?: string | null;
    gap?: number;
}

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
    monthly_cost: number;
    next_purchase_date?: string;
}

export type RegistryEntryType = 'asset' | 'item' | 'service' | 'income' | 'allocation' | 'debt';
export type RegistryFrequency = 'Monthly' | 'Yearly' | 'EveryNDays' | 'Irregular';

export interface RegistryEntry {
    id: number;
    name: string;
    entry_type: RegistryEntryType;
    category?: string | null;
    amount: number;
    currency: string;
    frequency: RegistryFrequency;
    frequency_days?: number | null;
    day_of_month: number;
    month_of_year?: number | null;
    transaction_type: Transaction['type'];
    line_type: MonthlyPlanLineType;
    budget_account_id?: number | null;
    budget_account_name?: string | null;
    source_account_id?: number | null;
    source_account_name?: string | null;
    destination_account_id?: number | null;
    destination_account_name?: string | null;
    funding_capsule_id?: number | null;
    funding_capsule_name?: string | null;
    budget_treatment?: 'auto' | 'expense_only' | 'reserve_allocation' | 'asset_replacement';
    generate_recurring: boolean;
    budget_active: boolean;
    is_active: boolean;
    source_product_id?: number | null;
    source_recurring_transaction_id?: number | null;
    recurring_transaction_id?: number | null;
    note?: string | null;
    start_period?: string | null;
    end_period?: string | null;
}

export type MonthlyPlanLineType = 'income' | 'expense' | 'allocation' | 'debt_payment' | 'borrowing' | 'drawdown';
export type MonthlyPlanTargetType = 'account' | 'capsule' | 'life_event' | 'product' | 'manual';
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
        entry_type?: string;
    }>;
    recurring_transaction_id?: number | null;
    is_active?: boolean;
    source?: string;
    source_kind?: string;
    source_id?: number | null;
    manual_override?: boolean;
}

export interface MonthlyReview {
    id: number;
    target_period: string;
    reflection: string;
    next_actions: string;
    created_at: string;
    updated_at?: string | null;
}

export interface RecurringTransaction {
    id: number;
    name: string;
    amount: number;
    currency: string;
    type: Transaction['type'];
    from_account_id?: number | null;
    to_account_id?: number | null;
    frequency: 'Monthly' | 'Yearly';
    day_of_month: number;
    month_of_year?: number | null;
    next_due_date?: string | null;
    start_period?: string | null;
    end_period?: string | null;
    auto_post: boolean;
    is_active: boolean;
    source_registry_entry_id?: number | null;
    source_registry_entry_name?: string | null;
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
    idle_money_rate?: number;
    idle_money?: number;
    idle_money_by_role?: Array<{
        role: AccountRole;
        balance: number;
        target?: number | null;
        status: string;
        idle_component: number;
    }>;
    liquidity_coverage_ratio?: number;
    runway_months?: number;
    roadmap_progression?: 'On Track' | 'At Risk' | 'Off Track';
    monthly_transaction_count?: number;
    total_goal_count?: number;
    budget_usage_rate?: number;
}

export interface ReconcileDiscrepancy {
    account_id: number;
    account_name: string;
    account_type: string;
    stored_balance: number;
    calculated_balance: number;
    difference: number;
    fixed: boolean;
}

export interface ReconcileResponse {
    status: 'ok' | 'discrepancies_found' | 'fixed';
    discrepancy_count?: number;
    fixed_count?: number;
    discrepancies?: ReconcileDiscrepancy[];
    fixed_accounts?: ReconcileDiscrepancy[];
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

export type ReviewActionKind = 'set_budget' | 'add_recurring' | 'pause_recurring' | 'boost_allocation' | 'change_capsule_contribution';

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

export interface Milestone {
    id: number;
    life_event_id?: number;
    date: string;
    target_amount: number;
    note?: string;
    source?: string;
    source_snapshot?: Record<string, unknown> | null;
    is_active_plan?: boolean;
}

export type MilestoneSimulationBasis = 'annual_plan' | 'deterministic' | 'p10' | 'p50' | 'p90';
export type MilestoneSimulationInterval = 'annual' | 'semiannual' | 'quarterly' | 'target_only';
export type MilestoneSimulationMode = 'add' | 'replace';
export type ContributionScheduleKind = 'monthly' | 'yearly' | 'one_time';

export interface ContributionScheduleItem {
    kind: ContributionScheduleKind;
    amount: number;
    month?: number | null;
    date?: string | null;
    start_date?: string | null;
    end_date?: string | null;
    note?: string | null;
}

export interface MilestoneSimulationRequest {
    basis: MilestoneSimulationBasis;
    interval: MilestoneSimulationInterval;
    mode: MilestoneSimulationMode;
    n_simulations: number;
    annual_return?: number;
    inflation?: number;
    monthly_savings?: number;
    contribution_schedule?: ContributionScheduleItem[];
    allocation_mode?: 'weighted' | 'direct';
}

export interface MilestoneSimulationPreview {
    life_event_id: number;
    basis: MilestoneSimulationBasis;
    interval: MilestoneSimulationInterval;
    mode: MilestoneSimulationMode;
    existing_count: number;
    items: Array<Omit<Milestone, 'id'>>;
}

export interface SimulationScenario {
    id: number;
    life_event_id: number;
    name: string;
    description?: string | null;
    annual_return: number;
    inflation: number;
    monthly_savings?: number | null;
    contribution_schedule: ContributionScheduleItem[];
    allocation_mode: 'weighted' | 'direct';
    created_at?: string | null;
    updated_at?: string | null;
}

export interface SimulationScenarioCreatePayload {
    life_event_id: number;
    name: string;
    description?: string | null;
    annual_return: number;
    inflation: number;
    monthly_savings?: number | null;
    contribution_schedule: ContributionScheduleItem[];
    allocation_mode: 'weighted' | 'direct';
}

export interface SimulationScenarioCompareItem {
    scenario_id: number;
    scenario_name: string;
    target_amount: number;
    years_remaining: number;
    probability: number;
    percentiles: { p10: number; p50: number; p90: number };
    year_by_year: { p10: number[]; p50: number[]; p90: number[] };
    deterministic_yearly: Array<{ year: number; end_balance: number }>;
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
    type: Transaction['type'];
    category?: string | null;
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

export interface RoadmapProjectionPoint {
    year: number;
    p10: number;
    p50: number;
    p90: number;
}

export interface LiabilityDemandPoint {
    year: number;
    cumulative_target: number;
    event_count: number;
}

export interface RoadmapMilestone extends Milestone {
    life_event_name?: string;
}

export interface RoadmapProjection {
    history: NetWorthHistoryPoint[];
    projection: RoadmapProjectionPoint[];
    liability_demand: LiabilityDemandPoint[];
    milestones: RoadmapMilestone[];
    events: LifeEvent[];
    roadmap_progression: 'On Track' | 'At Risk' | 'Off Track';
    roadmap_progression_pct: number;
    params: {
        years: number;
        annual_return: number;
        inflation: number;
        monthly_savings?: number | null;
    };
}

export interface CapsuleHolding {
    id: number;
    capsule_id: number;
    account_id: number;
    account_name?: string | null;
    held_amount: number;
    note?: string | null;
    updated_at?: string | null;
}

export interface Capsule {
    id: number;
    life_event_id?: number | null;
    name: string;
    target_amount: number;
    monthly_contribution: number;
    current_balance: number;
    account_id?: number;
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
    holdings: CapsuleHolding[];
}

export interface CapsuleRule {
    id: number;
    capsule_id: number;
    capsule_name?: string | null;
    trigger_type: Transaction['type'];
    trigger_category?: string | null;
    trigger_description?: string | null;
    source_mode: 'transaction_account' | 'fixed_account';
    source_account_id?: number | null;
    source_account_name?: string | null;
    amount_type: 'fixed' | 'percentage';
    amount_value: number;
    is_active: boolean;
    created_at: string;
}

export interface MonteCarloResult {
    life_event_id: number;
    life_event_name: string;
    target_amount: number;
    years_remaining: number;
    probability: number;
    percentiles: {
        p10: number;
        p50: number;
        p90: number;
    };
    year_by_year: {
        p10: number[];
        p50: number[];
        p90: number[];
    };
    n_simulations: number;
}

export interface BudgetPlan {
    id: number;
    name: string;
    description?: string | null;
    is_default: boolean;
    sort_order: number;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface BudgetPlanCashFlowRow {
    period: string;
    ending_cash: number;
    net_cash: number;
}

export interface BudgetPlanCompareResult {
    plan_id: number;
    plan_name: string;
    cash_flow: BudgetPlanCashFlowRow[];
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
