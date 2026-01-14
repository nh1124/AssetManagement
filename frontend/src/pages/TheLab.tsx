import { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import TabPanel from '../components/TabPanel';

const mockChartData = [
    { month: 'Jan', income: 400000, expense: 280000 },
    { month: 'Feb', income: 420000, expense: 290000 },
    { month: 'Mar', income: 410000, expense: 310000 },
    { month: 'Apr', income: 450000, expense: 270000 },
    { month: 'May', income: 430000, expense: 295000 },
    { month: 'Jun', income: 460000, expense: 300000 },
];

const mockCategoryData = [
    { name: 'Food', value: 85000, color: '#34d399' },
    { name: 'Transport', value: 35000, color: '#60a5fa' },
    { name: 'Entertainment', value: 25000, color: '#fbbf24' },
    { name: 'Utilities', value: 20000, color: '#f87171' },
    { name: 'Shopping', value: 45000, color: '#a78bfa' },
];

const mockBudgetVsActual = [
    { category: 'Food', budget: 50000, actual: 42000 },
    { category: 'Transport', budget: 15000, actual: 18500 },
    { category: 'Entertainment', budget: 20000, actual: 12000 },
    { category: 'Utilities', budget: 12000, actual: 11200 },
];

const mockBalanceSheet = [
    {
        category: 'Assets', items: [
            { name: 'Cash & Deposits', value: 1500000 },
            { name: 'Investment Securities', value: 2800000 },
            { name: 'Fixed Assets', value: 500000 },
        ]
    },
    {
        category: 'Liabilities', items: [
            { name: 'Credit Card', value: -45000 },
            { name: 'Loans', value: -1200000 },
        ]
    },
];

const TABS = [
    { id: 'trends', label: 'Trends' },
    { id: 'status', label: 'Budget vs Actual' },
    { id: 'bs', label: 'B/S' },
    { id: 'pl', label: 'P/L' },
];

export default function TheLab() {
    const [activeTab, setActiveTab] = useState('trends');
    const [selectedMonth, setSelectedMonth] = useState(() => {
        const now = new Date();
        return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    });

    const handleMonthChange = (delta: number) => {
        const [year, month] = selectedMonth.split('-').map(Number);
        const date = new Date(year, month - 1 + delta, 1);
        setSelectedMonth(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`);
    };

    const renderTabContent = () => {
        switch (activeTab) {
            case 'trends':
                return (
                    <div className="space-y-4">
                        {/* Income vs Expense */}
                        <div>
                            <h4 className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Income vs Expense (6 months)</h4>
                            <div className="h-40">
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={mockChartData}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                                        <XAxis dataKey="month" stroke="#64748b" fontSize={10} />
                                        <YAxis stroke="#64748b" fontSize={10} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
                                        <Tooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', fontSize: '11px' }} />
                                        <Bar dataKey="income" fill="#34d399" />
                                        <Bar dataKey="expense" fill="#f87171" />
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>

                        {/* Category Breakdown */}
                        <div>
                            <h4 className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Expense by Category</h4>
                            <div className="flex items-center gap-4">
                                <div className="h-32 w-32">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <PieChart>
                                            <Pie data={mockCategoryData} cx="50%" cy="50%" innerRadius={25} outerRadius={50} dataKey="value" stroke="none">
                                                {mockCategoryData.map((entry, index) => (
                                                    <Cell key={`cell-${index}`} fill={entry.color} />
                                                ))}
                                            </Pie>
                                        </PieChart>
                                    </ResponsiveContainer>
                                </div>
                                <div className="flex-1 space-y-1">
                                    {mockCategoryData.map((cat) => (
                                        <div key={cat.name} className="flex justify-between text-xs">
                                            <span className="flex items-center gap-1">
                                                <span className="w-2 h-2" style={{ backgroundColor: cat.color }}></span>
                                                {cat.name}
                                            </span>
                                            <span className="font-mono-nums text-slate-400">¥{cat.value.toLocaleString()}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                );
            case 'status':
                return (
                    <div className="space-y-4">
                        <h4 className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Budget vs Actual</h4>
                        <div className="border border-slate-800">
                            <table className="w-full text-xs">
                                <thead className="bg-slate-900/50">
                                    <tr className="border-b border-slate-800">
                                        <th className="text-left p-2 text-slate-500 font-medium">Category</th>
                                        <th className="text-right p-2 text-slate-500 font-medium">Budget</th>
                                        <th className="text-right p-2 text-slate-500 font-medium">Actual</th>
                                        <th className="text-right p-2 text-slate-500 font-medium">Variance</th>
                                        <th className="p-2 w-24"></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {mockBudgetVsActual.map((item) => {
                                        const variance = item.budget - item.actual;
                                        const pct = Math.round((item.actual / item.budget) * 100);
                                        return (
                                            <tr key={item.category} className="border-b border-slate-800/50">
                                                <td className="p-2">{item.category}</td>
                                                <td className="p-2 text-right font-mono-nums text-slate-400">¥{item.budget.toLocaleString()}</td>
                                                <td className="p-2 text-right font-mono-nums">¥{item.actual.toLocaleString()}</td>
                                                <td className={`p-2 text-right font-mono-nums ${variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                    {variance >= 0 ? '+' : ''}¥{variance.toLocaleString()}
                                                </td>
                                                <td className="p-2">
                                                    <div className="w-full bg-slate-800 h-1.5">
                                                        <div
                                                            className={`h-1.5 ${pct > 100 ? 'bg-rose-500' : 'bg-emerald-500'}`}
                                                            style={{ width: `${Math.min(pct, 100)}%` }}
                                                        />
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
            case 'bs':
                return (
                    <div className="space-y-4">
                        {mockBalanceSheet.map((section) => (
                            <div key={section.category}>
                                <h4 className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">{section.category}</h4>
                                <div className="space-y-1">
                                    {section.items.map((item) => (
                                        <div key={item.name} className="flex justify-between text-xs py-1 border-b border-slate-800/50">
                                            <span>{item.name}</span>
                                            <span className={`font-mono-nums ${item.value >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                ¥{Math.abs(item.value).toLocaleString()}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                        <div className="border-t border-slate-700 pt-2">
                            <div className="flex justify-between text-sm font-medium">
                                <span>Net Position</span>
                                <span className="font-mono-nums text-emerald-400">¥3,555,000</span>
                            </div>
                        </div>
                    </div>
                );
            case 'pl':
                return (
                    <div className="space-y-2">
                        <div className="grid grid-cols-3 text-[10px] text-slate-500 uppercase tracking-wider border-b border-slate-800 pb-1">
                            <span>Category</span>
                            <span className="text-right">Income</span>
                            <span className="text-right">Expense</span>
                        </div>
                        <div className="flex justify-between text-xs py-1.5 border-b border-slate-800/50">
                            <span>Salary</span>
                            <span className="text-right font-mono-nums text-emerald-400">¥450,000</span>
                            <span className="text-right font-mono-nums text-slate-600">-</span>
                        </div>
                        <div className="flex justify-between text-xs py-1.5 border-b border-slate-800/50">
                            <span>Living Expenses</span>
                            <span className="text-right font-mono-nums text-slate-600">-</span>
                            <span className="text-right font-mono-nums text-rose-400">¥210,000</span>
                        </div>
                        <div className="border-t border-slate-700 pt-2 mt-2">
                            <div className="flex justify-between text-sm font-medium">
                                <span>Net P/L</span>
                                <span className="font-mono-nums text-emerald-400">+¥240,000</span>
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
            {/* Period Control */}
            <div className="flex items-center justify-between mb-4">
                <h1 className="text-lg font-semibold">Analytics</h1>
                <div className="flex items-center gap-2">
                    <button onClick={() => handleMonthChange(-1)} className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200">
                        <ChevronLeft size={14} />
                    </button>
                    <span className="text-xs font-mono-nums text-slate-300 min-w-[70px] text-center">{selectedMonth}</span>
                    <button onClick={() => handleMonthChange(1)} className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200">
                        <ChevronRight size={14} />
                    </button>
                </div>
            </div>

            {/* Tabs */}
            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                {renderTabContent()}
            </TabPanel>
        </div>
    );
}
