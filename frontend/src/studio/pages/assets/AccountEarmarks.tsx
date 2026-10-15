import { useCallback, useId, useState, type FormEvent } from 'react';
import { getAccountEarmarks } from '../../../api';
import type { AccountEarmark, Capsule } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { loadAllCapsules, saveAttachment } from './accountEarmarkFunding';
import Overlay, { OverlayFooter } from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { assetErrorMessage, useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { buttonClass, primaryClass, useMutation } from '../db/forms';

const detachMessage = (capsuleName: string, accountName: string) =>
    `「${capsuleName}」は口座「${accountName}」から新たに資金を確保しなくなります。この口座で既に確保した額とその帰属は仕訳に残ります。紐づけを解除しますか？`;

interface AttachmentEditorProps {
    accountId: number; accountName: string; earmarks: AccountEarmark[];
    onSaved: (message: string) => void; onComplete: () => void; onBusy: (busy: boolean) => void;
}

function AttachmentList({ capsules, accountId, accountName, earmarks, onSaved, onComplete, onBusy }: AttachmentEditorProps & { capsules: Capsule[] }) {
    const formId = useId();
    const initial = () => new Set(capsules.filter((capsule) => capsule.funding_sources?.some((source) => source.account_id === accountId)).map((capsule) => capsule.id));
    const [selected, setSelected] = useState(initial);
    const [saved, setSaved] = useState(initial);
    const [confirming, setConfirming] = useState(false);
    const [message, setMessage] = useState('');
    const mutation = useMutation();
    const confirm = useConfirm();
    const changes = capsules.filter((capsule) => selected.has(capsule.id) !== saved.has(capsule.id));
    const busy = mutation.busy || confirming;

    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || !changes.length) return;
        const detaching = changes.filter((capsule) => !selected.has(capsule.id));
        if (detaching.length) {
            setConfirming(true);
            const accepted = await confirm(detachMessage(detaching.map((capsule) => capsule.name).join('」「'), accountName), '更新する', '取り置きの紐づけを解除');
            setConfirming(false);
            if (!accepted) return;
        }
        setMessage('');
        onBusy(true);
        try {
            await mutation.run(async () => {
                const attached: string[] = [];
                const detached: string[] = [];
                let completed = false;
                try {
                    // Each capsule has its own PUT; remember successes so a retry
                    // only applies unfinished changes after a partial failure.
                    for (const capsule of changes) {
                        const attach = selected.has(capsule.id);
                        try {
                            if (await saveAttachment(capsule.id, accountId, attach)) (attach ? attached : detached).push(capsule.name);
                            setSaved((previous) => {
                                const next = new Set(previous);
                                if (attach) next.add(capsule.id);
                                else next.delete(capsule.id);
                                return next;
                            });
                        } catch (failure: unknown) {
                            throw new Error(`「${capsule.name}」の紐づけを更新できませんでした。${assetErrorMessage(failure)}`);
                        }
                    }
                    completed = true;
                } finally {
                    const message = [
                        attached.length ? `紐づけました：${attached.join('、')}。` : '',
                        detached.length ? `解除しました：${detached.join('、')}。` : '',
                    ].filter(Boolean).join(' ');
                    // Refresh even after an error: earlier capsule writes may have succeeded.
                    setMessage(message);
                    onSaved(message || (completed ? '紐づけの変更はありませんでした。' : ''));
                }
            }, '', onComplete);
        } finally {
            onBusy(false);
        }
    };

    return <form id={formId} onSubmit={(event) => void submit(event)} className="space-y-3">
        <Feedback error={mutation.error} message={message} />
        <DataTable columns={['取り置き', '確保額（現在）']}>
            {capsules.length ? capsules.map((capsule) => {
                const earmark = earmarks.find((row) => row.capsule_id === capsule.id);
                return <tr key={capsule.id}>
                    <th scope="row" className="px-5 py-3 font-normal"><label className="flex items-center gap-3">
                        <input type="checkbox" checked={selected.has(capsule.id)} disabled={busy} onChange={(event) => {
                            const checked = event.target.checked;
                            setSelected((previous) => {
                                const next = new Set(previous);
                                if (checked) next.add(capsule.id);
                                else next.delete(capsule.id);
                                return next;
                            });
                        }} className="accent-[var(--studio-accent)]" />{capsule.name}
                    </label></th>
                    {/* The existing endpoint only reports attached capsules; a missing claim is not zero. */}
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{earmark ? formatCurrency(earmark.claimed, earmark.currency) : <span aria-label="現在の確保額は確認できません">—</span>}</td>
                </tr>;
            }) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">取り置きはありません。</td></tr>}
        </DataTable>
        <OverlayFooter><button type="submit" form={formId} disabled={busy || !changes.length} className={primaryClass}>{mutation.busy ? '更新中…' : '更新'}</button></OverlayFooter>
    </form>;
}

