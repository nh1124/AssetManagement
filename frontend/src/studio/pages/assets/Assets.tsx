import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { useClient } from '../../../context/ClientContext';
import { clientToday, useTimezone } from '../../datetime';
import MonthPicker from '../ledger/MonthPicker';

export interface AssetPeriod { asOf: string }

function AssetsForClient() {
    const timezone = useTimezone();
    const [monthEdit, setMonth] = useState<string | null>(null);
    const month = monthEdit ?? clientToday(timezone).slice(0, 7);
    const [year, number] = month.split('-').map(Number);
    // UTC arithmetic preserves the selected calendar month across browser zones.
    const asOf = new Date(Date.UTC(year, number, 0)).toISOString().slice(0, 10);
    return <section className="space-y-4">
        <MonthPicker value={month} onChange={setMonth} />
        <Outlet context={{ asOf } satisfies AssetPeriod} />
    </section>;
}

export default function Assets() {
    const { clientId } = useClient();
    // Keep the month across asset tabs, but reset it when the client changes.
    return <AssetsForClient key={clientId} />;
}
