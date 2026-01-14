import { useEffect, useState } from 'react';
import { TrendingUp, Wallet, AlertCircle, Target } from 'lucide-react';
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';
import type { AnalysisSummary } from '../types';
import { getAnalysisSummary } from '../api';

const mockBudgetVariance = [
    { category: 'Food', budget: 50000, actual: 42000 },
    { category: 'Transport', budget: 15000, actual: 18500 },
    { category: 'Entertainment', budget: 20000, actual: 12000 },
    { category: 'Utilities', budget: 12000, actual: 11200 },
    { category: 'Shopping', budget: 30000, actual: 28000 },
    { category: 'Healthcare', budget: 10000, actual: 5000 },
];

export default function Status() {
    const [summary, setSummary] = useState<AnalysisSummary | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        getAnalysisSummary()
            .then(setSummary)
            .catch(console.error)
            .finally(() => setLoading(false));
    }, []);

    const goalProbability = 72;
    const runwayMonths = 18;

    // CFO Logic: Effective Cash Calculation
    const totalCash = 1500000;
    const ccUnpaid = 45000;
    const nextMonthBudget = 137000; // Sum of essential budget
    const effectiveCash = totalCash - ccUnpaid - nextMonthBudget;

    // Pie chart data for goal probability gauge
    const gaugeData = [
        { name: 'Achieved', value: goalProbability },
        { name: 'Remaining', value: 100 - goalProbability },
    ];

    const totalBudget = mockBudgetVariance.reduce((sum, b) => sum + b.budget, 0);
    const totalActual = mockBudgetVariance.reduce((sum, b) => sum + b.actual, 0);
    const variance = totalBudget - totalActual;

    const cfoBriefing = `Monthly spending at 85% of budget with +¥${variance.toLocaleString()} surplus projected. Effective cash reserves cover ${runwayMonths} months at current burn rate. Transport overspend offset by Entertainment/Healthcare underspend.`;

    return (
        <div className="h-full overflow-auto p-4 space-y-4">
            {/* CFO Briefing */}
            <div className="border border-slate-800 bg-slate-900/50 p-4">
                <div className="flex items-start gap-3">
                    <div className="p-2 bg-emerald-900/30 border border-emerald-800 flex-shrink-0">
                        <AlertCircle size={14} className="text-emerald-400" />
                    </div>
                    <div>
                        <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">CFO Briefing</h2>
                        <p className="text-sm text-slate-300 leading-relaxed">{cfoBriefing}</p>
                    </div>
                </div>
            </div>

            {/* Key Metrics */}
            <div className="grid grid-cols-4 gap-0 border border-slate-800">
                {/* Goal Probability Gauge */}
                <div className="border-r border-slate-800 p-4 flex items-center gap-3">
                    <div className="w-16 h-16 flex-shrink-0">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={gaugeData}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={20}
                                    outerRadius={30}
                                    startAngle={90}
                                    endAngle={-270}
                                    dataKey="value"
                                    stroke="none"
                                >
                                    <Cell fill="#34d399" />
                                    <Cell fill="#1e293b" />
                                </Pie>
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                    <div>
                        <p className="text-xl font-bold font-mono-nums text-emerald-400">{goalProbability}%</p>
                        <p className="text-[10px] text-slate-500 uppercase tracking-wider">Goal Probability</p>
                    </div>
                </div>

                {/* Effective Cash */}
                <div className="border-r border-slate-800 p-4">
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Effective Cash</span>
                        <Wallet className="text-cyan-500" size={14} />
                    </div>
                    <p className="text-xl font-bold font-mono-nums text-cyan-400">
                        ¥{effectiveCash.toLocaleString()}
                    </p>
                    <p className="text-[10px] text-slate-600 mt-1">
                        Cash - CC - Budget
                    </p>
                </div>

                {/* Monthly Variance */}
                <div className="border-r border-slate-800 p-4">
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Budget Variance</span>
                        <Target className="text-amber-500" size={14} />
                    </div>
                    <p className={`text-xl font-bold font-mono-nums ${variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {variance >= 0 ? '+' : ''}¥{variance.toLocaleString()}
                    </p>
                    <p className="text-[10px] text-slate-600 mt-1">
                        {Math.round((totalActual / totalBudget) * 100)}% of budget used
                    </p>
                </div>

                {/* Runway */}
                <div className="p-4">
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Runway</span>
                        <TrendingUp className="text-emerald-500" size={14} />
                    </div>
                    <p className="text-xl font-bold font-mono-nums text-emerald-400">
                        {runwayMonths} <span className="text-sm text-slate-500">months</span>
                    </p>
                    <p className="text-[10px] text-slate-600 mt-1">
                        At current burn rate
                    </p>
                </div>
            </div>

            {/* Budget Variance Table */}
            <div className="border border-slate-800">
                <div className="px-3 py-2 border-b border-slate-800 bg-slate-900">
                    <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">This Month: Budget vs Actual</h3>
                </div>
                <table className="w-full text-xs">
                    <thead className="bg-slate-900/50">
                        <tr className="border-b border-slate-800">
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Category</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Budget</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Actual</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Variance</th>
                            <th className="p-2 w-24 text-slate-500 uppercase tracking-wider font-medium">Progress</th>
                        </tr>
                    </thead>
                    <tbody>
                        {mockBudgetVariance.map((item) => {
                            const itemVariance = item.budget - item.actual;
                            const pct = Math.round((item.actual / item.budget) * 100);
                            return (
                                <tr key={item.category} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                                    <td className="p-2">{item.category}</td>
                                    <td className="p-2 text-right font-mono-nums text-slate-400">¥{item.budget.toLocaleString()}</td>
                                    <td className="p-2 text-right font-mono-nums">{item.actual.toLocaleString()}</td>
                                    <td className={`p-2 text-right font-mono-nums ${itemVariance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                        {itemVariance >= 0 ? '+' : ''}¥{itemVariance.toLocaleString()}
                                    </td>
                                    <td className="p-2">
                                        <div className="w-full bg-slate-800 h-1.5">
                                            <div
                                                className={`h-1.5 ${pct > 100 ? 'bg-rose-500' : pct > 80 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                                                style={{ width: `${Math.min(pct, 100)}%` }}
                                            />
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                    <tfoot className="bg-slate-900/80">
                        <tr className="border-t border-slate-700">
                            <td className="p-2 font-medium">Total</td>
                            <td className="p-2 text-right font-mono-nums text-slate-300">¥{totalBudget.toLocaleString()}</td>
                            <td className="p-2 text-right font-mono-nums text-slate-300">¥{totalActual.toLocaleString()}</td>
                            <td className={`p-2 text-right font-mono-nums font-medium ${variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {variance >= 0 ? '+' : ''}¥{variance.toLocaleString()}
                            </td>
                            <td className="p-2 text-xs text-slate-500">{Math.round((totalActual / totalBudget) * 100)}%</td>
                        </tr>
                    </tfoot>
                </table>
            </div>

            {/* Net Position Summary */}
            <div className="grid grid-cols-3 gap-0 border border-slate-800">
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total Assets</p>
                    <p className="text-lg font-bold font-mono-nums text-emerald-400">
                        {loading ? '...' : `¥${(summary?.net_worth ?? 4800000).toLocaleString()}`}
                    </p>
                </div>
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total Liabilities</p>
                    <p className="text-lg font-bold font-mono-nums text-rose-400">
                        {loading ? '...' : `¥${(summary?.liability_total ?? 1245000).toLocaleString()}`}
                    </p>
                </div>
                <div className="p-3">
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Net Position</p>
                    <p className="text-lg font-bold font-mono-nums text-cyan-400">¥3,555,000</p>
                </div>
            </div>
        </div>
    );
}
