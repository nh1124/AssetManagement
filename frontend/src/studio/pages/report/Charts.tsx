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
    return <div role="region" aria-label="予算と支出のグラフ" tabIndex={0} className="max-h-[32rem] overflow-auto overscroll-contain rounded focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">
        {/* Preserve space for every item instead of compressing or dropping bars in long budgets. */}
        <div role="img" aria-label={`分類ごとの予算と支出。横軸：金額（${currency}）、縦軸：分類`} className="min-w-[36rem]" style={{ height: Math.max(240, rows.length * 60 + 90) }}>
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} layout="vertical" margin={{ top: 12, right: 20, bottom: 24, left: 10 }} accessibilityLayer>
                    <CartesianGrid stroke="var(--studio-border)" horizontal={false} />
                    <XAxis type="number" tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'bottom', fill: 'var(--studio-text-muted)', fontSize: 12 }} />
                    <YAxis type="category" dataKey="category" width={120} tick={axisStyle} interval={0} />
                    <Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [formatCurrency(Number(value), currency), name]} />
                    <Legend verticalAlign="top" />
                    <Bar dataKey="budget" name="予算" fill="var(--studio-budget)" isAnimationActive={false} />
                    <Bar dataKey="actual" name="支出" fill="var(--studio-expense)" isAnimationActive={false} />
                </BarChart>
            </ResponsiveContainer>
        </div>
    </div>;
}
