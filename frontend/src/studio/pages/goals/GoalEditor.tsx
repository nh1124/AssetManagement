import { useId, useState, type FormEvent } from 'react';
import { createGoal, updateGoal } from '../../../api';
import type { LifeEvent } from '../../../types';
import { EditorActions, Field } from '../db/Database';
import { inputClass } from '../db/forms';

export default function GoalEditor({ goal, currency, busy, onSave, onCancel }: {
    goal: LifeEvent | null; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const formId = useId();
    const [name, setName] = useState(goal?.name ?? '');
    const [amount, setAmount] = useState(String(goal?.target_amount ?? 0));
    const [target, setTarget] = useState(goal?.target_date ?? '');
    const [start, setStart] = useState(goal?.start_date ?? '');
    const [priority, setPriority] = useState<LifeEvent['priority']>(goal?.priority ?? 2);
    const [note, setNote] = useState(goal?.note ?? '');
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || !name.trim()) return;
        const payload = { name: name.trim(), target_amount: Number(amount), target_date: target, start_date: start || null, priority, note: note.trim() || null };
        onSave(() => goal ? updateGoal(goal.id, payload) : createGoal(payload));
    };
    return <form id={formId} onSubmit={submit} className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label={`目標額（${currency}）`}><input required type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <Field label="目標日"><input required type="date" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            <p className="text-xs text-[var(--studio-text-muted)] md:col-span-2">延期するときは目標日を変更してください。</p>
            <Field label="開始日"><input type="date" max={target || undefined} value={start} onChange={(event) => setStart(event.target.value)} className={inputClass} /></Field>
            <Field label="優先度"><select value={priority} onChange={(event) => setPriority(Number(event.target.value) as LifeEvent['priority'])} className={inputClass}><option value={1}>高</option><option value={2}>中</option><option value={3}>低</option></select></Field>
            <Field label="メモ"><textarea value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}
