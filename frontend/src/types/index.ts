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
    from_account_name?: string;
    to_account_name?: string;
}

export type AccountRole = 'defense' | 'growth' | 'earmarked' | 'operating' | 'unassigned';

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

export interface GoalAllocation {
    id: number;
    life_event_id: number;
    account_id: number;
    allocation_percentage: number;
    account_name?: string;
    account_balance?: number;
    expected_return?: number;
}

export interface RoadmapEntry {
    year: number;
    start_balance: number;
    contribution: number;
    investment_gain: number;
    end_balance: number;
    goal_coverage: number;
}

export interface LifeEvent {
    id: number;
    name: string;
    target_date: string;
    target_amount: number;
    priority: 1 | 2 | 3;
    note?: string | null;
    created_at?: string;
    allocations: GoalAllocation[];
    current_funded?: number;
    projected_amount?: number;
    gap?: number;
    weighted_return?: number;
    status?: 'On Track' | 'At Risk' | 'Off Track' | 'Achieved' | 'Missed' | 'Not Started';
    progress_percentage?: number;
    years_remaining?: number;
    roadmap?: RoadmapEntry[];
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
    purchase_price?: number;
    purchase_date?: string;
    monthly_cost: number;
    next_purchase_date?: string;
}

export interface MonthlyBudget {
    id: string;
    account_id: number;
    account_name: string;
    account_type: string;
    target_period: string;
    amount: number;
    actual_spending: number;
    variance: number;
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
    type: Transaction['type'];
    from_account_id?: number | null;
    to_account_id?: number | null;
    frequency: 'Monthly' | 'Yearly';
    day_of_month: number;
    month_of_year?: number | null;
    next_due_date?: string | null;
    is_active: boolean;
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

export interface NetWorthHistoryPoint {
    period: string;
    net_worth: number;
    assets: number;
    liabilities: number;
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
