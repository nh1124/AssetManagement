import { useCallback, useId, useState } from 'react';
import { createGoal, deleteGoal, getLifeEvents } from '../../../api';
import { createLifeEventLink, deleteLifeEventLink, getLifeEventLinks } from '../../../api/lifeEventGraph';
import type { LifeEventLink, LifeEventLinkInput } from '../../../api/lifeEventGraph';
import { compare, type ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { clientToday, useTimezone } from '../../datetime';
import { assetErrorMessage, useResource } from '../../useResource';
import { Choice, EditorActions, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';
import { eventAmount } from './eventKinds';
import GoalConditions from './GoalConditions';
import LifeEventDiagram from './LifeEventDiagram';
import LifeEventLinkDetails from './LifeEventLinkDetails';
import LifeEventOverlay from './LifeEventOverlay';
import { useScenario } from './scenarioContext';

function LinkEditor({ events, busy, onSave, onCancel }: {
    events: LifeEvent[]; busy: boolean; onSave: (input: LifeEventLinkInput) => void; onCancel: () => void;
}) {
    const form = useId();
    const [source, setSource] = useState<number | null>(null);
    const [target, setTarget] = useState<number | null>(null);
    const [offset, setOffset] = useState(0);
    return <form id={form} onSubmit={(event) => {
        event.preventDefault();
        if (source !== null && target !== null && !busy) onSave({ from_event_id: source, to_event_id: target, kind: 'after', offset_months: offset });
    }}>
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <Choice label="元のイベント" value={source} options={events} required onChange={(value) => { setSource(value); if (value === target) setTarget(null); }} />
            <Choice label="次のイベント" value={target} options={events.filter((item) => item.id !== source)} required onChange={setTarget} />
            <Field label="元のイベントからの月数" help="0のときは次のイベント自身の目標日です。"><input type="number" required step="1" value={offset} onChange={(event) => setOffset(Number(event.target.value))} className={inputClass} /></Field>
        </fieldset>
        <EditorActions busy={busy} form={form} onCancel={onCancel} />
    </form>;
}

/** The outline: each event under the event it follows, with the date the connection gives it. */
function EventOutline({ events, links, scenario, conditionEventIds, currency, disabled, onEdit, onDelete }: {
    events: LifeEvent[]; links: LifeEventLink[]; scenario?: ProjectedLifeScenario; conditionEventIds: ReadonlySet<number>; currency: string;
    disabled: boolean; onEdit: (event: LifeEvent) => void; onDelete: (link: LifeEventLink) => void;
}) {
    const byId = new Map(events.map((item) => [item.id, item]));
    const activeLinks = links.filter((edge) => byId.has(edge.from_event_id) && byId.has(edge.to_event_id));
    const outgoing = new Map<number, LifeEventLink[]>();
    const targets = new Set(activeLinks.map((edge) => edge.to_event_id));
    for (const edge of activeLinks) outgoing.set(edge.from_event_id, [...(outgoing.get(edge.from_event_id) ?? []), edge]);
    const resolved = new Map(scenario?.events.map((item) => [item.id, item]));
    const rows: Array<{ event: LifeEvent; edge?: LifeEventLink; depth: number; shared: boolean }> = [];
    const expanded = new Set<number>();
    const pending = events.filter((item) => !targets.has(item.id)).reverse().map((event) => ({ event, depth: 0, edge: undefined as LifeEventLink | undefined }));
    while (pending.length) {
        const entry = pending.pop();
        if (!entry) break;
        const shared = expanded.has(entry.event.id);
        rows.push({ ...entry, shared });
        // Expand a shared descendant once; converging paths must not explode the outline.
        if (shared) continue;
        expanded.add(entry.event.id);
        for (const edge of [...(outgoing.get(entry.event.id) ?? [])].reverse()) {
            const child = byId.get(edge.to_event_id);
            if (child) pending.push({ event: child, edge, depth: entry.depth + 1 });
        }
    }
    return <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
        {rows.length ? <ul className="min-w-max space-y-2" aria-label="イベントの接続">
            {rows.map(({ event, edge, depth, shared }) => <li key={edge ? `link-${edge.id}` : `root-${event.id}`} style={{ paddingLeft: `${depth * 24}px` }}>
                <div className="flex items-center gap-3 rounded border-l-2 border-[var(--studio-border)] py-2 pl-3 text-sm">
                    {edge && <span className="text-xs text-[var(--studio-text-muted)]">続く・{edge.offset_months === 0 ? '目標日' : `${edge.offset_months > 0 ? '+' : ''}${edge.offset_months}か月`}</span>}
                    <button type="button" disabled={disabled} onClick={() => onEdit(event)} className="rounded text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{event.name}</button>
                    {conditionEventIds.has(event.id) && <span className="text-xs text-[var(--studio-text-muted)]">前提条件あり</span>}
                    <span className="tabular-nums">{resolved.get(event.id)?.resolved_date ?? event.target_date}</span>
                    <span className="tabular-nums">{eventAmount(event, currency)}</span>
                    {resolved.get(event.id)?.on_likely_path && <span className="text-xs text-[var(--studio-accent)]">多くの試行が通る</span>}
                    {shared && <span className="text-xs text-[var(--studio-text-muted)]">共通イベント</span>}
                    {edge && <button type="button" disabled={disabled} onClick={() => onDelete(edge)} aria-label={`${byId.get(edge.from_event_id)?.name}から${event.name}への接続を削除`} className={buttonClass}>接続を削除</button>}
                </div>
            </li>)}
        </ul> : <p className="text-sm text-[var(--studio-text-muted)]">イベントはありません。</p>}
    </div>;
}

function GraphEditor({ currency, clientName, view }: { currency: string; clientName?: string; view: 'diagram' | 'outline' }) {
    const confirm = useConfirm();
    const timezone = useTimezone();
    const { scenario: current } = useScenario();
    const load = useCallback(async () => {
        const [events, links, comparison] = await Promise.all([
            getLifeEvents(current.id), getLifeEventLinks(current.id), compare([current.id]),
        ]);
        // The projection carries resolved dates, which events have preconditions and the likely path.
        const projected = comparison.scenarios[0];
        return {
            events, links, projected,
            conditionEventIds: new Set(projected?.conditions.map((row) => row.event_id) ?? []),
            pathEventIds: new Set(projected?.likely_path.event_ids ?? []),
            pathLinkIds: new Set(projected?.likely_path.link_ids ?? []),
        };
    }, [current.id]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [addingLink, setAddingLink] = useState(false);
    // undefined: closed; null: a new event.
    const [editing, setEditing] = useState<LifeEvent | null | undefined>(undefined);
    const [editingLink, setEditingLink] = useState<LifeEventLink | null>(null);
    const [conditionsEvent, setConditionsEvent] = useState<LifeEvent | null>(null);
    const [conditionsBusy, setConditionsBusy] = useState(false);
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy || conditionsBusy || !clientName;
    const remove = async (edge: LifeEventLink) => {
        if (disabled) return;
        const source = resource.data?.events.find((event) => event.id === edge.from_event_id)?.name;
        const target = resource.data?.events.find((event) => event.id === edge.to_event_id)?.name;
        if (await confirm(`「${clientName}」の「${source}」から「${target}」への接続を削除します。`, '接続を削除')) {
            void mutation.run(() => deleteLifeEventLink(edge.id), '接続を削除しました。', resource.reload);
        }
    };
    const deleteEvent = async (event: LifeEvent) => {
        if (disabled) return;
        if (await confirm(`「${clientName}」のライフイベント「${event.name}」を削除します。接続・前提条件も削除します（取り置きは残ります）。`, '削除する')) {
            void mutation.run(() => deleteGoal(event.id), 'ライフイベントを削除しました。', resource.reload);
        }
    };
    const addEvent = (sourceId?: number, handleType?: 'source' | 'target') => {
        if (disabled) return;
        const source = resource.data?.events.find((event) => event.id === sourceId);
        if (sourceId === undefined) { setEditing(null); return; }
        if (!source) return;
        // Dragging a connection onto empty space creates the event there and connects it.
        void mutation.run(async () => {
            const created = await createGoal({ name: '新しいライフイベント', target_amount: 0, direction: 'expense', target_date: source.target_date || clientToday(timezone), priority: 2, scenario_id: current.id });
            try {
                await createLifeEventLink({
                    from_event_id: handleType === 'source' ? source.id : created.id,
                    to_event_id: handleType === 'source' ? created.id : source.id,
                    kind: 'after', offset_months: 0,
                });
            } catch (failure: unknown) {
                // Keep the real event after a partial success and make it visible for recovery.
                resource.reload();
                throw new Error(`ライフイベント「${created.name}」は作成しましたが、接続の作成に失敗しました。イベントは残っています。${assetErrorMessage(failure)}`);
            }
            setEditing(created);
        }, 'ライフイベントと接続を追加しました。', resource.reload);
    };
    return <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
            <button type="button" disabled={disabled} onClick={() => setEditing(null)} className={buttonClass}>ライフイベントを追加</button>
            <button type="button" disabled={disabled || addingLink || (resource.data?.events.length ?? 0) < 2} onClick={() => setAddingLink(true)} className={buttonClass}>接続を追加</button>
        </div>
        <Feedback loading={resource.loading || mutation.busy} error={resource.error || (!addingLink && editing === undefined && !editingLink ? mutation.error : '')} message={mutation.message} />
        {resource.data && !resource.loading && !resource.error && <>
            {view === 'diagram' ? <LifeEventDiagram conditionEventIds={resource.data.conditionEventIds} pathEventIds={resource.data.pathEventIds} pathLinkIds={resource.data.pathLinkIds}
                events={resource.data.events} links={resource.data.links} scenario={resource.data.projected} currency={currency} disabled={disabled}
                onAddEvent={addEvent} onEditEvent={setEditing} onDeleteEvent={(event) => { void deleteEvent(event); }}
                onConditions={setConditionsEvent}
                onDeleteEdge={(edge) => { void remove(edge); }}
                onEdgeClick={setEditingLink} onConnect={(source, target) => {
                    if (disabled) return;
                    void mutation.run(() => createLifeEventLink({ from_event_id: source, to_event_id: target, kind: 'after', offset_months: 0 }), '接続を追加しました。', resource.reload);
                }} />
                : <EventOutline conditionEventIds={resource.data.conditionEventIds} events={resource.data.events} links={resource.data.links} scenario={resource.data.projected} currency={currency} disabled={disabled} onEdit={setEditing} onDelete={(edge) => { void remove(edge); }} />}
            <p className="text-xs text-[var(--studio-text-muted)]">イベントを選ぶと編集、右クリックで前提条件・削除。枠と線が強調されたイベント・接続は、シミュレーションの過半数の試行が通る分岐です。</p>
        </>}
        {addingLink && resource.data && <Overlay title="接続を追加" busy={mutation.busy} onClose={() => setAddingLink(false)}>
            <Feedback error={mutation.error} />
            <LinkEditor events={resource.data.events} busy={disabled} onCancel={() => setAddingLink(false)} onSave={(input) => {
                if (disabled) return;
                void mutation.run(() => createLifeEventLink(input), '接続を追加しました。', () => { setAddingLink(false); resource.reload(); });
            }} />
        </Overlay>}
        {editing !== undefined && resource.data && clientName && <LifeEventOverlay event={editing} scenarioId={current.id} events={resource.data.events}
            currency={currency} clientName={clientName} onClose={() => setEditing(undefined)} onChanged={resource.reload} />}
        {editingLink && resource.data && clientName && <LifeEventLinkDetails edge={editingLink} events={resource.data.events} clientName={clientName} onReload={resource.reload} onClose={() => setEditingLink(null)} />}
        {conditionsEvent && clientName && <Overlay title={`「${conditionsEvent.name}」の前提条件`} busy={conditionsBusy} onClose={() => setConditionsEvent(null)}>
            <GoalConditions goalId={conditionsEvent.id} scenarioId={current.id} currency={currency} clientName={clientName} onBusy={setConditionsBusy} onChanged={resource.reload} />
        </Overlay>}
    </div>;
}

function LifeEventGraphForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const [view, setView] = useState<'diagram' | 'outline'>('diagram');
    return <section className="space-y-4">
        <div role="group" aria-label="イベントの表示" className="flex gap-1">
            {(['diagram', 'outline'] as const).map((mode) => <button key={mode} type="button" aria-pressed={view === mode} onClick={() => setView(mode)} className={`${buttonClass} ${view === mode ? 'bg-[var(--studio-accent-soft)] ring-1 ring-[var(--studio-accent)]' : ''}`}>
                {mode === 'diagram' ? '図' : '接続の一覧'}
            </button>)}
        </div>
        <GraphEditor currency={currency} clientName={clientName} view={view} />
    </section>;
}

export default function LifeEventGraph() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <LifeEventGraphForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
