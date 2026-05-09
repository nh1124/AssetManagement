import { useEffect, useMemo, useState } from 'react';
import { Landmark, Shield, TrendingUp, WalletCards } from 'lucide-react';
import { getAccounts, getAnalysisSummary, getBalanceSheet, getNetWorthHistory } from '../../api';
import { useToast } from '../../components/Toast';
import { useClient } from '../../context/ClientContext';
import type { Account, AnalysisSummary, NetWorthHistoryPoint } from '../../types';
import { formatCurrency } from '../../utils/currency';

interface BalanceSheet {
    currency?: string;
    assets?: Array<{ name: string; balance: number }>;
    liabilities?: Array<{ name: string; balance: number }>;
    total_assets?: number;
    total_liabilities?: number;
    net_worth?: number;
}

const PIE_COLORS = ['#34d399', '#06b6d4', '#a78bfa', '#f59e0b', '#fb7185', '#64748b'];

export default function MobilePortfolioPage() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [summary, setSummary] = useState<AnalysisSummary | null>(null);
    const [balanceSheet, setBalanceSheet] = useState<BalanceSheet | null>(null);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [history, setHistory] = useState<NetWorthHistoryPoint[]>([]);
    const currentCurrency = balanceSheet?.currency || currentClient?.general_settings?.currency || 'JPY';

    const loadPortfolio = async () => {
        try {
            const [summaryData, bsData, accountData, historyData] = await Promise.all([
                getAnalysisSummary(),
                getBalanceSheet(),
                getAccounts(),
                getNetWorthHistory(12),
            ]);
            setSummary(summaryData);
            setBalanceSheet(bsData);
            setAccounts(accountData);
            setHistory(historyData);
        } catch {
            showToast('Failed to load mobile portfolio', 'error');
        }
    };

    useEffect(() => {
        loadPortfolio();
    }, []);

    const topAssets = useMemo(() => {
        return [...(balanceSheet?.assets ?? [])]
            .filter((item) => Math.abs(item.balance) > 0)
            .sort((a, b) => Math.abs(b.balance) - Math.abs(a.balance))
            .slice(0, 8);
    }, [balanceSheet]);

    const topLiabilities = useMemo(() => {
        return [...(balanceSheet?.liabilities ?? [])]
            .filter((item) => Math.abs(item.balance) > 0)
            .sort((a, b) => Math.abs(b.balance) - Math.abs(a.balance))
            .slice(0, 5);
    }, [balanceSheet]);

    const roleTotals = useMemo(() => {
        const totals = new Map<string, number>();
        accounts
            .filter((account) => account.account_type === 'asset')
            .forEach((account) => {
                totals.set(account.role, (totals.get(account.role) ?? 0) + Number(account.balance || 0));
            });
        return Array.from(totals.entries())
            .map(([role, balance]) => ({ name: role, balance }))
            .sort((a, b) => Math.abs(b.balance) - Math.abs(a.balance));
    }, [accounts]);

    const pieItems = useMemo(() => {
        const positiveAssets = topAssets.filter((item) => item.balance > 0);
        if (positiveAssets.length <= 5) return positiveAssets;
        const head = positiveAssets.slice(0, 5);
        const other = positiveAssets.slice(5).reduce((sum, item) => sum + item.balance, 0);
        return other > 0 ? [...head, { name: 'Other', balance: other }] : head;
    }, [topAssets]);

    return (
        <div className="space-y-4 p-3">
            <section className="grid grid-cols-2 gap-2">
                <PortfolioMetric
                    icon={WalletCards}
                    label="Net Worth"
                    value={formatCurrency(balanceSheet?.net_worth ?? summary?.net_worth ?? 0, currentCurrency)}
                />
                <PortfolioMetric
                    icon={Shield}
                    label="Logical"
                    value={formatCurrency(summary?.logical_balance ?? summary?.effective_cash ?? 0, currentCurrency)}
                />
                <PortfolioMetric
                    icon={TrendingUp}
                    label="Assets"
                    value={formatCurrency(balanceSheet?.total_assets ?? 0, currentCurrency)}
                />
                <PortfolioMetric
                    icon={Landmark}
                    label="Liabilities"
                    value={formatCurrency(balanceSheet?.total_liabilities ?? 0, currentCurrency)}
                    tone="warn"
                />
            </section>

            <section className="grid grid-cols-1 gap-3">
                <div className="border border-slate-800 bg-slate-900/70 p-3">
                    <AssetDonut items={pieItems} currency={currentCurrency} />
                </div>
                <div className="border border-slate-800 bg-slate-900/70 p-3">
                    <NetWorthLineChart points={history.slice(-12)} currency={currentCurrency} />
                </div>
            </section>

            <PortfolioList title="Assets" items={topAssets} currency={currentCurrency} empty="No asset balances yet." />
            <PortfolioList title="Liabilities" items={topLiabilities} currency={currentCurrency} empty="No liabilities." />
            <PortfolioList title="Roles" items={roleTotals} currency={currentCurrency} empty="No role totals yet." />
        </div>
    );
}

