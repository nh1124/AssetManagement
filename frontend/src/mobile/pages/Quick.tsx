import { useEffect, useMemo, useState } from 'react';
import { Check, Loader2 } from 'lucide-react';
import {
    createTransaction,
    getAccounts,
    getAnalysisSummary,
    getProfitLoss,
    getTransactionsPage,
} from '../../api';
import { useToast } from '../../components/Toast';
import { useClient } from '../../context/ClientContext';
import type { Account, AnalysisSummary, Transaction } from '../../types';
import { formatCurrency } from '../../utils/currency';

interface ProfitLossSnapshot {
    net_profit_loss?: number;
    total_income?: number;
    total_expense?: number;
}

type LanguageCode = 'ja' | 'en';
type EntryKind = 'expense' | 'income' | 'transfer';

// What each kind of entry moves: the credit side (from) and the debit side (to).
const ENTRY_KINDS: Array<{
    value: EntryKind;
    label: Record<LanguageCode, string>;
    from: Record<LanguageCode, string>;
    to: Record<LanguageCode, string>;
    fromTypes: string[];
    toTypes: string[];
}> = [
    {
        value: 'expense', label: { ja: '支出', en: 'Expense' },
        from: { ja: '支払元', en: 'From' }, to: { ja: '費目', en: 'Expense' },
        fromTypes: ['asset', 'liability'], toTypes: ['expense'],
    },
    {
        value: 'income', label: { ja: '収入', en: 'Income' },
        from: { ja: '収入元', en: 'Income Source' }, to: { ja: '入金先', en: 'Deposit' },
        fromTypes: ['income'], toTypes: ['asset', 'liability'],
    },
    {
        value: 'transfer', label: { ja: '移動', en: 'Transfer' },
        from: { ja: '移動元', en: 'From' }, to: { ja: '移動先', en: 'To' },
        fromTypes: ['asset', 'liability'], toTypes: ['asset', 'liability'],
    },
];

interface Entry {
    amount: string;
    description: string;
    date: string;
    fromId: string;
    toId: string;
}

const todayIso = () => new Date().toISOString().split('T')[0];

const monthStartIso = () => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0];
};

const accountsOf = (accounts: Account[], types: string[]) =>
    accounts.filter((account) => types.includes(account.account_type));

const blankEntry = (from: Account[], to: Account[]): Entry => ({
    amount: '',
    description: '',
    date: todayIso(),
    fromId: from[0] ? String(from[0].id) : '',
    toId: to[0] ? String(to[0].id) : '',
});

