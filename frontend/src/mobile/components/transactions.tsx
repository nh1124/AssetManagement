import { ArrowLeftRight, ArrowDownLeft, ArrowUpRight, Layers } from 'lucide-react';
import type { Account, Transaction } from '../../types';
import { formatCurrency } from '../../utils/currency';
import { direction } from '../direction';
import { focusRing } from './ui';

const ICONS = { expense: ArrowUpRight, income: ArrowDownLeft, transfer: ArrowLeftRight, compound: Layers };
const TONES = {
    expense: 'bg-red-50 text-[var(--studio-danger)]', income: 'bg-emerald-50 text-[var(--studio-positive)]',
    transfer: 'bg-[var(--studio-accent-soft)] text-[var(--studio-accent)]', compound: 'bg-[var(--studio-bg)] text-[var(--studio-text-muted)]',
};

/** One record in a list: what it was, where the money went, and how much. */
export function TransactionRow({ transaction, types, currency, onOpen, showDate = true }: {
    transaction: Transaction; types: Map<number, Account['account_type']>; currency: string; onOpen: (transaction: Transaction) => void; showDate?: boolean;
}) {
    const kind = direction(transaction, types);
    const Icon = ICONS[kind];
    const route = [transaction.from_account_name, transaction.to_account_name].filter(Boolean).join(' → ') || '複数の口座';
    const title = transaction.description || (kind === 'expense' ? transaction.to_account_name : kind === 'income' ? transaction.from_account_name : route) || '内容なし';
    const sign = kind === 'expense' ? '−' : kind === 'income' ? '+' : '';
    return <button type="button" onClick={() => onOpen(transaction)} className={`flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left active:bg-[var(--studio-accent-soft)] ${focusRing}`}>
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${TONES[kind]}`}><Icon size={17} aria-hidden /></span>
        <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{title}</span>
            <span className="block truncate text-xs text-[var(--studio-text-muted)]">{showDate ? `${transaction.date.slice(5).replace('-', '/')}・` : ''}{route}</span>
        </span>
        <span className={`shrink-0 text-sm font-semibold tabular-nums ${kind === 'income' ? 'text-[var(--studio-positive)]' : ''}`}>{sign}{formatCurrency(transaction.amount, transaction.currency || currency)}</span>
    </button>;
}
