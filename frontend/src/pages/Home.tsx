import { useEffect, useState } from 'react';
import { TrendingUp, Wallet, CreditCard, AlertCircle, Check, Calendar } from 'lucide-react';
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';
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
                getDueRecurringTransactions()
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
        } catch (err) {
            showToast('Failed to process', 'error');
        }
    };

    const goalProbability = 72;
    const runwayMonths = 18;
    const budgetProgress = 65;

    // Pie chart data for goal probability gauge
    const gaugeData = [
        { name: 'Achieved', value: goalProbability },
        { name: 'Remaining', value: 100 - goalProbability },
    ];

    const cfoBriefing = `Your financial health is stable. Net worth increased by 2.3% this month, outpacing your 1.8% target. Debt-to-asset ratio remains healthy at 12%, with credit card balances on track for full payoff.`;

    return (
        <div className="space-y-4">
            {/* CFO Briefing */}
            <div className="border border-slate-800 bg-slate-900/50 p-4">
                <div className="flex items-start gap-3">
                    <div className="p-2 bg-emerald-900/30 border border-emerald-800">
                        <AlertCircle size={16} className="text-emerald-400" />
                    </div>
                    <div>
                        <h2 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">CFO Briefing</h2>
                        <p className="text-sm text-slate-300 leading-relaxed">{cfoBriefing}</p>
                    </div>
                </div>
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-0 border border-slate-800">
                {/* Goal Probability Gauge */}
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
                        <p className="text-2xl font-bold font-mono-nums text-emerald-400">{goalProbability}%</p>
                        <p className="text-[10px] text-slate-500 uppercase tracking-wider">Goal Probability</p>
                    </div>
                </div>

                {/* Net Worth */}
                <div className="border-r border-slate-800 p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Net Worth</span>
                        <Wallet className="text-emerald-500" size={14} />
                    </div>
                    <p className="text-2xl font-bold font-mono-nums text-emerald-400">
                        {loading ? '...' : `¥${(summary?.net_worth ?? 0).toLocaleString()}`}
                    </p>
                </div>

                {/* Liabilities */}
                <div className="border-r border-slate-800 p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Total Liabilities</span>
                        <CreditCard className="text-rose-500" size={14} />
                    </div>
                    <p className="text-2xl font-bold font-mono-nums text-rose-400">
                        {loading ? '...' : `¥${(summary?.liability_total ?? 0).toLocaleString()}`}
                    </p>
                </div>

                {/* Runway */}
                <div className="p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Runway</span>
                        <TrendingUp className="text-cyan-500" size={14} />
                    </div>
                    <p className="text-2xl font-bold font-mono-nums text-cyan-400">{runwayMonths} <span className="text-sm text-slate-500">months</span></p>
                </div>
            </div>

            {/* Budget Progress */}
            <div className="border border-slate-800 bg-slate-900/50 p-4">
                <div className="flex justify-between items-center mb-2">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider">This Month's Budget</span>
                    <span className="text-xs font-mono-nums text-slate-400">{budgetProgress}%</span>
                </div>
                <div className="w-full bg-slate-800 h-2">
                    <div
                        className="bg-gradient-to-r from-emerald-500 to-cyan-500 h-2 transition-all duration-500"
                        style={{ width: `${budgetProgress}%` }}
                    />
                </div>
            </div>

            {/* Quick Stats Grid */}
            <div className="grid grid-cols-3 gap-0 border border-slate-800">
                <div className="border-r border-slate-800 p-3 text-center">
                    <p className="text-lg font-bold font-mono-nums text-slate-200">+¥120k</p>
                    <p className="text-[10px] text-slate-500 uppercase">This Month P/L</p>
                </div>
                <div className="border-r border-slate-800 p-3 text-center">
                    <p className="text-lg font-bold font-mono-nums text-slate-200">23</p>
                    <p className="text-[10px] text-slate-500 uppercase">Transactions</p>
                </div>
                <div className="p-3 text-center">
                    <p className="text-lg font-bold font-mono-nums text-amber-400">3</p>
                    <p className="text-[10px] text-slate-500 uppercase">Goals Tracked</p>
                </div>
            </div>

            {/* Due Payments Section */}
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
                                    <div className="flex gap-2">
                                        <button
                                            onClick={() => handleApprove(payment.id)}
                                            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-[10px] font-bold uppercase tracking-wider flex items-center gap-1"
                                        >
                                            <Check size={12} /> Approve
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
