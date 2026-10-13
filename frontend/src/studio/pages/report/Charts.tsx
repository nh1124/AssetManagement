import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { formatCurrency } from '../../../utils/currency';

const tooltipStyle = { background: 'var(--studio-surface)', border: '1px solid var(--studio-border)', color: 'var(--studio-text)' };
const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };

export function MoneyLineChart({ rows, currency, label, axisLabel }: {
    rows: Array<{ label: string; amount: number }>; currency: string; label: string; axisLabel: string;
}) {
    return <div role="img" aria-label={`${label}の推移。横軸：${axisLabel}、縦軸：金額（${currency}）`} className="h-80 min-w-0">
        {/* A single solid series keeps changes readable without suggesting extra measures. */}
        <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 20, right: 20, bottom: 28, left: 20 }} accessibilityLayer>
                <CartesianGrid stroke="var(--studio-border)" vertical={false} />
                <XAxis dataKey="label" tick={axisStyle} minTickGap={30} label={{ value: axisLabel, position: 'bottom', fill: 'var(--studio-text-muted)', fontSize: 12 }} />
                <YAxis width={105} tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'top', fill: 'var(--studio-text-muted)', fontSize: 12 }} />
                <Tooltip contentStyle={tooltipStyle} formatter={(value) => [formatCurrency(Number(value), currency), label]} />
                <Line type="linear" dataKey="amount" name={label} stroke="var(--studio-accent)" strokeWidth={2} dot={rows.length <= 12} activeDot={{ r: 4 }} isAnimationActive={false} />
            </LineChart>
        </ResponsiveContainer>
    </div>;
}

export function ComparisonChart({ rows, currency }: {
    rows: Array<{ category: string; budget: number; actual: number }>; currency: string;
}) {
    return <div role="img" aria-label={`分類ごとの計画と実績。横軸：金額（${currency}）、縦軸：分類`} style={{ height: Math.max(240, rows.length * 52 + 90) }}>
        <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ top: 12, right: 20, bottom: 24, left: 10 }} accessibilityLayer>
                <CartesianGrid stroke="var(--studio-border)" horizontal={false} />
                <XAxis type="number" tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'bottom', fill: 'var(--studio-text-muted)', fontSize: 12 }} />
                <YAxis type="category" dataKey="category" width={120} tick={axisStyle} interval={0} />
                <Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [formatCurrency(Number(value), currency), name]} />
                <Legend verticalAlign="top" />
                <Bar dataKey="budget" name="計画" fill="var(--studio-text-faint)" isAnimationActive={false} />
                <Bar dataKey="actual" name="実績" fill="var(--studio-accent)" isAnimationActive={false} />
            </BarChart>
        </ResponsiveContainer>
    </div>;
}
