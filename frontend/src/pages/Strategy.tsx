import { useState } from 'react';
import { Plus, Edit, Trash2, Calendar, Wallet } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import TabPanel from '../components/TabPanel';

interface LifeEvent {
    id: number;
    name: string;
    target_date: string;
    target_amount: number;
    priority: 'high' | 'medium' | 'low';
    funded: number;
    allocated_asset?: string;
}

const mockLifeEvents: LifeEvent[] = [
    { id: 1, name: 'House Down Payment', target_date: '2026-06-01', target_amount: 5000000, priority: 'high', funded: 2400000, allocated_asset: 'Savings' },
    { id: 2, name: 'Wedding Fund', target_date: '2027-03-01', target_amount: 3000000, priority: 'medium', funded: 800000 },
    { id: 3, name: 'Emergency Fund', target_date: '2025-12-01', target_amount: 1500000, priority: 'high', funded: 1500000, allocated_asset: 'Cash' },
    { id: 4, name: 'Car Purchase', target_date: '2028-01-01', target_amount: 2000000, priority: 'low', funded: 200000 },
];

const mockProjection = [
    { year: '2024', assets: 5000000, liabilities: 1200000 },
    { year: '2025', assets: 6500000, liabilities: 900000 },
    { year: '2026', assets: 8200000, liabilities: 600000 },
    { year: '2027', assets: 10500000, liabilities: 300000 },
    { year: '2028', assets: 13000000, liabilities: 0 },
];

const mockBudgetTemplate = [
    { category: 'Food', amount: 50000, derivedFrom: 'Living Expenses' },
    { category: 'Transport', amount: 15000, derivedFrom: 'Living Expenses' },
    { category: 'Savings', amount: 100000, derivedFrom: 'House Down Payment' },
    { category: 'Entertainment', amount: 20000, derivedFrom: 'Discretionary' },
];

const priorityColors = {
    high: 'text-rose-400 bg-rose-900/30',
    medium: 'text-amber-400 bg-amber-900/30',
    low: 'text-slate-400 bg-slate-800',
};

const TABS = [
    { id: 'events', label: 'Life Events' },
    { id: 'simulation', label: 'Simulation' },
    { id: 'budget', label: 'Budget Builder' },
];

