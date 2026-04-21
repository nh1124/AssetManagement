import { useEffect, useState } from 'react';
import { AlertCircle, Calendar, Check, CreditCard, TrendingUp, Wallet } from 'lucide-react';
import { Pie, PieChart, ResponsiveContainer, Cell } from 'recharts';
import type { AnalysisSummary } from '../types';
import { getAnalysisSummary, getDueRecurringTransactions, processRecurringTransaction } from '../api';
import { useToast } from '../components/Toast';

export default function Home() {
    const [summary, setSummary] = useState<AnalysisSummary | null>(null);
    const [duePayments, setDuePayments] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const { showToast } = useToast();

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        setLoading(true);
        try {
            const [summaryData, dueData] = await Promise.all([
                getAnalysisSummary(),
                getDueRecurringTransactions(),
            ]);
            setSummary(summaryData);
            setDuePayments(dueData);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleApprove = async (id: number) => {
        try {
            await processRecurringTransaction(id);
            showToast('Transaction processed', 'success');
            fetchData();
        } catch {
            showToast('Failed to process', 'error');
        }
    };

    const goalProbability = summary?.goal_probability ?? 0;
    const runwayMonths = summary?.runway_months ?? 0;
    const budgetProgress = summary?.budget_usage_rate ?? 0;
    const cfoBriefing = summary?.cfo_briefing ?? 'Loading financial context...';

    const gaugeData = [
        { name: 'Achieved', value: goalProbability },
        { name: 'Remaining', value: Math.max(0, 100 - goalProbability) },
    ];

    return (
        <div className="space-y-4">
            <div className="border border-slate-800 bg-slate-900/50 p-4">
                <div className="flex items-start gap-3">
                    <div className="p-2 bg-emerald-900/30 border border-emerald-800">
                        <AlertCircle size={16} className="text-emerald-400" />
                    </div>
                    <div>
                        <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">CFO Briefing</h2>
                        <p className="text-sm text-slate-300 leading-relaxed">{loading ? '...' : cfoBriefing}</p>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-0 border border-slate-800">
                <div className="border-r border-slate-800 p-4 flex items-center gap-4">
                    <div className="w-20 h-20">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={gaugeData}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={25}
                                    outerRadius={35}
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
                        <p className="text-2xl font-bold font-mono-nums text-emerald-400">{loading ? '...' : `${goalProbability}%`}</p>
                        <p className="text-[10px] text-slate-500 uppercase tracking-wider">Goal Probability</p>
                    </div>
                </div>

                <div className="border-r border-slate-800 p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Net Worth</span>
                        <Wallet className="text-emerald-500" size={14} />
                    </div>
                    <p className="text-2xl font-bold font-mono-nums text-emerald-400">
                        {loading ? '...' : `¥${(summary?.net_worth ?? 0).toLocaleString()}`}
                    </p>
                </div>

                <div className="border-r border-slate-800 p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Total Liabilities</span>
                        <CreditCard className="text-rose-500" size={14} />
                    </div>
                    <p className="text-2xl font-bold font-mono-nums text-rose-400">
                        {loading ? '...' : `¥${(summary?.liability_total ?? 0).toLocaleString()}`}
                    </p>
                </div>

                <div className="p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Runway</span>
                        <TrendingUp className="text-cyan-500" size={14} />
                    </div>
                    <p className="text-2xl font-bold font-mono-nums text-cyan-400">
                        {loading ? '...' : runwayMonths} <span className="text-sm text-slate-500">months</span>
                    </p>
                </div>
            </div>

            <div className="border border-slate-800 bg-slate-900/50 p-4">
                <div className="flex justify-between items-center mb-2">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider">This Month&apos;s Budget</span>
                    <span className="text-xs font-mono-nums text-slate-400">{loading ? '...' : `${budgetProgress}%`}</span>
                </div>
                <div className="w-full bg-slate-800 h-2">
                    <div
                        className={`h-2 transition-all duration-500 ${budgetProgress <= 80 ? 'bg-gradient-to-r from-emerald-500 to-cyan-500' : budgetProgress <= 100 ? 'bg-gradient-to-r from-amber-500 to-orange-500' : 'bg-gradient-to-r from-rose-500 to-red-500'}`}
                        style={{ width: `${Math.min(100, Math.max(0, budgetProgress))}%` }}
                    />
                </div>
            </div>

            <div className="grid grid-cols-3 gap-0 border border-slate-800">
                <div className="border-r border-slate-800 p-3 text-center">
                    <p className={`text-lg font-bold font-mono-nums ${(summary?.monthly_pl ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {loading ? '...' : `${(summary?.monthly_pl ?? 0) >= 0 ? '+' : ''}¥${Math.round(Math.abs(summary?.monthly_pl ?? 0) / 1000)}k`}
                    </p>
                    <p className="text-[10px] text-slate-500 uppercase">This Month P/L</p>
                </div>
                <div className="border-r border-slate-800 p-3 text-center">
                    <p className="text-lg font-bold font-mono-nums text-slate-200">{loading ? '...' : summary?.monthly_transaction_count ?? 0}</p>
                    <p className="text-[10px] text-slate-500 uppercase">Transactions</p>
                </div>
                <div className="p-3 text-center">
                    <p className="text-lg font-bold font-mono-nums text-amber-400">{loading ? '...' : summary?.total_goal_count ?? 0}</p>
                    <p className="text-[10px] text-slate-500 uppercase">Goals Tracked</p>
                </div>
            </div>

            {duePayments.length > 0 && (
                <div className="border border-slate-800 bg-slate-900/50 p-4">
                    <h2 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                        <Calendar size={12} className="text-cyan-400" /> Action Required: Due Payments
                    </h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {duePayments.map((payment) => (
                            <div key={payment.id} className="bg-slate-800/30 border border-slate-700 p-3 flex justify-between items-center group">
                                <div className="flex items-center gap-3">
                                    <div className="p-2 bg-slate-900 border border-slate-700">
                                        <Calendar size={14} className="text-slate-400" />
                                    </div>
                                    <div>
                                        <p className="text-xs font-medium">{payment.name}</p>
                                        <p className="text-[10px] text-slate-500">Scheduled: {payment.next_due_date}</p>
                                    </div>
                                </div>
                                <div className="flex items-center gap-4">
                                    <div className="text-right mr-2">
                                        <p className="text-sm font-bold font-mono-nums text-slate-200">¥{payment.amount.toLocaleString()}</p>
                                    </div>
                                    <button
                                        onClick={() => handleApprove(payment.id)}
                                        className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-[10px] font-bold uppercase tracking-wider flex items-center gap-1"
                                    >
                                        <Check size={12} /> Approve
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
