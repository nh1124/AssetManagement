import { useId, useState, type FormEvent } from 'react';
import { createGoal, updateGoal } from '../../../api';
import type { BudgetReflection, LifeEvent } from '../../../types';
import { useResource } from '../../useResource';
import { REFLECTION_HINTS, REFLECTIONS } from './presentation';
import { Choice, EditorActions, Feedback, Field } from '../db/Database';
import { ACCOUNT_TYPES, buttonClass, inputClass, loadAccounts } from '../db/forms';

export default function GoalEditor({ goal, scenarioId, currency, busy, embedded = false, onSave, onCancel }: {
    goal: LifeEvent | null; scenarioId?: number; currency: string; busy: boolean; embedded?: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const formId = useId();
    const reflectionHint = useId();
    const accounts = useResource(loadAccounts);
    const [direction, setDirection] = useState<NonNullable<LifeEvent['direction']>>(goal?.direction ?? 'expense');
    const [accountId, setAccountId] = useState<number | null>(goal?.account_id ?? null);
    const [name, setName] = useState(goal?.name ?? '');
    const [amount, setAmount] = useState(String(goal?.target_amount ?? 0));
    const [target, setTarget] = useState(goal?.target_date ?? '');
    const [start, setStart] = useState(goal?.start_date ?? '');
    const [priority, setPriority] = useState<LifeEvent['priority']>(goal?.priority ?? 2);
    const [note, setNote] = useState(goal?.note ?? '');
    // null keeps following the event's preconditions until the user picks one.
    const [reflection, setReflection] = useState<BudgetReflection | null>(goal?.budget_reflection ?? null);
    const locked = busy || accounts.loading || Boolean(accounts.error);
    const choices = (accounts.data ?? [])
        .filter((row) => (row.account_type === 'asset' || row.account_type === direction) && (row.is_active || row.id === accountId))
        .map((row) => ({ ...row, name: `${row.name}（${ACCOUNT_TYPES[row.account_type]}）` }));
    const chooseDirection = (value: typeof direction) => {
        setDirection(value);
        // Switching direction must not silently keep a category of the opposite type.
        const selected = accounts.data?.find((row) => row.id === accountId);
        if (selected && selected.account_type !== 'asset' && selected.account_type !== value) setAccountId(null);
    };
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (locked || !name.trim()) return;
        const payload = { direction, account_id: accountId, name: name.trim(), target_amount: Number(amount), target_date: target, start_date: start || null, priority, note: note.trim() || null, ...(reflection ? { budget_reflection: reflection } : {}) };
        onSave(() => goal ? updateGoal(goal.id, payload) : createGoal({ ...payload, scenario_id: scenarioId }));
    };
    return <form id={formId} onSubmit={submit} className={embedded ? 'space-y-4' : 'space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5'}>
        <Feedback loading={accounts.loading} error={accounts.error} />
        <fieldset disabled={locked} className="grid gap-4 md:grid-cols-2">
            <fieldset className="space-y-2"><legend className="text-sm text-[var(--studio-text-muted)]">種別</legend><div role="group" aria-label="種別" className="inline-flex overflow-hidden rounded-md border border-[var(--studio-border)]">
                {(['expense', 'income'] as const).map((value) => <button key={value} type="button" aria-pressed={direction === value} onClick={() => chooseDirection(value)} className={`${buttonClass} rounded-none border-0 aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>{value === 'expense' ? '支出' : '収入'}</button>)}
            </div></fieldset>
            <Choice label="口座・科目" value={accountId} options={choices} onChange={setAccountId} />
            <Field label="名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label={`${direction === 'income' ? '金額' : '目標額'}（${currency}）`}><input required type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <Field label="目標日"><input required type="date" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            <Field label="開始日"><input type="date" max={target || undefined} value={start} onChange={(event) => setStart(event.target.value)} className={inputClass} /></Field>
            <Field label="優先度"><select value={priority} onChange={(event) => setPriority(Number(event.target.value) as LifeEvent['priority'])} className={inputClass}><option value={1}>高</option><option value={2}>中</option><option value={3}>低</option></select></Field>
            {direction === 'expense' && <Field label="予算への反映"><select aria-describedby={reflectionHint} value={reflection ?? goal?.budget_reflection_effective ?? 'firm'} onChange={(event) => setReflection(event.target.value as BudgetReflection)} className={inputClass}>
                {(Object.keys(REFLECTIONS) as BudgetReflection[]).map((value) => <option key={value} value={value}>{REFLECTIONS[value]}</option>)}
            </select><span id={reflectionHint} className="mt-1 block text-xs text-[var(--studio-text-muted)]">{reflection ? REFLECTION_HINTS[reflection] : '未選択のときは、前提条件があれば条件つき、なければ確定として扱います。'}</span></Field>}
            <Field label="メモ"><textarea value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field>
            <EditorActions form={formId} busy={locked} onCancel={onCancel} />
        </fieldset>
    </form>;
}
