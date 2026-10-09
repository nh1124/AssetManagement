import type { Transaction, TransactionLegRead } from '../../types';

/** Which way money went, read from the entry's legs.
 *
 *  This replaces the transaction type, which the ledger no longer stores. The
 *  accounts say it directly: a debit on an expense account is money going out,
 *  a credit on an income account is money coming in, and anything else is a
 *  movement between accounts you already own.
 *
 *  Older rows and compound entries are both handled: it only ever looks at the
 *  legs, of which there are always at least two.
 */
export type Direction = 'in' | 'out' | 'move';

const isRead = (leg: Transaction['legs'] extends (infer L)[] | undefined ? L : never): leg is TransactionLegRead =>
    typeof leg === 'object' && leg !== null && 'account_type' in leg;

export const transactionDirection = (tx: Pick<Transaction, 'legs'>): Direction => {
    const legs = tx.legs ?? [];
    let sawExpense = false;
    let sawIncome = false;
    let sawLiabilityDebit = false;

    for (const leg of legs) {
        if (!isRead(leg)) continue;
        const debit = leg.debit ?? 0;
        const credit = leg.credit ?? 0;
        if (debit > 0 && leg.account_type === 'expense') sawExpense = true;
        if (credit > 0 && leg.account_type === 'income') sawIncome = true;
        if (debit > 0 && leg.account_type === 'liability') sawLiabilityDebit = true;
    }

    // An entry can be both -- a payroll run credits income and debits a stock
    // plan -- and then the money arriving is the headline.
    if (sawIncome) return 'in';
    if (sawExpense) return 'out';
    // Paying down a liability is money leaving, even though no expense is involved.
    if (sawLiabilityDebit) return 'out';
    return 'move';
};

export const directionSign = (direction: Direction): string =>
    direction === 'in' ? '+' : direction === 'out' ? '-' : '';

export const directionClass = (direction: Direction): string =>
    direction === 'in' ? 'text-emerald-500' : direction === 'out' ? 'text-rose-500' : 'text-cyan-500';
