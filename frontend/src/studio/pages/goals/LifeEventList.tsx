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

const PRIORITIES = { 1: '高', 2: '中', 3: '低' } as const;

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
        <div><button type="button" disabled={disabled} onClick={() => setEditing(null)} className={buttonClass}>新しいライフイベント</button></div>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <DataTable columns={['名称', '種別', '金額', '日付', '優先度']}>
            {resource.data.events.map((event) => <EditableRow key={event.id} disabled={disabled} onEdit={() => setEditing(event)}>
                <RowTitle name={event.name} disabled={disabled} onEdit={() => setEditing(event)}>{event.name}</RowTitle>
                <td className="whitespace-nowrap px-5 py-3">{KIND_LABELS[event.direction]}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{eventAmount(event, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3">{formatDate(event.target_date)}</td>
                <td className="whitespace-nowrap px-5 py-3">{PRIORITIES[event.priority]}</td>
            </EditableRow>)}
            {resource.data.events.length === 0 && <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">ライフイベントはありません。</td></tr>}
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
