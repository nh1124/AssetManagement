import { useState } from 'react';
import { Plus, Trash2, Edit } from 'lucide-react';

const mockBudget = [
    { id: 1, category: 'Food', proposed: 50000, current: 42000, suggestion: 'On track' },
    { id: 2, category: 'Transport', proposed: 15000, current: 18500, suggestion: 'Consider reducing by ¥3,500' },
    { id: 3, category: 'Entertainment', proposed: 20000, current: 12000, suggestion: 'Surplus available' },
    { id: 4, category: 'Utilities', proposed: 12000, current: 11200, suggestion: 'On track' },
    { id: 5, category: 'Shopping', proposed: 30000, current: 28000, suggestion: 'On track' },
    { id: 6, category: 'Healthcare', proposed: 10000, current: 5000, suggestion: 'Underspent' },
];

export default function Budget() {
    const [budgets] = useState(mockBudget);
    const [month] = useState('2026-01');

    const totalProposed = budgets.reduce((sum, b) => sum + b.proposed, 0);
    const totalCurrent = budgets.reduce((sum, b) => sum + b.current, 0);
    const variance = totalProposed - totalCurrent;

    return (
        <div className="h-full flex flex-col p-4">
            {/* Header */}
            <div className="flex justify-between items-center mb-4 flex-shrink-0">
                <div>
                    <h1 className="text-lg font-semibold">Budget Management</h1>
                    <p className="text-xs text-slate-500">Month: {month}</p>
                </div>
                <button className="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 flex items-center gap-1 text-xs">
                    <Plus size={14} /> Add Category
                </button>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-3 gap-0 border border-slate-800 mb-4 flex-shrink-0">
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Proposed Budget</p>
                    <p className="text-xl font-bold font-mono-nums text-slate-200">¥{totalProposed.toLocaleString()}</p>
                </div>
                <div className="border-r border-slate-800 p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Current Spending</p>
                    <p className="text-xl font-bold font-mono-nums text-amber-400">¥{totalCurrent.toLocaleString()}</p>
                </div>
                <div className="p-3">
                    <p className="text-[10px] text-slate-500 uppercase">Variance</p>
                    <p className={`text-xl font-bold font-mono-nums ${variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {variance >= 0 ? '+' : ''}¥{variance.toLocaleString()}
                    </p>
                </div>
            </div>

            {/* Budget Table */}
            <div className="border border-slate-800 flex-1 overflow-auto">
                <table className="w-full text-xs">
                    <thead className="bg-slate-900 sticky top-0">
                        <tr className="border-b border-slate-800">
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">Category</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Proposed</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">Current</th>
                            <th className="text-right p-2 text-slate-500 uppercase tracking-wider font-medium">%</th>
                            <th className="text-left p-2 text-slate-500 uppercase tracking-wider font-medium">AI Suggestion</th>
                            <th className="p-2 w-16"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {budgets.map((b) => {
                            const pct = Math.round((b.current / b.proposed) * 100);
                            return (
                                <tr key={b.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                                    <td className="p-2">{b.category}</td>
                                    <td className="p-2 text-right font-mono-nums text-slate-400">¥{b.proposed.toLocaleString()}</td>
                                    <td className={`p-2 text-right font-mono-nums ${b.current > b.proposed ? 'text-rose-400' : 'text-emerald-400'}`}>
                                        ¥{b.current.toLocaleString()}
                                    </td>
                                    <td className={`p-2 text-right font-mono-nums ${pct > 100 ? 'text-rose-400' : pct > 80 ? 'text-amber-400' : 'text-emerald-400'}`}>
                                        {pct}%
                                    </td>
                                    <td className="p-2 text-cyan-400">{b.suggestion}</td>
                                    <td className="p-2">
                                        <div className="flex gap-1 justify-end">
                                            <button className="p-1 hover:bg-slate-700 text-slate-500 hover:text-slate-300">
                                                <Edit size={12} />
                                            </button>
                                            <button className="p-1 hover:bg-slate-700 text-slate-500 hover:text-rose-400">
                                                <Trash2 size={12} />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
