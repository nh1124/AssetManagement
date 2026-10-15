import { useCallback } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { getLifeEventsWithProgress } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import { formatDate } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass } from '../db/forms';
import { goalPercent, goalPlanStatus } from './presentation';

function LifeEventListForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const navigate = useNavigate();
    const [search, setSearch] = useSearchParams();
    const includeArchived = search.get('archived') === 'true';
    const load = useCallback(() => getLifeEventsWithProgress(includeArchived), [includeArchived]);
    const resource = useResource(load);
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <button type="button" disabled={!clientName} onClick={() => navigate('/goals/events/new', { state: { returnTo: `/goals/events${includeArchived ? '?archived=true' : ''}` } })} className={buttonClass}>新しいライフイベント</button>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeArchived} onChange={(event) => {
            const next = new URLSearchParams(search);
            if (event.target.checked) next.set('archived', 'true'); else next.delete('archived');
            setSearch(next, { replace: true });
        }} />アーカイブを表示</label>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <DataTable columns={['名称', '目標額', '目標日', '現在の確保額', '進捗', '計画の状態']}>
            {resource.data.length ? resource.data.map((goal) => <tr key={goal.id} className="cursor-pointer hover:bg-[var(--studio-accent-soft)]" onClick={() => navigate(`/goals/events/${goal.id}`)}>
                <th scope="row" className="px-5 py-3 font-medium"><Link to={`/goals/events/${goal.id}`} onClick={(event) => event.stopPropagation()} className="rounded text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{goal.name}</Link></th>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(goal.target_amount, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3">{formatDate(goal.target_date)}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{goal.current_funded == null ? '—' : formatCurrency(goal.current_funded, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{goalPercent(goal.funded_percentage)}</td>
                <td className="whitespace-nowrap px-5 py-3">{goal.archived_at ? '中止・アーカイブ' : goalPlanStatus(goal)}</td>
            </tr>) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">ライフイベントはありません。</td></tr>}
        </DataTable>}
    </section>;
}

export default function LifeEventList() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <LifeEventListForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
