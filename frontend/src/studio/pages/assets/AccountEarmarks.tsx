import { useCallback, useId, useState, type FormEvent } from 'react';
import { getAccountEarmarks, setCapsuleAccountClaim } from '../../../api';
import type { AccountEarmark, Capsule } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { loadAllCapsules, saveAttachment } from './accountEarmarkFunding';
import Overlay, { OverlayFooter } from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { assetErrorMessage, useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';
import { tr } from '../../i18n';

const detachMessage = (capsuleName: string, accountName: string) => tr(
    `「${capsuleName}」は口座「${accountName}」から新たに資金を確保しなくなります。この口座で既に確保した額とその帰属は仕訳に残ります。紐づけを解除しますか？`,
    `“${capsuleName}” will no longer set money aside from “${accountName}”. Amounts already set aside in this account, and their assignments, stay in the journal. Detach it?`,
);

interface AttachmentEditorProps {
    accountId: number; accountName: string; earmarks: AccountEarmark[];
    claimsPending: boolean; onSaved: (message: string) => void; onBusy: (busy: boolean) => void;
}

function ClaimEditor({ accountId, earmark, onSaved, onBack, onBusy }: {
    accountId: number; earmark: AccountEarmark; onSaved: (message: string) => void;
    onBack: () => void; onBusy: (busy: boolean) => void;
}) {
    const formId = useId();
    const [amount, setAmount] = useState(String(earmark.claimed));
    const mutation = useMutation();
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (mutation.busy) return;
        onBusy(true);
        try {
            // Balance, currency and funding-source validation belong to the server.
            await mutation.run(async () => {
                await setCapsuleAccountClaim(earmark.capsule_id, {
                    account_id: accountId, target_amount: Number(amount),
                });
                // A committed claim must refresh even if its editor was closed.
                onSaved(tr(`「${earmark.capsule_name}」の確保額を保存しました。`, `Saved the amount set aside for “${earmark.capsule_name}”.`));
            }, '', onBack);
        } finally {
            onBusy(false);
        }
    };
    return <form id={formId} onSubmit={(event) => void submit(event)} className="space-y-4">
        <button type="button" disabled={mutation.busy} onClick={onBack} className={buttonClass}>{tr('一覧に戻る', 'Back to the list')}</button>
        <p className="text-sm font-medium">{earmark.capsule_name}</p>
        <dl className="flex items-center justify-between gap-4 text-sm"><dt>{tr('確保額（現在）', 'Set aside (now)')}</dt><dd className="tabular-nums">{formatCurrency(earmark.claimed, earmark.currency)}</dd></dl>
        <Field label={tr(`確保額をこの金額に変更（${earmark.currency}）`, `Change the amount set aside to (${earmark.currency})`)}><input autoFocus required type="number" min="0" step="any" disabled={mutation.busy} value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
        <Feedback error={mutation.error} />
        <OverlayFooter><button type="submit" form={formId} disabled={mutation.busy} className={primaryClass}>{mutation.busy ? tr('保存中…', 'Saving…') : tr('保存', 'Save')}</button></OverlayFooter>
    </form>;
}

function AttachmentList({ capsules, accountId, accountName, earmarks, claimsPending, onSaved, onBusy }: AttachmentEditorProps & { capsules: Capsule[] }) {
    const formId = useId();
    const initial = () => new Set(capsules.filter((capsule) => capsule.funding_sources?.some((source) => source.account_id === accountId)).map((capsule) => capsule.id));
    const [selected, setSelected] = useState(initial);
    const [saved, setSaved] = useState(initial);
    const [confirming, setConfirming] = useState(false);
    const [message, setMessage] = useState('');
    const [editingClaim, setEditingClaim] = useState<AccountEarmark | null>(null);
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
            const accepted = await confirm(detachMessage(detaching.map((capsule) => capsule.name).join(tr('」「', '”, “')), accountName), tr('更新する', 'Update'), tr('取り置きの紐づけを解除', 'Detach earmarks'));
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
                            throw new Error(tr(`「${capsule.name}」の紐づけを更新できませんでした。${assetErrorMessage(failure)}`, `Could not update “${capsule.name}”. ${assetErrorMessage(failure)}`));
                        }
                    }
                    completed = true;
                } finally {
                    const message = [
                        attached.length ? tr(`紐づけました：${attached.join('、')}。`, `Attached: ${attached.join(', ')}.`) : '',
                        detached.length ? tr(`解除しました：${detached.join('、')}。`, `Detached: ${detached.join(', ')}.`) : '',
                    ].filter(Boolean).join(' ');
                    // Refresh even after an error: earlier capsule writes may have succeeded.
                    setMessage(message);
                    onSaved(message || (completed ? tr('紐づけの変更はありませんでした。', 'Nothing changed.') : ''));
                }
            }, '');
        } finally {
            onBusy(false);
        }
    };

    if (editingClaim) return <ClaimEditor key={editingClaim.capsule_id} accountId={accountId} earmark={editingClaim} onBusy={onBusy} onBack={() => setEditingClaim(null)} onSaved={(result) => { setMessage(result); onSaved(result); }} />;

    return <form id={formId} onSubmit={(event) => void submit(event)} className="space-y-3">
        <Feedback error={mutation.error} message={message} />
        <DataTable columns={[tr('取り置き', 'Earmark'), tr('確保額（現在）', 'Set aside (now)')]}>
            {capsules.length ? capsules.map((capsule) => {
                const earmark = earmarks.find((row) => row.capsule_id === capsule.id);
                // An unsaved checkbox cannot authorize an amount change; wait for
                // the attachment write and a fresh claim before enabling the row.
                const editable = saved.has(capsule.id) && selected.has(capsule.id) && earmark && !claimsPending && !busy;
                return <tr key={capsule.id} onClick={() => { if (editable) setEditingClaim(earmark); }} className={editable ? 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]' : ''}>
                    <th scope="row" className="px-5 py-3 font-normal"><div className="flex items-center gap-3">
                        <input type="checkbox" aria-label={tr(`${capsule.name}を紐づける`, `Attach ${capsule.name}`)} checked={selected.has(capsule.id)} disabled={busy} onClick={(event) => event.stopPropagation()} onChange={(event) => {
                            const checked = event.target.checked;
                            setSelected((previous) => {
                                const next = new Set(previous);
                                if (checked) next.add(capsule.id);
                                else next.delete(capsule.id);
                                return next;
                            });
                        }} className="accent-[var(--studio-accent)]" />
                        {saved.has(capsule.id) ? <button type="button" disabled={!editable} aria-label={tr(`${capsule.name}の確保額を変更`, `Change the amount set aside for ${capsule.name}`)} onClick={(event) => { event.stopPropagation(); if (editable) setEditingClaim(earmark); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{capsule.name}</button> : <span>{capsule.name}</span>}
                    </div></th>
                    {/* The existing endpoint only reports attached capsules; a missing claim is not zero. */}
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{earmark ? formatCurrency(earmark.claimed, earmark.currency) : <span aria-label={tr('確保額は確認できません', 'Amount set aside unknown')}>—</span>}</td>
                </tr>;
            }) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('取り置きはありません。', 'No earmarks.')}</td></tr>}
        </DataTable>
        <OverlayFooter><button type="submit" form={formId} disabled={busy || !changes.length} className={primaryClass}>{mutation.busy ? tr('更新中…', 'Updating…') : tr('更新', 'Update')}</button></OverlayFooter>
    </form>;
}

