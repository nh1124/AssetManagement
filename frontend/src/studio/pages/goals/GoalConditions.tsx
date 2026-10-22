import { useCallback, useId, useState } from 'react';
import { getLifeEvents, updateGoal } from '../../../api';
import { addGoalCondition, deleteGoalCondition, getGoalConditions, getHouseholdMembers, updateGoalCondition,
    type ConditionInput, type ConditionMetric, type ConditionMode, type ConditionResult } from '../../../api/lifeEventConditions';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, EditableRow, EditorActions, Feedback, Field, RowTitle } from '../db/Database';
import { buttonClass, inputClass, loadLookups, useMutation } from '../db/forms';
import { activeLocale, labels, tr } from '../../i18n';

const METRIC_LABELS = labels<ConditionMetric>({ net_worth: ['純資産', 'Net worth'], free_cash: ['自由資金', 'Free cash'], account_balance: ['口座残高', 'Account balance'], capsule_claim: ['取り置きの確保額', 'Set aside in an earmark'], goal_progress: ['ライフイベントの進捗', 'Life event progress'], member_age: ['年齢', 'Age'], date_reached: ['日付', 'Date'] });
const METRIC_HELP = labels<ConditionMetric>({
    net_worth: ['シミュレーションの各経路で、イベントの日の純資産を判定します。', 'Judged on each simulated path’s net worth on the event’s date.'],
    free_cash: ['自由資金（取り置き分を除いた残高）の現在の値で判定します。', 'Judged on free cash now (balances less what is set aside).'],
    account_balance: ['シミュレーションに含まれる資産口座は各経路の残高、それ以外は現在の残高で判定します。', 'Asset accounts in the simulation are judged on each path’s balance; others on today’s balance.'],
    capsule_claim: ['取り置きの現在の確保額で判定します。', 'Judged on what the earmark holds now.'],
    goal_progress: ['実績管理の設定による、ライフイベントの現在の進捗（%）で判定します。', 'Judged on the life event’s progress now (%), from its tracking settings.'],
    member_age: ['イベントの日の、世帯メンバーの年齢で判定します。', 'Judged on the household member’s age on the event’s date.'],
    date_reached: ['イベントの日が条件日に達しているかで判定します。', 'Judged on whether the event’s date has reached the condition date.'],
});
const COMPARISONS = labels({ gte: ['以上', 'or more'], lte: ['以下', 'or less'], eq: ['等しい', 'exactly'] });
const moneyMetrics = new Set<ConditionMetric>(['net_worth', 'free_cash', 'account_balance', 'capsule_claim']);
const referencedMetrics = new Set<ConditionMetric>(['account_balance', 'capsule_claim', 'goal_progress', 'member_age']);
type Target = { id: number; name: string };
type Lookups = { accounts: Target[]; capsules: Target[]; goals: Target[]; members: Target[] };

