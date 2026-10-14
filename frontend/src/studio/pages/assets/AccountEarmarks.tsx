import { useReloadAction } from '../../components/useReloadAction';
import { useCallback, useState, type FormEvent } from 'react';
import { getAccountEarmarks } from '../../../api';
import type { Capsule } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { loadAllCapsules, saveAttachment, shareLabel } from './accountEarmarkFunding';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useResource } from '../../useResource';
import { Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';

const detachMessage = (capsuleName: string, accountName: string) =>
    `「${capsuleName}」は口座「${accountName}」から新たに資金を確保しなくなります。この口座で既に確保した額とその帰属は仕訳に残ります。紐づけを解除しますか？`;

function AttachmentChoice({ capsule, accountId, accountName, onSaved }: {
    capsule: Capsule; accountId: number; accountName: string; onSaved: () => void;
}) {
    const source = capsule.funding_sources?.find((row) => row.account_id === accountId);
    const [attached, setAttached] = useState(Boolean(source));
    const [share, setShare] = useState(source?.max_share_bp == null ? '' : String(source.max_share_bp / 100));
    const [saved, setSaved] = useState({ attached: Boolean(source), share });
    const [validation, setValidation] = useState('');
    const mutation = useMutation();
    const confirm = useConfirm();
    const [confirming, setConfirming] = useState(false);
    const changed = attached !== saved.attached || (attached && share !== saved.share);

    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (mutation.busy || confirming || !changed) return;
        const percent = share === '' ? null : Number(share);
        if (attached && percent !== null && (!Number.isFinite(percent) || percent < 0 || percent > 100
            || Math.abs(percent * 100 - Math.round(percent * 100)) > 1e-6)) {
            setValidation('上限は0〜100％（小数第2位まで）で入力してください。');
            return;
        }
        setValidation('');
        if (!attached) {
            setConfirming(true);
            const accepted = await confirm(detachMessage(capsule.name, accountName), '紐づけを解除', '取り置きの紐づけを解除');
            setConfirming(false);
            if (!accepted) return;
        }
        // Blank is uncapped; explicit zero is a zero-share cap.
        await mutation.run(async () => {
            await saveAttachment(capsule.id, accountId,
                attached ? (percent === null ? null : Math.round(percent * 100)) : undefined);
            // Refresh the account even if this overlay closed during the request.
            onSaved();
        }, '紐づけを保存しました。', () => setSaved({ attached, share }));
    };

    // Each attachment is saved independently; a shared footer would imply a batch write.
    return <form onSubmit={(event) => void submit(event)} className="space-y-2 rounded-md border border-[var(--studio-border)] p-3">
        <fieldset disabled={mutation.busy || confirming} className="flex flex-wrap items-end gap-3">
            <label className="flex min-w-40 flex-1 items-center gap-2 py-2 text-sm">
                <input type="checkbox" checked={attached} onChange={(event) => { setAttached(event.target.checked); setValidation(''); }} className="accent-[var(--studio-accent)]" />
                {capsule.name}
            </label>
            <div className="w-40"><Field label="上限（％・任意）"><input type="number" min="0" max="100" step="0.01" disabled={!attached} value={share} placeholder="上限なし" aria-label={`${capsule.name}の上限（％）`} onChange={(event) => { setShare(event.target.value); setValidation(''); }} className={inputClass} /></Field></div>
            <button type="submit" disabled={mutation.busy || confirming || !changed} aria-label={`${capsule.name}の紐づけを保存`} className={primaryClass}>{mutation.busy ? '保存中…' : '保存'}</button>
        </fieldset>
        <Feedback error={validation || mutation.error} message={mutation.message} />
    </form>;
}

function AttachmentEditor({ accountId, accountName, onSaved }: { accountId: number; accountName: string; onSaved: () => void }) {
    const capsules = useResource(loadAllCapsules);
    useReloadAction(capsules.reload, false, Boolean(capsules.error));
    return <div className="space-y-4">
        <p className="text-xs text-[var(--studio-text-muted)]">上限の空欄は上限なし、0％は利用不可です。同じ口座の上限の合計が100％を超えると保存できません。</p>
        <Feedback loading={capsules.loading} error={capsules.error} />
        {!capsules.loading && !capsules.error && capsules.data?.map((capsule) => <AttachmentChoice key={capsule.id} capsule={capsule} accountId={accountId} accountName={accountName} onSaved={onSaved} />)}
        {capsules.data?.length === 0 && <p className="text-sm text-[var(--studio-text-muted)]">取り置きはありません。取り置き画面から作成できます。</p>}
    </div>;
}

export default function AccountEarmarks({ accountId, accountName, disabled }: { accountId: number; accountName: string; disabled: boolean }) {
    const load = useCallback(() => getAccountEarmarks(accountId), [accountId]);
    const earmarks = useResource(load);
    const mutation = useMutation();
    const confirm = useConfirm();
    const [editing, setEditing] = useState(false);
    const [confirming, setConfirming] = useState(false);
    const busy = disabled || mutation.busy || confirming;
    const detach = async (capsuleId: number, capsuleName: string) => {
        if (busy) return;
        setConfirming(true);
        const accepted = await confirm(detachMessage(capsuleName, accountName), '紐づけを解除', '取り置きの紐づけを解除');
        setConfirming(false);
        if (!accepted) return;
        await mutation.run(() => saveAttachment(capsuleId, accountId, undefined), '取り置きの紐づけを解除しました。', earmarks.reload);
    };
    useReloadAction(earmarks.reload, Boolean(busy), Boolean(earmarks.error));
    return <div className="space-y-3">
        <Feedback loading={earmarks.loading} error={earmarks.error || mutation.error} message={mutation.message} />
        {earmarks.data && <table className="w-full text-left text-xs">
            <caption className="sr-only">{accountName}の取り置き</caption>
            <thead className="text-[var(--studio-text-muted)]"><tr><th scope="col" className="pb-2 font-medium">取り置き</th><th scope="col" className="pb-2 text-right font-medium">確保額</th><th scope="col" className="pb-2 text-right font-medium">上限</th><th scope="col" className="pb-2 text-right font-medium">操作</th></tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">{earmarks.data.map((earmark) => <tr key={earmark.capsule_id}>
                <th scope="row" className="py-2 font-normal">{earmark.capsule_name}</th>
                <td className="whitespace-nowrap py-2 text-right tabular-nums">{formatCurrency(earmark.claimed, earmark.currency)}</td>
                <td className="whitespace-nowrap py-2 text-right tabular-nums">{shareLabel(earmark.max_share_bp)}</td>
                <td className="py-2 text-right"><button type="button" disabled={busy || earmarks.loading || Boolean(earmarks.error)} onClick={() => void detach(earmark.capsule_id, earmark.capsule_name)} className={buttonClass}>紐づけを解除</button></td>
            </tr>)}</tbody>
        </table>}
        {earmarks.data?.length === 0 && <p className="text-sm text-[var(--studio-text-muted)]">紐づいている取り置きはありません。</p>}
        <button type="button" disabled={busy} onClick={() => setEditing(true)} className={buttonClass}>取り置きを紐づける</button>
        {editing && <Overlay title={`${accountName}に取り置きを紐づける`} onClose={() => setEditing(false)}><AttachmentEditor accountId={accountId} accountName={accountName} onSaved={earmarks.reload} /></Overlay>}
    </div>;
}
