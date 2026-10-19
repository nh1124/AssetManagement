import { useState } from 'react';
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts';
import type { ProjectedLifeScenario } from '../../../api/lifeScenarios';
import type { NetWorthHistoryPoint } from '../../../types';
import { formatCurrency } from '../../../utils/currency';

/** A month as a position on a year axis: the end of 2026-03 is 2026.25. */
const monthEnd = (period: string) => Number(period.slice(0, 4)) + Number(period.slice(5, 7)) / 12;

function monthLabel(position: number): string {
    const total = Math.round(position * 12);
    const year = Math.floor((total - 1) / 12);
    return `${year}年${total - year * 12}月`;
}

type Point = { x: number; band?: [number, number]; p50?: number; cumulative_target?: number; cumulative_income?: number; actual?: number; events?: string[] };

/** The month, each visible series, and the life events planned in that month. */
function ChartTooltip({ active, label, payload, currency }: Pick<TooltipContentProps<number | number[], string>, 'active' | 'label' | 'payload'> & { currency: string }) {
    if (!active || !payload?.length) return null;
    const point = payload[0]?.payload as Point | undefined;
    const money = (value: unknown) => Array.isArray(value) ? value.map((item) => formatCurrency(Number(item), currency)).join('〜') : formatCurrency(Number(value), currency);
    return <div className="space-y-1 rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] p-2 text-xs text-[var(--studio-text)] shadow">
        <p className="font-medium">{monthLabel(Number(label))}</p>
        {payload.filter((item) => item.value !== undefined && item.value !== null).map((item) => <p key={String(item.dataKey)} className="tabular-nums" style={{ color: item.color }}>{item.name}：{money(item.value)}</p>)}
        {point?.events && <p>ライフイベント：{point.events.join('・')}</p>}
    </div>;
}

/** Net worth bands from the simulation, the event demand, and (on the goal) the actual month-end net worth.
 *
 * Clicking a legend entry hides or shows its series; a hidden entry turns grey.
 */
export default function GoalProjectionChart({ scenario, history = [], currentPeriod, currency }: {
    scenario: ProjectedLifeScenario; history?: NetWorthHistoryPoint[]; currentPeriod: string; currency: string;
}) {
    const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
    const start = monthEnd(currentPeriod);
    const points = new Map<number, Point>();
    const at = (x: number) => points.get(x) ?? points.set(x, { x }).get(x) as Point;
    scenario.projection.forEach((row, index) => {
        Object.assign(at(start + index), { band: [row.p10, row.p90], p50: row.p50, cumulative_target: row.cumulative_target, cumulative_income: row.cumulative_income });
    });
    // Months before the first entry carry no ledger yet; they are not a net worth of zero.
    const first = history.findIndex((row) => row.assets !== 0 || row.liabilities !== 0);
    for (const row of first < 0 ? [] : history.slice(first)) at(monthEnd(row.period)).actual = row.net_worth;
    // An event month is a point of its own, so hovering its line names the events.
    const eventMonths = new Set<number>();
    for (const event of scenario.events) {
        if (!event.resolved_date) continue;
        const point = at(monthEnd(event.resolved_date.slice(0, 7)));
        point.events = [...(point.events ?? []), event.name];
        eventMonths.add(point.x);
    }
    const rows = [...points.values()].sort((a, b) => a.x - b.x);
    const hasIncome = scenario.events.some((event) => event.direction === 'income');
    const hasActual = rows.some((row) => row.actual !== undefined);
    const toggle = (key: string) => setHidden((current) => {
        const next = new Set(current);
        if (next.has(key)) next.delete(key); else next.add(key);
        return next;
    });
    const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };
    return <div role="img" aria-label={`純資産の推移。横軸：年、縦軸：金額（${currency}）。P10〜P90、中央値、累計必要額${hasIncome ? '、累計収入' : ''}${hasActual ? '、実績の純資産' : ''}とライフイベントの予定`} className="h-96 min-w-0">
        <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 12, right: 30, bottom: 28, left: 20 }} accessibilityLayer>
                <CartesianGrid stroke="var(--studio-border)" vertical={false} />
                <XAxis type="number" domain={['dataMin', 'dataMax']} dataKey="x" allowDecimals={false} tickFormatter={(value: number) => String(Math.floor(value))} tick={axisStyle} minTickGap={30} label={{ value: '年', position: 'bottom', ...axisStyle }} />
                <YAxis width={105} tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'top', ...axisStyle }} />
                <Tooltip content={(props) => <ChartTooltip active={props.active} label={props.label} payload={props.payload} currency={currency} />} />
                <Legend verticalAlign="top" inactiveColor="var(--studio-border-strong)" wrapperStyle={{ cursor: 'pointer', fontSize: 12, paddingBottom: 8 }}
                    onClick={(entry) => { if (typeof entry.dataKey === 'string') toggle(entry.dataKey); }}
                    formatter={(value: string, entry) => <span style={{ color: typeof entry.dataKey === 'string' && hidden.has(entry.dataKey) ? 'var(--studio-border-strong)' : 'var(--studio-text)' }}>{value}</span>} />
                <Area type="linear" dataKey="band" name="P10〜P90" hide={hidden.has('band')} stroke="none" fill="var(--studio-accent)" fillOpacity={0.15} connectNulls isAnimationActive={false} />
                <Line type="linear" dataKey="p50" name="中央値（P50）" hide={hidden.has('p50')} stroke="var(--studio-accent)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
                <Line type="linear" dataKey="cumulative_target" name="累計必要額" hide={hidden.has('cumulative_target')} stroke="var(--studio-text-muted)" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />
                {hasIncome && <Line type="linear" dataKey="cumulative_income" name="累計収入" hide={hidden.has('cumulative_income')} stroke="var(--studio-positive)" strokeWidth={2} strokeDasharray="2 4" dot={false} connectNulls isAnimationActive={false} />}
                {hasActual && <Line type="linear" dataKey="actual" name="実績の純資産" hide={hidden.has('actual')} stroke="var(--studio-warning)" strokeWidth={2} dot={{ r: 2 }} connectNulls isAnimationActive={false} />}
                {[...eventMonths].map((x) => <ReferenceLine key={`event-${x}`} x={x} ifOverflow="extendDomain" stroke="var(--studio-border-strong)" strokeDasharray="2 3" />)}
            </ComposedChart>
        </ResponsiveContainer>
    </div>;
}
