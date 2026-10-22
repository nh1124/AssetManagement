import { formatCurrency } from '../../../utils/currency';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass } from '../db/forms';
import { AccountFlowsReading } from './AccountFlows';
import { ComparisonChart } from './Charts';
import { ReportContext, ReportFigures, ReportProposals } from './ReportReading';
import { useBreakdownData, type BreakdownResource } from './useBreakdownData';
import { varianceRows } from './reportPresentation';
import { tr } from '../../i18n';

function Variance({ resource, currency }: { resource: BreakdownResource['variance']; currency: string }) {
    const rows = resource.data ? varianceRows(resource.data) : [];
    return <section className="space-y-4">
        <h2 className="text-lg font-semibold">{tr('予算と実績', 'Budget and actuals')}</h2>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <>
            {resource.data.plan_id === null && <p className="text-sm text-[var(--studio-text-muted)]">{tr('保存した計画の行なし', 'No saved plan lines')}</p>}
            <dl className="grid gap-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5 sm:grid-cols-3">
                {[{ label: tr('期間の予算合計', 'Budget in the period'), amount: resource.data.total_budget }, { label: tr('期間の支出合計', 'Spending in the period'), amount: resource.data.total_actual }, { label: tr('予算 − 支出', 'Budget − spending'), amount: resource.data.total_variance }].map((row) => <div key={row.label}><dt className="text-xs text-[var(--studio-text-muted)]">{row.label}</dt><dd className="mt-2 text-xl font-semibold tabular-nums">{formatCurrency(row.amount, currency)}</dd></div>)}
            </dl>
            {rows.length ? <>
                <div className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4"><ComparisonChart rows={rows} currency={currency} /></div>
                <DataTable columns={[tr('分類', 'Category'), tr('期間の予算', 'Budget'), tr('期間の支出', 'Spending'), tr('予算 − 支出', 'Budget − spending')]}>
                    {rows.map((row, index) => <tr key={`${row.category}:${index}`}><th scope="row" className="px-5 py-3 font-medium">{row.category}</th><td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.budget, currency)}</td><td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.actual, currency)}</td><td className={`whitespace-nowrap px-5 py-3 tabular-nums ${row.variance < 0 ? 'text-[var(--studio-danger)]' : ''}`}>{formatCurrency(row.variance, currency)}</td></tr>)}
                </DataTable>
            </> : <p className="text-sm text-[var(--studio-text-muted)]">{tr('この期間の支出計画・実績はありません。', 'No spending plan or actuals in this period.')}</p>}
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
            <h2 className="text-lg font-semibold">{tr(`${startDate} 〜 ${endDate} の内訳`, `Breakdown for ${startDate} to ${endDate}`)}</h2>
            <Feedback loading={report.loading} error={report.error} />
            <Feedback loading={profitLoss.loading} error={profitLoss.error} />
            {!profitLoss.loading && profitLoss.error && <button type="button" onClick={profitLoss.reload} className={`studio-print-hide ${buttonClass}`}>{tr('収入・支出を再取得', 'Reload income and expenses')}</button>}
            {report.data && <ReportFigures report={report.data} profitLoss={profitLoss.data} currency={currency} />}
        </section>
        {report.data && <ReportContext report={report.data} currency={currency} standalone />}
        <Variance resource={variance} currency={currency} />
        <AccountFlowsReading resource={flows} startDate={startDate} endDate={endDate} currency={currency} heading={tr('口座・科目', 'Accounts')} className="space-y-4" readOnly={readOnly} />
        {report.data && <ReportProposals report={report.data} currency={currency} readOnly={readOnly} standalone />}
    </div>;
}

