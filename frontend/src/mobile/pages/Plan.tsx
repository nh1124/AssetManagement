import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, ChevronLeft, ChevronRight, Loader2, Plus, Trash2, X, type LucideIcon } from 'lucide-react';
import {
    createAccount,
    deleteCapsule,
    getAccounts,
    getBudgetSummary,
    getCapsules,
    getLifeEventsWithProgress,
    updateCapsule,
} from '../../api';
import { addPlanRecord, amendPlanRecord, deletePlanRecord, type PlanRecordSection } from '../../api/plan';
import { useToast } from '../../components/Toast';
import { useClient } from '../../context/ClientContext';
import type { Account, LifeEventProgress, MonthlyPlanLine, MonthlyPlanLineType } from '../../types';
import { formatCurrency } from '../../utils/currency';

type PlanTab = 'goals' | 'capsules' | 'budget';
type BudgetGroup = 'income' | 'variable' | 'allocation' | 'debt';

const BUDGET_GROUPS: Array<[BudgetGroup, string]> = [
    ['income', 'INCOME'],
    ['variable', 'VARIABLE'],
    ['allocation', 'ALLOCATION'],
    ['debt', 'DEBT'],
];

interface BudgetSummary {
    period?: string;
    monthly_income?: number;
    required_monthly_savings?: number;
    monthly_fixed_costs?: number;
    total_expected_inflow?: number;
    total_variable_budget?: number;
    remaining_balance?: number;
    available_cash_flow?: number;
    free_cash_flow?: number;
    plan_lines?: MonthlyPlanLine[];
    others_actual?: number;
}

interface CapsuleSummary {
    id: number;
    name: string;
    current_balance?: number;
    target_amount?: number;
    monthly_contribution?: number;
    capsule_type?: string;
}

const monthKey = () => new Date().toISOString().slice(0, 7);

const shiftMonth = (period: string, delta: number) => {
    const [year, month] = period.split('-').map(Number);
    const date = new Date(year, month - 1 + delta, 1);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
};

export default function MobilePlanPage() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [activeTab, setActiveTab] = useState<PlanTab>('goals');
    const [budgetPeriod, setBudgetPeriod] = useState(monthKey());
    const [goals, setGoals] = useState<LifeEventProgress[]>([]);
    const [budget, setBudget] = useState<BudgetSummary | null>(null);
    const [capsules, setCapsules] = useState<CapsuleSummary[]>([]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [selectedCapsule, setSelectedCapsule] = useState<CapsuleSummary | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const currentCurrency = currentClient?.general_settings?.currency || 'JPY';

    const loadPlan = async () => {
        setIsLoading(true);
        try {
            const [goalData, budgetData, capsuleData, accountData] = await Promise.all([
                getLifeEventsWithProgress(),
                getBudgetSummary(budgetPeriod, { cash_flow_start_period: budgetPeriod, cash_flow_months: 1 }),
                getCapsules(),
                getAccounts(),
            ]);
            setGoals((goalData ?? []).filter((goal) => goal.direction === 'expense').slice(0, 20));
            setBudget(budgetData ?? null);
            setCapsules((capsuleData ?? []).slice(0, 30));
            setAccounts(accountData);
        } catch {
            showToast('Failed to load mobile plan', 'error');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        loadPlan();
    }, [budgetPeriod]);

    const sortedGoals = useMemo(() => [...goals].sort((a, b) => a.target_date.localeCompare(b.target_date)), [goals]);

    return (
        <div className="space-y-4 p-3">
            <div className="mx-auto flex w-fit rounded-full border border-slate-800 bg-slate-900/80 p-1">
                {([
                    ['goals', 'Goals'],
                    ['capsules', 'Capsules'],
                    ['budget', 'Budget'],
                ] as Array<[PlanTab, string]>).map(([tab, label]) => (
                    <button
                        key={tab}
                        type="button"
                        onClick={() => setActiveTab(tab)}
                        className={`h-8 rounded-full px-4 text-xs transition-colors ${activeTab === tab
                            ? 'bg-emerald-500 text-slate-950'
                            : 'text-slate-500'
                            }`}
                    >
                        {label}
                    </button>
                ))}
            </div>

            {activeTab === 'goals' && (
                <section className="space-y-2">
                    {isLoading && goals.length === 0 ? (
                        <LoadingBlock />
                    ) : sortedGoals.length === 0 ? (
                        <EmptyBlock text="No goals yet." />
                    ) : (
                        <div className="space-y-2">
                            {sortedGoals.map((goal) => (
                                <GoalCard
                                    key={goal.id}
                                    goal={goal}
                                    currency={currentCurrency}
                                />
                            ))}
                        </div>
                    )}
                </section>
            )}

            {activeTab === 'capsules' && (
                <section className="space-y-2">
                    {capsules.length === 0 ? (
                        <EmptyBlock text="No capsules yet." />
                    ) : (
                        <div className="space-y-2">
                            {capsules.map((capsule) => (
                                <CapsuleCard
                                    key={capsule.id}
                                    capsule={capsule}
                                    currency={currentCurrency}
                                    onOpen={() => setSelectedCapsule(capsule)}
                                />
                            ))}
                        </div>
                    )}
                </section>
            )}

            {activeTab === 'budget' && (
                <BudgetPanel
                    budget={budget}
                    period={budgetPeriod}
                    accounts={accounts}
                    currency={currentCurrency}
                    language={String(currentClient?.general_settings?.language || 'ja')}
                    onPeriodChange={setBudgetPeriod}
                    onChanged={loadPlan}
                />
            )}

            {selectedCapsule && (
                <CapsuleSheet
                    capsule={selectedCapsule}
                    currency={currentCurrency}
                    onClose={() => setSelectedCapsule(null)}
                    onChanged={async () => {
                        await loadPlan();
                    }}
                />
            )}
        </div>
    );
}

