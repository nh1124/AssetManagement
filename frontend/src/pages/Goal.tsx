import { useEffect, useMemo, useState } from 'react';
import { Calendar, Check, Edit2, Flag, Link, Plus, RefreshCw, Save, Sparkles, Trash2, TrendingUp, X } from 'lucide-react';
import { Area, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
    addAllocation,
    applyMilestonesFromSimulation,
    createGoal,
    createGoalCapsule,
    createMilestone,
    deleteAllocation,
    deleteGoal,
    deleteMilestone,
    getAccounts,
    getMilestones,
    getGoalDashboard,
    getGoalCapsules,
    getCapsules,
    getRoadmapProjection,
    optimizeAllocations,
    previewMilestonesFromSimulation,
    runMonteCarloSimulation,
    updateAllocation,
    updateGoal,
} from '../api';
import { useToast } from '../components/Toast';
import { useClient } from '../context/ClientContext';
import { formatCompactCurrency, formatCurrency as formatCurrencyWithSetting } from '../utils/currency';
import { PRIORITY_COLORS, priorityLabel } from '../utils/priority';
import type {
    Account,
    ContributionScheduleItem,
    ContributionScheduleKind,
    GoalAllocation,
    Capsule,
    LifeEvent,
    Milestone,
    MilestoneSimulationBasis,
    MilestoneSimulationInterval,
    MilestoneSimulationMode,
    MilestoneSimulationPreview,
    MonteCarloResult,
    RoadmapProjection,
} from '../types';

interface DashboardData {
    events: LifeEvent[];
    unallocated_assets: Array<{ id: number; name: string; balance: number; remaining_percentage?: number; available_balance?: number }>;
    total_allocated: number;
    total_unallocated: number;
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
    const [allocationForm, setAllocationForm] = useState({ account_id: '', allocation_percentage: '100' });
    const [allocationEdits, setAllocationEdits] = useState<Record<number, string>>({});
    const [milestoneForm, setMilestoneForm] = useState({ date: '', target_amount: '', note: '' });
    const [simParams, setSimParams] = useState({ annual_return: 5, inflation: 2, monthly_savings: 50000 });
    const [extraContributions, setExtraContributions] = useState<ContributionDraft[]>([]);
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
    const [loading, setLoading] = useState(false);
    const [simLoading, setSimLoading] = useState(false);
    const [roadmapLoading, setRoadmapLoading] = useState(false);
    const [optimizing, setOptimizing] = useState(false);
    const [deleteModal, setDeleteModal] = useState<{
        goalId: number;
        goalName: string;
        capsules: Array<{ id: number; name: string; current_balance: number; account_id: number | null }>;
        transferAccountId: string;
        confirming: boolean;
        assetAccounts: Account[];
    } | null>(null);

    const selectedGoalId = selectedGoal?.id;
    const simulationContributionSchedule = useMemo<ContributionScheduleItem[]>(() => {
        const schedule: ContributionScheduleItem[] = [
            { kind: 'monthly', amount: Math.max(0, Number(simParams.monthly_savings) || 0), note: 'base monthly savings' },
        ];
        extraContributions.forEach((item) => {
            const amount = Math.max(0, Number(item.amount) || 0);
            if (amount <= 0) return;
            schedule.push({
                kind: item.kind,
                amount,
                month: item.kind === 'yearly' ? item.month ?? 6 : null,
                date: item.kind === 'one_time' ? item.date || null : null,
                note: item.note || null,
            });
        });
        return schedule;
    }, [extraContributions, simParams.monthly_savings]);

    const simulationContextParams = useMemo(() => ({
        annual_return: simParams.annual_return,
        inflation: simParams.inflation,
        monthly_savings: simParams.monthly_savings,
        contribution_schedule: simulationContributionSchedule,
        allocation_mode: 'direct' as const,
    }), [simParams.annual_return, simParams.inflation, simParams.monthly_savings, simulationContributionSchedule]);

    const fetchGoalMilestones = async (goalId: number) => {
        setMilestones(await getMilestones(goalId));
    };

    const fetchAllMilestones = async () => {
        setMilestones(await getMilestones());
    };

