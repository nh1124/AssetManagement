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
    balance: number;
}

export interface Transaction {
    id: number;
    date: string;
    description: string;
    amount: number;
    type: 'Income' | 'Expense' | 'Transfer';
    asset_id?: number;
    liability_id?: number;
}

export interface LifeEvent {
    id: number;
    name: string;
    target_date: string;
    target_amount: number;
}

export interface AnalysisSummary {
    net_worth: number;
    monthly_pl: number;
    liability_total: number;
}
