import { useCallback, useState } from 'react';
import { CalendarPlus, Pencil, Target } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getLifeEventsWithProgress, getNetWorthHistory } from '../../../api';
import { planCheck } from '../../../api/goalPlan';
import { compare, list } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Help } from '../db/Database';
import { buttonClass, primaryClass } from '../db/forms';
import { eventAmount, KIND_LABELS } from './eventKinds';
import ReflectionOverlay from '../plan/ReflectionOverlay';
import GoalProjectionChart from './GoalProjectionChart';
import NoLifeEvents from './NoLifeEvents';
import { tr } from '../../i18n';

const percent = (value: number | null | undefined) => value == null ? '—' : `${Math.round(value * 100)}%`;

function SummaryForClient({ currency }: { currency: string }) {
    const timezone = useTimezone();
    const period = clientToday(timezone).slice(0, 7);
    const load = useCallback(async () => {
        const scenarios = await list();
        const goal = scenarios.find((scenario) => scenario.is_goal);
        if (!goal) return { scenarios, goal: null };
        const [comparison, events, history, check] = await Promise.all([
            compare([goal.id]), getLifeEventsWithProgress(), getNetWorthHistory(60), planCheck(period),
        ]);
        return { scenarios, goal: { projected: comparison.scenarios[0], events, history, check } };
    }, [period]);
    const resource = useResource(load);
    const [planning, setPlanning] = useState(false);
    const { clientId, currentClient } = useClient();
    const clientName = currentClient && currentClient.id === clientId ? currentClient.name : undefined;
    const data = resource.data;
    const goal = data?.goal;
    const expenses = goal?.events.filter((event) => event.direction === 'expense') ?? [];
    const required = expenses.reduce((total, event) => total + event.target_amount, 0);
    const funded = expenses.reduce((total, event) => total + event.current_funded, 0);
    const outcomes = new Map(goal?.projected.events.map((event) => [event.id, event]));
    const disabled = resource.loading;
    return <section className="space-y-5">
        <Feedback loading={resource.loading && !data} error={resource.error} />
        {data && !goal && (data.scenarios.length === 0 ? <NoLifeEvents noScenarios />
            : <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                <h2 className="font-semibold">{tr('ゴールにするシナリオが選ばれていません', 'No scenario is chosen as the goal')}</h2>
                <div className="flex justify-end"><Link to="/goals/scenarios" className={primaryClass}>{tr('シナリオ一覧で選ぶ', 'Choose from scenarios')}</Link></div>
            </div>)}
        {goal && <>
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="flex items-center gap-2 font-semibold"><Target size={18} aria-label={tr('ゴール', 'Goal')} />{goal.projected.name}</h2>
                <div className="flex flex-wrap items-center gap-2">
                    <button type="button" disabled={disabled} onClick={() => setPlanning(true)} className={`inline-flex items-center gap-2 ${buttonClass}`}><CalendarPlus size={14} aria-hidden="true" />{tr('計画への反映', 'Plan reflection')}</button>
                    <Link to="/goals/scenarios" className={`inline-flex items-center gap-2 ${buttonClass}`}><Pencil size={14} aria-hidden="true" />{tr('編集する', 'Edit')}</Link>
                </div>
            </div>
            {goal.events.length === 0 && <NoLifeEvents />}
            <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {[
                    [tr('必要額', 'Needed'), formatCurrency(required, currency), null],
                    [tr('確保額', 'Set aside'), formatCurrency(funded, currency), null],
                    [tr('不足', 'Short'), formatCurrency(Math.max(0, required - funded), currency), null],
                    [tr('今月の積立', 'Saving this month'), formatCurrency(goal.projected.monthly_contribution, currency),
                        goal.check.goal ? tr(`${goal.check.contribution === goal.projected.monthly_contribution ? '' : `積立設定（振替・取り崩しを含む）${formatCurrency(goal.check.contribution, currency)} ／ `}今月の計画 ${formatCurrency(goal.check.planned, currency)}（差 ${goal.check.difference >= 0 ? '+' : ''}${formatCurrency(goal.check.difference, currency)}）`,
                            `${goal.check.contribution === goal.projected.monthly_contribution ? '' : `Contribution settings (transfers and drawdowns included) ${formatCurrency(goal.check.contribution, currency)} / `}planned this month ${formatCurrency(goal.check.planned, currency)} (${goal.check.difference >= 0 ? '+' : ''}${formatCurrency(goal.check.difference, currency)})`) : null],
                ].map(([label, value, note]) => <div key={label} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
                    <dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt>
                    <dd className="mt-2 font-semibold tabular-nums">{value}</dd>
                    {note && <dd className="mt-1 text-xs tabular-nums text-[var(--studio-text-muted)]">{note}</dd>}
                </div>)}
            </dl>
            <div className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                <GoalProjectionChart scenario={goal.projected} history={goal.history} currentPeriod={period} currency={currency} />
                <p className="mt-3 flex items-center gap-1.5 text-xs text-[var(--studio-text-muted)]">{tr(`期間 ${goal.projected.horizon_years}年 ／ 既定の年利 ${goal.projected.annual_return}% ／ インフレ ${goal.projected.inflation}%`, `${goal.projected.horizon_years} years / default return ${goal.projected.annual_return}% / inflation ${goal.projected.inflation}%`)}<Help label={tr('グラフ', 'Chart')} text={tr('凡例を選ぶと表示を切り替えます。', 'Choose a legend entry to show or hide it.')} /></p>
            </div>
            <section className="space-y-3">
                <h3 className="flex items-center gap-1.5 font-semibold">{tr('ライフイベント', 'Life events')}<Help label={tr('ライフイベント', 'Life events')} text={tr('支出のライフイベントは、シミュレーションの積立設定に「ライフイベントへの取り崩し」（1回、または毎月・毎年など）を記録しておくと、「計画を作成」でイベントと同じ名前の取り置き（ゴール）ができ、最初に取り崩す月まで口座ごとに積み立てます。その確保額を確保額・進捗に数えます。', 'For a spending life event, record a “Drawdown for a life event” (once, or monthly, yearly and so on) in the simulation’s contribution settings. Making the plan then creates an earmark (a goal) named after the event and saves into it account by account until the first drawdown. What it holds counts as set aside and as progress.')} wide /></h3>
                <DataTable columns={[tr('名称', 'Name'), tr('目標日', 'Target date'), tr('金額', 'Amount'), tr('取り置き', 'Earmark'), tr('確保額', 'Set aside'), tr('進捗', 'Progress'), tr('起きる確率', 'Chance it happens'), tr('資金が足りる確率', 'Chance it is funded')]}>
                    {goal.events.map((event) => {
                        const outcome = outcomes.get(event.id);
                        const expense = event.direction === 'expense';
                        return <tr key={`event-${event.id}`}>
                            <th scope="row" className="whitespace-nowrap px-5 py-3 font-medium">{event.name}{!expense && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">{KIND_LABELS[event.direction]}</span>}</th>
                            <td className="whitespace-nowrap px-5 py-3">{formatDate(event.target_date)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{eventAmount(event, currency)}</td>
                            <td className="whitespace-nowrap px-5 py-3">{!expense ? '—' : event.earmark ? event.earmark.capsule_name : event.withdrawals.length ? <span className="text-xs text-[var(--studio-text-muted)]">{tr('計画の作成で作ります', 'Made when the plan is made')}</span> : <span className="text-xs text-[var(--studio-text-muted)]">{tr('口座なし', 'No account')}</span>}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{expense ? formatCurrency(event.current_funded, currency) : '—'}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{expense ? `${event.progress_percentage}%` : '—'}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{percent(outcome?.executed_probability)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{expense ? percent(outcome?.funded_probability) : '—'}</td>
                        </tr>;
                    })}
                </DataTable>
            </section>
        </>}
        {planning && <ReflectionOverlay clientName={clientName} currency={currency} onClose={(changed) => { setPlanning(false); if (changed) resource.reload(); }} />}
    </section>;
}

export default function GoalSummary() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <SummaryForClient key={`${clientId}:${currency}`} currency={currency} />;
}
