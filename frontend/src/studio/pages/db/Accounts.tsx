import Overlay from '../../components/Overlay';
import { useState } from 'react';
import { updateAccount } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { useResource } from '../../useResource';
import { ActiveSwitch, DataTable, EditableRow, Feedback, RowTitle } from './Database';
import AccountEditor from './AccountEditor';
import { ACCOUNT_TYPES, buttonClass, loadAccounts, useMutation, type DatabaseAccount } from './forms';
import { tr } from '../../i18n';

function AccountsForClient({ currency }: { currency: string }) {
    const resource = useResource(loadAccounts);
    const mutation = useMutation();
    const [editor, setEditor] = useState<{ account: DatabaseAccount | null } | null>(null);
    const [showInactive, setShowInactive] = useState(false);
    const accounts = (resource.data ?? []).filter((row) => showInactive || row.is_active);
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy;
    // Archiving keeps the record: an account named by a journal entry cannot disappear.
    const toggle = (account: DatabaseAccount) => void mutation.run(
        () => updateAccount(account.id, { is_active: !account.is_active }),
        tr(`「${account.name}」を${account.is_active ? '無効' : '有効'}にしました。`, `“${account.name}” ${account.is_active ? 'deactivated' : 'activated'}.`),
        () => {
            resource.setData((previous) => previous?.map((row) => row.id === account.id ? { ...row, is_active: !account.is_active } : row) ?? null);
            resource.reload();
        },
    );
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div role="group" aria-label={tr('表示する口座・勘定科目', 'Accounts to show')} className="inline-flex overflow-hidden rounded-md border border-[var(--studio-border)]">
                {([false, true] as const).map((value) => <button key={String(value)} type="button" aria-pressed={showInactive === value} onClick={() => setShowInactive(value)} className={`${buttonClass} rounded-none border-0 aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>{value ? tr('無効も表示', 'Include inactive') : tr('有効のみ', 'Active only')}</button>)}
            </div>
            <button type="button" disabled={disabled || editor !== null} onClick={() => setEditor({ account: null })} className={buttonClass}>{tr('新規作成', 'New')}</button>
        </div>
        <Feedback loading={resource.loading} error={mutation.error || resource.error} message={mutation.message} />
        {editor && resource.data && <Overlay title={editor.account ? tr(`${editor.account.name}を編集`, `Edit ${editor.account.name}`) : tr('口座・勘定科目の新規作成', 'New account')} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><AccountEditor key={editor.account?.id ?? 'new'} account={editor.account} currency={currency} busy={disabled} onCancel={() => setEditor(null)} onSave={(action) => void mutation.run(action, tr('口座・勘定科目を保存しました。', 'Account saved.'), () => { setEditor(null); resource.reload(); })} /></Overlay>}
        {resource.data && Object.entries(ACCOUNT_TYPES).map(([type, label]) => {
            const rows = accounts.filter((row) => row.account_type === type);
            return <section key={type} className="space-y-2"><h3 className="text-sm font-semibold">{label} <span className="font-normal text-[var(--studio-text-muted)]">{tr(`${rows.length}件`, `${rows.length}`)}</span></h3>
                <DataTable columns={[tr('名称', 'Name'), tr('状態', 'Status')]}>
                    {rows.length ? rows.map((row) => <EditableRow key={row.id} disabled={disabled || editor !== null} onEdit={() => setEditor({ account: row })} className={row.is_active ? '' : 'opacity-50'}>
                        <RowTitle name={row.name} disabled={disabled || editor !== null} onEdit={() => setEditor({ account: row })}>{row.name}</RowTitle>
                        <td className="px-5 py-3"><ActiveSwitch name={row.name} active={row.is_active} disabled={disabled || editor !== null} onToggle={() => toggle(row)} /></td>
                    </EditableRow>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('登録はありません。', 'None yet.')}</td></tr>}
                </DataTable>
            </section>;
        })}
    </section>;
}

export default function Accounts() {
    const { clientId, currentClient } = useClient();
    return <AccountsForClient key={clientId} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
