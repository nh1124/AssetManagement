import { useEffect, useMemo, useState } from 'react';
import { BarChart3, Box, Flag, Loader2, RefreshCw, Target } from 'lucide-react';
import { getBudgetSummary, getCapsules, getLifeEventsWithProgress, getUnitEconomicsSummary } from '../../api';
import { useToast } from '../../components/Toast';
import { useClient } from '../../context/ClientContext';
import type { LifeEvent } from '../../types';
import { formatCurrency } from '../../utils/currency';

interface BudgetSummary {
    monthly_income?: number;
    required_monthly_savings?: number;
    monthly_fixed_costs?: number;
    available_cash_flow?: number;
    free_cash_flow?: number;
}

interface CapsuleSummary {
    id: number;
    name: string;
    current_balance?: number;
    target_amount?: number;
    monthly_contribution?: number;
}

interface UnitSummary {
    total_monthly_cost?: number;
    total_recommended_monthly_reserve?: number;
}

export default function MobilePlanPage() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [goals, setGoals] = useState<LifeEvent[]>([]);
    const [budget, setBudget] = useState<BudgetSummary | null>(null);
    const [capsules, setCapsules] = useState<CapsuleSummary[]>([]);
    const [unitSummary, setUnitSummary] = useState<UnitSummary | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const currentCurrency = currentClient?.general_settings?.currency || 'JPY';

    const loadPlan = async () => {
        setIsLoading(true);
        try {
            const [goalData, budgetData, capsuleData, unitData] = await Promise.all([
                getLifeEventsWithProgress(),
                getBudgetSummary(),
                getCapsules(),
                getUnitEconomicsSummary(),
            ]);
            setGoals((goalData ?? []).slice(0, 8));
            setBudget(budgetData ?? null);
            setCapsules((capsuleData ?? []).slice(0, 8));
            setUnitSummary(unitData ?? null);
        } catch {
            showToast('Failed to load mobile plan', 'error');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        loadPlan();
    }, []);

    const sortedGoals = useMemo(() => {
        return [...goals].sort((a, b) => {
            const statusRank = (status?: string) => status === 'Off Track' ? 0 : status === 'At Risk' ? 1 : 2;
            return statusRank(a.status) - statusRank(b.status);
        });
    }, [goals]);

    return (
        <div className="space-y-4 p-3">
            <section className="flex items-center justify-between">
                <div>
                    <p className="text-[10px] uppercase tracking-wide text-slate-500">Mobile Plan</p>
                    <h1 className="text-xl font-semibold text-slate-50">Plan Check</h1>
                </div>
                <button
                    type="button"
                    onClick={loadPlan}
                    className="flex h-10 w-10 items-center justify-center border border-slate-800 bg-slate-900 text-slate-300"
                    aria-label="Refresh plan"
                >
                    <RefreshCw size={17} className={isLoading ? 'animate-spin' : ''} />
                </button>
            </section>

            <section className="grid grid-cols-2 gap-2">
                <PlanMetric
                    icon={BarChart3}
                    label="Income"
                    value={formatCurrency(budget?.monthly_income ?? 0, currentCurrency)}
                />
                <PlanMetric
                    icon={Target}
                    label="Goal Savings"
                    value={formatCurrency(budget?.required_monthly_savings ?? 0, currentCurrency)}
                />
                <PlanMetric
                    icon={Box}
                    label="Fixed Cost"
                    value={formatCurrency(budget?.monthly_fixed_costs ?? 0, currentCurrency)}
                />
                <PlanMetric
                    icon={Flag}
                    label="Product Reserve"
                    value={formatCurrency(unitSummary?.total_recommended_monthly_reserve ?? unitSummary?.total_monthly_cost ?? 0, currentCurrency)}
                />
            </section>

            <section className="space-y-2">
                <div className="flex items-center justify-between">
                    <h2 className="text-sm font-medium text-slate-100">Goals</h2>
                    <span className="text-[10px] text-slate-500">{goals.length} tracked</span>
                </div>
                {isLoading && goals.length === 0 ? (
                    <LoadingBlock />
                ) : sortedGoals.length === 0 ? (
                    <EmptyBlock text="No goals yet." />
                ) : (
                    <div className="space-y-2">
                        {sortedGoals.map((goal) => (
                            <GoalCard key={goal.id} goal={goal} currency={currentCurrency} />
                        ))}
                    </div>
                )}
            </section>

            <section className="space-y-2">
                <div className="flex items-center justify-between">
                    <h2 className="text-sm font-medium text-slate-100">Capsules</h2>
                    <span className="text-[10px] text-slate-500">{capsules.length} visible</span>
                </div>
                {capsules.length === 0 ? (
                    <EmptyBlock text="No capsules yet." />
                ) : (
                    <div className="divide-y divide-slate-800 border border-slate-800 bg-slate-900/60">
                        {capsules.map((capsule) => (
                            <div key={capsule.id} className="px-3 py-3">
                                <div className="flex items-center justify-between gap-3">
                                    <div className="min-w-0">
                                        <p className="truncate text-sm font-medium text-slate-100">{capsule.name}</p>
                                        <p className="mt-1 text-[10px] text-slate-500">
                                            +{formatCurrency(capsule.monthly_contribution ?? 0, currentCurrency)} / mo
                                        </p>
                                    </div>
                                    <p className="shrink-0 font-mono-nums text-xs text-cyan-300">
                                        {formatCurrency(capsule.current_balance ?? 0, currentCurrency)}
                                    </p>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>
        </div>
    );
}

function PlanMetric({
    icon: Icon,
    label,
    value,
}: {
    icon: typeof BarChart3;
    label: string;
    value: string;
}) {
    return (
        <div className="border border-slate-800 bg-slate-900/70 p-3">
            <div className="flex items-center gap-2 text-slate-500">
                <Icon size={15} />
                <p className="text-[10px] uppercase tracking-wide">{label}</p>
            </div>
            <p className="mt-2 truncate font-mono-nums text-sm text-slate-100">{value}</p>
        </div>
    );
}

function GoalCard({ goal, currency }: { goal: LifeEvent; currency: string }) {
    const progress = Math.max(0, Math.min(100, Number(goal.progress_percentage ?? 0)));
    const funded = Number(goal.current_funded ?? 0);
    const tone = goal.status === 'Off Track'
        ? 'text-rose-300'
        : goal.status === 'At Risk'
            ? 'text-amber-300'
            : 'text-emerald-300';

    return (
        <article className="border border-slate-800 bg-slate-900/70 p-3">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100">{goal.name}</p>
                    <p className={`mt-1 text-[10px] ${tone}`}>{goal.status ?? 'Not Started'}</p>
                </div>
                <div className="shrink-0 text-right">
                    <p className="font-mono-nums text-xs text-emerald-300">{formatCurrency(funded, currency)}</p>
                    <p className="mt-1 text-[9px] text-slate-600">funded</p>
                </div>
            </div>
            <div className="mt-3 h-2 bg-slate-800">
                <div className="h-full bg-emerald-500" style={{ width: `${progress}%` }} />
            </div>
            <div className="mt-2 flex justify-between text-[10px] text-slate-500">
                <span>{progress.toFixed(0)}%</span>
                <span>{formatCurrency(goal.target_amount, currency)} target - {goal.target_date}</span>
            </div>
        </article>
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