    const fetchGoalWorkspace = async (preferredGoalId = selectedGoalId, scope: GoalScope = selectedScope) => {
        setLoading(true);
        try {
            const baseDashboardData = await getGoalDashboard(
                simParams.annual_return,
                simParams.inflation,
                simParams.monthly_savings,
                simulationContributionSchedule,
                'weighted',
            );
            const preferredId = preferredGoalId ?? baseDashboardData.events[0]?.id;
            const directDashboardData = scope === 'goal' && preferredId
                ? await getGoalDashboard(
                    simParams.annual_return,
                    simParams.inflation,
                    simParams.monthly_savings,
                    simulationContributionSchedule,
                    'direct',
                )
                : null;
            const capsuleData = await getCapsules();
            setDashboard(baseDashboardData);
            setCapsules(capsuleData);

            const selectedEvents = directDashboardData?.events ?? baseDashboardData.events;
            const nextSelected = preferredId
                ? selectedEvents.find((goal: LifeEvent) => goal.id === preferredId)
                : selectedEvents[0];
            setSelectedGoal(nextSelected ?? null);
            setAllocationEdits({});
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
                monthly_savings: simParams.monthly_savings,
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
    }, [activeGoalTab, selectedScope, simParams.annual_return, simParams.inflation, simParams.monthly_savings, simulationContributionSchedule]);

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
        simParams.monthly_savings,
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

    const goalProjectionChartData = useMemo(() => {
        const mcByYear = new Map(monteCarloChartData.map((row) => [row.year, row]));
        return (selectedGoal?.roadmap ?? []).map((row) => {
            const mc = mcByYear.get(row.year);
            return {
                ...row,
                target: selectedGoal?.target_amount ?? 0,
                p10: mc?.p10,
                p50: mc?.p50,
                p90: mc?.p90,
                band: mc ? Math.max(0, mc.p90 - mc.p10) : undefined,
            };
        });
    }, [monteCarloChartData, selectedGoal]);

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

    const availableAssets = useMemo(() => {
        const allocatedAccountIds = new Set((selectedGoal?.allocations ?? []).map((allocation) => allocation.account_id));
        return (dashboard?.unallocated_assets ?? []).filter((asset) => !allocatedAccountIds.has(asset.id));
    }, [dashboard, selectedGoal]);

    const selectedAvailableAsset = useMemo(() => {
        const accountId = Number(allocationForm.account_id);
        return availableAssets.find((asset) => asset.id === accountId);
    }, [availableAssets, allocationForm.account_id]);

    const getUsedAllocation = (accountId: number, excludeAllocationId?: number) => {
        return (dashboard?.events ?? []).reduce((total, goal) => {
            return total + (goal.allocations ?? []).reduce((sum, allocation) => {
                if (allocation.account_id !== accountId || allocation.id === excludeAllocationId) return sum;
                return sum + allocation.allocation_percentage;
            }, 0);
        }, 0);
    };

    const validateAllocationPct = (value: number, maxPct: number) => {
        if (!Number.isFinite(value) || value <= 0) return 'Allocation must be greater than 0%.';
        if (value > 100) return 'Allocation cannot exceed 100%.';
        if (value > maxPct + 0.0001) return `Only ${Math.max(0, maxPct).toFixed(1)}% is available for this asset.`;
        return null;
    };

    const openCreateModal = () => {
        setEditingEvent(null);
        setEventForm(emptyEventForm);
        setShowEventModal(true);
    };

