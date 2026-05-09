import { useEffect, useMemo, useState } from 'react';
import { Filter, Loader2, RefreshCw, Search } from 'lucide-react';
import { getTransactionsPage, type TransactionQuery } from '../../api';
import { useToast } from '../../components/Toast';
import type { Transaction } from '../../types';
import { formatCurrency } from '../../utils/currency';

const PAGE_SIZE = 20;
const TYPES = ['All', 'Expense', 'Income', 'Transfer', 'LiabilityPayment', 'CreditExpense'] as const;

export default function MobileJournalPage() {
    const { showToast } = useToast();
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [total, setTotal] = useState(0);
    const [query, setQuery] = useState('');
    const [type, setType] = useState<(typeof TYPES)[number]>('All');
    const [isLoading, setIsLoading] = useState(false);

    const filters = useMemo<TransactionQuery>(() => ({
        q: query.trim() || undefined,
        type: type === 'All' ? undefined : type,
        limit: PAGE_SIZE,
        offset: 0,
    }), [query, type]);

    const loadTransactions = async (nextOffset = 0) => {
        setIsLoading(true);
        try {
            const result = await getTransactionsPage({ ...filters, offset: nextOffset });
            setTotal(result.total);
            setTransactions((prev) => nextOffset === 0 ? result.items : [...prev, ...result.items]);
        } catch {
            showToast('Failed to load mobile journal', 'error');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        loadTransactions(0);
    }, [filters]);

    return (
        <div className="space-y-4 p-3">
            <section className="flex items-center justify-between">
                <div>
                    <p className="text-[10px] uppercase tracking-wide text-slate-500">Mobile Journal</p>
                    <h1 className="text-xl font-semibold text-slate-50">Transactions</h1>
                </div>
                <button
                    type="button"
                    onClick={() => loadTransactions(0)}
                    className="flex h-10 w-10 items-center justify-center border border-slate-800 bg-slate-900 text-slate-300"
                    aria-label="Refresh journal"
                >
                    <RefreshCw size={17} className={isLoading ? 'animate-spin' : ''} />
                </button>
            </section>

            <section className="space-y-2">
                <label className="flex h-11 items-center gap-2 border border-slate-800 bg-slate-900 px-3">
                    <Search size={16} className="text-slate-500" />
                    <input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Search memo, category, account"
                        className="min-w-0 flex-1 bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
                    />
                </label>
                <div className="edge-fade-x scrollbar-none flex gap-2 overflow-x-auto pb-1">
                    {TYPES.map((item) => (
                        <button
                            key={item}
                            type="button"
                            onClick={() => setType(item)}
                            className={`shrink-0 border px-3 py-2 text-xs ${type === item
                                ? 'border-emerald-500 bg-emerald-950/30 text-emerald-200'
                                : 'border-slate-800 bg-slate-900 text-slate-400'
                                }`}
                        >
                            {item}
                        </button>
                    ))}
                </div>
            </section>

            <section className="space-y-2">
                <div className="flex items-center justify-between text-xs text-slate-500">
                    <span className="flex items-center gap-1"><Filter size={13} /> {total} records</span>
                    <span>{transactions.length}/{total}</span>
                </div>

                {transactions.length === 0 && !isLoading ? (
                    <div className="border border-dashed border-slate-800 bg-slate-900/40 px-3 py-5 text-sm text-slate-500">
                        No transactions match this filter.
                    </div>
                ) : (
                    <div className="divide-y divide-slate-800 border border-slate-800 bg-slate-900/60">
                        {transactions.map((tx) => (
                            <TransactionRow key={tx.id} tx={tx} />
                        ))}
                    </div>
                )}

                {transactions.length < total && (
                    <button
                        type="button"
                        onClick={() => loadTransactions(transactions.length)}
                        disabled={isLoading}
                        className="flex h-11 w-full items-center justify-center gap-2 border border-slate-800 bg-slate-900 text-sm text-slate-300 disabled:opacity-50"
                    >
                        {isLoading ? <Loader2 size={15} className="animate-spin" /> : null}
                        Load more
                    </button>
                )}
            </section>
        </div>
    );
}

function TransactionRow({ tx }: { tx: Transaction }) {
    const isIncome = tx.type === 'Income';
    const isExpense = tx.type === 'Expense' || tx.type === 'CreditExpense';

    return (
        <article className="px-3 py-3">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100">{tx.description || tx.category || tx.type}</p>
                    <p className="mt-1 text-[10px] text-slate-500">
                        {tx.date} - {tx.type}{tx.category ? ` - ${tx.category}` : ''}
                    </p>
                    {(tx.from_account_name || tx.to_account_name) && (
                        <p className="mt-1 truncate text-[10px] text-slate-600">
                            {tx.from_account_name || 'source'} to {tx.to_account_name || 'target'}
                        </p>
                    )}
                </div>
                <p className={`shrink-0 font-mono-nums text-sm ${isIncome ? 'text-emerald-300' : isExpense ? 'text-rose-300' : 'text-slate-200'}`}>
                    {isIncome ? '+' : isExpense ? '-' : ''}{formatCurrency(tx.amount, tx.currency)}
                </p>
            </div>
        </article>
    );
}
