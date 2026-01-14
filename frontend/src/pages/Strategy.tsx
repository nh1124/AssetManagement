import { useState, useEffect } from 'react';
import { Target, TrendingUp, Wallet, Plus, ChevronRight } from 'lucide-react';
import TabPanel from '../components/TabPanel';
import { getLifeEventsWithProgress, getGoalProbability, getSimulationConfig, saveSimulationConfig } from '../api';

const TABS = [
    { id: 'life-events', label: 'Life Events' },
    { id: 'simulation', label: 'Simulation' },
    { id: 'budget', label: 'Budget Builder' },
];

export default function Strategy() {
    const [activeTab, setActiveTab] = useState('life-events');
    const [lifeEvents, setLifeEvents] = useState<any[]>([]);
    const [goalData, setGoalData] = useState<any>(null);
    const [simConfig, setSimConfig] = useState({
        annual_return: 5.0,
        tax_rate: 20.0,
        is_nisa: true,
        monthly_savings: 100000
    });
    const [, setLoading] = useState(false);

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        setLoading(true);
        try {
            const [eventsData, probData, configData] = await Promise.all([
                getLifeEventsWithProgress(),
                getGoalProbability(),
                getSimulationConfig().catch(() => null)
            ]);
            setLifeEvents(eventsData);
            setGoalData(probData);
            if (configData) setSimConfig(configData);
        } catch (error) {
            console.error('Failed to fetch strategy data:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleSaveConfig = async () => {
        try {
            await saveSimulationConfig(simConfig);
            fetchData(); // Refresh to recalculate probabilities
        } catch (error) {
            console.error('Failed to save config:', error);
        }
    };

    const formatCurrency = (value: number) => `¥${value.toLocaleString()}`;

    const getPriorityColor = (priority: string) => {
        switch (priority) {
            case 'high': return 'text-rose-400 border-rose-600';
            case 'medium': return 'text-amber-400 border-amber-600';
            case 'low': return 'text-slate-400 border-slate-600';
            default: return 'text-slate-400 border-slate-600';
        }
    };

    const renderTabContent = () => {
        switch (activeTab) {
            case 'life-events':
                return (
                    <div className="space-y-4">
                        {/* Overall Goal Probability */}
                        <div className="bg-gradient-to-r from-emerald-900/20 to-cyan-900/20 border border-emerald-800/50 p-4">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-[10px] text-slate-500 uppercase">Overall Goal Probability</p>
                                    <p className="text-2xl font-mono-nums text-emerald-400">{goalData?.overall_probability || 0}%</p>
                                </div>
                                <div className="text-right text-xs text-slate-400">
                                    <p>{goalData?.total_goals || 0} goals</p>
                                    <p>Target: {formatCurrency(goalData?.total_target || 0)}</p>
                                </div>
                            </div>
                        </div>

                        {/* Life Events List */}
                        <div className="space-y-2">
                            {lifeEvents.length === 0 ? (
                                <div className="text-center py-8 text-slate-600 text-sm">
                                    No life events defined. Add your first goal!
                                </div>
                            ) : (
                                lifeEvents.map((event) => (
                                    <div key={event.id} className="bg-slate-800/30 border border-slate-700 p-3 hover:border-slate-600 transition-colors">
                                        <div className="flex items-start justify-between mb-2">
                                            <div className="flex items-center gap-2">
                                                <Target size={14} className={getPriorityColor(event.priority)} />
                                                <span className="text-sm font-medium">{event.name}</span>
                                                <span className={`text-[10px] px-1.5 py-0.5 border ${getPriorityColor(event.priority)}`}>
                                                    {event.priority}
                                                </span>
                                            </div>
                                            <div className="text-right">
                                                <p className="text-xs font-mono-nums">{formatCurrency(event.target_amount)}</p>
                                                <p className="text-[10px] text-slate-500">{event.target_date}</p>
                                            </div>
                                        </div>

                                        {/* Progress Bar */}
                                        <div className="space-y-1">
                                            <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                                                <div
                                                    className="h-full bg-gradient-to-r from-emerald-500 to-cyan-500 rounded-full transition-all"
                                                    style={{ width: `${Math.min(100, event.progress_pct)}%` }}
                                                />
                                            </div>
                                            <div className="flex justify-between text-[10px] text-slate-500">
                                                <span>Funded: {formatCurrency(event.funded_amount)}</span>
                                                <span>Projected: {formatCurrency(event.projected_amount)} ({event.probability.toFixed(0)}%)</span>
                                            </div>
                                            <div className="flex justify-between text-[10px] text-slate-600">
                                                <span>{event.months_remaining} months remaining</span>
                                                <span>Monthly: {formatCurrency(event.monthly_contribution)}</span>
                                            </div>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>

                        {/* Add Life Event Button */}
                        <button className="w-full border border-dashed border-slate-700 hover:border-emerald-600 p-3 text-xs text-slate-500 hover:text-emerald-400 flex items-center justify-center gap-1 transition-colors">
                            <Plus size={14} /> Add Life Event
                        </button>
                    </div>
                );

            case 'simulation':
                return (
                    <div className="space-y-4">
                        {/* Goal Probability Gauge */}
                        <div className="bg-slate-800/30 border border-slate-700 p-6 flex flex-col items-center">
                            <div className="relative w-40 h-40">
                                <svg className="transform -rotate-90" viewBox="0 0 100 100">
                                    {/* Background circle */}
                                    <circle
                                        cx="50" cy="50" r="40"
                                        fill="none"
                                        stroke="#334155"
                                        strokeWidth="8"
                                    />
                                    {/* Progress circle */}
                                    <circle
                                        cx="50" cy="50" r="40"
                                        fill="none"
                                        stroke={goalData?.overall_probability >= 80 ? '#10b981' : goalData?.overall_probability >= 50 ? '#f59e0b' : '#ef4444'}
                                        strokeWidth="8"
                                        strokeDasharray={`${(goalData?.overall_probability || 0) * 2.51} 251`}
                                        strokeLinecap="round"
                                    />
                                </svg>
                                <div className="absolute inset-0 flex flex-col items-center justify-center">
                                    <span className="text-3xl font-mono-nums">{goalData?.overall_probability || 0}%</span>
                                    <span className="text-[10px] text-slate-500">Goal Probability</span>
                                </div>
                            </div>
                        </div>

                        {/* Simulation Parameters */}
                        <div className="bg-slate-800/30 border border-slate-700 p-4 space-y-3">
                            <h3 className="text-xs font-medium text-slate-400 flex items-center gap-1">
                                <TrendingUp size={12} /> Simulation Parameters
                            </h3>

                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label className="block text-[10px] text-slate-500 uppercase mb-1">Annual Return (%)</label>
                                    <input
                                        type="number"
                                        step="0.1"
                                        value={simConfig.annual_return}
                                        onChange={(e) => setSimConfig({ ...simConfig, annual_return: parseFloat(e.target.value) })}
                                        className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                                    />
                                </div>
                                <div>
                                    <label className="block text-[10px] text-slate-500 uppercase mb-1">Tax Rate (%)</label>
                                    <input
                                        type="number"
                                        step="1"
                                        value={simConfig.tax_rate}
                                        onChange={(e) => setSimConfig({ ...simConfig, tax_rate: parseFloat(e.target.value) })}
                                        className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                                    />
                                </div>
                                <div>
                                    <label className="block text-[10px] text-slate-500 uppercase mb-1">Monthly Savings</label>
                                    <input
                                        type="number"
                                        step="10000"
                                        value={simConfig.monthly_savings}
                                        onChange={(e) => setSimConfig({ ...simConfig, monthly_savings: parseFloat(e.target.value) })}
                                        className="w-full bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums focus:outline-none focus:border-emerald-500"
                                    />
                                </div>
                                <div className="flex items-end">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={simConfig.is_nisa}
                                            onChange={(e) => setSimConfig({ ...simConfig, is_nisa: e.target.checked })}
                                            className="w-4 h-4 bg-slate-800 border border-slate-700"
                                        />
                                        <span className="text-xs">NISA Account</span>
                                    </label>
                                </div>
                            </div>

                            <button
                                onClick={handleSaveConfig}
                                className="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2 text-xs font-medium transition-colors"
                            >
                                Recalculate Probability
                            </button>
                        </div>
                    </div>
                );

            case 'budget':
                return (
                    <div className="space-y-4">
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs font-medium text-slate-400 flex items-center gap-1 mb-3">
                                <Wallet size={12} /> Monthly Budget Template
                            </h3>

                            <div className="space-y-2">
                                {lifeEvents.map((event) => (
                                    <div key={event.id} className="flex items-center justify-between py-2 border-b border-slate-800">
                                        <div className="flex items-center gap-2">
                                            <ChevronRight size={12} className="text-slate-600" />
                                            <span className="text-xs">Savings: {event.name}</span>
                                        </div>
                                        <span className="text-xs font-mono-nums text-emerald-400">
                                            {formatCurrency(event.monthly_contribution)}
                                        </span>
                                    </div>
                                ))}

                                {lifeEvents.length === 0 && (
                                    <p className="text-xs text-slate-600 py-4 text-center">
                                        Add life events to generate a budget template
                                    </p>
                                )}
                            </div>

                            <div className="border-t border-slate-700 mt-3 pt-3 flex justify-between text-sm font-medium">
                                <span>Total Monthly Savings</span>
                                <span className="text-emerald-400 font-mono-nums">
                                    {formatCurrency(simConfig.monthly_savings)}
                                </span>
                            </div>
                        </div>
                    </div>
                );

            default:
                return null;
        }
    };

    return (
        <div className="h-full p-4 overflow-auto">
            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                <div className="p-4">
                    {renderTabContent()}
                </div>
            </TabPanel>
        </div>
    );
}
