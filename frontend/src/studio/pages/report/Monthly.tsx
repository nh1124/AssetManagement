import { useCallback, useState } from 'react';
import { applyMonthlyReportAction, getMonthlyReport, getProfitLoss, getVarianceAnalysis } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass } from '../db/forms';
import MonthPicker from '../ledger/MonthPicker';
import { clientToday, useTimezone } from '../../datetime';
import MonthlyClose from './MonthlyClose';
import { ComparisonChart } from './Charts';
import { ReportContext, ReportFigures, ReportProposals, type ProfitLoss } from './ReportReading';

// The variance endpoint groups saved expense plans by category, including unplanned actuals.
interface VarianceAnalysis {
    plan_id: number | null;
    items: Array<{ category: string; budget: number; actual: number; variance: number; percentage: number }>;
    total_budget: number;
    total_actual: number;
    total_variance: number;
}

function Variance({ year, month, currency }: { year: number; month: number; currency: string }) {
    const load = useCallback((): Promise<VarianceAnalysis> => getVarianceAnalysis(year, month), [year, month]);
    const resource = useResource(load);
    const rows = resource.data?.items.filter((row) => row.budget !== 0 || row.actual !== 0).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance)) ?? [];
    return <section className="space-y-4">
        <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">月の計画と、実際に使った額</h2></div>
        <p className="text-sm leading-relaxed text-[var(--studio-text-muted)]">月の途中は、ここまでの実績との比較になります。</p>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <>
            {resource.data.plan_id === null && <p className="text-sm text-[var(--studio-text-muted)]">対象の予算プランがありません。計画額は 0 として表示しています。</p>}
            <dl className="grid gap-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5 sm:grid-cols-3">
                {[{ label: '支出の計画合計', amount: resource.data.total_budget }, { label: '支出の実績合計', amount: resource.data.total_actual }, { label: '計画 − 実績', amount: resource.data.total_variance }].map((row) => <div key={row.label}><dt className="text-xs text-[var(--studio-text-muted)]">{row.label}</dt><dd className="mt-2 text-xl font-semibold tabular-nums">{formatCurrency(row.amount, currency)}</dd></div>)}
            </dl>
            {rows.length ? <>
                <div className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4"><ComparisonChart rows={rows} currency={currency} /></div>
                <DataTable columns={['分類', '月の計画', '月の実績', '計画 − 実績']}>
                    {rows.map((row, index) => <tr key={`${row.category}:${index}`}><th scope="row" className="px-5 py-3 font-medium">{row.category}</th><td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.budget, currency)}</td><td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.actual, currency)}</td><td className={`whitespace-nowrap px-5 py-3 tabular-nums ${row.variance < 0 ? 'text-[var(--studio-danger)]' : ''}`}>{formatCurrency(row.variance, currency)}</td></tr>)}
                </DataTable>
            </> : <p className="text-sm text-[var(--studio-text-muted)]">この月の支出計画・実績はありません。</p>}
        </>}
    </section>;
}

function MonthlyReading({ period, currency, clientName, onBusy }: { period: string; currency: string; clientName?: string; onBusy: (busy: boolean) => void }) {
    const [year, month] = period.split('-').map(Number);
    const loadReport = useCallback(() => getMonthlyReport(year, month), [year, month]);
    // Report summaries expose the balance only; the existing P/L endpoint supplies income and expense.
    const loadProfitLoss = useCallback((): Promise<ProfitLoss> => getProfitLoss(year, month), [year, month]);
    const report = useResource(loadReport);
    const profitLoss = useResource(loadProfitLoss);
    const [busy, setBusy] = useState(false);
    const [varianceRevision, setVarianceRevision] = useState(0);
    const lock = (value: boolean) => { setBusy(value); onBusy(value); };
    const refresh = () => { report.reload(); profitLoss.reload(); setVarianceRevision((value) => value + 1); };
    return <div className="space-y-8">
        <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">{period} を読む</h2></div></div>
            <Feedback loading={report.loading} error={report.error} />
            <Feedback loading={profitLoss.loading} error={profitLoss.error} />
            {!profitLoss.loading && profitLoss.error && <button type="button" onClick={profitLoss.reload} className={buttonClass}>収入・支出を再取得</button>}
            {report.data && <><ReportFigures report={report.data} profitLoss={profitLoss.data} currency={currency} /><ReportContext report={report.data} currency={currency} /></>}
        </section>
        <Variance key={varianceRevision} year={year} month={month} currency={currency} />
        {report.data && <ReportProposals report={report.data} currency={currency} clientName={clientName} disabled={report.loading || Boolean(report.error) || busy} apply={(id) => applyMonthlyReportAction(period, id)} onApplied={refresh} onBusy={lock} />}
    </div>;
}

export default function Monthly() {
    const { clientId, currentClient } = useClient();
    const timezone = useTimezone();
    const [period, setPeriod] = useState(() => clientToday(timezone).slice(0, 7));
    const [busy, setBusy] = useState(false);
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <section className="space-y-6">
        <MonthPicker value={period} onChange={setPeriod} disabled={busy} />
        <MonthlyClose key={`close:${clientId}:${period}`} period={period} disabled={busy} onBusy={setBusy} />
        <MonthlyReading key={`${clientId}:${currency}:${period}`} period={period} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} onBusy={setBusy} />
    </section>;
}
