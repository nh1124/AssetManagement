import { useCallback, useId, useState } from 'react';
import { deleteHouseholdMember, getHouseholdMembers, saveHouseholdMember, type HouseholdMember, type MemberInput } from '../../api/lifeEventConditions';
import Overlay from '../components/Overlay';
import { useConfirm } from '../components/useConfirm';
import { formatDate } from '../datetime';
import { useResource } from '../useResource';
import { DataTable, EditorActions, Feedback, Field, RowActions } from './db/Database';
import { buttonClass, inputClass, useMutation } from './db/forms';
import { tr } from '../i18n';

function MemberEditor({ row, busy, onSave, onCancel }: { row: HouseholdMember | null; busy: boolean; onSave: (input: MemberInput) => void; onCancel: () => void }) {
    const form = useId();
    const [name, setName] = useState(row?.name ?? '');
    const [relation, setRelation] = useState(row?.relation ?? '');
    const [birthDate, setBirthDate] = useState(row?.birth_date ?? '');
    return <form id={form} onSubmit={(event) => { event.preventDefault(); if (!busy && name.trim()) onSave({ name: name.trim(), relation: relation.trim() || null, birth_date: birthDate }); }}>
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <Field label={tr('名前', 'Name')}><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('続柄', 'Relationship')}><input value={relation} onChange={(event) => setRelation(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('生年月日', 'Date of birth')}><input required type="date" value={birthDate} onChange={(event) => setBirthDate(event.target.value)} className={inputClass} /></Field>
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
    return <details className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <summary className="cursor-pointer text-sm font-semibold">{tr('世帯', 'Household')}</summary>
        <button type="button" disabled={locked || editor !== null} onClick={() => setEditor({ row: null })} className={buttonClass}>{tr('構成員を追加', 'Add member')}</button>
        <Feedback loading={resource.loading} error={resource.error || (!editor ? mutation.error : '')} message={mutation.message} />
        {resource.data && !resource.loading && !resource.error && <DataTable columns={[tr('名前', 'Name'), tr('続柄', 'Relationship'), tr('生年月日', 'Date of birth'), tr('操作', 'Actions')]}>
            {resource.data.map((row) => <tr key={row.id}>
                <th scope="row" className="px-5 py-3 font-medium">{row.name}</th><td className="px-5 py-3">{row.relation ?? '—'}</td><td className="px-5 py-3 tabular-nums">{formatDate(row.birth_date)}</td>
                <RowActions name={row.name} disabled={locked || editor !== null} onEdit={() => setEditor({ row })} onDelete={async () => {
                    if (!locked && await confirm(tr(`「${clientName}」の「${row.name}」を削除します。`, `Delete “${row.name}” from “${clientName}”.`), tr('構成員を削除', 'Delete member'))) void mutation.run(() => deleteHouseholdMember(row.id), tr('構成員を削除しました。', 'Member deleted.'), resource.reload);
                }} />
            </tr>)}
            {resource.data.length === 0 && <tr><td colSpan={4} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('構成員はありません。', 'No members.')}</td></tr>}
        </DataTable>}
        {editor && <Overlay title={editor.row ? tr('構成員を編集', 'Edit member') : tr('構成員を追加', 'Add member')} busy={mutation.busy} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><MemberEditor row={editor.row} busy={locked} onCancel={() => setEditor(null)} onSave={(input) => {
            if (!locked) void mutation.run(() => saveHouseholdMember(input, editor.row?.id), tr('構成員を保存しました。', 'Member saved.'), () => { setEditor(null); resource.reload(); });
        }} /></Overlay>}
    </details>;
}
