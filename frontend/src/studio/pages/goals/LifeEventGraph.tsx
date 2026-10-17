import { getAllConditions, type ConditionEvaluation } from '../../../api/lifeEventConditions';
import { useCallback, useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { getLifeEventsWithProgress } from '../../../api';
import { createLifeEventLink, deleteLifeEventLink, getLifeEventLinks, getLifeEventScenarios } from '../../../api/lifeEventGraph';
import type { LifeEventLink, LifeEventLinkInput, LifeEventScenario } from '../../../api/lifeEventGraph';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useResource } from '../../useResource';
import { Choice, EditorActions, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';
import LifeEventDiagram from './LifeEventDiagram';
import LifeEventLinkDetails from './LifeEventLinkDetails';

function LinkEditor({ events, busy, onSave, onCancel }: {
    events: LifeEvent[]; busy: boolean; onSave: (input: LifeEventLinkInput) => void; onCancel: () => void;
}) {
    const form = useId();
    const [source, setSource] = useState<number | null>(null);
    const [target, setTarget] = useState<number | null>(null);
    const [kind, setKind] = useState<LifeEventLinkInput['kind']>('after');
    const [offset, setOffset] = useState(0);
    return <form id={form} onSubmit={(event) => {
        event.preventDefault();
        if (source !== null && target !== null && !busy) onSave({ from_event_id: source, to_event_id: target, kind, offset_months: offset });
    }}>
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <Choice label="元のイベント" value={source} options={events} required onChange={(value) => { setSource(value); if (value === target) setTarget(null); }} />
            <Choice label="次のイベント" value={target} options={events.filter((item) => item.id !== source)} required onChange={setTarget} />
            <Field label="接続の種類"><select value={kind} onChange={(event) => setKind(event.target.value as LifeEventLinkInput['kind'])} className={inputClass}>
                <option value="after">必ず続く</option><option value="alternative">いずれかを選ぶ</option>
            </select></Field>
            <Field label="元のイベントからの月数（0＝目標日）"><input type="number" required step="1" value={offset} onChange={(event) => setOffset(Number(event.target.value))} className={inputClass} /></Field>
        </fieldset>
        <EditorActions busy={busy} form={form} onCancel={onCancel} />
    </form>;
}

function offsetDate(source: string | null, months: number): string | null {
    if (!source) return null;
    const [year, month, day] = source.split('-').map(Number);
    const absolute = year * 12 + month - 1 + months;
    const nextYear = Math.floor(absolute / 12);
    const nextMonth = absolute - nextYear * 12;
    if (nextYear < 1 || nextYear > 9999) return null;
    // Calendar offsets clamp the day at each step, matching the graph resolver.
    const leapYear = nextYear % 4 === 0 && (nextYear % 100 !== 0 || nextYear % 400 === 0);
    const lastDay = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][nextMonth];
    return `${String(nextYear).padStart(4, '0')}-${String(nextMonth + 1).padStart(2, '0')}-${String(Math.min(day, lastDay)).padStart(2, '0')}`;
}