export default function Strategy() {
    const [activeTab, setActiveTab] = useState('events');
    const [lifeEvents] = useState(mockLifeEvents);
    const [simulationParams, setSimulationParams] = useState({
        annualReturn: 5,
        taxRate: 20,
        isNisa: true,
    });

    const totalGoalAmount = lifeEvents.reduce((sum, e) => sum + e.target_amount, 0);
    const totalFunded = lifeEvents.reduce((sum, e) => sum + e.funded, 0);
    const goalProbability = Math.min(100, Math.round((totalFunded / totalGoalAmount) * 100 + simulationParams.annualReturn * 3));

    const gaugeData = [
        { name: 'Achieved', value: goalProbability },
        { name: 'Remaining', value: 100 - goalProbability },
    ];

    const renderTabContent = () => {
        switch (activeTab) {
            case 'events':
                return (
                    <div className="space-y-3">
                        <div className="flex justify-between items-center">
                            <p className="text-[10px] text-slate-500">Define your future liabilities (goals)</p>
                            <button className="text-emerald-400 hover:text-emerald-300 transition-colors">
                                <Plus size={16} />
                            </button>
                        </div>

                        {lifeEvents.map((event) => {
                            const progress = Math.round((event.funded / event.target_amount) * 100);
                            const daysUntil = Math.ceil((new Date(event.target_date).getTime() - Date.now()) / (1000 * 60 * 60 * 24));

                            return (
                                <div key={event.id} className="border border-slate-800 hover:border-slate-700 transition-colors group">
                                    <div className="p-3">
                                        <div className="flex items-center justify-between mb-2">
                                            <div className="flex items-center gap-2">
                                                <span className={`text-[9px] px-1.5 py-0.5 font-medium uppercase ${priorityColors[event.priority]}`}>
                                                    {event.priority}
                                                </span>
                                                <span className="text-sm font-medium">{event.name}</span>
                                            </div>
                                            <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                <button className="p-1 hover:bg-slate-800 text-slate-500 hover:text-slate-300">
                                                    <Edit size={12} />
                                                </button>
                                                <button className="p-1 hover:bg-slate-800 text-slate-500 hover:text-rose-400">
                                                    <Trash2 size={12} />
                                                </button>
                                            </div>
                                        </div>

                                        <div className="grid grid-cols-3 gap-2 text-xs mb-2">
                                            <div>
                                                <span className="text-slate-500">Target</span>
                                                <p className="font-mono-nums text-amber-400">¥{event.target_amount.toLocaleString()}</p>
                                            </div>
                                            <div>
                                                <span className="text-slate-500">Funded</span>
                                                <p className="font-mono-nums text-emerald-400">¥{event.funded.toLocaleString()}</p>
                                            </div>
                                            <div>
                                                <span className="text-slate-500">Due</span>
                                                <p className="flex items-center gap-1">
                                                    <Calendar size={10} className="text-slate-500" />
                                                    {daysUntil > 0 ? `${daysUntil}d` : 'Past'}
                                                </p>
                                            </div>
                                        </div>

                                        <div className="w-full bg-slate-800 h-1.5">
                                            <div
                                                className={`h-1.5 transition-all ${progress >= 100 ? 'bg-emerald-500' : progress >= 50 ? 'bg-cyan-500' : 'bg-amber-500'}`}
                                                style={{ width: `${Math.min(progress, 100)}%` }}
                                            />
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                );

            case 'simulation':
                return (
                    <div className="space-y-4">
                        {/* Goal Probability */}
                        <div className="border border-emerald-800/50 bg-emerald-900/10 p-4">
                            <div className="flex items-center gap-4">
                                <div className="w-20 h-20 flex-shrink-0">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <PieChart>
                                            <Pie data={gaugeData} cx="50%" cy="50%" innerRadius={25} outerRadius={38} startAngle={90} endAngle={-270} dataKey="value" stroke="none">
                                                <Cell fill="#34d399" />
                                                <Cell fill="#1e293b" />
                                            </Pie>
                                        </PieChart>
                                    </ResponsiveContainer>
                                </div>
                                <div>
                                    <p className="text-2xl font-bold font-mono-nums text-emerald-400">{goalProbability}%</p>
                                    <p className="text-xs text-slate-400 uppercase tracking-wider">Goal Probability</p>
                                </div>
                            </div>
                        </div>

                        {/* Parameters */}
                        <div className="space-y-3">
                            <div>
                                <div className="flex justify-between text-xs mb-1">
                                    <span className="text-slate-400">Annual Return</span>
                                    <span className="text-emerald-400 font-mono-nums">{simulationParams.annualReturn}%</span>
                                </div>
                                <input
                                    type="range" min="0" max="15" step="0.5"
                                    value={simulationParams.annualReturn}
                                    onChange={(e) => setSimulationParams({ ...simulationParams, annualReturn: parseFloat(e.target.value) })}
                                    className="w-full h-1.5 bg-slate-700 appearance-none cursor-pointer accent-emerald-500"
                                />
                            </div>
                            <div>
                                <div className="flex justify-between text-xs mb-1">
                                    <span className="text-slate-400">Tax Rate</span>
                                    <span className="text-amber-400 font-mono-nums">{simulationParams.taxRate}%</span>
                                </div>
                                <input
                                    type="range" min="0" max="50" step="1"
                                    value={simulationParams.taxRate}
                                    onChange={(e) => setSimulationParams({ ...simulationParams, taxRate: parseInt(e.target.value) })}
                                    className="w-full h-1.5 bg-slate-700 appearance-none cursor-pointer accent-amber-500"
                                />
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-slate-400">NISA Utilization</span>
                                <button
                                    onClick={() => setSimulationParams({ ...simulationParams, isNisa: !simulationParams.isNisa })}
                                    className={`w-10 h-5 rounded-full transition-colors ${simulationParams.isNisa ? 'bg-emerald-600' : 'bg-slate-700'}`}
                                >
                                    <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform ${simulationParams.isNisa ? 'translate-x-5' : 'translate-x-0.5'}`} />
                                </button>
                            </div>
                        </div>

                        {/* Chart */}
                        <div className="h-36">
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={mockProjection}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                                    <XAxis dataKey="year" stroke="#64748b" fontSize={10} />
                                    <YAxis stroke="#64748b" fontSize={10} tickFormatter={(v) => `¥${(v / 1000000).toFixed(0)}M`} />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', fontSize: '11px' }}
                                        formatter={(value) => value != null ? [`¥${Number(value).toLocaleString()}`, ''] : ['', '']}
                                    />
                                    <Line type="monotone" dataKey="assets" stroke="#34d399" strokeWidth={2} dot={{ fill: '#34d399', strokeWidth: 2 }} />
                                    <Line type="monotone" dataKey="liabilities" stroke="#f87171" strokeWidth={2} strokeDasharray="5 5" />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                    </div>
                );

            case 'budget':
                return (
                    <div className="space-y-3">
                        <div className="flex justify-between items-center">
                            <p className="text-[10px] text-slate-500">Monthly budget template</p>
                            <span className="text-xs text-slate-400">
                                Total: <span className="font-mono-nums text-emerald-400">¥{mockBudgetTemplate.reduce((sum, b) => sum + b.amount, 0).toLocaleString()}</span>
                            </span>
                        </div>

                        <div className="border border-slate-800">
                            <table className="w-full text-xs">
                                <thead className="bg-slate-900/50">
                                    <tr className="border-b border-slate-800">
                                        <th className="text-left p-2 text-slate-500 font-medium">Category</th>
                                        <th className="text-right p-2 text-slate-500 font-medium">Amount</th>
                                        <th className="text-left p-2 text-slate-500 font-medium">Source</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {mockBudgetTemplate.map((b, i) => (
                                        <tr key={i} className="border-b border-slate-800/50">
                                            <td className="p-2 flex items-center gap-1">
                                                <Wallet size={10} className="text-cyan-400" />
                                                {b.category}
                                            </td>
                                            <td className="p-2 text-right font-mono-nums">¥{b.amount.toLocaleString()}</td>
                                            <td className="p-2 text-slate-500 text-[10px]">{b.derivedFrom}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                        <button className="w-full border border-dashed border-slate-700 py-2 text-xs text-slate-500 hover:text-slate-400 hover:border-slate-600 flex items-center justify-center gap-1">
                            <Plus size={14} /> Add Category
                        </button>
                    </div>
                );

            default:
                return null;
        }
    };

    return (
        <div className="h-full p-4 overflow-auto">
            <div className="flex justify-between items-center mb-4">
                <h1 className="text-lg font-semibold">Strategy</h1>
                <div className="grid grid-cols-2 gap-2 text-center">
                    <div className="border border-slate-800 px-3 py-1">
                        <p className="text-sm font-bold font-mono-nums text-emerald-400">¥{(totalGoalAmount / 1000000).toFixed(1)}M</p>
                        <p className="text-[9px] text-slate-500">Goals</p>
                    </div>
                    <div className="border border-slate-800 px-3 py-1">
                        <p className="text-sm font-bold font-mono-nums text-cyan-400">¥{(totalFunded / 1000000).toFixed(1)}M</p>
                        <p className="text-[9px] text-slate-500">Funded</p>
                    </div>
                </div>
            </div>

            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                {renderTabContent()}
            </TabPanel>
        </div>
    );
}
