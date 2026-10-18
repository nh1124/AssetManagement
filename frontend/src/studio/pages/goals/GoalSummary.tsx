import { useCallback, useState } from 'react';
import { Pencil, Wallet } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getLifeEventsWithProgress } from '../../../api';
import { getGoalBudgetStatus } from '../../../api/goalBudget';
import { compare, list, type ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { clientToday, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import { buttonClass, primaryClass } from '../db/forms';
import GoalBaselinePanel from './GoalBaselinePanel';
import GoalReflectionNotice from './GoalReflectionNotice';
import GoalSavingsBreakdown from './GoalSavingsBreakdown';
import GoalBudgetReflection from './GoalBudgetReflection';
import NoLifeEvents from './NoLifeEvents';

function Projection({ scenario, currency }: { scenario: ProjectedLifeScenario; currency: string }) {
    const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };
    const rows = scenario.projection.map((row) => ({ ...row, band: [row.p10, row.p90] }));
    const eventNames = new Map<number, string[]>();
    for (const event of scenario.events) {
        if (!event.resolved_date) continue;
        const year = Number(event.resolved_date.slice(0, 4));
        eventNames.set(year, [...(eventNames.get(year) ?? []), event.name]);
    }
    const hasIncome = scenario.events.some((event) => event.direction === 'income');
    return <div className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <div role="img" aria-label={`ゴールシナリオの純資産推移。横軸：年、縦軸：金額（${currency}）。P10〜P90、P50、累計必要額${hasIncome ? '、累計収入' : ''}とライフイベントの予定年`} className="h-96 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={rows} margin={{ top: 40, right: 30, bottom: 28, left: 20 }} accessibilityLayer>
                    <CartesianGrid stroke="var(--studio-border)" vertical={false} />
                    <XAxis type="number" domain={['dataMin', 'dataMax']} dataKey="year" allowDecimals={false} tick={axisStyle} minTickGap={30} label={{ value: '年', position: 'bottom', ...axisStyle }} />
                    <YAxis width={105} tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'top', ...axisStyle }} />
                    <Tooltip contentStyle={{ background: 'var(--studio-surface)', border: '1px solid var(--studio-border)', color: 'var(--studio-text)' }} formatter={(value, name) => [Array.isArray(value) ? value.map((amount) => formatCurrency(Number(amount), currency)).join('〜') : formatCurrency(Number(value), currency), name]} />
                    <Legend verticalAlign="top" />
                    <Area type="linear" dataKey="band" name="P10〜P90" stroke="none" fill="var(--studio-accent)" fillOpacity={0.15} isAnimationActive={false} />
                    <Line type="linear" dataKey="p50" name="中央値（P50）" stroke="var(--studio-accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
                    <Line type="linear" dataKey="cumulative_target" name="累計必要額" stroke="var(--studio-text-muted)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                    {hasIncome && <Line type="linear" dataKey="cumulative_income" name="累計収入" stroke="var(--studio-positive)" strokeWidth={2} strokeDasharray="2 4" dot={false} isAnimationActive={false} />}
                    {[...eventNames].map(([year, names]) => <ReferenceLine key={`event-year-${year}`} x={year} ifOverflow="extendDomain" stroke="var(--studio-border-strong)" label={{ value: names.join('・'), position: 'insideTop', fill: 'var(--studio-text-muted)', fontSize: 11 }} />)}
                </ComposedChart>
            </ResponsiveContainer>
        </div>
        <p className="mt-3 text-xs text-[var(--studio-text-muted)]">期間 {scenario.horizon_years}年 ／ 年利 {scenario.annual_return}% ／ インフレ {scenario.inflation}% ／ 月の積立 {formatCurrency(scenario.monthly_savings, currency)}</p>
    </div>;
}

