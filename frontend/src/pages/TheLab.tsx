import { useEffect, useState } from 'react';
import { Check, RefreshCw, Save } from 'lucide-react';
import {
    CartesianGrid,
    Cell,
    ComposedChart,
    Legend,
    Line,
    Pie,
    PieChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';
import TabPanel from '../components/TabPanel';
import { useClient } from '../context/ClientContext';
import {
    getAnalysisSummary,
    getBalanceSheet,
    getCapsules,
    getPeriodReport,
    getPeriodReview,
    getNetWorthHistory,
    getProfitLoss,
    getAccounts,
    getRecurringTransactions,
    createMonthlyAction,
    getMonthlyActions,
    processDueMonthlyActions,
    applyReviewAction,
    skipReviewAction,
    applyPeriodReportAction,
    getReconcileStatus,
    getVarianceAnalysis,
    fixReconcile,
    savePeriodReview,
} from '../api';
import { useToast } from '../components/Toast';
import { formatCurrency as formatCurrencyWithSetting } from '../utils/currency';
import type { ActionProposal, AnalysisSummary, MonthlyAction, MonthlyReport, PeriodReview, NetWorthHistoryPoint, ReconcileResponse, ReviewActionKind } from '../types';

interface TheLabProps {
    onNavigate?: (page: string) => void;
}

const PORTFOLIO_TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'history', label: 'History' },
    { id: 'kpi', label: 'KPI' },
    { id: 'capsules', label: 'Capsules' },
    { id: 'reconcile', label: 'Data Quality' },
];

const PERIOD_TABS = [
    { id: 'periodSummary', label: 'Summary' },
    { id: 'pl', label: 'P/L' },
    { id: 'bs', label: 'B/S' },
    { id: 'variance', label: 'Budget' },
    { id: 'report', label: 'Report' },
    { id: 'review', label: 'Review' },
    { id: 'actions', label: 'Actions' },
];

type PeriodPreset = 'thisMonth' | 'lastMonth' | 'thisQuarter' | 'ytd' | 'thisYear' | 'last12Months' | 'custom';

const toISODate = (date: Date) => {
    const offset = date.getTimezoneOffset();
    const localDate = new Date(date.getTime() - offset * 60 * 1000);
    return localDate.toISOString().slice(0, 10);
};

const monthStart = (date: Date) => new Date(date.getFullYear(), date.getMonth(), 1);
const monthEnd = (date: Date) => new Date(date.getFullYear(), date.getMonth() + 1, 0);

const getPresetRange = (preset: PeriodPreset) => {
    const today = new Date();
    if (preset === 'lastMonth') {
        const lastMonth = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        return { start: toISODate(monthStart(lastMonth)), end: toISODate(monthEnd(lastMonth)) };
    }
    if (preset === 'thisQuarter') {
        const quarterStartMonth = Math.floor(today.getMonth() / 3) * 3;
        return {
            start: toISODate(new Date(today.getFullYear(), quarterStartMonth, 1)),
            end: toISODate(today),
        };
    }
    if (preset === 'ytd') {
        return { start: toISODate(new Date(today.getFullYear(), 0, 1)), end: toISODate(today) };
    }
    if (preset === 'thisYear') {
        return {
            start: toISODate(new Date(today.getFullYear(), 0, 1)),
            end: toISODate(new Date(today.getFullYear(), 11, 31)),
        };
    }
    if (preset === 'last12Months') {
        return {
            start: toISODate(new Date(today.getFullYear(), today.getMonth() - 11, 1)),
            end: toISODate(today),
        };
    }
    return { start: toISODate(monthStart(today)), end: toISODate(monthEnd(today)) };
};

