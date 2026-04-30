import { useEffect, useMemo, useState } from 'react';
import { BarChart3, RefreshCw, TrendingUp } from 'lucide-react';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts';
import TabPanel from '../components/TabPanel';
import TheLab from './TheLab';
import { getGoalDashboard, runMonteCarloSimulation } from '../api';
import { useToast } from '../components/Toast';
import type { LifeEvent, MonteCarloResult } from '../types';

interface DashboardData {
    events: LifeEvent[];
}

const TABS = [
    { id: 'simulation', label: 'Simulation' },
    { id: 'lab', label: 'Financial Lab' },
];

const formatCurrency = (value: number | undefined | null) => `JPY ${Math.round(value || 0).toLocaleString()}`;
const formatCompact = (value: number) => `JPY ${(value / 10000).toFixed(0)}man`;

export default function Analytics() {
    const { showToast } = useToast();
    const [activeTab, setActiveTab] = useState('simulation');
    const [dashboard, setDashboard] = useState<DashboardData | null>(null);
    const [selectedGoalId, setSelectedGoalId] = useState<number | null>(null);
    const [simParams, setSimParams] = useState({ annual_return: 5, inflation: 2, monthly_savings: 50000 });
    const [monteCarlo, setMonteCarlo] = useState<MonteCarloResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [simLoading, setSimLoading] = useState(false);

    const selectedGoal = useMemo(() => {
        return dashboard?.events.find((goal) => goal.id === selectedGoalId) ?? dashboard?.events[0] ?? null;
    }, [dashboard, selectedGoalId]);

    const fetchSimulationDashboard = async () => {
        setLoading(true);
        try {
            const data = await getGoalDashboard(
                simParams.annual_return,
                simParams.inflation,
                simParams.monthly_savings,
            );
            setDashboard(data);
            if (!selectedGoalId && data.events.length > 0) setSelectedGoalId(data.events[0].id);
        } catch (error) {
            console.error('Failed to load simulation dashboard:', error);
            showToast('Failed to load simulation data', 'error');
        } finally {
            setLoading(false);
        }
    };

    const fetchMonteCarlo = async (goalId: number) => {
        setSimLoading(true);
        try {
            setMonteCarlo(await runMonteCarloSimulation(goalId, 1000));
        } catch (error) {
            console.error('Failed to run Monte Carlo:', error);
            setMonteCarlo(null);
            showToast('Failed to run Monte Carlo simulation', 'error');
        } finally {
            setSimLoading(false);
        }
    };

    useEffect(() => {
        if (activeTab !== 'simulation') return;
        const timer = window.setTimeout(fetchSimulationDashboard, 300);
        return () => window.clearTimeout(timer);
    }, [activeTab, simParams.annual_return, simParams.inflation, simParams.monthly_savings]);

    useEffect(() => {
        if (activeTab === 'simulation' && selectedGoal?.id) fetchMonteCarlo(selectedGoal.id);
    }, [activeTab, selectedGoal?.id]);

    const monteCarloChartData = monteCarlo?.year_by_year.p50.map((p50, index) => ({
        year: index,
        p10: monteCarlo.year_by_year.p10[index] ?? p50,
        p50,
        p90: monteCarlo.year_by_year.p90[index] ?? p50,
    })) ?? [];

    const renderSimulation = () => (
        <div className="h-full overflow-auto p-4 space-y-4">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h1 className="text-xl font-semibold text-slate-100">Analytics Simulation</h1>
                </div>
                <button
                    onClick={fetchSimulationDashboard}
                    disabled={loading}
                    className="bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-2 text-xs text-slate-300 flex items-center gap-2 disabled:opacity-50"
                >
                    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
                </button>
            </div>

            <div className="grid grid-cols-1 min-[960px]:grid-cols-[340px_1fr] gap-4">
                <section className="space-y-4">
                    <div className="bg-slate-900/60 border border-slate-800 p-4">
                        <h2 className="text-xs text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2"><TrendingUp size={14} /> Assumptions</h2>
                        <div className="space-y-3">
                            <label className="block text-xs text-slate-500">
                                Goal
                                <select
                                    value={selectedGoal?.id ?? ''}
                                    onChange={(event) => setSelectedGoalId(Number(event.target.value))}
                                    className="mt-1 w-full bg-slate-900 border border-slate-700 px-2 py-2 text-xs text-slate-200"
                                >
                                    {(dashboard?.events ?? []).map((goal) => (
                                        <option key={goal.id} value={goal.id}>{goal.name}</option>
                                    ))}
                                </select>
                            </label>
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
                        </div>
                    </div>

                    {selectedGoal && (
                        <div className="bg-slate-900/60 border border-slate-800 p-4 space-y-3">
                            <h2 className="text-xs text-slate-400 uppercase tracking-wider">Selected Goal</h2>
                            <div className="grid grid-cols-2 gap-2 text-xs">
                                <div className="bg-slate-800/50 border border-slate-700 p-2">
                                    <p className="text-slate-500">Target</p>
                                    <p className="font-mono-nums text-cyan-400">{formatCurrency(selectedGoal.target_amount)}</p>
                                </div>
                                <div className="bg-slate-800/50 border border-slate-700 p-2">
                                    <p className="text-slate-500">Funded</p>
                                    <p className="font-mono-nums text-emerald-400">{formatCurrency(selectedGoal.current_funded)}</p>
                                </div>
                                <div className="bg-slate-800/50 border border-slate-700 p-2">
                                    <p className="text-slate-500">Gap</p>
                                    <p className="font-mono-nums text-amber-400">{formatCurrency(selectedGoal.gap)}</p>
                                </div>
                                <div className="bg-slate-800/50 border border-slate-700 p-2">
                                    <p className="text-slate-500">Status</p>
                                    <p className="font-mono-nums text-slate-200">{selectedGoal.status}</p>
                                </div>
                            </div>
                        </div>
                    )}
                </section>

                <section className="space-y-4 min-w-0">
                    {!selectedGoal ? (
                        <div className="bg-slate-900/60 border border-slate-800 p-10 text-center text-xs text-slate-600">Create a goal first to run simulations.</div>
                    ) : (
                        <>
                            <div className="bg-slate-900/60 border border-slate-800 p-4">
                                <h2 className="text-xs text-slate-400 uppercase tracking-wider mb-3">Projection ({selectedGoal.weighted_return?.toFixed(1) || simParams.annual_return}% return)</h2>
                                <div className="h-64">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <LineChart data={selectedGoal.roadmap ?? []} margin={{ top: 8, right: 16, bottom: 34, left: 8 }}>
                                            <XAxis dataKey="year" tick={{ fontSize: 10 }} stroke="#64748b" label={{ value: 'Years', position: 'insideBottom', offset: -8, fontSize: 10 }} />
                                            <YAxis tick={{ fontSize: 10 }} stroke="#64748b" tickFormatter={formatCompact} />
                                            <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 11 }} formatter={(value) => [formatCurrency(value as number), '']} />
                                            <Legend verticalAlign="bottom" align="center" wrapperStyle={{ fontSize: 10, paddingTop: 14 }} />
                                            <Line type="monotone" dataKey="end_balance" stroke="#10b981" name="Balance" strokeWidth={2} dot={false} />
                                            <Line type="monotone" dataKey={() => selectedGoal.target_amount} stroke="#f97316" strokeDasharray="5 5" name="Target" dot={false} />
                                        </LineChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                            <div className="bg-slate-900/60 border border-slate-800 p-4">
                                <h2 className="text-xs text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2"><BarChart3 size={14} /> Monte Carlo (1000 runs)</h2>
                                {simLoading ? (
                                    <p className="text-xs text-slate-500">Calculating...</p>
                                ) : monteCarlo ? (
                                    <>
                                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-xs">
                                            <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">Success</p><p className="font-mono-nums text-emerald-400">{monteCarlo.probability}%</p></div>
                                            <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">P10</p><p className="font-mono-nums">{formatCurrency(monteCarlo.percentiles.p10)}</p></div>
                                            <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">P50</p><p className="font-mono-nums text-cyan-400">{formatCurrency(monteCarlo.percentiles.p50)}</p></div>
                                            <div className="bg-slate-800/50 border border-slate-700 p-2"><p className="text-slate-500">P90</p><p className="font-mono-nums text-emerald-400">{formatCurrency(monteCarlo.percentiles.p90)}</p></div>
                                        </div>
                                        <div className="h-60">
                                            <ResponsiveContainer width="100%" height="100%">
                                                <LineChart data={monteCarloChartData} margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
                                                    <XAxis dataKey="year" tick={{ fontSize: 10 }} stroke="#64748b" />
                                                    <YAxis tick={{ fontSize: 10 }} stroke="#64748b" tickFormatter={formatCompact} />
                                                    <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 11 }} formatter={(value) => [formatCurrency(value as number), '']} />
                                                    <Legend verticalAlign="bottom" align="center" wrapperStyle={{ fontSize: 10, paddingTop: 14 }} />
                                                    <Line type="monotone" dataKey="p10" stroke="#f59e0b" name="P10" dot={false} />
                                                    <Line type="monotone" dataKey="p50" stroke="#22d3ee" name="P50" dot={false} />
                                                    <Line type="monotone" dataKey="p90" stroke="#10b981" name="P90" dot={false} />
                                                </LineChart>
                                            </ResponsiveContainer>
                                        </div>
                                    </>
                                ) : (
                                    <p className="text-xs text-slate-500">No simulation result yet.</p>
                                )}
                            </div>
                        </>
                    )}
                </section>
            </div>
        </div>
    );

    return (
        <div className="h-full flex flex-col">
            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                {activeTab === 'simulation' ? renderSimulation() : <TheLab />}
            </TabPanel>
        </div>
    );
}
