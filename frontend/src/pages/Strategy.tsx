import { useState } from 'react';
import { Plus, Edit, Calendar, TrendingUp, Wallet, ToggleLeft, ToggleRight } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import SplitView from '../components/SplitView';
import TabPanel from '../components/TabPanel';

const mockProjection = [
    { year: '2024', assets: 5000000, goal: 5000000 },
    { year: '2025', assets: 6200000, goal: 6500000 },
    { year: '2026', assets: 7800000, goal: 8000000 },
    { year: '2027', assets: 9500000, goal: 9500000 },
    { year: '2028', assets: 11500000, goal: 11000000 },
    { year: '2029', assets: 14000000, goal: 12500000 },
    { year: '2030', assets: 17000000, goal: 14000000 },
];

const mockLifeEvents = [
    { id: 1, name: 'House Down Payment', target_date: '2026-06-01', target_amount: 5000000, funded: 2400000 },
    { id: 2, name: 'Wedding Fund', target_date: '2027-03-01', target_amount: 3000000, funded: 800000 },
    { id: 3, name: 'Emergency Fund', target_date: '2025-12-01', target_amount: 1500000, funded: 1500000 },
];

const mockBudgetTemplate = [
    { id: 1, category: 'Food', amount: 50000 },
    { id: 2, category: 'Transport', amount: 15000 },
    { id: 3, category: 'Entertainment', amount: 20000 },
    { id: 4, category: 'Utilities', amount: 12000 },
    { id: 5, category: 'Shopping', amount: 30000 },
    { id: 6, category: 'Healthcare', amount: 10000 },
];

const TABS = [
    { id: 'simulation', label: 'Simulation' },
    { id: 'budget', label: 'Budget Builder' },
];

