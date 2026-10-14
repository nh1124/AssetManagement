import Overlay, { OverlayFooter } from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { copyPeriodFullReplace } from '../../../api';
import { Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';

export default function MonthCopy({ period, disabled, clientName, onBusy, onCopied }: {
    period: string; disabled: boolean; clientName?: string;
    onBusy: (busy: boolean) => void; onCopied: () => void;
}) {
    const formId = useId();
    const confirm = useConfirm();
    const [open, setOpen] = useState(false);
    const [target, setTarget] = useState('');
    const mutation = useMutation();
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || mutation.busy || !clientName || !/^\d{4}-(0[1-9]|1[0-2])$/.test(target) || target === period) return;
        if (!(await confirm(`「${clientName}」の${period}の予算行を${target}へコピーしますか？\n${target}の既存の予算行はすべて置き換えられます。`, 'コピーする'))) return;
        onBusy(true);
        // Omitting plan_id uses the same default plan as the monthly screen.
        void mutation.run(() => copyPeriodFullReplace({ source_period: period, target_period: target }), `${period}の予算行を${target}へコピーしました。`, () => { setOpen(false); onCopied(); }).finally(() => onBusy(false));
    };
    return <><button type="button" disabled={disabled || mutation.busy} onClick={() => setOpen(true)} className={buttonClass}>月の予算をコピー</button>
        <Feedback message={mutation.message} />
        {open && <Overlay title={`${period}の予算をコピー`} onClose={() => setOpen(false)}><form id={formId} onSubmit={submit} className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
        <fieldset disabled={disabled || mutation.busy} className="flex flex-wrap items-end gap-3">
            <Field label="コピー先の月"><input required type="month" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            <OverlayFooter><button type="submit" form={formId} disabled={disabled || mutation.busy || !target || target === period} className={primaryClass}>{mutation.busy ? 'コピー中…' : 'コピー'}</button></OverlayFooter>
        </fieldset>
        <p className="text-xs text-[var(--studio-text-muted)]">保存済みの予算行をコピーし、コピー先の行を置き換えます。</p>
        <Feedback error={mutation.error} message={mutation.message} />
    </form></Overlay>}</>;
}
