import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, RefreshCw, Save } from 'lucide-react';
import TabPanel from '../components/TabPanel';
import {
    getAnalysisSummary,
    getBalanceSheet,
    getCapsules,
    getMonthlyReport,
    getMonthlyReview,
    getProfitLoss,
    getVarianceAnalysis,
    saveMonthlyReview,
} from '../api';
import { useToast } from '../components/Toast';
import type { MonthlyReview } from '../types';

const TABS = [
    { id: 'trends', label: 'Trends' },
    { id: 'variance', label: 'Budget vs Actual' },
    { id: 'bs', label: 'B/S' },
    { id: 'pl', label: 'P/L' },
    { id: 'capsules', label: 'Capsules' },
    { id: 'report', label: 'Monthly Report' },
    { id: 'review', label: 'Monthly Review' },
];

export default function TheLab() {
    const [activeTab, setActiveTab] = useState('trends');
    const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
    const [selectedMonth, setSelectedMonth] = useState(new Date().getMonth() + 1);
    const [loading, setLoading] = useState(false);

    const [summary, setSummary] = useState<any>(null);
    const [balanceSheet, setBalanceSheet] = useState<any>(null);
    const [profitLoss, setProfitLoss] = useState<any>(null);
    const [variance, setVariance] = useState<any>(null);
    const [capsules, setCapsules] = useState<any[]>([]);
    const [monthlyReport, setMonthlyReport] = useState<any>(null);
    const [monthlyReview, setMonthlyReview] = useState<MonthlyReview | null>(null);
    const [reviewDraft, setReviewDraft] = useState({ reflection: '', next_actions: '' });
    const [reviewSaving, setReviewSaving] = useState(false);
    const { showToast } = useToast();

    const fetchData = async () => {
        setLoading(true);
        try {
            const period = `${selectedYear}-${String(selectedMonth).padStart(2, '0')}`;
            const [summaryData, bsData, plData, varianceData, capsuleData, reportData, reviewData] = await Promise.all([
                getAnalysisSummary(),
                getBalanceSheet(selectedYear, selectedMonth),
                getProfitLoss(selectedYear, selectedMonth),
                getVarianceAnalysis(selectedYear, selectedMonth),
                getCapsules(),
                getMonthlyReport(selectedYear, selectedMonth),
                getMonthlyReview(period),
            ]);
            setSummary(summaryData);
            setBalanceSheet(bsData);
            setProfitLoss(plData);
            setVariance(varianceData);
            setCapsules(capsuleData);
            setMonthlyReport(reportData);
            setMonthlyReview(reviewData);
            setReviewDraft({
                reflection: reviewData.reflection || '',
                next_actions: reviewData.next_actions || '',
            });
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

    const formatCurrency = (value: number) => `¥${Math.round(value).toLocaleString()}`;

    const handleSaveReview = async () => {
        const period = `${selectedYear}-${String(selectedMonth).padStart(2, '0')}`;
        setReviewSaving(true);
        try {
            const saved = await saveMonthlyReview({
                target_period: period,
                reflection: reviewDraft.reflection,
                next_actions: reviewDraft.next_actions,
            });
            setMonthlyReview(saved);
            showToast('Monthly review saved', 'success');
        } catch (error) {
            showToast('Failed to save monthly review', 'error');
        } finally {
            setReviewSaving(false);
        }
    };

    const renderTabContent = () => {
        switch (activeTab) {
            case 'trends':
                return (
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
                );
            case 'variance':
                return (
                    <div className="bg-slate-800/30 border border-slate-700 p-4 space-y-2">
                        {(variance?.items ?? []).map((item: any, idx: number) => (
                            <div key={idx} className="grid grid-cols-4 gap-2 text-xs">
                                <span className="text-slate-300">{item.category}</span>
                                <span className="font-mono-nums text-slate-400 text-right">{formatCurrency(item.budget)}</span>
                                <span className="font-mono-nums text-amber-400 text-right">{formatCurrency(item.actual)}</span>
                                <span className={`font-mono-nums text-right ${item.variance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {formatCurrency(item.variance)}
                                </span>
                            </div>
                        ))}
                    </div>
                );
            case 'bs':
                return (
                    <div className="grid grid-cols-2 gap-4">
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs text-emerald-400 mb-2">Assets</h3>
                            {(balanceSheet?.assets ?? []).map((a: any, idx: number) => (
                                <div key={idx} className="flex justify-between text-xs">
                                    <span>{a.name}</span>
                                    <span className="font-mono-nums">{formatCurrency(a.balance)}</span>
                                </div>
                            ))}
                        </div>
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs text-rose-400 mb-2">Liabilities</h3>
                            {(balanceSheet?.liabilities ?? []).map((l: any, idx: number) => (
                                <div key={idx} className="flex justify-between text-xs">
                                    <span>{l.name}</span>
                                    <span className="font-mono-nums">{formatCurrency(l.balance)}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                );
            case 'pl':
                return (
                    <div className="grid grid-cols-2 gap-4">
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs text-emerald-400 mb-2">Income</h3>
                            {(profitLoss?.income ?? []).map((i: any, idx: number) => (
                                <div key={idx} className="flex justify-between text-xs">
                                    <span>{i.category}</span>
                                    <span className="font-mono-nums text-emerald-400">+{formatCurrency(i.amount)}</span>
                                </div>
                            ))}
                        </div>
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <h3 className="text-xs text-rose-400 mb-2">Expenses</h3>
                            {(profitLoss?.expenses ?? []).map((e: any, idx: number) => (
                                <div key={idx} className="flex justify-between text-xs">
                                    <span>{e.category}</span>
                                    <span className="font-mono-nums text-rose-400">-{formatCurrency(e.amount)}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                );
            case 'capsules':
                return (
                    <div className="space-y-2">
                        {capsules.map((c, idx) => (
                            <div key={idx} className="bg-slate-800/30 border border-slate-700 p-3 text-xs flex justify-between">
                                <span>{c.name}</span>
                                <span className="font-mono-nums text-purple-400">{formatCurrency(c.current_balance)}</span>
                            </div>
                        ))}
                    </div>
                );
            case 'report':
                return (
                    <div className="space-y-3">
                        <div className="bg-slate-800/30 border border-slate-700 p-4 text-xs">
                            <p>Period: {monthlyReport?.period}</p>
                            <p>Net Worth: <span className="font-mono-nums">{formatCurrency(monthlyReport?.summary?.net_worth ?? 0)}</span></p>
                            <p>Monthly P/L: <span className="font-mono-nums">{formatCurrency(monthlyReport?.summary?.monthly_pl ?? 0)}</span></p>
                            <p>Savings Rate: <span className="font-mono-nums">{monthlyReport?.summary?.savings_rate ?? 0}%</span></p>
                        </div>
                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <p className="text-xs text-slate-400 mb-2">Anomalies</p>
                            {(monthlyReport?.anomalies ?? []).map((a: any, idx: number) => (
                                <div key={idx} className="text-xs flex justify-between py-1">
                                    <span>{a.category}</span>
                                    <span className="font-mono-nums">{a.overage_pct}%</span>
                                </div>
                            ))}
                        </div>
                    </div>
                );
            case 'review':
                return (
                    <div className="space-y-4">
                        <div className="grid grid-cols-3 gap-3">
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Monthly P/L</p>
                                <p className={`text-lg font-mono-nums ${(monthlyReport?.summary?.monthly_pl ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                    {formatCurrency(monthlyReport?.summary?.monthly_pl ?? 0)}
                                </p>
                            </div>
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Savings Rate</p>
                                <p className="text-lg font-mono-nums text-cyan-400">{monthlyReport?.summary?.savings_rate ?? 0}%</p>
                            </div>
                            <div className="bg-slate-800/50 border border-slate-700 p-3">
                                <p className="text-[10px] text-slate-500 uppercase">Anomalies</p>
                                <p className="text-lg font-mono-nums text-amber-400">{monthlyReport?.anomalies?.length ?? 0}</p>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="bg-slate-800/30 border border-slate-700 p-4">
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-2">
                                    Reflection
                                </label>
                                <textarea
                                    value={reviewDraft.reflection}
                                    onChange={(e) => setReviewDraft({ ...reviewDraft, reflection: e.target.value })}
                                    placeholder="What happened this month? What should be kept or corrected?"
                                    className="w-full min-h-48 bg-slate-900 border border-slate-700 px-3 py-2 text-xs text-slate-200 resize-y focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                            <div className="bg-slate-800/30 border border-slate-700 p-4">
                                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-2">
                                    Next Month Actions
                                </label>
                                <textarea
                                    value={reviewDraft.next_actions}
                                    onChange={(e) => setReviewDraft({ ...reviewDraft, next_actions: e.target.value })}
                                    placeholder="Budget changes, spending rules, transfers, or follow-up actions for next month."
                                    className="w-full min-h-48 bg-slate-900 border border-slate-700 px-3 py-2 text-xs text-slate-200 resize-y focus:outline-none focus:border-emerald-500"
                                />
                            </div>
                        </div>

                        <div className="bg-slate-800/30 border border-slate-700 p-4">
                            <div className="flex items-center justify-between mb-3">
                                <p className="text-xs text-slate-400">Report Signals</p>
                                <span className="text-[10px] text-slate-600">
                                    Last saved: {monthlyReview?.updated_at || monthlyReview?.created_at || 'Not saved yet'}
                                </span>
                            </div>
                            <div className="space-y-2">
                                {(monthlyReport?.action_proposals ?? []).length === 0 ? (
                                    <p className="text-xs text-slate-500">No automatic action proposals for this month.</p>
                                ) : (
                                    monthlyReport.action_proposals.map((proposal: any, idx: number) => (
                                        <div key={idx} className="flex justify-between gap-3 text-xs border-b border-slate-800 pb-2">
                                            <span className="text-slate-300">{proposal.description}</span>
                                            <span className="font-mono-nums text-cyan-400 whitespace-nowrap">{formatCurrency(proposal.amount ?? 0)}</span>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>

                        <button
                            onClick={handleSaveReview}
                            disabled={reviewSaving}
                            className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white py-2 text-xs font-bold flex items-center justify-center gap-2"
                        >
                            <Save size={14} />
                            {reviewSaving ? 'Saving...' : 'Save Monthly Review'}
                        </button>
                    </div>
                );
            default:
                return null;
        }
    };

    return (
        <div className="h-full flex flex-col p-4 overflow-auto">
            <div className="flex items-center justify-between mb-4 flex-shrink-0">
                <div className="flex items-center gap-2">
                    <button onClick={() => navigateMonth('prev')} className="p-1 hover:bg-slate-800 text-slate-400">
                        <ChevronLeft size={16} />
                    </button>
                    <span className="text-sm font-medium min-w-[100px] text-center">
                        {selectedYear}/{String(selectedMonth).padStart(2, '0')}
                    </span>
                    <button onClick={() => navigateMonth('next')} className="p-1 hover:bg-slate-800 text-slate-400">
                        <ChevronRight size={16} />
                    </button>
                </div>
                <button onClick={fetchData} className="p-1.5 hover:bg-slate-800 text-slate-400 flex items-center gap-1 text-xs" disabled={loading}>
                    <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                    Refresh
                </button>
            </div>

            <TabPanel tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
                <div className="p-4">{renderTabContent()}</div>
            </TabPanel>
        </div>
    );
}
