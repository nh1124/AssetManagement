import { useCallback, useState } from 'react';
import { getBalanceSheet } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { clientToday, useTimezone } from '../../datetime';
import MonthPicker from '../ledger/MonthPicker';
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

function OverviewForDate({ asOf }: { asOf: string }) {
    const loadBalanceSheet = useCallback((): Promise<BalanceSheet> => getBalanceSheet(undefined, undefined, asOf), [asOf]);
    const { data: sheet, loading, error } = useAssetData(loadBalanceSheet);

    return (
        <section className="space-y-4">
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">貸借対照表を読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">貸借対照表を取得できませんでした。{error}</p>}
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

function OverviewForClient() {
    const timezone = useTimezone();
    const [monthEdit, setMonth] = useState<string | null>(null);
    const month = monthEdit ?? clientToday(timezone).slice(0, 7);
    const [year, number] = month.split('-').map(Number);
    // UTC arithmetic preserves the selected calendar month across browser zones.
    const asOf = new Date(Date.UTC(year, number, 0)).toISOString().slice(0, 10);
    // A month change starts a fresh reader so stale figures and errors cannot
    // appear under the newly selected month while its request is pending.
    return <section className="space-y-4">
        <MonthPicker value={month} onChange={setMonth} />
        <OverviewForDate key={asOf} asOf={asOf} />
    </section>;
}

export default function Overview() {
    const { clientId } = useClient();
    return <OverviewForClient key={clientId} />;
}
