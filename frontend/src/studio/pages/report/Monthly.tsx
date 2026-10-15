import { useState } from 'react';
import { useClient } from '../../../context/ClientContext';
import { lastMonthsRange } from '../ledger/periods';
import BreakdownReading from './BreakdownReading';
import PeriodSelector from './PeriodSelector';

function BreakdownForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const [months, setMonths] = useState(12);
    const [busy, setBusy] = useState(false);
    const { startDate, endDate } = lastMonthsRange(months);
    return <section className="space-y-6">
        <PeriodSelector months={months} onChange={setMonths} disabled={busy} />
        <BreakdownReading key={`${startDate}:${endDate}`} startDate={startDate} endDate={endDate} months={months} currency={currency} clientName={clientName} onBusy={setBusy} />
    </section>;
}

export default function Breakdown() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Remounting discards the previous client's figures and proposals before another write.
    return <BreakdownForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
