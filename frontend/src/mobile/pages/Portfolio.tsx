import { useEffect, useMemo, useState } from 'react';
import { Landmark, RefreshCw, Shield, TrendingUp, WalletCards } from 'lucide-react';
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

export default function MobilePortfolioPage() {
    const { showToast } = useToast();
    const { currentClient } = useClient();
    const [summary, setSummary] = useState<AnalysisSummary | null>(null);
    const [balanceSheet, setBalanceSheet] = useState<BalanceSheet | null>(null);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [history, setHistory] = useState<NetWorthHistoryPoint[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const currentCurrency = balanceSheet?.currency || currentClient?.general_settings?.currency || 'JPY';

    const loadPortfolio = async () => {
        setIsLoading(true);
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
        } finally {
            setIsLoading(false);
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
            .map(([role, balance]) => ({ role, balance }))
            .sort((a, b) => Math.abs(b.balance) - Math.abs(a.balance));
    }, [accounts]);

    const latestHistory = history.slice(-6);

    return (
        <div className="space-y-4 p-3">
            <section className="flex items-center justify-between">
                <div>
                    <p className="text-[10px] uppercase tracking-wide text-slate-500">Mobile Portfolio</p>
                    <h1 className="text-xl font-semibold text-slate-50">Portfolio</h1>
                </div>
                <button
                    type="button"
                    onClick={loadPortfolio}
                    className="flex h-10 w-10 items-center justify-center border border-slate-800 bg-slate-900 text-slate-300"
                    aria-label="Refresh portfolio"
                >
                    <RefreshCw size={17} className={isLoading ? 'animate-spin' : ''} />
                </button>
            </section>

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

            {latestHistory.length > 1 && (
                <section className="border border-slate-800 bg-slate-900/70 p-3">
                    <div className="flex items-center justify-between">
                        <h2 className="text-sm font-medium text-slate-100">Net Worth Trend</h2>
                        <span className="text-[10px] text-slate-500">12 mo</span>
                    </div>
                    <div className="mt-4 flex h-24 items-end gap-1">
                        {latestHistory.map((point) => {
                            const values = latestHistory.map((item) => Math.max(0, item.net_worth ?? 0));
                            const max = Math.max(...values, 1);
                            const height = Math.max(8, ((point.net_worth ?? 0) / max) * 100);
                            return (
                                <div key={point.period} className="flex flex-1 flex-col items-center gap-1">
                                    <div className="w-full bg-emerald-500/80" style={{ height: `${height}%` }} />
                                    <span className="text-[9px] text-slate-600">{point.period.slice(5)}</span>
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}

            <PortfolioList title="Assets" items={topAssets} currency={currentCurrency} empty="No asset balances yet." />
            <PortfolioList title="Liabilities" items={topLiabilities} currency={currentCurrency} empty="No liabilities." />

            <section className="space-y-2">
                <h2 className="text-sm font-medium text-slate-100">Asset Roles</h2>
                {roleTotals.length === 0 ? (
                    <EmptyBlock text="No role totals yet." />
                ) : (
                    <div className="divide-y divide-slate-800 border border-slate-800 bg-slate-900/60">
                        {roleTotals.map((row) => (
                            <div key={row.role} className="flex items-center justify-between gap-3 px-3 py-3">
                                <p className="truncate text-sm capitalize text-slate-100">{row.role}</p>
                                <p className="shrink-0 font-mono-nums text-xs text-cyan-300">{formatCurrency(row.balance, currentCurrency)}</p>
                            </div>
                        ))}
                    </div>
                )}
            </section>
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
