import { useCallback, useState } from 'react';
import { Archive } from 'lucide-react';
import { Link, useNavigate, useSearchParams, useParams } from 'react-router-dom';
import { getLifeEventsWithProgress } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { formatDate } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass, useMutation } from '../db/forms';
import GoalEditor from './GoalEditor';
import { goalPercent, goalPlanStatus } from './presentation';

function LifeEventListForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const navigate = useNavigate();
    const { scenarioId } = useParams();
    const eventBase = scenarioId ? `/goals/scenarios/${scenarioId}/events` : '/goals/events';
    const [search, setSearch] = useSearchParams();
    const includeArchived = search.get('archived') === 'true';
    const load = useCallback(() => getLifeEventsWithProgress(includeArchived), [includeArchived]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [editing, setEditing] = useState(false);
    const closeEditor = () => { if (!mutation.busy) setEditing(false); };
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <button type="button" disabled={!clientName || editing} onClick={() => setEditing(true)} className={buttonClass}>新しいライフイベント</button>
            <button type="button" aria-pressed={includeArchived} title="アーカイブを表示" aria-label="アーカイブを表示" onClick={() => {
                const next = new URLSearchParams(search);
                if (includeArchived) next.delete('archived'); else next.set('archived', 'true');
                setSearch(next, { replace: true });
            }} className={`${buttonClass} aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}><Archive size={18} aria-hidden="true" /></button>
        </div>
        <Feedback loading={resource.loading} error={resource.error} />
        {editing && <Overlay title="新しいライフイベント" onClose={closeEditor}>
            <Feedback error={mutation.error} />
            <GoalEditor goal={null} currency={currency} embedded busy={mutation.busy || !clientName} onCancel={closeEditor}
                onSave={(action) => { if (clientName) void mutation.run(action, 'ライフイベントを保存しました。', () => { setEditing(false); resource.reload(); }); }} />
        </Overlay>}
        {resource.data && <DataTable columns={['名称', '種別', '目標額', '目標日', '現在の確保額', '進捗', '計画の状態']}>
            {resource.data.length ? resource.data.map((goal) => <tr key={goal.id} className="cursor-pointer hover:bg-[var(--studio-accent-soft)]" onClick={() => navigate(`${eventBase}/${goal.id}`)}>
                <th scope="row" className="px-5 py-3 font-medium"><Link to={`${eventBase}/${goal.id}`} onClick={(event) => event.stopPropagation()} className="rounded text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{goal.name}</Link></th>
                <td className="whitespace-nowrap px-5 py-3">{goal.direction === 'income' ? '収入' : '支出'}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(goal.target_amount, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3">{formatDate(goal.target_date)}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{goal.direction === 'income' || goal.current_funded == null ? '—' : formatCurrency(goal.current_funded, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{goal.direction === 'income' ? '—' : goalPercent(goal.funded_percentage)}</td>
                <td className="whitespace-nowrap px-5 py-3">{goal.direction === 'income' ? '—' : goal.archived_at ? '中止・アーカイブ' : goalPlanStatus(goal)}</td>
            </tr>) : <tr><td colSpan={7} className="px-5 py-4 text-[var(--studio-text-muted)]">ライフイベントはありません。</td></tr>}
        </DataTable>}
    </section>;
}

export default function LifeEventList() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <LifeEventListForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
