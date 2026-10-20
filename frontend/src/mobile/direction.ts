import type { Account, Transaction } from '../types';

export type Direction = 'expense' | 'income' | 'transfer' | 'compound';

/** 支出 when money lands on an expense, 収入 when it comes from income, else 振替; several legs are 複合. */
export function direction(transaction: Transaction, types: Map<number, Account['account_type']>): Direction {
    const to = transaction.to_account_id ? types.get(transaction.to_account_id) : undefined;
    const from = transaction.from_account_id ? types.get(transaction.from_account_id) : undefined;
    if (!transaction.to_account_id || !transaction.from_account_id) return to === 'expense' ? 'expense' : from === 'income' ? 'income' : 'compound';
    if (to === 'expense') return 'expense';
    if (from === 'income') return 'income';
    return 'transfer';
}
