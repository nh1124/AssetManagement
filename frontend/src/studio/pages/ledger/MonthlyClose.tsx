import { useCallback, useState } from 'react';
import { closePeriod, getPeriodCloses, reopenPeriod } from '../../../api/periodCloses';
import { useClient } from '../../../context/ClientContext';
import { useConfirm } from '../../components/useConfirm';
import { formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { Feedback, Help } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';

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
        const label = reopening ? '締めを解除' : '月を締める';
        const memo = note;
        if (!(await confirm(`「${currentClient?.name}」の ${period} の${reopening ? '締めを解除します。' : '締めを記録します。'}\n締めは確認済みの目印であり、ロックではありません。締め後も記録・修正でき、締め後に作成した取引はデータ点検で報告されます。${!reopening && memo.trim() ? `\nメモ：${memo.trim()}` : ''}`, label))) return;
        onBusy(true);
        try {
            await mutation.run(() => reopening ? reopenPeriod(period) : closePeriod(period, memo), reopening ? '締めを解除しました。' : '月を締めました。', resource.reload);
        } finally {
            onBusy(false);
        }
    };
    if (!finished) {
        const last = previousMonth(currentPeriod);
        const lastClosed = closes.some((row) => row.period === last);
        return <section className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] px-5 py-3 text-sm">
            <h2 className="flex items-center gap-1.5 font-semibold">月次締め<Help label="月次締め" text="締められるのは終わった月だけです。記録を確認し終えたら締めます。締めは確認済みの目印で、締め後も記録・修正できます。" /></h2>
            {resource.data && <span>{last}：{lastClosed ? '締め済み' : '未締め'}</span>}
            {resource.data && !lastClosed && <button type="button" disabled={disabled} onClick={() => onSelect(last)} className={buttonClass}>{last} を確認する</button>}
            <Feedback error={resource.error} />
        </section>;
    }
    return <section className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">月次締め<Help label="月次締め" text="締められるのは終わった月だけです。記録を確認し終えたら締めます。締めは確認済みの目印で、締め後も記録・修正できます。" below /></h2>
        <Feedback loading={resource.loading} error={resource.error || mutation.error} message={mutation.message} />
        {resource.error && <button type="button" onClick={resource.reload} className={buttonClass}>締め状況を再取得</button>}
        {close ? <p className="text-sm">{period} は締め済み（{formatDate(close.closed_at, timezone)}）{close.note ? ` ／ ${close.note}` : ''}</p> : <label className="block space-y-2 text-sm"><span>締めのメモ（任意）</span><input value={note} disabled={locked} onChange={(event) => setNote(event.target.value)} className={inputClass} /></label>}
        <div className="flex justify-end"><button type="button" disabled={locked} onClick={run} className={buttonClass}>{close ? '締めを解除' : '月を締める'}</button></div>
    </section>;
}