// The goal's funding comes from its 実績管理の設定; editing it lives in the studio.
function GoalCard({ goal, currency }: { goal: LifeEventProgress; currency: string }) {
    const funded = goal.current_funded;
    const progress = Math.max(0, Math.min(100, goal.progress_percentage));

    return (
        <div className="w-full border border-slate-800 bg-slate-900/70 p-3 text-left">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100">{goal.name}</p>
                    <p className="mt-1 text-[10px] text-slate-500">{goal.months_remaining} months left</p>
                </div>
                <div className="shrink-0 text-right">
                    <p className="font-mono-nums text-xs text-emerald-300">{formatCurrency(funded, currency)}</p>
                    <p className="mt-1 text-[9px] text-slate-600">{progress.toFixed(0)}%</p>
                </div>
            </div>
            <div className="mt-3 h-2 bg-slate-800">
                <div className="h-full bg-emerald-500" style={{ width: `${progress}%` }} />
            </div>
            <div className="mt-2 flex justify-between text-[10px] text-slate-500">
                <span>{formatCurrency(goal.target_amount, currency)} target</span>
                <span>{goal.target_date}</span>
            </div>
        </div>
    );
}

function CapsuleCard({ capsule, currency, onOpen }: { capsule: CapsuleSummary; currency: string; onOpen: () => void }) {
    const current = Number(capsule.current_balance ?? 0);
    const target = Number(capsule.target_amount ?? 0);
    const progress = target > 0 ? Math.max(0, Math.min(100, (current / target) * 100)) : 0;

    return (
        <button type="button" onClick={onOpen} className="w-full border border-slate-800 bg-slate-900/70 p-3 text-left active:border-emerald-500">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100">{capsule.name}</p>
                    <p className="mt-1 text-[10px] text-slate-500">+{formatCurrency(capsule.monthly_contribution ?? 0, currency)} / mo</p>
                </div>
                <p className="shrink-0 font-mono-nums text-xs text-cyan-300">{formatCurrency(current, currency)}</p>
            </div>
            <div className="mt-3 h-2 bg-slate-800">
                <div className="h-full bg-cyan-500" style={{ width: `${progress}%` }} />
            </div>
            <p className="mt-2 text-right text-[10px] text-slate-500">{formatCurrency(target, currency)} target</p>
        </button>
    );
}

