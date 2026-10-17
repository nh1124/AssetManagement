import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { formatCurrency } from '../../../utils/currency';

const colours = ['accent', 'budget', 'warning', 'positive', 'danger', 'text-muted'];

function projectionRows(scenarios: ProjectedLifeScenario[], focusedId: number | undefined) {
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

export default function ScenarioProjectionChart({ scenarios, focusedId, currency, colourIds }: {
    scenarios: ProjectedLifeScenario[]; focusedId?: number; currency: string; colourIds: number[];
}) {
    const rows = projectionRows(scenarios, focusedId);
    const focused = scenarios.find((scenario) => scenario.id === focusedId);
    const colour = (id: number) => `var(--studio-${colours[Math.max(0, colourIds.indexOf(id)) % colours.length]})`;
    const eventNames = new Map<number, string[]>();
    for (const event of focused?.events ?? []) {
        if (!event.resolved_date) continue;
        const year = Number(event.resolved_date.slice(0, 4));
        eventNames.set(year, [...(eventNames.get(year) ?? []), event.name]);
    }
    const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };
    return <div role="img" aria-label={`シナリオ別の純資産推移（中央値）と選択中のシナリオのP10〜P90。横軸：年、縦軸：金額（${currency}）`} className="h-96 min-w-0">
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
    </div>;
}
