import { getPeriodCloses } from '../../api/periodCloses';
import { useClient } from '../../context/ClientContext';
import { useCallback } from 'react';
import { useResource } from '../useResource';

export default function ClosedPeriodWarning({ date }: { date: string }) {
    const { clientId } = useClient();
    // Reload on client switches, without delaying or disabling a correction.
    const load = useCallback(async () => ({ clientId, closes: await getPeriodCloses() }), [clientId]);
    const resource = useResource(load);
    const period = date.slice(0, 7);
    const closed = resource.data?.clientId === clientId && resource.data.closes.some((row) => row.period === period);
    return <>
        {closed && <p role="status" className="text-xs text-[var(--studio-warning)]">{period} は締め済みです。この記録・変更は締め後の変更として報告されます。記録は続けられます。</p>}
        {resource.error && <p role="status" className="text-xs text-[var(--studio-warning)]">締め状況を取得できませんでした。記録は続けられます。<button type="button" onClick={resource.reload} className="ml-2 underline">再取得</button></p>}
    </>;
}
