import { useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import { formatDate, useTimezone } from '../../datetime';
import type { AssetPeriod } from './Assets';
import { getAnalysisSummary, getBalanceSheet } from '../../../api';
import { formatCurrency } from '../../../utils/currency';
import { useResource as useAssetData } from '../../useResource';

interface BalanceSheet {
    as_of_date: string;
    currency: string;
    assets: Array<{ name: string; balance: number }>;
    liabilities: Array<{ name: string; balance: number }>;
    total_assets: number;
    total_liabilities: number;
    net_worth: number;
}

function BalanceRows({ rows, currency, emptyLabel }: {
    rows: BalanceSheet['assets'];
    currency: string;
    emptyLabel: string;
}) {
    if (!rows.length) return <p className="px-5 py-4 text-sm text-[var(--studio-text-muted)]">{emptyLabel}</p>;
    return (
        <dl className="divide-y divide-[var(--studio-border)]">
            {/* Names are the only identity in this response; there is no account link. */}
            {rows.map((row, index) => (
                <div key={`${row.name}-${index}`} className="flex items-center justify-between gap-4 px-5 py-3 text-sm">
                    <dt>{row.name}</dt>
                    <dd className="whitespace-nowrap tabular-nums">{formatCurrency(row.balance, currency)}</dd>
                </div>
            ))}
        </dl>
    );
}

function OverviewForDate({ asOf }: AssetPeriod) {
    const timezone = useTimezone();
    const loadBalanceSheet = useCallback((): Promise<BalanceSheet> => getBalanceSheet(undefined, undefined, asOf), [asOf]);
    const { data: sheet, loading, error } = useAssetData(loadBalanceSheet);
    const summary = useAssetData(getAnalysisSummary);

    return (
        <section className="space-y-4">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <h2 className="text-lg font-semibold">貸借対照表</h2>
                    {sheet && <p className="mt-1 text-xs text-[var(--studio-text-muted)]">基準日：<time dateTime={sheet.as_of_date}>{formatDate(sheet.as_of_date, timezone)}</time></p>}
                </div>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">貸借対照表を読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">貸借対照表を取得できませんでした。{error}</p>}
            {summary.error && <p role="alert" className="text-sm text-[var(--studio-danger)]">引き出し制限を取得できませんでした。{summary.error}</p>}
            {summary.data?.locked_accounts?.map((row) => Object.entries(row.balances_minor).map(([currency, minor]) => (
                <p key={`${row.account_id}-${currency}`} className="text-sm text-[var(--studio-warning)]">現在の引き出し制限：{row.name} {formatCurrency(minor / (['JPY', 'KRW'].includes(currency) ? 1 : 100), currency)} ／ {row.withdrawable_from_age}歳（{formatDate(row.available_on, timezone)}）から</p>
            )))}
            {sheet && (
                <div className="grid gap-4 lg:grid-cols-2" aria-busy={loading}>
                    <section className="flex flex-col overflow-hidden rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                        <h3 className="border-b border-[var(--studio-border)] px-5 py-4 text-sm font-semibold">資産</h3>
                        <div className="flex-1"><BalanceRows rows={sheet.assets} currency={sheet.currency} emptyLabel="資産はありません。" /></div>
                        <dl className="border-t border-[var(--studio-border)] bg-[var(--studio-accent-soft)] px-5 py-4">
                            <div className="flex justify-between gap-4 text-sm font-semibold">
                                <dt>資産合計</dt><dd className="whitespace-nowrap tabular-nums">{formatCurrency(sheet.total_assets, sheet.currency)}</dd>
                            </div>
                        </dl>
                    </section>
                    <section className="overflow-hidden rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                        <h3 className="border-b border-[var(--studio-border)] px-5 py-4 text-sm font-semibold">負債・純資産</h3>
                        <BalanceRows rows={sheet.liabilities} currency={sheet.currency} emptyLabel="負債はありません。" />
                        <dl className="border-t border-[var(--studio-border)]">
                            <div className="flex justify-between gap-4 px-5 py-3 text-sm font-medium">
                                <dt>負債合計</dt><dd className="whitespace-nowrap tabular-nums">{formatCurrency(sheet.total_liabilities, sheet.currency)}</dd>
                            </div>
                            <div className="flex justify-between gap-4 border-t border-[var(--studio-border)] px-5 py-4 text-sm font-semibold">
                                <dt>純資産</dt><dd className={`whitespace-nowrap tabular-nums ${sheet.net_worth < 0 ? 'text-[var(--studio-danger)]' : 'text-[var(--studio-positive)]'}`}>{formatCurrency(sheet.net_worth, sheet.currency)}</dd>
                            </div>
                            <div className="flex justify-between gap-4 border-t border-[var(--studio-border)] bg-[var(--studio-accent-soft)] px-5 py-4 text-sm font-semibold">
                                <dt>負債＋純資産</dt><dd className="whitespace-nowrap tabular-nums">{formatCurrency(sheet.total_liabilities + sheet.net_worth, sheet.currency)}</dd>
                            </div>
                        </dl>
                    </section>
                </div>
            )}
        </section>
    );
}

export default function Overview() {
    const { asOf } = useOutletContext<AssetPeriod>();
    // A month change starts a fresh reader so stale figures and errors cannot
    // appear under the newly selected month while its request is pending.
    return <OverviewForDate key={asOf} asOf={asOf} />;
}