function AttachmentEditor(props: AttachmentEditorProps) {
    const capsules = useResource(loadAllCapsules);
    return <div className="space-y-4">
        <Feedback loading={capsules.loading} error={capsules.error} />
        {!capsules.loading && !capsules.error && capsules.data && <AttachmentList {...props} capsules={capsules.data} />}
    </div>;
}

export default function AccountEarmarks({ accountId, accountName, disabled, onReconcile }: { accountId: number; accountName: string; disabled: boolean; onReconcile: () => void }) {
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
        const accepted = await confirm(detachMessage(earmark.capsule_name, accountName), tr('紐づけを解除', 'Detach'), tr('取り置きの紐づけを解除', 'Detach earmarks'));
        setConfirming(false);
        if (!accepted) return;
        setMessage('');
        await mutation.run(() => saveAttachment(earmark.capsule_id, accountId, false), tr(`「${earmark.capsule_name}」の紐づけを解除しました。`, `Detached “${earmark.capsule_name}”.`), () => { setSelected(null); earmarks.reload(); });
    };
    return <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={onReconcile} className={buttonClass}>{tr('残高照合', 'Reconcile')}</button>
            <button type="button" disabled={locked} onClick={() => setEditing(true)} className={buttonClass}>{tr('取り置きを紐づける', 'Attach earmarks')}</button>
        </div>
        <Feedback loading={earmarks.loading} error={earmarks.error || mutation.error} message={message || mutation.message} />
        {earmarks.data && <DataTable columns={[tr('取り置き', 'Earmark'), tr('確保額（現在）', 'Set aside (now)')]}>
            {earmarks.data.length ? earmarks.data.map((earmark) => <tr key={earmark.capsule_id} onClick={() => { if (!locked) setSelected(earmark); }} className={locked ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]'}>
                <th scope="row" className="px-5 py-3 font-normal"><button type="button" disabled={locked} aria-haspopup="dialog" aria-label={tr(`${accountName}の「${earmark.capsule_name}」を開く`, `Open “${earmark.capsule_name}” in ${accountName}`)} onClick={(event) => { event.stopPropagation(); setSelected(earmark); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{earmark.capsule_name}</button></th>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(earmark.claimed, earmark.currency)}</td>
            </tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('紐づいている取り置きはありません。', 'No earmarks attached.')}</td></tr>}
        </DataTable>}
        {editing && <Overlay title={tr(`${accountName}に取り置きを紐づける`, `Attach earmarks to ${accountName}`)} onClose={() => setEditing(false)}>
            <Feedback loading={earmarks.loading} error={earmarks.error} />
            <AttachmentEditor accountId={accountId} accountName={accountName} earmarks={earmarks.data ?? []} claimsPending={earmarks.loading || Boolean(earmarks.error)} onBusy={setAttachmentBusy} onSaved={(result) => { setMessage(result); earmarks.reload(); }} />
        </Overlay>}
        {selected && <Overlay title={tr(`${accountName}の「${selected.capsule_name}」`, `“${selected.capsule_name}” in ${accountName}`)} onClose={() => setSelected(null)}>
            <Feedback error={mutation.error} />
            <dl className="flex items-center justify-between gap-4 text-sm"><dt>{tr('確保額（現在）', 'Set aside (now)')}</dt><dd className="tabular-nums">{formatCurrency(selected.claimed, selected.currency)}</dd></dl>
            <OverlayFooter><button type="button" disabled={locked} onClick={() => void detach(selected)} className={`${buttonClass} text-[var(--studio-danger)]`}>{mutation.busy ? tr('解除中…', 'Detaching…') : tr('紐づけを解除', 'Detach')}</button></OverlayFooter>
        </Overlay>}
    </div>;
}
