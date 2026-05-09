import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, ChevronLeft, ChevronRight, Loader2, Plus, Trash2, X, type LucideIcon } from 'lucide-react';
import {
    createAccount,
    createCapsuleHolding,
    createMilestone,
    createMonthlyPlanLines,
    deleteCapsule,
    deleteCapsuleHolding,
    deleteMilestone,
    deleteMonthlyPlanLine,
    getAccounts,
    getBudgetSummary,
    getCapsuleHoldings,
    getCapsules,
    getLifeEventsWithProgress,
    getMilestones,
    updateCapsule,
    updateCapsuleHolding,
    updateMilestone,
    updateMonthlyPlanLines,
    type MonthlyPlanLinePayload,
} from '../../api';
import { useToast } from '../../components/Toast';
import { useClient } from '../../context/ClientContext';
import type { Account, LifeEvent, Milestone, MonthlyPlanLine, MonthlyPlanLineType } from '../../types';
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
    expense_accounts?: BudgetAccount[];
    plan_lines?: MonthlyPlanLine[];
    others_actual?: number;
}

interface BudgetAccount {
    id: number;
    account_id?: number | null;
    target_type?: 'account' | 'capsule' | 'life_event' | 'product' | 'manual' | null;
    target_id?: number | null;
    source_account_id?: number | null;
    name: string;
    amount: number;
    balance: number;
    plan_line_id?: number | null;
    priority?: number;
    note?: string | null;
    suggested_amount?: number;
    suggested_source?: string | null;
    source?: string | null;
}

interface CapsuleSummary {
    id: number;
    name: string;
    current_balance?: number;
    target_amount?: number;
    monthly_contribution?: number;
    life_event_id?: number | null;
    capsule_type?: string;
    holdings?: CapsuleHolding[];
}

interface CapsuleHolding {
    id: number;
    account_id: number;
    account_name?: string | null;
    held_amount: number;
    note?: string | null;
}

