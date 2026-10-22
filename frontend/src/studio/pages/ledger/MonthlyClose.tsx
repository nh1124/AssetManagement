import { useCallback, useState } from 'react';
import { closePeriod, getPeriodCloses, reopenPeriod } from '../../../api/periodCloses';
import { useClient } from '../../../context/ClientContext';
import { useConfirm } from '../../components/useConfirm';
import { formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { Feedback, Help } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';
import { tr } from '../../i18n';

const closeHelp = () => tr(
    '締められるのは終わった月だけです。記録を確認し終えたら締めます。締めは確認済みの目印で、締め後も記録・修正できます。',
    'Only a finished month can be closed. Close it once you have checked its records. A close marks the month as checked; you can still record and correct entries afterwards.',
);

function previousMonth(month: string): string {
    const [year, number] = month.split('-').map(Number);
    const date = new Date(year, number - 2, 1);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

/** The month check beside the ledger: only a finished month can be closed, as the backend enforces. */
export default function MonthlyClose({ period, currentPeriod, disabled, onBusy, onSelect }: {
    period: string;
    /** This month in the client's timezone; it and later months are not finished. */
    currentPeriod: string;
    disabled: boolean;
    onBusy: (busy: boolean) => void;
    onSelect: (period: string) => void;
}) {
    const { clientId, currentClient } = useClient();
    const timezone = useTimezone();
    const confirm = useConfirm();
    const load = useCallback(async () => ({ clientId, closes: await getPeriodCloses() }), [clientId]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [note, setNote] = useState('');
    const identified = currentClient?.id === clientId;
    const closes = resource.data?.clientId === clientId ? resource.data.closes : [];
    const finished = period < currentPeriod;
    const close = closes.find((row) => row.period === period);
    const locked = disabled || mutation.busy || resource.loading || Boolean(resource.error) || !identified || resource.data?.clientId !== clientId;
    const run = async () => {
        if (locked || !finished) return;
        const reopening = Boolean(close);
        const label = reopening ? tr('締めを解除', 'Reopen month') : tr('月を締める', 'Close month');
        const memo = note;
        const text = tr(
            `「${currentClient?.name}」の ${period} の${reopening ? '締めを解除します。' : '締めを記録します。'}\n締めは確認済みの目印であり、ロックではありません。締め後も記録・修正でき、締め後に作成した取引はデータ点検で報告されます。${!reopening && memo.trim() ? `\nメモ：${memo.trim()}` : ''}`,
            `${reopening ? 'Reopen' : 'Close'} ${period} for “${currentClient?.name}”.\nA close marks the month as checked; it is not a lock. You can still record and correct entries, and transactions created after the close are reported by the data check.${!reopening && memo.trim() ? `\nNote: ${memo.trim()}` : ''}`,
        );
        if (!(await confirm(text, label))) return;
        onBusy(true);
        try {
            await mutation.run(() => reopening ? reopenPeriod(period) : closePeriod(period, memo), reopening ? tr('締めを解除しました。', 'Month reopened.') : tr('月を締めました。', 'Month closed.'), resource.reload);
        } finally {
            onBusy(false);
        }
    };
    if (!finished) {
        const last = previousMonth(currentPeriod);
        const lastClosed = closes.some((row) => row.period === last);
        return <section className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] px-5 py-3 text-sm">
            <h2 className="flex items-center gap-1.5 font-semibold">{tr('月次締め', 'Monthly close')}<Help label={tr('月次締め', 'Monthly close')} text={closeHelp()} /></h2>
            {resource.data && <span>{last}{tr('：', ': ')}{lastClosed ? tr('締め済み', 'closed') : tr('未締め', 'not closed')}</span>}
            {resource.data && !lastClosed && <button type="button" disabled={disabled} onClick={() => onSelect(last)} className={buttonClass}>{tr(`${last} を確認する`, `Review ${last}`)}</button>}
            <Feedback error={resource.error} />
        </section>;
    }
    return <section className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">{tr('月次締め', 'Monthly close')}<Help label={tr('月次締め', 'Monthly close')} text={closeHelp()} below /></h2>
        <Feedback loading={resource.loading} error={resource.error || mutation.error} message={mutation.message} />
        {resource.error && <button type="button" onClick={resource.reload} className={buttonClass}>{tr('締め状況を再取得', 'Reload close status')}</button>}
        {close ? <p className="text-sm">{tr(`${period} は締め済み（${formatDate(close.closed_at, timezone)}）`, `${period} closed (${formatDate(close.closed_at, timezone)})`)}{close.note ? ` / ${close.note}` : ''}</p> : <label className="block space-y-2 text-sm"><span>{tr('締めのメモ（任意）', 'Note for the close (optional)')}</span><input value={note} disabled={locked} onChange={(event) => setNote(event.target.value)} className={inputClass} /></label>}
        <div className="flex justify-end"><button type="button" disabled={locked} onClick={run} className={buttonClass}>{close ? tr('締めを解除', 'Reopen month') : tr('月を締める', 'Close month')}</button></div>
    </section>;
}
