import { useCallback } from 'react';
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { runMonteCarloSimulation } from '../../../api';
import type { LifeEvent, Milestone, RoadmapProjection } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import { buttonClass } from '../db/forms';
import { projectionRows } from './projection';
import { goalPercent } from './presentation';

export default function GoalProjection({ goal, roadmap, currency, monteCarlo }: {
    goal: LifeEvent; roadmap: RoadmapProjection; currency: string; monteCarlo: boolean;
}) {
    const timezone = useTimezone();
    const { annual_return, inflation, monthly_savings } = roadmap.params;
    const load = useCallback(() => monteCarlo ? runMonteCarloSimulation(goal.id, 1000, {
        annual_return, inflation, monthly_savings: monthly_savings ?? 50000, allocation_mode: 'weighted',
    }) : Promise.resolve(null), [goal.id, monteCarlo, annual_return, inflation, monthly_savings]);
    const resource = useResource(load);
    const milestones: Milestone[] = roadmap.milestones.filter((row) => row.life_event_id === goal.id);
    const rows = projectionRows(goal, milestones, roadmap.params.reference_date || clientToday(timezone), resource.data);
    const axisStyle = { fill: 'var(--studio-text-muted)', fontSize: 11 };
    return <div className="space-y-3">
        <p className="text-xs text-[var(--studio-text-muted)]">年利 {annual_return}% ／ インフレ {inflation}% ／ 全ゴールの月額積立 {formatCurrency(monthly_savings ?? 50000, currency)}（{currency}）を優先度で配分。通常試算は一定利回り、モンテカルロはインフレを差し引いた利回りの分布です。</p>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.error && <button type="button" onClick={resource.reload} className={buttonClass}>再試算</button>}
        {!resource.loading && !resource.error && <>
            {resource.data && <p className="text-sm">目標額の達成確率：{goalPercent(resource.data.probability)} ／ {resource.data.n_simulations.toLocaleString()}回の試算</p>}
            <div role="img" aria-label={`${goal.name}の将来残高と採用中の計画。横軸：日付、縦軸：金額（${currency}）${monteCarlo ? '。P10・P50・P90の分布' : ''}`} className="h-80 min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={rows} margin={{ top: 20, right: 20, bottom: 28, left: 20 }} accessibilityLayer>
                        <CartesianGrid stroke="var(--studio-border)" vertical={false} />
                        <XAxis dataKey="date" type="number" domain={['dataMin', 'dataMax']} tick={axisStyle} minTickGap={30} tickFormatter={(value: number) => formatDate(value)} label={{ value: '日付', position: 'bottom', ...axisStyle }} />
                        <YAxis width={105} tick={axisStyle} tickFormatter={(value: number) => formatCurrency(value, currency)} label={{ value: `金額（${currency}）`, position: 'top', ...axisStyle }} />
                        <Tooltip contentStyle={{ background: 'var(--studio-surface)', border: '1px solid var(--studio-border)', color: 'var(--studio-text)' }} labelFormatter={(value) => formatDate(Number(value))} formatter={(value, name) => [formatCurrency(Number(value), currency), name]} />
                        <Legend verticalAlign="top" />
                        {monteCarlo ? <>
                            <Area type="linear" dataKey="band" name="P10〜P90" stroke="none" fill="var(--studio-accent-soft)" fillOpacity={1} legendType="none" tooltipType="none" isAnimationActive={false} />
                            <Line type="linear" dataKey="p10" name="下位10%（P10）" stroke="var(--studio-warning)" strokeWidth={2} dot={false} isAnimationActive={false} />
                            <Line type="linear" dataKey="p50" name="中央値（P50）" stroke="var(--studio-accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
                            <Line type="linear" dataKey="p90" name="上位10%（P90）" stroke="var(--studio-positive)" strokeWidth={2} dot={false} isAnimationActive={false} />
                        </> : <Line type="linear" dataKey="projection" name="通常試算" stroke="var(--studio-accent)" strokeWidth={2} dot={false} isAnimationActive={false} />}
                        {rows.some((row) => row.plan !== undefined) && <Line type="linear" dataKey="plan" name="採用中の計画" stroke="var(--studio-text-muted)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />}
                    </ComposedChart>
                </ResponsiveContainer>
            </div>
            {goal.target_date <= clientToday(timezone) && <p className="text-xs text-[var(--studio-text-muted)]">目標日を迎えたゴールです。現在の確保額を表示しています。</p>}
        </>}
    </div>;
}