    const openEditModal = (event: LifeEvent) => {
        setEditingEvent(event);
        setEventForm({
            name: event.name,
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

    const saveAllocation = async () => {
        if (!selectedGoal || !allocationForm.account_id) return;
        const requestedPct = Number(allocationForm.allocation_percentage);
        const maxPct = selectedAvailableAsset?.remaining_percentage ?? 0;
        const validationError = validateAllocationPct(requestedPct, maxPct);
        if (validationError) {
            showToast(validationError, 'error');
            return;
        }

        try {
            await addAllocation(selectedGoal.id, {
                account_id: Number(allocationForm.account_id),
                allocation_percentage: requestedPct,
            });
            setAllocationForm({ account_id: '', allocation_percentage: '100' });
            showToast('Allocation added', 'success');
            await fetchGoalWorkspace(selectedGoal.id);
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to add allocation'), 'error');
        }
    };

    const saveAllocationUpdate = async (allocation: GoalAllocation) => {
        const nextPct = Number(allocationEdits[allocation.id] ?? allocation.allocation_percentage);
        const maxPct = 100 - getUsedAllocation(allocation.account_id, allocation.id);
        const validationError = validateAllocationPct(nextPct, maxPct);
        if (validationError) {
            showToast(validationError, 'error');
            return;
        }

        try {
            await updateAllocation(allocation.id, {
                account_id: allocation.account_id,
                allocation_percentage: nextPct,
            });
            showToast('Allocation updated', 'success');
            await fetchGoalWorkspace(selectedGoal?.id);
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to update allocation'), 'error');
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

    const removeAllocation = async (allocationId: number) => {
        try {
            await deleteAllocation(allocationId);
            showToast('Allocation removed', 'info');
            await fetchGoalWorkspace(selectedGoal?.id);
        } catch (error) {
            showToast('Failed to remove allocation', 'error');
        }
    };

    const runAllocationOptimization = async () => {
        setOptimizing(true);
        try {
            const suggestions = await optimizeAllocations();
            if (!suggestions || suggestions.length === 0) {
                showToast('No allocation suggestions found', 'info');
                return;
            }
            if (!confirm(`Apply ${suggestions.length} suggested allocations?`)) return;

            let applied = 0;
            for (const suggestion of suggestions) {
                const targetGoal = dashboard?.events.find((goal) => goal.id === suggestion.life_event_id);
                const alreadyAllocated = targetGoal?.allocations?.some((allocation) => allocation.account_id === suggestion.account_id);
                if (alreadyAllocated) continue;
                await addAllocation(suggestion.life_event_id, {
                    account_id: suggestion.account_id,
                    allocation_percentage: suggestion.percentage,
                });
                applied += 1;
            }
            showToast(applied > 0 ? `Applied ${applied} suggested allocations` : 'No new allocation suggestions to apply', applied > 0 ? 'success' : 'info');
            await fetchGoalWorkspace(selectedGoal?.id);
        } catch (error) {
            showToast(getErrorDetail(error, 'Failed to optimize allocations'), 'error');
        } finally {
            setOptimizing(false);
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

    const milestonePlanPayload = () => ({
        ...milestonePlan,
        annual_return: simParams.annual_return,
        inflation: simParams.inflation,
        monthly_savings: simParams.monthly_savings,
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
        setExtraContributions((items) => [
            ...items,
            {
                id: `${kind}-${Date.now()}`,
                kind,
                amount: 0,
                month: kind === 'yearly' ? 6 : null,
                date: kind === 'one_time' ? new Date().toISOString().slice(0, 10) : null,
                note: kind === 'yearly' ? 'bonus' : 'one-time',
            },
        ]);
    };

    const updateContribution = (id: string, patch: Partial<ContributionDraft>) => {
        setExtraContributions((items) => items.map((item) => item.id === id ? { ...item, ...patch } : item));
    };

    const removeContribution = (id: string) => {
        setExtraContributions((items) => items.filter((item) => item.id !== id));
    };

    const monthlyEquivalentForSelectedGoal = useMemo(() => {
        if (!selectedGoal) return simParams.monthly_savings;
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
    }, [selectedGoal, simParams.monthly_savings, simulationContributionSchedule]);

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
                    Using current simulation: Return {simParams.annual_return}%, Inflation {simParams.inflation}%, Contribution Plan {formatCurrency(monthlyEquivalentForSelectedGoal)} / mo equivalent
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
                            <label className="block text-xs text-slate-500">
                                Monthly Savings
                                <input type="number" step="10000" value={simParams.monthly_savings} onChange={(event) => setSimParams({ ...simParams, monthly_savings: Number(event.target.value) })} className="mt-1 w-full bg-slate-900 border border-slate-700 px-2 py-2 text-xs font-mono-nums" />
                            </label>
                            <div className="border-t border-slate-800 pt-3 space-y-2">
                                <div className="flex items-center justify-between gap-2">
                                    <div>
                                        <p className="text-[10px] uppercase tracking-wider text-slate-500">Contribution Plan</p>
                                        <p className="text-[10px] text-slate-600">Equivalent: {formatCurrency(monthlyEquivalentForSelectedGoal)} / mo</p>
                                    </div>
                                    <div className="flex border border-slate-700">
                                        <button onClick={() => addContribution('yearly')} className="px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800" title="Add yearly bonus contribution"><Plus size={11} /></button>
                                        <button onClick={() => addContribution('one_time')} className="px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800 border-l border-slate-700" title="Add one-time contribution"><Calendar size={11} /></button>
                                    </div>
                                </div>
                                {extraContributions.map((item) => (
                                    <div key={item.id} className="grid grid-cols-[82px_1fr_32px] gap-2 items-center">
                                        <select
                                            value={item.kind}
                                            onChange={(event) => updateContribution(item.id, {
                                                kind: event.target.value as ContributionScheduleKind,
                                                month: event.target.value === 'yearly' ? item.month ?? 6 : null,
                                                date: event.target.value === 'one_time' ? item.date || new Date().toISOString().slice(0, 10) : null,
                                            })}
                                            className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-[10px]"
                                        >
                                            <option value="yearly">Bonus</option>
                                            <option value="one_time">One-time</option>
                                        </select>
                                        <div className="grid grid-cols-2 gap-2">
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
                                                    onChange={(event) => updateContribution(item.id, { month: Number(event.target.value) })}
                                                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-[10px]"
                                                >
                                                    {Array.from({ length: 12 }, (_, index) => index + 1).map((month) => (
                                                        <option key={month} value={month}>{month}月</option>
                                                    ))}
                                                </select>
                                            ) : (
                                                <input
                                                    type="date"
                                                    value={item.date || ''}
                                                    onChange={(event) => updateContribution(item.id, { date: event.target.value })}
                                                    className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-[10px]"
                                                />
                                            )}
                                        </div>
                                        <button onClick={() => removeContribution(item.id)} className="h-full border border-slate-700 text-slate-500 hover:text-rose-300 hover:border-rose-800" title="Remove contribution">
                                            <Trash2 size={12} className="mx-auto" />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

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
                                    <ResponsiveContainer width="100%" height="100%">
                                        <ComposedChart data={goalProjectionChartData} margin={{ top: 8, right: 16, bottom: 34, left: 8 }}>
                                            <XAxis dataKey="year" tick={{ fontSize: 10 }} stroke="#64748b" label={{ value: 'Years', position: 'insideBottom', offset: -8, fontSize: 10 }} />
                                            <YAxis tick={{ fontSize: 10 }} stroke="#64748b" tickFormatter={formatCompact} />
                                            <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 11 }} formatter={(value) => [formatCurrency(value as number), '']} />
                                            <Legend verticalAlign="bottom" align="center" wrapperStyle={{ fontSize: 10, paddingTop: 14 }} />
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Area dataKey="p10" stackId="goal-band" stroke="none" fill="transparent" name="P10" />}
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Area dataKey="band" stackId="goal-band" stroke="none" fill="#22c55e" fillOpacity={0.12} name="P10-P90" />}
                                            {(projectionView === 'projection' || projectionView === 'combined') && <Line type="monotone" dataKey="end_balance" stroke="#10b981" name="Projection" strokeWidth={2} dot={false} />}
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Line type="monotone" dataKey="p10" stroke="#f59e0b" name="P10" dot={false} connectNulls={false} />}
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Line type="monotone" dataKey="p50" stroke="#22d3ee" name="P50" dot={false} connectNulls={false} />}
                                            {(projectionView === 'monteCarlo' || projectionView === 'combined') && <Line type="monotone" dataKey="p90" stroke="#10b981" name="P90" dot={false} connectNulls={false} />}
                                            <Line type="monotone" dataKey="target" stroke="#f97316" strokeDasharray="5 5" name="Target" dot={false} />
                                        </ComposedChart>
                                    </ResponsiveContainer>
                                </div>
                            </>
                        )}
                    </div>

                    <div className="bg-slate-800/30 border border-slate-700 overflow-hidden">
                        <h3 className="text-[10px] text-slate-500 uppercase tracking-wider p-3 bg-slate-800/50 border-b border-slate-700">Annual Roadmap</h3>
                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-[10px]">
                                <thead className="bg-slate-800 text-slate-500 uppercase">
                                    <tr>
                                        <th className="px-3 py-2 font-normal">Year</th>
                                        <th className="px-3 py-2 font-normal">Start</th>
                                        <th className="px-3 py-2 font-normal">Contribution</th>
                                        <th className="px-3 py-2 font-normal">Gain</th>
                                        <th className="px-3 py-2 font-normal">End</th>
                                        <th className="px-3 py-2 font-normal text-right">Coverage</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-800">
                                    {(selectedGoal.roadmap ?? []).map((row) => (
                                        <tr key={row.year} className="hover:bg-slate-800/40">
                                            <td className="px-3 py-2 text-slate-400">{row.year === 0 ? 'Current' : `Year ${row.year}`}</td>
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
            <div className="space-y-2 max-h-[520px] overflow-auto">
                {displayedMilestones.length === 0 ? (
                    <p className="text-xs text-slate-600">{showingPlan ? 'No candidate milestones for this plan.' : 'No milestones yet. Add one manually or adopt a simulation plan.'}</p>
                ) : displayedMilestones.map((milestone) => (
                    <div key={`${milestone.date}-${milestone.target_amount}-${milestone.note ?? ''}`} className="grid grid-cols-1 md:grid-cols-[140px_1fr_auto] items-center gap-3 bg-slate-900/60 border border-slate-700 p-2 text-xs">
                        <div className="flex items-center gap-2">
                            <Calendar size={12} className="text-slate-500" />
                            <span className="font-mono-nums text-slate-300">{milestone.date}</span>
                        </div>
                        <div className="min-w-0">
                            <span className="font-mono-nums text-emerald-400">{formatCurrency(milestone.target_amount)}</span>
                            {milestone.note && <span className="ml-3 text-slate-500">{milestone.note}</span>}
                            {milestone.source && milestone.source !== 'manual' && <span className="ml-3 text-[10px] text-cyan-500">{milestone.source}</span>}
                        </div>
                        {!showingPlan && typeof (milestone as Milestone).id === 'number' && <button onClick={() => removeRoadmapMilestone((milestone as Milestone).id)} className="text-slate-600 hover:text-rose-400 justify-self-end"><Trash2 size={12} /></button>}
                    </div>
                ))}
            </div>
        </div>
        );
    };

    const renderAssetAllocation = () => {
        const allocations = selectedGoal?.allocations ?? [];
        const linkedCapsule = selectedGoal ? capsules.find((capsule) => capsule.life_event_id === selectedGoal.id) : undefined;
        const allocationTotal = allocations.reduce((sum, allocation) => sum + (allocation.account_balance || 0) * allocation.allocation_percentage / 100, 0);

        return (
            <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="bg-slate-800/40 border border-slate-700 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">Allocated Here</p>
                        <p className="font-mono-nums text-emerald-400">{formatCurrency(allocationTotal)}</p>
                    </div>
                    <div className="bg-slate-800/40 border border-slate-700 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">Unallocated</p>
                        <p className="font-mono-nums text-cyan-400">{formatCurrency(dashboard?.total_unallocated)}</p>
                    </div>
                    <div className="bg-slate-800/40 border border-slate-700 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">Assets</p>
                        <p className="font-mono-nums text-slate-200">{allocations.length}</p>
                    </div>
                </div>

                <div className="bg-slate-800/30 border border-slate-700 p-4">
                    <div className="flex items-center justify-between mb-3">
                        <h3 className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1"><Link size={12} /> Allocated Assets</h3>
                        <button
                            onClick={runAllocationOptimization}
                            disabled={optimizing}
                            className="text-[10px] text-purple-400 hover:text-purple-300 flex items-center gap-1 disabled:opacity-50"
                        >
                            <Sparkles size={12} /> {optimizing ? 'Optimizing...' : 'AI Optimize'}
                        </button>
                    </div>

                    <div className="space-y-2 mb-4">
                        {!linkedCapsule && (
                            <div className="bg-cyan-950/20 border border-cyan-800/50 p-3 flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs">
                                <div>
                                    <p className="text-cyan-200">No linked capsule for this goal.</p>
                                    <p className="text-[10px] text-slate-500 mt-1">Create a dedicated sinking fund and use its account as this goal's allocation source.</p>
                                </div>
                                <button onClick={ensureSelectedGoalCapsule} className="px-3 py-1.5 bg-cyan-700 hover:bg-cyan-600 text-white text-[10px]">
                                    Create Capsule
                                </button>
                            </div>
                        )}
                        {allocations.length === 0 ? (
                            <p className="text-xs text-slate-600">No assets allocated yet.</p>
                        ) : (
                            allocations.map((allocation) => {
                                const editValue = allocationEdits[allocation.id] ?? String(allocation.allocation_percentage);
                                const allocatedAmount = (allocation.account_balance || 0) * Number(editValue || allocation.allocation_percentage) / 100;

                                return (
                                    <div key={allocation.id} className="grid grid-cols-1 min-[760px]:grid-cols-[1fr_170px_84px] items-center gap-3 bg-slate-900/60 border border-slate-700 p-2 text-xs">
                                        <div className="min-w-0">
                                            <p className="text-slate-200 truncate">{allocation.account_name}</p>
                                            <p className="text-[10px] text-slate-500">
                                                {formatCurrency(allocation.account_balance)} / {formatCurrency(allocatedAmount)}
                                            </p>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <input
                                                type="number"
                                                min="0.1"
                                                max={100 - getUsedAllocation(allocation.account_id, allocation.id)}
                                                step="0.1"
                                                value={editValue}
                                                onChange={(event) => setAllocationEdits({ ...allocationEdits, [allocation.id]: event.target.value })}
                                                className="w-full bg-slate-950 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                                            />
                                            <span className="text-slate-500">%</span>
                                        </div>
                                        <div className="flex justify-end gap-2">
                                            <button onClick={() => saveAllocationUpdate(allocation)} className="p-1.5 text-slate-500 hover:text-emerald-400" title="Save allocation"><Check size={13} /></button>
                                            <button onClick={() => removeAllocation(allocation.id)} className="p-1.5 text-slate-600 hover:text-rose-400" title="Remove allocation"><Trash2 size={13} /></button>
                                        </div>
                                    </div>
                                );
                            })
                        )}
                    </div>

                    <div className="grid grid-cols-12 gap-2 border-t border-slate-800 pt-3">
                        <select
                            value={allocationForm.account_id}
                            onChange={(event) => {
                                const accountId = Number(event.target.value);
                                const account = availableAssets.find((asset) => asset.id === accountId);
                                setAllocationForm({
                                    account_id: event.target.value,
                                    allocation_percentage: String(Math.round(account?.remaining_percentage ?? 100)),
                                });
                            }}
                            className="col-span-12 md:col-span-7 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-300"
                        >
                            <option value="">Select asset...</option>
                            {availableAssets.map((asset) => (
                                <option key={asset.id} value={asset.id}>{asset.name} ({Math.round(asset.remaining_percentage ?? 0)}% left)</option>
                            ))}
                        </select>
                        <input
                            type="number"
                            min="0.1"
                            max={selectedAvailableAsset?.remaining_percentage ?? 100}
                            step="0.1"
                            value={allocationForm.allocation_percentage}
                            onChange={(event) => setAllocationForm({ ...allocationForm, allocation_percentage: event.target.value })}
                            className="col-span-8 md:col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                        />
                        <button onClick={saveAllocation} disabled={!allocationForm.account_id} className="col-span-4 md:col-span-2 bg-cyan-900/50 border border-cyan-800 text-cyan-300 hover:bg-cyan-900 disabled:opacity-40"><Plus size={14} className="mx-auto" /></button>
                    </div>
                </div>
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
                <div className="bg-slate-800/40 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Unallocated Assets</p>
                    <p className="text-lg text-emerald-400 font-mono-nums">{formatCurrency(dashboard?.total_unallocated)}</p>
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
                                <input type="date" value={eventForm.target_date} onChange={(event) => setEventForm({ ...eventForm, target_date: event.target.value })} className="bg-slate-800 border border-slate-700 px-3 py-2 text-sm" />
                                <input type="number" value={eventForm.target_amount} onChange={(event) => setEventForm({ ...eventForm, target_amount: event.target.value })} placeholder="Target amount" className="bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-mono-nums" />
                            </div>
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
