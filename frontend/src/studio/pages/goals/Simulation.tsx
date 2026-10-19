import { useCallback, useId, useState, type FormEvent } from 'react';
import { useParams } from 'react-router-dom';
import * as scenariosApi from '../../../api/lifeScenarios';
import type { ContributionPlan, LifeScenario, ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, EditableRow, Feedback, Field, RowTitle } from '../db/Database';
import { buttonClass, inputClass, loadAccounts, primaryClass, useMutation } from '../db/forms';
import ContributionPlanEditor from './ContributionPlanEditor';
import GoalProjectionChart from './GoalProjectionChart';
import ScenarioPreconditions from './ScenarioPreconditions';
import { useScenario } from './scenarioContext';
import { useMakeScenarioGoal } from './useMakeScenarioGoal';

const percent = (value: number | null) => value === null ? '期間外' : `${Math.round(value * 100)}%`;

function Assumptions({ scenario, busy, onSave }: { scenario: LifeScenario; busy: boolean; onSave: (values: scenariosApi.LifeScenarioUpdate) => void }) {
    const form = useId();
    const [years, setYears] = useState(String(scenario.horizon_years));
    const [rate, setRate] = useState(String(scenario.annual_return));
    const [inflation, setInflation] = useState(String(scenario.inflation));
    const [error, setError] = useState('');
    const changed = years !== String(scenario.horizon_years) || rate !== String(scenario.annual_return) || inflation !== String(scenario.inflation);
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const horizon = Number(years);
        if (busy || !changed) return;
        if (!Number.isInteger(horizon) || horizon < 1 || horizon > 60 || !rate.trim() || !inflation.trim() || !Number.isFinite(Number(rate)) || !Number.isFinite(Number(inflation))) {
            setError('期間は1〜60の整数、年利・インフレは数値で入力してください。');
            return;
        }
        setError('');
        onSave({ horizon_years: horizon, annual_return: Number(rate), inflation: Number(inflation) });
    };
    return <form id={form} onSubmit={submit} className="space-y-3">
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid items-end gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="期間（年）"><input type="number" min="1" max="60" step="1" required value={years} onChange={(event) => setYears(event.target.value)} className={inputClass} /></Field>
            <Field label="既定の年利（%）" help="積立設定に年利のない口座の利回りです。"><input inputMode="decimal" required value={rate} onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>
            <Field label="インフレ（%）" help="金額は今日の価値で表します。利回りからインフレを差し引き、積立額は実質で一定とします。"><input inputMode="decimal" required value={inflation} onChange={(event) => setInflation(event.target.value)} className={inputClass} /></Field>
            <div><button type="submit" disabled={busy || !changed} className={primaryClass}>前提を保存</button></div>
        </fieldset>
    </form>;
}