export default function MobileQuickPage() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [summary, setSummary] = useState<AnalysisSummary | null>(null);
    const [pl, setPl] = useState<ProfitLossSnapshot | null>(null);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [recentTransactions, setRecentTransactions] = useState<Transaction[]>([]);
    const [kind, setKind] = useState<EntryKind>('expense');

    const currentCurrency = currentClient?.general_settings?.currency || 'JPY';
    const language: LanguageCode = String(currentClient?.general_settings?.language || 'ja').toLowerCase().startsWith('ja') ? 'ja' : 'en';

    const loadQuickData = async () => {
        try {
            const [summaryData, plData, accountData, txData] = await Promise.all([
                getAnalysisSummary(),
                getProfitLoss(undefined, undefined, false, monthStartIso(), todayIso()),
                getAccounts(),
                getTransactionsPage({ limit: 6, offset: 0 }),
            ]);
            setSummary(summaryData);
            setPl(plData);
            setAccounts(accountData);
            setRecentTransactions(txData.items);
        } catch {
            showToast('Failed to load mobile quick data', 'error');
        }
    };

    useEffect(() => {
        loadQuickData();
    }, []);

    return (
        <div className="space-y-4 p-3 pt-4">
            <section className="grid grid-cols-2 gap-2">
                <MetricTile
                    label="Logical"
                    value={formatCurrency(summary?.logical_balance ?? summary?.effective_cash ?? summary?.net_worth ?? 0, currentCurrency)}
                />
                <MetricTile
                    label="This Month"
                    value={formatCurrency(pl?.net_profit_loss ?? summary?.monthly_pl ?? 0, currentCurrency)}
                    tone={(pl?.net_profit_loss ?? summary?.monthly_pl ?? 0) >= 0 ? 'good' : 'bad'}
                />
            </section>

            <section className="space-y-3">
                <div className="mx-auto flex w-fit rounded-full border border-slate-800 bg-slate-900/80 p-1">
                    {ENTRY_KINDS.map((option) => (
                        <button
                            key={option.value}
                            type="button"
                            onClick={() => setKind(option.value)}
                            className={`h-8 rounded-full px-4 text-xs transition-colors ${kind === option.value ? 'bg-emerald-500 text-slate-950' : 'text-slate-500'}`}
                        >
                            {option.label[language]}
                        </button>
                    ))}
                </div>
                <EntryForm
                    kind={kind}
                    accounts={accounts}
                    currentCurrency={currentCurrency}
                    language={language}
                    onSaved={loadQuickData}
                />
            </section>

            <section className="space-y-2">
                <h2 className="text-sm font-medium text-slate-100">Recent</h2>
                {recentTransactions.length === 0 ? (
                    <EmptyState text="No recent transactions." />
                ) : (
                    <div className="divide-y divide-slate-800 border border-slate-800 bg-slate-900/60">
                        {recentTransactions.map((tx) => (
                            <div key={tx.id} className="flex items-center justify-between gap-3 px-3 py-2">
                                <div className="min-w-0">
                                    <p className="truncate text-sm text-slate-100">{tx.description}</p>
                                    <p className="text-[10px] text-slate-500">{tx.date}</p>
                                </div>
                                <p className="shrink-0 font-mono-nums text-xs text-slate-200">
                                    {formatCurrency(tx.amount, tx.currency)}
                                </p>
                            </div>
                        ))}
                    </div>
                )}
            </section>
        </div>
    );
}

function MetricTile({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: 'neutral' | 'good' | 'warn' | 'bad' }) {
    const toneClass = {
        neutral: 'text-slate-100',
        good: 'text-emerald-300',
        warn: 'text-amber-300',
        bad: 'text-rose-300',
    }[tone];

    return (
        <div className="min-w-0 border border-slate-800 bg-slate-900/70 p-2">
            <p className="truncate text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
            <p className={`mt-1 truncate font-mono-nums text-sm ${toneClass}`}>{value}</p>
        </div>
    );
}

function EmptyState({ text }: { text: string }) {
    return (
        <div className="border border-dashed border-slate-800 bg-slate-900/40 px-3 py-4 text-sm text-slate-500">
            {text}
        </div>
    );
}