const todayIso = () => new Date().toISOString().split('T')[0];
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
    const [goals, setGoals] = useState<LifeEvent[]>([]);
    const [budget, setBudget] = useState<BudgetSummary | null>(null);
    const [capsules, setCapsules] = useState<CapsuleSummary[]>([]);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [selectedGoal, setSelectedGoal] = useState<LifeEvent | null>(null);
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
            setGoals((goalData ?? []).slice(0, 20));
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

    const sortedGoals = useMemo(() => {
        return [...goals].sort((a, b) => {
            const statusRank = (status?: string) => status === 'Off Track' ? 0 : status === 'At Risk' ? 1 : 2;
            return statusRank(a.status) - statusRank(b.status);
        });
    }, [goals]);

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
                                    onOpen={() => setSelectedGoal(goal)}
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

            {selectedGoal && (
                <GoalSheet
                    goal={selectedGoal}
                    currency={currentCurrency}
                    onClose={() => setSelectedGoal(null)}
                    onChanged={loadPlan}
                />
            )}

            {selectedCapsule && (
                <CapsuleSheet
                    capsule={selectedCapsule}
                    accounts={accounts}
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

function GoalCard({ goal, currency, onOpen }: { goal: LifeEvent; currency: string; onOpen: () => void }) {
    const funded = fundedAmount(goal);
    const progress = goal.target_amount > 0 ? Math.max(0, Math.min(100, (funded / goal.target_amount) * 100)) : 0;
    const tone = goal.status === 'Off Track'
        ? 'text-rose-300'
        : goal.status === 'At Risk'
            ? 'text-amber-300'
            : 'text-emerald-300';

    return (
        <button type="button" onClick={onOpen} className="w-full border border-slate-800 bg-slate-900/70 p-3 text-left active:border-emerald-500">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100">{goal.name}</p>
                    <p className={`mt-1 text-[10px] ${tone}`}>{goal.status ?? 'Not Started'}</p>
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
        </button>
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
    const variableRows = budget?.expense_accounts ?? [];
    const planLines = budget?.plan_lines ?? [];
    const [activeBudgetGroup, setActiveBudgetGroup] = useState<BudgetGroup>('variable');
    const [edits, setEdits] = useState<Record<string, string>>({});
    const [showAddForm, setShowAddForm] = useState(false);
    const [addForm, setAddForm] = useState({ account_id: '', name: '', amount: '' });
    const [isSaving, setIsSaving] = useState(false);
    const [touchStartX, setTouchStartX] = useState<number | null>(null);

    const rows = useMemo(() => {
        if (activeBudgetGroup === 'variable') {
            return variableRows.map((row) => ({
                key: `variable-${row.id}`,
                name: row.name,
                amount: Number(row.amount ?? 0),
                actual: Number(row.balance ?? 0),
                line_type: 'expense' as MonthlyPlanLineType,
                target_type: row.target_type ?? (row.account_id ? 'account' : 'manual'),
                target_id: row.target_id ?? null,
                account_id: row.account_id ?? null,
                source_account_id: row.source_account_id ?? null,
                plan_line_id: row.plan_line_id ?? null,
                priority: row.priority ?? 2,
                note: row.note ?? null,
                source: row.source ?? 'manual',
                raw_id: row.id,
            }));
        }
        const lineTypes: MonthlyPlanLineType[] = activeBudgetGroup === 'income'
            ? ['income', 'borrowing', 'drawdown']
            : activeBudgetGroup === 'allocation'
                ? ['allocation']
                : ['debt_payment'];
        return planLines
            .filter((line) => lineTypes.includes(line.line_type))
            .map((line) => ({
                key: `line-${line.id ?? `${line.line_type}-${line.target_type}-${line.account_id ?? line.target_id ?? line.name}`}`,
                name: line.target_name || line.name || line.account_name || line.line_type.replace('_', ' '),
                amount: Number(line.amount ?? 0),
                actual: Number(line.actual ?? 0),
                line_type: line.line_type,
                target_type: line.target_type,
                target_id: line.target_id ?? null,
                account_id: line.account_id ?? null,
                source_account_id: line.source_account_id ?? null,
                plan_line_id: line.id ?? null,
                priority: line.priority ?? 2,
                note: line.note ?? null,
                source: line.source ?? 'manual',
                raw_id: line.id ?? 0,
            }));
    }, [activeBudgetGroup, planLines, variableRows]);

    const allRows = useMemo(() => {
        const result: Array<{ key: string; amount: number }> = [];
        variableRows.forEach((row) => result.push({ key: `variable-${row.id}`, amount: Number(row.amount ?? 0) }));
        planLines
            .filter((line) => line.line_type !== 'expense')
            .forEach((line) => result.push({
                key: `line-${line.id ?? `${line.line_type}-${line.target_type}-${line.account_id ?? line.target_id ?? line.name}`}`,
                amount: Number(line.amount ?? 0),
            }));
        return result;
    }, [planLines, variableRows]);

    useEffect(() => {
        const next: Record<string, string> = {};
        allRows.forEach((row) => {
            next[row.key] = String(Number(row.amount ?? 0));
        });
        setEdits(next);
    }, [budget?.period, allRows.length]);

    const budgetTotal = rows.reduce((sum, row) => sum + Number(edits[row.key] ?? row.amount ?? 0), 0);
    const actualTotal = rows.reduce((sum, row) => sum + Number(row.actual ?? 0), 0);
    const varianceTotal = activeBudgetGroup === 'income' ? actualTotal - budgetTotal : budgetTotal - actualTotal;
    const usedRate = budgetTotal > 0 ? Math.min(999, Math.round((actualTotal / budgetTotal) * 100)) : 0;
    const currentAccountIds = new Set(variableRows.map((row) => row.account_id).filter(Boolean));
    const targetAccountType = activeBudgetGroup === 'income'
        ? 'income'
        : activeBudgetGroup === 'allocation'
            ? 'asset'
            : activeBudgetGroup === 'debt'
                ? 'liability'
                : 'expense';
    const availableTargetAccounts = accounts.filter((account) => (
        account.account_type === targetAccountType
        && (activeBudgetGroup !== 'variable' || !currentAccountIds.has(account.id))
    ));
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

    type EditablePlanLinePayload = MonthlyPlanLinePayload & { id?: number };

    const persistLines = async (lines: EditablePlanLinePayload[]) => {
        const creates: MonthlyPlanLinePayload[] = [];
        const updates: Array<MonthlyPlanLinePayload & { id: number }> = [];
        lines.forEach((line) => {
            const { id, ...payload } = line;
            if (typeof id === 'number') {
                updates.push({ id, ...payload });
            } else if (payload.amount > 0) {
                creates.push(payload);
            }
        });
        if (creates.length > 0) await createMonthlyPlanLines(creates);
        if (updates.length > 0) await updateMonthlyPlanLines(updates);
    };

    const budgetPayload = (row: typeof rows[number], amount: number): EditablePlanLinePayload => {
        const targetType = row.target_type ?? (row.account_id ? 'account' : 'manual');
        return {
            ...(typeof row.plan_line_id === 'number' ? { id: row.plan_line_id } : {}),
            target_period: period,
            line_type: row.line_type,
            target_type: targetType,
            target_id: row.target_id ?? null,
            account_id: row.account_id ?? (targetType === 'account' && row.raw_id > 0 ? row.raw_id : null),
            source_account_id: row.source_account_id ?? null,
            name: row.name,
            amount,
            priority: row.priority ?? 2,
            note: row.note ?? null,
            source: 'manual',
            recurring_transaction_id: null,
            is_active: true,
        };
    };

    const saveBudget = async () => {
        setIsSaving(true);
        try {
            await persistLines(rows.map((row) => budgetPayload(row, Number(edits[row.key] || 0))));
            await onChanged();
            showToast('Budget saved', 'success');
        } catch {
            showToast('Failed to save budget', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const lineTypeForActiveGroup = (): MonthlyPlanLineType => {
        if (activeBudgetGroup === 'income') return 'income';
        if (activeBudgetGroup === 'allocation') return 'allocation';
        if (activeBudgetGroup === 'debt') return 'debt_payment';
        return 'expense';
    };

    const addBudgetLine = async () => {
        const amount = Number(addForm.amount || 0);
        if (!amount || (!addForm.account_id && !addForm.name.trim())) {
            showToast('Category and amount are required', 'warning');
            return;
        }
        setIsSaving(true);
        try {
            const lineType = lineTypeForActiveGroup();
            if (addForm.account_id) {
                const account = accounts.find((item) => item.id === Number(addForm.account_id));
                await persistLines([{
                    target_period: period,
                    line_type: lineType,
                    target_type: 'account',
                    account_id: Number(addForm.account_id),
                    name: account?.name ?? null,
                    amount,
                    source: 'manual',
                    is_active: true,
                }]);
            } else if (activeBudgetGroup === 'variable') {
                const created = await createAccount({ name: addForm.name.trim(), account_type: 'expense', balance: 0 });
                await persistLines([{
                    target_period: period,
                    line_type: lineType,
                    target_type: 'account',
                    account_id: created.id,
                    name: created.name,
                    amount,
                    source: 'manual',
                    is_active: true,
                }]);
            } else {
                await persistLines([{
                    target_period: period,
                    line_type: lineType,
                    target_type: 'manual',
                    account_id: null,
                    name: addForm.name.trim(),
                    amount,
                    source: 'manual',
                    is_active: true,
                }]);
            }
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

    const removeBudgetLine = async (row: typeof rows[number]) => {
        if (!row.plan_line_id) {
            setEdits((prev) => ({ ...prev, [row.key]: '0' }));
            showToast('Set this budget to zero, then save.', 'info');
            return;
        }
        setIsSaving(true);
        try {
            await deleteMonthlyPlanLine(row.plan_line_id);
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
                        <option value="">New manual item...</option>
                        {availableTargetAccounts.map((account) => (
                            <option key={account.id} value={account.id}>{account.name}</option>
                        ))}
                    </select>
                    {!addForm.account_id && (
                        <input
                            value={addForm.name}
                            onChange={(event) => setAddForm({ ...addForm, name: event.target.value })}
                            placeholder="Item name"
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
                    const planned = Number(edits[row.key] || 0);
                    const actual = Number(row.actual || 0);
                    const left = activeBudgetGroup === 'income' ? actual - planned : planned - actual;
                    const usage = planned > 0 ? Math.min(100, (actual / planned) * 100) : 0;
                    return (
                        <div key={row.key} className="border border-slate-800 bg-slate-900/70 px-3 py-2.5">
                            <div className="flex items-center justify-between gap-3">
                                <div className="min-w-0">
                                    <p className="truncate text-sm font-medium text-slate-100">{row.name}</p>
                                </div>
                                <button type="button" onClick={() => removeBudgetLine(row)} className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 active:text-rose-300" aria-label="Remove budget">
                                    <Trash2 size={15} />
                                </button>
                            </div>
                            <div className="mt-2 grid grid-cols-[1fr_108px] items-end gap-3">
                                <p className="min-w-0 font-mono-nums text-[11px] text-slate-500">
                                    <span className={left < 0 ? 'text-rose-300' : 'text-emerald-300'}>{left < 0 ? 'Over' : 'Left'} {formatCurrency(Math.abs(left), currency)}</span>
                                    <span className="ml-2 text-slate-600">{formatCurrency(actual, currency)} / {formatCurrency(planned, currency)}</span>
                                </p>
                                <input
                                    type="number"
                                    inputMode="decimal"
                                    value={edits[row.key] ?? ''}
                                    onChange={(event) => setEdits((prev) => ({ ...prev, [row.key]: event.target.value }))}
                                    className="h-8 w-full border-0 border-b border-slate-600 bg-transparent px-1 text-right text-sm font-mono-nums text-slate-100 outline-none focus:border-emerald-400"
                                />
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

function GoalSheet({ goal, currency, onClose, onChanged }: { goal: LifeEvent; currency: string; onClose: () => void; onChanged: () => Promise<void> }) {
    const { showToast } = useToast();
    const [milestones, setMilestones] = useState<Milestone[]>([]);
    const [form, setForm] = useState({ id: '', date: todayIso(), target_amount: '', note: '' });
    const [isSaving, setIsSaving] = useState(false);

    const loadMilestones = async () => {
        try {
            setMilestones(await getMilestones(goal.id));
        } catch {
            showToast('Failed to load milestones', 'error');
        }
    };

    useEffect(() => {
        loadMilestones();
    }, [goal.id]);

    const saveMilestone = async () => {
        if (!form.date || !Number(form.target_amount)) {
            showToast('Date and target amount are required', 'warning');
            return;
        }
        setIsSaving(true);
        try {
            if (form.id) {
                await updateMilestone(Number(form.id), {
                    date: form.date,
                    target_amount: Number(form.target_amount),
                    note: form.note || null,
                });
            } else {
                await createMilestone({
                    life_event_id: goal.id,
                    date: form.date,
                    target_amount: Number(form.target_amount),
                    note: form.note || null,
                    source: 'mobile',
                });
            }
            setForm({ id: '', date: todayIso(), target_amount: '', note: '' });
            await loadMilestones();
            await onChanged();
            showToast('Milestone saved', 'success');
        } catch {
            showToast('Failed to save milestone', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const removeMilestone = async (id: number) => {
        setIsSaving(true);
        try {
            await deleteMilestone(id);
            await loadMilestones();
            await onChanged();
            showToast('Milestone deleted', 'info');
        } catch {
            showToast('Failed to delete milestone', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <Sheet onClose={onClose}>
            <div className="mb-4 flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate text-lg font-semibold text-slate-100">{goal.name}</p>
                    <p className="mt-1 text-xs text-slate-500">{formatCurrency(fundedAmount(goal), currency)} funded</p>
                </div>
                <IconButton icon={X} onClick={onClose} label="Close" />
            </div>

            <div className="grid grid-cols-2 gap-2">
                <input type="date" value={form.date} onChange={(event) => setForm({ ...form, date: event.target.value })} className="h-11 border border-slate-700 bg-slate-900 px-3 text-sm" />
                <input type="number" inputMode="decimal" placeholder="Target" value={form.target_amount} onChange={(event) => setForm({ ...form, target_amount: event.target.value })} className="h-11 border border-slate-700 bg-slate-900 px-3 text-sm font-mono-nums" />
                <input placeholder="Note" value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} className="col-span-2 h-11 border border-slate-700 bg-slate-900 px-3 text-sm" />
                <button type="button" onClick={saveMilestone} disabled={isSaving} className="col-span-2 flex h-11 items-center justify-center gap-2 bg-emerald-600 text-sm font-semibold text-white disabled:opacity-50">
                    {isSaving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                    {form.id ? 'Update Milestone' : 'Add Milestone'}
                </button>
            </div>

            <div className="mt-4 divide-y divide-slate-800 border border-slate-800 bg-slate-900/60">
                {milestones.length === 0 ? (
                    <div className="px-3 py-4 text-sm text-slate-500">No milestones yet.</div>
                ) : milestones.map((milestone) => (
                    <div key={milestone.id} className="flex items-center justify-between gap-3 px-3 py-3">
                        <button
                            type="button"
                            onClick={() => setForm({
                                id: String(milestone.id),
                                date: milestone.date,
                                target_amount: String(milestone.target_amount),
                                note: milestone.note || '',
                            })}
                            className="min-w-0 flex-1 text-left"
                        >
                            <p className="text-sm text-slate-100">{formatCurrency(milestone.target_amount, currency)}</p>
                            <p className="mt-1 truncate text-[10px] text-slate-500">{milestone.date} {milestone.note ? `- ${milestone.note}` : ''}</p>
                        </button>
                        <IconButton icon={Trash2} onClick={() => removeMilestone(milestone.id)} label="Delete milestone" />
                    </div>
                ))}
            </div>
        </Sheet>
    );
}

function CapsuleSheet({ capsule, accounts, currency, onClose, onChanged }: { capsule: CapsuleSummary; accounts: Account[]; currency: string; onClose: () => void; onChanged: () => Promise<void> }) {
    const { showToast } = useToast();
    const assetAccounts = accounts.filter((account) => account.account_type === 'asset');
    const [holdings, setHoldings] = useState<CapsuleHolding[]>([]);
    const [form, setForm] = useState({
        name: capsule.name,
        target_amount: String(capsule.target_amount ?? 0),
        monthly_contribution: String(capsule.monthly_contribution ?? 0),
    });
    const [holdingForm, setHoldingForm] = useState({ id: '', account_id: '', held_amount: '', note: '' });
    const [isSaving, setIsSaving] = useState(false);

    const loadHoldings = async () => {
        try {
            setHoldings(await getCapsuleHoldings(capsule.id));
        } catch {
            setHoldings(capsule.holdings ?? []);
        }
    };

    useEffect(() => {
        loadHoldings();
    }, [capsule.id]);

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

    const saveHolding = async () => {
        if (!holdingForm.account_id || !Number(holdingForm.held_amount)) {
            showToast('Account and amount are required', 'warning');
            return;
        }
        setIsSaving(true);
        try {
            if (holdingForm.id) {
                await updateCapsuleHolding(capsule.id, Number(holdingForm.id), {
                    held_amount: Number(holdingForm.held_amount),
                    note: holdingForm.note || undefined,
                });
            } else {
                await createCapsuleHolding(capsule.id, {
                    account_id: Number(holdingForm.account_id),
                    held_amount: Number(holdingForm.held_amount),
                    note: holdingForm.note || undefined,
                });
            }
            setHoldingForm({ id: '', account_id: '', held_amount: '', note: '' });
            await loadHoldings();
            await onChanged();
            showToast('Allocation saved', 'success');
        } catch {
            showToast('Failed to save allocation', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const removeHolding = async (id: number) => {
        setIsSaving(true);
        try {
            await deleteCapsuleHolding(capsule.id, id);
            await loadHoldings();
            await onChanged();
            showToast('Allocation removed', 'info');
        } catch {
            showToast('Failed to remove allocation', 'error');
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
                    <button type="button" onClick={removeCapsule} disabled={isSaving || Boolean(capsule.life_event_id)} className="flex h-11 items-center justify-center gap-2 border border-rose-800 text-sm text-rose-300 disabled:opacity-40">
                        <Trash2 size={15} /> Delete
                    </button>
                </div>
            </div>

            <div className="mt-5 space-y-2">
                <p className="text-xs uppercase tracking-wide text-slate-500">Asset Allocation</p>
                <select value={holdingForm.account_id} onChange={(event) => setHoldingForm({ ...holdingForm, account_id: event.target.value })} className="h-11 w-full border border-slate-700 bg-slate-900 px-3 text-sm">
                    <option value="">Account...</option>
                    {assetAccounts.map((account) => (
                        <option key={account.id} value={account.id}>{account.name}</option>
                    ))}
                </select>
                <div className="grid grid-cols-2 gap-2">
                    <input type="number" inputMode="decimal" placeholder="Amount" value={holdingForm.held_amount} onChange={(event) => setHoldingForm({ ...holdingForm, held_amount: event.target.value })} className="h-11 border border-slate-700 bg-slate-900 px-3 text-sm font-mono-nums" />
                    <input placeholder="Note" value={holdingForm.note} onChange={(event) => setHoldingForm({ ...holdingForm, note: event.target.value })} className="h-11 border border-slate-700 bg-slate-900 px-3 text-sm" />
                </div>
                <button type="button" onClick={saveHolding} disabled={isSaving} className="flex h-11 w-full items-center justify-center gap-2 bg-cyan-600 text-sm font-semibold text-white disabled:opacity-50">
                    <Plus size={15} /> {holdingForm.id ? 'Update Allocation' : 'Add Allocation'}
                </button>
            </div>

            <div className="mt-4 divide-y divide-slate-800 border border-slate-800 bg-slate-900/60">
                {holdings.length === 0 ? (
                    <div className="px-3 py-4 text-sm text-slate-500">No allocations yet.</div>
                ) : holdings.map((holding) => (
                    <div key={holding.id} className="flex items-center justify-between gap-3 px-3 py-3">
                        <button
                            type="button"
                            onClick={() => setHoldingForm({
                                id: String(holding.id),
                                account_id: String(holding.account_id),
                                held_amount: String(holding.held_amount),
                                note: holding.note || '',
                            })}
                            className="min-w-0 flex-1 text-left"
                        >
                            <p className="truncate text-sm text-slate-100">{holding.account_name || `Account ${holding.account_id}`}</p>
                            <p className="mt-1 font-mono-nums text-[10px] text-cyan-300">{formatCurrency(holding.held_amount, currency)}</p>
                        </button>
                        <IconButton icon={Trash2} onClick={() => removeHolding(holding.id)} label="Remove allocation" />
                    </div>
                ))}
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

function fundedAmount(goal: LifeEvent) {
    const direct = Number(goal.current_funded ?? 0);
    if (direct > 0) return direct;
    return Number(goal.target_amount || 0) * (Number(goal.progress_percentage || 0) / 100);
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
