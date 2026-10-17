import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { LifeEventScenario } from '../../../api/lifeEventGraph';
import { formatCurrency } from '../../../utils/currency';
import { DataTable } from '../db/Database';

export default function Comparison({ scenarios, currency }: { scenarios: LifeEventScenario[]; currency: string }) {
    const rows = scenarios[0]?.projection.map((row, index) => {
        const point: Record<string, number> = { year: row.year };
        for (const scenario of scenarios) point[`scenario-${scenario.id}`] = scenario.projection[index].p50;
        return point;
    }) ?? [];
    const colours = ['accent', 'positive', 'warning', 'budget', 'danger', 'text-muted'];
    const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };
    return <>
        <div role="img" aria-label={`シナリオ別の純資産推移（中央値）。横軸：年、縦軸：金額（${currency}）`} className="h-96 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} margin={{ top: 20, right: 20, bottom: 28, left: 20 }} accessibilityLayer>
                    <CartesianGrid stroke="var(--studio-border)" vertical={false} />
                    <XAxis dataKey="year" tick={axisStyle} minTickGap={30} label={{ value: '年', position: 'bottom', ...axisStyle }} />
                    <YAxis width={105} tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'top', ...axisStyle }} />
                    <Tooltip contentStyle={{ background: 'var(--studio-surface)', border: '1px solid var(--studio-border)', color: 'var(--studio-text)' }} formatter={(value, name) => [formatCurrency(Number(value), currency), name]} />
                    {scenarios.map((scenario, index) => <Line key={scenario.id} type="linear" dataKey={`scenario-${scenario.id}`} name={scenario.label} stroke={`var(--studio-${colours[index % colours.length]})`} strokeDasharray={index < colours.length ? undefined : `${2 + Math.floor(index / colours.length) * 2} 3`} strokeWidth={2} dot={false} isAnimationActive={false} />)}
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

