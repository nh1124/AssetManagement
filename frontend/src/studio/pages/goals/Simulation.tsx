import { useCallback, useId, useState, type FormEvent, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { getLifeEvents } from '../../../api';
import { getLifeEventLinks } from '../../../api/lifeEventGraph';
import * as scenariosApi from '../../../api/lifeScenarios';
import type { AssumptionPeriod, ContributionPlan, LifeScenario, ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { useClient } from '../../../context/ClientContext';
import type { LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Field, Help } from '../db/Database';
import { buttonClass, inputClass, loadAccounts, primaryClass, useMutation } from '../db/forms';
import type { LifeEventLink } from '../../../api/lifeEventGraph';
import AssumptionPeriodEditor from './AssumptionPeriodEditor';
import ContributionPlanEditor from './ContributionPlanEditor';
import { recordText, scheduleText, SHORTAGE_TEXT } from './contributionText';
import { eventAmount, KIND_LABELS } from './eventKinds';
import GoalProjectionChart from './GoalProjectionChart';
import LifeEventDiagram from './LifeEventDiagram';
import ScenarioPreconditions from './ScenarioPreconditions';
import { useScenario } from './scenarioContext';
import { useMakeScenarioGoal } from './useMakeScenarioGoal';
import { tr } from '../../i18n';

const percent = (value: number | null) => value === null ? tr('期間外', 'Out of range') : `${Math.round(value * 100)}%`;
const noop = () => undefined;

/** One of the two halves of the screen: what is set, and what follows from it. */
function Panel({ title, help, action, children }: { title: string; help: string; action?: ReactNode; children: ReactNode }) {
    return <section className="space-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--studio-border)] pb-3">
            <h2 className="flex items-center gap-1.5 font-semibold">{title}<Help label={title} text={help} below /></h2>
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
            setError(tr('期間は1〜60の整数、年利・インフレは数値で入力してください。', 'Enter a whole number of years from 1 to 60, and numbers for the return and inflation.'));
            return;
        }
        setError('');
        onSave({ horizon_years: horizon, annual_return: Number(rate), inflation: Number(inflation) });
    };
    return <form id={form} onSubmit={submit} className="space-y-3">
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid items-end gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label={tr('期間（年）', 'Horizon (years)')}><input type="number" min="1" max="60" step="1" required value={years} onChange={(event) => setYears(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('既定の年利（%）', 'Default return (%)')} help={tr('積立設定に年利のない口座の利回りです。', 'The return for accounts without one in the contribution settings.')}><input inputMode="decimal" required value={rate} onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('インフレ（%）', 'Inflation (%)')} help={tr('金額は今日の価値で表します。利回りからインフレを差し引き、積立額・借入・返済は実質で一定とします。', 'Amounts are in today’s money. Inflation is taken off returns; contributions, borrowing and repayments stay constant in real terms.')}><input inputMode="decimal" required value={inflation} onChange={(event) => setInflation(event.target.value)} className={inputClass} /></Field>
            <div><button type="submit" disabled={busy || !changed} className={primaryClass}>{tr('前提を保存', 'Save assumptions')}</button></div>
        </fieldset>
    </form>;
}

const monthText = (period: string) => tr(`${period.slice(0, 4)}年${Number(period.slice(5, 7))}月`, period);
const rateText = (value: number | null) => value === null ? <span className="text-[var(--studio-text-muted)]">{tr('変えない', 'Unchanged')}</span> : `${value}%`;

/** 期間ごとの前提: the records that set the default yield and the inflation for some months, oldest start first. */
function AssumptionPeriods({ periods, disabled, onEdit }: { periods: AssumptionPeriod[]; disabled: boolean; onEdit: (period: AssumptionPeriod) => void }) {
    if (!periods.length) return <p className="rounded-md border border-dashed border-[var(--studio-border)] p-4 text-sm text-[var(--studio-text-muted)]">{tr('ありません。すべての月で上の前提を使います。', 'None. Every month uses the assumptions above.')}</p>;
    return <div className="overflow-hidden rounded-md border border-[var(--studio-border)]">
        <table className="w-full table-fixed text-left text-sm">
            <colgroup><col className="w-60" /><col className="w-32" /><col className="w-32" /><col /></colgroup>
            <thead className="text-xs text-[var(--studio-text-muted)]"><tr>{[tr('期間', 'Period'), tr('既定の年利', 'Default return'), tr('インフレ', 'Inflation'), tr('メモ', 'Note')].map((label) => <th key={label} scope="col" className="px-4 py-2 font-medium">{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">{[...periods].sort((a, b) => a.start_period.localeCompare(b.start_period) || a.id - b.id).map((period) => {
                const span = `${monthText(period.start_period)}${tr('〜', ' – ')}${period.end_period ? monthText(period.end_period) : ''}`;
                return <tr key={period.id} onClick={() => { if (!disabled) onEdit(period); }} className={disabled ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)]'}>
                    <th scope="row" className="px-4 py-2 font-normal"><button type="button" disabled={disabled} aria-haspopup="dialog" aria-label={tr(`期間ごとの前提（${span}）を編集`, `Edit the assumption period (${span})`)} onClick={(event) => { event.stopPropagation(); onEdit(period); }} className="rounded text-left tabular-nums hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{span}</button></th>
                    <td className="px-4 py-2 tabular-nums">{rateText(period.annual_return)}</td>
                    <td className="px-4 py-2 tabular-nums">{rateText(period.inflation)}</td>
                    <td className="px-4 py-2 text-[var(--studio-text-muted)]">{period.note ?? ''}</td>
                </tr>;
            })}</tbody>
        </table>
    </div>;
}

