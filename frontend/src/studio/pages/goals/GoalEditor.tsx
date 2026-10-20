import { useId, useState, type FormEvent } from 'react';
import { createGoal, updateGoal } from '../../../api';
import type { LifeEvent, LifeEventKind } from '../../../types';
import { Choice, EditorActions, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass } from '../db/forms';
import { KIND_LABELS } from './eventKinds';

/** A life event: its kind, name, amount and date; a loan's rate, or a repayment's borrowing and months.
 * What an account gives toward it is a 積立設定 record of the simulation settings. */
export default function GoalEditor({ goal, scenarioId, events, currency, busy, onSave, onCancel, onDelete }: {
    goal: LifeEvent | null; scenarioId: number; events: LifeEvent[]; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void; onDelete?: () => void;
}) {
    const formId = useId();
    const [direction, setDirection] = useState<LifeEventKind>(goal?.direction ?? 'expense');
    const [name, setName] = useState(goal?.name ?? '');
    const [amount, setAmount] = useState(goal ? String(goal.target_amount) : '');
    const [target, setTarget] = useState(goal?.target_date ?? '');
    const [priority, setPriority] = useState<LifeEvent['priority']>(goal?.priority ?? 2);
    const [note, setNote] = useState(goal?.note ?? '');
    const [rate, setRate] = useState(goal?.interest_rate != null ? String(goal.interest_rate) : '');
    const [borrowingId, setBorrowingId] = useState<number | null>(goal?.borrowing_event_id ?? null);
    const [count, setCount] = useState(goal?.repeat_count != null ? String(goal.repeat_count) : '12');
    const [error, setError] = useState('');
    const borrowings = events.filter((event) => event.direction === 'borrowing' && event.id !== goal?.id);
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const value = Number(amount);
        if (busy) return;
        if (!name.trim() || !target || amount.trim() === '' || !Number.isFinite(value) || value < 0) {
            setError('名称・日付と0以上の金額を入力してください。');
            return;
        }
        if (direction === 'repayment' && (!borrowingId || !Number.isInteger(Number(count)) || Number(count) < 1)) {
            setError('返済する借入と、1以上の回数を入力してください。');
            return;
        }
        if (direction === 'borrowing' && rate.trim() !== '' && !(Number(rate) >= 0)) {
            setError('年利は0以上の数値で入力してください。');
            return;
        }
        setError('');
        const payload = {
            direction, name: name.trim(), target_amount: value, target_date: target, priority, note: note.trim() || null,
            interest_rate: direction === 'borrowing' ? Number(rate || 0) : null,
            borrowing_event_id: direction === 'repayment' ? borrowingId : null,
            repeat_count: direction === 'repayment' ? Number(count) : null,
        };
        onSave(() => goal ? updateGoal(goal.id, payload) : createGoal({ ...payload, scenario_id: scenarioId }));
    };
    return <form id={formId} onSubmit={submit} className="space-y-4">
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <fieldset className="space-y-2 md:col-span-2"><legend className="text-sm text-[var(--studio-text-muted)]">種別</legend><div role="group" aria-label="種別" className="inline-flex overflow-hidden rounded-md border border-[var(--studio-border)]">
                {(Object.keys(KIND_LABELS) as LifeEventKind[]).map((value) => <button key={value} type="button" aria-pressed={direction === value} onClick={() => setDirection(value)} className={`${buttonClass} rounded-none border-0 aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>{KIND_LABELS[value]}</button>)}
            </div></fieldset>
            <Field label="名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            {direction === 'repayment' && <Choice label="返済する借入" value={borrowingId} options={borrowings} required onChange={setBorrowingId} />}
            <Field label={direction === 'repayment' ? `毎月の返済額（${currency}）` : direction === 'expense' ? `目標額（${currency}）` : `金額（${currency}）`}
                help={direction === 'expense' ? 'どの口座からいくら払うかは、シミュレーションの「使用口座と積立設定」に「ライフイベントへの取り崩し」として記録します。' : undefined}><input required type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <Field label={direction === 'repayment' ? '返済の開始日' : '目標日'}><input required type="date" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            {direction === 'repayment' && <Field label="回数（か月）" help="開始日の月から毎月払います。残高を払い終えた後は払いません。"><input required type="number" min="1" max="1200" step="1" value={count} onChange={(event) => setCount(event.target.value)} className={inputClass} /></Field>}
            {direction === 'borrowing' && <Field label="年利（%）" help="返済のたびに、残高 × 年利 ÷ 12 の利息を先に払います。"><input inputMode="decimal" value={rate} placeholder="0" onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>}
            <Field label="優先度"><select value={priority} onChange={(event) => setPriority(Number(event.target.value) as LifeEvent['priority'])} className={inputClass}><option value={1}>高</option><option value={2}>中</option><option value={3}>低</option></select></Field>
            <div className="md:col-span-2"><Field label="メモ"><textarea value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field></div>
            {direction === 'repayment' && borrowings.length === 0 && <p className="text-xs text-[var(--studio-warning)] md:col-span-2">このシナリオに借入のイベントがありません。先に借入を作ってください。</p>}
            <EditorActions form={formId} busy={busy} onCancel={onCancel} onDelete={onDelete} />
        </fieldset>
    </form>;
}
