import { useEffect, useMemo, useState } from 'react';
import {
    ArrowRightLeft,
    Check,
    ChevronRight,
    Loader2,
    RefreshCw,
    SkipForward,
    X,
} from 'lucide-react';
import {
    applyReviewAction,
    createTransactionBatch,
    getAccounts,
    getAnalysisSummary,
    getDueRecurringTransactions,
    getMonthlyActions,
    getProfitLoss,
    getQuickTemplates,
    getTransactionsPage,
    processRecurringTransaction,
    skipRecurringTransaction,
    skipReviewAction,
} from '../../api';
import { useToast } from '../../components/Toast';
import { useClient } from '../../context/ClientContext';
import type { Account, AnalysisSummary, MonthlyAction, QuickTemplate, RecurringTransaction, Transaction } from '../../types';
import { formatCurrency } from '../../utils/currency';
import {
    buildQuickTransactions,
    QUICK_KIND_RULES,
    quickKindLabel,
    quickPresetFor,
    type AccountItem,
    type QuickEntry,
    type QuickTemplateKind,
} from '../../features/journal/quick';

interface ProfitLossSnapshot {
    net_profit_loss?: number;
    total_income?: number;
    total_expense?: number;
}

const todayIso = () => new Date().toISOString().split('T')[0];

const monthStartIso = () => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0];
};

const toAccountItems = (accounts: Account[]): AccountItem[] =>
    accounts.map((account) => ({
        id: account.id,
        name: account.name,
        account_type: account.account_type,
        balance: account.balance,
    }));

const pendingActions = (actions: MonthlyAction[]) =>
    actions.filter((action) => action.status === 'pending').slice(0, 5);