/** 使用口座と積立設定: each used account with its records, oldest start first; a transfer shows under both of its accounts. */
function UsedAccounts({ plans, currency, disabled, onEdit }: {
    plans: ContributionPlan[]; currency: string; disabled: boolean; onEdit: (plan: ContributionPlan) => void;
}) {
    const groups = new Map<number, { name: string; rows: Array<{ plan: ContributionPlan; incoming: boolean }> }>();
    const add = (accountId: number, name: string | null, plan: ContributionPlan, incoming: boolean) => {
        const group = groups.get(accountId) ?? { name: name ?? `#${accountId}`, rows: [] };
        group.rows.push({ plan, incoming });
        groups.set(accountId, group);
    };
    for (const plan of [...plans].sort((a, b) => a.start_period.localeCompare(b.start_period) || a.id - b.id)) {
        add(plan.account_id, plan.account_name, plan, false);
        if (plan.kind === 'transfer' && plan.to_account_id !== null) add(plan.to_account_id, plan.to_account_name, plan, true);
    }
    if (!groups.size) return <p className="rounded-md border border-dashed border-[var(--studio-border)] p-4 text-sm text-[var(--studio-text-muted)]">{tr('使用口座がありません。「レコードを追加」で口座ごとの積立と年利を追加してください。', 'No accounts are used. Use “Add a record” to add each account’s contributions and return.')}</p>;
    return <div className="space-y-3">{[...groups].sort(([, a], [, b]) => a.name.localeCompare(b.name, 'ja')).map(([accountId, group]) => <div key={accountId} className="overflow-hidden rounded-md border border-[var(--studio-border)]">
        <h4 className="bg-[var(--studio-bg)] px-4 py-2 text-sm font-medium">{group.name}</h4>
        <table className="w-full table-fixed text-left text-sm">
            <colgroup><col className="w-60" /><col className="w-72" /><col className="w-28" /><col /></colgroup>
            <thead className="text-xs text-[var(--studio-text-muted)]"><tr>{[tr('時期', 'When'), tr('内容', 'What'), tr('年利', 'Return'), tr('メモ', 'Note')].map((label) => <th key={label} scope="col" className="px-4 py-2 font-medium">{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">{group.rows.map(({ plan, incoming }) => <tr key={`${plan.id}:${incoming}`} onClick={() => { if (!disabled) onEdit(plan); }} className={disabled ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)]'}>
                <th scope="row" className="px-4 py-2 font-normal"><button type="button" disabled={disabled} aria-haspopup="dialog" aria-label={tr(`${group.name}（${scheduleText(plan)}）を編集`, `Edit ${group.name} (${scheduleText(plan)})`)} onClick={(event) => { event.stopPropagation(); onEdit(plan); }} className="rounded text-left tabular-nums hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{scheduleText(plan)}</button></th>
                <td className="px-4 py-2 tabular-nums">{incoming ? `${tr('振替', 'Transfer')} ${formatCurrency(plan.amount, currency)} ← ${plan.account_name ?? `#${plan.account_id}`}` : recordText(plan, currency)}
                    {plan.on_shortage && !incoming && <span className="block text-xs text-[var(--studio-text-muted)]">{tr('不足時：', 'When short: ')}{SHORTAGE_TEXT[plan.on_shortage]}</span>}</td>
                <td className="px-4 py-2 tabular-nums">{plan.kind !== 'contribution' ? <span className="text-[var(--studio-text-muted)]">—</span> : plan.annual_return === null ? <span className="text-[var(--studio-text-muted)]">{tr('引き継ぐ', 'Carried over')}</span> : `${plan.annual_return}%`}</td>
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
                [tr('今月の積立', 'Saving this month'), formatCurrency(projected.monthly_contribution, currency)],
                [tr(`${last?.year ?? ''}年の純資産（中央値）`, `Net worth in ${last?.year ?? ''} (median)`), last ? formatCurrency(last.p50, currency) : '—'],
                [tr(`${last?.year ?? ''}年の純資産（P10〜P90）`, `Net worth in ${last?.year ?? ''} (P10–P90)`), last ? `${formatCurrency(last.p10, currency)}${tr('〜', ' – ')}${formatCurrency(last.p90, currency)}` : '—'],
            ].map(([label, value]) => <div key={label} className="rounded-lg border border-[var(--studio-border)] p-4">
                <dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt>
                <dd className="mt-2 font-semibold tabular-nums">{value}</dd>
            </div>)}
        </dl>
        <GoalProjectionChart scenario={projected} currentPeriod={currentPeriod} currency={currency} />
        <section className="space-y-2">
            <h3 className="flex items-center gap-1.5 font-semibold">{tr('通る分岐', 'Likely branches')}<Help label={tr('通る分岐', 'Likely branches')} text={tr('強調した接続とイベントは過半数の試行が通る分岐、グレーは多くの試行で起きないイベントです。編集は「構成」で行います。', 'Highlighted links and events are the branches most runs take; grey events do not happen in most runs. Edit them under “Structure”.')} /></h3>
            <LifeEventDiagram events={events} links={links} scenario={projected} currency={currency} disabled dimOffPath
                pathEventIds={new Set(projected.likely_path.event_ids)} pathLinkIds={new Set(projected.likely_path.link_ids)}
                conditionEventIds={new Set(projected.conditions.map((row) => row.event_id))}
                onAddEvent={noop} onEditEvent={noop} onDeleteEvent={noop} onConditions={noop} onDeleteEdge={noop} onConnect={noop} onEdgeClick={noop} />
        </section>
        <section className="space-y-3">
            <h3 className="flex items-center gap-1.5 font-semibold">{tr('ライフイベントの達成状況', 'Life event outcomes')}<Help label={tr('ライフイベントの達成状況', 'Life event outcomes')} text={tr('起きる確率：前のイベント（返済は借入）が起き、前提条件を満たす割合。資金が足りる確率：支出が起きたうえで、その後の純資産が0以上の割合。', 'Chance it happens: the share of runs where the previous event (for a repayment, the borrowing) happens and the preconditions hold. Chance it is funded: the share where the spending happens and net worth stays at 0 or more afterwards.')} wide /></h3>
            <DataTable columns={[tr('ライフイベント', 'Life event'), tr('種別', 'Kind'), tr('日付', 'Date'), tr('金額', 'Amount'), tr('起きる確率', 'Chance it happens'), tr('資金が足りる確率', 'Chance it is funded')]}>
                {[...projected.events].sort((a, b) => (a.resolved_date ?? '9999').localeCompare(b.resolved_date ?? '9999')).map((event) => <tr key={`event-${event.id}`}>
                    <th scope="row" className="whitespace-nowrap px-5 py-3 font-medium">{event.name}</th>
                    <td className="whitespace-nowrap px-5 py-3">{KIND_LABELS[event.direction]}</td>
                    <td className="whitespace-nowrap px-5 py-3">{event.resolved_date ? formatDate(event.resolved_date) : tr('日付未設定', 'No date')}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{eventAmount(event, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{percent(event.executed_probability)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{event.direction === 'expense' ? percent(event.funded_probability) : '—'}</td>
                </tr>)}
                {projected.events.length === 0 && <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('ライフイベントはありません。', 'No life events.')}</td></tr>}
            </DataTable>
        </section>
        <ScenarioPreconditions events={projected.conditions} currency={currency} />
        <section className="space-y-3">
            <h3 className="font-semibold">{tr('使用口座の見通し（中央値）', 'Outlook for the accounts used (median)')}</h3>
            <DataTable columns={[tr('口座', 'Account'), tr('現在', 'Now'), ...columns.map((offset) => tr(`${startYear + offset}年`, `${startYear + offset}`))]}>
                {projected.accounts.map((account) => <tr key={`account-${account.account_id}`}>
                    <th scope="row" className="px-5 py-3 font-medium">{account.name}</th>
                    {[0, ...columns].map((offset) => <td key={offset} className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(account.p50[offset] ?? 0, currency)}</td>)}
                </tr>)}
                {projected.accounts.length === 0 && <tr><td colSpan={columns.length + 2} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('使用口座はありません。', 'No accounts used.')}</td></tr>}
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
        if (!scenario) throw new Error(tr('このシナリオは見つかりません。', 'This scenario was not found.'));
        return { scenario, projected: comparison.scenarios[0], accounts, events, links };
    }, [scenarioId]);
    const resource = useResource(load);
    const mutation = useMutation();
    const goal = useMakeScenarioGoal(reloadLayout);
    // undefined: closed; null: a new record.
    const [editing, setEditing] = useState<ContributionPlan | null | undefined>(undefined);
    const [editingPeriod, setEditingPeriod] = useState<AssumptionPeriod | null | undefined>(undefined);
    const data = resource.data;
    const disabled = !clientName || mutation.busy || resource.loading || Boolean(resource.error);
    const saveRecord = (action: () => Promise<unknown>, message: string) => {
        void mutation.run(action, message, () => { setEditing(undefined); setEditingPeriod(undefined); resource.reload(); });
    };
    const removePeriod = (period: AssumptionPeriod) => {
        void (async () => {
            if (await confirm(tr(`「${clientName}」の期間ごとの前提（${monthText(period.start_period)}〜${period.end_period ? monthText(period.end_period) : ''}）を削除します。`, `Delete the assumption period (${monthText(period.start_period)} – ${period.end_period ? monthText(period.end_period) : ''}) of “${clientName}”.`), tr('削除する', 'Delete'))) {
                saveRecord(() => scenariosApi.deleteAssumptionPeriod(period.id), tr('期間ごとの前提を削除しました。', 'Assumption period deleted.'));
            }
        })();
    };
    const removeRecord = (plan: ContributionPlan) => {
        void (async () => {
            if (await confirm(tr(`「${clientName}」の積立設定（${plan.account_name}・${scheduleText(plan)}）を削除します。`, `Delete the contribution setting (${plan.account_name}, ${scheduleText(plan)}) of “${clientName}”.`), tr('削除する', 'Delete'))) {
                saveRecord(() => scenariosApi.deleteContributionPlan(plan.id), tr('積立設定を削除しました。', 'Contribution setting deleted.'));
            }
        })();
    };
    return <section className="space-y-6">
        <Feedback loading={resource.loading && !data} error={resource.error || (editing === undefined && editingPeriod === undefined ? mutation.error : '') || goal.error} message={mutation.message || goal.message} />
        {goal.dialog}
        {data && <>
            {!data.scenario.is_goal && <div className="flex justify-end">
                <button type="button" disabled={disabled || goal.busy} onClick={() => goal.chooseGoal(data.scenario)} className={buttonClass}>{tr('このシナリオをゴールにする', 'Make this scenario the goal')}</button>
            </div>}
            <Panel title={tr('シミュレーションの設定', 'Simulation settings')} help={tr('ここを変えると下の結果を計算し直します。', 'Changing these recalculates the results below.')}>
                <section className="space-y-3">
                    <h3 className="text-sm font-semibold">{tr('前提', 'Assumptions')}</h3>
                    <Assumptions key={`${data.scenario.horizon_years}:${data.scenario.annual_return}:${data.scenario.inflation}`} scenario={data.scenario} busy={disabled}
                        onSave={(values) => saveRecord(() => scenariosApi.update(scenarioId, values), tr('前提を保存しました。', 'Assumptions saved.'))} />
                </section>
                <section className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <h3 className="flex items-center gap-1.5 text-sm font-semibold">{tr('期間ごとの前提', 'Assumption periods')}<Help label={tr('期間ごとの前提', 'Assumption periods')} text={tr('期間を決めて、既定の年利とインフレを上の前提から変えます。空欄の項目は変えません。期間が重なるときは開始月の遅いレコードを使います。口座の積立設定に年利があれば、その口座はそちらを使います。シミュレーションは年ごとに計算するため、各年の最初の月の値を使います。変動率と税率はすべてのシナリオに共通で、設定画面で変えます。', 'Change the default return and inflation from the assumptions above for a span of months. Empty fields stay unchanged. Where spans overlap, the record with the later start wins. An account with a return in its contribution settings uses that instead. The simulation runs year by year, so each year uses its first month’s values. Volatility and tax rate are shared by all scenarios and set in Settings.')} wide /></h3>
                        <button type="button" disabled={disabled} onClick={() => setEditingPeriod(null)} className={buttonClass}>{tr('レコードを追加', 'Add a record')}</button>
                    </div>
                    <AssumptionPeriods periods={data.scenario.assumption_periods} disabled={disabled} onEdit={setEditingPeriod} />
                </section>
                <section className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <h3 className="flex items-center gap-1.5 text-sm font-semibold">{tr('使用口座と積立設定', 'Accounts and contribution settings')}<Help label={tr('使用口座と積立設定', 'Accounts and contribution settings')} text={tr('シミュレーションで増やすのは使用口座（レコードにある口座）だけです（それ以外の資産・負債は残りの純資産）。レコードは積立・口座振替・ライフイベントへの取り崩しの3種類で、1回、または毎月・毎年・指定の間隔で、回数や終了月まで行います。レコードは足し合わせます。口座振替と取り崩しは、口座の残高が足りないときの扱い（取引を発生させない／ある分だけで取引する）を選べます。取り崩しはイベントの月より前は確保（純資産は変わらない）、イベントの月からはイベントの支払いになり、口座から払えない分は残りの純資産から払います。計画の作成では、積立は配分、口座振替は振替元からの配分、取り崩しはその月までのゴールの取り置きと、取り崩す月の取り崩しの行になります。', 'The simulation grows only the accounts used (those in the records); other assets and liabilities are the rest of net worth. Records are contributions, transfers or drawdowns for a life event, once or monthly, yearly or at a set interval, for a count or until a month, and they add up. For transfers and drawdowns, choose what happens when the balance is short (skip, or move what is there). A drawdown sets money aside before the event’s month (net worth does not change) and pays the event from that month; what the account cannot pay comes from the rest of net worth. When the plan is made, contributions become allocations, transfers become allocations funded from the source, and drawdowns become the goal’s earmark until that month and drawdown rows in the drawdown months.')} wide /></h3>
                        <button type="button" disabled={disabled} onClick={() => setEditing(null)} className={buttonClass}>{tr('レコードを追加', 'Add a record')}</button>
                    </div>
                    <UsedAccounts plans={data.scenario.contribution_plans} currency={currency} disabled={disabled} onEdit={setEditing} />
                </section>
            </Panel>
            <Panel title={tr('シミュレーションの結果', 'Simulation results')} help={tr(`${data.projected?.horizon_years ?? data.scenario.horizon_years}年分・1200 通りの試行の集計です。`, `${data.projected?.horizon_years ?? data.scenario.horizon_years} years, summarised over 1,200 runs.`)}
                action={resource.loading ? <p role="status" className="text-xs text-[var(--studio-text-muted)]">{tr('計算しています…', 'Calculating…')}</p> : undefined}>
                {data.projected && <Results projected={data.projected} events={data.events} links={data.links} currency={currency} currentPeriod={currentPeriod} />}
            </Panel>
        </>}
        {editing !== undefined && data && <Overlay title={editing ? tr('積立設定を編集', 'Edit contribution setting') : tr('積立設定を追加', 'Add a contribution setting')} busy={mutation.busy} onClose={() => setEditing(undefined)}>
            <Feedback error={mutation.error} />
            <ContributionPlanEditor plan={editing} accounts={data.accounts} events={data.events} defaultPeriod={currentPeriod} currency={currency} defaultRate={data.scenario.annual_return} busy={disabled}
                onCancel={() => setEditing(undefined)} onDelete={editing ? () => removeRecord(editing) : undefined}
                onSave={(input) => saveRecord(() => editing ? scenariosApi.updateContributionPlan(editing.id, input) : scenariosApi.createContributionPlan(scenarioId, input), tr('積立設定を保存しました。', 'Contribution setting saved.'))} />
        </Overlay>}
        {editingPeriod !== undefined && data && <Overlay title={editingPeriod ? tr('期間ごとの前提を編集', 'Edit assumption period') : tr('期間ごとの前提を追加', 'Add an assumption period')} busy={mutation.busy} onClose={() => setEditingPeriod(undefined)}>
            <Feedback error={mutation.error} />
            <AssumptionPeriodEditor period={editingPeriod} defaultPeriod={currentPeriod} defaultRate={data.scenario.annual_return} defaultInflation={data.scenario.inflation} busy={disabled}
                onCancel={() => setEditingPeriod(undefined)} onDelete={editingPeriod ? () => removePeriod(editingPeriod) : undefined}
                onSave={(input) => saveRecord(() => editingPeriod ? scenariosApi.updateAssumptionPeriod(editingPeriod.id, input) : scenariosApi.createAssumptionPeriod(scenarioId, input), tr('期間ごとの前提を保存しました。', 'Assumption period saved.'))} />
        </Overlay>}
    </section>;
}

export default function Simulation() {
    const { clientId, currentClient } = useClient();
    const { scenarioId = '' } = useParams();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <SimulationForClient key={`${clientId}:${currency}:${scenarioId}`} scenarioId={Number(scenarioId)} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