function AttachmentEditor(props: AttachmentEditorProps) {
    const capsules = useResource(loadAllCapsules);
    return <div className="space-y-4">
        <Feedback loading={capsules.loading} error={capsules.error} />
        {!capsules.loading && !capsules.error && capsules.data && <AttachmentList {...props} capsules={capsules.data} />}
    </div>;
}

export default function AccountEarmarks({ accountId, accountName, disabled }: { accountId: number; accountName: string; disabled: boolean }) {
    // This endpoint has no as-of parameter, so claims remain explicitly current.
    const load = useCallback(() => getAccountEarmarks(accountId), [accountId]);
    const earmarks = useResource(load);
    const mutation = useMutation();
    const confirm = useConfirm();
    const [editing, setEditing] = useState(false);
    const [selected, setSelected] = useState<AccountEarmark | null>(null);
    const [confirming, setConfirming] = useState(false);
    const [attachmentBusy, setAttachmentBusy] = useState(false);
    const [message, setMessage] = useState('');
    const busy = disabled || mutation.busy || confirming || attachmentBusy;
    const locked = busy || earmarks.loading || Boolean(earmarks.error);
    const detach = async (earmark: AccountEarmark) => {
        if (locked) return;
        setConfirming(true);
        const accepted = await confirm(detachMessage(earmark.capsule_name, accountName), '紐づけを解除', '取り置きの紐づけを解除');
        setConfirming(false);
        if (!accepted) return;
        setMessage('');
        await mutation.run(() => saveAttachment(earmark.capsule_id, accountId, false), `「${earmark.capsule_name}」の紐づけを解除しました。`, () => { setSelected(null); earmarks.reload(); });
    };
    return <div className="space-y-3">
        <Feedback loading={earmarks.loading} error={earmarks.error || mutation.error} message={message || mutation.message} />
        {earmarks.data && <DataTable columns={['取り置き', '確保額（現在）']}>
            {earmarks.data.length ? earmarks.data.map((earmark) => <tr key={earmark.capsule_id} onClick={() => { if (!locked) setSelected(earmark); }} className={locked ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]'}>
                <th scope="row" className="px-5 py-3 font-normal"><button type="button" disabled={locked} aria-haspopup="dialog" aria-label={`${accountName}の「${earmark.capsule_name}」を開く`} onClick={(event) => { event.stopPropagation(); setSelected(earmark); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{earmark.capsule_name}</button></th>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(earmark.claimed, earmark.currency)}</td>
            </tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">紐づいている取り置きはありません。</td></tr>}
        </DataTable>}
        <button type="button" disabled={locked} onClick={() => setEditing(true)} className={buttonClass}>取り置きを紐づける</button>
        {editing && <Overlay title={`${accountName}に取り置きを紐づける`} onClose={() => setEditing(false)}><AttachmentEditor accountId={accountId} accountName={accountName} earmarks={earmarks.data ?? []} onBusy={setAttachmentBusy} onComplete={() => setEditing(false)} onSaved={(result) => { setMessage(result); earmarks.reload(); }} /></Overlay>}
        {selected && <Overlay title={`${accountName}の「${selected.capsule_name}」`} onClose={() => setSelected(null)}>
            <Feedback error={mutation.error} />
            <dl className="flex items-center justify-between gap-4 text-sm"><dt>確保額（現在）</dt><dd className="tabular-nums">{formatCurrency(selected.claimed, selected.currency)}</dd></dl>
            <OverlayFooter><button type="button" disabled={locked} onClick={() => void detach(selected)} className={`${buttonClass} text-[var(--studio-danger)]`}>{mutation.busy ? '解除中…' : '紐づけを解除'}</button></OverlayFooter>
        </Overlay>}
    </div>;
}
