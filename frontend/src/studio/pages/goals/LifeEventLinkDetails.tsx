import { useId, useState } from 'react';
import { createLifeEventLink, deleteLifeEventLink, type LifeEventLink } from '../../../api/lifeEventGraph';
import type { LifeEvent } from '../../../types';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';

export default function LifeEventLinkDetails({ edge, events, clientName, onReload, onClose }: {
    edge: LifeEventLink; events: LifeEvent[]; clientName: string;
    onReload: () => void; onClose: () => void;
}) {
    const form = useId();
    const confirm = useConfirm();
    const mutation = useMutation();
    const [offset, setOffset] = useState(edge.offset_months);
    const [deleted, setDeleted] = useState(false);
    const source = events.find((event) => event.id === edge.from_event_id)?.name ?? `#${edge.from_event_id}`;
    const target = events.find((event) => event.id === edge.to_event_id)?.name ?? `#${edge.to_event_id}`;
    const changed = offset !== edge.offset_months;
    const done = () => { onClose(); onReload(); };

    return <Overlay title="接続" onClose={() => { if (!mutation.busy) onClose(); }} footer={<>
        {!deleted && <button type="button" disabled={mutation.busy} className={`${buttonClass} mr-auto text-[var(--studio-danger)]`} onClick={() => {
            void (async () => {
                if (await confirm(`「${clientName}」の「${source}」から「${target}」への接続を削除します。`, '削除')) {
                    await mutation.run(() => deleteLifeEventLink(edge.id), '接続を削除しました。', done);
                }
            })();
        }}>削除</button>}
        <button type="submit" form={form} disabled={mutation.busy || (!changed && !deleted)} className={primaryClass}>
            {mutation.busy ? '保存中…' : deleted ? '再作成' : '削除して再作成'}
        </button>
    </>}>
        <Feedback error={mutation.error} />
        {deleted && mutation.error && (
            // The replacement is two requests and the first one succeeded. Saying so
            // is the difference between a retry and a connection the user thinks is
            // still there.
            <p className="text-sm text-[var(--studio-danger)]">
                元の接続は削除済みで、作り直しに失敗しました。もう一度保存すると作り直します。
            </p>
        )}
        <form id={form} className="space-y-4" onSubmit={(event) => {
            event.preventDefault();
            if (mutation.busy || (!changed && !deleted)) return;
            void mutation.run(async () => {
                // The API has no update operation; preserve the note across replacement.
                if (!deleted) {
                    await deleteLifeEventLink(edge.id);
                    setDeleted(true);
                }
                try {
                    await createLifeEventLink({ from_event_id: edge.from_event_id, to_event_id: edge.to_event_id, kind: 'after', offset_months: offset, note: edge.note });
                } catch (failure: unknown) {
                    // A failed second request has already removed the old edge. Refresh and allow creation to be retried.
                    onReload();
                    throw failure;
                }
            }, '接続を変更しました。', done);
        }}>
            <fieldset disabled={mutation.busy} className="grid gap-4 sm:grid-cols-2">
                <Field label="元のイベント"><span className="block">{source}</span></Field>
                <Field label="次のイベント"><span className="block">{target}</span></Field>
                <Field label="元のイベントからの月数（0＝目標日）"><input type="number" required step="1" value={offset} onChange={(event) => setOffset(Number(event.target.value))} className={inputClass} /></Field>
            </fieldset>
            {/* This operation is two requests, so the user must see its non-atomic state. */}
            <p role="status" className="text-xs text-[var(--studio-text-muted)]">{deleted ? '接続は削除済みです。再作成してください。' : '変更は接続を削除して再作成します。'}</p>
        </form>
    </Overlay>;
}
