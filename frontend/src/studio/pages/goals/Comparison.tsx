import { Link } from 'react-router-dom';
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { formatCurrency } from '../../../utils/currency';
import { DataTable } from '../db/Database';

const colours = ['accent', 'budget', 'warning', 'positive', 'danger', 'text-muted'];

export function MissingForks({ scenario }: { scenario: { id: number; missing_forks: number[] } }) {
    return scenario.missing_forks.length > 0 && <p role="status" className="text-sm text-[var(--studio-warning)]">未選択の分岐あり（<Link to={`/goals/graph?scenario=${scenario.id}`} className="underline">シナリオ作成で選ぶ</Link>）</p>;
}

function comparisonRows(scenarios: ProjectedLifeScenario[], focusedId: number | undefined) {
    // Horizons belong to scenarios; array positions cannot align different projections.
    const years = new Map<number, Record<string, number | [number, number]>>();
    for (const scenario of scenarios) for (const row of scenario.projection) {
        const point = years.get(row.year) ?? { year: row.year };
        point[`scenario-${scenario.id}`] = row.p50;
        if (scenario.id === focusedId) point.band = [row.p10, row.p90];
        years.set(row.year, point);
    }
    return [...years.values()].sort((a, b) => Number(a.year) - Number(b.year));
}

function EventTotal({ scenario, direction, currency }: { scenario: ProjectedLifeScenario; direction: 'expense' | 'income'; currency: string }) {
    const totals = new Map<string, number>();
    for (const event of scenario.events) if (event.direction === direction) totals.set(event.currency, (totals.get(event.currency) ?? 0) + event.target_amount);
    return totals.size ? [...totals].map(([code, amount]) => <span key={code} className="block whitespace-nowrap">{formatCurrency(amount, code)}（{code}）</span>) : formatCurrency(0, currency);
}

export default function Comparison({ scenarios, focusedId, currency, colourIds }: { scenarios: ProjectedLifeScenario[]; focusedId?: number; currency: string; colourIds: number[] }) {
    const rows = comparisonRows(scenarios, focusedId);
    const focused = scenarios.find((scenario) => scenario.id === focusedId);
    const colour = (id: number) => `var(--studio-${colours[Math.max(0, colourIds.indexOf(id)) % colours.length]})`;
    const eventNames = new Map<number, string[]>();
    for (const event of focused?.events ?? []) {
        if (!event.resolved_date) continue;
        const year = Number(event.resolved_date.slice(0, 4));
        eventNames.set(year, [...(eventNames.get(year) ?? []), event.name]);
    }
    const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };
    return <>
        <div role="img" aria-label={`シナリオ別の純資産推移（中央値）と選択中のシナリオのP10〜P90。横軸：年、縦軸：金額（${currency}）`} className="h-96 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={rows} margin={{ top: 40, right: 30, bottom: 28, left: 20 }} accessibilityLayer>
                    <CartesianGrid stroke="var(--studio-border)" vertical={false} />
                    <XAxis type="number" domain={['dataMin', 'dataMax']} dataKey="year" allowDecimals={false} tick={axisStyle} minTickGap={30} label={{ value: '年', position: 'bottom', ...axisStyle }} />
                    <YAxis width={105} tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'top', ...axisStyle }} />
                    <Tooltip contentStyle={{ background: 'var(--studio-surface)', border: '1px solid var(--studio-border)', color: 'var(--studio-text)' }} formatter={(value, name) => [Array.isArray(value) ? value.map((amount) => formatCurrency(Number(amount), currency)).join('〜') : formatCurrency(Number(value), currency), name]} />
                    {focused && <Area key={`band-${focused.id}`} type="linear" dataKey="band" name={`${focused.name} P10〜P90`} stroke="none" fill={colour(focused.id)} fillOpacity={0.15} isAnimationActive={false} />}
                    {scenarios.map((scenario) => <Line key={`line-${scenario.id}`} type="linear" dataKey={`scenario-${scenario.id}`} name={scenario.name} stroke={colour(scenario.id)} strokeDasharray={colourIds.indexOf(scenario.id) < colours.length ? undefined : '5 3'} strokeWidth={2} dot={false} isAnimationActive={false} />)}
                    {[...eventNames].map(([year, names]) => <ReferenceLine key={`event-year-${year}`} x={year} ifOverflow="extendDomain" stroke="var(--studio-border-strong)" label={{ value: names.join('・'), position: 'insideTop', ...axisStyle }} />)}
                    <Legend verticalAlign="top" wrapperStyle={{ maxHeight: 96, overflowY: 'auto' }} />
                </ComposedChart>
            </ResponsiveContainer>
        </div>
        <DataTable columns={['シナリオ', '最終純資産（中央値）', '支出イベント合計', '収入イベント合計', '前提条件']}>
            {scenarios.map((scenario) => {
                const probabilities = scenario.conditions.filter((event) => event.conditions.length > 0).map((event) => event.probability).filter((value) => value !== null);
                const lowest = probabilities.length ? Math.min(...probabilities) : null;
                return <tr key={`scenario-row-${scenario.id}`} className={scenario.id === focusedId ? 'bg-[var(--studio-accent-soft)]' : ''}>
                    <th scope="row" className="px-5 py-3 font-medium">{scenario.name}{scenario.is_goal && <span className="ml-2 text-xs text-[var(--studio-accent)]">ゴール</span>}<MissingForks scenario={scenario} /></th>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{scenario.projection.length ? formatCurrency(scenario.projection.at(-1)?.p50, currency) : '—'}</td>
                    <td className="px-5 py-3 tabular-nums"><EventTotal scenario={scenario} direction="expense" currency={currency} /></td>
                    <td className="px-5 py-3 tabular-nums"><EventTotal scenario={scenario} direction="income" currency={currency} /></td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{lowest === null ? '—' : `${Math.round(lowest * 100)}%`}</td>
                </tr>;
            })}
        </DataTable>
    </>;
}
