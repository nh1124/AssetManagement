export interface Asset {
    id: number;
    name: string;
    category: string;
    value: number;
}

export interface Liability {
    id: number;
    name: string;
    category: string;
    lender?: string;
    total_borrowed: number;
    amount_repaid: number;
    balance: number;
}

export interface Transaction {
    id: number;
    date: string;
    description: string;
    amount: number;
    type: 'Income' | 'Expense' | 'Transfer';
    category?: string;
    currency: string;
    from_account?: string;
    to_account?: string;
}

export interface LifeEvent {
    id: number;
    name: string;
    target_date: string;
    target_amount: number;
    funded_amount: number;
    priority: 'high' | 'medium' | 'low';
    allocated_asset_id?: number;
}

export interface Product {
    id: number;
    name: string;
    category: string;
    location?: string;
    last_unit_price: number;
    frequency_days: number;
    last_purchase_date?: string;
    is_asset: boolean;
    lifespan_months?: number;
}

export interface Budget {
    id: number;
    category: string;
    proposed_amount: number;
    current_spending: number;
    month: string;
    derived_from?: string;
}

export interface AnalysisSummary {
    net_worth: number;
    monthly_pl: number;
    liability_total: number;
    goal_probability: number;
    total_goal_amount: number;
    total_funded: number;
    effective_cash?: number;
}
