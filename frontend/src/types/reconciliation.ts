export interface ReconciliationComparison {
    account: { id: number; name: string; account_type: string };
    as_of: string;
    ledger_minor: number;
    statement_minor: number;
    difference_minor: number;
    currency: string;
    capsule_claims: Array<{ capsule_id: number; capsule_name: string; claimed_minor: number }>;
}

export interface ReconciliationAdjustment {
    as_of: string;
    statement: string;
    currency: string;
    counter_account_id: number;
    capsule_id?: number;
    note?: string;
    expected_ledger_minor: number;
}
