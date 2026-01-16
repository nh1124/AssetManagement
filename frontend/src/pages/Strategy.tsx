import { useState, useEffect } from 'react';
import { TrendingUp, Plus, Trash2, X, Link, Wallet, Edit2, Save, ChevronLeft, ChevronRight, Copy } from 'lucide-react';
import SplitView from '../components/SplitView';
import TabPanel from '../components/TabPanel';
import { useToast } from '../components/Toast';
import {
    getStrategyDashboard,
    createLifeEvent,
    updateLifeEvent,
    deleteLifeEvent,
    addAllocation,
    deleteAllocation,
    getAccounts,
    getBudgetSummary,
    saveMonthlyBudgets,
    suggestBudget,
    optimizeAllocations
} from '../api';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { Sparkles } from 'lucide-react';

interface RoadmapItem {
    year: number;
    start_balance: number;
    contribution: number;
    investment_gain: number;
    end_balance: number;
    goal_coverage: number;
}

interface LifeEvent {
    id: number;
    name: string;
    target_date: string;
    target_amount: number;
    priority: number;
    note: string | null;
    allocations: Allocation[];
    current_funded: number;
    projected_amount: number;
    gap: number;
    status: string;
    progress_percentage: number;
    years_remaining: number;
    weighted_return?: number;
    roadmap?: RoadmapItem[];
}

interface Allocation {
    id: number;
    life_event_id: number;
    account_id: number;
    allocation_percentage: number;
    account_name: string;
    account_balance: number;
    expected_return?: number;
}

interface DashboardData {
    events: LifeEvent[];
    unallocated_assets: Array<{ id: number; name: string; balance: number; remaining_percentage?: number }>;
    total_allocated: number;
    total_unallocated: number;
    simulation_params: {
        annual_return: number;
        inflation: number;
        monthly_savings: number;
    };
}

interface BudgetAccount {
    id: number;
    name: string;
    budget_limit: number;
    balance: number;
    is_custom: boolean;
}

interface BudgetSummary {
    period: string;
    required_monthly_savings: number;
    monthly_fixed_costs: number;
    monthly_income: number;
    total_variable_budget: number;
    remaining_balance: number;
    expense_accounts: BudgetAccount[];
    goals_count: number;
    total_goal_gap: number;
}

const TABS = [
    { id: 'simulation', label: 'Simulation' },
    { id: 'budgeting', label: 'Budgeting' },
];

