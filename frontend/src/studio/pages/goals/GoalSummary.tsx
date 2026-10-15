import { useCallback, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getLifeEventsWithProgress } from '../../../api';
import { getLifeEventScenarios, type LifeEventScenario, type ScenarioParameters } from '../../../api/lifeEventGraph';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { formatDate } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass } from '../db/forms';
import { goalPercent } from './presentation';

const defaults: ScenarioParameters = { years: 30, annual_return: 5, inflation: 2 };
const linkClass = 'rounded text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]';

function Projection({ scenario, currency }: { scenario: LifeEventScenario; currency: string }) {
    const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };
    return <div role="img" aria-label={`採用案の純資産推移。横軸：年、縦軸：金額（${currency}）。P10・P50・P90と累計必要額`} className="h-80 min-w-0">
        <ResponsiveContainer width="100%" height="100%">
            <LineChart data={scenario.projection} margin={{ top: 20, right: 20, bottom: 28, left: 20 }} accessibilityLayer>
                <CartesianGrid stroke="var(--studio-border)" vertical={false} />
                <XAxis dataKey="year" tick={axisStyle} minTickGap={30} label={{ value: '年', position: 'bottom', ...axisStyle }} />
                <YAxis width={105} tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'top', ...axisStyle }} />
                <Tooltip contentStyle={{ background: 'var(--studio-surface)', border: '1px solid var(--studio-border)', color: 'var(--studio-text)' }} formatter={(value, name) => [formatCurrency(Number(value), currency), name]} />
                <Legend verticalAlign="top" />
                <Line type="linear" dataKey="p10" name="下位10%（P10）" stroke="var(--studio-warning)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="linear" dataKey="p50" name="中央値（P50）" stroke="var(--studio-accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="linear" dataKey="p90" name="上位10%（P90）" stroke="var(--studio-positive)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="linear" dataKey="cumulative_target" name="累計必要額" stroke="var(--studio-text-muted)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
            </LineChart>
        </ResponsiveContainer>
    </div>;
}

function AdoptedSummary({ scenario, events, exact, currency }: { scenario: LifeEventScenario; events: LifeEvent[]; exact: boolean; currency: string }) {
    const navigate = useNavigate();
    const progress = new Map(events.map((event) => [event.id, event]));
    const rows = [...scenario.events].sort((a, b) => (a.resolved_date ?? '\uffff').localeCompare(b.resolved_date ?? '\uffff') || a.id - b.id);
    const required = rows.reduce((total, event) => total + event.target_amount, 0);
    // Only claims belonging to this branch count; missing progress contributes zero.
    const funded = rows.reduce((total, event) => total + (progress.get(event.id)?.current_funded ?? 0), 0);
    const lastDate = rows.filter((event) => event.resolved_date !== null).at(-1)?.resolved_date;
    return <>
        <div className="font-semibold">{scenario.label}</div>
        {!exact && <p role="status" className="text-sm text-[var(--studio-warning)]">分岐の選択がまだ確定していません（<Link to="/goals/graph" className={linkClass}>接続図</Link>）。</p>}
        <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
            {[
                ['合計必要額', formatCurrency(required, currency)],
                ['確保済み合計', formatCurrency(funded, currency)],
                ['不足', formatCurrency(Math.max(0, required - funded), currency)],
                ['最終目標日', lastDate ? formatDate(lastDate) : '未設定'],
                ['イベント数', `${rows.length}件`],
            ].map(([label, value]) => <div key={label}><dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt><dd className="mt-2 font-semibold tabular-nums">{value}</dd></div>)}
        </dl>
        <DataTable columns={['名称', '日付', '必要額', '確保済み', '進捗']}>
            {rows.map((item) => {
                const claimed = progress.get(item.id)?.current_funded ?? 0;
                return <tr key={item.id} className="cursor-pointer hover:bg-[var(--studio-accent-soft)]" onClick={() => navigate(`/goals/events/${item.id}`)}>
                    <th scope="row" className="px-5 py-3 font-medium"><Link to={`/goals/events/${item.id}`} onClick={(event) => event.stopPropagation()} className={linkClass}>{item.name}</Link></th>
                    <td className="whitespace-nowrap px-5 py-3">{item.resolved_date ? formatDate(item.resolved_date) : '未設定'}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(item.target_amount, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(claimed, currency)}</td>
                    {/* A zero target has no percentage to report; 0% would read as no progress. */}
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{goalPercent(item.target_amount > 0 ? claimed / item.target_amount * 100 : undefined)}</td>
                </tr>;
            })}
        </DataTable>
        <Projection scenario={scenario} currency={currency} />
    </>;
}

function SummaryResults({ parameters, currency }: { parameters: ScenarioParameters; currency: string }) {
    const load = useCallback(async () => {
        const [comparison, events] = await Promise.all([getLifeEventScenarios(parameters), getLifeEventsWithProgress(false)]);
        return { comparison, events };
    }, [parameters]);
    const resource = useResource(load);
    const data = resource.data;
    const scenario = data?.comparison.scenarios.find((item) => item.id === data.comparison.adopted.scenario_id);
    // The graph contract expresses every event in one client currency; never combine currencies.
    const scenarioCurrency = scenario?.events[0]?.currency ?? currency;
    const mixedCurrencies = scenario?.events.some((event) => event.currency !== scenarioCurrency);
    return <>
        <Feedback loading={resource.loading} error={resource.error} />
        {data && !resource.loading && !resource.error && (
            data.events.length === 0 && data.comparison.scenarios.every((item) => item.events.length === 0) ? <p className="text-sm text-[var(--studio-text-muted)]">ライフイベントはありません。<Link to="/goals/events" className={linkClass}>ライフイベント一覧</Link></p>
                : !scenario ? <p className="text-sm text-[var(--studio-text-muted)]">採用された分岐はありません。<Link to="/goals/graph" className={linkClass}>接続図</Link></p>
                    : mixedCurrencies ? <Feedback error="採用案の通貨が一致しないため集計できません。" />
                        : <AdoptedSummary scenario={scenario} events={data.events} exact={data.comparison.adopted.exact} currency={scenarioCurrency} />
        )}
    </>;
}

function SummaryForClient({ currency }: { currency: string }) {
    const [draft, setDraft] = useState(defaults);
    const [parameters, setParameters] = useState(defaults);
    return <section className="space-y-5">
        <form onSubmit={(event) => { event.preventDefault(); setParameters({ ...draft }); }} className="flex flex-wrap items-end gap-4">
            <Field label="期間（年）"><input type="number" min="1" max="60" step="1" required value={draft.years} onChange={(event) => setDraft({ ...draft, years: Number(event.target.value) })} className={inputClass} /></Field>
            <Field label="年利（%）"><input type="number" step="0.1" required value={draft.annual_return} onChange={(event) => setDraft({ ...draft, annual_return: Number(event.target.value) })} className={inputClass} /></Field>
            <Field label="インフレ（%）"><input type="number" step="0.1" required value={draft.inflation} onChange={(event) => setDraft({ ...draft, inflation: Number(event.target.value) })} className={inputClass} /></Field>
            <button type="submit" className={buttonClass}>再試算</button>
        </form>
        {/* Remount so a projection never appears with another request's assumptions. */}
        <SummaryResults key={JSON.stringify(parameters)} parameters={parameters} currency={currency} />
    </section>;
}

export default function GoalSummary() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <SummaryForClient key={`${clientId}:${currency}`} currency={currency} />;
}
