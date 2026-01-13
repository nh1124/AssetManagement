import { useEffect, useState } from 'react';
import { TrendingUp, Wallet, CreditCard, Target } from 'lucide-react';
import type { AnalysisSummary } from '../types';
import { getAnalysisSummary } from '../api';

export default function Home() {
    const [summary, setSummary] = useState<AnalysisSummary | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        getAnalysisSummary()
            .then(setSummary)
            .catch(console.error)
            .finally(() => setLoading(false));
    }, []);

    const goalProbability = 72; // Mock data
    const runwayMonths = 18; // Mock data
    const budgetProgress = 65; // Mock data

    return (
        <div className="space-y-6">
            <h1 className="text-2xl font-bold text-slate-100">Cockpit</h1>

            {/* Key Metrics Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {/* Net Worth */}
                <div className="bg-gradient-to-br from-slate-800 to-slate-800/50 rounded-xl border border-slate-700 p-5">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-sm text-slate-400">Net Worth</span>
                        <Wallet className="text-emerald-400" size={20} />
                    </div>
                    <p className="text-3xl font-bold text-emerald-400">
                        {loading ? '...' : `¥${(summary?.net_worth ?? 0).toLocaleString()}`}
                    </p>
                </div>

                {/* Liabilities */}
                <div className="bg-gradient-to-br from-slate-800 to-slate-800/50 rounded-xl border border-slate-700 p-5">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-sm text-slate-400">Total Liabilities</span>
                        <CreditCard className="text-rose-400" size={20} />
                    </div>
                    <p className="text-3xl font-bold text-rose-400">
                        {loading ? '...' : `¥${(summary?.liability_total ?? 0).toLocaleString()}`}
                    </p>
                </div>

                {/* Runway */}
                <div className="bg-gradient-to-br from-slate-800 to-slate-800/50 rounded-xl border border-slate-700 p-5">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-sm text-slate-400">Runway</span>
                        <TrendingUp className="text-cyan-400" size={20} />
                    </div>
                    <p className="text-3xl font-bold text-cyan-400">{runwayMonths} months</p>
                </div>

                {/* Goal Probability */}
                <div className="bg-gradient-to-br from-slate-800 to-slate-800/50 rounded-xl border border-slate-700 p-5">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-sm text-slate-400">Goal Probability</span>
                        <Target className="text-amber-400" size={20} />
                    </div>
                    <p className="text-3xl font-bold text-amber-400">{goalProbability}%</p>
                </div>
            </div>

            {/* Budget Progress */}
            <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
                <h2 className="text-lg font-semibold mb-4">This Month's Budget</h2>
                <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Spent</span>
                        <span className="text-slate-200">{budgetProgress}%</span>
                    </div>
                    <div className="w-full bg-slate-700 rounded-full h-3">
                        <div
                            className="bg-gradient-to-r from-emerald-500 to-cyan-500 h-3 rounded-full transition-all duration-500"
                            style={{ width: `${budgetProgress}%` }}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
}