function PortfolioMetric({
    icon: Icon,
    label,
    value,
    tone = 'normal',
}: {
    icon: typeof WalletCards;
    label: string;
    value: string;
    tone?: 'normal' | 'warn';
}) {
    return (
        <div className="border border-slate-800 bg-slate-900/70 p-3">
            <div className="flex items-center gap-2 text-slate-500">
                <Icon size={15} />
                <p className="text-[10px] uppercase tracking-wide">{label}</p>
            </div>
            <p className={`mt-2 truncate font-mono-nums text-sm ${tone === 'warn' ? 'text-amber-300' : 'text-slate-100'}`}>{value}</p>
        </div>
    );
}

function AssetDonut({ items, currency }: { items: Array<{ name: string; balance: number }>; currency: string }) {
    const total = items.reduce((sum, item) => sum + Math.max(0, item.balance), 0);
    let offset = 25;

    return (
        <div className="grid grid-cols-[132px_1fr] items-center gap-3">
            <svg viewBox="0 0 42 42" className="h-32 w-32 -rotate-90">
                <circle cx="21" cy="21" r="15.915" fill="transparent" stroke="#1e293b" strokeWidth="5" />
                {items.map((item, index) => {
                    const share = total > 0 ? (Math.max(0, item.balance) / total) * 100 : 0;
                    const dash = `${share} ${100 - share}`;
                    const currentOffset = offset;
                    offset -= share;
                    return (
                        <circle
                            key={item.name}
                            cx="21"
                            cy="21"
                            r="15.915"
                            fill="transparent"
                            stroke={PIE_COLORS[index % PIE_COLORS.length]}
                            strokeWidth="5"
                            strokeDasharray={dash}
                            strokeDashoffset={currentOffset}
                        />
                    );
                })}
            </svg>
            <div className="min-w-0 space-y-2">
                <p className="text-xs uppercase tracking-wide text-slate-500">Allocation</p>
                <p className="font-mono-nums text-lg text-slate-100">{formatCurrency(total, currency)}</p>
                <div className="space-y-1">
                    {items.slice(0, 6).map((item, index) => (
                        <div key={item.name} className="flex items-center justify-between gap-2 text-[10px]">
                            <span className="min-w-0 truncate text-slate-400">
                                <span className="mr-1 inline-block h-2 w-2" style={{ backgroundColor: PIE_COLORS[index % PIE_COLORS.length] }} />
                                {item.name}
                            </span>
                            <span className="font-mono-nums text-slate-300">{total ? Math.round((item.balance / total) * 100) : 0}%</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

function NetWorthLineChart({ points, currency }: { points: NetWorthHistoryPoint[]; currency: string }) {
    const values = points.map((point) => point.net_worth);
    const min = Math.min(...values, 0);
    const max = Math.max(...values, 1);
    const range = Math.max(max - min, 1);
    const width = 300;
    const height = 120;
    const pad = 14;
    const path = points.map((point, index) => {
        const x = pad + (index / Math.max(points.length - 1, 1)) * (width - pad * 2);
        const y = height - pad - ((point.net_worth - min) / range) * (height - pad * 2);
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');

    return (
        <div>
            <div className="mb-2 flex items-center justify-between">
                <p className="text-xs uppercase tracking-wide text-slate-500">Net Worth Trend</p>
                <p className="font-mono-nums text-xs text-slate-300">{formatCurrency(points.at(-1)?.net_worth ?? 0, currency)}</p>
            </div>
            <svg viewBox={`0 0 ${width} ${height}`} className="h-32 w-full overflow-visible">
                <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#1e293b" strokeWidth="1" />
                <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="#1e293b" strokeWidth="1" />
                <path d={path} fill="none" stroke="#34d399" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                {points.map((point, index) => {
                    const x = pad + (index / Math.max(points.length - 1, 1)) * (width - pad * 2);
                    const y = height - pad - ((point.net_worth - min) / range) * (height - pad * 2);
                    return <circle key={point.period} cx={x} cy={y} r="2.5" fill="#34d399" />;
                })}
            </svg>
            <div className="flex justify-between text-[9px] text-slate-600">
                {points.slice(0, 1).map((point) => <span key={point.period}>{point.period.slice(5)}</span>)}
                {points.slice(-1).map((point) => <span key={point.period}>{point.period.slice(5)}</span>)}
            </div>
        </div>
    );
}

function PortfolioList({
    title,
    items,
    currency,
    empty,
}: {
    title: string;
    items: Array<{ name: string; balance: number }>;
    currency: string;
    empty: string;
}) {
    return (
        <section className="space-y-2">
            <div className="flex items-center justify-between">
                <h2 className="text-sm font-medium text-slate-100">{title}</h2>
                <span className="text-[10px] text-slate-500">{items.length}</span>
            </div>
            {items.length === 0 ? (
                <EmptyBlock text={empty} />
            ) : (
                <div className="divide-y divide-slate-800 border border-slate-800 bg-slate-900/60">
                    {items.map((item) => (
                        <div key={item.name} className="flex items-center justify-between gap-3 px-3 py-3">
                            <p className="min-w-0 truncate text-sm text-slate-100">{item.name}</p>
                            <p className="shrink-0 font-mono-nums text-xs text-slate-200">{formatCurrency(item.balance, currency)}</p>
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}

function EmptyBlock({ text }: { text: string }) {
    return (
        <div className="border border-dashed border-slate-800 bg-slate-900/40 px-3 py-5 text-sm text-slate-500">
            {text}
        </div>
    );
}
