import { useEffect, useMemo, useState } from 'react';
import { Calendar, Edit2, Flag, Link, Plus, Save, Sparkles, Trash2, X } from 'lucide-react';
import {
    addAllocation,
    createGoal,
    createMilestone,
    deleteAllocation,
    deleteGoal,
    deleteMilestone,
    getMilestones,
    getGoalDashboard,
    optimizeAllocations,
    updateGoal,
} from '../api';
import { useToast } from '../components/Toast';
import { PRIORITY_COLORS, priorityLabel } from '../utils/priority';
import type { LifeEvent, Milestone } from '../types';

interface DashboardData {
    events: LifeEvent[];
    unallocated_assets: Array<{ id: number; name: string; balance: number; remaining_percentage?: number }>;
    total_allocated: number;
    total_unallocated: number;
}

const emptyEventForm = {
    name: '',
    target_date: '',
    target_amount: '',
    priority: 2 as 1 | 2 | 3,
    note: '',
};

const formatCurrency = (value: number | undefined | null) => `JPY ${Math.round(value || 0).toLocaleString()}`;

export default function Goal() {
    const { showToast } = useToast();
    const [dashboard, setDashboard] = useState<DashboardData | null>(null);
    const [selectedGoal, setSelectedGoal] = useState<LifeEvent | null>(null);
    const [milestones, setMilestones] = useState<Milestone[]>([]);
    const [eventForm, setEventForm] = useState(emptyEventForm);
    const [editingEvent, setEditingEvent] = useState<LifeEvent | null>(null);
    const [showEventModal, setShowEventModal] = useState(false);
    const [allocationForm, setAllocationForm] = useState({ account_id: '', allocation_percentage: '100' });
    const [milestoneForm, setMilestoneForm] = useState({ date: '', target_amount: '', note: '' });
    const [loading, setLoading] = useState(false);
    const [optimizing, setOptimizing] = useState(false);

    const selectedGoalId = selectedGoal?.id;

    const fetchGoalWorkspace = async () => {
        setLoading(true);
        try {
            const [dashboardData, milestoneData] = await Promise.all([
                getGoalDashboard(),
                getMilestones(),
            ]);
            setDashboard(dashboardData);
            setMilestones(milestoneData);

            const nextSelected = selectedGoalId
                ? dashboardData.events.find((goal: LifeEvent) => goal.id === selectedGoalId)
                : dashboardData.events[0];
            setSelectedGoal(nextSelected ?? null);
        } catch (error) {
            console.error('Failed to load goal workspace:', error);
            showToast('Failed to load goals', 'error');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchGoalWorkspace();
    }, []);

    const totals = useMemo(() => {
        const goals = dashboard?.events ?? [];
        return {
            target: goals.reduce((sum, goal) => sum + (goal.target_amount || 0), 0),
            gap: goals.reduce((sum, goal) => sum + Math.max(0, goal.gap || 0), 0),
            count: goals.length,
        };
    }, [dashboard]);

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
            } else {
                await createGoal(payload);
                showToast('Goal created', 'success');
            }
            setShowEventModal(false);
            await fetchGoalWorkspace();
        } catch (error) {
            showToast('Failed to save goal', 'error');
        }
    };

    const removeEvent = async (eventId: number) => {
        if (!confirm('Delete this goal?')) return;
        try {
            await deleteGoal(eventId);
            if (selectedGoal?.id === eventId) setSelectedGoal(null);
            showToast('Goal deleted', 'info');
            await fetchGoalWorkspace();
        } catch (error) {
            showToast('Failed to delete goal', 'error');
        }
    };

    const saveAllocation = async () => {
        if (!selectedGoal || !allocationForm.account_id) return;
        try {
            await addAllocation(selectedGoal.id, {
                account_id: Number(allocationForm.account_id),
                allocation_percentage: Number(allocationForm.allocation_percentage),
            });
            setAllocationForm({ account_id: '', allocation_percentage: '100' });
            showToast('Allocation added', 'success');
            await fetchGoalWorkspace();
        } catch (error) {
            showToast('Failed to add allocation', 'error');
        }
    };

    const removeAllocation = async (allocationId: number) => {
        try {
            await deleteAllocation(allocationId);
            showToast('Allocation removed', 'info');
            await fetchGoalWorkspace();
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
            for (const suggestion of suggestions) {
                await addAllocation(suggestion.life_event_id, {
                    account_id: suggestion.account_id,
                    allocation_percentage: suggestion.percentage,
                });
            }
            showToast('Optimized allocations applied', 'success');
            await fetchGoalWorkspace();
        } catch (error) {
            showToast('Failed to optimize allocations', 'error');
        } finally {
            setOptimizing(false);
        }
    };

    const createRoadmapMilestone = async () => {
        if (!milestoneForm.date || !milestoneForm.target_amount) return;
        try {
            await createMilestone({
                date: milestoneForm.date,
                target_amount: Number(milestoneForm.target_amount),
                note: milestoneForm.note,
            });
            setMilestoneForm({ date: '', target_amount: '', note: '' });
            showToast('Milestone created', 'success');
            await fetchGoalWorkspace();
        } catch (error) {
            showToast('Failed to create milestone', 'error');
        }
    };

    const removeRoadmapMilestone = async (id: number) => {
        if (!confirm('Delete this milestone?')) return;
        try {
            await deleteMilestone(id);
            showToast('Milestone deleted', 'info');
            await fetchGoalWorkspace();
        } catch (error) {
            showToast('Failed to delete milestone', 'error');
        }
    };

    return (
        <div className="h-full overflow-auto p-4 space-y-4">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h1 className="text-xl font-semibold text-slate-100">Goal</h1>
                </div>
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
                        {(dashboard?.events ?? []).length === 0 ? (
                            <div className="text-center text-xs text-slate-600 py-10">No goals yet. Create the first north star.</div>
                        ) : (
                            dashboard?.events.map((goal) => (
                                <button
                                    key={goal.id}
                                    onClick={() => setSelectedGoal(goal)}
                                    className={`w-full text-left border px-3 py-3 transition-colors ${selectedGoal?.id === goal.id ? 'border-cyan-700 bg-cyan-950/20' : 'border-slate-800 bg-slate-800/20 hover:bg-slate-800/50'}`}
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
                    {!selectedGoal ? (
                        <div className="h-full flex items-center justify-center text-xs text-slate-600">Select or create a goal to edit its roadmap.</div>
                    ) : (
                        <div className="p-4 space-y-4">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <p className="text-[10px] text-slate-500 uppercase">Selected Goal</p>
                                    <h2 className="text-lg text-slate-100">{selectedGoal.name}</h2>
                                    <p className="text-xs text-slate-500 mt-1">{selectedGoal.note || 'No note yet.'}</p>
                                </div>
                                <div className="flex gap-2">
                                    <button onClick={() => openEditModal(selectedGoal)} className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300"><Edit2 size={14} /></button>
                                    <button onClick={() => removeEvent(selectedGoal.id)} className="p-2 bg-slate-800 hover:bg-rose-950 text-slate-300 hover:text-rose-300"><Trash2 size={14} /></button>
                                </div>
                            </div>

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

                            <div className="grid grid-cols-1 min-[1120px]:grid-cols-2 gap-4">
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
                                        {(selectedGoal.allocations ?? []).length === 0 ? (
                                            <p className="text-xs text-slate-600">No assets allocated yet.</p>
                                        ) : (
                                            selectedGoal.allocations.map((allocation) => (
                                                <div key={allocation.id} className="flex items-center justify-between gap-3 bg-slate-900/60 border border-slate-700 p-2 text-xs">
                                                    <div>
                                                        <p className="text-slate-200">{allocation.account_name}</p>
                                                        <p className="text-[10px] text-slate-500">{allocation.allocation_percentage}% / {formatCurrency((allocation.account_balance || 0) * allocation.allocation_percentage / 100)}</p>
                                                    </div>
                                                    <button onClick={() => removeAllocation(allocation.id)} className="text-slate-600 hover:text-rose-400"><Trash2 size={12} /></button>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                    <div className="grid grid-cols-12 gap-2 border-t border-slate-800 pt-3">
                                        <select
                                            value={allocationForm.account_id}
                                            onChange={(event) => {
                                                const accountId = Number(event.target.value);
                                                const account = dashboard?.unallocated_assets.find((asset) => asset.id === accountId);
                                                setAllocationForm({
                                                    account_id: event.target.value,
                                                    allocation_percentage: String(Math.round(account?.remaining_percentage ?? 100)),
                                                });
                                            }}
                                            className="col-span-7 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs text-slate-300"
                                        >
                                            <option value="">Select asset...</option>
                                            {(dashboard?.unallocated_assets ?? []).map((asset) => (
                                                <option key={asset.id} value={asset.id}>{asset.name} ({Math.round(asset.remaining_percentage ?? 0)}% left)</option>
                                            ))}
                                        </select>
                                        <input
                                            type="number"
                                            value={allocationForm.allocation_percentage}
                                            onChange={(event) => setAllocationForm({ ...allocationForm, allocation_percentage: event.target.value })}
                                            className="col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                                        />
                                        <button onClick={saveAllocation} className="col-span-2 bg-cyan-900/50 border border-cyan-800 text-cyan-300 hover:bg-cyan-900"><Plus size={14} className="mx-auto" /></button>
                                    </div>
                                </div>

                                <div className="bg-slate-800/30 border border-slate-700 p-4">
                                    <h3 className="text-[10px] text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-1"><Flag size={12} /> Roadmap Milestones</h3>
                                    <div className="grid grid-cols-12 gap-2 mb-3">
                                        <input type="date" value={milestoneForm.date} onChange={(event) => setMilestoneForm({ ...milestoneForm, date: event.target.value })} className="col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                                        <input type="number" placeholder="Target" value={milestoneForm.target_amount} onChange={(event) => setMilestoneForm({ ...milestoneForm, target_amount: event.target.value })} className="col-span-3 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums" />
                                        <input placeholder="Note" value={milestoneForm.note} onChange={(event) => setMilestoneForm({ ...milestoneForm, note: event.target.value })} className="col-span-4 bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs" />
                                        <button onClick={createRoadmapMilestone} className="col-span-2 bg-emerald-900/50 border border-emerald-800 text-emerald-300 text-xs">Add</button>
                                    </div>
                                    <div className="space-y-2 max-h-52 overflow-auto">
                                        {milestones.map((milestone) => (
                                            <div key={milestone.id} className="flex items-center justify-between bg-slate-900/60 border border-slate-700 p-2 text-xs">
                                                <div className="flex items-center gap-3">
                                                    <Calendar size={12} className="text-slate-500" />
                                                    <span className="font-mono-nums text-slate-300">{milestone.date}</span>
                                                    <span className="font-mono-nums text-emerald-400">{formatCurrency(milestone.target_amount)}</span>
                                                    <span className="text-slate-500">{milestone.note}</span>
                                                </div>
                                                <button onClick={() => removeRoadmapMilestone(milestone.id)} className="text-slate-600 hover:text-rose-400"><Trash2 size={12} /></button>
                                            </div>
                                        ))}
                                    </div>
                                </div>
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
                        </div>
                    )}
                </section>
            </div>

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
