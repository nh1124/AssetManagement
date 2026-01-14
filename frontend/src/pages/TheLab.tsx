import { useState, useEffect } from 'react';
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import TabPanel from '../components/TabPanel';
import { getBalanceSheet, getProfitLoss, getVarianceAnalysis, getAnalysisSummary } from '../api';

const TABS = [
    { id: 'trends', label: 'Trends' },
    { id: 'variance', label: 'Budget vs Actual' },
    { id: 'bs', label: 'B/S' },
    { id: 'pl', label: 'P/L' },
];

const COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

export default function TheLab() {
    const [activeTab, setActiveTab] = useState('trends');
    const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
    const [selectedMonth, setSelectedMonth] = useState(new Date().getMonth() + 1);
    const [loading, setLoading] = useState(false);

    // Data state
    const [summary, setSummary] = useState<any>(null);
    const [balanceSheet, setBalanceSheet] = useState<any>(null);
    const [profitLoss, setProfitLoss] = useState<any>(null);
    const [variance, setVariance] = useState<any>(null);

    const fetchData = async () => {
        setLoading(true);
        try {
            const [summaryData, bsData, plData, varianceData] = await Promise.all([
                getAnalysisSummary(),
                getBalanceSheet(selectedYear, selectedMonth),
                getProfitLoss(selectedYear, selectedMonth),
                getVarianceAnalysis(selectedYear, selectedMonth)
            ]);
            setSummary(summaryData);
            setBalanceSheet(bsData);
            setProfitLoss(plData);
            setVariance(varianceData);
        } catch (error) {
            console.error('Failed to fetch analytics data:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, [selectedYear, selectedMonth]);

    const navigateMonth = (direction: 'prev' | 'next') => {
        if (direction === 'prev') {
            if (selectedMonth === 1) {
                setSelectedMonth(12);
                setSelectedYear(selectedYear - 1);
            } else {
                setSelectedMonth(selectedMonth - 1);
            }
        } else {
            if (selectedMonth === 12) {
                setSelectedMonth(1);
                setSelectedYear(selectedYear + 1);
            } else {
                setSelectedMonth(selectedMonth + 1);
            }
        }
    };

    const formatCurrency = (value: number) => `¥${value.toLocaleString()}`;

    const renderTabContent = () => {
        switch (activeTab) {
            case 'trends':
                return (
                    <div className="space-y-4">
                        {/* Summary Cards */}
                        <div className="grid grid-cols-4 gap-3">
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Net Worth</p>
                                <p className="text-lg font-mono-nums text-emerald-400">{formatCurrency(summary?.net_worth || 0)}</p>
                            </div>
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Monthly P/L</p>
                                <p className={`text-lg font-mono-nums ${(summary?.monthly_pl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {formatCurrency(summary?.monthly_pl || 0)}
                                </p>
                            </div>
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Effective Cash</p>
                                <p className="text-lg font-mono-nums text-cyan-400">{formatCurrency(summary?.effective_cash || 0)}</p>
                            </div>
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Goal Probability</p>
                                <p className="text-lg font-mono-nums text-amber-400">{summary?.goal_probability || 0}%</p>
                            </div>
                        </div>

                        {/* CFO Briefing */}
                        {summary?.cfo_briefing && (
                            <div className="bg-slate-800/30 border border-slate-700 p-3 text-xs text-slate-400">
                                💼 {summary.cfo_briefing}
                            </div>
                        )}

                        {/* Income vs Expense Chart */}
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs font-medium text-slate-400 mb-3">Income vs Expenses</h3>
                            <div className="h-48">
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={[
                                        { name: 'Income', value: profitLoss?.total_income || 0 },
                                        { name: 'Expenses', value: profitLoss?.total_expenses || 0 }
                                    ]}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                                        <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                                        <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v) => `¥${(v / 1000).toFixed(0)}k`} />
                                        <Tooltip
                                            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', fontSize: 11 }}
                                            formatter={(value) => formatCurrency(Number(value))}
                                        />
                                        <Bar dataKey="value" fill="#10b981" />
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    </div>
                );

            case 'variance':
                return (
                    <div className="space-y-4">
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <div className="flex justify-between items-center mb-3">
                                <h3 className="text-xs font-medium text-slate-400">Budget vs Actual</h3>
                                <div className="text-xs text-slate-500">
                                    Total: {formatCurrency(variance?.total_actual || 0)} / {formatCurrency(variance?.total_budget || 0)}
                                </div>
                            </div>
                            <div className="space-y-2">
                                {variance?.items?.map((item: any, idx: number) => (
                                    <div key={idx} className="flex items-center gap-2">
                                        <div className="w-24 text-xs text-slate-400 truncate">{item.category}</div>
                                        <div className="flex-1 h-4 bg-slate-800 relative overflow-hidden">
                                            <div
                                                className={`absolute h-full ${item.percentage > 100 ? 'bg-rose-500' : 'bg-emerald-500'}`}
                                                style={{ width: `${Math.min(100, item.percentage)}%` }}
                                            />
                                            {item.budget > 0 && (
                                                <div className="absolute right-0 top-0 h-full w-0.5 bg-slate-400" />
                                            )}
                                        </div>
                                        <div className="w-20 text-xs font-mono-nums text-right">
                                            {formatCurrency(item.actual)}
                                        </div>
                                        <div className={`w-16 text-xs font-mono-nums text-right ${item.variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                            {item.variance >= 0 ? '+' : ''}{formatCurrency(item.variance)}
                                        </div>
                                    </div>
                                )) || <p className="text-xs text-slate-600">No budget data for this period</p>}
                            </div>
                        </div>
                    </div>
                );

            case 'bs':
                return (
                    <div className="grid grid-cols-2 gap-4">
                        {/* Assets */}
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs font-medium text-emerald-400 mb-3">Assets</h3>
                            <div className="space-y-1">
                                {balanceSheet?.assets?.map((asset: any, idx: number) => (
                                    <div key={idx} className="flex justify-between text-xs">
                                        <span className="text-slate-400 capitalize">{asset.name}</span>
                                        <span className="font-mono-nums">{formatCurrency(asset.balance)}</span>
                                    </div>
                                )) || <p className="text-xs text-slate-600">No assets</p>}
                            </div>
                            <div className="border-t border-slate-700 mt-2 pt-2 flex justify-between text-xs font-medium">
                                <span>Total Assets</span>
                                <span className="text-emerald-400 font-mono-nums">{formatCurrency(balanceSheet?.total_assets || 0)}</span>
                            </div>
                        </div>

                        {/* Liabilities */}
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs font-medium text-rose-400 mb-3">Liabilities</h3>
                            <div className="space-y-1">
                                {balanceSheet?.liabilities?.map((liability: any, idx: number) => (
                                    <div key={idx} className="flex justify-between text-xs">
                                        <span className="text-slate-400 capitalize">{liability.name}</span>
                                        <span className="font-mono-nums">{formatCurrency(liability.balance)}</span>
                                    </div>
                                )) || <p className="text-xs text-slate-600">No liabilities</p>}
                            </div>
                            <div className="border-t border-slate-700 mt-2 pt-2 flex justify-between text-xs font-medium">
                                <span>Total Liabilities</span>
                                <span className="text-rose-400 font-mono-nums">{formatCurrency(balanceSheet?.total_liabilities || 0)}</span>
                            </div>
                        </div>

                        {/* Net Worth */}
                        <div className="col-span-2 bg-gradient-to-r from-emerald-900/20 to-cyan-900/20 border border-emerald-800/50 p-4">
                            <div className="flex justify-between items-center">
                                <span className="text-sm font-medium">Net Worth</span>
                                <span className="text-xl font-mono-nums text-emerald-400">{formatCurrency(balanceSheet?.net_worth || 0)}</span>
                            </div>
                        </div>
                    </div>
                );

            case 'pl':
                return (
                    <div className="space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                            {/* Income */}
                            <div className="bg-slate-800/30 border border-slate-700 p-4">
                                <h3 className="text-xs font-medium text-emerald-400 mb-3">Income</h3>
                                <div className="space-y-1">
                                    {profitLoss?.income?.map((item: any, idx: number) => (
                                        <div key={idx} className="flex justify-between text-xs">
                                            <span className="text-slate-400">{item.category}</span>
                                            <span className="font-mono-nums text-emerald-400">+{formatCurrency(item.amount)}</span>
                                        </div>
                                    )) || <p className="text-xs text-slate-600">No income</p>}
                                </div>
                                <div className="border-t border-slate-700 mt-2 pt-2 flex justify-between text-xs font-medium">
                                    <span>Total Income</span>
                                    <span className="text-emerald-400 font-mono-nums">{formatCurrency(profitLoss?.total_income || 0)}</span>
                                </div>
                            </div>

                            {/* Expenses */}
                            <div className="bg-slate-800/30 border border-slate-700 p-4">
                                <h3 className="text-xs font-medium text-rose-400 mb-3">Expenses</h3>
                                <div className="space-y-1">
                                    {profitLoss?.expenses?.map((item: any, idx: number) => (
                                        <div key={idx} className="flex justify-between text-xs">
                                            <span className="text-slate-400">{item.category}</span>
                                            <span className="font-mono-nums text-rose-400">-{formatCurrency(item.amount)}</span>
                                        </div>
                                    )) || <p className="text-xs text-slate-600">No expenses</p>}
                                </div>
                                <div className="border-t border-slate-700 mt-2 pt-2 flex justify-between text-xs font-medium">
                                    <span>Total Expenses</span>
                                    <span className="text-rose-400 font-mono-nums">{formatCurrency(profitLoss?.total_expenses || 0)}</span>
                                </div>
                            </div>
                        </div>

                        {/* Net P/L */}
                        <div className={`p-4 border ${(profitLoss?.net_profit_loss || 0) >= 0 ? 'bg-emerald-900/20 border-emerald-800/50' : 'bg-rose-900/20 border-rose-800/50'}`}>
                            <div className="flex justify-between items-center">
                                <span className="text-sm font-medium">Net Profit/Loss</span>
                                <span className={`text-xl font-mono-nums ${(profitLoss?.net_profit_loss || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {(profitLoss?.net_profit_loss || 0) >= 0 ? '+' : ''}{formatCurrency(profitLoss?.net_profit_loss || 0)}
                                </span>
                            </div>
                        </div>

                        {/* Expense Pie Chart */}
                        {profitLoss?.expenses?.length > 0 && (
                            <div className="bg-slate-800/30 border border-slate-700 p-4">
                                <h3 className="text-xs font-medium text-slate-400 mb-3">Expense Breakdown</h3>
                                <div className="h-48">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <PieChart>
                                            <Pie
                                                data={profitLoss.expenses}
                                                dataKey="amount"
                                                nameKey="category"
                                                cx="50%"
                                                cy="50%"
                                                outerRadius={60}
                                                label={({ name, percent }) => `${name} ${((percent || 0) * 100).toFixed(0)}%`}
                                                labelLine={false}
                                            >
                                                {profitLoss.expenses.map((_: any, index: number) => (
                                                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                                ))}
                                            </Pie>
                                            <Tooltip
                                                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', fontSize: 11 }}
                                                formatter={(value) => formatCurrency(Number(value))}
                                            />
                                        </PieChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>
                        )}
                    </div>
                );

            default:
                return null;
        }
    };

    return (
        <div className="h-full flex flex-col p-4 overflow-auto">
            {/* Period Selector */}
            <div className="flex items-center justify-between mb-4 flex-shrink-0">
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => navigateMonth('prev')}
                        className="p-1 hover:bg-slate-800 text-slate-400"
                    >
                        <ChevronLeft size={16} />
                    </button>
                    <span className="text-sm font-medium min-w-[100px] text-center">
                        {selectedYear}/{String(selectedMonth).padStart(2, '0')}
                    </span>
                    <button
                        onClick={() => navigateMonth('next')}
                        className="p-1 hover:bg-slate-800 text-slate-400"
                    >
                        <ChevronRight size={16} />
                    </button>
                </div>
                <button
                    onClick={fetchData}
                    className="p-1.5 hover:bg-slate-800 text-slate-400 flex items-center gap-1 text-xs"
                    disabled={loading}
                >
                    <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                    Refresh
                </button>
            </div>

            {/* Tabs */}
            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                <div className="p-4">
                    {renderTabContent()}
                </div>
            </TabPanel>
        </div>
    );
}
