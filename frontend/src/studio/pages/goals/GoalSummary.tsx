import { useCallback, useState } from 'react';
import { CalendarPlus, Flag, Pencil } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getCapsules, getLifeEventsWithProgress, getNetWorthHistory } from '../../../api';
import { planCheck } from '../../../api/goalPlan';
import { compare, list } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import type { LifeEventProgress } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, EditableRow, Feedback, RowTitle } from '../db/Database';
import { buttonClass, primaryClass, useMutation } from '../db/forms';
import GoalEarmarkEditor from './GoalEarmarkEditor';
import GoalPlanDialog from './GoalPlanDialog';
import GoalProjectionChart from './GoalProjectionChart';
import NoLifeEvents from './NoLifeEvents';

const percent = (value: number | null | undefined) => value == null ? '—' : `${Math.round(value * 100)}%`;

function SummaryForClient({ currency }: { currency: string }) {
    const timezone = useTimezone();
    const period = clientToday(timezone).slice(0, 7);
    const load = useCallback(async () => {
        const scenarios = await list();
        const goal = scenarios.find((scenario) => scenario.is_goal);
        if (!goal) return { scenarios, goal: null };
        const [comparison, events, history, check, capsules] = await Promise.all([
            compare([goal.id]), getLifeEventsWithProgress(), getNetWorthHistory(60), planCheck(period), getCapsules(),
        ]);
        return { scenarios, goal: { projected: comparison.scenarios[0], events, history, check, capsules } };
    }, [period]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [planning, setPlanning] = useState(false);
    const [linking, setLinking] = useState<LifeEventProgress | null>(null);
    const data = resource.data;
    const goal = data?.goal;
    const expenses = goal?.events.filter((event) => event.direction === 'expense') ?? [];
    const required = expenses.reduce((total, event) => total + event.target_amount, 0);
    const funded = expenses.reduce((total, event) => total + event.current_funded, 0);
    const outcomes = new Map(goal?.projected.events.map((event) => [event.id, event]));
    // One earmark can be split across events; more than all of it would count money twice.
    const shares = new Map<string, number>();
    for (const event of expenses) for (const link of event.earmarks) shares.set(link.capsule_name ?? `#${link.capsule_id}`, (shares.get(link.capsule_name ?? `#${link.capsule_id}`) ?? 0) + link.share);
    const overShared = [...shares].filter(([, share]) => share > 100).map(([name]) => name);
    const disabled = resource.loading || mutation.busy;
    return <section className="space-y-5">
        <Feedback loading={resource.loading && !data} error={resource.error} message={mutation.message} />
        {data && !goal && (data.scenarios.length === 0 ? <NoLifeEvents noScenarios />
            : <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                <h2 className="font-semibold">ゴールにするシナリオが選ばれていません</h2>
                <div className="flex justify-end"><Link to="/goals/scenarios" className={primaryClass}>シナリオ一覧で選ぶ</Link></div>
            </div>)}
        {goal && <>
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="flex items-center gap-2 font-semibold"><Flag size={18} aria-label="ゴール" />{goal.projected.name}</h2>
                <div className="flex flex-wrap items-center gap-2">
                    <button type="button" disabled={disabled} onClick={() => setPlanning(true)} className={`inline-flex items-center gap-2 ${buttonClass}`}><CalendarPlus size={14} aria-hidden="true" />計画を作成</button>
                    <Link to="/goals/scenarios" className={`inline-flex items-center gap-2 ${buttonClass}`}><Pencil size={14} aria-hidden="true" />編集する</Link>
                </div>
            </div>
            {goal.events.length === 0 && <NoLifeEvents />}
            <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {[
                    ['必要額', formatCurrency(required, currency), null],
                    ['確保額', formatCurrency(funded, currency), null],
                    ['不足', formatCurrency(Math.max(0, required - funded), currency), null],
                    ['毎月の積立', formatCurrency(goal.projected.monthly_contribution, currency),
                        goal.check.goal ? `今月の計画 ${formatCurrency(goal.check.planned, currency)}（差 ${goal.check.difference >= 0 ? '+' : ''}${formatCurrency(goal.check.difference, currency)}）` : null],
                ].map(([label, value, note]) => <div key={label} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
                    <dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt>
                    <dd className="mt-2 font-semibold tabular-nums">{value}</dd>
                    {note && <dd className="mt-1 text-xs tabular-nums text-[var(--studio-text-muted)]">{note}</dd>}
                </div>)}
            </dl>
            <div className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                <GoalProjectionChart scenario={goal.projected} history={goal.history} currentPeriod={period} currency={currency} />
                <p className="mt-3 text-xs text-[var(--studio-text-muted)]">期間 {goal.projected.horizon_years}年 ／ 既定の年利 {goal.projected.annual_return}% ／ インフレ {goal.projected.inflation}%。凡例を選ぶと表示を切り替えます。</p>
            </div>
            <section className="space-y-3">
                <h3 className="font-semibold">ライフイベント</h3>
                <DataTable columns={['名称', '目標日', '目標額', '確保額', '進捗', '起きる確率', '資金が足りる確率']}>
                    {goal.events.map((event) => {
                        const outcome = outcomes.get(event.id);
                        const expense = event.direction === 'expense';
                        return <tr key={`event-${event.id}`}>
                            <th scope="row" className="whitespace-nowrap px-5 py-3 font-medium">{event.name}{!expense && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">収入</span>}</th>
                            <td className="whitespace-nowrap px-5 py-3">{formatDate(event.target_date)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(event.target_amount, currency)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{expense ? formatCurrency(event.current_funded, currency) : '—'}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{expense ? `${event.progress_percentage}%` : '—'}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{percent(outcome?.executed_probability)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{expense ? percent(outcome?.funded_probability) : '—'}</td>
                        </tr>;
                    })}
                </DataTable>
            </section>
            <section className="space-y-3">
                <h3 className="font-semibold">実績管理の設定</h3>
                <p className="text-xs text-[var(--studio-text-muted)]">ゴールのライフイベントごとに、確保額として数える取り置きと割合を決めます。確保額・不足と、ゴールから作る計画の取り置きの月額に使います。</p>
                {overShared.length > 0 && <p role="alert" className="text-sm text-[var(--studio-warning)]">割合の合計が100%を超えている取り置きがあります：{overShared.join('、')}</p>}
                <DataTable columns={['ライフイベント', '取り置き（割合）', '確保額', '不足']}>
                    {expenses.map((event) => <EditableRow key={`link-${event.id}`} disabled={disabled} onEdit={() => setLinking(event)}>
                        <RowTitle name={`${event.name}の実績管理の設定`} disabled={disabled} onEdit={() => setLinking(event)}>{event.name}</RowTitle>
                        <td className="px-5 py-3">{event.earmarks.length ? event.earmarks.map((link) => `${link.capsule_name}（${link.share}%）`).join('、') : <span className="text-[var(--studio-text-muted)]">未設定</span>}</td>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(event.current_funded, currency)}</td>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(event.gap, currency)}</td>
                    </EditableRow>)}
                    {expenses.length === 0 && <tr><td colSpan={4} className="px-5 py-4 text-[var(--studio-text-muted)]">支出のライフイベントはありません。</td></tr>}
                </DataTable>
            </section>
        </>}
        {planning && <GoalPlanDialog onClose={(applied) => { setPlanning(false); if (applied) resource.reload(); }} />}
        {linking && goal && <Overlay title={`「${linking.name}」の実績管理の設定`} busy={mutation.busy} onClose={() => setLinking(null)}>
            <Feedback error={mutation.error} />
            <GoalEarmarkEditor event={linking} capsules={goal.capsules} currency={currency} busy={mutation.busy} onCancel={() => setLinking(null)}
                onSave={(action) => { void mutation.run(action, '実績管理の設定を保存しました。', () => { setLinking(null); resource.reload(); }); }} />
        </Overlay>}
    </section>;
}

export default function GoalSummary() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <SummaryForClient key={`${clientId}:${currency}`} currency={currency} />;
}