/** The group's movements and the section a new user record goes to. */
const GROUP_TYPES: Record<BudgetGroup, MonthlyPlanLineType[]> = {
    income: ['income', 'borrowing', 'drawdown'], variable: ['expense'], allocation: ['allocation'], debt: ['debt_payment'],
};
const GROUP_SECTION: Record<BudgetGroup, PlanRecordSection> = { income: 'income', variable: 'expense', allocation: 'allocation', debt: 'debt_payment' };
const GROUP_KIND: Record<BudgetGroup, Account['account_type']> = { income: 'income', variable: 'expense', allocation: 'asset', debt: 'liability' };
const ORIGIN_LABELS = { goal: 'Goal', registry: 'Auto', card: 'Card', earmark: 'Earmark', unassigned: 'No account' } as const;

/** Where a row comes from; null is the user's own record, the only kind edited here (the server refuses the others). */
function rowOrigin(line: MonthlyPlanLine): keyof typeof ORIGIN_LABELS | null {
    if (line.target_type === 'capsule') return 'earmark';
    if (line.source === 'goal' || line.source_kind === 'goal') return 'goal';
    if (line.source === 'registry') return 'registry';
    if (line.source === 'credit_settlement' || (line.source !== 'manual' && line.source_kind === 'credit_settlement')) return 'card';
    if (line.account_id == null || line.id == null) return 'unassigned';
    return null;
}