function Results({ projected, currency, currentPeriod }: { projected: ProjectedLifeScenario; currency: string; currentPeriod: string }) {
    const last = projected.projection.at(-1);
    const columns = [...new Set([5, 10, projected.horizon_years])].filter((offset) => offset <= projected.horizon_years);
    const startYear = projected.projection[0]?.year ?? Number(currentPeriod.slice(0, 4));
    return <>
        <dl className="grid gap-4 sm:grid-cols-3">
            {[
                ['今月の積立', formatCurrency(projected.monthly_contribution, currency)],
                [`${last?.year ?? ''}年の純資産（中央値）`, last ? formatCurrency(last.p50, currency) : '—'],
                [`${last?.year ?? ''}年の純資産（P10〜P90）`, last ? `${formatCurrency(last.p10, currency)}〜${formatCurrency(last.p90, currency)}` : '—'],
            ].map(([label, value]) => <div key={label} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
                <dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt>
                <dd className="mt-2 font-semibold tabular-nums">{value}</dd>
            </div>)}
        </dl>
        <div className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
            <GoalProjectionChart scenario={projected} currentPeriod={currentPeriod} currency={currency} />
        </div>
        <section className="space-y-3">
            <h3 className="font-semibold">ライフイベントの達成状況</h3>
            <DataTable columns={['ライフイベント', '日付', '金額', '起きる確率', '資金が足りる確率', '分岐']}>
                {[...projected.events].sort((a, b) => (a.resolved_date ?? '9999').localeCompare(b.resolved_date ?? '9999')).map((event) => <tr key={`event-${event.id}`}>
                    <th scope="row" className="whitespace-nowrap px-5 py-3 font-medium">{event.name}</th>
                    <td className="whitespace-nowrap px-5 py-3">{event.resolved_date ? formatDate(event.resolved_date) : '日付未設定'}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{event.direction === 'income' ? '+' : ''}{formatCurrency(event.target_amount, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{percent(event.executed_probability)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{event.direction === 'income' ? '—' : percent(event.funded_probability)}</td>
                    <td className="whitespace-nowrap px-5 py-3">{event.on_likely_path ? '多くの試行が通る' : '少数'}</td>
                </tr>)}
                {projected.events.length === 0 && <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">ライフイベントはありません。</td></tr>}
            </DataTable>
            <p className="text-xs text-[var(--studio-text-muted)]">起きる確率：前のイベントが起き、前提条件を満たす割合。資金が足りる確率：起きたうえで、その後の純資産が0以上の割合。分岐：過半数の試行で起きるイベントを「多くの試行が通る」とします（構成の図で強調）。</p>
        </section>
        <ScenarioPreconditions events={projected.conditions} currency={currency} />
        <section className="space-y-3">
            <h3 className="font-semibold">口座ごとの見通し（中央値）</h3>
            <DataTable columns={['口座', '現在', ...columns.map((offset) => `${startYear + offset}年`)]}>
                {projected.accounts.map((account) => <tr key={`account-${account.account_id}`}>
                    <th scope="row" className="px-5 py-3 font-medium">{account.name}</th>
                    {[0, ...columns].map((offset) => <td key={offset} className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(account.p50[offset] ?? 0, currency)}</td>)}
                </tr>)}
            </DataTable>
        </section>
    </>;
}

function SimulationForClient({ currency, clientName, scenarioId }: { currency: string; clientName?: string; scenarioId: number }) {
    const confirm = useConfirm();
    const timezone = useTimezone();
    const currentPeriod = clientToday(timezone).slice(0, 7);
    const { reload: reloadLayout } = useScenario();
    const load = useCallback(async () => {
        const [scenarios, comparison, accounts] = await Promise.all([scenariosApi.list(), scenariosApi.compare([scenarioId]), loadAccounts()]);
        const scenario = scenarios.find((row) => row.id === scenarioId);
        if (!scenario) throw new Error('このシナリオは見つかりません。');
        return { scenario, projected: comparison.scenarios[0], accounts };
    }, [scenarioId]);
    const resource = useResource(load);
    const mutation = useMutation();
    const goal = useMakeScenarioGoal(reloadLayout);
    // undefined: closed; null: a new record.
    const [editing, setEditing] = useState<ContributionPlan | null | undefined>(undefined);
    const data = resource.data;
    const disabled = !clientName || mutation.busy || resource.loading || Boolean(resource.error);
    const plans = [...(data?.scenario.contribution_plans ?? [])].sort((a, b) => (a.account_name ?? '').localeCompare(b.account_name ?? '', 'ja') || a.start_period.localeCompare(b.start_period));
    const saveRecord = (action: () => Promise<unknown>, message: string) => { void mutation.run(action, message, () => { setEditing(undefined); resource.reload(); }); };
    const removeRecord = (plan: ContributionPlan) => {
        void (async () => {
            if (await confirm(`「${clientName}」の積立設定（${plan.account_name}・${plan.start_period}〜）を削除します。`, '削除する')) {
                saveRecord(() => scenariosApi.deleteContributionPlan(plan.id), '積立設定を削除しました。');
            }
        })();
    };
    return <section className="space-y-6">
        <Feedback loading={resource.loading && !data} error={resource.error || (editing === undefined ? mutation.error : '') || goal.error} message={mutation.message || goal.message} />
        {goal.dialog}
        {data && <>
            {!data.scenario.is_goal && <div className="flex justify-end">
                <button type="button" disabled={disabled || goal.busy} onClick={() => goal.chooseGoal(data.scenario)} className={buttonClass}>このシナリオをゴールにする</button>
            </div>}
            <section className="space-y-3">
                <h2 className="font-semibold">前提</h2>
                <Assumptions key={`${data.scenario.horizon_years}:${data.scenario.annual_return}:${data.scenario.inflation}`} scenario={data.scenario} busy={disabled}
                    onSave={(values) => saveRecord(() => scenariosApi.update(scenarioId, values), '前提を保存しました。')} />
            </section>
            <section className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <h2 className="font-semibold">積立設定</h2>
                    <button type="button" disabled={disabled} onClick={() => setEditing(null)} className={buttonClass}>レコードを追加</button>
                </div>
                <DataTable columns={['口座', '開始月', '月額', '年利', 'メモ']}>
                    {plans.map((plan) => <EditableRow key={plan.id} disabled={disabled} onEdit={() => setEditing(plan)}>
                        <RowTitle name={`${plan.account_name}（${plan.start_period}〜）`} disabled={disabled} onEdit={() => setEditing(plan)}>{plan.account_name ?? `#${plan.account_id}`}</RowTitle>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{plan.start_period}</td>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(plan.monthly_amount, currency)}</td>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{plan.annual_return === null ? <span className="text-[var(--studio-text-muted)]">引き継ぐ</span> : `${plan.annual_return}%`}</td>
                        <td className="px-5 py-3 text-[var(--studio-text-muted)]">{plan.note ?? ''}</td>
                    </EditableRow>)}
                    {plans.length === 0 && <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">積立設定はありません。口座ごとに、毎月の積立額と年利を追加してください。</td></tr>}
                </DataTable>
                <p className="text-xs text-[var(--studio-text-muted)]">口座ごとに、開始月がその月以前で最も新しいレコードの月額を使います（昇給などで年ごとに変えられます）。</p>
            </section>
            <section className="space-y-4" aria-busy={resource.loading}>
                <h2 className="font-semibold">結果</h2>
                {resource.loading && <p role="status" className="text-xs text-[var(--studio-text-muted)]">試算しています…</p>}
                {data.projected && <Results projected={data.projected} currency={currency} currentPeriod={currentPeriod} />}
            </section>
        </>}
        {editing !== undefined && data && <Overlay title={editing ? '積立設定を編集' : '積立設定を追加'} busy={mutation.busy} onClose={() => setEditing(undefined)}>
            <Feedback error={mutation.error} />
            <ContributionPlanEditor plan={editing} accounts={data.accounts} defaultPeriod={currentPeriod} currency={currency} defaultRate={data.scenario.annual_return} busy={disabled}
                onCancel={() => setEditing(undefined)} onDelete={editing ? () => removeRecord(editing) : undefined}
                onSave={(input) => saveRecord(() => editing ? scenariosApi.updateContributionPlan(editing.id, input) : scenariosApi.createContributionPlan(scenarioId, input), '積立設定を保存しました。')} />
        </Overlay>}
    </section>;
}

export default function Simulation() {
    const { clientId, currentClient } = useClient();
    const { scenarioId = '' } = useParams();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <SimulationForClient key={`${clientId}:${currency}:${scenarioId}`} scenarioId={Number(scenarioId)} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