export default function TheLab({ onNavigate }: TheLabProps) {
    const [analysisMode, setAnalysisMode] = useState<'portfolio' | 'period'>('portfolio');
    const [portfolioTab, setPortfolioTab] = useState('overview');
    const [periodTab, setPeriodTab] = useState('periodSummary');
    const [periodPreset, setPeriodPreset] = useState<PeriodPreset>('thisMonth');
    const initialRange = getPresetRange('thisMonth');
    const [periodStartDate, setPeriodStartDate] = useState(initialRange.start);
    const [periodEndDate, setPeriodEndDate] = useState(initialRange.end);
    const [loading, setLoading] = useState(false);
    const [plRollup, setPlRollup] = useState(false);

    const [summary, setSummary] = useState<AnalysisSummary | null>(null);
    const [balanceSheet, setBalanceSheet] = useState<any>(null);
    const [profitLoss, setProfitLoss] = useState<any>(null);
    const [previousProfitLoss, setPreviousProfitLoss] = useState<any>(null);
    const [variance, setVariance] = useState<any>(null);
    const [capsules, setCapsules] = useState<any[]>([]);
    const [recurringItems, setRecurringItems] = useState<any[]>([]);
    const [accounts, setAccounts] = useState<any[]>([]);
    const [monthlyReport, setMonthlyReport] = useState<MonthlyReport | null>(null);
    const [periodReview, setPeriodReview] = useState<PeriodReview | null>(null);
    const [monthlyActions, setMonthlyActions] = useState<MonthlyAction[]>([]);
    const [netWorthHistory, setNetWorthHistory] = useState<NetWorthHistoryPoint[]>([]);
    const [historyMonths, setHistoryMonths] = useState(36);
    const [reviewDraft, setReviewDraft] = useState({ reflection: '', next_actions: '' });
    const [actionDraft, setActionDraft] = useState({
        kind: 'set_budget' as ReviewActionKind,
        target_period: '',
        description: '',
        account_id: '',
        amount: '',
        name: '',
        type: 'Expense',
        from_account_id: '',
        to_account_id: '',
        recurring_id: '',
        life_event_id: '',
        delta_percent: '10',
        capsule_id: '',
        monthly_contribution: '',
    });
    const [reviewSaving, setReviewSaving] = useState(false);
    const [actionSaving, setActionSaving] = useState(false);
    const [reconcileResult, setReconcileResult] = useState<ReconcileResponse | null>(null);
    const [reconcileLoading, setReconcileLoading] = useState(false);
    const [lastVerified, setLastVerified] = useState(() => localStorage.getItem('finance_reconcile_last_verified') || '');
    const [applyingProposalId, setApplyingProposalId] = useState<string | null>(null);
    const { showToast } = useToast();
    const { currentClient } = useClient();

    const fetchData = async () => {
        setLoading(true);
        try {
            const periodKey = `${periodStartDate}..${periodEndDate}`;
            const start = new Date(`${periodStartDate}T00:00:00`);
            const end = new Date(`${periodEndDate}T00:00:00`);
            const spanDays = Math.max(1, Math.round((end.getTime() - start.getTime()) / 86400000) + 1);
            const previousEnd = new Date(start);
            previousEnd.setDate(previousEnd.getDate() - 1);
            const previousStart = new Date(previousEnd);
            previousStart.setDate(previousStart.getDate() - spanDays + 1);
            const [summaryData, bsData, plData, prevPlData, varianceData, capsuleData, reportData, reviewData, historyData, recurringData, accountData, actionData] = await Promise.all([
                getAnalysisSummary(),
                getBalanceSheet(undefined, undefined, periodEndDate),
                getProfitLoss(undefined, undefined, plRollup, periodStartDate, periodEndDate),
                getProfitLoss(undefined, undefined, plRollup, toISODate(previousStart), toISODate(previousEnd)),
                getVarianceAnalysis(undefined, undefined, periodStartDate, periodEndDate),
                getCapsules(),
                getPeriodReport(periodStartDate, periodEndDate),
                getPeriodReview(periodStartDate, periodEndDate),
                getNetWorthHistory(historyMonths),
                getRecurringTransactions(),
                getAccounts(),
                getMonthlyActions(periodKey),
            ]);
            setSummary(summaryData);
            setBalanceSheet(bsData);
            setProfitLoss(plData);
            setPreviousProfitLoss(prevPlData);
            setVariance(varianceData);
            setCapsules(capsuleData);
            setRecurringItems(recurringData);
            setAccounts(accountData);
            setMonthlyActions(actionData);
            setMonthlyReport(reportData);
            setPeriodReview(reviewData);
            setNetWorthHistory(historyData);
            setReviewDraft({
                reflection: reviewData.reflection || '',
                next_actions: reviewData.next_actions || '',
            });
        } catch (error) {
            console.error('Failed to fetch analytics data:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, [periodStartDate, periodEndDate, historyMonths, plRollup]);

    const changeHistoryMonths = async (months: number) => {
        setHistoryMonths(months);
        try {
            setNetWorthHistory(await getNetWorthHistory(months));
        } catch (error) {
            showToast('Failed to load net worth history', 'error');
        }
    };

    const formatCurrency = (value: number) => formatCurrencyWithSetting(value, currentClient?.general_settings?.currency);
    const formatOptionalCurrency = (value?: number | null) =>
        typeof value === 'number' && Number.isFinite(value) ? formatCurrency(value) : '—';
    const formatOptionalPercent = (value?: number | null) =>
        typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString()}%` : '—';
    const formatOptionalMonths = (value?: number | null) =>
        typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString()} mo` : '—';

    const kpiTone = (status: 'good' | 'warn' | 'bad') => {
        if (status === 'good') return 'text-emerald-400';
        if (status === 'warn') return 'text-amber-400';
        return 'text-rose-400';
    };

    const currencyStatus = (value?: number | null) => {
        if (typeof value !== 'number') return 'warn';
        if (value > 0) return 'good';
        if (value > -50000) return 'warn';
        return 'bad';
    };
    const savingsStatus = (value?: number | null) => {
        if (typeof value !== 'number') return 'warn';
        if (value > 20) return 'good';
        if (value > 10) return 'warn';
        return 'bad';
    };
    const probabilityStatus = (value?: number | null) => {
        if (typeof value !== 'number') return 'warn';
        if (value > 85) return 'good';
        if (value > 60) return 'warn';
        return 'bad';
    };
    const idleStatus = (value?: number | null) => {
        if (typeof value !== 'number') return 'warn';
        if (value === 0) return 'good';
        if (value <= 10) return 'warn';
        return 'bad';
    };
    const coverageStatus = (value?: number | null) => {
        if (typeof value !== 'number') return 'warn';
        if (value > 100) return 'good';
        if (value > 50) return 'warn';
        return 'bad';
    };
    const runwayStatus = (value?: number | null) => {
        if (typeof value !== 'number') return 'warn';
        if (value > 6) return 'good';
        if (value > 3) return 'warn';
        return 'bad';
    };
    const roadmapStatus = (value?: AnalysisSummary['roadmap_progression']) => {
        if (value === 'On Track') return 'good';
        if (value === 'At Risk') return 'warn';
        return 'bad';
    };

    const kpiCards = [
        {
            label: 'Logical Balance',
            value: formatOptionalCurrency(summary?.logical_balance),
            status: currencyStatus(summary?.logical_balance),
        },
        {
            label: 'Savings Rate',
            value: formatOptionalPercent(summary?.savings_rate),
            status: savingsStatus(summary?.savings_rate),
        },
        {
            label: 'Goal Achievement',
            value: formatOptionalPercent(summary?.goal_probability),
            status: probabilityStatus(summary?.goal_probability),
        },
        {
            label: 'Idle Money Rate',
            value: formatOptionalPercent(summary?.idle_money_rate),
            status: idleStatus(summary?.idle_money_rate),
        },
        {
            label: 'Liquidity Coverage',
            value: formatOptionalPercent(summary?.liquidity_coverage_ratio),
            status: coverageStatus(summary?.liquidity_coverage_ratio),
        },
        {
            label: 'Runway',
            value: formatOptionalMonths(summary?.runway_months),
            status: runwayStatus(summary?.runway_months),
        },
        {
            label: 'Roadmap Progression',
            value: summary?.roadmap_progression ?? '—',
            status: roadmapStatus(summary?.roadmap_progression),
        },
    ];

    const handleSaveReview = async () => {
        setReviewSaving(true);
        try {
            const saved = await savePeriodReview({
                start_date: periodStartDate,
                end_date: periodEndDate,
                label: `${periodStartDate} - ${periodEndDate}`,
                reflection: reviewDraft.reflection,
                next_actions: reviewDraft.next_actions,
            });
            setPeriodReview(saved);
            showToast('Period review saved', 'success');
        } catch (error) {
            showToast('Failed to save period review', 'error');
        } finally {
            setReviewSaving(false);
        }
    };

    const nextMonthPeriod = () => {
        const end = new Date(`${periodEndDate}T00:00:00`);
        const date = new Date(end.getFullYear(), end.getMonth() + 1, 1);
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
    };

    const buildActionPayload = () => {
        switch (actionDraft.kind) {
            case 'set_budget':
                return { account_id: Number(actionDraft.account_id), amount: Number(actionDraft.amount) };
            case 'add_recurring':
                return {
                    name: actionDraft.name,
                    amount: Number(actionDraft.amount),
                    type: actionDraft.type,
                    from_account_id: actionDraft.from_account_id ? Number(actionDraft.from_account_id) : null,
                    to_account_id: actionDraft.to_account_id ? Number(actionDraft.to_account_id) : null,
                    frequency: 'Monthly',
                };
            case 'pause_recurring':
                return { recurring_id: Number(actionDraft.recurring_id), until_period: actionDraft.target_period || nextMonthPeriod() };
            case 'boost_allocation':
                return {
                    life_event_id: Number(actionDraft.life_event_id),
                    account_id: Number(actionDraft.account_id),
                    delta_percent: Number(actionDraft.delta_percent),
                };
            case 'change_capsule_contribution':
                return { capsule_id: Number(actionDraft.capsule_id), monthly_contribution: Number(actionDraft.monthly_contribution) };
            default:
                return {};
        }
    };

    const refreshActions = async () => {
        setMonthlyActions(await getMonthlyActions(`${periodStartDate}..${periodEndDate}`));
    };

    const handleCreateAction = async () => {
        setActionSaving(true);
        try {
            await createMonthlyAction({
                source_period: `${periodStartDate}..${periodEndDate}`,
                target_period: actionDraft.target_period || nextMonthPeriod(),
                kind: actionDraft.kind,
                description: actionDraft.description,
                payload: buildActionPayload(),
            });
            setActionDraft({
                ...actionDraft,
                description: '',
                account_id: '',
                amount: '',
                name: '',
                from_account_id: '',
                to_account_id: '',
                recurring_id: '',
                life_event_id: '',
                capsule_id: '',
                monthly_contribution: '',
            });
            await refreshActions();
            showToast('Action queued', 'success');
        } catch (error) {
            showToast('Failed to queue action', 'error');
        } finally {
            setActionSaving(false);
        }
    };

    const handleProcessDueActions = async () => {
        await processDueMonthlyActions();
        await refreshActions();
        showToast('Due actions processed', 'success');
    };

    const handleApplyReviewAction = async (id: number) => {
        await applyReviewAction(id);
        await refreshActions();
    };

    const handleSkipReviewAction = async (id: number) => {
        await skipReviewAction(id);
        await refreshActions();
    };

    const updateLastVerified = () => {
        const timestamp = new Date().toLocaleString();
        localStorage.setItem('finance_reconcile_last_verified', timestamp);
        setLastVerified(timestamp);
    };

    const handleRunReconcile = async () => {
        setReconcileLoading(true);
        try {
            const result = await getReconcileStatus();
            setReconcileResult(result);
            updateLastVerified();
        } catch (error) {
            console.error('Failed to run reconcile:', error);
            showToast('Failed to run reconcile check', 'error');
        } finally {
            setReconcileLoading(false);
        }
    };

    const handleFixReconcile = async () => {
        if (!window.confirm('Auto-fix account balances from journal entries?')) return;

        setReconcileLoading(true);
        try {
            await fixReconcile();
            const result = await getReconcileStatus();
            setReconcileResult(result);
            updateLastVerified();
            showToast('Reconcile fix completed', 'success');
        } catch (error) {
            console.error('Failed to fix reconcile:', error);
            showToast('Failed to auto-fix reconcile discrepancies', 'error');
        } finally {
            setReconcileLoading(false);
        }
    };

    const handleApplyProposal = async (proposal: ActionProposal) => {
        if (!monthlyReport) return;
        setApplyingProposalId(proposal.id);
        try {
            const result = await applyPeriodReportAction(periodStartDate, periodEndDate, proposal.id);
            const nextReport = await getPeriodReport(periodStartDate, periodEndDate);
            setMonthlyReport(nextReport);
            showToast(result.status === 'already_applied' ? 'Action already applied' : 'Action applied', 'success');
        } catch (error) {
            console.error('Failed to apply proposal:', error);
            showToast('Failed to apply action proposal', 'error');
        } finally {
            setApplyingProposalId(null);
        }
    };

    const renderTabContent = () => {
        const activeTab = analysisMode === 'portfolio' ? portfolioTab : periodTab;
        const expenseRows = profitLoss?.expenses ?? [];
        const previousExpenseMap = new Map<string, number>(
            (previousProfitLoss?.expenses ?? []).map((row: any) => [String(row.category).toLowerCase(), row.amount || 0])
        );
        const sortedExpenses = [...expenseRows].sort((a: any, b: any) => (b.amount || 0) - (a.amount || 0));
        const pieExpenses = sortedExpenses.length > 8
            ? [
                ...sortedExpenses.slice(0, 8),
                {
                    category: 'Others',
                    amount: sortedExpenses.slice(8).reduce((sum: number, row: any) => sum + (row.amount || 0), 0),
                },
            ]
            : sortedExpenses;
        const accountNameById = new Map(accounts.map((account) => [account.id, String(account.name).toLowerCase()]));
        const fixedCategories = new Set(
            recurringItems
                .filter((item) => ['Expense', 'CreditExpense', 'LiabilityPayment'].includes(item.type))
                .flatMap((item) => [
                    String(item.name || '').toLowerCase(),
                    accountNameById.get(item.to_account_id),
                ])
                .filter(Boolean) as string[]
        );
        const fixedAmount = expenseRows
            .filter((row: any) => fixedCategories.has(String(row.category).toLowerCase()))
            .reduce((sum: number, row: any) => sum + (row.amount || 0), 0);
        const variableAmount = Math.max(0, (profitLoss?.total_expenses ?? 0) - fixedAmount);
        const fixedVariableData = [
            { name: 'Fixed', amount: fixedAmount },
            { name: 'Variable', amount: variableAmount },
        ].filter((row) => row.amount > 0);
        const categoryColor = (index: number, total: number) => `hsl(${Math.round(index * 360 / Math.max(total, 1))}, 62%, 52%)`;

        switch (activeTab) {
            case 'overview':
                return (
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Net Worth</p>
                            <p className="text-lg font-mono-nums text-emerald-400">{formatOptionalCurrency(summary?.net_worth)}</p>
                        </div>
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Effective Cash</p>
                            <p className="text-lg font-mono-nums text-cyan-400">{formatOptionalCurrency(summary?.effective_cash)}</p>
                        </div>
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Goal Probability</p>
                            <p className="text-lg font-mono-nums text-amber-400">{formatOptionalPercent(summary?.goal_probability)}</p>
                        </div>
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Roadmap</p>
                            <p className={`text-lg font-mono-nums ${kpiTone(roadmapStatus(summary?.roadmap_progression))}`}>{summary?.roadmap_progression ?? '—'}</p>
                        </div>
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Logical Balance</p>
                            <p className={`text-lg font-mono-nums ${kpiTone(currencyStatus(summary?.logical_balance))}`}>{formatOptionalCurrency(summary?.logical_balance)}</p>
                        </div>
                    </div>
                );
            case 'periodSummary':
                return (
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Period P/L</p>
                            <p className={`text-lg font-mono-nums ${(monthlyReport?.summary?.monthly_pl ?? profitLoss?.net_profit_loss ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {formatCurrency(monthlyReport?.summary?.monthly_pl ?? profitLoss?.net_profit_loss ?? 0)}
                            </p>
                        </div>
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Income</p>
                            <p className="text-lg font-mono-nums text-emerald-400">{formatCurrency(profitLoss?.total_income ?? 0)}</p>
                        </div>
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Expenses</p>
                            <p className="text-lg font-mono-nums text-rose-400">{formatCurrency(profitLoss?.total_expenses ?? 0)}</p>
                        </div>
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Savings Rate</p>
                            <p className="text-lg font-mono-nums text-cyan-400">{monthlyReport?.summary?.savings_rate ?? 0}%</p>
                        </div>
                        <div className="bg-slate-800/50 border border-slate-700 p-3">
                            <p className="text-[10px] text-slate-500 uppercase">Anomalies</p>
                            <p className="text-lg font-mono-nums text-amber-400">{monthlyReport?.anomalies?.length ?? 0}</p>
                        </div>
                    </div>
                );
            case 'history':
                return (
                    <div className="space-y-3">
                        <div className="flex justify-end gap-1">
                            {[12, 36, 60, 240].map((months) => (
                                <button
                                    key={months}
                                    onClick={() => changeHistoryMonths(months)}
                                    className={`px-2 py-1 text-[10px] ${historyMonths === months
                                        ? 'bg-emerald-700 text-white'
                                        : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                                        }`}
                                >
                                    {months === 240 ? 'All' : `${months}M`}
                                </button>
                            ))}
                        </div>
                        <div className="h-[360px] border border-slate-700 bg-slate-800/30 p-3">
                            <ResponsiveContainer width="100%" height="100%">
                                <ComposedChart data={netWorthHistory} margin={{ top: 8, right: 16, bottom: 20, left: 8 }}>
                                    <CartesianGrid stroke="#1e293b" />
                                    <XAxis dataKey="period" stroke="#64748b" tick={{ fontSize: 10 }} />
                                    <YAxis stroke="#64748b" tick={{ fontSize: 10 }} tickFormatter={(value) => `${formatCurrencyWithSetting(Math.round(Number(value) / 1000), currentClient?.general_settings?.currency)}k`} />
                                    <Tooltip
                                        contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
                                        formatter={(value, name) => [formatCurrency(Number(value ?? 0)), String(name)]}
                                    />
                                    <Legend wrapperStyle={{ fontSize: 11 }} />
                                    <Line type="monotone" dataKey="net_worth" name="Net Worth" stroke="#10b981" dot={false} strokeWidth={2} />
                                    <Line type="monotone" dataKey="assets" name="Assets" stroke="#22d3ee" dot={false} strokeWidth={1.5} />
                                    <Line type="monotone" dataKey="liabilities" name="Liabilities" stroke="#f59e0b" dot={false} strokeWidth={1.5} />
                                </ComposedChart>
                            </ResponsiveContainer>
                        </div>
                    </div>
                );
            case 'kpi':
                return (
                    <div className="space-y-4">
                        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                            {kpiCards.map((card) => (
                                <div key={card.label} className="bg-slate-800/50 border border-slate-700 p-3 min-h-24">
                                    <p className="text-[10px] text-slate-500 uppercase">{card.label}</p>
                                    <p className={`text-lg font-mono-nums mt-2 ${kpiTone(card.status as 'good' | 'warn' | 'bad')}`}>
                                        {card.value}
                                    </p>
                                </div>
                            ))}
                        </div>

                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <div className="flex items-center justify-between gap-3 mb-3">
                                <h3 className="text-xs text-slate-400 uppercase tracking-wider">Role Balances</h3>
                                <span className="text-[10px] text-slate-500">
                                    Idle: <span className="font-mono-nums text-amber-300">{formatOptionalCurrency(summary?.idle_money)}</span>
                                </span>
                            </div>
                            <div className="overflow-x-auto">
                                <table className="w-full text-xs">
                                    <thead>
                                        <tr className="border-b border-slate-800">
                                            <th className="p-2 text-left text-slate-500 uppercase font-medium">Role</th>
                                            <th className="p-2 text-right text-slate-500 uppercase font-medium">Balance</th>
                                            <th className="p-2 text-right text-slate-500 uppercase font-medium">Target</th>
                                            <th className="p-2 text-left text-slate-500 uppercase font-medium">Status</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(summary?.idle_money_by_role ?? []).map((row) => (
                                            <tr key={row.role} className="border-b border-slate-800/50">
                                                <td className="p-2 text-slate-200 capitalize">{row.role}</td>
                                                <td className="p-2 text-right font-mono-nums text-slate-300">{formatCurrency(row.balance)}</td>
                                                <td className="p-2 text-right font-mono-nums text-slate-500">{row.target == null ? '-' : formatCurrency(row.target)}</td>
                                                <td className={`p-2 ${row.status === 'Idle' || row.status === 'Over' ? 'text-amber-300' : row.status === 'Short' ? 'text-rose-300' : 'text-emerald-300'}`}>
                                                    {row.status}
                                                    {row.idle_component > 0 && (
                                                        <span className="ml-2 font-mono-nums text-slate-500">+{formatCurrency(row.idle_component)}</span>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                );
            case 'variance':
                return (
                    <div className="bg-slate-800/30 border border-slate-700 p-4 space-y-2">
                        {(variance?.items ?? []).map((item: any, idx: number) => (
                            <div key={idx} className="grid grid-cols-4 gap-2 text-xs">
                                <span className="text-slate-300">{item.category}</span>
                                <span className="font-mono-nums text-slate-400 text-right">{formatCurrency(item.budget)}</span>
                                <span className="font-mono-nums text-amber-400 text-right">{formatCurrency(item.actual)}</span>
                                <span className={`font-mono-nums text-right ${item.variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {formatCurrency(item.variance)}
                                </span>
                            </div>
                        ))}
                    </div>
                );
            case 'bs':
                return (
                    <div className="grid grid-cols-2 gap-4">
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs text-emerald-400 mb-2">Assets</h3>
                            {(balanceSheet?.assets ?? []).map((a: any, idx: number) => (
                                <div key={idx} className="flex justify-between text-xs">
                                    <span>{a.name}</span>
                                    <span className="font-mono-nums">{formatCurrency(a.balance)}</span>
                                </div>
                            ))}
                        </div>
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs text-rose-400 mb-2">Liabilities</h3>
                            {(balanceSheet?.liabilities ?? []).map((l: any, idx: number) => (
                                <div key={idx} className="flex justify-between text-xs">
                                    <span>{l.name}</span>
                                    <span className="font-mono-nums">{formatCurrency(l.balance)}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                );
            case 'pl':
                return (
                    <div className="space-y-3">
                        <div className="flex justify-end">
                            <label className="flex items-center gap-2 text-xs text-slate-400">
                                <input
                                    type="checkbox"
                                    checked={plRollup}
                                    onChange={(event) => setPlRollup(event.target.checked)}
                                />
                                Roll up child categories
                            </label>
                        </div>
                    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
                    <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs text-emerald-400 mb-2">Income</h3>
                            {(profitLoss?.income ?? []).map((i: any, idx: number) => (
                                <div key={idx} className="flex justify-between text-xs">
                                    <span>{i.category}</span>
                                    <span className="font-mono-nums text-emerald-400">+{formatCurrency(i.amount)}</span>
                                </div>
                            ))}
                        </div>
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs text-rose-400 mb-2">Expenses</h3>
                            {(profitLoss?.expenses ?? []).map((e: any, idx: number) => (
                                <div key={idx} className="flex justify-between gap-2 text-xs py-1">
                                    <span>{e.category}</span>
                                    <div className="flex items-center gap-2">
                                        {(() => {
                                            const prev = previousExpenseMap.get(String(e.category).toLowerCase()) || 0;
                                            const delta = prev > 0 ? ((e.amount - prev) / prev) * 100 : null;
                                            const color = delta === null || Math.abs(delta) <= 5
                                                ? 'text-slate-400 border-slate-700'
                                                : delta > 0
                                                    ? 'text-rose-400 border-rose-900'
                                                    : 'text-emerald-400 border-emerald-900';
                                            return (
                                                <span className={`text-[10px] px-1.5 border ${color}`}>
                                                    {delta === null ? 'new' : `${delta > 0 ? '+' : ''}${Math.round(delta)}%`}
                                                </span>
                                            );
                                        })()}
                                        <span className="font-mono-nums text-rose-400">-{formatCurrency(e.amount)}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div className="bg-slate-800/30 border border-slate-700 p-4 min-h-72">
                            <h3 className="text-xs text-cyan-400 mb-2">Expense Mix</h3>
                            <ResponsiveContainer width="100%" height={260}>
                                <PieChart>
                                    <Pie
                                        data={fixedVariableData}
                                        dataKey="amount"
                                        nameKey="name"
                                        innerRadius={36}
                                        outerRadius={58}
                                        paddingAngle={2}
                                    >
                                        <Cell fill="#f59e0b" />
                                        <Cell fill="#22d3ee" />
                                    </Pie>
                                    <Pie
                                        data={pieExpenses}
                                        dataKey="amount"
                                        nameKey="category"
                                        innerRadius={72}
                                        outerRadius={102}
                                        label={(props: any) => props.category}
                                    >
                                        {pieExpenses.map((_: any, idx: number) => (
                                            <Cell key={idx} fill={categoryColor(idx, pieExpenses.length)} />
                                        ))}
                                    </Pie>
                                    <Tooltip
                                        contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
                                        formatter={(value, name) => [formatCurrency(Number(value ?? 0)), String(name)]}
                                    />
                                </PieChart>
                            </ResponsiveContainer>
                        </div>
                    </div>
                    </div>
                );
            case 'reconcile': {
                const discrepancies = reconcileResult?.discrepancies ?? reconcileResult?.fixed_accounts ?? [];
                const isOk = reconcileResult?.status === 'ok';
                const hasDiscrepancies = reconcileResult?.status === 'discrepancies_found';

                return (
                    <div className="space-y-4">
                        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 bg-slate-800/30 border border-slate-700 p-4">
                            <div>
                                <div className="flex items-center gap-2 mb-1">
                                    <span className={`text-[10px] uppercase px-2 py-1 border ${isOk
                                        ? 'text-emerald-400 border-emerald-800 bg-emerald-950/40'
                                        : hasDiscrepancies
                                            ? 'text-rose-400 border-rose-800 bg-rose-950/40'
                                            : 'text-slate-400 border-slate-700 bg-slate-900/60'
                                        }`}>
                                        {reconcileResult?.status ?? 'Not Checked'}
                                    </span>
                                    <span className="text-[10px] text-slate-500">
                                        Last verified: {lastVerified || '—'}
                                    </span>
                                </div>
                                <p className="text-xs text-slate-400">
                                    Journal entries are compared with stored account balances.
                                </p>
                            </div>
                            <div className="flex gap-2">
                                <button
                                    onClick={handleRunReconcile}
                                    disabled={reconcileLoading}
                                    className="px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-xs text-white"
                                >
                                    {reconcileLoading ? 'Running...' : 'Run Check'}
                                </button>
                                <button
                                    onClick={handleFixReconcile}
                                    disabled={reconcileLoading || !hasDiscrepancies}
                                    className="px-3 py-2 bg-rose-700 hover:bg-rose-600 disabled:opacity-40 text-xs text-white"
                                >
                                    Auto Fix
                                </button>
                            </div>
                        </div>

                        {isOk && (
                            <div className="border border-emerald-900 bg-emerald-950/20 p-4 text-xs text-emerald-300">
                                Account balances match journal-entry truth.
                            </div>
                        )}

                        {hasDiscrepancies && (
                            <div className="border border-amber-900 bg-amber-950/20 p-4 text-xs text-amber-200 space-y-1">
                                <p>Possible causes include direct database edits, retroactive transaction bugs, or interrupted sync work.</p>
                                <p>When none apply, export data before deeper investigation.</p>
                            </div>
                        )}

                        {discrepancies.length > 0 && (
                            <div className="border border-slate-700 overflow-x-auto">
                                <table className="w-full text-xs">
                                    <thead className="bg-slate-900/80">
                                        <tr className="border-b border-slate-800">
                                            <th className="text-left p-2 text-slate-500 uppercase font-medium">Account</th>
                                            <th className="text-left p-2 text-slate-500 uppercase font-medium">Type</th>
                                            <th className="text-right p-2 text-slate-500 uppercase font-medium">Stored</th>
                                            <th className="text-right p-2 text-slate-500 uppercase font-medium">Calculated</th>
                                            <th className="text-right p-2 text-slate-500 uppercase font-medium">Difference</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {discrepancies.map((item) => (
                                            <tr key={item.account_id} className="border-b border-slate-800/50">
                                                <td className="p-2 text-slate-200">{item.account_name}</td>
                                                <td className="p-2 text-slate-400">{item.account_type}</td>
                                                <td className="p-2 text-right font-mono-nums">{formatCurrency(item.stored_balance)}</td>
                                                <td className="p-2 text-right font-mono-nums">{formatCurrency(item.calculated_balance)}</td>
                                                <td className={`p-2 text-right font-mono-nums ${item.difference >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                    {item.difference >= 0 ? '+' : ''}{formatCurrency(item.difference)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                );
            }
            case 'capsules':
                return (
                    <div className="space-y-2">
                        {capsules.map((c, idx) => (
                            <div key={idx} className="bg-slate-800/30 border border-slate-700 p-3 text-xs flex justify-between">
                                <span>{c.name}</span>
                                <span className="font-mono-nums text-purple-400">{formatCurrency(c.current_balance)}</span>
                            </div>
                        ))}
                    </div>
                );
            case 'report':
                return (
                    <div className="space-y-3">
                        <div className="bg-slate-800/30 border border-slate-700 p-4 text-xs">
                            <p>Period: {monthlyReport?.period}</p>
                            <p>Net Worth: <span className="font-mono-nums">{formatCurrency(monthlyReport?.summary?.net_worth ?? 0)}</span></p>
                            <p>Period P/L: <span className="font-mono-nums">{formatCurrency(monthlyReport?.summary?.monthly_pl ?? 0)}</span></p>
                            <p>Savings Rate: <span className="font-mono-nums">{monthlyReport?.summary?.savings_rate ?? 0}%</span></p>
                        </div>
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <p className="text-xs text-slate-400 mb-2">Anomalies</p>
                            {(monthlyReport?.anomalies ?? []).map((a: any, idx: number) => (
                                <div key={idx} className="text-xs flex justify-between py-1">
                                    <span>{a.category}</span>
                                    <span className="font-mono-nums">{a.overage_pct}%</span>
                                </div>
                            ))}
                        </div>
                    </div>
                );
            case 'review':
                return (
                    <div className="space-y-4">
                        <div className="grid grid-cols-3 gap-3">
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Period P/L</p>
                                <p className={`text-lg font-mono-nums ${(monthlyReport?.summary?.monthly_pl ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {formatCurrency(monthlyReport?.summary?.monthly_pl ?? 0)}
                                </p>
                            </div>
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Savings Rate</p>
                                <p className="text-lg font-mono-nums text-cyan-400">{monthlyReport?.summary?.savings_rate ?? 0}%</p>
                            </div>
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Anomalies</p>
                                <p className="text-lg font-mono-nums text-amber-400">{monthlyReport?.anomalies?.length ?? 0}</p>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="bg-slate-800/30 border border-slate-700 p-4">
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-2">
                                    Reflection
                                </label>
                                <textarea
                                    value={reviewDraft.reflection}
                                    onChange={(e) => setReviewDraft({ ...reviewDraft, reflection: e.target.value })}
                                    placeholder="What happened in this period? What should be kept or corrected?"
                                    className="w-full min-h-48 bg-slate-900 border border-slate-700 px-3 py-2 text-xs text-slate-200 resize-y focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div className="bg-slate-800/30 border border-slate-700 p-4">
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-2">
                                    Next Actions
                                </label>
                                <textarea
                                    value={reviewDraft.next_actions}
                                    onChange={(e) => setReviewDraft({ ...reviewDraft, next_actions: e.target.value })}
                                    placeholder="Budget changes, spending rules, transfers, or follow-up actions for the next period."
                                    className="w-full min-h-48 bg-slate-900 border border-slate-700 px-3 py-2 text-xs text-slate-200 resize-y focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                        </div>

                        <div className="bg-slate-800/30 border border-slate-700 p-4 space-y-3">
                            <div className="flex items-center justify-between gap-3">
                                <p className="text-xs text-slate-400">Action Builder</p>
                                <button onClick={handleProcessDueActions} className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-white text-[10px]">
                                    Process Due
                                </button>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
                                <select
                                    value={actionDraft.kind}
                                    onChange={(event) => setActionDraft({ ...actionDraft, kind: event.target.value as ReviewActionKind })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                                >
                                    <option value="set_budget">Set Budget</option>
                                    <option value="add_recurring">Add Recurring</option>
                                    <option value="pause_recurring">Pause Recurring</option>
                                    <option value="boost_allocation">Boost Allocation</option>
                                    <option value="change_capsule_contribution">Capsule Contribution</option>
                                </select>
                                <input
                                    type="month"
                                    value={actionDraft.target_period || nextMonthPeriod()}
                                    onChange={(event) => setActionDraft({ ...actionDraft, target_period: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                                />
                                <input
                                    value={actionDraft.description}
                                    onChange={(event) => setActionDraft({ ...actionDraft, description: event.target.value })}
                                    placeholder="Description"
                                    className="md:col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                                />
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                                {actionDraft.kind === 'set_budget' && (
                                    <>
                                        <select value={actionDraft.account_id} onChange={(event) => setActionDraft({ ...actionDraft, account_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                            <option value="">Expense account</option>
                                            {accounts.filter((account) => account.account_type === 'expense').map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                                        </select>
                                        <input type="number" value={actionDraft.amount} onChange={(event) => setActionDraft({ ...actionDraft, amount: event.target.value })} placeholder="Amount" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                                    </>
                                )}
                                {actionDraft.kind === 'add_recurring' && (
                                    <>
                                        <input value={actionDraft.name} onChange={(event) => setActionDraft({ ...actionDraft, name: event.target.value })} placeholder="Name" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                                        <input type="number" value={actionDraft.amount} onChange={(event) => setActionDraft({ ...actionDraft, amount: event.target.value })} placeholder="Amount" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                                        <select value={actionDraft.from_account_id} onChange={(event) => setActionDraft({ ...actionDraft, from_account_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                            <option value="">From</option>
                                            {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                                        </select>
                                        <select value={actionDraft.to_account_id} onChange={(event) => setActionDraft({ ...actionDraft, to_account_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                            <option value="">To</option>
                                            {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                                        </select>
                                    </>
                                )}
                                {actionDraft.kind === 'pause_recurring' && (
                                    <select value={actionDraft.recurring_id} onChange={(event) => setActionDraft({ ...actionDraft, recurring_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                        <option value="">Recurring rule</option>
                                        {recurringItems.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                                    </select>
                                )}
                                {actionDraft.kind === 'boost_allocation' && (
                                    <>
                                        <input type="number" value={actionDraft.life_event_id} onChange={(event) => setActionDraft({ ...actionDraft, life_event_id: event.target.value })} placeholder="Goal ID" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                                        <select value={actionDraft.account_id} onChange={(event) => setActionDraft({ ...actionDraft, account_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                            <option value="">Asset account</option>
                                            {accounts.filter((account) => account.account_type === 'asset').map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                                        </select>
                                        <input type="number" value={actionDraft.delta_percent} onChange={(event) => setActionDraft({ ...actionDraft, delta_percent: event.target.value })} placeholder="+%" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                                    </>
                                )}
                                {actionDraft.kind === 'change_capsule_contribution' && (
                                    <>
                                        <select value={actionDraft.capsule_id} onChange={(event) => setActionDraft({ ...actionDraft, capsule_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                            <option value="">Capsule</option>
                                            {capsules.map((capsule) => <option key={capsule.id} value={capsule.id}>{capsule.name}</option>)}
                                        </select>
                                        <input type="number" value={actionDraft.monthly_contribution} onChange={(event) => setActionDraft({ ...actionDraft, monthly_contribution: event.target.value })} placeholder="Monthly contribution" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                                    </>
                                )}
                                <button onClick={handleCreateAction} disabled={actionSaving} className="bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white text-xs px-3 py-1.5">
                                    {actionSaving ? 'Queueing...' : 'Queue Action'}
                                </button>
                            </div>

                            <div className="space-y-2">
                                {monthlyActions.length === 0 ? (
                                    <p className="text-xs text-slate-500">No queued review actions.</p>
                                ) : monthlyActions.map((action) => (
                                    <div key={action.id} className="flex items-center justify-between gap-3 border-t border-slate-800 pt-2 text-xs">
                                        <div className="min-w-0">
                                            <p className="text-slate-300 truncate">{action.description || action.kind}</p>
                                            <p className="text-[10px] text-slate-600">{action.kind} / {action.target_period} / {action.status}</p>
                                            {typeof action.result?.error === 'string' && <p className="text-[10px] text-rose-300">{action.result.error}</p>}
                                        </div>
                                        <div className="flex gap-2">
                                            <button disabled={action.status === 'applied'} onClick={() => handleApplyReviewAction(action.id)} className="px-2 py-1 bg-emerald-800 disabled:opacity-40 text-white">Apply</button>
                                            <button disabled={action.status === 'skipped'} onClick={() => handleSkipReviewAction(action.id)} className="px-2 py-1 bg-slate-700 disabled:opacity-40 text-white">Skip</button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <div className="flex items-center justify-between mb-3">
                                <p className="text-xs text-slate-400">Report Signals</p>
                                <span className="text-[10px] text-slate-600">
                                    Last saved: {periodReview?.updated_at || periodReview?.created_at || 'Not saved yet'}
                                </span>
                            </div>
                            <div className="space-y-2">
                                {(monthlyReport?.action_proposals ?? []).length === 0 ? (
                                    <p className="text-xs text-slate-500">No automatic action proposals for this period.</p>
                                ) : (
                                    (monthlyReport?.action_proposals ?? []).map((proposal) => (
                                        <div key={proposal.id} className="flex items-center justify-between gap-3 text-xs border-b border-slate-800 pb-2">
                                            <div className="min-w-0">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-slate-300">{proposal.description}</span>
                                                    {proposal.applied && (
                                                        <span className="inline-flex items-center gap-1 text-[10px] text-emerald-400 border border-emerald-900 bg-emerald-950/20 px-1.5 py-0.5">
                                                            <Check size={10} />
                                                            Applied
                                                        </span>
                                                    )}
                                                </div>
                                                <p className="text-[10px] text-slate-600 mt-1">
                                                    {proposal.kind} · {proposal.auto_executable ? 'auto executable' : 'review required'}
                                                </p>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <span className="font-mono-nums text-cyan-400 whitespace-nowrap">{formatCurrency(proposal.amount ?? 0)}</span>
                                                {proposal.auto_executable ? (
                                                    <button
                                                        type="button"
                                                        onClick={() => handleApplyProposal(proposal)}
                                                        disabled={proposal.applied || applyingProposalId === proposal.id}
                                                        className="px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 text-white text-[10px] font-bold"
                                                    >
                                                        {proposal.applied ? 'Applied' : applyingProposalId === proposal.id ? 'Applying...' : 'Apply'}
                                                    </button>
                                                ) : (
                                                    <button
                                                        type="button"
                                                        onClick={() => onNavigate?.('strategy')}
                                                        className="px-3 py-1.5 bg-cyan-700 hover:bg-cyan-600 text-white text-[10px] font-bold"
                                                    >
                                                        Open in Strategy
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>

                        <button
                            onClick={handleSaveReview}
                            disabled={reviewSaving}
                            className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white py-2 text-xs font-bold flex items-center justify-center gap-2"
                        >
                            <Save size={14} />
                            {reviewSaving ? 'Saving...' : 'Save Period Review'}
                        </button>
                    </div>
                );
            case 'actions':
                return (
                    <div className="space-y-4">
                        <div className="bg-slate-800/30 border border-slate-700 p-4 space-y-3">
                            <div className="flex items-center justify-between gap-3">
                                <p className="text-xs text-slate-400">Action Builder</p>
                                <button onClick={handleProcessDueActions} className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-white text-[10px]">
                                    Process Due
                                </button>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
                                <select
                                    value={actionDraft.kind}
                                    onChange={(event) => setActionDraft({ ...actionDraft, kind: event.target.value as ReviewActionKind })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                                >
                                    <option value="set_budget">Set Budget</option>
                                    <option value="add_recurring">Add Recurring</option>
                                    <option value="pause_recurring">Pause Recurring</option>
                                    <option value="boost_allocation">Boost Allocation</option>
                                    <option value="change_capsule_contribution">Capsule Contribution</option>
                                </select>
                                <input
                                    type="month"
                                    value={actionDraft.target_period || nextMonthPeriod()}
                                    onChange={(event) => setActionDraft({ ...actionDraft, target_period: event.target.value })}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                                />
                                <input
                                    value={actionDraft.description}
                                    onChange={(event) => setActionDraft({ ...actionDraft, description: event.target.value })}
                                    placeholder="Description"
                                    className="md:col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                                />
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                                <select value={actionDraft.account_id} onChange={(event) => setActionDraft({ ...actionDraft, account_id: event.target.value })} className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs">
                                    <option value="">Account</option>
                                    {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                                </select>
                                <input type="number" value={actionDraft.amount} onChange={(event) => setActionDraft({ ...actionDraft, amount: event.target.value })} placeholder="Amount" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                                <input value={actionDraft.name} onChange={(event) => setActionDraft({ ...actionDraft, name: event.target.value })} placeholder="Name" className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                                <button onClick={handleCreateAction} disabled={actionSaving} className="bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white text-xs px-3 py-1.5">
                                    {actionSaving ? 'Queueing...' : 'Queue Action'}
                                </button>
                            </div>
                        </div>

                        <div className="bg-slate-800/30 border border-slate-700 p-4 space-y-2">
                            <p className="text-xs text-slate-400">Queued Actions</p>
                            {monthlyActions.length === 0 ? (
                                <p className="text-xs text-slate-500">No queued review actions.</p>
                            ) : monthlyActions.map((action) => (
                                <div key={action.id} className="flex items-center justify-between gap-3 border-t border-slate-800 pt-2 text-xs">
                                    <div className="min-w-0">
                                        <p className="text-slate-300 truncate">{action.description || action.kind}</p>
                                        <p className="text-[10px] text-slate-600">{action.kind} / {action.target_period} / {action.status}</p>
                                        {typeof action.result?.error === 'string' && <p className="text-[10px] text-rose-300">{action.result.error}</p>}
                                    </div>
                                    <div className="flex gap-2">
                                        <button disabled={action.status === 'applied'} onClick={() => handleApplyReviewAction(action.id)} className="px-2 py-1 bg-emerald-800 disabled:opacity-40 text-white">Apply</button>
                                        <button disabled={action.status === 'skipped'} onClick={() => handleSkipReviewAction(action.id)} className="px-2 py-1 bg-slate-700 disabled:opacity-40 text-white">Skip</button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                );
            default:
                return null;
        }
    };

    return (
        <div className="h-full flex flex-col p-4 overflow-auto">
            <div className="flex flex-col gap-3 mb-4 flex-shrink-0">
                <div className="flex flex-col min-[760px]:flex-row min-[760px]:items-center justify-between gap-3">
                    <div className="inline-flex border border-slate-800 bg-slate-900/70 w-fit">
                        <button
                            type="button"
                            onClick={() => setAnalysisMode('portfolio')}
                            className={`px-4 py-2 text-xs font-medium ${analysisMode === 'portfolio' ? 'bg-emerald-950/40 text-emerald-300 border-b border-emerald-500' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/40'}`}
                        >
                            Portfolio
                        </button>
                        <button
                            type="button"
                            onClick={() => setAnalysisMode('period')}
                            className={`px-4 py-2 text-xs font-medium ${analysisMode === 'period' ? 'bg-emerald-950/40 text-emerald-300 border-b border-emerald-500' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/40'}`}
                        >
                            Period Review
                        </button>
                    </div>

                    <div className="flex items-center gap-2">
                        {analysisMode === 'period' && (
                            <div className="flex flex-wrap items-center justify-end gap-2">
                                <select
                                    value={periodPreset}
                                    onChange={(event) => {
                                        const nextPreset = event.target.value as PeriodPreset;
                                        setPeriodPreset(nextPreset);
                                        if (nextPreset !== 'custom') {
                                            const nextRange = getPresetRange(nextPreset);
                                            setPeriodStartDate(nextRange.start);
                                            setPeriodEndDate(nextRange.end);
                                        }
                                    }}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-200"
                                >
                                    <option value="thisMonth">This Month</option>
                                    <option value="lastMonth">Last Month</option>
                                    <option value="thisQuarter">This Quarter</option>
                                    <option value="ytd">YTD</option>
                                    <option value="thisYear">This Year</option>
                                    <option value="last12Months">Last 12 Months</option>
                                    <option value="custom">Custom</option>
                                </select>
                                <input
                                    type="date"
                                    value={periodStartDate}
                                    onChange={(event) => {
                                        setPeriodPreset('custom');
                                        setPeriodStartDate(event.target.value);
                                    }}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-200"
                                />
                                <span className="text-xs text-slate-600">to</span>
                                <input
                                    type="date"
                                    value={periodEndDate}
                                    onChange={(event) => {
                                        setPeriodPreset('custom');
                                        setPeriodEndDate(event.target.value);
                                    }}
                                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-200"
                                />
                            </div>
                        )}
                        <button onClick={fetchData} className="p-1.5 hover:bg-slate-800 text-slate-400 flex items-center gap-1 text-xs" disabled={loading}>
                            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                            Refresh
                        </button>
                    </div>
                </div>
            </div>

            <TabPanel
                tabs={analysisMode === 'portfolio' ? PORTFOLIO_TABS : PERIOD_TABS}
                activeTab={analysisMode === 'portfolio' ? portfolioTab : periodTab}
                onTabChange={analysisMode === 'portfolio' ? setPortfolioTab : setPeriodTab}
            >
                <div className="p-4">{renderTabContent()}</div>
            </TabPanel>
        </div>
    );
}
