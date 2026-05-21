import { useEffect, useMemo, useState } from 'react';
import {
    ArrowLeft,
    ArrowRightLeft,
    Check,
    ChevronRight,
    Loader2,
    X,
} from 'lucide-react';
import {
    createTransactionBatch,
    getAccounts,
    getAnalysisSummary,
    getProfitLoss,
    getQuickTemplates,
    getTransactionsPage,
} from '../../api';
import { useToast } from '../../components/Toast';
import { useClient } from '../../context/ClientContext';
import type { Account, AnalysisSummary, QuickTemplate, Transaction } from '../../types';
import { formatCurrency } from '../../utils/currency';
import {
    buildQuickTransactions,
    filterVisibleQuickTemplates,
    QUICK_KIND_RULES,
    QUICK_TEMPLATE_GROUPS,
    quickGroupLabel,
    quickKindLabelFor,
    quickKindGroup,
    quickPresetFor,
    quickTemplateDisplay,
    type AccountItem,
    type QuickEntry,
    type LanguageCode,
    type QuickTemplateGroup,
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

export default function MobileQuickPage() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [summary, setSummary] = useState<AnalysisSummary | null>(null);
    const [pl, setPl] = useState<ProfitLossSnapshot | null>(null);
    const [templates, setTemplates] = useState<QuickTemplate[]>([]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [recentTransactions, setRecentTransactions] = useState<Transaction[]>([]);
    const [selectedTemplate, setSelectedTemplate] = useState<QuickTemplate | null>(null);
    const [activeGroup, setActiveGroup] = useState<QuickTemplateGroup>('expense');
    const [activeTray, setActiveTray] = useState('');
    const [, setIsLoading] = useState(true);

    const currentCurrency = currentClient?.general_settings?.currency || 'JPY';
    const language: LanguageCode = String(currentClient?.general_settings?.language || 'ja').toLowerCase().startsWith('ja') ? 'ja' : 'en';
    const trayTiles = Array.from(new Set(
        templates
            .filter((template) => quickKindGroup(template.template_kind) === activeGroup)
            .map((template) => quickTemplateDisplay(template, language).tray)
    )).map((tray) => {
        const trayTemplates = templates.filter((template) =>
            quickTemplateDisplay(template, language).tray === tray && quickKindGroup(template.template_kind) === activeGroup
        );
        const preset = trayTemplates[0] ? quickPresetFor(trayTemplates[0]) : undefined;
        return {
            tray,
            count: trayTemplates.length,
            icon: preset?.icon ?? ArrowRightLeft,
            tone: preset?.color ?? 'text-emerald-300',
        };
    });
    const visibleTemplates = activeTray
        ? templates.filter((template) => quickTemplateDisplay(template, language).tray === activeTray && quickKindGroup(template.template_kind) === activeGroup)
        : [];
    const mobileQuickText = {
        templateCount: (count: number) => language === 'ja' ? `${count} テンプレート` : `${count} templates`,
        noCategories: (group: QuickTemplateGroup) => language === 'ja'
            ? `${quickGroupLabel(group, language)}カテゴリはまだありません。`
            : `No ${quickGroupLabel(group, language).toLowerCase()} categories yet.`,
        noTemplatesIn: (tray: string) => language === 'ja' ? `${tray} のテンプレートはありません。` : `No templates in ${tray}.`,
    };

    const loadQuickData = async () => {
        setIsLoading(true);
        try {
            const [summaryData, plData, templateData, accountData, txData] = await Promise.all([
                getAnalysisSummary(),
                getProfitLoss(undefined, undefined, false, monthStartIso(), todayIso()),
                getQuickTemplates(),
                getAccounts(),
                getTransactionsPage({ limit: 6, offset: 0 }),
            ]);
            setSummary(summaryData);
            setPl(plData);
            setTemplates(filterVisibleQuickTemplates(templateData));
            setAccounts(accountData);
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
                    {QUICK_TEMPLATE_GROUPS.map((group) => (
                        <button
                            key={group.value}
                            type="button"
                            onClick={() => { setActiveGroup(group.value); setActiveTray(''); }}
                            className={`h-8 rounded-full px-4 text-xs transition-colors ${activeGroup === group.value ? 'bg-emerald-500 text-slate-950' : 'text-slate-500'}`}
                        >
                            {quickGroupLabel(group.value, language)}
                        </button>
                    ))}
                </div>
                {activeTray && (
                    <div className="relative flex min-h-8 items-center justify-center">
                        <button
                            type="button"
                            onClick={() => setActiveTray('')}
                            className="absolute left-0 top-0 flex h-8 w-8 items-center justify-center rounded-full border border-slate-800 bg-slate-900/80 text-slate-400 active:text-slate-100"
                            aria-label="Back to tray list"
                        >
                            <ArrowLeft size={14} />
                        </button>
                        <p className="text-sm font-medium text-slate-100">{activeTray}</p>
                    </div>
                )}
                {templates.length === 0 ? (
                    <EmptyState text="No quick templates yet. Create them from the desktop Journal screen." />
                ) : !activeTray ? (
                    trayTiles.length === 0 ? (
                        <EmptyState text={mobileQuickText.noCategories(activeGroup)} />
                    ) : (
                        <div className="flex flex-wrap justify-center gap-2">
                            {trayTiles.map((tray) => (
                                <CategoryButton
                                    key={tray.tray}
                                    label={tray.tray}
                                    meta={mobileQuickText.templateCount(tray.count)}
                                    icon={tray.icon}
                                    tone={tray.tone}
                                    onSelect={() => setActiveTray(tray.tray)}
                                />
                            ))}
                        </div>
                    )
                ) : visibleTemplates.length === 0 ? (
                    <EmptyState text={mobileQuickText.noTemplatesIn(activeTray)} />
                ) : (
                    <div className="flex flex-wrap justify-center gap-2">
                        {visibleTemplates.map((template) => (
                            <TemplateButton
                                key={template.id}
                                template={template}
                                language={language}
                                onSelect={() => setSelectedTemplate(template)}
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
                language={language}
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

function CategoryButton({
    label,
    meta,
    icon: Icon,
    tone,
    onSelect,
}: {
    label: string;
    meta: string;
    icon: any;
    tone: string;
    onSelect: () => void;
}) {
    return (
        <button
            type="button"
            onClick={onSelect}
            className="h-28 w-28 rounded-2xl border border-slate-800 bg-slate-900/70 p-3 text-left active:border-emerald-500 active:bg-emerald-950/20"
        >
            <div className="flex items-start justify-between gap-2">
                <Icon size={19} className={tone} />
                <ChevronRight size={15} className="text-slate-600" />
            </div>
            <p className="mt-3 truncate text-sm font-medium text-slate-100">{label}</p>
            <p className="mt-1 truncate text-[10px] text-slate-500">{meta}</p>
        </button>
    );
}

function TemplateButton({
    template,
    language,
    onSelect,
}: {
    template: QuickTemplate;
    language: LanguageCode;
    onSelect: () => void;
}) {
    const preset = quickPresetFor(template);
    const Icon = preset?.icon ?? ArrowRightLeft;
    const display = quickTemplateDisplay(template, language);

    return (
        <button
            type="button"
            onClick={onSelect}
            className="h-28 w-28 rounded-2xl border border-slate-800 bg-slate-900/70 p-3 text-left active:border-emerald-500 active:bg-emerald-950/20"
        >
            <div className="flex items-start justify-between gap-2">
                <Icon size={19} className={preset?.color ?? 'text-emerald-300'} />
                <ChevronRight size={15} className="text-slate-600" />
            </div>
            <p className="mt-3 truncate text-sm font-medium text-slate-100">{display.name}</p>
            <p className="mt-1 truncate text-[10px] text-slate-500">{display.tray} - {quickKindLabelFor(template.template_kind, language)}</p>
        </button>
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
    language,
    onClose,
    onSaved,
}: {
    template: QuickTemplate | null;
    accounts: Account[];
    currentCurrency: string;
    language: LanguageCode;
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
    const display = quickTemplateDisplay(template, language);

    const save = async () => {
        const ownAmount = entry.ownAmount || entry.amount;
        const resolvedEntry = resolveEntryAccounts(entry, template, accountItems, currentCurrency);
        const { transactions, error } = buildQuickTransactions({
            selectedTemplate: template,
            quickEntry: { ...resolvedEntry, ownAmount },
            accounts: accountItems,
            currentCurrency,
            language,
        });

        const resolvedTransactions = error && isMissingAccountError(error)
            ? [buildFallbackTransaction(template, resolvedEntry, accountItems, currentCurrency, language)]
            : transactions;

        if (error && resolvedTransactions.length === 0) {
            showToast(error, 'warning');
            return;
        }

        setIsSaving(true);
        try {
            await createTransactionBatch({
                quick_template_id: template.id,
                label: display.name,
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
            showToast(`Saved ${display.name}`, 'success');
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
                        <p className="text-[10px] uppercase tracking-wide text-slate-500">{quickKindLabelFor(template.template_kind, language)}</p>
                        <h2 className="truncate text-lg font-semibold text-slate-100">{display.name}</h2>
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
                            placeholder={display.name}
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

function fallbackTransactionType(kind: string, paymentAccount?: AccountItem): Transaction['type'] {
    if (kind === 'income') return 'Income';
    if (kind === 'credit_expense' && paymentAccount?.account_type === 'liability') return 'CreditExpense';
    if (paymentAccount?.account_type === 'liability') return 'CreditExpense';
    if (kind === 'transfer') return 'Transfer';
    if (kind === 'debt_payment') return 'LiabilityPayment';
    return 'Expense';
}

function buildFallbackTransaction(
    template: QuickTemplate,
    entry: QuickEntry,
    accounts: AccountItem[],
    currentCurrency: string,
    language: LanguageCode,
): Omit<Transaction, 'id'> {
    const paymentAccount = accounts.find((account) => account.id === Number(entry.payment_account_id));
    const display = quickTemplateDisplay(template, language);
    return {
        date: entry.date,
        description: entry.description.trim() || display.name,
        amount: Number(entry.amount || 0),
        type: fallbackTransactionType(template.template_kind, paymentAccount),
        category: display.category,
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

function defaultAccountId(accounts: AccountItem[], allowedTypes: string[], preferredTypes: string[] = []) {
    return accounts.find((account) => preferredTypes.includes(account.account_type))?.id
        ?? accounts.find((account) => allowedTypes.includes(account.account_type))?.id;
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
    const preferredFromTypes = kind === 'credit_expense'
        ? ['liability']
        : kind === 'income'
            ? ['income']
            : ['asset', 'item'];
    const fallbackFromId = rules ? defaultAccountId(accounts, rules.fromTypes, preferredFromTypes) : undefined;
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
