import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useCallback, useId, useState, type FormEvent } from 'react';
import { createMilestone, deleteMilestone, getMilestones, updateMilestone } from '../../../api';
import type { Milestone } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, EditorActions, Feedback, Field, RowActions } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';
import { clientToday, formatDate, useTimezone } from '../../datetime';

function MilestoneEditor({ row, goalId, currency, busy, onSave, onCancel }: {
    row: Milestone | null; goalId: number; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const formId = useId();
    const timezone = useTimezone();
    const [date, setDate] = useState(row?.date ?? clientToday(timezone));
    const [amount, setAmount] = useState(String(row?.target_amount ?? 0));
    const [note, setNote] = useState(row?.note ?? '');
    const [active, setActive] = useState(row?.is_active_plan !== false);
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy) return;
        const payload = { date, target_amount: Number(amount), note: note.trim(), is_active_plan: active };
        onSave(() => row ? updateMilestone(row.id, payload) : createMilestone({ ...payload, life_event_id: goalId }));
    };
    return <form id={formId} onSubmit={submit} className="rounded-lg border border-[var(--studio-border)] p-5">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="予定日"><input required type="date" value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} /></Field>
            <Field label={`計画額（${currency}）`}><input required type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <Field label="メモ"><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />進捗計算に採用する</label>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}

export default function Milestones({ goalId, currency, disabled, onChanged, onBusy }: {
    goalId: number; currency: string; disabled: boolean; onChanged: () => void; onBusy: (busy: boolean) => void;
}) {
    const confirm = useConfirm();
    const load = useCallback(() => getMilestones(goalId), [goalId]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [editor, setEditor] = useState<{ row: Milestone | null } | null>(null);
    const locked = disabled || resource.loading || Boolean(resource.error) || mutation.busy;
    const run = (action: () => Promise<unknown>, message: string, close = false) => {
        if (locked) return;
        onBusy(true);
        void mutation.run(action, message, () => { if (close) setEditor(null); resource.reload(); onChanged(); }).finally(() => onBusy(false));
    };
    return <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2">
            <button type="button" disabled={locked || editor !== null} onClick={() => setEditor({ row: null })} className={buttonClass}>新しいマイルストーン</button>
        </div></div>
        <p className="text-xs text-[var(--studio-text-muted)]">採用中の行を進捗計算に使います。シナリオを採用すると、手動で編集したものを含む現在のマイルストーンが置き換わります。</p>
        <Feedback loading={resource.loading} error={resource.error} />
        <Feedback error={mutation.error} message={mutation.message} />
        {editor && <Overlay title={editor.row ? 'マイルストーンを編集' : '新しいマイルストーン'} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><MilestoneEditor key={editor.row?.id ?? 'new'} row={editor.row} goalId={goalId} currency={currency} busy={locked} onCancel={() => setEditor(null)} onSave={(action) => run(action, 'マイルストーンを保存しました。', true)} /></Overlay>}
        {resource.data && <DataTable columns={['予定日', '計画額', 'メモ', '進捗計算に採用', '操作']}>
            {resource.data.length ? resource.data.map((row) => <tr key={row.id}>
                <th scope="row" className="whitespace-nowrap px-5 py-3 font-normal">{formatDate(row.date)}</th>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.target_amount, currency)}</td>
                <td className="px-5 py-3">{row.note || '—'}</td>
                <td className="px-5 py-3"><label className="flex items-center gap-2"><input type="checkbox" checked={row.is_active_plan !== false} disabled={locked || editor !== null} aria-label={`${row.date}のマイルストーンを進捗計算に採用`} onChange={(event) => run(() => updateMilestone(row.id, { is_active_plan: event.target.checked }), '採用状態を変更しました。')} />{row.is_active_plan === false ? '参考' : '採用中'}</label></td>
                <RowActions name={`${row.date}のマイルストーン`} disabled={locked || editor !== null} onEdit={() => setEditor({ row })} onDelete={async () => { if ((await confirm(`${row.date}のマイルストーン（${formatCurrency(row.target_amount, currency)}）を削除しますか？`, '削除する'))) run(() => deleteMilestone(row.id), 'マイルストーンを削除しました。'); }} />
            </tr>) : <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">マイルストーンはありません。</td></tr>}
        </DataTable>}
    </section>;
}
