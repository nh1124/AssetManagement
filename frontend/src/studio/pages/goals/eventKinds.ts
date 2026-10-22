import type { LifeEventKind } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { labels, tr } from '../../i18n';

/** The four kinds of life event, in the words every goal screen uses. */
export const KIND_LABELS = labels<LifeEventKind>({ expense: ['支出', 'Expense'], income: ['収入', 'Income'], borrowing: ['借入', 'Borrowing'], repayment: ['返済', 'Repayment'] });

/** An event's amount as it reads in a table: a repayment is a monthly payment repeated. */
export function eventAmount(event: { direction: LifeEventKind; target_amount: number; repeat_count?: number | null }, currency: string): string {
    const amount = formatCurrency(event.target_amount, currency);
    if (event.direction === 'repayment') return tr(`月 ${amount} × ${event.repeat_count ?? 1}回`, `${amount} a month × ${event.repeat_count ?? 1}`);
    return event.direction === 'income' || event.direction === 'borrowing' ? `+${amount}` : amount;
}