function EventOutline({ events, links, scenario, evaluations, currency, disabled, onDelete }: {
    events: LifeEvent[]; links: LifeEventLink[]; scenario?: LifeEventScenario; evaluations: Record<number, ConditionEvaluation>; currency: string;
    disabled: boolean; onDelete: (link: LifeEventLink) => void;
}) {
    const byId = new Map(events.map((item) => [item.id, item]));
    const activeLinks = links.filter((edge) => byId.has(edge.from_event_id) && byId.has(edge.to_event_id));
    const outgoing = new Map<number, LifeEventLink[]>();
    const targets = new Set(activeLinks.map((edge) => edge.to_event_id));
    for (const edge of activeLinks) outgoing.set(edge.from_event_id, [...(outgoing.get(edge.from_event_id) ?? []), edge]);
    const resolved = new Map(scenario?.events.map((item) => [item.id, item]));
    const rows: Array<{ event: LifeEvent; edge?: LifeEventLink; depth: number; date: string | null; shared: boolean }> = [];
    const expanded = new Set<number>();
    const pending = events.filter((item) => !targets.has(item.id)).reverse().map((event) => ({ event, depth: 0, date: event.target_date as string | null, edge: undefined as LifeEventLink | undefined }));
    while (pending.length) {
        const entry = pending.pop();
        if (!entry) break;
        const selected = resolved.get(entry.event.id);
        const date = selected ? selected.resolved_date : entry.date;
        const shared = expanded.has(entry.event.id);
        rows.push({ ...entry, date, shared });
        // Expand a shared descendant once; converging paths must not explode the outline.
        if (shared) continue;
        expanded.add(entry.event.id);
        const children = outgoing.get(entry.event.id) ?? [];
        for (const edge of [...children].reverse()) {
            const child = byId.get(edge.to_event_id);
            if (child) pending.push({ event: child, edge, depth: entry.depth + 1, date: edge.offset_months === 0 ? child.target_date : offsetDate(date, edge.offset_months) });
        }
    }
    return <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
        {rows.length ? <ul className="min-w-max space-y-2" aria-label="イベントの接続">
            {rows.map(({ event, edge, depth, date, shared }) => <li key={edge ? `link-${edge.id}` : `root-${event.id}`} style={{ paddingLeft: `${depth * 24}px` }}>
                <div className="flex items-center gap-3 rounded border-l-2 border-[var(--studio-border)] py-2 pl-3 text-sm">
                    {edge && <span className="text-xs text-[var(--studio-text-muted)]">{edge.kind === 'alternative' ? '選択肢' : '必ず続く'}・{edge.offset_months === 0 ? '目標日' : `${edge.offset_months > 0 ? '+' : ''}${edge.offset_months}か月`}</span>}
                    <Link to={`/goals/events/${event.id}`} className="text-[var(--studio-accent)] hover:underline">{event.name}</Link>
                    {evaluations[event.id]?.satisfied === false && <span className="text-xs text-[var(--studio-text-muted)]" aria-label="条件未達">○ 条件未達</span>}
                    {evaluations[event.id]?.conditions.length > 0 && evaluations[event.id]?.satisfied === null && <span className="text-xs text-[var(--studio-text-muted)]">○ 判定不能</span>}
                    <span className="tabular-nums">{date ?? '日付未設定'}</span>
                    <span className="tabular-nums">{formatCurrency(event.target_amount, currency)}</span>
                    {shared && <span className="text-xs text-[var(--studio-text-muted)]">共通イベント</span>}
                    {!resolved.has(event.id) && <span className="text-xs text-[var(--studio-text-muted)]">選択中の案では対象外</span>}
                    {edge && <button type="button" disabled={disabled} onClick={() => onDelete(edge)} aria-label={`${byId.get(edge.from_event_id)?.name}から${event.name}への接続を削除`} className={buttonClass}>接続を削除</button>}
                </div>
            </li>)}
        </ul> : <p className="text-sm text-[var(--studio-text-muted)]">イベントはありません。</p>}
    </div>;
}

