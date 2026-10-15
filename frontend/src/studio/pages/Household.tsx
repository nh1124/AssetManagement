import { useCallback, useId, useState } from 'react';
import { deleteHouseholdMember, getHouseholdMembers, saveHouseholdMember, type HouseholdMember, type MemberInput } from '../../api/lifeEventConditions';
import Overlay from '../components/Overlay';
import { useConfirm } from '../components/useConfirm';
import { useReloadAction } from '../components/useReloadAction';
import { formatDate } from '../datetime';
import { useResource } from '../useResource';
import { DataTable, EditorActions, Feedback, Field, RowActions } from './db/Database';
import { buttonClass, inputClass, useMutation } from './db/forms';

function MemberEditor({ row, busy, onSave, onCancel }: { row: HouseholdMember | null; busy: boolean; onSave: (input: MemberInput) => void; onCancel: () => void }) {
    const form = useId();
    const [name, setName] = useState(row?.name ?? '');
    const [relation, setRelation] = useState(row?.relation ?? '');
    const [birthDate, setBirthDate] = useState(row?.birth_date ?? '');
    return <form id={form} onSubmit={(event) => { event.preventDefault(); if (!busy && name.trim()) onSave({ name: name.trim(), relation: relation.trim() || null, birth_date: birthDate }); }}>
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <Field label="名前"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label="続柄"><input value={relation} onChange={(event) => setRelation(event.target.value)} className={inputClass} /></Field>
            <Field label="生年月日"><input required type="date" value={birthDate} onChange={(event) => setBirthDate(event.target.value)} className={inputClass} /></Field>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} />
    </form>;
}

export default function Household({ disabled, clientName }: { disabled: boolean; clientName?: string }) {
    const load = useCallback(() => getHouseholdMembers(), []);
    const resource = useResource(load);
    const mutation = useMutation();
    const confirm = useConfirm();
    const [editor, setEditor] = useState<{ row: HouseholdMember | null } | null>(null);
    const locked = disabled || !clientName || mutation.busy || resource.loading || Boolean(resource.error);
    useReloadAction(resource.reload, locked || editor !== null);
    return <details className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <summary className="cursor-pointer text-sm font-semibold">世帯</summary>
        <button type="button" disabled={locked || editor !== null} onClick={() => setEditor({ row: null })} className={buttonClass}>構成員を追加</button>
        <Feedback loading={resource.loading} error={resource.error || (!editor ? mutation.error : '')} message={mutation.message} />
        {resource.data && !resource.loading && !resource.error && <DataTable columns={['名前', '続柄', '生年月日', '操作']}>
            {resource.data.map((row) => <tr key={row.id}>
                <th scope="row" className="px-5 py-3 font-medium">{row.name}</th><td className="px-5 py-3">{row.relation ?? '—'}</td><td className="px-5 py-3 tabular-nums">{formatDate(row.birth_date)}</td>
                <RowActions name={row.name} disabled={locked || editor !== null} onEdit={() => setEditor({ row })} onDelete={async () => {
                    if (!locked && await confirm(`「${clientName}」の「${row.name}」を削除します。`, '構成員を削除')) void mutation.run(() => deleteHouseholdMember(row.id), '構成員を削除しました。', resource.reload);
                }} />
            </tr>)}
            {resource.data.length === 0 && <tr><td colSpan={4} className="px-5 py-4 text-[var(--studio-text-muted)]">構成員はありません。</td></tr>}
        </DataTable>}
        {editor && <Overlay title={editor.row ? '構成員を編集' : '構成員を追加'} onClose={() => { if (!mutation.busy) setEditor(null); }}><Feedback error={mutation.error} /><MemberEditor row={editor.row} busy={locked} onCancel={() => setEditor(null)} onSave={(input) => {
            if (!locked) void mutation.run(() => saveHouseholdMember(input, editor.row?.id), '構成員を保存しました。', () => { setEditor(null); resource.reload(); });
        }} /></Overlay>}
    </details>;
}
