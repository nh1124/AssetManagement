import { useEffect, useMemo, useRef, useState } from 'react';
import { Archive, Calendar, Check, ChevronUp, Edit2, Flag, Info, Plus, RefreshCw, Save, Sparkles, Trash2, TrendingUp, X } from 'lucide-react';
import { Area, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
    applyMilestonesFromSimulation,
    compareSimulationScenarios,
    createCapsuleHolding,
    createGoal,
    createGoalCapsule,
    createMilestone,
    createSimulationScenario,
    deleteCapsuleHolding,
    deleteGoal,
    deleteMilestone,
    deleteSimulationScenario,
    getAccounts,
    getMilestones,
    getGoalDashboard,
    getGoalCapsules,
    getCapsules,
    getRoadmapProjection,
    getSimulationScenarios,
    previewMilestonesFromSimulation,
    runMonteCarloSimulation,
    updateCapsuleHolding,
    updateGoal,
    updateMilestone,
} from '../api';
import { useToast } from '../components/Toast';
import { useClient } from '../context/ClientContext';
import { formatCompactCurrency, formatCurrency as formatCurrencyWithSetting } from '../utils/currency';
import { PRIORITY_COLORS, priorityLabel } from '../utils/priority';
import type {
    Account,
    ContributionScheduleItem,
    ContributionScheduleKind,
    CapsuleHolding,
    Capsule,
    LifeEvent,
    Milestone,
    MilestoneSimulationBasis,
    MilestoneSimulationInterval,
    MilestoneSimulationMode,
    MilestoneSimulationPreview,
    MonteCarloResult,
    RoadmapEntry,
    RoadmapProjection,
    SimulationScenario,
    SimulationScenarioCompareItem,
} from '../types';

interface DashboardData {
    events: LifeEvent[];
    simulation_params?: {
        annual_return: number;
        inflation: number;
        monthly_savings: number;
    };
}

type RoadmapChartPoint = {
    label: string;
    sort: number;
    actual?: number;
    p10?: number;
    p50?: number;
    p90?: number;
    band?: number;
    liability?: number;
    risk?: boolean;
};

type GoalTab = 'summary' | 'simulation' | 'milestone' | 'assetAllocation';
type GoalScope = 'all' | 'goal';
type ProjectionView = 'projection' | 'monteCarlo' | 'combined';
type AllRoadmapView = 'roadmap' | 'riskBand' | 'combined';
type ContributionDraft = ContributionScheduleItem & { id: string };

const GOAL_TABS: Array<{ id: GoalTab; label: string }> = [
    { id: 'summary', label: 'Summary' },
    { id: 'simulation', label: 'Simulation' },
    { id: 'milestone', label: 'Milestone' },
    { id: 'assetAllocation', label: 'AssetAllocation' },
];

const emptyEventForm = {
    name: '',
    start_date: '',
    target_date: '',
    target_amount: '',
    priority: 2 as 1 | 2 | 3,
    note: '',
};

const statusTone = (status?: string) => {
    if (status === 'On Track') return 'text-emerald-300 border-emerald-800 bg-emerald-950/30';
    if (status === 'At Risk') return 'text-amber-300 border-amber-800 bg-amber-950/30';
    return 'text-rose-300 border-rose-800 bg-rose-950/30';
};

const getErrorDetail = (error: unknown, fallback: string) => {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    return detail || fallback;
};

