import api from './index';
import type { ReconciliationAdjustment, ReconciliationComparison, Transaction } from '../types';

export async function compareStatement(accountId: number, asOf: string, statement: string, currency: string): Promise<ReconciliationComparison> {
    const response = await api.get<ReconciliationComparison>(`/analysis/reconcile/${accountId}`, {
        params: { as_of: asOf, statement, currency },
    });
    return response.data;
}

export async function postReconciliationAdjustment(accountId: number, payload: ReconciliationAdjustment): Promise<Transaction> {
    const response = await api.post<Transaction>(`/analysis/reconcile/${accountId}/adjust`, payload);
    return response.data;
}