function ConditionEditor({ condition, currency, lookups, busy, onSave, onCancel, onDelete }: {
    condition: ConditionResult | null; currency: string; lookups: Lookups; busy: boolean;
    onSave: (input: ConditionInput) => void; onCancel: () => void; onDelete?: () => void;
}) {
    const form = useId();
    const timezone = useTimezone();
    const [metric, setMetric] = useState<ConditionMetric>(condition?.metric ?? 'net_worth');
    const [comparator, setComparator] = useState<ConditionInput['comparator']>(condition?.comparator ?? 'gte');
    const [value, setValue] = useState(condition && condition.metric !== 'date_reached' ? String(condition.threshold) : '');
    const [reference, setReference] = useState(condition?.reference_id ? String(condition.reference_id) : '');
    const [note, setNote] = useState(condition?.note ?? '');
    const [date, setDate] = useState(condition?.metric === 'date_reached' ? String(condition.threshold) : clientToday(timezone));
    const [error, setError] = useState('');
    const targets = metric === 'account_balance' ? lookups.accounts : metric === 'capsule_claim' ? lookups.capsules : metric === 'goal_progress' ? lookups.goals : lookups.members;
    const scale = currency === 'JPY' ? 1 : 100;
    return <form id={form} onSubmit={(event) => {
        event.preventDefault();
        if (busy) return;
        const input: ConditionInput = { metric, comparator, note: note.trim() || null };
        if (referencedMetrics.has(metric)) input.reference_id = Number(reference);
        if (metric === 'date_reached') input.threshold_date = date;
        else if (moneyMetrics.has(metric)) {
            const minor = Math.round(Number(value) * scale);
            if (!Number.isSafeInteger(minor)) { setError(tr('金額が入力範囲を超えています。', 'The amount is out of range.')); return; }
            input.threshold_minor = minor;
        } else input.threshold_number = Number(value);
        onSave(input);
    }}>
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <Field label={tr('指標', 'Measure')} help={METRIC_HELP[metric]}><select value={metric} onChange={(event) => { setMetric(event.target.value as ConditionMetric); setReference(''); setValue(''); setError(''); }} className={inputClass}>{Object.entries(METRIC_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
            {referencedMetrics.has(metric) && <Field label={tr('対象', 'Target')}><select required value={reference} onChange={(event) => setReference(event.target.value)} className={inputClass}><option value="">{tr('選択してください', 'Choose…')}</option>{targets.map((target) => <option key={target.id} value={target.id}>{target.name}</option>)}</select></Field>}
            <Field label={tr('比較', 'Comparison')}><select value={comparator} onChange={(event) => setComparator(event.target.value as ConditionInput['comparator'])} className={inputClass}>{Object.entries(COMPARISONS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
            {metric === 'date_reached' ? <Field label={tr('条件日', 'Condition date')}><input required type="date" value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} /></Field> : <Field label={moneyMetrics.has(metric) ? tr(`条件額（${currency}）`, `Amount (${currency})`) : metric === 'member_age' ? tr('年齢（歳）', 'Age (years)') : tr('進捗（%）', 'Progress (%)')}><input required type="number" step={moneyMetrics.has(metric) ? 1 / scale : metric === 'member_age' ? 1 : '0.1'} value={value} onChange={(event) => setValue(event.target.value)} className={inputClass} /></Field>}
            <div className="sm:col-span-2"><Field label={tr('メモ', 'Note')}><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field></div>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} onDelete={onDelete} />
    </form>;
}

function conditionFigure(value: number | string | null, metric: ConditionMetric, currency: string): string {
    if (value === null) return '—';
    if (metric === 'date_reached') return formatDate(String(value));
    if (moneyMetrics.has(metric)) return formatCurrency(Number(value), currency);
    return metric === 'member_age' ? tr(`${Number(value).toLocaleString('ja-JP')}歳`, `age ${Number(value).toLocaleString('en-US')}`) : `${Number(value).toLocaleString(activeLocale())}%`;
}

/** An event's preconditions: how they combine, and each one to add, edit or delete. */
export default function GoalConditions({ goalId, scenarioId, currency, clientName, onBusy, onChanged }: {
    goalId: number; scenarioId: number; currency: string; clientName: string; onBusy: (busy: boolean) => void; onChanged: () => void;
}) {
    const confirm = useConfirm();
    const load = useCallback(async () => {
        const [evaluation, lookups, goals, members] = await Promise.all([getGoalConditions(goalId), loadLookups(), getLifeEvents(scenarioId), getHouseholdMembers()]);
        return { evaluation, lookups: { ...lookups, goals: goals.filter((goal) => goal.id !== goalId), members } };
    }, [goalId, scenarioId]);
    const resource = useResource(load);
    const mutation = useMutation();
    // undefined: closed; null: a new condition.
    const [editing, setEditing] = useState<ConditionResult | null | undefined>(undefined);
    const locked = mutation.busy || resource.loading || Boolean(resource.error);
    const run = (action: () => Promise<unknown>, message: string) => {
        if (locked) return;
        onBusy(true);
        void mutation.run(action, message, () => { setEditing(undefined); resource.reload(); onChanged(); }).finally(() => onBusy(false));
    };
    const evaluation = resource.data?.evaluation;
    const remove = (row: ConditionResult) => {
        void (async () => {
            if (await confirm(tr(`「${clientName}」の「${METRIC_LABELS[row.metric]}」の条件を削除します。`, `Delete the “${METRIC_LABELS[row.metric]}” condition of “${clientName}”.`), tr('削除する', 'Delete'))) run(() => deleteGoalCondition(goalId, row.id), tr('条件を削除しました。', 'Condition deleted.'));
        })();
    };
    return <section className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
            {evaluation && <Field label={tr('条件の組み合わせ', 'Combine conditions')}><select value={evaluation.mode} disabled={locked} onChange={(event) => run(() => updateGoal(goalId, { condition_mode: event.target.value as ConditionMode }), tr('組み合わせを変更しました。', 'Combination changed.'))} className={inputClass}><option value="all">{tr('すべて満たす', 'All must hold')}</option><option value="any">{tr('いずれかを満たす', 'Any must hold')}</option></select></Field>}
            <button type="button" disabled={locked} onClick={() => setEditing(null)} className={buttonClass}>{tr('条件を追加', 'Add a condition')}</button>
        </div>
        <Feedback loading={resource.loading} error={resource.error || (editing === undefined ? mutation.error : '')} message={mutation.message} />
        {evaluation && <DataTable columns={[tr('指標', 'Measure'), tr('対象', 'Target'), tr('条件', 'Condition'), tr('メモ', 'Note')]}>
            {evaluation.conditions.map((row) => <EditableRow key={row.id} disabled={locked} onEdit={() => setEditing(row)}>
                <RowTitle name={METRIC_LABELS[row.metric]} disabled={locked} onEdit={() => setEditing(row)}>{METRIC_LABELS[row.metric]}</RowTitle>
                <td className="px-5 py-3">{referencedMetrics.has(row.metric) ? row.reference_name ?? tr('対象なし', 'No target') : '—'}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{conditionFigure(row.threshold, row.metric, currency)} {COMPARISONS[row.comparator]}</td>
                <td className="px-5 py-3 text-[var(--studio-text-muted)]">{row.note ?? ''}</td>
            </EditableRow>)}
            {evaluation.conditions.length === 0 && <tr><td colSpan={4} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('前提条件はありません。', 'No preconditions.')}</td></tr>}
        </DataTable>}
        {editing !== undefined && resource.data && <Overlay title={editing ? tr('条件を編集', 'Edit condition') : tr('条件を追加', 'Add a condition')} busy={mutation.busy} onClose={() => setEditing(undefined)}>
            <Feedback error={mutation.error} />
            <ConditionEditor condition={editing} currency={currency} lookups={resource.data.lookups} busy={locked}
                onCancel={() => setEditing(undefined)} onDelete={editing ? () => remove(editing) : undefined}
                onSave={(input) => run(() => editing ? updateGoalCondition(goalId, editing.id, input) : addGoalCondition(goalId, input), editing ? tr('条件を保存しました。', 'Condition saved.') : tr('条件を追加しました。', 'Condition added.'))} />
        </Overlay>}
    </section>;
}
