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

export interface AnalysisSummary {
    net_worth: number;
    monthly_pl: number;
    liability_total: number;
    goal_probability: number;
    total_goal_amount: number;
    total_funded: number;
    effective_cash?: number;
    cfo_briefing?: string;
    savings_rate?: number;
    idle_money_rate?: number;
    liquidity_coverage_ratio?: number;
    runway_months?: number;
    monthly_transaction_count?: number;
    total_goal_count?: number;
    budget_usage_rate?: number;
}

export interface Milestone {
    id: number;
    life_event_id?: number;
    date: string;
    target_amount: number;
    note?: string;
}

export interface Capsule {
    id: number;
    name: string;
    target_amount: number;
    monthly_contribution: number;
    current_balance: number;
    account_id?: number;
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
