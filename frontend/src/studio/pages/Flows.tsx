import { clientToday, useTimezone } from '../datetime';
import { useCallback, useState } from 'react';
import { getProfitLoss } from '../../api';
import { useClient } from '../../context/ClientContext';
import { formatCurrency } from '../../utils/currency';
import { useResource } from '../useResource';
import MonthPicker from './ledger/MonthPicker';
import Accounts from './assets/Accounts';
import { tr } from '../i18n';

// Match reporting_service.get_profit_loss_for_range, including its plural expenses.
interface ProfitLoss {
    period: string;
    start_date: string;
    end_date: string;
    income: Array<{ category: string; amount: number }>;
    expenses: Array<{ category: string; amount: number }>;
    total_income: number;
    total_expenses: number;
    net_profit_loss: number;
}

function FlowTable({ title, rows, total, currency }: {
    title: string;
    rows: ProfitLoss['income'];
    total: number;
    currency: string;
}) {
    return (
        <section className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
            <h3 className="border-b border-[var(--studio-border)] px-5 py-4 text-sm font-semibold">{title}</h3>
            <table className="w-full text-left text-sm">
                <caption className="sr-only">{tr(`分類ごとの${title}`, `${title} by category`)}</caption>
                <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                    <tr><th scope="col" className="px-5 py-3 font-medium">{tr('分類', 'Category')}</th><th scope="col" className="px-5 py-3 text-right font-medium">{tr('金額', 'Amount')}</th></tr>
                </thead>
                <tbody className="divide-y divide-[var(--studio-border)]">
                    {rows.length ? rows.map((row, index) => (
                        <tr key={`${row.category}-${index}`}><th scope="row" className="px-5 py-3 font-normal">{row.category}</th><td className="whitespace-nowrap px-5 py-3 text-right tabular-nums">{formatCurrency(row.amount, currency)}</td></tr>
                    )) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr(`この月の${title}はありません。`, `No ${title.toLowerCase()} this month.`)}</td></tr>}
                </tbody>
                <tfoot className="border-t border-[var(--studio-border)] bg-[var(--studio-accent-soft)] font-semibold">
                    <tr><th scope="row" className="px-5 py-4">{tr(`${title}合計`, `Total ${title.toLowerCase()}`)}</th><td className="whitespace-nowrap px-5 py-4 text-right tabular-nums">{formatCurrency(total, currency)}</td></tr>
                </tfoot>
            </table>
        </section>
    );
}

function MonthlyFlows({ month, currency }: { month: string; currency: string }) {
    const load = useCallback((): Promise<ProfitLoss> => {
        const [year, number] = month.split('-').map(Number);
        return getProfitLoss(year, number);
    }, [month]);
    const { data: report, loading, error } = useResource(load);

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between gap-4">
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('収支を読み込んでいます…', 'Loading income and expenses…')}</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('収支を取得できませんでした。', 'Could not load income and expenses. ')}{error}</p>}
            {report && (
                <div className="space-y-4" aria-busy={loading}>
                    {/* The backend values all legs in the client's currency before aggregation. */}
                    <div className="grid gap-4 lg:grid-cols-2">
                        <FlowTable title={tr('収入', 'Income')} rows={report.income} total={report.total_income} currency={currency} />
                        <FlowTable title={tr('支出', 'Expenses')} rows={report.expenses} total={report.total_expenses} currency={currency} />
                    </div>
                    <dl className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] px-5 py-4">
                        <div className="flex items-center justify-between gap-4 text-sm font-semibold">
                            <dt>{tr('収支（収入 − 支出）', 'Net (income − expenses)')}</dt><dd className={`whitespace-nowrap tabular-nums ${report.net_profit_loss < 0 ? 'text-[var(--studio-danger)]' : 'text-[var(--studio-positive)]'}`}>{formatCurrency(report.net_profit_loss, currency)}</dd>
                        </div>
                    </dl>
                </div>
            )}
        </div>
    );
}

export default function Flows({ subjects = false }: { subjects?: boolean }) {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const timezone = useTimezone();
    const [monthEdit, setMonth] = useState<string | null>(null);
    const month = monthEdit ?? clientToday(timezone).slice(0, 7);
    if (subjects) return <Accounts subjects />;
    return (
        <section className="space-y-4">
            <MonthPicker value={month} onChange={setMonth} />
            <MonthlyFlows key={`${clientId}-${month}-${currency}`} month={month} currency={currency} />
        </section>
    );
}
