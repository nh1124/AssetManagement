import { useConfirm } from '../../components/useConfirm';
import { useState, type FormEvent } from 'react';
import { createCapsule, createGoalCapsule, updateCapsule } from '../../../api';
import type { Capsule, LifeEvent } from '../../../types';
import { Choice, EditorActions, Field } from '../db/Database';
import { inputClass } from '../db/forms';

export default function EarmarkEditor({ capsule, capsules, goals, currency, busy, onSave, onCancel }: {
    capsule: Capsule | null; capsules: Capsule[]; goals: LifeEvent[]; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const confirm = useConfirm();
    const [name, setName] = useState(capsule?.name ?? '');
    const [target, setTarget] = useState(String(capsule?.target_amount ?? 0));
    const [monthly, setMonthly] = useState(String(capsule?.monthly_contribution ?? 0));
    const [goalId, setGoalId] = useState<number | null>(null);
    const existing = capsules.find((row) => row.life_event_id === goalId);
    const chooseGoal = (id: number | null) => {
        setGoalId(id);
        const row = capsules.find((entry) => entry.life_event_id === id);
        const goal = goals.find((entry) => entry.id === id);
        if (goal) { setName(row?.name ?? goal.name); setTarget(String(row?.target_amount ?? goal.target_amount)); setMonthly(String(row?.monthly_contribution ?? 0)); }
    };
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || !name.trim()) return;
        if (!capsule && goalId && existing && !(await confirm(`このゴールには「${existing.name}」の取り置きが既にあります。既存の取り置きを使い、名称・目標額・月額を入力内容に変更しますか？`, '変更する'))) return;
        const fields = { name: name.trim(), target_amount: Number(target), monthly_contribution: Number(monthly) };
        onSave(async () => {
            if (capsule) return updateCapsule(capsule.id, fields);
            if (goalId !== null) {
                // The goal endpoint reuses its capsule; apply the reviewed fields to that record.
                const linked = await createGoalCapsule(goalId);
                return updateCapsule(linked.id, fields);
            }
            return createCapsule(fields);
        });
    };
    return <form onSubmit={submit} className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label={`目標額（${currency}）`}><input required type="number" min="0" step="any" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            <Field label={`月額（${currency}）`}><input required type="number" min="0" step="any" value={monthly} onChange={(event) => setMonthly(event.target.value)} className={inputClass} /></Field>
            {!capsule && <Choice label="紐づけるゴール（任意）" value={goalId} options={goals} onChange={chooseGoal} />}
            {!capsule && existing && goalId !== null && <p className="text-xs text-[var(--studio-text-muted)] md:col-span-2">このゴールの既存の取り置き「{existing.name}」を編集します。貯蓄と資金計画は残ります。</p>}
            <EditorActions busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}
