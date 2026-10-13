import { useState, type FormEvent } from 'react';
import { copyPeriodFullReplace } from '../../../api';
import { Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';

export default function MonthCopy({ period, disabled, clientName, onBusy, onCopied }: {
    period: string; disabled: boolean; clientName?: string;
    onBusy: (busy: boolean) => void; onCopied: () => void;
}) {
    const [target, setTarget] = useState('');
    const mutation = useMutation();
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || mutation.busy || !clientName || !/^\d{4}-(0[1-9]|1[0-2])$/.test(target) || target === period) return;
        if (!window.confirm(`「${clientName}」の${period}の予算行を${target}へコピーしますか？\n${target}の既存の予算行はすべて置き換えられます。`)) return;
        onBusy(true);
        // Omitting plan_id uses the same default plan as the monthly screen.
        void mutation.run(() => copyPeriodFullReplace({ source_period: period, target_period: target }), `${period}の予算行を${target}へコピーしました。`, onCopied).finally(() => onBusy(false));
    };
    return <form onSubmit={submit} className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
        <fieldset disabled={disabled || mutation.busy} className="flex flex-wrap items-end gap-3">
            <p className="pb-2 text-sm">{period}の予算をコピー</p>
            <Field label="コピー先の月"><input required type="month" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            <button type="submit" disabled={!target || target === period} className={buttonClass}>{mutation.busy ? 'コピー中…' : 'コピー'}</button>
        </fieldset>
        <p className="text-xs text-[var(--studio-text-muted)]">保存済みの予算行をコピーし、コピー先の行を置き換えます。各月の予算設定は一つです。</p>
        <Feedback error={mutation.error} message={mutation.message} />
    </form>;
}
