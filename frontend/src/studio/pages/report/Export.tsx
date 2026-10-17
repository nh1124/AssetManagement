import { useState } from 'react';
import { useClient } from '../../../context/ClientContext';
import { buttonClass, primaryClass } from '../db/forms';
import { Feedback } from '../db/Database';
import { lastMonthsRange } from '../ledger/periods';
import BreakdownReading from './BreakdownReading';
import PeriodSelector from './PeriodSelector';
import { useBreakdownData } from './useBreakdownData';
import { breakdownCsv, breakdownMarkdown, downloadBreakdown } from './breakdownExport';

function ExportPeriod({ startDate, endDate, months, currency, onMonths }: {
    startDate: string; endDate: string; months: number; currency: string; onMonths: (months: number) => void;
}) {
    const resource = useBreakdownData(startDate, endDate);
    const save = (format: 'md' | 'csv') => {
        const { report, profitLoss, variance, flows } = resource;
        if (!resource.ready || !report.data || !profitLoss.data || !variance.data || !flows.data) return;
        const data = { report: report.data, profitLoss: profitLoss.data, variance: variance.data, flows: flows.data };
        const content = format === 'md' ? breakdownMarkdown(data, startDate, endDate, currency) : breakdownCsv(data, currency);
        downloadBreakdown(content, `内訳_${startDate}_${endDate}.${format}`, format === 'md' ? 'text/markdown;charset=utf-8' : 'text/csv;charset=utf-8');
    };
    return <section className="space-y-6">
        <div className="studio-print-hide flex flex-wrap items-end gap-4">
            <PeriodSelector months={months} onChange={onMonths} />
            <button type="button" disabled={!resource.ready} onClick={() => window.print()} className={primaryClass}>印刷・PDF保存</button>
            <button type="button" disabled={!resource.ready} onClick={() => save('md')} className={buttonClass}>Markdownで保存</button>
            <button type="button" disabled={!resource.ready} onClick={() => save('csv')} className={buttonClass}>CSVで保存</button>
        </div>
        <div className="studio-print-hide flex flex-wrap items-center gap-3">
            <Feedback loading={resource.loading} error={resource.failed ? '内訳を取得できませんでした。' : undefined} />
            {resource.failed && <button type="button" onClick={resource.refresh} className={buttonClass}>再取得</button>}
        </div>
        <div className="studio-print-only" inert aria-hidden="true">
            <BreakdownReading startDate={startDate} endDate={endDate} months={months} currency={currency} resource={resource} readOnly />
        </div>
    </section>;
}

function ExportForClient({ currency }: { currency: string }) {
    const [months, setMonths] = useState(12);
    const { startDate, endDate } = lastMonthsRange(months);
    // A new period must disable saving before any previous snapshot can be reused.
    return <ExportPeriod key={`${startDate}:${endDate}`} startDate={startDate} endDate={endDate} months={months} currency={currency} onMonths={setMonths} />;
}

export default function Export() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Remounting keeps a new client's printout free of the previous client's data.
    return <ExportForClient key={`${clientId}:${currency}`} currency={currency} />;
}
