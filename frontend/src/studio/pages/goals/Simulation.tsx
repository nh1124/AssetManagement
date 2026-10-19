import { useCallback, useId, useState, type FormEvent, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { getLifeEvents } from '../../../api';
import { getLifeEventLinks } from '../../../api/lifeEventGraph';
import * as scenariosApi from '../../../api/lifeScenarios';
import type { ContributionPlan, LifeScenario, ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, loadAccounts, primaryClass, useMutation } from '../db/forms';
import type { LifeEventLink } from '../../../api/lifeEventGraph';
import ContributionPlanEditor from './ContributionPlanEditor';
import { eventAmount, KIND_LABELS } from './eventKinds';
import GoalProjectionChart from './GoalProjectionChart';
import LifeEventDiagram from './LifeEventDiagram';
import ScenarioPreconditions from './ScenarioPreconditions';
import { useScenario } from './scenarioContext';
import { useMakeScenarioGoal } from './useMakeScenarioGoal';

const percent = (value: number | null) => value === null ? '期間外' : `${Math.round(value * 100)}%`;
const noop = () => undefined;

/** One of the two halves of the screen: what is set, and what follows from it. */
function Panel({ title, note, action, children }: { title: string; note: string; action?: ReactNode; children: ReactNode }) {
    return <section className="space-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--studio-border)] pb-3">
            <div><h2 className="font-semibold">{title}</h2><p className="mt-1 text-xs text-[var(--studio-text-muted)]">{note}</p></div>
            {action}
        </div>
        {children}
    </section>;
}

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
            <Field label="インフレ（%）" help="金額は今日の価値で表します。利回りからインフレを差し引き、積立額・借入・返済は実質で一定とします。"><input inputMode="decimal" required value={inflation} onChange={(event) => setInflation(event.target.value)} className={inputClass} /></Field>
            <div><button type="submit" disabled={busy || !changed} className={primaryClass}>前提を保存</button></div>
        </fieldset>
    </form>;
}