function EntryForm({
    kind,
    accounts,
    currentCurrency,
    language,
    onSaved,
}: {
    kind: EntryKind;
    accounts: Account[];
    currentCurrency: string;
    language: LanguageCode;
    onSaved: () => Promise<void>;
}) {
    const { showToast } = useToast();
    const rules = ENTRY_KINDS.find((option) => option.value === kind) ?? ENTRY_KINDS[0];
    const fromAccounts = useMemo(() => accountsOf(accounts, rules.fromTypes), [accounts, rules]);
    const toAccounts = useMemo(() => accountsOf(accounts, rules.toTypes), [accounts, rules]);
    const [entry, setEntry] = useState<Entry>(() => blankEntry(fromAccounts, toAccounts));
    const [isSaving, setIsSaving] = useState(false);
    const isJapanese = language === 'ja';

    useEffect(() => {
        setEntry(blankEntry(fromAccounts, toAccounts));
    }, [fromAccounts, toAccounts]);

    const save = async () => {
        const amount = Number(entry.amount || 0);
        if (!amount || amount <= 0) {
            showToast(isJapanese ? '金額を入力してください' : 'Amount is required', 'warning');
            return;
        }
        if (!entry.fromId || !entry.toId) {
            showToast(isJapanese ? '口座を選んでください' : 'Choose both accounts', 'warning');
            return;
        }

        setIsSaving(true);
        try {
            await createTransaction({
                date: entry.date,
                description: entry.description.trim() || rules.label[language],
                amount,
                currency: currentCurrency,
                from_account_id: Number(entry.fromId),
                to_account_id: Number(entry.toId),
            });
            showToast(isJapanese ? '保存しました' : 'Saved', 'success');
            setEntry(blankEntry(fromAccounts, toAccounts));
            await onSaved();
        } catch {
            showToast('Failed to save quick entry', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="space-y-3 border border-slate-800 bg-slate-900/40 p-3">
            <label className="block">
                <span className="text-[10px] uppercase tracking-wide text-slate-500">Amount</span>
                <input
                    type="number"
                    inputMode="decimal"
                    value={entry.amount}
                    onChange={(event) => setEntry({ ...entry, amount: event.target.value })}
                    className="mt-1 h-12 w-full border border-slate-700 bg-slate-900 px-3 text-lg font-mono-nums text-slate-100 outline-none focus:border-emerald-500"
                    placeholder="0"
                />
            </label>
            <label className="block">
                <span className="text-[10px] uppercase tracking-wide text-slate-500">Memo</span>
                <input
                    value={entry.description}
                    onChange={(event) => setEntry({ ...entry, description: event.target.value })}
                    className="mt-1 h-11 w-full border border-slate-700 bg-slate-900 px-3 text-sm text-slate-100 outline-none focus:border-emerald-500"
                    placeholder={rules.label[language]}
                />
            </label>
            <AccountPicker
                label={isJapanese ? `貸方 / ${rules.from.ja}` : `Credit / ${rules.from.en}`}
                accounts={fromAccounts}
                selected={entry.fromId}
                onSelect={(id) => setEntry({ ...entry, fromId: id })}
            />
            <AccountPicker
                label={isJapanese ? `借方 / ${rules.to.ja}` : `Debit / ${rules.to.en}`}
                accounts={toAccounts}
                selected={entry.toId}
                onSelect={(id) => setEntry({ ...entry, toId: id })}
            />
            <label className="block">
                <span className="text-[10px] uppercase tracking-wide text-slate-500">Date</span>
                <input
                    type="date"
                    value={entry.date}
                    onChange={(event) => setEntry({ ...entry, date: event.target.value })}
                    className="mt-1 h-11 w-full border border-slate-700 bg-slate-900 px-3 text-sm text-slate-100 outline-none focus:border-emerald-500"
                />
            </label>
            <button
                type="button"
                onClick={save}
                disabled={isSaving}
                className="flex h-12 w-full items-center justify-center gap-2 bg-emerald-600 text-sm font-semibold text-white disabled:opacity-50"
            >
                {isSaving ? <Loader2 size={17} className="animate-spin" /> : <Check size={17} />}
                Save
            </button>
        </div>
    );
}

function AccountPicker({
    label,
    accounts,
    selected,
    onSelect,
}: {
    label: string;
    accounts: Account[];
    selected: string;
    onSelect: (id: string) => void;
}) {
    return (
        <div>
            <span className="mb-1 block text-[10px] uppercase tracking-wide text-slate-500">{label}</span>
            <div className="edge-fade-x scrollbar-none flex gap-2 overflow-x-auto pb-1">
                {accounts.map((account) => {
                    const name = account.name.replace(/_/g, ' ');
                    const isSelected = selected === String(account.id);
                    return (
                        <button
                            key={account.id}
                            type="button"
                            onClick={() => onSelect(String(account.id))}
                            className={`h-10 max-w-[12rem] shrink-0 truncate border px-3 text-xs ${isSelected
                                ? 'border-emerald-500 bg-emerald-950/30 text-emerald-200'
                                : 'border-slate-700 bg-slate-900 text-slate-400'
                                }`}
                            title={name}
                        >
                            {name}
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