export default function Strategy() {
    const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);
    const [selectedEvent, setSelectedEvent] = useState<LifeEvent | null>(null);
    const [showEventModal, setShowEventModal] = useState(false);
    const [editingEvent, setEditingEvent] = useState<LifeEvent | null>(null);
    const [activeTab, setActiveTab] = useState('simulation');
    const [budgetSummary, setBudgetSummary] = useState<BudgetSummary | null>(null);
    const [budgetEdits, setBudgetEdits] = useState<Record<number, number>>({});
    const [currentPeriod, setCurrentPeriod] = useState<string>(new Date().toISOString().slice(0, 7)); // YYYY-MM
    const { showToast } = useToast();

    // Simulation parameters
    const [simParams, setSimParams] = useState({
        annual_return: 5.0,
        inflation: 2.0,
        monthly_savings: 50000
    });

    // Event form
    const [eventForm, setEventForm] = useState({
        name: '',
        target_date: '',
        target_amount: '',
        priority: 2,
        note: ''
    });

    // Allocation form
    const [allocationForm, setAllocationForm] = useState({
        account_id: '',
        allocation_percentage: '100'
    });
    const [analyzing, setAnalyzing] = useState(false);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData();
        }, 500); // Debounce API calls
        return () => clearTimeout(timer);
    }, [simParams.annual_return, simParams.inflation, simParams.monthly_savings]);

    useEffect(() => {
        if (activeTab === 'budgeting') {
            fetchBudgetSummary();
        }
    }, [activeTab, currentPeriod]);

    const handleAISuggestBudget = async () => {
        if (!budgetSummary) return;
        setAnalyzing(true);
        try {
            const suggestions = await suggestBudget();
            const newEdits = { ...budgetEdits };
            let appliedCount = 0;

            suggestions.forEach((s: any) => {
                const account = budgetSummary.expense_accounts.find(
                    a => a.name.toLowerCase().includes(s.category.toLowerCase()) ||
                        s.category.toLowerCase().includes(a.name.toLowerCase())
                );
                if (account) {
                    newEdits[account.id] = s.suggested_limit;
                    appliedCount++;
                }
            });

            setBudgetEdits(newEdits);
            if (appliedCount > 0) showToast(`Applied ${appliedCount} AI budget suggestions`, 'success');
            else showToast('No matching categories found for suggestions', 'info');

        } catch (e) {
            console.error(e);
            showToast('Failed to get AI suggestions', 'error');
        } finally {
            setAnalyzing(false);
        }
    };

    const handleAIOptimize = async () => {
        if (!dashboardData) return;
        setAnalyzing(true);
        try {
            const suggestions = await optimizeAllocations();
            if (!suggestions || suggestions.length === 0) {
                showToast('AI found no optimizations', 'info');
                return;
            }

            if (confirm(`AI found ${suggestions.length} optimal allocations. Apply them?`)) {
                for (const s of suggestions) {
                    try {
                        await addAllocation(s.life_event_id, {
                            account_id: s.account_id,
                            allocation_percentage: s.percentage
                        });
                    } catch (err) {
                        console.error('Failed to apply allocation', s, err);
                    }
                }
                fetchData();
                showToast('Optimized allocations applied', 'success');
            }
        } catch (e) {
            console.error(e);
            showToast('Failed to optimize allocations', 'error');
        } finally {
            setAnalyzing(false);
        }
    };

    const fetchData = async () => {
        try {
            const [dashboard] = await Promise.all([
                getStrategyDashboard(simParams.annual_return, simParams.inflation, simParams.monthly_savings),
                getAccounts()
            ]);
            setDashboardData(dashboard);
            if (dashboard.events.length > 0 && !selectedEvent) {
                setSelectedEvent(dashboard.events[0]);
            } else if (selectedEvent) {
                const updated = dashboard.events.find((e: LifeEvent) => e.id === selectedEvent.id);
                if (updated) setSelectedEvent(updated);
            }
        } catch (error) {
            console.error('Failed to fetch strategy data:', error);
            showToast('Failed to load strategy data', 'error');
        }
    };



    const fetchBudgetSummary = async () => {
        try {
            const summary = await getBudgetSummary(currentPeriod);
            setBudgetSummary(summary);
            // Initialize edits with values from response
            const edits: Record<number, number> = {};
            summary.expense_accounts.forEach((acc: BudgetAccount) => {
                edits[acc.id] = acc.budget_limit;
            });
            setBudgetEdits(edits);
        } catch (error) {
            console.error('Failed to fetch budget summary:', error);
        }
    };

    const handleOpenEditModal = (event: LifeEvent) => {
        setEditingEvent(event);
        setEventForm({
            name: event.name,
            target_date: event.target_date,
            target_amount: String(event.target_amount),
            priority: event.priority,
            note: event.note || ''
        });
        setShowEventModal(true);
    };

    const handleOpenCreateModal = () => {
        setEditingEvent(null);
        setEventForm({ name: '', target_date: '', target_amount: '', priority: 2, note: '' });
        setShowEventModal(true);
    };

    const handleSaveEvent = async () => {
        if (!eventForm.name || !eventForm.target_date || !eventForm.target_amount) return;
        try {
            const payload = {
                name: eventForm.name,
                target_date: eventForm.target_date,
                target_amount: parseFloat(eventForm.target_amount),
                priority: eventForm.priority,
                note: eventForm.note || null
            };
            if (editingEvent) {
                await updateLifeEvent(editingEvent.id, payload);
                showToast('Life event updated', 'success');
            } else {
                await createLifeEvent(payload);
                showToast('Life event created', 'success');
            }
            setShowEventModal(false);
            fetchData();
        } catch (error) {
            showToast('Failed to save event', 'error');
        }
    };

    const handleDeleteEvent = async (id: number) => {
        if (!confirm('Delete this life event?')) return;
        try {
            await deleteLifeEvent(id);
            showToast('Life event deleted', 'info');
            if (selectedEvent?.id === id) setSelectedEvent(null);
            fetchData();
        } catch (error) {
            showToast('Failed to delete event', 'error');
        }
    };

    const handleAddAllocation = async () => {
        if (!selectedEvent || !allocationForm.account_id) return;
        try {
            await addAllocation(selectedEvent.id, {
                account_id: parseInt(allocationForm.account_id),
                allocation_percentage: parseFloat(allocationForm.allocation_percentage)
            });
            showToast('Allocation added', 'success');
            setAllocationForm({ account_id: '', allocation_percentage: '100' });
            fetchData();
        } catch (error) {
            showToast('Failed to add allocation', 'error');
        }
    };

    const handleDeleteAllocation = async (allocId: number) => {
        try {
            await deleteAllocation(allocId);
            showToast('Allocation removed', 'info');
            fetchData();
        } catch (error) {
            showToast('Failed to remove allocation', 'error');
        }
    };


    const handleSaveBudget = async () => {
        try {
            const budgets = Object.entries(budgetEdits).map(([id, limit]) => ({
                account_id: parseInt(id),
                target_period: currentPeriod,
                amount: limit
            }));
            await saveMonthlyBudgets(budgets);
            showToast('Monthly budget saved', 'success');
            fetchBudgetSummary();
        } catch (error) {
            showToast('Failed to save budget', 'error');
        }
    };

    const changePeriod = (delta: number) => {
        const [year, month] = currentPeriod.split('-').map(Number);
        const date = new Date(year, month - 1 + delta, 1);
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        setCurrentPeriod(`${y}-${m}`);
    };

    const handleCopyPrevious = async () => {
        const [year, month] = currentPeriod.split('-').map(Number);
        const prevDate = new Date(year, month - 2, 1);
        const y = prevDate.getFullYear();
        const m = String(prevDate.getMonth() + 1).padStart(2, '0');
        const prevPeriod = `${y}-${m}`;

        try {
            const prevSummary = await getBudgetSummary(prevPeriod);
            const edits: Record<number, number> = {};
            prevSummary.expense_accounts.forEach((acc: BudgetAccount) => {
                edits[acc.id] = acc.budget_limit;
            });
            setBudgetEdits(edits);
            showToast(`Copied from ${prevPeriod}`, 'info');
        } catch (error) {
            showToast('Failed to fetch previous budget', 'error');
        }
    };

    const formatCurrency = (val: number) => `¥${Math.round(val).toLocaleString()}`;



    // Left Pane: Event Manager
    const leftPane = (
        <div className="space-y-4 h-full flex flex-col">
            <div className="grid grid-cols-2 gap-2">
                <div className="bg-emerald-900/20 border border-emerald-800/50 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Allocated</p>
                    <p className="text-lg font-mono-nums text-emerald-400">{formatCurrency(dashboardData?.total_allocated || 0)}</p>
                </div>
                <div className="bg-slate-800/50 border border-slate-700 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Unallocated</p>
                    <p className="text-lg font-mono-nums text-slate-300">{formatCurrency(dashboardData?.total_unallocated || 0)}</p>
                </div>
            </div>

            <div className="flex-1 overflow-auto space-y-2">
                {dashboardData?.events.length === 0 ? (
                    <div className="text-center py-8 text-slate-600 text-xs">No life events. Add your first goal!</div>
                ) : (
                    dashboardData?.events.map((event) => (
                        <div
                            key={event.id}
                            onClick={() => setSelectedEvent(event)}
                            className={`
                                group px-3 py-2 cursor-pointer border-b border-white/5 transition-colors
                                ${selectedEvent?.id === event.id
                                    ? 'bg-white/10'
                                    : 'hover:bg-white/5'
                                }
                            `}
                        >
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2 min-w-0">
                                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${event.status === 'On Track' ? 'bg-emerald-500' :
                                        event.status === 'At Risk' ? 'bg-amber-500' : 'bg-rose-500'
                                        }`} />
                                    <span className="text-xs text-slate-200 truncate">{event.name}</span>
                                </div>

                                <span className="text-[10px] text-slate-500 font-mono-nums flex-shrink-0">
                                    {event.target_date.substring(0, 4)}
                                </span>
                            </div>

                            <div className="mt-1 flex items-center justify-between gap-4">
                                <div className="flex-1 h-0.5 bg-slate-700/50 rounded-full overflow-hidden">
                                    <div
                                        className={`h-full ${event.status === 'On Track' ? 'bg-emerald-500/70' :
                                            event.status === 'At Risk' ? 'bg-amber-500/70' : 'bg-rose-500/70'
                                            }`}
                                        style={{ width: `${Math.min(100, event.progress_percentage)}%` }}
                                    />
                                </div>
                                <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <Edit2 size={10} className="text-slate-400 hover:text-cyan-400" onClick={(e) => { e.stopPropagation(); handleOpenEditModal(event); }} />
                                    <Trash2 size={10} className="text-slate-500 hover:text-rose-400" onClick={(e) => { e.stopPropagation(); handleDeleteEvent(event.id); }} />
                                </div>
                            </div>
                        </div>
                    ))
                )}
            </div>

            <button
                onClick={handleOpenCreateModal}
                className="w-full border border-dashed border-slate-700 hover:border-cyan-600 p-3 text-xs text-slate-500 hover:text-cyan-400 flex items-center justify-center gap-1 transition-colors"
            >
                <Plus size={14} /> Add Life Event
            </button>
        </div>
    );

    const renderRightPane = () => {
        if (activeTab === 'budgeting') {
            return (
                <div className="space-y-4 h-full flex flex-col">
                    {/* Month Selector */}
                    <div className="flex items-center justify-between bg-slate-800/30 border border-slate-700 px-4 py-2">
                        <button onClick={() => changePeriod(-1)} className="p-1 hover:bg-slate-700 text-slate-400"><ChevronLeft size={16} /></button>
                        <span className="text-sm font-medium font-mono-nums">{currentPeriod}</span>
                        <button onClick={() => changePeriod(1)} className="p-1 hover:bg-slate-700 text-slate-400"><ChevronRight size={16} /></button>
                        <button
                            onClick={handleCopyPrevious}
                            className="ml-4 flex items-center gap-1 text-[10px] text-cyan-400 hover:text-cyan-300"
                            title="Copy from previous month"
                        >
                            <Copy size={12} /> Copy Prev
                        </button>
                    </div>

                    <div className="bg-gradient-to-r from-cyan-900/20 to-emerald-900/20 border border-cyan-800/50 p-4">
                        <h3 className="text-[10px] text-slate-400 uppercase tracking-wider mb-3">THE TARGET</h3>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <p className="text-[10px] text-slate-500">Required Monthly Savings</p>
                                <p className="text-xl font-mono-nums text-cyan-400">
                                    {formatCurrency(budgetSummary?.required_monthly_savings || 0)}
                                </p>
                            </div>
                            <div>
                                <p className="text-[10px] text-slate-500">Fixed Costs (Recurring)</p>
                                <p className="text-xl font-mono-nums text-amber-400">
                                    {formatCurrency(budgetSummary?.monthly_fixed_costs || 0)}
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="flex-1 bg-slate-800/30 border border-slate-700 p-4 overflow-auto">
                        <h3 className="text-[10px] text-slate-400 uppercase tracking-wider mb-3 flex items-center justify-between">
                            <span className="flex items-center gap-1"><Wallet size={10} /> Variable Budget</span>
                            <button
                                onClick={handleAISuggestBudget}
                                disabled={analyzing}
                                className="flex items-center gap-1 text-[9px] text-cyan-400 hover:text-cyan-300 disabled:opacity-50"
                            >
                                <Sparkles size={10} /> {analyzing ? 'Thinking...' : 'AI Suggest'}
                            </button>
                        </h3>
                        <div className="overflow-x-auto">
                            <table className="w-full text-[10px]">
                                <thead className="text-slate-500 uppercase border-b border-slate-700 bg-slate-800/50">
                                    <tr>
                                        <th className="px-2 py-1.5 text-left font-normal w-1/3">Category</th>
                                        <th className="px-2 py-1.5 text-right font-normal text-slate-600">Actual</th>
                                        <th className="px-2 py-1.5 text-right font-normal">Limit</th>
                                        <th className="px-2 py-1.5 text-right font-normal">Var</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-800/50">
                                    {budgetSummary?.expense_accounts.map(acc => {
                                        const limit = budgetEdits[acc.id] ?? 0;
                                        const actual = acc.balance || 0;
                                        const variance = limit - actual;

                                        return (
                                            <tr key={acc.id} className="hover:bg-slate-800/30 transition-colors group">
                                                <td className="px-2 py-1.5 text-slate-300 truncate max-w-[120px]" title={acc.name}>
                                                    {acc.name}
                                                    {acc.is_custom && <span className="ml-1 text-[8px] text-cyan-500 bg-cyan-900/30 px-1 rounded">Cust</span>}
                                                </td>
                                                <td className="px-2 py-1.5 text-right font-mono-nums text-slate-500">
                                                    {formatCurrency(actual)}
                                                </td>
                                                <td className="px-2 py-1.5 text-right">
                                                    <input
                                                        type="number"
                                                        step="1000"
                                                        value={limit}
                                                        onChange={(e) => setBudgetEdits({ ...budgetEdits, [acc.id]: parseFloat(e.target.value) || 0 })}
                                                        className="w-20 bg-transparent border-b border-slate-700 focus:border-cyan-500 text-right font-mono-nums text-slate-200 focus:bg-slate-800/50 outline-none px-1 py-0.5"
                                                    />
                                                </td>
                                                <td className={`px-2 py-1.5 text-right font-mono-nums ${variance >= 0 ? 'text-emerald-500/70' : 'text-rose-500'}`}>
                                                    {formatCurrency(variance)}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="bg-slate-800/50 border border-slate-700 p-4">
                        <div className="grid grid-cols-2 gap-2 text-xs mb-3">
                            <div className="flex justify-between">
                                <span className="text-slate-500">Income</span>
                                <span className="font-mono-nums text-emerald-400">{formatCurrency(budgetSummary?.monthly_income || 0)}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-500">- Savings</span>
                                <span className="font-mono-nums text-cyan-400">{formatCurrency(budgetSummary?.required_monthly_savings || 0)}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-500">- Fixed</span>
                                <span className="font-mono-nums text-amber-400">{formatCurrency(budgetSummary?.monthly_fixed_costs || 0)}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-500">- Variable</span>
                                <span className="font-mono-nums">{formatCurrency(Object.values(budgetEdits).reduce((a, b) => a + b, 0))}</span>
                            </div>
                        </div>
                        <div className="border-t border-slate-700 pt-2 flex justify-between items-center">
                            <span className="text-sm font-medium">Remaining</span>
                            <span className={`text-lg font-mono-nums ${(budgetSummary?.monthly_income || 0) -
                                (budgetSummary?.required_monthly_savings || 0) -
                                (budgetSummary?.monthly_fixed_costs || 0) -
                                Object.values(budgetEdits).reduce((a, b) => a + b, 0) >= 0
                                ? 'text-emerald-400' : 'text-rose-400'
                                }`}>
                                {formatCurrency(
                                    (budgetSummary?.monthly_income || 0) -
                                    (budgetSummary?.required_monthly_savings || 0) -
                                    (budgetSummary?.monthly_fixed_costs || 0) -
                                    Object.values(budgetEdits).reduce((a, b) => a + b, 0)
                                )}
                            </span>
                        </div>
                    </div>

                    <button
                        onClick={handleSaveBudget}
                        className="w-full bg-cyan-600 hover:bg-cyan-500 text-white py-2.5 text-xs font-medium flex items-center justify-center gap-2"
                    >
                        <Save size={14} /> Save {currentPeriod} Budget
                    </button>
                </div>
            );
        }

        return (
            <div className="space-y-4 h-full flex flex-col overflow-auto">
                {/* Simulation Parameters */}
                <div className="bg-slate-800/30 border border-slate-700 p-3">
                    <h3 className="text-[10px] text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1">
                        <TrendingUp size={10} /> Default Simulation Settings
                    </h3>
                    <div className="grid grid-cols-3 gap-2">
                        <div>
                            <label className="block text-[9px] text-slate-600 mb-0.5">Return %</label>
                            <input
                                type="number"
                                step="0.5"
                                value={simParams.annual_return}
                                onChange={(e) => setSimParams({ ...simParams, annual_return: parseFloat(e.target.value) })}
                                className="w-full bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                            />
                        </div>
                        <div>
                            <label className="block text-[9px] text-slate-600 mb-0.5">Inflation %</label>
                            <input
                                type="number"
                                step="0.5"
                                value={simParams.inflation}
                                onChange={(e) => setSimParams({ ...simParams, inflation: parseFloat(e.target.value) })}
                                className="w-full bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                            />
                        </div>
                        <div>
                            <label className="block text-[9px] text-slate-600 mb-0.5">Monthly Save</label>
                            <input
                                type="number"
                                step="10000"
                                value={simParams.monthly_savings}
                                onChange={(e) => setSimParams({ ...simParams, monthly_savings: parseFloat(e.target.value) })}
                                className="w-full bg-slate-900 border border-slate-700 px-2 py-1 text-xs font-mono-nums"
                            />
                        </div>
                    </div>
                </div>

                {selectedEvent && (
                    <div className="grid grid-cols-1 gap-4">
                        {/* Projection Chart */}
                        <div className="bg-slate-800/30 border border-slate-700 p-3">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">
                                {selectedEvent.name} Projection ({selectedEvent.weighted_return?.toFixed(1) || simParams.annual_return}% Return)
                            </h3>
                            <div className="h-48">
                                <ResponsiveContainer width="100%" height="100%">
                                    <LineChart data={selectedEvent.roadmap || []}>
                                        <XAxis dataKey="year" tick={{ fontSize: 10 }} stroke="#64748b" label={{ value: 'Years', position: 'bottom', fontSize: 10 }} />
                                        <YAxis tick={{ fontSize: 10 }} stroke="#64748b" tickFormatter={(v) => `¥${(v / 10000).toFixed(0)}万`} />
                                        <Tooltip
                                            contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 11 }}
                                            formatter={(value) => [`¥${(value as number || 0).toLocaleString()}`, '']}
                                        />
                                        <Legend wrapperStyle={{ fontSize: 10 }} />
                                        <Line type="monotone" dataKey="end_balance" stroke="#10b981" name="Balance" strokeWidth={2} dot={false} />
                                        <Line type="monotone" dataKey={() => selectedEvent.target_amount} stroke="#f97316" strokeDasharray="5 5" name="Target" dot={false} />
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                        </div>

                        {/* Roadmap Roadmap Table */}
                        <div className="bg-slate-800/30 border border-slate-700 overflow-hidden">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider p-3 bg-slate-800/50 border-b border-slate-700">Annual Roadmap</h3>
                            <div className="overflow-x-auto">
                                <table className="w-full text-left text-[10px]">
                                    <thead className="bg-slate-800 text-slate-500 uppercase">
                                        <tr>
                                            <th className="px-3 py-2 font-normal">Year</th>
                                            <th className="px-3 py-2 font-normal">Start Bal</th>
                                            <th className="px-3 py-2 font-normal">Contribution</th>
                                            <th className="px-3 py-2 font-normal">Gain</th>
                                            <th className="px-3 py-2 font-normal">End Bal</th>
                                            <th className="px-3 py-2 font-normal text-right">Coverage</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-800">
                                        {selectedEvent.roadmap?.map(row => (
                                            <tr key={row.year} className="hover:bg-slate-700/30">
                                                <td className="px-3 py-2 text-slate-400">{row.year === 0 ? 'Current' : `Year ${row.year}`}</td>
                                                <td className="px-3 py-2 font-mono-nums">{formatCurrency(row.start_balance)}</td>
                                                <td className="px-3 py-2 font-mono-nums text-cyan-400">+{formatCurrency(row.contribution)}</td>
                                                <td className="px-3 py-2 font-mono-nums text-emerald-400">+{formatCurrency(row.investment_gain)}</td>
                                                <td className="px-3 py-2 font-mono-nums font-bold text-slate-200">{formatCurrency(row.end_balance)}</td>
                                                <td className="px-3 py-2 text-right">
                                                    <span className={`px-1.5 py-0.5 rounded ${row.goal_coverage >= 100 ? 'bg-emerald-900/40 text-emerald-400' : 'bg-slate-800 text-slate-500'}`}>
                                                        {row.goal_coverage}%
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        {/* Asset Allocations Section (Restored) */}
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-[10px] text-slate-500 uppercase tracking-wider mb-3 flex items-center justify-between">
                                <span className="flex items-center gap-1"><Link size={10} className="text-cyan-400" /> Allocated Assets</span>
                                <div className="flex items-center gap-3">
                                    <button
                                        onClick={handleAIOptimize}
                                        disabled={analyzing}
                                        className="flex items-center gap-1 text-[9px] text-purple-400 hover:text-purple-300 disabled:opacity-50"
                                    >
                                        <Sparkles size={10} /> {analyzing ? 'Optimizing...' : 'AI Optimize'}
                                    </button>
                                    <span className="text-slate-600 font-mono-nums">
                                        Total: {formatCurrency(selectedEvent.current_funded)}
                                    </span>
                                </div>
                            </h3>

                            <div className="space-y-2 mb-4">
                                {selectedEvent.allocations.length === 0 ? (
                                    <p className="text-[10px] text-slate-600 italic">No assets allocated to this goal.</p>
                                ) : (
                                    selectedEvent.allocations.map(alloc => (
                                        <div key={alloc.id} className="flex items-center justify-between p-2 bg-slate-900/50 border border-slate-700 group">
                                            <div className="flex-1">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs font-medium">{alloc.account_name}</span>
                                                    <span className="text-[9px] text-slate-500 font-mono-nums">({alloc.expected_return}% Return)</span>
                                                </div>
                                                <div className="flex items-center gap-2 text-[10px] text-slate-500">
                                                    <span>{alloc.allocation_percentage}% from account</span>
                                                    <span>•</span>
                                                    <span>{formatCurrency(alloc.account_balance * (alloc.allocation_percentage / 100))}</span>
                                                </div>
                                            </div>
                                            <button
                                                onClick={() => handleDeleteAllocation(alloc.id)}
                                                className="p-1 text-slate-600 hover:text-rose-400 opacity-0 group-hover:opacity-100 transition-opacity"
                                            >
                                                <Trash2 size={12} />
                                            </button>
                                        </div>
                                    ))
                                )}
                            </div>

                            {/* Add Allocation Form */}
                            <div className="grid grid-cols-12 gap-2 pt-3 border-t border-slate-800">
                                <div className="col-span-6">
                                    <select
                                        value={allocationForm.account_id}
                                        onChange={(e) => {
                                            const accId = parseInt(e.target.value);
                                            const asset = dashboardData?.unallocated_assets.find(a => a.id === accId);
                                            setAllocationForm({
                                                ...allocationForm,
                                                account_id: e.target.value,
                                                allocation_percentage: asset?.remaining_percentage ? asset.remaining_percentage.toString() : '0'
                                            });
                                        }}
                                        className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-[10px] text-slate-300"
                                    >
                                        <option value="">Select Asset Account...</option>
                                        {dashboardData?.unallocated_assets.map(acc => (
                                            <option key={acc.id} value={acc.id}>
                                                {acc.name} ({formatCurrency(acc.balance)}) - {Math.round(acc.remaining_percentage || 0)}% left
                                            </option>
                                        ))}
                                    </select>
                                </div>
                                <div className="col-span-4 relative">
                                    <input
                                        type="number"
                                        placeholder="%"
                                        value={allocationForm.allocation_percentage}
                                        onChange={(e) => setAllocationForm({ ...allocationForm, allocation_percentage: e.target.value })}
                                        max={100}
                                        className="w-full bg-slate-900 border border-slate-700 px-2 py-1.5 text-[10px] pr-5 font-mono-nums"
                                    />
                                    <span className="absolute right-2 top-1.5 text-[9px] text-slate-600">%</span>
                                </div>
                                <button
                                    onClick={handleAddAllocation}
                                    disabled={!allocationForm.account_id}
                                    className="col-span-2 bg-cyan-900/40 hover:bg-cyan-900/60 text-cyan-400 border border-cyan-800 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    <Plus size={14} />
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        );
    };

    return (
        <>
            <div className="h-full p-4">
                <SplitView
                    left={leftPane}
                    right={
                        <div className="h-full flex flex-col">
                            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                                <div className="p-2 flex-1 overflow-hidden">
                                    {renderRightPane()}
                                </div>
                            </TabPanel>
                        </div>
                    }
                    leftTitle="LIFE EVENTS"
                    rightTitle=""
                />
            </div>

            {showEventModal && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
                    <div className="bg-slate-900 border border-slate-700 p-6 w-full max-w-md">
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-sm font-medium">{editingEvent ? 'Edit Life Event' : 'New Life Event'}</h2>
                            <button onClick={() => setShowEventModal(false)}><X size={16} /></button>
                        </div>

                        <div className="space-y-3">
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase mb-1">Event Name</label>
                                <input
                                    type="text"
                                    placeholder="e.g., Retirement, House, Education"
                                    value={eventForm.name}
                                    onChange={(e) => setEventForm({ ...eventForm, name: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
                                />
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label className="block text-[10px] text-slate-500 uppercase mb-1">Target Date</label>
                                    <input
                                        type="date"
                                        value={eventForm.target_date}
                                        onChange={(e) => setEventForm({ ...eventForm, target_date: e.target.value })}
                                        className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
                                    />
                                </div>
                                <div>
                                    <label className="block text-[10px] text-slate-500 uppercase mb-1">Target Amount</label>
                                    <input
                                        type="number"
                                        placeholder="¥"
                                        value={eventForm.target_amount}
                                        onChange={(e) => setEventForm({ ...eventForm, target_amount: e.target.value })}
                                        className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-mono-nums"
                                    />
                                </div>
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase mb-1">Priority</label>
                                <select
                                    value={eventForm.priority}
                                    onChange={(e) => setEventForm({ ...eventForm, priority: parseInt(e.target.value) })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
                                >
                                    <option value={1}>High Priority</option>
                                    <option value={2}>Medium Priority</option>
                                    <option value={3}>Low Priority</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-[10px] text-slate-500 uppercase mb-1">Note (Optional)</label>
                                <textarea
                                    placeholder="Additional details..."
                                    value={eventForm.note}
                                    onChange={(e) => setEventForm({ ...eventForm, note: e.target.value })}
                                    className="w-full bg-slate-800 border border-slate-700 px-3 py-2 text-sm h-20 resize-none"
                                />
                            </div>
                        </div>

                        <div className="flex gap-2 mt-4">
                            <button
                                onClick={handleSaveEvent}
                                className="flex-1 bg-cyan-600 hover:bg-cyan-500 text-white py-2 text-xs font-medium"
                            >
                                {editingEvent ? 'Update Event' : 'Create Event'}
                            </button>
                            <button
                                onClick={() => setShowEventModal(false)}
                                className="px-4 bg-slate-800 hover:bg-slate-700 text-white py-2 text-xs"
                            >
                                Cancel
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
