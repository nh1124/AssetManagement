import { useCallback, useState } from 'react';
import { getLifeEvents } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import { formatDate } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, EditableRow, Feedback, RowTitle } from '../db/Database';
import { buttonClass } from '../db/forms';
import { eventAmount, KIND_LABELS } from './eventKinds';
import LifeEventOverlay from './LifeEventOverlay';
import { useScenario } from './scenarioContext';
import { labels, tr } from '../../i18n';

const PRIORITIES = labels<'1' | '2' | '3'>({ 1: ['高', 'High'], 2: ['中', 'Medium'], 3: ['低', 'Low'] });

function LifeEventListForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const { scenario } = useScenario();
    const load = useCallback(async () => {
        const events = await getLifeEvents(scenario.id);
        return { events: [...events].sort((a, b) => a.target_date.localeCompare(b.target_date) || a.id - b.id) };
    }, [scenario.id]);
    const resource = useResource(load);
    // undefined: closed; null: a new event.
    const [editing, setEditing] = useState<LifeEvent | null | undefined>(undefined);
    const disabled = !clientName || resource.loading || Boolean(resource.error);
    return <section className="space-y-4">
        <div><button type="button" disabled={disabled} onClick={() => setEditing(null)} className={buttonClass}>{tr('新しいライフイベント', 'New life event')}</button></div>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <DataTable columns={[tr('名称', 'Name'), tr('種別', 'Kind'), tr('金額', 'Amount'), tr('日付', 'Date'), tr('優先度', 'Priority')]}>
            {resource.data.events.map((event) => <EditableRow key={event.id} disabled={disabled} onEdit={() => setEditing(event)}>
                <RowTitle name={event.name} disabled={disabled} onEdit={() => setEditing(event)}>{event.name}</RowTitle>
                <td className="whitespace-nowrap px-5 py-3">{KIND_LABELS[event.direction]}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{eventAmount(event, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3">{formatDate(event.target_date)}</td>
                <td className="whitespace-nowrap px-5 py-3">{PRIORITIES[String(event.priority) as '1' | '2' | '3']}</td>
            </EditableRow>)}
            {resource.data.events.length === 0 && <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('ライフイベントはありません。', 'No life events.')}</td></tr>}
        </DataTable>}
        {editing !== undefined && resource.data && clientName && <LifeEventOverlay event={editing} scenarioId={scenario.id} events={resource.data.events}
            currency={currency} clientName={clientName} onClose={() => setEditing(undefined)} onChanged={resource.reload} />}
    </section>;
}

export default function LifeEventList() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <LifeEventListForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
