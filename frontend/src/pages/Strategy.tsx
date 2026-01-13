import { useState } from 'react';
import { Plus, Edit, Calendar, TrendingUp } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import SplitView from '../components/SplitView';

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
    { id: 1, name: 'House Down Payment', target_date: '2026-06-01', target_amount: 5000000 },
    { id: 2, name: 'Wedding Fund', target_date: '2027-03-01', target_amount: 3000000 },
    { id: 3, name: 'Emergency Fund', target_date: '2025-12-01', target_amount: 1500000 },
];

export default function Strategy() {
    const [annualReturn, setAnnualReturn] = useState(5);
    const [monthlySavings, setMonthlySavings] = useState(100000);

    const leftPane = (
        <div className="space-y-6">
            {/* Life Events */}
            <div>
                <div className="flex justify-between items-center mb-3">
                    <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Life Events</h3>
                    <button className="text-emerald-400 hover:text-emerald-300 transition-colors">
                        <Plus size={18} />
                    </button>
                </div>
                <div className="space-y-2">
                    {mockLifeEvents.map((event) => (
                        <div
                            key={event.id}
                            className="flex items-center justify-between p-3 bg-slate-700/50 rounded-lg hover:bg-slate-700 transition-colors group"
                        >
                            <div className="flex items-center gap-3">
                                <Calendar className="text-cyan-400" size={18} />
                                <div>
                                    <p className="text-sm font-medium">{event.name}</p>
                                    <p className="text-xs text-slate-500">{event.target_date}</p>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-amber-400">
                                    ¥{event.target_amount.toLocaleString()}
                                </span>
                                <button className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-slate-200 transition-all">
                                    <Edit size={14} />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Simulation Parameters */}
            <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Simulation Parameters</h3>

                <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                        <span className="text-slate-300">Annual Return</span>
                        <span className="text-emerald-400 font-medium">{annualReturn}%</span>
                    </div>
                    <input
                        type="range"
                        min="0"
                        max="15"
                        step="0.5"
                        value={annualReturn}
                        onChange={(e) => setAnnualReturn(parseFloat(e.target.value))}
                        className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                    />
                </div>

                <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                        <span className="text-slate-300">Monthly Savings</span>
                        <span className="text-cyan-400 font-medium">¥{monthlySavings.toLocaleString()}</span>
                    </div>
                    <input
                        type="range"
                        min="0"
                        max="500000"
                        step="10000"
                        value={monthlySavings}
                        onChange={(e) => setMonthlySavings(parseInt(e.target.value))}
                        className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-cyan-500"
                    />
                </div>
            </div>

            {/* AI Chat Placeholder */}
            <div className="bg-slate-700/30 border border-dashed border-slate-600 rounded-lg p-4 text-center">
                <TrendingUp className="mx-auto text-slate-500 mb-2" size={24} />
                <p className="text-sm text-slate-500">AI Advisor (Coming Soon)</p>
            </div>
        </div>
    );

    const rightPane = (
        <div className="space-y-4">
            <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Projected Asset Growth</h3>

            <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={mockProjection}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="year" stroke="#94a3b8" fontSize={12} />
                        <YAxis stroke="#94a3b8" fontSize={12} tickFormatter={(v) => `¥${(v / 1000000).toFixed(0)}M`} />
                        <Tooltip
                            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                            labelStyle={{ color: '#f1f5f9' }}
                            formatter={(value) => value != null ? [`¥${Number(value).toLocaleString()}`, ''] : ['', '']}
                        />
                        <Line
                            type="monotone"
                            dataKey="assets"
                            stroke="#34d399"
                            strokeWidth={2}
                            dot={{ fill: '#34d399', strokeWidth: 2 }}
                            name="Projected Assets"
                        />
                        <Line
                            type="monotone"
                            dataKey="goal"
                            stroke="#fbbf24"
                            strokeWidth={2}
                            strokeDasharray="5 5"
                            dot={{ fill: '#fbbf24', strokeWidth: 2 }}
                            name="Goal Target"
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>

            {/* Monte Carlo Summary */}
            <div className="bg-gradient-to-r from-emerald-900/30 to-cyan-900/30 border border-emerald-700/50 rounded-lg p-4">
                <h4 className="text-sm font-semibold text-emerald-400 mb-2">Monte Carlo Simulation</h4>
                <div className="grid grid-cols-3 gap-4 text-center">
                    <div>
                        <p className="text-2xl font-bold text-slate-100">72%</p>
                        <p className="text-xs text-slate-400">Success Rate</p>
                    </div>
                    <div>
                        <p className="text-2xl font-bold text-emerald-400">¥14.2M</p>
                        <p className="text-xs text-slate-400">Median Outcome</p>
                    </div>
                    <div>
                        <p className="text-2xl font-bold text-amber-400">2028</p>
                        <p className="text-xs text-slate-400">Goal Year</p>
                    </div>
                </div>
            </div>
        </div>
    );

    return <SplitView left={leftPane} right={rightPane} leftTitle="Controls" rightTitle="Simulation" />;
}