function ScenarioSummary({ scenario, events, currency }: { scenario: ProjectedLifeScenario; events: LifeEvent[]; currency: string }) {
    const [reflecting, setReflecting] = useState(false);
    // A reflection changes the breakdown and may move the baseline; reload both after it.
    const [version, setVersion] = useState(0);
    const timezone = useTimezone();
    const period = clientToday(timezone).slice(0, 7);
    // The status feeds the breakdown; the reminders are the goal-reflection notification.
    const loadStatus = useCallback(() => getGoalBudgetStatus(period), [period]);
    const status = useResource(loadStatus);
    const progress = new Map(events.map((event) => [event.id, event.current_funded ?? 0]));
    // Income events are inflows, not funding needs; keep them in the chart and table only.
    const expenses = scenario.events.filter((event) => event.direction === 'expense');
    const required = expenses.reduce((total, event) => total + event.target_amount, 0);
    // Only claims belonging to this branch count; missing progress contributes zero.
    const funded = expenses.reduce((total, event) => total + (progress.get(event.id) ?? 0), 0);
    const budget = status.data?.goal ? status.data : null;
    return <>
        <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold">{scenario.name}</h2>
            <div className="flex flex-wrap items-center gap-2">
                <Link to={`/goals/scenarios/${scenario.id}/events`} className={`inline-flex items-center gap-2 ${buttonClass}`}><Pencil size={14} aria-hidden="true" />編集する</Link>
                <button type="button" onClick={() => setReflecting(true)} className={`inline-flex items-center gap-2 ${buttonClass}`}><Wallet size={14} aria-hidden="true" />予算に反映</button>
            </div>
        </div>
        <GoalReflectionNotice />
        {reflecting && <GoalBudgetReflection onClose={() => { setReflecting(false); setVersion((value) => value + 1); status.reload(); }} />}
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
                ['必要額', formatCurrency(required, currency), null],
                ['確保額', formatCurrency(funded, currency), null],
                ['不足', formatCurrency(Math.max(0, required - funded), currency), null],
                ['毎月の積立', formatCurrency(scenario.monthly_savings, currency),
                    budget?.budget ? `今月の予算 ${formatCurrency(budget.budget.total, currency)}（差 ${budget.budget.difference >= 0 ? '+' : ''}${formatCurrency(budget.budget.difference, currency)}）` : null],
            ].map(([label, value, note]) => <div key={label} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
                <dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt>
                <dd className="mt-2 font-semibold tabular-nums">{value}</dd>
                {note && <dd className="mt-1 text-xs text-[var(--studio-text-muted)] tabular-nums">{note}</dd>}
            </div>)}
        </dl>
        <Projection scenario={scenario} currency={currency} />
        <Feedback error={status.error} />
        <GoalSavingsBreakdown scenario={scenario} funded={progress} budget={budget} currency={currency} />
        <GoalBaselinePanel key={`baseline-${version}`} currency={currency} />
    </>;
}

function SummaryForClient({ currency }: { currency: string }) {
    const load = useCallback(async () => {
        const [scenarios, events] = await Promise.all([list(), getLifeEventsWithProgress(false)]);
        const goal = scenarios.find((scenario) => scenario.is_goal);
        const scenario = goal ? (await compare([goal.id])).scenarios.find((item) => item.id === goal.id) : undefined;
        return { scenarios, scenario, events };
    }, []);
    const resource = useResource(load);
    const data = resource.data;
    const scenario = data?.scenario;
    // The graph contract expresses every event in one client currency; never combine currencies.
    const scenarioCurrency = scenario?.events[0]?.currency ?? currency;
    const mixedCurrencies = scenario?.events.some((event) => event.currency !== scenarioCurrency);
    return <section className="space-y-5">
        <Feedback loading={resource.loading} error={resource.error} />
        {data && !resource.loading && !resource.error && (
            data.scenarios.length === 0 ? <NoLifeEvents noScenarios />
                : data.events.length === 0 && data.scenarios.every((item) => item.events.length === 0) ? <NoLifeEvents />
                : !scenario ? <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                    <h2 className="font-semibold">ゴールにするシナリオが選ばれていません</h2>
                    <div className="flex justify-end"><Link to="/goals/scenarios" className={primaryClass}>シナリオ一覧で選ぶ</Link></div>
                </div>
                    : mixedCurrencies ? <Feedback error="ゴールシナリオの通貨が一致しないため集計できません。" />
                        : <ScenarioSummary scenario={scenario} events={data.events} currency={scenarioCurrency} />
        )}
    </section>;
}

export default function GoalSummary() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <SummaryForClient key={`${clientId}:${currency}`} currency={currency} />;
}
