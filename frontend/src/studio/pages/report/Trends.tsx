import { useCallback, useState } from 'react';
import { getNetWorthHistory } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import { MoneyLineChart } from './Charts';
import PeriodSelector from './PeriodSelector';
import { tr } from '../../i18n';

function NetWorth({ months, currency }: { months: number; currency: string }) {
    const load = useCallback(() => getNetWorthHistory(months), [months]);
    const resource = useResource(load);
    const first = resource.data?.[0];
    const latest = resource.data?.at(-1);
    return <section className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <h2 className="text-lg font-semibold">{tr('純資産の推移', 'Net worth over time')}</h2>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && (first && latest ? <>
            <dl className="flex flex-wrap gap-x-10 gap-y-4"><div><dt className="text-xs text-[var(--studio-text-muted)]">{tr(`${latest.period} の純資産`, `Net worth in ${latest.period}`)}</dt><dd className="mt-2 text-2xl font-semibold tabular-nums">{formatCurrency(latest.net_worth, currency)}</dd></div><div><dt className="text-xs text-[var(--studio-text-muted)]">{tr(`${first.period} からの増減`, `Change since ${first.period}`)}</dt><dd className="mt-2 text-xl tabular-nums">{formatCurrency(latest.net_worth - first.net_worth, currency)}</dd></div></dl>
            <MoneyLineChart rows={resource.data.map((row) => ({ label: row.period, amount: row.net_worth }))} currency={currency} label={tr('純資産', 'Net worth')} axisLabel={tr('月末', 'Month end')} />
        </> : <p className="text-sm text-[var(--studio-text-muted)]">{tr('純資産の履歴はありません。', 'No net worth history.')}</p>)}
    </section>;
}

// Account movements live in the breakdown tab; repeating the table here made the two drift apart.
function TrendsForClient({ currency }: { currency: string }) {
    const [months, setMonths] = useState(12);
    return <section className="space-y-8">
        <div className="flex flex-wrap items-end gap-4">
            <PeriodSelector months={months} onChange={setMonths} />
        </div>
        <NetWorth key={months} months={months} currency={currency} />
    </section>;
}

export default function Trends() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <TrendsForClient key={`${clientId}:${currency}`} currency={currency} />;
}
