import { useState } from 'react';
import { useClient } from '../../../context/ClientContext';
import { primaryClass } from '../db/forms';
import { lastMonthsRange } from '../ledger/periods';
import BreakdownReading from './BreakdownReading';
import PeriodSelector from './PeriodSelector';

function ExportForClient({ currency }: { currency: string }) {
    const [months, setMonths] = useState(12);
    const { startDate, endDate } = lastMonthsRange(months);
    return <section className="space-y-6">
        <div className="studio-print-hide flex flex-wrap items-end gap-4">
            <PeriodSelector months={months} onChange={setMonths} />
            <button type="button" onClick={() => window.print()} className={primaryClass}>印刷・PDF保存</button>
        </div>
        <BreakdownReading key={`${startDate}:${endDate}`} startDate={startDate} endDate={endDate} months={months} currency={currency} readOnly />
    </section>;
}

export default function Export() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Remounting keeps a new client's printout free of the previous client's data.
    return <ExportForClient key={`${clientId}:${currency}`} currency={currency} />;
}
