import { useCallback, useState } from 'react';
import { closePeriod, getPeriodCloses, reopenPeriod } from '../../../api/periodCloses';
import { useClient } from '../../../context/ClientContext';
import { useConfirm } from '../../components/useConfirm';
import { formatDate, useTimezone } from '../../datetime';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';

export default function MonthlyClose({ period, disabled, onBusy }: { period: string; disabled: boolean; onBusy: (busy: boolean) => void }) {
    const { clientId, currentClient } = useClient();
    const timezone = useTimezone();
    const confirm = useConfirm();
    const load = useCallback(async () => ({ clientId, closes: await getPeriodCloses() }), [clientId]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [note, setNote] = useState('');
    const identified = currentClient?.id === clientId;
    const close = resource.data?.clientId === clientId ? resource.data.closes.find((row) => row.period === period) : undefined;
    const locked = disabled || mutation.busy || resource.loading || Boolean(resource.error) || !identified || resource.data?.clientId !== clientId;
    const run = async () => {
        if (locked) return;
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
    return <section className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <h2 className="text-sm font-semibold">月次締め</h2>
        <Feedback loading={resource.loading} error={resource.error || mutation.error} message={mutation.message} />
        {resource.error && <button type="button" onClick={resource.reload} className={buttonClass}>締め状況を再取得</button>}
        {close ? <p className="text-sm">{period} は締め済み（{formatDate(close.closed_at, timezone)}）{close.note ? ` ／ ${close.note}` : ''}</p> : <label className="block space-y-2 text-sm"><span>締めのメモ（任意）</span><input value={note} disabled={locked} onChange={(event) => setNote(event.target.value)} className={inputClass} /></label>}
        <p className="text-xs text-[var(--studio-text-muted)]">締めは確認済みの目印です。締め後も記録・修正できます。</p>
        <button type="button" disabled={locked} onClick={run} className={buttonClass}>{close ? '締めを解除' : '月を締める'}</button>
    </section>;
}
