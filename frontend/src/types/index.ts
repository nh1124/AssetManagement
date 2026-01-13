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
    source_account_id?: number;
    destination_account_id?: number;
    asset_id?: number;
    liability_id?: number;
}

export interface LifeEvent {
    id: number;
    name: string;
    target_date: string;
    target_amount: number;
}

export interface AssetGoalMapping {
    id: number;
    asset_id: number;
    life_event_id: number;
    allocation_pct: number;
}

export interface Product {
    id: number;
    name: string;
    category: string;
    last_price: number;
    frequency_days: number;
    last_purchase_date?: string;
}

export interface Budget {
    id: number;
    category: string;
    proposed_amount: number;
    current_spending: number;
    month: string;
    ai_suggestion?: string;
}

export interface AnalysisSummary {
    net_worth: number;
    monthly_pl: number;
    liability_total: number;
    cfo_briefing?: string;
}
