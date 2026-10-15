import { useCallback, useId, useState } from 'react';
import { getLifeEvents, updateGoal } from '../../../api';
import { addGoalCondition, deleteGoalCondition, getGoalConditions, getHouseholdMembers, type ConditionInput, type ConditionMetric, type ConditionMode } from '../../../api/lifeEventConditions';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useReloadAction } from '../../components/useReloadAction';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { DataTable, EditorActions, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, loadLookups, useMutation } from '../db/forms';

const metricLabels: Record<ConditionMetric, string> = { net_worth: '純資産', free_cash: '自由資金', account_balance: '口座残高', capsule_claim: '取り置きの確保額', goal_progress: 'ゴールの進捗', member_age: '年齢', date_reached: '日付' };
const comparisons = { gte: '以上', lte: '以下', eq: '等しい' };
const moneyMetrics = new Set<ConditionMetric>(['net_worth', 'free_cash', 'account_balance', 'capsule_claim']);
const referencedMetrics = new Set<ConditionMetric>(['account_balance', 'capsule_claim', 'goal_progress', 'member_age']);
type Lookups = Awaited<ReturnType<typeof loadLookups>> & { goals: Array<{ id: number; name: string }>; members: Array<{ id: number; name: string }> };

function ConditionEditor({ currency, lookups, busy, onSave, onCancel }: { currency: string; lookups: Lookups; busy: boolean; onSave: (input: ConditionInput) => void; onCancel: () => void }) {
    const form = useId();
    const timezone = useTimezone();
    const [metric, setMetric] = useState<ConditionMetric>('net_worth');
    const [comparator, setComparator] = useState<ConditionInput['comparator']>('gte');
    const [value, setValue] = useState('');
    const [reference, setReference] = useState('');
    const [note, setNote] = useState('');
    const [date, setDate] = useState(clientToday(timezone));
    const [error, setError] = useState('');
    const targets = metric === 'account_balance' ? lookups.accounts : metric === 'capsule_claim' ? lookups.capsules : metric === 'goal_progress' ? lookups.goals : lookups.members;
    const scale = currency === 'JPY' ? 1 : 100;
    return <form id={form} onSubmit={(event) => {
        event.preventDefault();
        if (busy) return;
        const input: ConditionInput = { metric, comparator, note: note || null };
        if (referencedMetrics.has(metric)) input.reference_id = Number(reference);
        if (metric === 'date_reached') input.threshold_date = date;
        else if (moneyMetrics.has(metric)) {
            const minor = Math.round(Number(value) * scale);
            if (!Number.isSafeInteger(minor)) { setError('金額が入力範囲を超えています。'); return; }
            input.threshold_minor = minor;
        } else input.threshold_number = Number(value);
        onSave(input);
    }}>
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <Field label="指標"><select value={metric} onChange={(event) => { setMetric(event.target.value as ConditionMetric); setReference(''); setValue(''); setError(''); }} className={inputClass}>{Object.entries(metricLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
            {referencedMetrics.has(metric) && <Field label="対象"><select required value={reference} onChange={(event) => setReference(event.target.value)} className={inputClass}><option value="">選択してください</option>{targets.map((target) => <option key={target.id} value={target.id}>{target.name}</option>)}</select></Field>}
            <Field label="比較"><select value={comparator} onChange={(event) => setComparator(event.target.value as ConditionInput['comparator'])} className={inputClass}>{Object.entries(comparisons).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
            {metric === 'date_reached' ? <Field label="条件日"><input required type="date" value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} /></Field> : <Field label={moneyMetrics.has(metric) ? `条件額（${currency}）` : metric === 'member_age' ? '年齢（歳）' : '進捗（%）'}><input required type="number" step={moneyMetrics.has(metric) ? 1 / scale : metric === 'member_age' ? 1 : '0.1'} value={value} onChange={(event) => setValue(event.target.value)} className={inputClass} /></Field>}
            <Field label="メモ"><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} />
    </form>;
}

function figure(value: number | string | null, metric: ConditionMetric, currency: string): string {
    if (value === null) return '—';
    if (metric === 'date_reached') return formatDate(String(value));
    if (moneyMetrics.has(metric)) return formatCurrency(Number(value), currency);
    return `${Number(value).toLocaleString('ja-JP')}${metric === 'member_age' ? '歳' : '%'}`;
}

export default function GoalConditions({ goalId, currency, clientName, disabled, onBusy }: { goalId: number; currency: string; clientName?: string; disabled: boolean; onBusy: (busy: boolean) => void }) {
    const confirm = useConfirm();
    const load = useCallback(async () => {
        const [evaluation, lookups, goals, members] = await Promise.all([getGoalConditions(goalId), loadLookups(), getLifeEvents(true), getHouseholdMembers()]);
        return { evaluation, lookups: { ...lookups, goals, members } };
    }, [goalId]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [editing, setEditing] = useState(false);
    const locked = disabled || !clientName || mutation.busy || resource.loading || Boolean(resource.error);
    const run = (action: () => Promise<unknown>, message: string, close = false) => {
        if (locked) return;
        onBusy(true);
        void mutation.run(action, message, () => { if (close) setEditing(false); resource.reload(); }).finally(() => onBusy(false));
    };
    useReloadAction(resource.reload, locked || editing);
    const evaluation = resource.data?.evaluation;
    return <section className="space-y-4 rounded-lg border border-[var(--studio-border)] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">条件</h3><span className="text-xs text-[var(--studio-text-muted)]">{evaluation && (evaluation.conditions.length === 0 ? '前提なし' : evaluation.satisfied === null ? '判定不能' : evaluation.satisfied ? '成立' : '未達')}</span><button type="button" disabled={locked || editing} onClick={() => setEditing(true)} className={buttonClass}>条件を追加</button></div>
        <Feedback loading={resource.loading} error={resource.error || (!editing ? mutation.error : '')} message={mutation.message} />
        {evaluation && !resource.loading && !resource.error && <>
            <Field label="条件の組み合わせ"><select value={evaluation.mode} disabled={locked || editing} onChange={(event) => run(() => updateGoal(goalId, { condition_mode: event.target.value as ConditionMode }), '組み合わせを変更しました。')} className={inputClass}><option value="all">すべて満たす</option><option value="any">いずれかを満たす</option></select></Field>
            <DataTable columns={['対象', '条件値', '現在値', '判定', '操作']}>
                {evaluation.conditions.map((row) => <tr key={row.id}>
                    <th scope="row" className="px-5 py-3 font-medium">{metricLabels[row.metric]}{referencedMetrics.has(row.metric) && <span className="block text-xs text-[var(--studio-text-muted)]">{row.reference_name ?? '対象なし'}</span>}{row.note && <span className="block text-xs text-[var(--studio-text-muted)]">{row.note}</span>}</th>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{figure(row.threshold, row.metric, currency)}・{comparisons[row.comparator]}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{figure(row.actual, row.metric, currency)}</td>
                    <td className="px-5 py-3">{row.satisfied === null ? '判定不能' : row.satisfied ? '成立' : '未達'}{row.reason && <span className="block text-xs text-[var(--studio-text-muted)]">{row.reason}</span>}</td>
                    <td className="px-5 py-3"><button type="button" disabled={locked || editing} className={buttonClass} onClick={async () => { if (await confirm(`「${clientName}」の「${metricLabels[row.metric]}」の条件を削除します。`, '条件を削除')) run(() => deleteGoalCondition(goalId, row.id), '条件を削除しました。'); }}>削除</button></td>
                </tr>)}
                {evaluation.conditions.length === 0 && <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">前提なし</td></tr>}
            </DataTable>
        </>}
        {editing && resource.data && <Overlay title="条件を追加" onClose={() => { if (!mutation.busy) setEditing(false); }}><Feedback error={mutation.error} /><ConditionEditor currency={currency} lookups={resource.data.lookups} busy={locked} onCancel={() => setEditing(false)} onSave={(input) => run(() => addGoalCondition(goalId, input), '条件を追加しました。', true)} /></Overlay>}
    </section>;
}
