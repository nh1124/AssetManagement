import { useId, useState, type FormEvent } from 'react';
import { createCapsule, updateCapsule } from '../../../api';
import type { Capsule } from '../../../types';
import { Field } from '../db/Database';
import { OverlayFooter } from '../../components/Overlay';
import { inputClass, primaryClass } from '../db/forms';
import { tr } from '../../i18n';

/** An earmark's own fields. Which goal events it counts toward is the goal's 実績管理の設定. */
export default function EarmarkEditor({ capsule, currency, busy, onSave }: {
    capsule: Capsule | null; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void;
}) {
    const formId = useId();
    const [name, setName] = useState(capsule?.name ?? '');
    const [target, setTarget] = useState(String(capsule?.target_amount ?? 0));
    const [monthly, setMonthly] = useState(String(capsule?.monthly_contribution ?? 0));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || !name.trim()) return;
        const fields = { name: name.trim(), target_amount: Number(target), monthly_contribution: Number(monthly) };
        onSave(() => capsule ? updateCapsule(capsule.id, fields) : createCapsule(fields));
    };
    return <form id={formId} onSubmit={submit} className="space-y-4">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label={tr('名称', 'Name')}><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label={tr(`目標額（${currency}）`, `Target (${currency})`)}><input required type="number" min="0" step="any" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            <Field label={tr(`月額（${currency}）`, `Monthly (${currency})`)}><input required type="number" min="0" step="any" value={monthly} onChange={(event) => setMonthly(event.target.value)} className={inputClass} /></Field>
        </fieldset>
        <OverlayFooter><button type="submit" form={formId} disabled={busy} className={primaryClass}>{busy ? tr('保存中…', 'Saving…') : tr('保存', 'Save')}</button></OverlayFooter>
    </form>;
}