function ScenarioResults({ currency, clientName, view }: { currency: string; clientName?: string; view: 'diagram' | 'outline' }) {
    const confirm = useConfirm();
    const load = useCallback(async () => {
        // This goal reader exposes major-unit target amounts; raw ORM rows carry minor units.
        const [events, links, comparison, evaluations] = await Promise.all([getLifeEventsWithProgress(), getLifeEventLinks(), getLifeEventScenarios(), getAllConditions()]);
        return { events, links, comparison, evaluations };
    }, []);
    const resource = useResource(load);
    const mutation = useMutation();
    const [editing, setEditing] = useState(false);
    const [editingLink, setEditingLink] = useState<LifeEventLink | null>(null);
    const [nextKind, setNextKind] = useState<LifeEventLinkInput['kind']>('after');
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy || !clientName;
    const selected = resource.data?.comparison.scenarios.find((item) => item.id === resource.data?.comparison.adopted.scenario_id);
    const remove = async (edge: LifeEventLink) => {
        if (disabled) return;
        const source = resource.data?.events.find((event) => event.id === edge.from_event_id)?.name;
        const target = resource.data?.events.find((event) => event.id === edge.to_event_id)?.name;
        if (await confirm(`「${clientName}」の「${source}」から「${target}」への接続を削除します。`, '接続を削除')) {
            void mutation.run(() => deleteLifeEventLink(edge.id), '接続を削除しました。', resource.reload);
        }
    };
    return <div className="space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-wrap items-end gap-3">
                <button type="button" disabled={disabled || (resource.data?.events.length ?? 0) < 2} onClick={() => setEditing(true)} className={buttonClass}>接続を追加</button>
                <div className="space-y-2 text-sm"><span className="block text-[var(--studio-text-muted)]">接続の種類</span><div role="group" aria-label="ドラッグで作る接続の種類" className="flex gap-1">
                    {(['after', 'alternative'] as const).map((kind) => <button key={kind} type="button" aria-pressed={nextKind === kind} disabled={disabled} onClick={() => setNextKind(kind)} className={`${buttonClass} ${nextKind === kind ? 'bg-[var(--studio-accent-soft)] ring-1 ring-[var(--studio-accent)]' : ''}`}>
                        {kind === 'after' ? '必ず続く' : 'いずれかを選ぶ'}
                    </button>)}
                </div></div>
            </div>
        </div>
        <Feedback loading={resource.loading} error={resource.error || (!editing && !editingLink ? mutation.error : '')} message={mutation.message} />
        {resource.data && !resource.loading && !resource.error && <>
            {!resource.data.comparison.adopted.exact && <p role="status" className="text-sm text-[var(--studio-warning)]">分岐の選択がまだ確定していません。</p>}
            {resource.data.comparison.truncated && <p role="status" className="text-sm text-[var(--studio-warning)]">{resource.data.comparison.fork_count}か所の分岐で64案を超えたため、先頭64案を表示しています。</p>}
            {view === 'diagram' ? <LifeEventDiagram evaluations={resource.data.evaluations} events={resource.data.events} links={resource.data.links} scenarios={resource.data.comparison.scenarios} scenario={selected} currency={currency} disabled={disabled}
                onEdgeClick={setEditingLink} onConnect={(source, target) => {
                    if (disabled) return;
                    void mutation.run(() => createLifeEventLink({ from_event_id: source, to_event_id: target, kind: nextKind, offset_months: 0 }), '接続を追加しました。', resource.reload);
                }} />
                : <EventOutline evaluations={resource.data.evaluations} events={resource.data.events} links={resource.data.links} scenario={selected} currency={currency} disabled={disabled} onDelete={(edge) => { void remove(edge); }} />}
        </>}
        {editing && resource.data && <Overlay title="接続を追加" onClose={() => { if (!mutation.busy) setEditing(false); }}>
            <Feedback error={mutation.error} />
            <LinkEditor events={resource.data.events} busy={mutation.busy} onCancel={() => setEditing(false)} onSave={(input) => {
                if (disabled) return;
                void mutation.run(() => createLifeEventLink(input), '接続を追加しました。', () => { setEditing(false); resource.reload(); });
            }} />
        </Overlay>}
        {editingLink && resource.data && clientName && <LifeEventLinkDetails edge={editingLink} events={resource.data.events} clientName={clientName} onReload={resource.reload} onClose={() => setEditingLink(null)} />}
    </div>;
}

function LifeEventGraphForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const [view, setView] = useState<'diagram' | 'outline'>('diagram');
    return <section className="space-y-5">
        <div role="group" aria-label="イベントの表示" className="flex gap-1">
            {(['diagram', 'outline'] as const).map((mode) => <button key={mode} type="button" aria-pressed={view === mode} onClick={() => setView(mode)} className={`${buttonClass} ${view === mode ? 'bg-[var(--studio-accent-soft)] ring-1 ring-[var(--studio-accent)]' : ''}`}>
                {mode === 'diagram' ? '図' : '接続の一覧'}
            </button>)}
        </div>
        <ScenarioResults currency={currency} clientName={clientName} view={view} />
    </section>;
}

export default function LifeEventGraph() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <LifeEventGraphForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