export default function Goal() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const currentCurrency = currentClient?.general_settings?.currency || 'JPY';
    const formatCurrency = (value: number | undefined | null) => formatCurrencyWithSetting(value, currentCurrency);
    const formatCompact = (value: number | undefined | null) => formatCompactCurrency(value, currentCurrency);
    const [dashboard, setDashboard] = useState<DashboardData | null>(null);
    const [selectedGoal, setSelectedGoal] = useState<LifeEvent | null>(null);
    const [capsules, setCapsules] = useState<Capsule[]>([]);
    const [selectedScope, setSelectedScope] = useState<GoalScope>('all');
    const [activeGoalTab, setActiveGoalTab] = useState<GoalTab>('simulation');
    const [projectionView, setProjectionView] = useState<ProjectionView>('combined');
    const [allRoadmapView, setAllRoadmapView] = useState<AllRoadmapView>('combined');
    const [milestones, setMilestones] = useState<Milestone[]>([]);
    const [eventForm, setEventForm] = useState(emptyEventForm);
    const [editingEvent, setEditingEvent] = useState<LifeEvent | null>(null);
    const [showEventModal, setShowEventModal] = useState(false);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [holdingForm, setHoldingForm] = useState({ account_id: '', held_amount: '', note: '' });
    const [holdingEdits, setHoldingEdits] = useState<Record<number, string>>({});
    const [milestoneForm, setMilestoneForm] = useState({ date: '', target_amount: '', note: '' });
    const [simParams, setSimParams] = useState({ annual_return: 5, inflation: 2 });
    const [contributions, setContributions] = useState<ContributionDraft[]>([
        { id: 'base-monthly', kind: 'monthly', amount: 50000, note: '' },
    ]);
    const goalSimStoreRef = useRef<Record<number, {
        simParams: { annual_return: number; inflation: number };
        contributions: ContributionDraft[];
    }>>({});
    const prevGoalIdRef = useRef<number | undefined>(undefined);
    const [roadmapInterval, setRoadmapInterval] = useState<'auto' | 'monthly' | 'quarterly' | 'annual'>('auto');
    const [roadmapTableEntries, setRoadmapTableEntries] = useState<RoadmapEntry[]>([]);
    const [monteCarlo, setMonteCarlo] = useState<MonteCarloResult | null>(null);
    const [roadmapProjection, setRoadmapProjection] = useState<RoadmapProjection | null>(null);
    const [milestonePlan, setMilestonePlan] = useState<{
        basis: MilestoneSimulationBasis;
        interval: MilestoneSimulationInterval;
        mode: MilestoneSimulationMode;
        n_simulations: number;
    }>({ basis: 'p50', interval: 'annual', mode: 'replace', n_simulations: 1000 });
    const [milestonePreview, setMilestonePreview] = useState<MilestoneSimulationPreview | null>(null);
    const [milestonePlanLoading, setMilestonePlanLoading] = useState(false);
    const [editingMilestoneNoteId, setEditingMilestoneNoteId] = useState<number | null>(null);
    const [editingNoteText, setEditingNoteText] = useState('');
    const [expandedSnapshotId, setExpandedSnapshotId] = useState<number | null>(null);
    const [scenarios, setScenarios] = useState<SimulationScenario[]>([]);
    const [scenarioName, setScenarioName] = useState('');
    const [compareMode, setCompareMode] = useState(false);
    const [compareScenarioIds, setCompareScenarioIds] = useState<{ a: number | null; b: number | null }>({ a: null, b: null });
    const [compareResult, setCompareResult] = useState<SimulationScenarioCompareItem[] | null>(null);
    const [compareLoading, setCompareLoading] = useState(false);
    const [compareSeriesVisibility, setCompareSeriesVisibility] = useState({
        p10: false,
        p50: true,
        p90: false,
        deterministic: false,
    });
    const [loading, setLoading] = useState(false);
    const [simLoading, setSimLoading] = useState(false);
    const [roadmapLoading, setRoadmapLoading] = useState(false);
    const [deleteModal, setDeleteModal] = useState<{
        goalId: number;
        goalName: string;
        capsules: Array<{ id: number; name: string; current_balance: number; account_id: number | null }>;
        transferAccountId: string;
        confirming: boolean;
        assetAccounts: Account[];
    } | null>(null);

    const selectedGoalId = selectedGoal?.id;

    const simulationContributionSchedule = useMemo<ContributionScheduleItem[]>(() =>
        contributions
            .filter((item) => Number(item.amount) > 0)
            .map((item) => ({
                kind: item.kind,
                amount: Math.max(0, Number(item.amount) || 0),
                month: item.kind === 'yearly' ? (item.month ?? 6) : null,
                date: item.kind === 'one_time' ? (item.date || null) : null,
                note: item.note || null,
            })),
    [contributions]);

    const baseMonthlyEquivalent = useMemo(() =>
        contributions
            .filter((item) => item.kind === 'monthly')
            .reduce((sum, item) => sum + Math.max(0, Number(item.amount) || 0), 0),
    [contributions]);

    const monthlyEquivalentForSelectedGoal = useMemo(() => {
        if (!selectedGoal) return baseMonthlyEquivalent;
        const targetDate = new Date(`${selectedGoal.target_date}T00:00:00`);
        const now = new Date();
        const horizonYears = Math.max((targetDate.getTime() - now.getTime()) / (365.25 * 24 * 60 * 60 * 1000), 1 / 12);
        const total = simulationContributionSchedule.reduce((sum, item) => {
            if (item.kind === 'monthly') return sum + item.amount * 12 * horizonYears;
            if (item.kind === 'yearly') return sum + item.amount * horizonYears;
            if (item.kind === 'one_time') {
                if (!item.date) return sum + item.amount;
                const itemDate = new Date(`${item.date}T00:00:00`);
                return itemDate >= now && itemDate <= targetDate ? sum + item.amount : sum;
            }
            return sum;
        }, 0);
        return total / horizonYears / 12;
    }, [selectedGoal, baseMonthlyEquivalent, simulationContributionSchedule]);

    const simulationContextParams = useMemo(() => ({
        annual_return: simParams.annual_return,
        inflation: simParams.inflation,
        monthly_savings: monthlyEquivalentForSelectedGoal,
        contribution_schedule: simulationContributionSchedule,
        allocation_mode: 'direct' as const,
    }), [simParams.annual_return, simParams.inflation, monthlyEquivalentForSelectedGoal, simulationContributionSchedule]);

    const compareChartData = useMemo(() => {
        if (!compareResult || compareResult.length !== 2) return [] as Array<Record<string, number | string>>;
        const [a, b] = compareResult;
        const maxYears = Math.max(
            a.year_by_year.p50.length,
            b.year_by_year.p50.length,
            a.deterministic_yearly.length,
            b.deterministic_yearly.length,
        );
        const aDetByYear = new Map<number, number>(a.deterministic_yearly.map((p) => [Math.round(p.year), p.end_balance]));
        const bDetByYear = new Map<number, number>(b.deterministic_yearly.map((p) => [Math.round(p.year), p.end_balance]));
        const points: Array<Record<string, number | string>> = [];
        for (let y = 0; y < maxYears; y += 1) {
            const row: Record<string, number | string> = { label: y === 0 ? 'Today' : `+${y}y`, year: y };
            if (a.year_by_year.p10[y] != null) row.a_p10 = a.year_by_year.p10[y];
            if (a.year_by_year.p50[y] != null) row.a_p50 = a.year_by_year.p50[y];
            if (a.year_by_year.p90[y] != null) row.a_p90 = a.year_by_year.p90[y];
            if (aDetByYear.has(y)) row.a_det = aDetByYear.get(y) as number;
            if (b.year_by_year.p10[y] != null) row.b_p10 = b.year_by_year.p10[y];
            if (b.year_by_year.p50[y] != null) row.b_p50 = b.year_by_year.p50[y];
            if (b.year_by_year.p90[y] != null) row.b_p90 = b.year_by_year.p90[y];
            if (bDetByYear.has(y)) row.b_det = bDetByYear.get(y) as number;
            row.target = selectedGoal?.target_amount ?? 0;
            points.push(row);
        }
        return points;
    }, [compareResult, selectedGoal?.target_amount]);

    // Load per-goal sim params when the selected goal changes; save when user edits them
    useEffect(() => {
        if (!selectedGoalId) return;
        if (prevGoalIdRef.current !== selectedGoalId) {
            // Goal switched — load stored values or reset to defaults
            prevGoalIdRef.current = selectedGoalId;
            const stored = goalSimStoreRef.current[selectedGoalId];
            if (stored) {
                setSimParams(stored.simParams);
                setContributions(stored.contributions);
            } else {
                setSimParams({ annual_return: 5, inflation: 2 });
                setContributions([{ id: 'base-monthly', kind: 'monthly', amount: 50000, note: '' }]);
            }
        } else {
            // Same goal — user edited params, persist to store
            goalSimStoreRef.current[selectedGoalId] = { simParams, contributions };
        }
    }, [selectedGoalId, simParams, contributions]);

    const fetchScenarios = async (goalId: number) => {
        try {
            const data = await getSimulationScenarios(goalId);
            setScenarios(data);
        } catch (error) {
            console.error('Failed to load scenarios:', error);
        }
    };

    useEffect(() => {
        if (!selectedGoalId) {
            setScenarios([]);
            setCompareScenarioIds({ a: null, b: null });
            setCompareResult(null);
            setCompareMode(false);
            return;
        }
        fetchScenarios(selectedGoalId);
    }, [selectedGoalId]);

    const contributionsToDrafts = (items: ContributionScheduleItem[]): ContributionDraft[] => (
        items.length > 0
            ? items.map((it, idx) => ({
                id: `${it.kind}-${idx}-${Date.now()}`,
                kind: it.kind,
                amount: Number(it.amount) || 0,
                month: it.month ?? null,
                date: it.date ?? null,
                note: it.note ?? '',
            }))
            : [{ id: 'base-monthly', kind: 'monthly', amount: 0, note: '' }]
    );

    const handleSaveScenario = async () => {
        if (!selectedGoal || !scenarioName.trim()) return;
        try {
            const created = await createSimulationScenario({
                life_event_id: selectedGoal.id,
                name: scenarioName.trim(),
                description: null,
                annual_return: simParams.annual_return,
                inflation: simParams.inflation,
                monthly_savings: monthlyEquivalentForSelectedGoal,
                contribution_schedule: simulationContributionSchedule,
                allocation_mode: selectedScope === 'goal' ? 'direct' : 'weighted',
            });
            setScenarios((prev) => [created, ...prev]);
            setScenarioName('');
            showToast('Scenario saved', 'success');
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to save scenario'), 'error');
        }
    };

    const handleLoadScenario = (scenario: SimulationScenario) => {
        setSimParams({
            annual_return: Number(scenario.annual_return),
            inflation: Number(scenario.inflation),
        });
        setContributions(contributionsToDrafts(scenario.contribution_schedule || []));
        showToast(`Loaded scenario: ${scenario.name}`, 'success');
    };

    const handleDeleteScenario = async (scenarioId: number) => {
        if (!confirm('Delete this scenario?')) return;
        try {
            await deleteSimulationScenario(scenarioId);
            setScenarios((prev) => prev.filter((s) => s.id !== scenarioId));
            setCompareScenarioIds((prev) => ({
                a: prev.a === scenarioId ? null : prev.a,
                b: prev.b === scenarioId ? null : prev.b,
            }));
            showToast('Scenario deleted', 'info');
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to delete scenario'), 'error');
        }
    };

    const runScenarioCompare = async (a: number | null, b: number | null) => {
        if (!selectedGoal || !a || !b) return;
        setCompareLoading(true);
        try {
            const result = await compareSimulationScenarios(selectedGoal.id, [a, b]);
            setCompareResult(result);
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to compare scenarios'), 'error');
            setCompareResult(null);
        } finally {
            setCompareLoading(false);
        }
    };

    const loadSnapshotIntoSimulation = (snap: Record<string, unknown>) => {
        const annualReturn = Number(snap.annual_return ?? simParams.annual_return) || simParams.annual_return;
        const inflation = Number(snap.inflation_rate ?? simParams.inflation) || simParams.inflation;
        setSimParams({ annual_return: annualReturn, inflation });
        const items = Array.isArray(snap.contribution_schedule)
            ? (snap.contribution_schedule as ContributionScheduleItem[])
            : [];
        setContributions(contributionsToDrafts(items));
        setActiveGoalTab('simulation');
        showToast('Loaded snapshot into simulation', 'success');
    };

    const computeMilestoneDrift = (milestone: Pick<Milestone, 'date' | 'target_amount'>): { current: number; diff: number; pct: number } | null => {
        if (!roadmapProjection?.projection?.length) return null;
        const today = new Date();
        const milestoneDate = new Date(`${milestone.date}T00:00:00`);
        const yearsOffset = (milestoneDate.getTime() - today.getTime()) / (365.25 * 24 * 60 * 60 * 1000);
        if (yearsOffset < 0) return null;
        const points = roadmapProjection.projection;
        // points are ordered by year (0..N). Linear interpolate p50 at yearsOffset.
        let lower = points[0];
        let upper = points[points.length - 1];
        for (let i = 0; i < points.length - 1; i += 1) {
            if (points[i].year <= yearsOffset && points[i + 1].year >= yearsOffset) {
                lower = points[i];
                upper = points[i + 1];
                break;
            }
        }
        let current: number;
        if (lower.year === upper.year) {
            current = lower.p50;
        } else {
            const t = (yearsOffset - lower.year) / (upper.year - lower.year);
            current = lower.p50 + (upper.p50 - lower.p50) * t;
        }
        const target = milestone.target_amount || 0;
        const diff = current - target;
        const pct = target > 0 ? (diff / target) * 100 : 0;
        return { current, diff, pct };
    };

    const fetchGoalMilestones = async (goalId: number) => {
        setMilestones(await getMilestones(goalId));
    };

    const fetchAllMilestones = async () => {
        setMilestones(await getMilestones());
    };

    const fetchGoalWorkspace = async (preferredGoalId = selectedGoalId, scope: GoalScope = selectedScope) => {
        setLoading(true);
        try {
            // Always use 'annual' for chart data so MC year-by-year aligns correctly
            const baseDashboardData = await getGoalDashboard(
                simParams.annual_return,
                simParams.inflation,
                baseMonthlyEquivalent,
                simulationContributionSchedule,
                'weighted',
                'annual',
            );
            const preferredId = preferredGoalId ?? baseDashboardData.events[0]?.id;
            const directDashboardData = scope === 'goal' && preferredId
                ? await getGoalDashboard(
                    simParams.annual_return,
                    simParams.inflation,
                    baseMonthlyEquivalent,
                    simulationContributionSchedule,
                    'direct',
                    'annual',
                )
                : null;
            const [capsuleData, accountsData] = await Promise.all([getCapsules(), getAccounts('asset')]);
            setDashboard(baseDashboardData);
            setCapsules(capsuleData);
            setAccounts(accountsData as Account[]);

            const selectedEvents = directDashboardData?.events ?? baseDashboardData.events;
            const nextSelected = preferredId
                ? selectedEvents.find((goal: LifeEvent) => goal.id === preferredId)
                : selectedEvents[0];
            setSelectedGoal(nextSelected ?? null);
            if (scope === 'all') {
                await fetchAllMilestones();
            } else if (nextSelected) {
                await fetchGoalMilestones(nextSelected.id);
            } else {
                setMilestones([]);
            }
        } catch (error) {
            console.error('Failed to load goal workspace:', error);
            showToast('Failed to load goals', 'error');
        } finally {
            setLoading(false);
        }
    };

    const fetchRoadmapTable = async (goalId: number, interval: typeof roadmapInterval) => {
        try {
            const data = await getGoalDashboard(
                simParams.annual_return,
                simParams.inflation,
                baseMonthlyEquivalent,
                simulationContributionSchedule,
                'direct',
                interval,
            );
            const goal = (data.events as LifeEvent[]).find((e) => e.id === goalId);
            setRoadmapTableEntries(goal?.roadmap ?? []);
        } catch {
            setRoadmapTableEntries([]);
        }
    };

    const fetchMonteCarlo = async (goalId: number) => {
        setSimLoading(true);
        try {
            setMonteCarlo(await runMonteCarloSimulation(goalId, 1000, simulationContextParams));
        } catch (error) {
            console.error('Failed to run Monte Carlo:', error);
            setMonteCarlo(null);
            showToast('Failed to run Monte Carlo simulation', 'error');
        } finally {
            setSimLoading(false);
        }
    };

    const fetchRoadmapProjection = async () => {
        setRoadmapLoading(true);
        try {
            setRoadmapProjection(await getRoadmapProjection({
                years: 30,
                annual_return: simParams.annual_return,
                inflation: simParams.inflation,
                monthly_savings: baseMonthlyEquivalent,
                contribution_schedule: simulationContributionSchedule,
                allocation_mode: selectedScope === 'goal' ? 'direct' : 'weighted',
            }));
        } catch (error) {
            console.error('Failed to load roadmap projection:', error);
            setRoadmapProjection(null);
            showToast('Failed to load roadmap projection', 'error');
        } finally {
            setRoadmapLoading(false);
        }
    };

    useEffect(() => {
        fetchGoalWorkspace();
    }, []);

    useEffect(() => {
        if (activeGoalTab !== 'simulation') return;
        const timer = window.setTimeout(() => {
            fetchGoalWorkspace(selectedGoalId, selectedScope);
            fetchRoadmapProjection();
        }, 300);
        return () => window.clearTimeout(timer);
    }, [activeGoalTab, selectedScope, simParams.annual_return, simParams.inflation, simulationContributionSchedule]);

    // Roadmap table with user-selected granularity (separate from chart which is always annual)
    useEffect(() => {
        if (activeGoalTab !== 'simulation' || selectedScope !== 'goal' || !selectedGoalId) {
            setRoadmapTableEntries([]);
            return;
        }
        const timer = window.setTimeout(() => fetchRoadmapTable(selectedGoalId, roadmapInterval), 300);
        return () => window.clearTimeout(timer);
    }, [activeGoalTab, selectedScope, selectedGoalId, roadmapInterval, simParams.annual_return, simParams.inflation, simulationContributionSchedule]);

    useEffect(() => {
        if (activeGoalTab === 'simulation' && selectedScope === 'goal' && selectedGoal?.id) fetchMonteCarlo(selectedGoal.id);
    }, [activeGoalTab, selectedScope, selectedGoal?.id, simulationContextParams]);

    useEffect(() => {
        if (selectedScope !== 'goal' || activeGoalTab !== 'simulation' || !selectedGoal?.id) {
            setMilestonePreview(null);
            return;
        }

        let cancelled = false;
        const timer = window.setTimeout(async () => {
            setMilestonePlanLoading(true);
            try {
                const preview = await previewMilestonesFromSimulation(selectedGoal.id, milestonePlanPayload());
                if (!cancelled) setMilestonePreview(preview);
            } catch (error) {
                if (!cancelled) setMilestonePreview(null);
            } finally {
                if (!cancelled) setMilestonePlanLoading(false);
            }
        }, 250);
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [
        selectedScope,
        activeGoalTab,
        selectedGoal?.id,
        simParams.annual_return,
        simParams.inflation,
        simulationContributionSchedule,
        milestonePlan.basis,
        milestonePlan.interval,
        milestonePlan.mode,
        milestonePlan.n_simulations,
    ]);

    const totals = useMemo(() => {
        const goals = dashboard?.events ?? [];
        return {
            target: goals.reduce((sum, goal) => sum + (goal.target_amount || 0), 0),
            gap: goals.reduce((sum, goal) => sum + Math.max(0, goal.gap || 0), 0),
            count: goals.length,
        };
    }, [dashboard]);

    const monteCarloChartData = useMemo(() => monteCarlo?.year_by_year.p50.map((p50, index) => ({
        year: index,
        p10: monteCarlo.year_by_year.p10[index] ?? p50,
        p50,
        p90: monteCarlo.year_by_year.p90[index] ?? p50,
    })) ?? [], [monteCarlo]);

    // How many roadmap periods equal one year (for sub-annual granularity overlay)
    const periodsPerYear = useMemo(() => {
        if (roadmapInterval === 'monthly') return 12;
        if (roadmapInterval === 'quarterly') return 4;
        if (roadmapInterval === 'annual') return 1;
        // 'auto': infer from entry count vs years remaining
        const totalPeriods = roadmapTableEntries.length - 1;
        const yr = selectedGoal?.years_remaining ?? 1;
        if (totalPeriods <= 0 || yr <= 0) return 1;
        const ratio = totalPeriods / yr;
        return ratio > 6 ? 12 : ratio > 2 ? 4 : 1;
    }, [roadmapInterval, roadmapTableEntries.length, selectedGoal?.years_remaining]);

    const goalProjectionChartData = useMemo(() => {
        const source = roadmapTableEntries.length > 0 ? roadmapTableEntries : (selectedGoal?.roadmap ?? []);
        return source.map((row, i) => {
            let p10: number | undefined;
            let p50: number | undefined;
            let p90: number | undefined;

            if (periodsPerYear > 1 && monteCarloChartData.length > 0) {
                // Linearly interpolate annual MC values across sub-annual periods
                // to avoid sudden jumps at year midpoints
                const yearFloat = i / periodsPerYear;
                const yr = Math.floor(yearFloat);
                const frac = yearFloat - yr;
                const mcCur = monteCarloChartData[yr];
                const mcNext = monteCarloChartData[yr + 1];
                if (mcCur) {
                    if (mcNext && frac > 0) {
                        p10 = mcCur.p10 + (mcNext.p10 - mcCur.p10) * frac;
                        p50 = mcCur.p50 + (mcNext.p50 - mcCur.p50) * frac;
                        p90 = mcCur.p90 + (mcNext.p90 - mcCur.p90) * frac;
                    } else {
                        ({ p10, p50, p90 } = mcCur);
                    }
                }
            } else {
                const mc = monteCarloChartData[row.year];
                p10 = mc?.p10;
                p50 = mc?.p50;
                p90 = mc?.p90;
            }

            return {
                ...row,
                periodIndex: i,
                target: selectedGoal?.target_amount ?? 0,
                p10,
                p50,
                p90,
                band: p10 !== undefined && p90 !== undefined ? Math.max(0, p90 - p10) : undefined,
            };
        });
    }, [monteCarloChartData, selectedGoal, roadmapTableEntries, periodsPerYear]);

    const roadmapChartData = useMemo<RoadmapChartPoint[]>(() => {
        if (!roadmapProjection) return [];
        const demandByYear = new Map(roadmapProjection.liability_demand.map((row) => [row.year, row.cumulative_target]));
        const history = roadmapProjection.history.map((row) => {
            const [year, month] = row.period.split('-').map(Number);
            return {
                label: row.period,
                sort: year + (month - 1) / 12,
                actual: row.net_worth,
            };
        });
        const projection = roadmapProjection.projection.map((row) => {
            const liability = demandByYear.get(row.year) ?? 0;
            return {
                label: String(row.year),
                sort: row.year,
                p10: row.p10,
                p50: row.p50,
                p90: row.p90,
                band: Math.max(0, row.p90 - row.p10),
                liability,
                risk: row.p50 < liability,
            };
        });
        return [...history, ...projection].sort((a, b) => a.sort - b.sort);
    }, [roadmapProjection]);

    const firstRoadmapRisk = useMemo(() => roadmapChartData.find((row) => row.risk), [roadmapChartData]);

    const roadmapTotals = useMemo(() => {
        const goals = roadmapProjection?.events ?? [];
        return {
            target: goals.reduce((sum, goal) => sum + (goal.target_amount || 0), 0),
            projected: goals.reduce((sum, goal) => sum + (goal.projected_amount || 0), 0),
        };
    }, [roadmapProjection]);

    const linkedCapsule = useMemo(
        () => (selectedGoal ? capsules.find((c) => c.life_event_id === selectedGoal.id) : undefined),
        [capsules, selectedGoal],
    );

    const openCreateModal = () => {
        setEditingEvent(null);
        setEventForm(emptyEventForm);
        setShowEventModal(true);
    };

    const openEditModal = (event: LifeEvent) => {
        setEditingEvent(event);
        setEventForm({
            name: event.name,
            start_date: event.start_date || '',
            target_date: event.target_date,
            target_amount: String(event.target_amount),
            priority: event.priority,
            note: event.note || '',
        });
        setShowEventModal(true);
    };

    const saveEvent = async () => {
        if (!eventForm.name.trim() || !eventForm.target_date || !eventForm.target_amount) return;
        const payload = {
            name: eventForm.name.trim(),
            start_date: eventForm.start_date || null,
            target_date: eventForm.target_date,
            target_amount: Number(eventForm.target_amount),
            priority: eventForm.priority,
            note: eventForm.note || null,
        };

        try {
            if (editingEvent) {
                await updateGoal(editingEvent.id, payload);
                showToast('Goal updated', 'success');
                setShowEventModal(false);
                await fetchGoalWorkspace(editingEvent.id);
            } else {
                const created = await createGoal(payload);
                showToast('Goal created', 'success');
                setShowEventModal(false);
                await fetchGoalWorkspace(created.id);
            }
        } catch (error) {
            showToast('Failed to save goal', 'error');
        }
    };

    const openDeleteModal = async (goalId: number, goalName: string) => {
        try {
            const [capsuleData, accountData] = await Promise.all([
                getGoalCapsules(goalId),
                getAccounts('asset'),
            ]);
            const assetAccounts = (accountData as Account[]).filter(
                (a) => a.role !== 'earmarked' && a.is_active,
            );
            setDeleteModal({
                goalId,
                goalName,
                capsules: capsuleData,
                transferAccountId: '',
                confirming: false,
                assetAccounts,
            });
        } catch {
            showToast('Failed to load capsule data', 'error');
        }
    };

    const confirmDelete = async () => {
        if (!deleteModal) return;
        const hasBalance = deleteModal.capsules.some((c) => c.current_balance > 0);
        if (hasBalance && !deleteModal.transferAccountId) {
            showToast('Please select a transfer account', 'warning');
            return;
        }
        setDeleteModal({ ...deleteModal, confirming: true });
        try {
            const transferId = deleteModal.transferAccountId
                ? Number(deleteModal.transferAccountId)
                : undefined;
            await deleteGoal(deleteModal.goalId, transferId);
            if (selectedGoal?.id === deleteModal.goalId) setSelectedGoal(null);
            showToast('Goal deleted', 'info');
            setDeleteModal(null);
            await fetchGoalWorkspace();
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to delete goal'), 'error');
            setDeleteModal({ ...deleteModal, confirming: false });
        }
    };

    const ensureSelectedGoalCapsule = async () => {
        if (!selectedGoal) return;
        try {
            await createGoalCapsule(selectedGoal.id);
            showToast('Goal capsule created', 'success');
            await fetchGoalWorkspace(selectedGoal.id);
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to create goal capsule'), 'error');
        }
    };

    const saveHolding = async () => {
        if (!linkedCapsule || !holdingForm.account_id || !holdingForm.held_amount) return;
        try {
            await createCapsuleHolding(linkedCapsule.id, {
                account_id: Number(holdingForm.account_id),
                held_amount: Number(holdingForm.held_amount),
                note: holdingForm.note || undefined,
            });
            setHoldingForm({ account_id: '', held_amount: '', note: '' });
            showToast('Holding saved', 'success');
            await fetchGoalWorkspace(selectedGoal?.id);
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to save holding'), 'error');
        }
    };

    const updateHolding = async (holdingId: number) => {
        if (!linkedCapsule) return;
        const newAmount = holdingEdits[holdingId];
        if (newAmount === undefined) return;
        try {
            await updateCapsuleHolding(linkedCapsule.id, holdingId, { held_amount: Number(newAmount) });
            showToast('Holding updated', 'success');
            await fetchGoalWorkspace(selectedGoal?.id);
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to update holding'), 'error');
        }
    };

    const removeHolding = async (holdingId: number) => {
        if (!linkedCapsule) return;
        try {
            await deleteCapsuleHolding(linkedCapsule.id, holdingId);
            showToast('Holding removed', 'info');
            await fetchGoalWorkspace(selectedGoal?.id);
        } catch (error) {
            showToast('Failed to remove holding', 'error');
        }
    };

    const createRoadmapMilestone = async () => {
        if (!selectedGoal || !milestoneForm.date || !milestoneForm.target_amount) return;
        try {
            await createMilestone({
                life_event_id: selectedGoal.id,
                date: milestoneForm.date,
                target_amount: Number(milestoneForm.target_amount),
                note: milestoneForm.note,
            });
            setMilestoneForm({ date: '', target_amount: '', note: '' });
            showToast('Milestone created', 'success');
            await fetchGoalMilestones(selectedGoal.id);
        } catch (error) {
            showToast('Failed to create milestone', 'error');
        }
    };

    const removeRoadmapMilestone = async (id: number) => {
        if (!confirm('Delete this milestone?')) return;
        try {
            await deleteMilestone(id);
            showToast('Milestone deleted', 'info');
            if (selectedGoal) await fetchGoalMilestones(selectedGoal.id);
        } catch (error) {
            showToast('Failed to delete milestone', 'error');
        }
    };

    const handleEditNote = (id: number, currentNote: string) => {
        setEditingMilestoneNoteId(id);
        setEditingNoteText(currentNote ?? '');
        setExpandedSnapshotId(null);
    };

    const handleCancelEdit = () => {
        setEditingMilestoneNoteId(null);
        setEditingNoteText('');
    };

    const handleSaveNote = async (id: number) => {
        try {
            await updateMilestone(id, { note: editingNoteText || null });
            setMilestones((prev) => prev.map((m) => m.id === id ? { ...m, note: editingNoteText || undefined } : m));
            setEditingMilestoneNoteId(null);
        } catch {
            showToast('Failed to update note', 'error');
        }
    };

    const milestonePlanPayload = () => ({
        ...milestonePlan,
        annual_return: simParams.annual_return,
        inflation: simParams.inflation,
        monthly_savings: monthlyEquivalentForSelectedGoal,
        contribution_schedule: simulationContributionSchedule,
        allocation_mode: selectedScope === 'goal' ? 'direct' as const : 'weighted' as const,
    });

    const previewSimulationMilestones = async () => {
        if (!selectedGoal) return;
        setMilestonePlanLoading(true);
        try {
            const preview = await previewMilestonesFromSimulation(selectedGoal.id, milestonePlanPayload());
            setMilestonePreview(preview);
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to preview simulation milestones'), 'error');
        } finally {
            setMilestonePlanLoading(false);
        }
    };

    const applySimulationMilestones = async () => {
        if (!selectedGoal) return;
        const verb = milestonePlan.mode === 'replace' ? 'replace existing milestones' : 'add new milestones';
        if (!confirm(`Apply this simulation plan and ${verb}?`)) return;
        setMilestonePlanLoading(true);
        try {
            const created = await applyMilestonesFromSimulation(selectedGoal.id, milestonePlanPayload());
            setMilestones(await getMilestones(selectedGoal.id));
            await previewSimulationMilestones();
            showToast(`Created ${created.length} simulation milestones`, 'success');
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to apply simulation milestones'), 'error');
        } finally {
            setMilestonePlanLoading(false);
        }
    };

    const addContribution = (kind: ContributionScheduleKind) => {
        setContributions((items) => [
            ...items,
            {
                id: `${kind}-${Date.now()}`,
                kind,
                amount: 0,
                month: kind === 'yearly' ? 6 : null,
                date: kind === 'one_time' ? new Date().toISOString().slice(0, 10) : null,
                note: '',
            },
        ]);
    };

    const updateContribution = (id: string, patch: Partial<ContributionDraft>) => {
        setContributions((items) => items.map((item) => item.id === id ? { ...item, ...patch } : item));
    };

    const removeContribution = (id: string) => {
        setContributions((items) => items.filter((item) => item.id !== id));
    };

    const renderScenariosPanel = () => (
        <div className="bg-slate-800/30 border border-slate-700 p-4">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-2"><Save size={12} /> Scenarios</h3>
                <span className="text-[10px] text-slate-600">{scenarios.length} saved</span>
            </div>
            <div className="grid grid-cols-[1fr_auto] gap-2 mb-3">
                <input
                    type="text"
                    title="Scenario name"
                    placeholder="Scenario name"
                    value={scenarioName}
                    onChange={(event) => setScenarioName(event.target.value)}
                    onKeyDown={(event) => { if (event.key === 'Enter') handleSaveScenario(); }}
                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                />
                <button
                    type="button"
                    onClick={handleSaveScenario}
                    disabled={!scenarioName.trim() || !selectedGoal}
                    className="px-3 py-1.5 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-40 text-white text-[10px] flex items-center gap-1"
                >
                    <Save size={11} /> Save
                </button>
            </div>
            {scenarios.length === 0 ? (
                <p className="text-[10px] text-slate-600">No saved scenarios yet. Save the current parameters above.</p>
            ) : (
                <div className="space-y-1 max-h-48 overflow-auto">
                    {scenarios.map((scenario) => (
                        <div key={scenario.id} className="grid grid-cols-[1fr_auto_auto] items-center gap-2 bg-slate-900/60 border border-slate-700 px-2 py-1.5 text-[10px]">
                            <div className="min-w-0">
                                <p className="text-slate-200 truncate">{scenario.name}</p>
                                <p className="text-slate-600 truncate">
                                    {scenario.annual_return}% / Inf {scenario.inflation}% / {scenario.contribution_schedule.length} items
                                </p>
                            </div>
                            <button
                                type="button"
                                title="Load into simulation"
                                onClick={() => handleLoadScenario(scenario)}
                                className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200"
                            >
                                Load
                            </button>
                            <button
                                type="button"
                                title="Delete scenario"
                                onClick={() => handleDeleteScenario(scenario.id)}
                                className="p-1 text-slate-500 hover:text-rose-400"
                            >
                                <Trash2 size={11} />
                            </button>
                        </div>
                    ))}
                </div>
            )}
            <div className="border-t border-slate-800 mt-3 pt-3 space-y-2">
                <label className="flex items-center gap-2 text-[10px] text-slate-400">
                    <input
                        type="checkbox"
                        checked={compareMode}
                        onChange={(event) => {
                            setCompareMode(event.target.checked);
                            if (!event.target.checked) setCompareResult(null);
                        }}
                    />
                    Compare two scenarios
                </label>
                {compareMode && (
                    <div className="space-y-2">
                        <div className="grid grid-cols-2 gap-2">
                            <select
                                title="Scenario A"
                                value={compareScenarioIds.a ?? ''}
                                onChange={(event) => {
                                    const next = event.target.value ? Number(event.target.value) : null;
                                    setCompareScenarioIds((prev) => ({ ...prev, a: next }));
                                    setCompareResult(null);
                                }}
                                className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-[10px] text-slate-200"
                            >
                                <option value="">Scenario A...</option>
                                {scenarios.map((s) => (
                                    <option key={s.id} value={s.id}>{s.name}</option>
                                ))}
                            </select>
                            <select
                                title="Scenario B"
                                value={compareScenarioIds.b ?? ''}
                                onChange={(event) => {
                                    const next = event.target.value ? Number(event.target.value) : null;
                                    setCompareScenarioIds((prev) => ({ ...prev, b: next }));
                                    setCompareResult(null);
                                }}
                                className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-[10px] text-slate-200"
                            >
                                <option value="">Scenario B...</option>
                                {scenarios.map((s) => (
                                    <option key={s.id} value={s.id}>{s.name}</option>
                                ))}
                            </select>
                        </div>
                        <button
                            type="button"
                            onClick={() => runScenarioCompare(compareScenarioIds.a, compareScenarioIds.b)}
                            disabled={!compareScenarioIds.a || !compareScenarioIds.b || compareScenarioIds.a === compareScenarioIds.b || compareLoading}
                            className="w-full px-3 py-1.5 bg-purple-700 hover:bg-purple-600 disabled:opacity-40 text-white text-[10px] flex items-center justify-center gap-1"
                        >
                            <TrendingUp size={11} /> {compareLoading ? 'Computing...' : 'Compare'}
                        </button>
                        <div className="flex flex-wrap gap-2 text-[10px] text-slate-400">
                            {(['p10', 'p50', 'p90', 'deterministic'] as const).map((key) => (
                                <label key={key} className="flex items-center gap-1">
                                    <input
                                        type="checkbox"
                                        checked={compareSeriesVisibility[key]}
                                        onChange={(event) => setCompareSeriesVisibility((prev) => ({ ...prev, [key]: event.target.checked }))}
                                    />
                                    {key === 'deterministic' ? 'Det' : key.toUpperCase()}
                                </label>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );

    const renderMilestonePlan = () => (
        <div className="bg-slate-800/30 border border-slate-700 p-4">
            <div className="flex flex-col gap-3 mb-3">
                <div className="flex items-center justify-between gap-3">
                    <h3 className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-2"><Sparkles size={14} /> Milestone Plan</h3>
                    <div className="flex gap-2">
                        <button
                            onClick={applySimulationMilestones}
                            disabled={milestonePlanLoading || !milestonePreview}
                            className="px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 text-white text-[10px]"
                        >
                            Adopt
                        </button>
                    </div>
                </div>
                <p className="text-[10px] text-slate-500">
                    Return {simParams.annual_return}%, Inflation {simParams.inflation}%, Income {formatCurrency(monthlyEquivalentForSelectedGoal)} / mo
                </p>
            </div>
            <div className="grid grid-cols-1 gap-2 mb-3">
                <label className="text-[10px] text-slate-500 uppercase">
                    Basis
                    <select value={milestonePlan.basis} onChange={(event) => {
                        setMilestonePlan({ ...milestonePlan, basis: event.target.value as MilestoneSimulationBasis });
                        setMilestonePreview(null);
                    }} className="mt-1 w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-200">
                        <option value="annual_plan">Annual Plan</option>
                        <option value="p50">Monte Carlo P50</option>
                        <option value="p10">Conservative P10</option>
                        <option value="p90">Upside P90</option>
                        <option value="deterministic">Deterministic</option>
                    </select>
                </label>
                <label className="text-[10px] text-slate-500 uppercase">
                    Interval
                    <select value={milestonePlan.interval} onChange={(event) => {
                        setMilestonePlan({ ...milestonePlan, interval: event.target.value as MilestoneSimulationInterval });
                        setMilestonePreview(null);
                    }} className="mt-1 w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-200">
                        <option value="annual">Annual</option>
                        <option value="semiannual">Semiannual</option>
                        <option value="quarterly">Quarterly</option>
                        <option value="target_only">Target only</option>
                    </select>
                </label>
                <label className="text-[10px] text-slate-500 uppercase">
                    Mode
                    <select value={milestonePlan.mode} onChange={(event) => {
                        setMilestonePlan({ ...milestonePlan, mode: event.target.value as MilestoneSimulationMode });
                        setMilestonePreview(null);
                    }} className="mt-1 w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-200">
                        <option value="replace">Replace existing</option>
                        <option value="add">Add only</option>
                    </select>
                </label>
            </div>
            <p className="text-xs text-slate-500">
                {milestonePlanLoading
                    ? 'Updating milestone candidates...'
                    : milestonePreview
                        ? `${milestonePreview.items.length} candidates shown below. ${milestonePreview.mode === 'replace' ? `${milestonePreview.existing_count} existing milestones will be replaced.` : 'Existing milestone dates will be kept.'}`
                        : 'Milestone candidates are generated from these settings.'}
            </p>
        </div>
    );

    const refreshSimulation = async () => {
        await Promise.all([
            fetchGoalWorkspace(selectedGoal?.id, selectedScope),
            fetchRoadmapProjection(),
        ]);
        if (selectedScope === 'goal' && selectedGoal?.id) await fetchMonteCarlo(selectedGoal.id);
    };

    const renderSummary = () => {
        if (!selectedGoal) return null;
        const fundedPct = selectedGoal.target_amount > 0 ? Math.min(100, ((selectedGoal.current_funded || 0) / selectedGoal.target_amount) * 100) : 0;
        const projectedPct = selectedGoal.target_amount > 0 ? Math.min(100, ((selectedGoal.projected_amount || 0) / selectedGoal.target_amount) * 100) : 0;

        return (
            <div className="space-y-4">
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                    <div className="bg-slate-800/40 border border-slate-700 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">Target</p>
                        <p className="font-mono-nums text-cyan-400">{formatCurrency(selectedGoal.target_amount)}</p>
                    </div>
                    <div className="bg-slate-800/40 border border-slate-700 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">Funded</p>
                        <p className="font-mono-nums text-emerald-400">{formatCurrency(selectedGoal.current_funded)}</p>
                    </div>
                    <div className="bg-slate-800/40 border border-slate-700 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">Gap</p>
                        <p className="font-mono-nums text-amber-400">{formatCurrency(selectedGoal.gap)}</p>
                    </div>
                    <div className="bg-slate-800/40 border border-slate-700 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">Status</p>
                        <p className="font-mono-nums text-slate-200">{selectedGoal.status || 'Not Started'}</p>
                    </div>
                </div>

                <div className="grid grid-cols-1 min-[1120px]:grid-cols-[1fr_320px] gap-4">
                    <div className="bg-slate-800/30 border border-slate-700 p-4">
                        <h3 className="text-[10px] text-slate-500 uppercase tracking-wider mb-4">Progress</h3>
                        <div className="space-y-4">
                            <div>
                                <div className="flex justify-between text-xs mb-1">
                                    <span className="text-slate-400">Funded</span>
                                    <span className="font-mono-nums text-emerald-400">{fundedPct.toFixed(1)}%</span>
                                </div>
                                <div className="h-2 bg-slate-950 border border-slate-800 overflow-hidden">
                                    <div className="h-full bg-emerald-500" style={{ width: `${fundedPct}%` }} />
                                </div>
                            </div>
                            <div>
                                <div className="flex justify-between text-xs mb-1">
                                    <span className="text-slate-400">Projected</span>
                                    <span className="font-mono-nums text-cyan-400">{projectedPct.toFixed(1)}%</span>
                                </div>
                                <div className="h-2 bg-slate-950 border border-slate-800 overflow-hidden">
                                    <div className="h-full bg-cyan-500" style={{ width: `${projectedPct}%` }} />
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="bg-slate-800/30 border border-slate-700 p-4">
                        <h3 className="text-[10px] text-slate-500 uppercase tracking-wider mb-3">Signals</h3>
                        <div className="space-y-2 text-xs">
                            <div className="flex justify-between gap-3">
                                <span className="text-slate-500">Priority</span>
                                <span className={PRIORITY_COLORS[selectedGoal.priority]}>{priorityLabel(selectedGoal.priority)}</span>
                            </div>
                            <div className="flex justify-between gap-3">
                                <span className="text-slate-500">Start Date</span>
                                <span className="font-mono-nums text-slate-300">{selectedGoal.start_date || '—'}</span>
                            </div>
                            <div className="flex justify-between gap-3">
                                <span className="text-slate-500">Target Date</span>
                                <span className="font-mono-nums text-slate-300">{selectedGoal.target_date}</span>
                            </div>
                            <div className="flex justify-between gap-3">
                                <span className="text-slate-500">Years Left</span>
                                <span className="font-mono-nums text-slate-300">{selectedGoal.years_remaining?.toFixed(1) ?? '0.0'}</span>
                            </div>
                            <div className="flex justify-between gap-3">
                                <span className="text-slate-500">Return</span>
                                <span className="font-mono-nums text-slate-300">{selectedGoal.weighted_return?.toFixed(1) ?? simParams.annual_return}%</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    const renderAllMilestones = () => (
        <div className="bg-slate-800/30 border border-slate-700 p-4">
            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1 mb-3"><Flag size={12} /> All Milestones</h3>
            <div className="space-y-2 max-h-[420px] overflow-auto">
                {milestones.length === 0 ? (
                    <p className="text-xs text-slate-600">No milestones yet.</p>
                ) : milestones.map((milestone) => (
                    <div key={milestone.id} className="grid grid-cols-1 md:grid-cols-[140px_1fr] items-center gap-3 bg-slate-900/60 border border-slate-700 p-2 text-xs">
                        <div className="flex items-center gap-2">
                            <Calendar size={12} className="text-slate-500" />
                            <span className="font-mono-nums text-slate-300">{milestone.date}</span>
                        </div>
                        <div className="min-w-0">
                            <span className="font-mono-nums text-emerald-400">{formatCurrency(milestone.target_amount)}</span>
                            {milestone.note && <span className="ml-3 text-slate-500">{milestone.note}</span>}
                            {milestone.source && milestone.source !== 'manual' && <span className="ml-3 text-[10px] text-cyan-500">{milestone.source}</span>}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );

    const renderAllSimulation = () => (
        <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Roadmap</p>
                    <p className={`font-mono-nums ${statusTone(roadmapProjection?.roadmap_progression).split(' ')[0]}`}>{roadmapProjection?.roadmap_progression ?? 'No Data'}</p>
                </div>
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Progression</p>
                    <p className="font-mono-nums text-cyan-400">{Math.round(roadmapProjection?.roadmap_progression_pct ?? 0)}%</p>
                </div>
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Demand</p>
                    <p className="font-mono-nums text-rose-300">{formatCurrency(roadmapTotals.target)}</p>
                </div>
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Projected</p>
                    <p className="font-mono-nums text-emerald-300">{formatCurrency(roadmapTotals.projected)}</p>
                </div>
            </div>

            <div className="bg-slate-800/30 border border-slate-700 p-4">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-3">
                    <h3 className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-2"><TrendingUp size={14} /> All Goals Roadmap</h3>
                    <div className="inline-flex border border-slate-700 bg-slate-900/80">
                        {([
                            ['roadmap', 'Roadmap'],
                            ['riskBand', 'Risk Band'],
                            ['combined', 'Combined'],
                        ] as Array<[AllRoadmapView, string]>).map(([id, label]) => (
                            <button
                                key={id}
                                onClick={() => setAllRoadmapView(id)}
                                className={`px-3 py-1.5 text-[10px] ${allRoadmapView === id ? 'bg-cyan-950/50 text-cyan-300' : 'text-slate-500 hover:text-slate-300'}`}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                </div>
                {roadmapLoading && roadmapChartData.length === 0 ? (
                    <p className="text-xs text-slate-500">Loading roadmap...</p>
                ) : (
                    <div className="h-[420px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <ComposedChart data={roadmapChartData} margin={{ top: 8, right: 16, bottom: 28, left: 8 }}>
                                <XAxis dataKey="label" tick={{ fontSize: 10 }} stroke="#64748b" interval="preserveStartEnd" minTickGap={24} />
                                <YAxis tick={{ fontSize: 10 }} stroke="#64748b" tickFormatter={formatCompact} width={70} />
                                <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 11 }} formatter={(value) => [formatCurrency(value as number), '']} />
                                <Legend verticalAlign="bottom" align="center" wrapperStyle={{ fontSize: 10, paddingTop: 14 }} />
                                {(allRoadmapView === 'riskBand' || allRoadmapView === 'combined') && <Area dataKey="p10" stackId="roadmap-band" stroke="none" fill="transparent" name="P10" />}
                                {(allRoadmapView === 'riskBand' || allRoadmapView === 'combined') && <Area dataKey="band" stackId="roadmap-band" stroke="none" fill="#22c55e" fillOpacity={0.12} name="P10-P90" />}
                                <Line type="monotone" dataKey="actual" stroke="#34d399" strokeWidth={2} dot={false} name="Actual Net Worth" connectNulls={false} />
                                {(allRoadmapView === 'riskBand' || allRoadmapView === 'combined') && <Line type="monotone" dataKey="p10" stroke="#f59e0b" dot={false} name="P10" connectNulls={false} />}
                                <Line type="monotone" dataKey="p50" stroke="#22d3ee" strokeWidth={2} strokeDasharray="6 4" dot={false} name="Projected P50" connectNulls={false} />
                                {(allRoadmapView === 'riskBand' || allRoadmapView === 'combined') && <Line type="monotone" dataKey="p90" stroke="#10b981" dot={false} name="P90" connectNulls={false} />}
                                {(allRoadmapView === 'roadmap' || allRoadmapView === 'combined') && <Line type="monotone" dataKey="liability" stroke="#fb7185" strokeWidth={2} dot={false} name="Liability Demand" connectNulls={false} />}
                                {firstRoadmapRisk && <ReferenceLine x={firstRoadmapRisk.label} stroke="#fb7185" strokeDasharray="4 4" />}
                            </ComposedChart>
                        </ResponsiveContainer>
                    </div>
                )}
                {firstRoadmapRisk && (
                    <p className="mt-2 text-xs text-rose-300">P50 falls below cumulative demand in {firstRoadmapRisk.label}.</p>
                )}
            </div>

            {renderAllMilestones()}
        </div>
    );

    const renderSimulation = () => {
        if (selectedScope === 'all') return renderAllSimulation();
        if (!selectedGoal) return null;

        return (
            <div className="grid grid-cols-1 min-[1120px]:grid-cols-[320px_1fr] gap-4">
                <section className="space-y-4">
                    <div className="bg-slate-800/30 border border-slate-700 p-4">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-2"><TrendingUp size={14} /> Assumptions</h3>
                            <button
                                onClick={refreshSimulation}
                                disabled={loading || simLoading}
                                className="p-1.5 hover:bg-slate-800 text-slate-400 disabled:opacity-50"
                                title="Refresh simulation"
                            >
                                <RefreshCw size={13} className={loading || simLoading ? 'animate-spin' : ''} />
                            </button>
                        </div>
                        <div className="space-y-3">
                            <label className="block text-xs text-slate-500">
                                Annual Return (%)
                                <input type="number" step="0.5" value={simParams.annual_return} onChange={(event) => setSimParams({ ...simParams, annual_return: Number(event.target.value) })} className="mt-1 w-full bg-slate-900 border border-slate-700 px-2 py-2 text-xs font-mono-nums" />
                            </label>
                            <label className="block text-xs text-slate-500">
                                Inflation (%)
                                <input type="number" step="0.5" value={simParams.inflation} onChange={(event) => setSimParams({ ...simParams, inflation: Number(event.target.value) })} className="mt-1 w-full bg-slate-900 border border-slate-700 px-2 py-2 text-xs font-mono-nums" />
                            </label>
                            <div className="border-t border-slate-800 pt-3 space-y-2">
                                <div className="flex items-center justify-between gap-2">
                                    <div>
                                        <p className="text-[10px] uppercase tracking-wider text-slate-500">Income Schedule</p>
                                        <p className="text-[10px] text-slate-600">≈ {formatCurrency(monthlyEquivalentForSelectedGoal)} / mo</p>
                                    </div>
                                    <div className="flex border border-slate-700">
                                        <button type="button" onClick={() => addContribution('monthly')} className="px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800" title="Add monthly savings"><Plus size={11} /></button>
                                        <button type="button" onClick={() => addContribution('yearly')} className="px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800 border-l border-slate-700" title="Add yearly bonus"><Calendar size={11} /></button>
                                        <button type="button" onClick={() => addContribution('one_time')} className="px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800 border-l border-slate-700" title="Add one-time contribution"><Archive size={11} /></button>
                                    </div>
                                </div>
                                {contributions.map((item) => (
                                    <div key={item.id} className="grid grid-cols-[72px_1fr_28px] gap-1.5 items-center">
                                        <select
                                            value={item.kind}
                                            title="Contribution type"
                                            onChange={(event) => updateContribution(item.id, {
                                                kind: event.target.value as ContributionScheduleKind,
                                                month: event.target.value === 'yearly' ? (item.month ?? 6) : null,
                                                date: event.target.value === 'one_time' ? (item.date || new Date().toISOString().slice(0, 10)) : null,
                                            })}
                                            className="bg-slate-900 border border-slate-700 px-1.5 py-1.5 text-[10px]"
                                        >
                                            <option value="monthly">Monthly</option>
                                            <option value="yearly">Bonus</option>
                                            <option value="one_time">One-time</option>
                                        </select>
                                        <div className="grid grid-cols-2 gap-1.5">
                                            <input
                                                type="number"
                                                step="10000"
                                                value={item.amount}
                                                onChange={(event) => updateContribution(item.id, { amount: Number(event.target.value) })}
                                                className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-[10px] font-mono-nums"
                                                placeholder="Amount"
                                            />
                                            {item.kind === 'yearly' ? (
                                                <select
                                                    value={item.month ?? 6}
                                                    title="Month of year"
                                                    onChange={(event) => updateContribution(item.id, { month: Number(event.target.value) })}
                                                    className="bg-slate-900 border border-slate-700 px-1.5 py-1.5 text-[10px]"
                                                >
                                                    {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                                                        <option key={m} value={m}>{m}月</option>
                                                    ))}
                                                </select>
                                            ) : item.kind === 'one_time' ? (
                                                <input
                                                    type="date"
                                                    title="Date of contribution"
                                                    value={item.date || ''}
                                                    onChange={(event) => updateContribution(item.id, { date: event.target.value })}
                                                    className="bg-slate-900 border border-slate-700 px-1.5 py-1.5 text-[10px]"
                                                />
                                            ) : (
                                                <div className="text-[10px] text-slate-600 px-2 py-1.5">per month</div>
                                            )}
                                        </div>
                                        <button onClick={() => removeContribution(item.id)} className="h-full border border-slate-700 text-slate-500 hover:text-rose-300 hover:border-rose-800" title="Remove">
                                            <Trash2 size={11} className="mx-auto" />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {renderScenariosPanel()}
                    {renderMilestonePlan()}

                    <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="bg-slate-800/40 border border-slate-700 p-2">
                            <p className="text-slate-500">Projected</p>
                            <p className="font-mono-nums text-cyan-400">{formatCurrency(selectedGoal.projected_amount)}</p>
                        </div>
                        <div className="bg-slate-800/40 border border-slate-700 p-2">
                            <p className="text-slate-500">Gap</p>
                            <p className="font-mono-nums text-amber-400">{formatCurrency(selectedGoal.gap)}</p>
                        </div>
                    </div>
                </section>

                <section className="space-y-4 min-w-0">
                    <div className="bg-slate-800/30 border border-slate-700 p-4">
                        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-3">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider">
                                Projection ({selectedGoal.weighted_return?.toFixed(1) || simParams.annual_return}% return)
                            </h3>
                            <div className="flex flex-wrap gap-2">
                                <div className="inline-flex border border-slate-700">
                                    {(['auto', 'monthly', 'quarterly', 'annual'] as const).map((iv) => (
                                        <button
                                            key={iv}
                                            type="button"
                                            onClick={() => setRoadmapInterval(iv)}
                                            className={`px-2 py-1 text-[10px] ${roadmapInterval === iv ? 'bg-slate-700 text-slate-100' : 'text-slate-500 hover:text-slate-300'}`}
                                        >
                                            {iv === 'auto' ? 'Auto' : iv.charAt(0).toUpperCase() + iv.slice(1)}
                                        </button>
                                    ))}
                                </div>
                                <div className="inline-flex border border-slate-700 bg-slate-900/80">
                                    {([
                                        ['projection', 'Projection'],
                                        ['monteCarlo', 'Monte Carlo'],
                                        ['combined', 'Combined'],
                                    ] as Array<[ProjectionView, string]>).map(([id, label]) => (
                                        <button
                                            key={id}
                                            onClick={() => setProjectionView(id)}
                                            className={`px-3 py-1.5 text-[10px] ${projectionView === id ? 'bg-cyan-950/50 text-cyan-300' : 'text-slate-500 hover:text-slate-300'}`}
                                        >
                                            {label}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                        {simLoading ? (
                            <p className="text-xs text-slate-500">Calculating...</p>
                        ) : (
                            <>
                                {monteCarlo && (
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-xs">
                                        <div className="bg-slate-900/60 border border-slate-700 p-2"><p className="text-slate-500">Success</p><p className="font-mono-nums text-emerald-400">{monteCarlo.probability}%</p></div>
                                        <div className="bg-slate-900/60 border border-slate-700 p-2"><p className="text-slate-500">P10</p><p className="font-mono-nums">{formatCurrency(monteCarlo.percentiles.p10)}</p></div>
                                        <div className="bg-slate-900/60 border border-slate-700 p-2"><p className="text-slate-500">P50</p><p className="font-mono-nums text-cyan-400">{formatCurrency(monteCarlo.percentiles.p50)}</p></div>
                                        <div className="bg-slate-900/60 border border-slate-700 p-2"><p className="text-slate-500">P90</p><p className="font-mono-nums text-emerald-400">{formatCurrency(monteCarlo.percentiles.p90)}</p></div>
                                    </div>
                                )}
                                <div className="h-[360px]">
                                    {compareMode && compareResult && compareResult.length === 2 ? (
                                        <ResponsiveContainer width="100%" height="100%">
                                            <ComposedChart data={compareChartData} margin={{ top: 8, right: 16, bottom: 34, left: 8 }}>
                                                <XAxis dataKey="label" tick={{ fontSize: 10 }} stroke="#64748b" />
                                                <YAxis tick={{ fontSize: 10 }} stroke="#64748b" tickFormatter={formatCompact} />
                                                <Tooltip
                                                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 11 }}
                                                    formatter={(value) => [formatCurrency(value as number), '']}
                                                />
                                                <Legend verticalAlign="bottom" align="center" wrapperStyle={{ fontSize: 10, paddingTop: 14 }} />
                                                {compareSeriesVisibility.p10 && <Line type="monotone" dataKey="a_p10" stroke="#fbbf24" name={`${compareResult[0].scenario_name} P10`} dot={false} connectNulls />}
                                                {compareSeriesVisibility.p50 && <Line type="monotone" dataKey="a_p50" stroke="#22d3ee" strokeWidth={2} name={`${compareResult[0].scenario_name} P50`} dot={false} connectNulls />}
                                                {compareSeriesVisibility.p90 && <Line type="monotone" dataKey="a_p90" stroke="#34d399" name={`${compareResult[0].scenario_name} P90`} dot={false} connectNulls />}
                                                {compareSeriesVisibility.deterministic && <Line type="monotone" dataKey="a_det" stroke="#22d3ee" strokeDasharray="4 3" name={`${compareResult[0].scenario_name} Det`} dot={false} connectNulls />}
                                                {compareSeriesVisibility.p10 && <Line type="monotone" dataKey="b_p10" stroke="#f87171" name={`${compareResult[1].scenario_name} P10`} dot={false} connectNulls />}
                                                {compareSeriesVisibility.p50 && <Line type="monotone" dataKey="b_p50" stroke="#a78bfa" strokeWidth={2} name={`${compareResult[1].scenario_name} P50`} dot={false} connectNulls />}
                                                {compareSeriesVisibility.p90 && <Line type="monotone" dataKey="b_p90" stroke="#86efac" name={`${compareResult[1].scenario_name} P90`} dot={false} connectNulls />}
                                                {compareSeriesVisibility.deterministic && <Line type="monotone" dataKey="b_det" stroke="#a78bfa" strokeDasharray="4 3" name={`${compareResult[1].scenario_name} Det`} dot={false} connectNulls />}
                                                <Line type="monotone" dataKey="target" stroke="#f97316" strokeDasharray="5 5" name="Target" dot={false} />
                                            </ComposedChart>
                                        </ResponsiveContainer>
                                    ) : (
                                    <ResponsiveContainer width="100%" height="100%">
                                        <ComposedChart data={goalProjectionChartData} margin={{ top: 8, right: 16, bottom: 34, left: 8 }}>
                                            <XAxis
                                                dataKey="label"
                                                tick={{ fontSize: 10 }}
                                                stroke="#64748b"
                                                interval={periodsPerYear > 1
                                                    ? Math.max(0, Math.ceil(goalProjectionChartData.length / 8) - 1)
                                                    : 0}
                                                label={periodsPerYear === 1
                                                    ? { value: 'Years', position: 'insideBottom', offset: -8, fontSize: 10 }
                                                    : undefined}
                                            />
                                            <YAxis tick={{ fontSize: 10 }} stroke="#64748b" tickFormatter={formatCompact} />
                                            <Tooltip
                                                content={({ active, payload, label }) => {
                                                    if (!active || !payload?.length) return null;
                                                    const HIDDEN = new Set(['band']);
                                                    const seen = new Set<string>();
                                                    const rows = payload.filter((p) => {
                                                        const key = p.dataKey as string;
                                                        if (HIDDEN.has(key) || seen.has(key)) return false;
                                                        seen.add(key);
                                                        return true;
                                                    });
                                                    return (
                                                        <div className="bg-slate-800 border border-slate-600 px-3 py-2 text-[11px]">
                                                            <p className="text-slate-400 mb-1">{label}</p>
                                                            {rows.map((p) => (
                                                                <div key={p.dataKey as string} className="flex justify-between gap-4" style={{ color: p.color }}>
                                                                    <span>{p.name}</span>
                                                                    <span className="font-mono-nums">{formatCurrency(p.value as number)}</span>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    );
                                                }}
                                            />
                                            <Legend verticalAlign="bottom" align="center" wrapperStyle={{ fontSize: 10, paddingTop: 14 }} />
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Area dataKey="p10" stackId="goal-band" stroke="none" fill="transparent" name="P10" legendType="none" />}
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Area dataKey="band" stackId="goal-band" stroke="none" fill="#22c55e" fillOpacity={0.12} name="P10–P90 Band" legendType="none" />}
                                            {(projectionView === 'projection' || projectionView === 'combined') && <Line type="monotone" dataKey="end_balance" stroke="#10b981" name="Projection" strokeWidth={2} dot={false} />}
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Line type="monotone" dataKey="p10" stroke="#f59e0b" name="P10" dot={false} connectNulls={true} />}
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Line type="monotone" dataKey="p50" stroke="#22d3ee" name="P50" dot={false} connectNulls={true} />}
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Line type="monotone" dataKey="p90" stroke="#10b981" name="P90" dot={false} connectNulls={true} />}
                                            <Line type="monotone" dataKey="target" stroke="#f97316" strokeDasharray="5 5" name="Target" dot={false} />
                                        </ComposedChart>
                                    </ResponsiveContainer>
                                    )}
                                </div>
                            </>
                        )}
                    </div>

                    <div className="bg-slate-800/30 border border-slate-700 overflow-hidden">
                        <div className="flex items-center justify-between px-3 py-2 bg-slate-800/50 border-b border-slate-700">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider">Roadmap</h3>
                        </div>
                        <div className="overflow-x-auto max-h-64">
                            <table className="w-full text-left text-[10px]">
                                <thead className="bg-slate-800 text-slate-500 uppercase sticky top-0">
                                    <tr>
                                        <th className="px-3 py-2 font-normal">Period</th>
                                        <th className="px-3 py-2 font-normal">Start</th>
                                        <th className="px-3 py-2 font-normal">Contribution</th>
                                        <th className="px-3 py-2 font-normal">Gain</th>
                                        <th className="px-3 py-2 font-normal">End</th>
                                        <th className="px-3 py-2 font-normal text-right">Coverage</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-800">
                                    {roadmapTableEntries.map((row, i) => (
                                        <tr key={i} className="hover:bg-slate-800/40">
                                            <td className="px-3 py-2 text-slate-400">{row.label ?? (row.year === 0 ? 'Current' : `Year ${row.year}`)}</td>
                                            <td className="px-3 py-2 font-mono-nums">{formatCurrency(row.start_balance)}</td>
                                            <td className="px-3 py-2 font-mono-nums text-cyan-400">+{formatCurrency(row.contribution)}</td>
                                            <td className="px-3 py-2 font-mono-nums text-emerald-400">+{formatCurrency(row.investment_gain)}</td>
                                            <td className="px-3 py-2 font-mono-nums text-slate-100">{formatCurrency(row.end_balance)}</td>
                                            <td className="px-3 py-2 text-right font-mono-nums">{row.goal_coverage}%</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    {renderMilestones()}
                </section>
            </div>
        );
    };

    const renderMilestones = () => {
        const showingPlan = selectedScope === 'goal' && activeGoalTab === 'simulation';
        const displayedMilestones = showingPlan ? (milestonePreview?.items ?? []) : milestones;

        return (
        <div className="bg-slate-800/30 border border-slate-700 p-4">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1">
                    <Flag size={12} /> {showingPlan ? 'Milestone Candidates' : 'Milestones'}
                </h3>
                {showingPlan && (
                    <div className="flex items-center gap-2">
                        {milestonePlanLoading && <span className="text-[10px] text-slate-600">Updating...</span>}
                        <button
                            onClick={applySimulationMilestones}
                            disabled={milestonePlanLoading || !milestonePreview}
                            className="inline-flex items-center gap-1 px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 text-white text-[10px]"
                        >
                            <Check size={12} /> Adopt
                        </button>
                    </div>
                )}
            </div>
            {!showingPlan && (
                <div className="grid grid-cols-12 gap-2 mb-3">
                    <input type="date" value={milestoneForm.date} onChange={(event) => setMilestoneForm({ ...milestoneForm, date: event.target.value })} className="col-span-12 md:col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                    <input type="number" placeholder="Target" value={milestoneForm.target_amount} onChange={(event) => setMilestoneForm({ ...milestoneForm, target_amount: event.target.value })} className="col-span-12 md:col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                    <input placeholder="Note" value={milestoneForm.note} onChange={(event) => setMilestoneForm({ ...milestoneForm, note: event.target.value })} className="col-span-12 md:col-span-4 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                    <button onClick={createRoadmapMilestone} className="col-span-12 md:col-span-2 bg-emerald-900/50 border border-emerald-800 text-emerald-300 text-xs">Add</button>
                </div>
            )}
            <div className="space-y-1 max-h-[520px] overflow-auto">
                {displayedMilestones.length === 0 ? (
                    <p className="text-xs text-slate-600">{showingPlan ? 'No candidate milestones for this plan.' : 'No milestones yet. Add one manually or adopt a simulation plan.'}</p>
                ) : displayedMilestones.map((milestone) => {
                    const milestoneId = (milestone as Milestone).id;
                    const isReal = !showingPlan && typeof milestoneId === 'number';
                    const isSimSrc = !!milestone.source && milestone.source !== 'manual';
                    const isEditing = isReal && editingMilestoneNoteId === milestoneId;
                    const isExpanded = isReal && expandedSnapshotId === milestoneId;
                    const snap = milestone.source_snapshot as Record<string, unknown> | null | undefined;
                    return (
                        <div key={isReal ? milestoneId : `${milestone.date}-${milestone.target_amount}`} className="border border-slate-700">
                            <div className="grid grid-cols-1 md:grid-cols-[140px_1fr_auto] items-center gap-2 bg-slate-900/60 p-2 text-xs">
                                {/* Date */}
                                <div className="flex items-center gap-2">
                                    <Calendar size={12} className="text-slate-500 shrink-0" />
                                    <span className="font-mono-nums text-slate-300">{milestone.date}</span>
                                </div>
                                {/* Amount + note */}
                                <div className="min-w-0 flex items-center gap-2">
                                    <span className="font-mono-nums text-emerald-400 shrink-0">{formatCurrency(milestone.target_amount)}</span>
                                    {isEditing ? (
                                        <input
                                            value={editingNoteText}
                                            onChange={(e) => setEditingNoteText(e.target.value)}
                                            onKeyDown={(e) => { if (e.key === 'Enter') handleSaveNote(milestoneId); if (e.key === 'Escape') handleCancelEdit(); }}
                                            className="flex-1 bg-slate-800 border border-slate-600 px-2 py-0.5 text-xs text-slate-200 min-w-0 outline-none focus:border-slate-400"
                                            placeholder="Add note..."
                                            autoFocus
                                        />
                                    ) : (
                                        <span className="text-slate-500 truncate">{milestone.note || ''}</span>
                                    )}
                                    {isSimSrc && !isEditing && (
                                        <span className="text-[10px] text-cyan-600 shrink-0">{milestone.source}</span>
                                    )}
                                </div>
                                {/* Actions */}
                                {isEditing ? (
                                    <div className="flex items-center gap-1.5 justify-self-end">
                                        <button type="button" title="Save note" onClick={() => handleSaveNote(milestoneId)} className="text-emerald-400 hover:text-emerald-300"><Check size={12} /></button>
                                        <button type="button" title="Cancel edit" onClick={handleCancelEdit} className="text-slate-500 hover:text-slate-300"><X size={12} /></button>
                                    </div>
                                ) : isReal ? (
                                    <div className="flex items-center gap-1.5 justify-self-end">
                                        {isSimSrc && snap && (
                                            <button
                                                type="button"
                                                onClick={() => setExpandedSnapshotId(isExpanded ? null : milestoneId)}
                                                className={isExpanded ? 'text-cyan-400' : 'text-slate-600 hover:text-cyan-400'}
                                                title="Show simulation parameters"
                                            >
                                                {isExpanded ? <ChevronUp size={12} /> : <Info size={12} />}
                                            </button>
                                        )}
                                        <button type="button" onClick={() => handleEditNote(milestoneId, milestone.note ?? '')} className="text-slate-600 hover:text-slate-300" title="Edit note"><Edit2 size={12} /></button>
                                        <button type="button" title="Delete milestone" onClick={() => removeRoadmapMilestone(milestoneId)} className="text-slate-600 hover:text-rose-400"><Trash2 size={12} /></button>
                                    </div>
                                ) : null}
                            </div>
                            {/* Simulation snapshot panel */}
                            {isExpanded && snap && (
                                <div className="border-t border-slate-700/60 bg-slate-950/60 px-3 py-2 text-[10px] text-slate-400 space-y-2">
                                    <div className="flex items-center justify-between gap-2">
                                        <div className="flex flex-wrap gap-x-4 gap-y-1">
                                            {snap.basis != null && <span>Basis <span className="text-slate-200 uppercase">{String(snap.basis)}</span></span>}
                                            {snap.annual_return != null && <span>Return <span className="text-slate-200">{String(snap.annual_return)}%</span></span>}
                                            {snap.inflation_rate != null && <span>Inflation <span className="text-slate-200">{String(snap.inflation_rate)}%</span></span>}
                                            {snap.monthly_savings != null && <span>Savings <span className="text-slate-200 font-mono-nums">{formatCurrency(snap.monthly_savings as number)}/mo</span></span>}
                                            {snap.current_funded != null && <span>Funded <span className="text-slate-200 font-mono-nums">{formatCurrency(snap.current_funded as number)}</span></span>}
                                            {snap.n_simulations != null && <span>Sims <span className="text-slate-200">{String(snap.n_simulations)}</span></span>}
                                        </div>
                                        <button
                                            type="button"
                                            title="Load these parameters into the Simulation tab"
                                            onClick={() => loadSnapshotIntoSimulation(snap)}
                                            className="shrink-0 inline-flex items-center gap-1 px-2 py-1 bg-cyan-900/40 hover:bg-cyan-800/60 border border-cyan-800 text-cyan-200 text-[10px]"
                                        >
                                            <TrendingUp size={11} /> Load into Simulation
                                        </button>
                                    </div>
                                    {Array.isArray(snap.contribution_schedule) && (snap.contribution_schedule as ContributionScheduleItem[]).length > 0 && (
                                        <div className="flex flex-wrap gap-1.5">
                                            {(snap.contribution_schedule as ContributionScheduleItem[]).map((item, idx) => (
                                                <span key={idx} className="bg-slate-800 border border-slate-700 px-1.5 py-0.5">
                                                    {item.kind === 'monthly' && `${formatCurrency(item.amount)}/mo`}
                                                    {item.kind === 'yearly' && `${formatCurrency(item.amount)} bonus (${item.month}月)`}
                                                    {item.kind === 'one_time' && `${formatCurrency(item.amount)} on ${item.date}`}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                    {(() => {
                                        const outlook = snap.goal_outlook as Record<string, unknown> | undefined;
                                        if (!outlook) return null;
                                        const projectedAtTarget = outlook.projected_at_target as number | undefined;
                                        const probability = outlook.probability_at_target as number | null | undefined;
                                        const percentiles = outlook.percentiles_at_target as { p10: number; p50: number; p90: number } | null | undefined;
                                        const yearsToTarget = outlook.years_to_target as number | undefined;
                                        return (
                                            <div className="border-t border-slate-800 pt-2 space-y-1">
                                                <p className="text-slate-500 uppercase tracking-wider text-[9px]">Goal Outlook (at target date)</p>
                                                <div className="flex flex-wrap gap-x-4 gap-y-1">
                                                    {projectedAtTarget != null && <span>Projected <span className="text-slate-200 font-mono-nums">{formatCurrency(projectedAtTarget)}</span></span>}
                                                    {probability != null && <span>Probability <span className="text-emerald-300 font-mono-nums">{Number(probability).toFixed(1)}%</span></span>}
                                                    {yearsToTarget != null && <span>Horizon <span className="text-slate-200 font-mono-nums">{Number(yearsToTarget).toFixed(1)}y</span></span>}
                                                </div>
                                                {percentiles && (
                                                    <div className="flex flex-wrap gap-x-4 gap-y-1">
                                                        <span>P10 <span className="text-amber-300 font-mono-nums">{formatCurrency(percentiles.p10)}</span></span>
                                                        <span>P50 <span className="text-cyan-300 font-mono-nums">{formatCurrency(percentiles.p50)}</span></span>
                                                        <span>P90 <span className="text-emerald-300 font-mono-nums">{formatCurrency(percentiles.p90)}</span></span>
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })()}
                                    {(() => {
                                        const drift = computeMilestoneDrift(milestone);
                                        if (!drift) return null;
                                        const tone = drift.diff > 0 ? 'text-emerald-300' : drift.diff < 0 ? 'text-rose-300' : 'text-slate-300';
                                        return (
                                            <div className="border-t border-slate-800 pt-2">
                                                <p className="text-slate-500 uppercase tracking-wider text-[9px]">Drift (saved → current P50)</p>
                                                <div className="flex flex-wrap gap-x-4 gap-y-1">
                                                    <span>Saved <span className="text-slate-200 font-mono-nums">{formatCurrency(milestone.target_amount)}</span></span>
                                                    <span>Current <span className="text-slate-200 font-mono-nums">{formatCurrency(drift.current)}</span></span>
                                                    <span>Δ <span className={`${tone} font-mono-nums`}>{drift.diff >= 0 ? '+' : ''}{formatCurrency(drift.diff)} ({drift.diff >= 0 ? '+' : ''}{drift.pct.toFixed(1)}%)</span></span>
                                                </div>
                                            </div>
                                        );
                                    })()}
                                    {snap.generated_at != null && (
                                        <p className="text-slate-600">Generated {String(snap.generated_at).slice(0, 10)}</p>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
        );
    };

    const renderAssetAllocation = () => {
        const holdings = linkedCapsule?.holdings ?? [];
        const holdingsTotal = holdings.reduce((s, h) => s + h.held_amount, 0);
        const assetAccounts = accounts.filter((a) => a.account_type === 'asset' && a.role !== 'earmarked');
        const capsuleProgress = linkedCapsule
            ? Math.min(100, (linkedCapsule.current_balance / (linkedCapsule.target_amount || 1)) * 100)
            : 0;

        return (
            <div className="space-y-4">
                {/* Section 1: Linked Capsule */}
                <div className="bg-slate-800/30 border border-slate-700 p-4">
                    <h3 className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1 mb-3">
                        <Archive size={12} /> Linked Capsule
                    </h3>
                    {!linkedCapsule ? (
                        <div className="bg-cyan-950/20 border border-cyan-800/50 p-3 flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs">
                            <div>
                                <p className="text-cyan-200">No linked capsule for this goal.</p>
                                <p className="text-[10px] text-slate-500 mt-1">Create a dedicated sinking fund to track physical holdings.</p>
                            </div>
                            <button type="button" onClick={ensureSelectedGoalCapsule} className="px-3 py-1.5 bg-cyan-700 hover:bg-cyan-600 text-white text-[10px]">
                                Create Capsule
                            </button>
                        </div>
                    ) : (
                        <div>
                            <div className="flex justify-between items-start gap-3">
                                <div>
                                    <p className="text-sm text-slate-100">{linkedCapsule.name}</p>
                                    <p className="text-[10px] text-slate-500 mt-0.5">
                                        Target {formatCurrency(linkedCapsule.target_amount)} / +{formatCurrency(linkedCapsule.monthly_contribution)} / mo
                                    </p>
                                </div>
                                <div className="text-right">
                                    <p className="text-lg font-mono-nums text-purple-400">{formatCurrency(linkedCapsule.current_balance)}</p>
                                    <p className="text-[10px] text-slate-500">{Math.round(capsuleProgress)}%</p>
                                </div>
                            </div>
                            <div className="h-1.5 bg-slate-900 rounded-full overflow-hidden mt-2">
                                <div className="h-full bg-purple-500" style={{ width: `${capsuleProgress}%` }} />
                            </div>
                        </div>
                    )}
                </div>

                {/* Section 2: Physical Holdings */}
                {linkedCapsule && (
                    <div className="bg-slate-800/30 border border-slate-700 p-4">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1">
                                <TrendingUp size={12} /> Physical Holdings
                            </h3>
                            <span className="text-[10px] font-mono-nums text-slate-400">
                                {formatCurrency(holdingsTotal)} / {formatCurrency(linkedCapsule.current_balance)}
                            </span>
                        </div>
                        <div className="space-y-2 mb-4">
                            {holdings.length === 0 ? (
                                <p className="text-xs text-slate-600">No holdings recorded. Add which accounts physically hold this capsule's funds.</p>
                            ) : (
                                holdings.map((h: CapsuleHolding) => {
                                    const editValue = holdingEdits[h.id] ?? String(h.held_amount);
                                    return (
                                        <div key={h.id} className="grid grid-cols-1 min-[640px]:grid-cols-[1fr_160px_auto] items-center gap-2 bg-slate-900/60 border border-slate-700 p-2 text-xs">
                                            <div className="min-w-0">
                                                <p className="text-slate-200 truncate">{h.account_name}</p>
                                                {h.note && <p className="text-[10px] text-slate-500">{h.note}</p>}
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <input
                                                    type="number"
                                                    title="Held amount"
                                                    placeholder="Amount"
                                                    value={editValue}
                                                    onChange={(e) => setHoldingEdits({ ...holdingEdits, [h.id]: e.target.value })}
                                                    className="w-full bg-slate-950 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                                                />
                                            </div>
                                            <div className="flex justify-end gap-2">
                                                <button type="button" onClick={() => updateHolding(h.id)} className="p-1.5 text-slate-500 hover:text-emerald-400" title="Save"><Check size={13} /></button>
                                                <button type="button" onClick={() => removeHolding(h.id)} className="p-1.5 text-slate-600 hover:text-rose-400" title="Remove holding"><Trash2 size={13} /></button>
                                            </div>
                                        </div>
                                    );
                                })
                            )}
                        </div>
                        <div className="grid grid-cols-12 gap-2 border-t border-slate-800 pt-3">
                            <select
                                title="Select account for holding"
                                value={holdingForm.account_id}
                                onChange={(e) => setHoldingForm({ ...holdingForm, account_id: e.target.value })}
                                className="col-span-12 md:col-span-5 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-300"
                            >
                                <option value="">Select account...</option>
                                {assetAccounts.map((a) => (
                                    <option key={a.id} value={a.id}>{a.name}</option>
                                ))}
                            </select>
                            <input
                                type="number"
                                title="Held amount"
                                placeholder="Amount"
                                value={holdingForm.held_amount}
                                onChange={(e) => setHoldingForm({ ...holdingForm, held_amount: e.target.value })}
                                className="col-span-8 md:col-span-4 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                            />
                            <button
                                type="button"
                                title="Add holding"
                                onClick={saveHolding}
                                disabled={!holdingForm.account_id || !holdingForm.held_amount}
                                className="col-span-4 md:col-span-3 bg-purple-900/50 border border-purple-800 text-purple-300 hover:bg-purple-900 disabled:opacity-40"
                            >
                                <Plus size={14} className="mx-auto" />
                            </button>
                        </div>
                    </div>
                )}

            </div>
        );
    };

    const renderActiveGoalTab = () => {
        if (selectedScope === 'all') return renderSimulation();
        switch (activeGoalTab) {
            case 'summary':
                return renderSummary();
            case 'simulation':
                return renderSimulation();
            case 'milestone':
                return renderMilestones();
            case 'assetAllocation':
                return renderAssetAllocation();
            default:
                return null;
        }
    };

    return (
        <div className="h-full overflow-auto p-4 space-y-4">
            <div className="flex justify-end">
                <button
                    onClick={openCreateModal}
                    className="bg-cyan-600 hover:bg-cyan-500 text-white px-3 py-2 text-xs font-medium flex items-center gap-2"
                >
                    <Plus size={14} /> Add Goal
                </button>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Goals</p>
                    <p className="text-lg text-slate-100 font-mono-nums">{totals.count}</p>
                </div>
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Target Total</p>
                    <p className="text-lg text-cyan-400 font-mono-nums">{formatCurrency(totals.target)}</p>
                </div>
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Remaining Gap</p>
                    <p className="text-lg text-amber-400 font-mono-nums">{formatCurrency(totals.gap)}</p>
                </div>
            </div>

            <div className="grid grid-cols-1 min-[960px]:grid-cols-[340px_1fr] gap-4 min-h-[640px]">
                <section className="bg-slate-900/60 border border-slate-800 flex flex-col min-h-0">
                    <div className="px-3 py-2 border-b border-slate-800 flex items-center justify-between">
                        <h2 className="text-xs text-slate-400 uppercase tracking-wider">Goals</h2>
                        {loading && <span className="text-[10px] text-slate-600">Loading...</span>}
                    </div>
                    <div className="flex-1 overflow-auto p-3 space-y-2">
                        <button
                            onClick={() => {
                                setSelectedScope('all');
                                setActiveGoalTab('simulation');
                                setMilestonePreview(null);
                                fetchGoalWorkspace(undefined, 'all');
                                fetchAllMilestones();
                                fetchRoadmapProjection();
                            }}
                            className={`w-full text-left border px-3 py-3 transition-colors ${selectedScope === 'all' ? 'border-cyan-700 bg-cyan-950/20' : 'border-slate-800 bg-slate-800/20 hover:bg-slate-800/50'}`}
                        >
                            <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                    <p className="text-sm text-slate-100 truncate">All Goals</p>
                                    <p className="text-[10px] text-slate-500 mt-1">Portfolio roadmap / aggregate liability demand</p>
                                </div>
                                <span className="text-[10px] text-slate-400 font-mono-nums">{Math.round(roadmapProjection?.roadmap_progression_pct ?? 0)}%</span>
                            </div>
                            <div className="h-1 bg-slate-900 rounded-full mt-3 overflow-hidden">
                                <div className="h-full bg-cyan-500" style={{ width: `${Math.min(100, roadmapProjection?.roadmap_progression_pct ?? 0)}%` }} />
                            </div>
                        </button>
                        {(dashboard?.events ?? []).length === 0 ? (
                            <div className="text-center text-xs text-slate-600 py-10">No goals yet. Create the first north star.</div>
                        ) : (
                            dashboard?.events.map((goal) => (
                                <button
                                    key={goal.id}
                                    onClick={() => {
                                        setSelectedScope('goal');
                                        setSelectedGoal(goal);
                                        setActiveGoalTab('summary');
                                        setMilestonePreview(null);
                                        fetchGoalWorkspace(goal.id, 'goal');
                                        fetchGoalMilestones(goal.id);
                                    }}
                                    className={`w-full text-left border px-3 py-3 transition-colors ${selectedScope === 'goal' && selectedGoal?.id === goal.id ? 'border-cyan-700 bg-cyan-950/20' : 'border-slate-800 bg-slate-800/20 hover:bg-slate-800/50'}`}
                                >
                                    <div className="flex items-start justify-between gap-2">
                                        <div className="min-w-0">
                                            <p className="text-sm text-slate-100 truncate">{goal.name}</p>
                                            <p className="text-[10px] text-slate-500 mt-1">
                                                {goal.target_date} / <span className={PRIORITY_COLORS[goal.priority]}>{priorityLabel(goal.priority)}</span>
                                            </p>
                                        </div>
                                        <span className="text-[10px] text-slate-400 font-mono-nums">{Math.round(goal.progress_percentage || 0)}%</span>
                                    </div>
                                    <div className="h-1 bg-slate-900 rounded-full mt-3 overflow-hidden">
                                        <div className="h-full bg-cyan-500" style={{ width: `${Math.min(100, goal.progress_percentage || 0)}%` }} />
                                    </div>
                                </button>
                            ))
                        )}
                    </div>
                </section>

                <section className="bg-slate-900/60 border border-slate-800 overflow-auto">
                    {selectedScope === 'goal' && !selectedGoal ? (
                        <div className="h-full flex items-center justify-center text-xs text-slate-600">Select or create a goal to edit its details.</div>
                    ) : (
                        <div className="p-4 space-y-4">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <p className="text-[10px] text-slate-500 uppercase">{selectedScope === 'all' ? 'Selected Scope' : 'Selected Goal'}</p>
                                    <h2 className="text-lg text-slate-100">{selectedScope === 'all' ? 'All Goals' : selectedGoal?.name}</h2>
                                    <p className="text-xs text-slate-500 mt-1">
                                        {selectedScope === 'all' ? 'Portfolio roadmap and aggregate liability demand.' : selectedGoal?.note || 'No note yet.'}
                                    </p>
                                </div>
                                {selectedScope === 'goal' && selectedGoal && (
                                    <div className="flex gap-2">
                                        <button onClick={() => openEditModal(selectedGoal)} className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300"><Edit2 size={14} /></button>
                                        <button onClick={() => openDeleteModal(selectedGoal.id, selectedGoal.name)} className="p-2 bg-slate-800 hover:bg-rose-950 text-slate-300 hover:text-rose-300"><Trash2 size={14} /></button>
                                    </div>
                                )}
                            </div>

                            {selectedScope === 'goal' && (
                                <div className="flex border-b border-slate-800 overflow-x-auto">
                                {GOAL_TABS.map((tab) => (
                                    <button
                                        key={tab.id}
                                        onClick={() => setActiveGoalTab(tab.id)}
                                        className={`px-4 py-2 text-xs font-medium whitespace-nowrap transition-colors ${activeGoalTab === tab.id ? 'text-cyan-300 border-b border-cyan-500 bg-slate-800/40' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/30'}`}
                                    >
                                        {tab.label}
                                    </button>
                                ))}
                                </div>
                            )}

                            {renderActiveGoalTab()}
                        </div>
                    )}
                </section>
            </div>

            {deleteModal && (
                <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
                    <div className="bg-slate-900 border border-rose-800/60 p-6 w-full max-w-md">
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-sm font-medium text-rose-300 flex items-center gap-2">
                                <Trash2 size={14} /> Delete Goal
                            </h2>
                            <button
                                onClick={() => setDeleteModal(null)}
                                disabled={deleteModal.confirming}
                                className="text-slate-400 hover:text-white disabled:opacity-40"
                            >
                                <X size={16} />
                            </button>
                        </div>

                        <p className="text-sm text-slate-300 mb-1">
                            Are you sure you want to delete <span className="text-white font-medium">"{deleteModal.goalName}"</span>?
                        </p>
                        <p className="text-xs text-slate-500 mb-4">
                            All linked Capsules, Capsule Rules, Allocations, and Milestones will also be permanently deleted.
                        </p>

                        {deleteModal.capsules.length > 0 && (
                            <div className="mb-4 space-y-2">
                                <p className="text-[10px] text-slate-500 uppercase tracking-wider">Linked Capsules</p>
                                {deleteModal.capsules.map((cap) => (
                                    <div
                                        key={cap.id}
                                        className="flex justify-between items-center bg-slate-800/50 border border-slate-700 px-3 py-2 text-xs"
                                    >
                                        <span className="text-slate-300">{cap.name}</span>
                                        <span className={`font-mono-nums ${cap.current_balance > 0 ? 'text-amber-400' : 'text-slate-500'}`}>
                                            {formatCurrency(cap.current_balance)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {deleteModal.capsules.some((c) => c.current_balance > 0) && (
                            <div className="mb-5">
                                <p className="text-[10px] text-amber-400 uppercase tracking-wider mb-2">
                                    ⚠ Capsule balance detected — select transfer destination
                                </p>
                                <p className="text-[10px] text-slate-500 mb-2">
                                    The accumulated balance will be transferred to the selected account before deletion.
                                </p>
                                <select
                                    value={deleteModal.transferAccountId}
                                    onChange={(e) =>
                                        setDeleteModal({ ...deleteModal, transferAccountId: e.target.value })
                                    }
                                    className="w-full bg-slate-800 border border-slate-600 px-3 py-2 text-xs text-slate-200"
                                    disabled={deleteModal.confirming}
                                >
                                    <option value="">Select account...</option>
                                    {deleteModal.assetAccounts.map((acc) => (
                                        <option key={acc.id} value={acc.id}>
                                            {acc.name} ({formatCompact(acc.balance)})
                                        </option>
                                    ))}
                                </select>
                            </div>
                        )}

                        <div className="flex gap-2 justify-end">
                            <button
                                onClick={() => setDeleteModal(null)}
                                disabled={deleteModal.confirming}
                                className="px-4 py-2 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={confirmDelete}
                                disabled={
                                    deleteModal.confirming ||
                                    (deleteModal.capsules.some((c) => c.current_balance > 0) &&
                                        !deleteModal.transferAccountId)
                                }
                                className="px-4 py-2 text-xs bg-rose-800 hover:bg-rose-700 text-rose-100 disabled:opacity-40 flex items-center gap-2"
                            >
                                <Trash2 size={12} />
                                {deleteModal.confirming ? 'Deleting...' : 'Delete Goal'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {showEventModal && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
                    <div className="bg-slate-900 border border-slate-700 p-6 w-full max-w-md">
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-sm font-medium">{editingEvent ? 'Edit Goal' : 'New Goal'}</h2>
                            <button onClick={() => setShowEventModal(false)} className="text-slate-400 hover:text-white"><X size={16} /></button>
                        </div>
                        <div className="space-y-3">
                            <input value={eventForm.name} onChange={(event) => setEventForm({ ...eventForm, name: event.target.value })} placeholder="Goal name" className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm" />
                            <div className="grid grid-cols-2 gap-3">
                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">
                                    Start Date
                                    <input type="date" title="Start date" value={eventForm.start_date} onChange={(event) => setEventForm({ ...eventForm, start_date: event.target.value })} className="mt-1 w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm" />
                                </label>
                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">
                                    Target Date
                                    <input type="date" title="Target date" value={eventForm.target_date} onChange={(event) => setEventForm({ ...eventForm, target_date: event.target.value })} className="mt-1 w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm" />
                                </label>
                            </div>
                            <input type="number" value={eventForm.target_amount} onChange={(event) => setEventForm({ ...eventForm, target_amount: event.target.value })} placeholder="Target amount" className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-mono-nums" />
                            <select value={eventForm.priority} onChange={(event) => setEventForm({ ...eventForm, priority: Number(event.target.value) as 1 | 2 | 3 })} className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm">
                                <option value={1}>High priority</option>
                                <option value={2}>Medium priority</option>
                                <option value={3}>Low priority</option>
                            </select>
                            <textarea value={eventForm.note} onChange={(event) => setEventForm({ ...eventForm, note: event.target.value })} placeholder="Why this matters" className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm min-h-24" />
                            <button onClick={saveEvent} className="w-full bg-cyan-600 hover:bg-cyan-500 text-white py-2 text-xs font-medium flex items-center justify-center gap-2">
                                <Save size={14} /> Save Goal
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
