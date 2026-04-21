import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import TabPanel from '../components/TabPanel';
import {
    getAnalysisSummary,
    getBalanceSheet,
    getCapsules,
    getMonthlyReport,
    getProfitLoss,
    getVarianceAnalysis,
    runPurchaseAudit,
} from '../api';

const TABS = [
    { id: 'trends', label: 'Trends' },
    { id: 'variance', label: 'Budget vs Actual' },
    { id: 'bs', label: 'B/S' },
    { id: 'pl', label: 'P/L' },
    { id: 'capsules', label: 'Capsules' },
    { id: 'purchase_audit', label: 'Purchase Audit' },
    { id: 'report', label: 'Monthly Report' },
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

    const [auditForm, setAuditForm] = useState({
        name: '',
        price: '',
        lifespan_months: '24',
        category: 'Other',
    });
    const [auditResult, setAuditResult] = useState<any>(null);

    const fetchData = async () => {
        setLoading(true);
        try {
            const [summaryData, bsData, plData, varianceData, capsuleData, reportData] = await Promise.all([
                getAnalysisSummary(),
                getBalanceSheet(selectedYear, selectedMonth),
                getProfitLoss(selectedYear, selectedMonth),
                getVarianceAnalysis(selectedYear, selectedMonth),
                getCapsules(),
                getMonthlyReport(selectedYear, selectedMonth),
            ]);
            setSummary(summaryData);
            setBalanceSheet(bsData);
            setProfitLoss(plData);
            setVariance(varianceData);
            setCapsules(capsuleData);
            setMonthlyReport(reportData);
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

    const handleAudit = async () => {
        if (!auditForm.name || !auditForm.price) return;
        const result = await runPurchaseAudit({
            name: auditForm.name,
            price: parseFloat(auditForm.price),
            lifespan_months: parseInt(auditForm.lifespan_months, 10),
            category: auditForm.category,
        });
        setAuditResult(result);
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
            case 'purchase_audit':
                return (
                    <div className="space-y-4">
                        <div className="bg-slate-800/30 border border-slate-700 p-4 grid grid-cols-2 gap-3">
                            <input
                                type="text"
                                placeholder="Item name"
                                value={auditForm.name}
                                onChange={(e) => setAuditForm({ ...auditForm, name: e.target.value })}
                                className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                            />
                            <input
                                type="number"
                                placeholder="Price"
                                value={auditForm.price}
                                onChange={(e) => setAuditForm({ ...auditForm, price: e.target.value })}
                                className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                            />
                            <input
                                type="number"
                                placeholder="Lifespan months"
                                value={auditForm.lifespan_months}
                                onChange={(e) => setAuditForm({ ...auditForm, lifespan_months: e.target.value })}
                                className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs font-mono-nums"
                            />
                            <input
                                type="text"
                                placeholder="Category"
                                value={auditForm.category}
                                onChange={(e) => setAuditForm({ ...auditForm, category: e.target.value })}
                                className="bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs"
                            />
                            <button onClick={handleAudit} className="col-span-2 bg-cyan-600 hover:bg-cyan-500 text-white py-2 text-xs">
                                Run Purchase Audit
                            </button>
                        </div>
                        {auditResult && (
                            <div className="bg-slate-800/30 border border-slate-700 p-4 space-y-2 text-xs">
                                <p className="text-slate-400">Verdict</p>
                                <p className={`text-lg font-bold ${auditResult.verdict === 'Go' ? 'text-emerald-400' : auditResult.verdict === 'Wait' ? 'text-amber-400' : 'text-rose-400'}`}>
                                    {auditResult.verdict}
                                </p>
                                <p className="text-slate-300">{auditResult.verdict_reason}</p>
                                <p>TCO Monthly: <span className="font-mono-nums text-cyan-400">{formatCurrency(auditResult.tco_analysis.monthly_cost)}</span></p>
                                <p>Logical Balance After: <span className="font-mono-nums">{formatCurrency(auditResult.logical_balance_after)}</span></p>
                                <div className="space-y-1">
                                    <p className="text-slate-400">Goal Impact</p>
                                    {(auditResult.goal_impact ?? []).map((g: any, idx: number) => (
                                        <div key={idx} className="flex justify-between">
                                            <span>{g.life_event_name}</span>
                                            <span className={`font-mono-nums ${g.delta < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>{g.delta}%</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
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
