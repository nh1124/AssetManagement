import type { LifeEventKind } from '../../../types';
import { formatCurrency } from '../../../utils/currency';

/** The four kinds of life event, in the words every goal screen uses. */
export const KIND_LABELS: Record<LifeEventKind, string> = { expense: '支出', income: '収入', borrowing: '借入', repayment: '返済' };

/** An event's amount as it reads in a table: a repayment is a monthly payment repeated. */
export function eventAmount(event: { direction: LifeEventKind; target_amount: number; repeat_count?: number | null }, currency: string): string {
    const amount = formatCurrency(event.target_amount, currency);
    if (event.direction === 'repayment') return `月 ${amount} × ${event.repeat_count ?? 1}回`;
    return event.direction === 'income' || event.direction === 'borrowing' ? `+${amount}` : amount;
}
