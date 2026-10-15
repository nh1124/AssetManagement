import { useCallback, useState } from 'react';
import { applyPeriodReportAction, getPeriodReport, getProfitLoss, getVarianceAnalysis } from '../../../api';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass } from '../db/forms';
import { AccountFlows } from './Trends';
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

function Variance({ startDate, endDate, currency }: { startDate: string; endDate: string; currency: string }) {
    const load = useCallback((): Promise<VarianceAnalysis> => getVarianceAnalysis(undefined, undefined, startDate, endDate), [startDate, endDate]);
    const resource = useResource(load);
    // Zero-valued items still belong to the period's budget and must remain visible.
    const rows = resource.data?.items.slice().sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance)) ?? [];
    return <section className="space-y-4">
        <h2 className="text-lg font-semibold">予算と実績</h2>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <>
            {resource.data.plan_id === null && <p className="text-sm text-[var(--studio-text-muted)]">対象の予算プランなし</p>}
            <dl className="grid gap-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5 sm:grid-cols-3">
                {[{ label: '期間の予算合計', amount: resource.data.total_budget }, { label: '期間の支出合計', amount: resource.data.total_actual }, { label: '予算 − 支出', amount: resource.data.total_variance }].map((row) => <div key={row.label}><dt className="text-xs text-[var(--studio-text-muted)]">{row.label}</dt><dd className="mt-2 text-xl font-semibold tabular-nums">{formatCurrency(row.amount, currency)}</dd></div>)}
            </dl>
            {rows.length ? <>
                <div className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4"><ComparisonChart rows={rows} currency={currency} /></div>
                <DataTable columns={['分類', '期間の予算', '期間の支出', '予算 − 支出']}>
                    {rows.map((row, index) => <tr key={`${row.category}:${index}`}><th scope="row" className="px-5 py-3 font-medium">{row.category}</th><td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.budget, currency)}</td><td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.actual, currency)}</td><td className={`whitespace-nowrap px-5 py-3 tabular-nums ${row.variance < 0 ? 'text-[var(--studio-danger)]' : ''}`}>{formatCurrency(row.variance, currency)}</td></tr>)}
                </DataTable>
            </> : <p className="text-sm text-[var(--studio-text-muted)]">この期間の支出計画・実績はありません。</p>}
        </>}
    </section>;
}

export default function BreakdownReading({ startDate, endDate, months, currency, clientName, onBusy, readOnly = false }: {
    startDate: string; endDate: string; months: number; currency: string; clientName?: string; onBusy?: (busy: boolean) => void; readOnly?: boolean;
}) {
    const loadReport = useCallback(() => getPeriodReport(startDate, endDate), [startDate, endDate]);
    // Report summaries expose the balance only; the existing P/L endpoint supplies income and expense.
    const loadProfitLoss = useCallback((): Promise<ProfitLoss> => getProfitLoss(undefined, undefined, false, startDate, endDate), [startDate, endDate]);
    const report = useResource(loadReport);
    const profitLoss = useResource(loadProfitLoss);
    const [busy, setBusy] = useState(false);
    const [varianceRevision, setVarianceRevision] = useState(0);
    const lock = (value: boolean) => { setBusy(value); onBusy?.(value); };
    const refresh = () => { report.reload(); profitLoss.reload(); setVarianceRevision((value) => value + 1); };
    // Daily detail fits one month; monthly and quarterly buckets keep longer periods readable.
    const grain = months === 1 ? 'day' : months === 12 ? 'month' : 'quarter';
    return <div className="studio-report space-y-8">
        <section className="space-y-4">
            <h2 className="text-lg font-semibold">{startDate} 〜 {endDate} の内訳</h2>
            <Feedback loading={report.loading} error={report.error} />
            <Feedback loading={profitLoss.loading} error={profitLoss.error} />
            {!profitLoss.loading && profitLoss.error && <button type="button" onClick={profitLoss.reload} className={`studio-print-hide ${buttonClass}`}>収入・支出を再取得</button>}
            {report.data && <ReportFigures report={report.data} profitLoss={profitLoss.data} currency={currency} />}
        </section>
        {report.data && <ReportContext report={report.data} currency={currency} standalone />}
        {/* Distinct keys: two siblings sharing one key makes reconciliation mismatch
            them when the conditional sections above appear, and the period report
            section ends up rendered twice. */}
        <Variance key={`variance:${varianceRevision}`} startDate={startDate} endDate={endDate} currency={currency} />
        <AccountFlows key={`flows:${varianceRevision}`} startDate={startDate} endDate={endDate} currency={currency} grain={grain} heading="口座・科目" className="space-y-4" />
        {report.data && <ReportProposals report={report.data} currency={currency} clientName={clientName} disabled={report.loading || Boolean(report.error) || busy} apply={(id) => applyPeriodReportAction(startDate, endDate, id)} onApplied={refresh} onBusy={lock} readOnly={readOnly} standalone />}
    </div>;
}

