import { formatCurrency } from '../../../utils/currency';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass } from '../db/forms';
import { AccountFlowsReading } from './AccountFlows';
import { ComparisonChart } from './Charts';
import { ReportContext, ReportFigures, ReportProposals } from './ReportReading';
import { useBreakdownData, type BreakdownResource } from './useBreakdownData';
import { varianceRows } from './reportPresentation';

function Variance({ resource, currency }: { resource: BreakdownResource['variance']; currency: string }) {
    const rows = resource.data ? varianceRows(resource.data) : [];
    return <section className="space-y-4">
        <h2 className="text-lg font-semibold">予算と実績</h2>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <>
            {resource.data.plan_id === null && <p className="text-sm text-[var(--studio-text-muted)]">保存した計画の行なし</p>}
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

interface BreakdownProps {
    startDate: string; endDate: string; months: number; currency: string; clientName?: string;
    onBusy?: (busy: boolean) => void; readOnly?: boolean;
}

function LoadedBreakdownReading(props: BreakdownProps) {
    const resource = useBreakdownData(props.startDate, props.endDate);
    return <BreakdownContent {...props} resource={resource} />;
}

export default function BreakdownReading({ resource, ...props }: BreakdownProps & { resource?: BreakdownResource }) {
    // Export passes its own snapshot so downloads and print never fetch separate copies.
    return resource ? <BreakdownContent {...props} resource={resource} /> : <LoadedBreakdownReading {...props} />;
}

function BreakdownContent({ startDate, endDate, currency, readOnly = false, resource }: BreakdownProps & { resource: BreakdownResource }) {
    const { report, profitLoss, variance, flows } = resource;
    return <div className="studio-report space-y-8">
        <section className="space-y-4">
            <h2 className="text-lg font-semibold">{startDate} 〜 {endDate} の内訳</h2>
            <Feedback loading={report.loading} error={report.error} />
            <Feedback loading={profitLoss.loading} error={profitLoss.error} />
            {!profitLoss.loading && profitLoss.error && <button type="button" onClick={profitLoss.reload} className={`studio-print-hide ${buttonClass}`}>収入・支出を再取得</button>}
            {report.data && <ReportFigures report={report.data} profitLoss={profitLoss.data} currency={currency} />}
        </section>
        {report.data && <ReportContext report={report.data} currency={currency} standalone />}
        <Variance resource={variance} currency={currency} />
        <AccountFlowsReading resource={flows} startDate={startDate} endDate={endDate} currency={currency} heading="口座・科目" className="space-y-4" readOnly={readOnly} />
        {report.data && <ReportProposals report={report.data} currency={currency} readOnly={readOnly} standalone />}
    </div>;
}