/** 使用口座と積立設定: each used account with its records, newest month last. */
function UsedAccounts({ plans, currency, disabled, onEdit }: { plans: ContributionPlan[]; currency: string; disabled: boolean; onEdit: (plan: ContributionPlan) => void }) {
    const groups = new Map<number, ContributionPlan[]>();
    for (const plan of [...plans].sort((a, b) => (a.account_name ?? '').localeCompare(b.account_name ?? '', 'ja') || a.start_period.localeCompare(b.start_period))) {
        groups.set(plan.account_id, [...(groups.get(plan.account_id) ?? []), plan]);
    }
    if (!groups.size) return <p className="rounded-md border border-dashed border-[var(--studio-border)] p-4 text-sm text-[var(--studio-text-muted)]">使用口座がありません。「レコードを追加」で口座ごとの毎月の積立（または取り崩し）と年利を追加してください。</p>;
    return <div className="space-y-3">{[...groups].map(([accountId, rows]) => <div key={accountId} className="overflow-hidden rounded-md border border-[var(--studio-border)]">
        <h4 className="bg-[var(--studio-bg)] px-4 py-2 text-sm font-medium">{rows[0].account_name ?? `#${accountId}`}</h4>
        <table className="w-full table-fixed text-left text-sm">
            <colgroup><col className="w-32" /><col className="w-48" /><col className="w-28" /><col /></colgroup>
            <thead className="text-xs text-[var(--studio-text-muted)]"><tr>{['開始月', '毎月', '年利', 'メモ'].map((label) => <th key={label} scope="col" className="px-4 py-2 font-medium">{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">{rows.map((plan) => <tr key={plan.id} onClick={() => { if (!disabled) onEdit(plan); }} className={disabled ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)]'}>
                <th scope="row" className="px-4 py-2 font-normal"><button type="button" disabled={disabled} aria-haspopup="dialog" aria-label={`${plan.account_name}（${plan.start_period}〜）を編集`} onClick={(event) => { event.stopPropagation(); onEdit(plan); }} className="rounded tabular-nums hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{plan.start_period}〜</button></th>
                <td className="px-4 py-2 tabular-nums">{plan.monthly_amount < 0 ? `取り崩し ${formatCurrency(-plan.monthly_amount, currency)}` : `積立 ${formatCurrency(plan.monthly_amount, currency)}`}</td>
                <td className="px-4 py-2 tabular-nums">{plan.annual_return === null ? <span className="text-[var(--studio-text-muted)]">引き継ぐ</span> : `${plan.annual_return}%`}</td>
                <td className="px-4 py-2 text-[var(--studio-text-muted)]">{plan.note ?? ''}</td>
            </tr>)}</tbody>
        </table>
    </div>)}</div>;
}

function Results({ projected, events, links, currency, currentPeriod }: {
    projected: ProjectedLifeScenario; events: LifeEvent[]; links: LifeEventLink[]; currency: string; currentPeriod: string;
}) {
    const last = projected.projection.at(-1);
    const columns = [...new Set([5, 10, projected.horizon_years])].filter((offset) => offset <= projected.horizon_years);
    const startYear = projected.projection[0]?.year ?? Number(currentPeriod.slice(0, 4));
    return <>
        <dl className="grid gap-4 sm:grid-cols-3">
            {[
                ['今月の積立', formatCurrency(projected.monthly_contribution, currency)],
                [`${last?.year ?? ''}年の純資産（中央値）`, last ? formatCurrency(last.p50, currency) : '—'],
                [`${last?.year ?? ''}年の純資産（P10〜P90）`, last ? `${formatCurrency(last.p10, currency)}〜${formatCurrency(last.p90, currency)}` : '—'],
            ].map(([label, value]) => <div key={label} className="rounded-lg border border-[var(--studio-border)] p-4">
                <dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt>
                <dd className="mt-2 font-semibold tabular-nums">{value}</dd>
            </div>)}
        </dl>
        <GoalProjectionChart scenario={projected} currentPeriod={currentPeriod} currency={currency} />
        <section className="space-y-2">
            <h3 className="font-semibold">通る分岐</h3>
            <LifeEventDiagram events={events} links={links} scenario={projected} currency={currency} disabled dimOffPath
                pathEventIds={new Set(projected.likely_path.event_ids)} pathLinkIds={new Set(projected.likely_path.link_ids)}
                conditionEventIds={new Set(projected.conditions.map((row) => row.event_id))}
                onAddEvent={noop} onEditEvent={noop} onDeleteEvent={noop} onConditions={noop} onDeleteEdge={noop} onConnect={noop} onEdgeClick={noop} />
            <p className="text-xs text-[var(--studio-text-muted)]">強調した接続とイベントは過半数の試行が通る分岐、グレーは多くの試行で起きないイベントです。編集は「構成」で行います。</p>
        </section>
        <section className="space-y-3">
            <h3 className="font-semibold">ライフイベントの達成状況</h3>
            <DataTable columns={['ライフイベント', '種別', '日付', '金額', '起きる確率', '資金が足りる確率']}>
                {[...projected.events].sort((a, b) => (a.resolved_date ?? '9999').localeCompare(b.resolved_date ?? '9999')).map((event) => <tr key={`event-${event.id}`}>
                    <th scope="row" className="whitespace-nowrap px-5 py-3 font-medium">{event.name}</th>
                    <td className="whitespace-nowrap px-5 py-3">{KIND_LABELS[event.direction]}</td>
                    <td className="whitespace-nowrap px-5 py-3">{event.resolved_date ? formatDate(event.resolved_date) : '日付未設定'}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{eventAmount(event, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{percent(event.executed_probability)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{event.direction === 'expense' ? percent(event.funded_probability) : '—'}</td>
                </tr>)}
                {projected.events.length === 0 && <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">ライフイベントはありません。</td></tr>}
            </DataTable>
            <p className="text-xs text-[var(--studio-text-muted)]">起きる確率：前のイベント（返済は借入）が起き、前提条件を満たす割合。資金が足りる確率：支出が起きたうえで、その後の純資産が0以上の割合。</p>
        </section>
        <ScenarioPreconditions events={projected.conditions} currency={currency} />
        <section className="space-y-3">
            <h3 className="font-semibold">使用口座の見通し（中央値）</h3>
            <DataTable columns={['口座', '現在', ...columns.map((offset) => `${startYear + offset}年`)]}>
                {projected.accounts.map((account) => <tr key={`account-${account.account_id}`}>
                    <th scope="row" className="px-5 py-3 font-medium">{account.name}</th>
                    {[0, ...columns].map((offset) => <td key={offset} className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(account.p50[offset] ?? 0, currency)}</td>)}
                </tr>)}
                {projected.accounts.length === 0 && <tr><td colSpan={columns.length + 2} className="px-5 py-4 text-[var(--studio-text-muted)]">使用口座はありません。</td></tr>}
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
        const [scenarios, comparison, accounts, events, links] = await Promise.all([
            scenariosApi.list(), scenariosApi.compare([scenarioId]), loadAccounts(), getLifeEvents(scenarioId), getLifeEventLinks(scenarioId),
        ]);
        const scenario = scenarios.find((row) => row.id === scenarioId);
        if (!scenario) throw new Error('このシナリオは見つかりません。');
        return { scenario, projected: comparison.scenarios[0], accounts, events, links };
    }, [scenarioId]);
    const resource = useResource(load);
    const mutation = useMutation();
    const goal = useMakeScenarioGoal(reloadLayout);
    // undefined: closed; null: a new record.
    const [editing, setEditing] = useState<ContributionPlan | null | undefined>(undefined);
    const data = resource.data;
    const disabled = !clientName || mutation.busy || resource.loading || Boolean(resource.error);
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
            <Panel title="シミュレーションの設定" note="ここを変えると下の結果を計算し直します。">
                <section className="space-y-3">
                    <h3 className="text-sm font-semibold">前提</h3>
                    <Assumptions key={`${data.scenario.horizon_years}:${data.scenario.annual_return}:${data.scenario.inflation}`} scenario={data.scenario} busy={disabled}
                        onSave={(values) => saveRecord(() => scenariosApi.update(scenarioId, values), '前提を保存しました。')} />
                </section>
                <section className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <h3 className="text-sm font-semibold">使用口座と積立設定</h3>
                        <button type="button" disabled={disabled} onClick={() => setEditing(null)} className={buttonClass}>レコードを追加</button>
                    </div>
                    <UsedAccounts plans={data.scenario.contribution_plans} currency={currency} disabled={disabled} onEdit={setEditing} />
                    <p className="text-xs text-[var(--studio-text-muted)]">シミュレーションで増やすのは使用口座だけです（それ以外の資産・負債は残りの純資産）。口座ごとに、開始月がその月以前で最も新しいレコードを使います。計画の作成では、積立は配分、取り崩しは取り崩しの行になります。</p>
                </section>
            </Panel>
            <Panel title="シミュレーションの結果" note={`${data.projected?.horizon_years ?? data.scenario.horizon_years}年分・1200 通りの試行の集計です。`}
                action={resource.loading ? <p role="status" className="text-xs text-[var(--studio-text-muted)]">計算しています…</p> : undefined}>
                {data.projected && <Results projected={data.projected} events={data.events} links={data.links} currency={currency} currentPeriod={currentPeriod} />}
            </Panel>
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
