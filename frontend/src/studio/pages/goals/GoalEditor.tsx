import { useId, useState, type FormEvent } from 'react';
import { createGoal, updateGoal } from '../../../api';
import type { LifeEvent } from '../../../types';
import { Choice, EditorActions, Feedback, Field } from '../db/Database';
import { ACCOUNT_TYPES, buttonClass, inputClass, type DatabaseAccount } from '../db/forms';

/** A life event's facts: kind, account or subject, name, amount, date, priority and memo. */
export default function GoalEditor({ goal, scenarioId, accounts, currency, busy, onSave, onCancel, onDelete }: {
    goal: LifeEvent | null; scenarioId: number; accounts: DatabaseAccount[]; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void; onDelete?: () => void;
}) {
    const formId = useId();
    const [direction, setDirection] = useState<LifeEvent['direction']>(goal?.direction ?? 'expense');
    const [accountId, setAccountId] = useState<number | null>(goal?.account_id ?? null);
    const [name, setName] = useState(goal?.name ?? '');
    const [amount, setAmount] = useState(goal ? String(goal.target_amount) : '');
    const [target, setTarget] = useState(goal?.target_date ?? '');
    const [priority, setPriority] = useState<LifeEvent['priority']>(goal?.priority ?? 2);
    const [note, setNote] = useState(goal?.note ?? '');
    const [error, setError] = useState('');
    const choices = accounts
        .filter((row) => (row.account_type === 'asset' || row.account_type === direction) && (row.is_active || row.id === accountId))
        .map((row) => ({ ...row, name: `${row.name}（${ACCOUNT_TYPES[row.account_type]}）` }));
    const chooseDirection = (value: LifeEvent['direction']) => {
        setDirection(value);
        // Switching kind must not silently keep a subject of the opposite type.
        const selected = accounts.find((row) => row.id === accountId);
        if (selected && selected.account_type !== 'asset' && selected.account_type !== value) setAccountId(null);
    };
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const value = Number(amount);
        if (busy) return;
        if (!name.trim() || !target || amount.trim() === '' || !Number.isFinite(value) || value < 0) {
            setError('名称・目標日と0以上の金額を入力してください。');
            return;
        }
        setError('');
        const payload = { direction, account_id: accountId, name: name.trim(), target_amount: value, target_date: target, priority, note: note.trim() || null };
        onSave(() => goal ? updateGoal(goal.id, payload) : createGoal({ ...payload, scenario_id: scenarioId }));
    };
    return <form id={formId} onSubmit={submit} className="space-y-4">
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <fieldset className="space-y-2"><legend className="text-sm text-[var(--studio-text-muted)]">種別</legend><div role="group" aria-label="種別" className="inline-flex overflow-hidden rounded-md border border-[var(--studio-border)]">
                {(['expense', 'income'] as const).map((value) => <button key={value} type="button" aria-pressed={direction === value} onClick={() => chooseDirection(value)} className={`${buttonClass} rounded-none border-0 aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>{value === 'expense' ? '支出' : '収入'}</button>)}
            </div></fieldset>
            <Choice label="口座・科目" help="資産口座を選ぶと、シミュレーションではその口座から出入りします。科目や未設定のときは、それ以外の純資産から出入りします。" value={accountId} options={choices} onChange={setAccountId} />
            <Field label="名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label={`${direction === 'income' ? '金額' : '目標額'}（${currency}）`}><input required type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <Field label="目標日"><input required type="date" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            <Field label="優先度"><select value={priority} onChange={(event) => setPriority(Number(event.target.value) as LifeEvent['priority'])} className={inputClass}><option value={1}>高</option><option value={2}>中</option><option value={3}>低</option></select></Field>
            <div className="md:col-span-2"><Field label="メモ"><textarea value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field></div>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} onDelete={onDelete} />
        </fieldset>
    </form>;
}