export default function Strategy() {
    const [activeTab, setActiveTab] = useState('simulation');
    const [annualReturn, setAnnualReturn] = useState(5);
    const [monthlySavings, setMonthlySavings] = useState(100000);
    const [taxRate, setTaxRate] = useState(20);
    const [isNisa, setIsNisa] = useState(true);
    const [budgetTemplate] = useState(mockBudgetTemplate);

    const totalBudget = budgetTemplate.reduce((sum, b) => sum + b.amount, 0);

    const leftPane = (
        <div className="space-y-6">
            {/* Life Events */}
            <div>
                <div className="flex justify-between items-center mb-3">
                    <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Life Events</h3>
                    <button className="text-emerald-400 hover:text-emerald-300 transition-colors">
                        <Plus size={16} />
                    </button>
                </div>
                <div className="space-y-2">
                    {mockLifeEvents.map((event) => {
                        const progress = Math.round((event.funded / event.target_amount) * 100);
                        return (
                            <div key={event.id} className="p-3 border border-slate-800 hover:border-slate-700 transition-colors group">
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-2">
                                        <Calendar className="text-cyan-400" size={14} />
                                        <span className="text-sm font-medium">{event.name}</span>
                                    </div>
                                    <button className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-slate-200 transition-all">
                                        <Edit size={12} />
                                    </button>
                                </div>
                                <div className="flex justify-between text-xs mb-1">
                                    <span className="text-slate-500">{event.target_date}</span>
                                    <span className="font-mono-nums text-amber-400">¥{event.target_amount.toLocaleString()}</span>
                                </div>
                                <div className="w-full bg-slate-800 h-1.5">
                                    <div
                                        className={`h-1.5 transition-all ${progress >= 100 ? 'bg-emerald-500' : 'bg-cyan-500'}`}
                                        style={{ width: `${Math.min(progress, 100)}%` }}
                                    />
                                </div>
                                <div className="text-[10px] text-slate-500 mt-1">
                                    {progress}% funded (¥{event.funded.toLocaleString()})
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* AI Advisor Placeholder */}
            <div className="border border-dashed border-slate-700 p-4 text-center">
                <TrendingUp className="mx-auto text-slate-600 mb-2" size={20} />
                <p className="text-xs text-slate-500">AI Strategy Advisor (Coming Soon)</p>
            </div>
        </div>
    );

    const renderTabContent = () => {
        switch (activeTab) {
            case 'simulation':
                return (
                    <div className="space-y-4">
                        {/* Simulation Parameters */}
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <div className="flex justify-between text-xs">
                                    <span className="text-slate-400">Annual Return</span>
                                    <span className="text-emerald-400 font-mono-nums">{annualReturn}%</span>
                                </div>
                                <input
                                    type="range" min="0" max="15" step="0.5" value={annualReturn}
                                    onChange={(e) => setAnnualReturn(parseFloat(e.target.value))}
                                    className="w-full h-1.5 bg-slate-700 appearance-none cursor-pointer accent-emerald-500"
                                />
                            </div>
                            <div className="space-y-2">
                                <div className="flex justify-between text-xs">
                                    <span className="text-slate-400">Monthly Savings</span>
                                    <span className="text-cyan-400 font-mono-nums">¥{monthlySavings.toLocaleString()}</span>
                                </div>
                                <input
                                    type="range" min="0" max="500000" step="10000" value={monthlySavings}
                                    onChange={(e) => setMonthlySavings(parseInt(e.target.value))}
                                    className="w-full h-1.5 bg-slate-700 appearance-none cursor-pointer accent-cyan-500"
                                />
                            </div>
                            <div className="space-y-2">
                                <div className="flex justify-between text-xs">
                                    <span className="text-slate-400">Tax Rate</span>
                                    <span className="text-amber-400 font-mono-nums">{taxRate}%</span>
                                </div>
                                <input
                                    type="range" min="0" max="50" step="1" value={taxRate}
                                    onChange={(e) => setTaxRate(parseInt(e.target.value))}
                                    className="w-full h-1.5 bg-slate-700 appearance-none cursor-pointer accent-amber-500"
                                />
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-slate-400">NISA Utilization</span>
                                <button onClick={() => setIsNisa(!isNisa)} className="text-emerald-400">
                                    {isNisa ? <ToggleRight size={24} /> : <ToggleLeft size={24} className="text-slate-500" />}
                                </button>
                            </div>
                        </div>

                        {/* Projection Chart */}
                        <div className="h-48">
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={mockProjection}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                                    <XAxis dataKey="year" stroke="#64748b" fontSize={10} />
                                    <YAxis stroke="#64748b" fontSize={10} tickFormatter={(v) => `¥${(v / 1000000).toFixed(0)}M`} />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', fontSize: '11px' }}
                                        formatter={(value) => value != null ? [`¥${Number(value).toLocaleString()}`, ''] : ['', '']}
                                    />
                                    <Line type="monotone" dataKey="assets" stroke="#34d399" strokeWidth={2} dot={{ fill: '#34d399', strokeWidth: 2 }} name="Projected" />
                                    <Line type="monotone" dataKey="goal" stroke="#fbbf24" strokeWidth={2} strokeDasharray="5 5" dot={{ fill: '#fbbf24', strokeWidth: 2 }} name="Goal" />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>

                        {/* Monte Carlo Summary */}
                        <div className="border border-emerald-800/50 bg-emerald-900/10 p-3">
                            <h4 className="text-xs font-medium text-emerald-400 mb-2">Monte Carlo Simulation</h4>
                            <div className="grid grid-cols-3 gap-4 text-center">
                                <div>
                                    <p className="text-xl font-bold font-mono-nums text-slate-100">72%</p>
                                    <p className="text-[10px] text-slate-500">Success Rate</p>
                                </div>
                                <div>
                                    <p className="text-xl font-bold font-mono-nums text-emerald-400">¥14.2M</p>
                                    <p className="text-[10px] text-slate-500">Median Outcome</p>
                                </div>
                                <div>
                                    <p className="text-xl font-bold font-mono-nums text-amber-400">2028</p>
                                    <p className="text-[10px] text-slate-500">Goal Year</p>
                                </div>
                            </div>
                        </div>
                    </div>
                );
            case 'budget':
                return (
                    <div className="space-y-4">
                        <div className="flex justify-between items-center">
                            <h4 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Monthly Budget Template</h4>
                            <div className="text-xs">
                                Total: <span className="font-mono-nums text-emerald-400">¥{totalBudget.toLocaleString()}</span>
                            </div>
                        </div>

                        <div className="border border-slate-800">
                            <table className="w-full text-xs">
                                <thead className="bg-slate-900">
                                    <tr className="border-b border-slate-800">
                                        <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Category</th>
                                        <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Target Amount</th>
                                        <th className="p-2 w-12"></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {budgetTemplate.map((item) => (
                                        <tr key={item.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                                            <td className="p-2 flex items-center gap-2">
                                                <Wallet size={12} className="text-cyan-400" />
                                                {item.category}
                                            </td>
                                            <td className="p-2 text-right font-mono-nums">¥{item.amount.toLocaleString()}</td>
                                            <td className="p-2">
                                                <button className="p-1 hover:bg-slate-700 text-slate-500 hover:text-slate-300">
                                                    <Edit size={12} />
                                                </button>
                                            </td>
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

    const rightPane = (
        <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
            {renderTabContent()}
        </TabPanel>
    );

    return <SplitView left={leftPane} right={rightPane} leftTitle="Life Events" rightTitle="Planning" />;
}