function BudgetPanel({
    budget,
    period,
    accounts,
    currency,
    language,
    onPeriodChange,
    onChanged,
}: {
    budget: BudgetSummary | null;
    period: string;
    accounts: Account[];
    currency: string;
    language: string;
    onPeriodChange: (period: string) => void;
    onChanged: () => Promise<void>;
}) {
    const { showToast } = useToast();
    const [activeBudgetGroup, setActiveBudgetGroup] = useState<BudgetGroup>('variable');
    // Typed amounts of the user's records, by record id, until saved.
    const [edits, setEdits] = useState<Record<number, string>>({});
    const [showAddForm, setShowAddForm] = useState(false);
    const [addForm, setAddForm] = useState({ account_id: '', name: '', amount: '' });
    const [isSaving, setIsSaving] = useState(false);
    const [touchStartX, setTouchStartX] = useState<number | null>(null);

    useEffect(() => { setEdits({}); }, [budget]);

    const rows = useMemo(() => (budget?.plan_lines ?? [])
        .filter((line) => GROUP_TYPES[activeBudgetGroup].includes(line.line_type))
        .map((line, index) => {
            const origin = rowOrigin(line);
            return {
                key: `line-${line.id ?? `${line.line_type}-${line.target_type}-${line.target_id ?? ''}-${line.account_id ?? line.name}-${index}`}`,
                name: line.target_name || line.name || line.account_name || line.line_type.replace('_', ' '),
                amount: Number(line.budget_amount ?? line.amount ?? 0),
                actual: Number(line.actual ?? 0),
                lineType: line.line_type,
                accountId: line.account_id ?? null,
                recordId: origin == null ? line.id ?? null : null,
                origin,
            };
        }), [activeBudgetGroup, budget]);

    const planned = (row: typeof rows[number]) => Number(row.recordId != null ? edits[row.recordId] ?? row.amount : row.amount) || 0;
    const budgetTotal = rows.reduce((sum, row) => sum + planned(row), 0);
    const actualTotal = rows.reduce((sum, row) => sum + Number(row.actual ?? 0), 0);
    const varianceTotal = activeBudgetGroup === 'income' ? actualTotal - budgetTotal : budgetTotal - actualTotal;
    const usedRate = budgetTotal > 0 ? Math.min(999, Math.round((actualTotal / budgetTotal) * 100)) : 0;
    // One user record per account and section: an account that has one is edited in its row.
    const recorded = new Set(rows.filter((row) => row.recordId != null && row.lineType === GROUP_SECTION[activeBudgetGroup]).map((row) => row.accountId));
    const availableTargetAccounts = accounts.filter((account) => account.account_type === GROUP_KIND[activeBudgetGroup] && !recorded.has(account.id));
    const isJapanese = language.toLowerCase().startsWith('ja');
    const [periodYear, periodMonth] = period.split('-').map(Number);
    const periodLabel = isJapanese
        ? `${periodYear}年${periodMonth}月`
        : `${periodYear} ${new Intl.DateTimeFormat('en-US', { month: 'long' }).format(new Date(periodYear, periodMonth - 1, 1))}`;

    const handleSwipeEnd = (clientX: number) => {
        if (touchStartX == null) return;
        const delta = clientX - touchStartX;
        if (Math.abs(delta) > 44) {
            onPeriodChange(shiftMonth(period, delta < 0 ? -1 : 1));
        }
        setTouchStartX(null);
    };

    const saveBudget = async () => {
        const changed = rows.filter((row) => row.recordId != null && edits[row.recordId] != null && planned(row) !== row.amount);
        if (changed.some((row) => planned(row) < 0)) {
            showToast('Amounts must be zero or more', 'warning');
            return;
        }
        setIsSaving(true);
        try {
            for (const row of changed) await amendPlanRecord(row.recordId as number, { amount: planned(row) });
            await onChanged();
            showToast('Budget saved', 'success');
        } catch {
            showToast('Failed to save budget', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const addBudgetLine = async () => {
        const amount = Number(addForm.amount || 0);
        const creating = !addForm.account_id && activeBudgetGroup === 'variable';
        if (!amount || amount < 0 || (!addForm.account_id && !(creating && addForm.name.trim()))) {
            showToast('Account and amount are required', 'warning');
            return;
        }
        setIsSaving(true);
        try {
            const accountId = creating
                ? (await createAccount({ name: addForm.name.trim(), account_type: 'expense', balance: 0 })).id
                : Number(addForm.account_id);
            await addPlanRecord({ period, account_id: accountId, section: GROUP_SECTION[activeBudgetGroup], amount });
            setAddForm({ account_id: '', name: '', amount: '' });
            setShowAddForm(false);
            await onChanged();
            showToast('Budget line added', 'success');
        } catch {
            showToast('Failed to add budget line', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const removeBudgetLine = async (recordId: number) => {
        setIsSaving(true);
        try {
            await deletePlanRecord(recordId);
            await onChanged();
            showToast('Budget line removed', 'info');
        } catch {
            showToast('Failed to remove budget line', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <section className="space-y-3">
            <div
                className="grid grid-cols-[44px_1fr_44px] items-center"
                onTouchStart={(event) => setTouchStartX(event.touches[0]?.clientX ?? null)}
                onTouchEnd={(event) => handleSwipeEnd(event.changedTouches[0]?.clientX ?? 0)}
            >
                <button type="button" onClick={() => onPeriodChange(shiftMonth(period, -1))} className="flex h-10 items-center justify-center text-slate-500 active:text-slate-100" aria-label="Previous month">
                    <ChevronLeft size={20} />
                </button>
                <label className="relative flex h-10 items-center justify-center text-center">
                    <span className="font-mono-nums text-base font-semibold text-slate-100">{periodLabel}</span>
                    <input
                        type="month"
                        value={period}
                        onChange={(event) => onPeriodChange(event.target.value || monthKey())}
                        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                        aria-label="Budget month"
                    />
                </label>
                <button type="button" onClick={() => onPeriodChange(shiftMonth(period, 1))} className="flex h-10 items-center justify-center text-slate-500 active:text-slate-100" aria-label="Next month">
                    <ChevronRight size={20} />
                </button>
            </div>

            <div className="border border-slate-800 bg-slate-900/60 px-3 py-3">
                <div className="mb-2 flex items-center justify-between text-[10px] uppercase tracking-wide text-slate-500">
                    <span>Usage</span>
                    <span className="font-mono-nums">{usedRate}%</span>
                </div>
                <div className="h-2 bg-slate-800">
                    <div className={`h-full ${usedRate > 100 ? 'bg-rose-500' : 'bg-emerald-500'}`} style={{ width: `${Math.min(100, usedRate)}%` }} />
                </div>
                <div className="mt-3 grid grid-cols-3 gap-3">
                    <BudgetMetric label="Budget" value={budgetTotal} currency={currency} tone="text-slate-100" />
                    <BudgetMetric label="Actual" value={actualTotal} currency={currency} tone={actualTotal > budgetTotal ? 'text-rose-300' : 'text-cyan-300'} />
                    <BudgetMetric label="Left" value={varianceTotal} currency={currency} tone={varianceTotal < 0 ? 'text-rose-300' : 'text-emerald-300'} />
                </div>
            </div>

            <div className="flex items-center gap-2">
                <div className="scrollbar-none flex min-w-0 flex-1 gap-1 overflow-x-auto">
                    {BUDGET_GROUPS.map(([group, label]) => (
                        <button
                            key={group}
                            type="button"
                            onClick={() => {
                                setActiveBudgetGroup(group);
                                setShowAddForm(false);
                                setAddForm({ account_id: '', name: '', amount: '' });
                            }}
                            className={`h-8 shrink-0 border-b px-2 text-[10px] font-medium tracking-wide ${activeBudgetGroup === group
                                ? 'border-emerald-400 text-emerald-300'
                                : 'border-slate-800 text-slate-500'
                                }`}
                        >
                            {label}
                        </button>
                    ))}
                </div>
                <button
                    type="button"
                    onClick={() => setShowAddForm((value) => !value)}
                    className={`flex h-8 w-8 shrink-0 items-center justify-center border ${showAddForm ? 'border-emerald-500 text-emerald-300' : 'border-slate-800 text-slate-500'}`}
                    aria-label="Add budget line"
                >
                    <Plus size={15} />
                </button>
            </div>

            {showAddForm && (
                <div className="space-y-2 border border-slate-800 bg-slate-900/60 p-3">
                    <select
                        value={addForm.account_id}
                        onChange={(event) => setAddForm({ ...addForm, account_id: event.target.value, name: event.target.value ? '' : addForm.name })}
                        className="h-10 w-full border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100"
                    >
                        <option value="">{activeBudgetGroup === 'variable' ? 'New expense subject...' : 'Choose an account...'}</option>
                        {availableTargetAccounts.map((account) => (
                            <option key={account.id} value={account.id}>{account.name}</option>
                        ))}
                    </select>
                    {!addForm.account_id && activeBudgetGroup === 'variable' && (
                        <input
                            value={addForm.name}
                            onChange={(event) => setAddForm({ ...addForm, name: event.target.value })}
                            placeholder="Subject name"
                            className="h-10 w-full border-0 border-b border-slate-700 bg-transparent px-1 text-sm text-slate-100 outline-none focus:border-emerald-400"
                        />
                    )}
                    <input
                        type="number"
                        inputMode="decimal"
                        value={addForm.amount}
                        onChange={(event) => setAddForm({ ...addForm, amount: event.target.value })}
                        placeholder="Budget amount"
                        className="h-10 w-full border-0 border-b border-slate-700 bg-transparent px-1 text-sm font-mono-nums text-slate-100 outline-none focus:border-emerald-400"
                    />
                    <button type="button" onClick={addBudgetLine} disabled={isSaving} className="flex h-10 w-full items-center justify-center gap-2 bg-cyan-600 text-sm font-semibold text-white disabled:opacity-50">
                        <Plus size={15} /> Add
                    </button>
                </div>
            )}

            <div className="space-y-1.5">
                {rows.length === 0 ? (
                    <EmptyBlock text="No budget lines for this month." />
                ) : rows.map((row) => {
                    const amount = planned(row);
                    const actual = Number(row.actual || 0);
                    const left = activeBudgetGroup === 'income' ? actual - amount : amount - actual;
                    const usage = amount > 0 ? Math.min(100, (actual / amount) * 100) : 0;
                    const recordId = row.recordId;
                    return (
                        <div key={row.key} className="border border-slate-800 bg-slate-900/70 px-3 py-2.5">
                            <div className="flex items-center justify-between gap-3">
                                <div className="min-w-0">
                                    <p className="truncate text-sm font-medium text-slate-100">{row.name}</p>
                                </div>
                                {recordId != null
                                    ? <button type="button" onClick={() => void removeBudgetLine(recordId)} disabled={isSaving} className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 active:text-rose-300" aria-label="Remove budget">
                                        <Trash2 size={15} />
                                    </button>
                                    : <span className="shrink-0 text-[10px] uppercase tracking-wide text-slate-500">{row.origin ? ORIGIN_LABELS[row.origin] : ''}</span>}
                            </div>
                            <div className="mt-2 grid grid-cols-[1fr_108px] items-end gap-3">
                                <p className="min-w-0 font-mono-nums text-[11px] text-slate-500">
                                    <span className={left < 0 ? 'text-rose-300' : 'text-emerald-300'}>{left < 0 ? 'Over' : 'Left'} {formatCurrency(Math.abs(left), currency)}</span>
                                    <span className="ml-2 text-slate-600">{formatCurrency(actual, currency)} / {formatCurrency(amount, currency)}</span>
                                </p>
                                {recordId != null
                                    ? <input
                                        type="number"
                                        inputMode="decimal"
                                        aria-label={`${row.name} budget`}
                                        value={edits[recordId] ?? String(row.amount)}
                                        onChange={(event) => setEdits((prev) => ({ ...prev, [recordId]: event.target.value }))}
                                        className="h-8 w-full border-0 border-b border-slate-600 bg-transparent px-1 text-right text-sm font-mono-nums text-slate-100 outline-none focus:border-emerald-400"
                                    />
                                    : <span className="h-8 text-right text-sm font-mono-nums leading-8 text-slate-400">{formatCurrency(row.amount, currency)}</span>}
                            </div>
                            <div className="mt-2 h-1.5 bg-slate-800">
                                <div className={`h-full ${left < 0 ? 'bg-rose-500' : 'bg-cyan-500'}`} style={{ width: `${usage}%` }} />
                            </div>
                        </div>
                    );
                })}
            </div>

            {(budget?.others_actual ?? 0) > 0 && (
                <div className="border border-dashed border-amber-900/60 bg-amber-950/10 px-3 py-3 text-xs text-amber-200">
                    Uncategorized actual {formatCurrency(budget?.others_actual ?? 0, currency)}
                </div>
            )}

            <button type="button" onClick={saveBudget} disabled={isSaving} className="flex h-11 w-full items-center justify-center gap-2 bg-emerald-600 text-sm font-semibold text-white disabled:opacity-50">
                {isSaving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                Save Budget
            </button>
        </section>
    );
}

function BudgetMetric({ label, value, currency, tone }: { label: string; value: number; currency: string; tone: string }) {
    return (
        <div className="min-w-0">
            <p className="text-[9px] uppercase tracking-wide text-slate-500">{label}</p>
            <p className={`mt-1 truncate border-b border-slate-700 pb-1 font-mono-nums text-xs ${tone}`}>{formatCurrency(value, currency)}</p>
        </div>
    );
}

function CapsuleSheet({ capsule, currency, onClose, onChanged }: { capsule: CapsuleSummary; currency: string; onClose: () => void; onChanged: () => Promise<void> }) {
    const { showToast } = useToast();
    const [form, setForm] = useState({
        name: capsule.name,
        target_amount: String(capsule.target_amount ?? 0),
        monthly_contribution: String(capsule.monthly_contribution ?? 0),
    });
    const [isSaving, setIsSaving] = useState(false);

    const saveCapsule = async () => {
        setIsSaving(true);
        try {
            await updateCapsule(capsule.id, {
                name: form.name,
                target_amount: Number(form.target_amount || 0),
                monthly_contribution: Number(form.monthly_contribution || 0),
            });
            await onChanged();
            showToast('Capsule updated', 'success');
        } catch {
            showToast('Failed to update capsule', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const removeCapsule = async () => {
        setIsSaving(true);
        try {
            await deleteCapsule(capsule.id);
            await onChanged();
            onClose();
            showToast('Capsule deleted', 'info');
        } catch {
            showToast('Failed to delete capsule', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <Sheet onClose={onClose}>
            <div className="mb-4 flex items-start justify-between gap-3">
                <p className="truncate text-lg font-semibold text-slate-100">{capsule.name}</p>
                <IconButton icon={X} onClick={onClose} label="Close" />
            </div>

            <div className="space-y-2">
                <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} className="h-11 w-full border border-slate-700 bg-slate-900 px-3 text-sm" />
                <div className="grid grid-cols-2 gap-2">
                    <input type="number" inputMode="decimal" value={form.target_amount} onChange={(event) => setForm({ ...form, target_amount: event.target.value })} className="h-11 border border-slate-700 bg-slate-900 px-3 text-sm font-mono-nums" />
                    <input type="number" inputMode="decimal" value={form.monthly_contribution} onChange={(event) => setForm({ ...form, monthly_contribution: event.target.value })} className="h-11 border border-slate-700 bg-slate-900 px-3 text-sm font-mono-nums" />
                </div>
                <div className="grid grid-cols-2 gap-2">
                    <button type="button" onClick={saveCapsule} disabled={isSaving} className="flex h-11 items-center justify-center gap-2 bg-emerald-600 text-sm font-semibold text-white disabled:opacity-50">
                        <Check size={15} /> Save
                    </button>
                    <button type="button" onClick={removeCapsule} disabled={isSaving} className="flex h-11 items-center justify-center gap-2 border border-rose-800 text-sm text-rose-300 disabled:opacity-40">
                        <Trash2 size={15} /> Delete
                    </button>
                </div>
            </div>

            <div className="mt-5 space-y-2">
                <p className="text-xs uppercase tracking-wide text-slate-500">Capsule Claim</p>
                <p className="font-mono-nums text-cyan-300">{formatCurrency(capsule.current_balance ?? 0, currency)}</p>
            </div>
        </Sheet>
    );
}

function Sheet({ children, onClose }: { children: ReactNode; onClose: () => void }) {
    return (
        <div className="fixed inset-0 z-50 flex items-end bg-black/60">
            <button type="button" className="absolute inset-0" onClick={onClose} aria-label="Close" />
            <section className="scrollbar-none relative max-h-[88dvh] w-full overflow-y-auto border-t border-slate-700 bg-slate-950 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-2xl">
                {children}
            </section>
        </div>
    );
}

function IconButton({ icon: Icon, onClick, label }: { icon: LucideIcon; onClick: () => void; label: string }) {
    return (
        <button type="button" onClick={onClick} className="flex h-9 w-9 shrink-0 items-center justify-center text-slate-500 active:text-slate-200" aria-label={label}>
            <Icon size={17} />
        </button>
    );
}

function LoadingBlock() {
    return (
        <div className="flex items-center justify-center border border-slate-800 bg-slate-900/60 py-8 text-slate-500">
            <Loader2 size={18} className="animate-spin" />
        </div>
    );
}

function EmptyBlock({ text }: { text: string }) {
    return (
        <div className="border border-dashed border-slate-800 bg-slate-900/40 px-3 py-5 text-sm text-slate-500">
            {text}
        </div>
    );
}
