import Overlay, { OverlayFooter } from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { copyPeriodFullReplace } from '../../../api';
import { Feedback, Field } from '../db/Database';
import { inputClass, primaryClass, useMutation } from '../db/forms';

/** 月の予算をコピー, opened from the budget page's menu. */
export default function MonthCopy({ period, clientName, onBusy, onCopied, onClose }: {
    period: string; clientName?: string;
    onBusy: (busy: boolean) => void; onCopied: (message: string) => void; onClose: () => void;
}) {
    const formId = useId();
    const confirm = useConfirm();
    const [target, setTarget] = useState('');
    const mutation = useMutation();
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (mutation.busy || !clientName || !/^\d{4}-(0[1-9]|1[0-2])$/.test(target) || target === period) return;
        if (!(await confirm(`「${clientName}」の${period}の予算行を${target}へコピーしますか？\n${target}の既存の予算行はすべて置き換えられます。`, 'コピーする'))) return;
        onBusy(true);
        const message = `${period}の予算行を${target}へコピーしました。`;
        void mutation.run(() => copyPeriodFullReplace({ source_period: period, target_period: target }), message, () => onCopied(message)).finally(() => onBusy(false));
    };
    return <Overlay title={`${period}の予算をコピー`} help="保存済みの予算行をコピーし、コピー先の月の予算行を置き換えます。" busy={mutation.busy} onClose={onClose}><form id={formId} onSubmit={submit} className="space-y-3">
        <fieldset disabled={mutation.busy || !clientName} className="flex flex-wrap items-end gap-3">
            <Field label="コピー先の月"><input required type="month" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>
            <OverlayFooter><button type="submit" form={formId} disabled={mutation.busy || !clientName || !target || target === period} className={primaryClass}>{mutation.busy ? 'コピー中…' : 'コピー'}</button></OverlayFooter>
        </fieldset>
        <Feedback error={mutation.error} />
    </form></Overlay>;
}