export default function MobileQuickPage() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [summary, setSummary] = useState<AnalysisSummary | null>(null);
    const [pl, setPl] = useState<ProfitLossSnapshot | null>(null);
    const [templates, setTemplates] = useState<QuickTemplate[]>([]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [dueRecurring, setDueRecurring] = useState<RecurringTransaction[]>([]);
    const [actions, setActions] = useState<MonthlyAction[]>([]);
    const [recentTransactions, setRecentTransactions] = useState<Transaction[]>([]);
    const [selectedTemplate, setSelectedTemplate] = useState<QuickTemplate | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [busyKey, setBusyKey] = useState<string | null>(null);

    const currentCurrency = currentClient?.general_settings?.currency || 'JPY';
    const approvalCount = dueRecurring.length + pendingActions(actions).length;

    const loadQuickData = async () => {
        setIsLoading(true);
        try {
            const [summaryData, plData, templateData, accountData, recurringData, actionData, txData] = await Promise.all([
                getAnalysisSummary(),
                getProfitLoss(undefined, undefined, false, monthStartIso(), todayIso()),
                getQuickTemplates(),
                getAccounts(),
                getDueRecurringTransactions(),
                getMonthlyActions(),
                getTransactionsPage({ limit: 6, offset: 0 }),
            ]);
            setSummary(summaryData);
            setPl(plData);
            setTemplates(templateData.filter((template) => template.is_active).slice(0, 12));
            setAccounts(accountData);
            setDueRecurring(recurringData);
            setActions(actionData);
            setRecentTransactions(txData.items);
        } catch {
            showToast('Failed to load mobile quick data', 'error');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        loadQuickData();
    }, []);

    const processRecurring = async (item: RecurringTransaction, mode: 'apply' | 'skip') => {
        const key = `recurring:${item.id}:${mode}`;
        setBusyKey(key);
        try {
            if (mode === 'apply') {
                await processRecurringTransaction(item.id);
                showToast(`Posted ${item.name}`, 'success');
            } else {
                await skipRecurringTransaction(item.id);
                showToast(`Skipped ${item.name}`, 'info');
            }
            await loadQuickData();
        } catch {
            showToast(`Failed to ${mode} recurring item`, 'error');
        } finally {
            setBusyKey(null);
        }
    };

    const processAction = async (action: MonthlyAction, mode: 'apply' | 'skip') => {
        const key = `action:${action.id}:${mode}`;
        setBusyKey(key);
        try {
            if (mode === 'apply') {
                await applyReviewAction(action.id);
                showToast('Action applied', 'success');
            } else {
                await skipReviewAction(action.id);
                showToast('Action skipped', 'info');
            }
            await loadQuickData();
        } catch {
            showToast(`Failed to ${mode} action`, 'error');
        } finally {
            setBusyKey(null);
        }
    };

    return (
        <div className="space-y-4 p-3">
            <section className="flex items-center justify-between">
                <div>
                    <p className="text-[10px] uppercase tracking-wide text-slate-500">Mobile Quick</p>
                    <h1 className="text-xl font-semibold text-slate-50">Today</h1>
                </div>
                <button
                    type="button"
                    onClick={loadQuickData}
                    className="flex h-10 w-10 items-center justify-center border border-slate-800 bg-slate-900 text-slate-300 active:bg-slate-800"
                    aria-label="Refresh"
                >
                    <RefreshCw size={17} className={isLoading ? 'animate-spin' : ''} />
                </button>
            </section>

            <section className="grid grid-cols-3 gap-2">
                <MetricTile
                    label="Logical"
                    value={formatCurrency(summary?.logical_balance ?? summary?.effective_cash ?? summary?.net_worth ?? 0, currentCurrency)}
                />
                <MetricTile
                    label="This Month"
                    value={formatCurrency(pl?.net_profit_loss ?? summary?.monthly_pl ?? 0, currentCurrency)}
                    tone={(pl?.net_profit_loss ?? summary?.monthly_pl ?? 0) >= 0 ? 'good' : 'bad'}
                />
                <MetricTile
                    label="Inbox"
                    value={String(approvalCount)}
                    tone={approvalCount > 0 ? 'warn' : 'good'}
                />
            </section>

            <section className="space-y-2">
                <div className="flex items-center justify-between">
                    <h2 className="text-sm font-medium text-slate-100">Quick Templates</h2>
                    <span className="text-[10px] text-slate-500">{templates.length} active</span>
                </div>
                {templates.length === 0 ? (
                    <EmptyState text="No quick templates yet. Create them from the desktop Journal screen." />
                ) : (
                    <div className="grid grid-cols-2 gap-2">
                        {templates.map((template) => (
                            <TemplateButton
                                key={template.id}
                                template={template}
                                onSelect={() => setSelectedTemplate(template)}
                            />
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <h2 className="text-sm font-medium text-slate-100">Approval Inbox</h2>
                {approvalCount === 0 ? (
                    <EmptyState text="Nothing needs approval right now." />
                ) : (
                    <div className="space-y-2">
                        {dueRecurring.map((item) => (
                            <ApprovalCard
                                key={`recurring-${item.id}`}
                                title={item.name}
                                meta={`Recurring - ${item.next_due_date ?? 'due'}`}
                                amount={formatCurrency(item.amount, item.currency)}
                                isApplying={busyKey === `recurring:${item.id}:apply`}
                                isSkipping={busyKey === `recurring:${item.id}:skip`}
                                onApply={() => processRecurring(item, 'apply')}
                                onSkip={() => processRecurring(item, 'skip')}
                            />
                        ))}
                        {pendingActions(actions).map((action) => (
                            <ApprovalCard
                                key={`action-${action.id}`}
                                title={action.kind}
                                meta={action.description || action.source_period}
                                amount={action.amount != null ? formatCurrency(action.amount, currentCurrency) : undefined}
                                isApplying={busyKey === `action:${action.id}:apply`}
                                isSkipping={busyKey === `action:${action.id}:skip`}
                                onApply={() => processAction(action, 'apply')}
                                onSkip={() => processAction(action, 'skip')}
                            />
                        ))}
                    </div>
                )}
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
                                    <p className="text-[10px] text-slate-500">{tx.date} - {tx.type}</p>
                                </div>
                                <p className="shrink-0 font-mono-nums text-xs text-slate-200">
                                    {formatCurrency(tx.amount, tx.currency)}
                                </p>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <MobileQuickEntrySheet
                template={selectedTemplate}
                accounts={accounts}
                currentCurrency={currentCurrency}
                onClose={() => setSelectedTemplate(null)}
                onSaved={loadQuickData}
            />
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

function TemplateButton({ template, onSelect }: { template: QuickTemplate; onSelect: () => void }) {
    const preset = quickPresetFor(template);
    const Icon = preset?.icon ?? ArrowRightLeft;

    return (
        <button
            type="button"
            onClick={onSelect}
            className="min-h-24 border border-slate-800 bg-slate-900/70 p-3 text-left active:border-emerald-500 active:bg-emerald-950/20"
        >
            <div className="flex items-start justify-between gap-2">
                <Icon size={19} className={preset?.color ?? 'text-emerald-300'} />
                <ChevronRight size={15} className="text-slate-600" />
            </div>
            <p className="mt-3 truncate text-sm font-medium text-slate-100">{template.name}</p>
            <p className="mt-1 truncate text-[10px] text-slate-500">{template.tray} - {quickKindLabel(template.template_kind)}</p>
        </button>
    );
}

function ApprovalCard({
    title,
    meta,
    amount,
    isApplying,
    isSkipping,
    onApply,
    onSkip,
}: {
    title: string;
    meta: string;
    amount?: string;
    isApplying: boolean;
    isSkipping: boolean;
    onApply: () => void;
    onSkip: () => void;
}) {
    return (
        <article className="border border-slate-800 bg-slate-900/70 p-3">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100">{title}</p>
                    <p className="mt-1 line-clamp-2 text-[10px] text-slate-500">{meta}</p>
                </div>
                {amount && <p className="shrink-0 font-mono-nums text-xs text-slate-200">{amount}</p>}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                    type="button"
                    onClick={onSkip}
                    disabled={isApplying || isSkipping}
                    className="flex h-10 items-center justify-center gap-2 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
                >
                    {isSkipping ? <Loader2 size={14} className="animate-spin" /> : <SkipForward size={14} />}
                    Skip
                </button>
                <button
                    type="button"
                    onClick={onApply}
                    disabled={isApplying || isSkipping}
                    className="flex h-10 items-center justify-center gap-2 bg-emerald-600 text-xs font-medium text-white disabled:opacity-50"
                >
                    {isApplying ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                    Apply
                </button>
            </div>
        </article>
    );
}

function EmptyState({ text }: { text: string }) {
    return (
        <div className="border border-dashed border-slate-800 bg-slate-900/40 px-3 py-4 text-sm text-slate-500">
            {text}
        </div>
    );
}

function MobileQuickEntrySheet({
    template,
    accounts,
    currentCurrency,
    onClose,
    onSaved,
}: {
    template: QuickTemplate | null;
    accounts: Account[];
    currentCurrency: string;
    onClose: () => void;
    onSaved: () => Promise<void>;
}) {
    const { showToast } = useToast();
    const accountItems = useMemo(() => toAccountItems(accounts), [accounts]);
    const paymentAccounts = useMemo(() => paymentMethodsFor(template, accountItems), [template, accountItems]);
    const [entry, setEntry] = useState<QuickEntry>(() => makeEntry(template, currentCurrency, accountItems));
    const [isSaving, setIsSaving] = useState(false);

    useEffect(() => {
        setEntry(makeEntry(template, currentCurrency, accountItems));
    }, [template, currentCurrency, accountItems]);

    if (!template) return null;

    const save = async () => {
        const ownAmount = entry.ownAmount || entry.amount;
        const resolvedEntry = resolveEntryAccounts(entry, template, accountItems, currentCurrency);
        const { transactions, error } = buildQuickTransactions({
            selectedTemplate: template,
            quickEntry: { ...resolvedEntry, ownAmount },
            accounts: accountItems,
            currentCurrency,
        });

        const resolvedTransactions = error && isMissingAccountError(error)
            ? [buildFallbackTransaction(template, resolvedEntry, currentCurrency)]
            : transactions;

        if (error && resolvedTransactions.length === 0) {
            showToast(error, 'warning');
            return;
        }

        setIsSaving(true);
        try {
            await createTransactionBatch({
                quick_template_id: template.id,
                label: template.name,
                source: 'mobile_quick',
                input_payload: {
                    amount: entry.amount,
                    date: entry.date,
                    description: entry.description,
                    payment_account_id: resolvedEntry.payment_account_id || null,
                    fallback_account_resolution: Boolean(error),
                },
                transactions: resolvedTransactions,
            });
            showToast(`Saved ${template.name}`, 'success');
            onClose();
            await onSaved();
        } catch {
            showToast('Failed to save quick entry', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-end bg-black/60">
            <button type="button" className="absolute inset-0" onClick={onClose} aria-label="Close quick entry" />
            <section className="relative w-full border-t border-slate-700 bg-slate-950 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-2xl">
                <div className="mb-4 flex items-center justify-between">
                    <div className="min-w-0">
                        <p className="text-[10px] uppercase tracking-wide text-slate-500">{quickKindLabel(template.template_kind)}</p>
                        <h2 className="truncate text-lg font-semibold text-slate-100">{template.name}</h2>
                    </div>
                    <button type="button" onClick={onClose} className="p-2 text-slate-500 active:text-slate-200" aria-label="Close">
                        <X size={20} />
                    </button>
                </div>

                <div className="space-y-3">
                    <label className="block">
                        <span className="text-[10px] uppercase tracking-wide text-slate-500">Amount</span>
                        <input
                            type="number"
                            inputMode="decimal"
                            value={entry.amount}
                            onChange={(event) => setEntry({ ...entry, amount: event.target.value, ownAmount: event.target.value })}
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
                            placeholder={template.name}
                        />
                    </label>
                    <div>
                        <div className="mb-1 flex items-center justify-between">
                            <span className="text-[10px] uppercase tracking-wide text-slate-500">Payment</span>
                            <span className="text-[10px] text-slate-600">Auto is allowed</span>
                        </div>
                        <div className="edge-fade-x scrollbar-none flex gap-2 overflow-x-auto pb-1">
                            <PaymentChip
                                label="Auto"
                                selected={!entry.payment_account_id}
                                onClick={() => setEntry({ ...entry, payment_account_id: '' })}
                            />
                            {paymentAccounts.map((account) => (
                                <PaymentChip
                                    key={account.id}
                                    label={account.name.replace(/_/g, ' ')}
                                    selected={entry.payment_account_id === String(account.id)}
                                    onClick={() => setEntry({ ...entry, payment_account_id: String(account.id) })}
                                />
                            ))}
                        </div>
                    </div>
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
            </section>
        </div>
    );
}

function isMissingAccountError(error: string) {
    return error.toLowerCase().includes('account');
}

function fallbackTransactionType(kind: string): Transaction['type'] {
    if (kind === 'credit_expense') return 'CreditExpense';
    if (kind === 'transfer') return 'Transfer';
    if (kind === 'debt_payment') return 'LiabilityPayment';
    return 'Expense';
}

function buildFallbackTransaction(
    template: QuickTemplate,
    entry: QuickEntry,
    currentCurrency: string,
): Omit<Transaction, 'id'> {
    return {
        date: entry.date,
        description: entry.description.trim() || template.name,
        amount: Number(entry.amount || 0),
        type: fallbackTransactionType(template.template_kind),
        category: template.category || template.tray || template.name,
        currency: entry.currency || template.default_currency || currentCurrency,
        from_account_id: entry.payment_account_id ? Number(entry.payment_account_id) : undefined,
        to_account_id: entry.expense_account_id ? Number(entry.expense_account_id) : undefined,
    };
}

function PaymentChip({
    label,
    selected,
    onClick,
}: {
    label: string;
    selected: boolean;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={`h-10 shrink-0 border px-3 text-xs capitalize ${selected
                ? 'border-emerald-500 bg-emerald-950/30 text-emerald-200'
                : 'border-slate-700 bg-slate-900 text-slate-400'
                }`}
        >
            {label}
        </button>
    );
}

function defaultAccountId(accounts: AccountItem[], allowedTypes: string[]) {
    return accounts.find((account) => allowedTypes.includes(account.account_type))?.id;
}

function paymentMethodsFor(template: QuickTemplate | null, accounts: AccountItem[]) {
    const kind = template?.template_kind as QuickTemplateKind | undefined;
    const allowedTypes = kind && QUICK_KIND_RULES[kind] ? QUICK_KIND_RULES[kind].fromTypes : ['asset', 'liability'];
    return accounts.filter((account) => allowedTypes.includes(account.account_type));
}

function resolveEntryAccounts(
    entry: QuickEntry,
    template: QuickTemplate | null,
    accounts: AccountItem[],
    currentCurrency: string,
) {
    const fallback = makeEntry(template, currentCurrency, accounts);
    return {
        ...entry,
        payment_account_id: entry.payment_account_id || fallback.payment_account_id,
        expense_account_id: entry.expense_account_id || fallback.expense_account_id,
        receivable_account_id: entry.receivable_account_id || fallback.receivable_account_id,
        reimbursement_account_id: entry.reimbursement_account_id || fallback.reimbursement_account_id,
    };
}

function makeEntry(template: QuickTemplate | null, currentCurrency: string, accounts: AccountItem[]): QuickEntry {
    const kind = template?.template_kind as QuickTemplateKind | undefined;
    const rules = kind ? QUICK_KIND_RULES[kind] : undefined;
    const fallbackFromId = rules ? defaultAccountId(accounts, rules.fromTypes) : undefined;
    const fallbackToId = rules ? defaultAccountId(accounts, rules.toTypes) : undefined;

    return {
        date: todayIso(),
        description: '',
        amount: '',
        ownAmount: '',
        advanceAmount: '',
        currency: template?.default_currency || currentCurrency,
        payment_account_id: String(template?.default_from_account_id ?? fallbackFromId ?? ''),
        expense_account_id: String(template?.default_to_account_id ?? fallbackToId ?? ''),
        receivable_account_id: typeof template?.config?.receivable_account_id === 'number'
            ? String(template.config.receivable_account_id)
            : '',
        reimbursement_account_id: typeof template?.config?.reimbursement_account_id === 'number'
            ? String(template.config.reimbursement_account_id)
            : '',
        reimbursementReceived: false,
    };
}
