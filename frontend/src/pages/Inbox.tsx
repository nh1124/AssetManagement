import { useEffect, useMemo, useState } from 'react';
import { Calendar, Check, Edit, RefreshCw, SkipForward } from 'lucide-react';
import {
    getAccounts,
    getDueRecurringTransactions,
    getTransactions,
    processRecurringTransaction,
    skipRecurringTransaction,
} from '../api';
import { useToast } from '../components/Toast';
import type { RecurringTransaction, Transaction } from '../types';

interface InboxProps {
    onNavigate: (page: string) => void;
}

interface AccountItem {
    id: number;
    name: string;
}

export default function Inbox({ onNavigate }: InboxProps) {
    const [dueItems, setDueItems] = useState<RecurringTransaction[]>([]);
    const [recentTransactions, setRecentTransactions] = useState<Transaction[]>([]);
    const [accounts, setAccounts] = useState<AccountItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [processingId, setProcessingId] = useState<number | null>(null);
    const { showToast } = useToast();

    const accountNames = useMemo(
        () => new Map(accounts.map((account) => [account.id, account.name])),
        [accounts]
    );

    const fetchInbox = async () => {
        setLoading(true);
        try {
            const end = new Date();
            const start = new Date();
            start.setDate(end.getDate() - 7);
            const [due, txs, accountData] = await Promise.all([
                getDueRecurringTransactions(),
                getTransactions(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10)),
                getAccounts(),
            ]);
            setDueItems(due);
            setRecentTransactions(txs.slice(0, 8));
            setAccounts(accountData);
        } catch (error) {
            console.error('Failed to fetch inbox:', error);
            showToast('Failed to load inbox', 'error');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchInbox();
    }, []);

    const handleApprove = async (id: number) => {
        setProcessingId(id);
        try {
            await processRecurringTransaction(id);
            showToast('Recurring transaction approved', 'success');
            await fetchInbox();
        } catch (error) {
            showToast('Failed to approve recurring transaction', 'error');
        } finally {
            setProcessingId(null);
        }
    };

    const handleSkip = async (id: number) => {
        setProcessingId(id);
        try {
            await skipRecurringTransaction(id);
            showToast('Recurring transaction skipped', 'info');
            await fetchInbox();
        } catch (error) {
            showToast('Failed to skip recurring transaction', 'error');
        } finally {
            setProcessingId(null);
        }
    };

    const handleEditRule = () => {
        localStorage.setItem('finance_journal_tab', 'recurring');
        onNavigate('journal');
    };

    const formatCurrency = (value: number) => `¥${Math.round(value).toLocaleString()}`;
    const accountName = (id?: number | null) => (id ? accountNames.get(id) || `#${id}` : '-');

    return (
        <div className="h-full overflow-auto p-4 space-y-4">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-sm font-semibold text-slate-100">Inbox</h1>
                    <p className="text-xs text-slate-500">Daily workflow for due recurring transactions.</p>
                </div>
                <button
                    onClick={fetchInbox}
                    disabled={loading}
                    className="p-1.5 hover:bg-slate-800 text-slate-400 flex items-center gap-1 text-xs disabled:opacity-50"
                >
                    <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                    Refresh
                </button>
            </div>

            <section className="border border-slate-800 bg-slate-900/50">
                <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Calendar size={14} className="text-cyan-400" />
                        <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Due Approval</h2>
                    </div>
                    <span className={`text-[10px] px-2 py-1 border ${dueItems.length > 0
                        ? 'text-rose-400 border-rose-800 bg-rose-950/30'
                        : 'text-emerald-400 border-emerald-800 bg-emerald-950/30'
                        }`}>
                        {dueItems.length} due
                    </span>
                </div>

                <div className="p-4">
                    {dueItems.length === 0 ? (
                        <div className="border border-emerald-900 bg-emerald-950/20 p-4 text-xs text-emerald-300">
                            All recurring transactions are handled.
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                            {dueItems.map((item) => (
                                <div key={item.id} className="border border-slate-700 bg-slate-800/30 p-3">
                                    <div className="flex items-start justify-between gap-3">
                                        <div>
                                            <p className="text-sm font-medium text-slate-100">{item.name}</p>
                                            <p className="text-[10px] text-slate-500 mt-1">
                                                {item.type} · {accountName(item.from_account_id)} &rarr; {accountName(item.to_account_id)}
                                            </p>
                                            <p className="text-[10px] text-slate-500">Due: {item.next_due_date || '-'}</p>
                                        </div>
                                        <p className="font-mono-nums text-sm text-slate-100 whitespace-nowrap">
                                            {formatCurrency(item.amount)}
                                        </p>
                                    </div>
                                    <div className="grid grid-cols-3 gap-2 mt-3">
                                        <button
                                            onClick={() => handleApprove(item.id)}
                                            disabled={processingId === item.id}
                                            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white py-2 text-[10px] font-bold flex items-center justify-center gap-1"
                                        >
                                            <Check size={12} />
                                            Approve
                                        </button>
                                        <button
                                            onClick={() => handleSkip(item.id)}
                                            disabled={processingId === item.id}
                                            className="bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-100 py-2 text-[10px] font-bold flex items-center justify-center gap-1"
                                        >
                                            <SkipForward size={12} />
                                            Skip
                                        </button>
                                        <button
                                            onClick={handleEditRule}
                                            className="bg-cyan-700 hover:bg-cyan-600 text-white py-2 text-[10px] font-bold flex items-center justify-center gap-1"
                                        >
                                            <Edit size={12} />
                                            Rule
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </section>

            <section className="border border-slate-800 bg-slate-900/50">
                <div className="px-4 py-3 border-b border-slate-800">
                    <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Recent 7 Days</h2>
                </div>
                <div className="divide-y divide-slate-800">
                    {recentTransactions.length === 0 ? (
                        <p className="p-4 text-xs text-slate-500">No transactions in the last 7 days.</p>
                    ) : (
                        recentTransactions.map((tx) => (
                            <div key={tx.id} className="grid grid-cols-[96px_1fr_auto] gap-3 p-3 text-xs">
                                <span className="text-slate-500">{tx.date}</span>
                                <span className="text-slate-300">{tx.description}</span>
                                <span className={`font-mono-nums ${tx.type === 'Income' ? 'text-emerald-400' : 'text-slate-200'}`}>
                                    {tx.type === 'Income' ? '+' : '-'}{formatCurrency(tx.amount)}
                                </span>
                            </div>
                        ))
                    )}
                </div>
            </section>
        </div>
    );
}
