import { useCallback, useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getLifeEventsWithProgress } from '../../../api';
import { createLifeEventLink, deleteLifeEventLink, getLifeEventLinks, getLifeEventScenarios } from '../../../api/lifeEventGraph';
import type { LifeEventLink, LifeEventLinkInput, LifeEventScenario, ScenarioParameters } from '../../../api/lifeEventGraph';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useReloadAction } from '../../components/useReloadAction';
import { useResource } from '../../useResource';
import { Choice, DataTable, EditorActions, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';

const defaults: ScenarioParameters = { years: 30, annual_return: 5, inflation: 2 };

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

function EventOutline({ events, links, scenario, currency, disabled, onDelete }: {
    events: LifeEvent[]; links: LifeEventLink[]; scenario?: LifeEventScenario; currency: string;
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
                    <Link to={`/goals/${event.id}`} className="text-[var(--studio-accent)] hover:underline">{event.name}</Link>
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

function Comparison({ scenarios, currency }: { scenarios: LifeEventScenario[]; currency: string }) {
    const rows = scenarios[0]?.projection.map((row, index) => {
        const point: Record<string, number> = { year: row.year };
        for (const scenario of scenarios) point[`scenario-${scenario.id}`] = scenario.projection[index].p50;
        return point;
    }) ?? [];
    const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };
    return <>
        <div role="img" aria-label={`シナリオ別の純資産推移（中央値）。横軸：年、縦軸：金額（${currency}）`} className="h-96 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} margin={{ top: 20, right: 20, bottom: 28, left: 20 }} accessibilityLayer>
                    <CartesianGrid stroke="var(--studio-border)" vertical={false} />
                    <XAxis dataKey="year" tick={axisStyle} minTickGap={30} label={{ value: '年', position: 'bottom', ...axisStyle }} />
                    <YAxis width={105} tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'top', ...axisStyle }} />
                    <Tooltip contentStyle={{ background: 'var(--studio-surface)', border: '1px solid var(--studio-border)', color: 'var(--studio-text)' }} formatter={(value, name) => [formatCurrency(Number(value), currency), name]} />
                    {scenarios.map((scenario, index) => <Line key={scenario.id} type="linear" dataKey={`scenario-${scenario.id}`} name={scenario.label} stroke={`hsl(${(index * 137.508 + 210) % 360} 50% 48%)`} strokeWidth={2} dot={false} isAnimationActive={false} />)}
                    <Legend verticalAlign="top" wrapperStyle={{ maxHeight: 96, overflowY: 'auto' }} />
                </LineChart>
            </ResponsiveContainer>
        </div>
        <DataTable columns={['シナリオ', `最終純資産・中央値（${currency}）`, 'イベント総額（通貨別）']}>
            {scenarios.map((scenario) => {
                // Even if a later format supports foreign events, never collapse their currencies.
                const totals = new Map<string, number>();
                for (const event of scenario.events) totals.set(event.currency, (totals.get(event.currency) ?? 0) + event.target_amount);
                return <tr key={scenario.id}>
                    <th scope="row" className="px-5 py-3 font-medium">{scenario.label}</th>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(scenario.projection.at(-1)?.p50, currency)}</td>
                    <td className="px-5 py-3 tabular-nums">{[...totals].map(([code, amount]) => <span key={code} className="block whitespace-nowrap">{formatCurrency(amount, code)}（{code}）</span>)}</td>
                </tr>;
            })}
        </DataTable>
    </>;
}

function ScenarioResults({ currency, clientName, parameters }: { currency: string; clientName?: string; parameters: ScenarioParameters }) {
    const confirm = useConfirm();
    const load = useCallback(async () => {
        // This goal reader exposes major-unit target amounts; raw ORM rows carry minor units.
        const [events, links, comparison] = await Promise.all([getLifeEventsWithProgress(), getLifeEventLinks(), getLifeEventScenarios(parameters)]);
        return { events, links, comparison };
    }, [parameters]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [editing, setEditing] = useState(false);
    const [selectedId, setSelectedId] = useState('');
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy || !clientName;
    const selected = resource.data?.comparison.scenarios.find((item) => item.id === selectedId) ?? resource.data?.comparison.scenarios[0];
    useReloadAction(resource.reload, resource.loading || mutation.busy || editing);
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
            <button type="button" disabled={disabled || (resource.data?.events.length ?? 0) < 2} onClick={() => setEditing(true)} className={buttonClass}>接続を追加</button>
            {resource.data && <Field label="日付の基準にする案"><select value={selected?.id ?? ''} onChange={(event) => setSelectedId(event.target.value)} disabled={disabled} className={inputClass}>
                {resource.data.comparison.scenarios.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select></Field>}
        </div>
        <Feedback loading={resource.loading} error={resource.error || (!editing ? mutation.error : '')} message={mutation.message} />
        {resource.data && !resource.loading && !resource.error && <>
            {resource.data.comparison.truncated && <p role="status" className="text-sm text-[var(--studio-warning)]">{resource.data.comparison.fork_count}か所の分岐で64案を超えたため、先頭64案を表示しています。</p>}
            <EventOutline events={resource.data.events} links={resource.data.links} scenario={selected} currency={currency} disabled={disabled} onDelete={(edge) => { void remove(edge); }} />
            <Comparison scenarios={resource.data.comparison.scenarios} currency={currency} />
        </>}
        {editing && resource.data && <Overlay title="接続を追加" onClose={() => { if (!mutation.busy) setEditing(false); }}>
            <Feedback error={mutation.error} />
            <LinkEditor events={resource.data.events} busy={mutation.busy} onCancel={() => setEditing(false)} onSave={(input) => {
                if (disabled) return;
                void mutation.run(() => createLifeEventLink(input), '接続を追加しました。', () => { setEditing(false); resource.reload(); });
            }} />
        </Overlay>}
    </div>;
}

function ScenariosForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const [draft, setDraft] = useState(defaults);
    const [parameters, setParameters] = useState(defaults);
    return <section className="space-y-5">
        <form onSubmit={(event) => { event.preventDefault(); setParameters({ ...draft }); }} className="flex flex-wrap items-end gap-4">
            <Field label="期間（年）"><input type="number" min="1" max="60" step="1" required value={draft.years} onChange={(event) => setDraft({ ...draft, years: Number(event.target.value) })} className={inputClass} /></Field>
            <Field label="年利（%）"><input type="number" step="0.1" required value={draft.annual_return} onChange={(event) => setDraft({ ...draft, annual_return: Number(event.target.value) })} className={inputClass} /></Field>
            <Field label="インフレ（%）"><input type="number" step="0.1" required value={draft.inflation} onChange={(event) => setDraft({ ...draft, inflation: Number(event.target.value) })} className={inputClass} /></Field>
            <button type="submit" className={buttonClass}>再試算</button>
        </form>
        {/* Parameter changes remount results so dates and paths always use the same assumptions. */}
        <ScenarioResults key={JSON.stringify(parameters)} currency={currency} clientName={clientName} parameters={parameters} />
    </section>;
}

export default function LifeEventScenarios() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <ScenariosForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
