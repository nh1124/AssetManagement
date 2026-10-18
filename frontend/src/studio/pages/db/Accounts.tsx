import Overlay from '../../components/Overlay';
import { useState } from 'react';
import { updateAccount } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { ActiveSwitch, DataTable, EditableRow, Feedback, RowTitle } from './Database';
import AccountEditor from './AccountEditor';
import { ACCOUNT_TYPES, INSTITUTIONS, ROLES, buttonClass, loadAccounts, useMutation, type DatabaseAccount } from './forms';

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
        `「${account.name}」を${account.is_active ? '無効' : '有効'}にしました。`,
        () => {
            resource.setData((previous) => previous?.map((row) => row.id === account.id ? { ...row, is_active: !account.is_active } : row) ?? null);
            resource.reload();
        },
    );
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div role="group" aria-label="表示する口座・勘定科目" className="inline-flex overflow-hidden rounded-md border border-[var(--studio-border)]">
                {([false, true] as const).map((value) => <button key={String(value)} type="button" aria-pressed={showInactive === value} onClick={() => setShowInactive(value)} className={`${buttonClass} rounded-none border-0 aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>{value ? '無効も表示' : '有効のみ'}</button>)}
            </div>
            <button type="button" disabled={disabled || editor !== null} onClick={() => setEditor({ account: null })} className={buttonClass}>新規作成</button>
        </div>
        <Feedback loading={resource.loading} error={mutation.error || resource.error} message={mutation.message} />
        {editor && resource.data && <Overlay title={editor.account ? `${editor.account.name}を編集` : '口座・勘定科目の新規作成'} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><AccountEditor key={editor.account?.id ?? 'new'} account={editor.account} accounts={resource.data} currency={currency} busy={disabled} onCancel={() => setEditor(null)} onSave={(action) => void mutation.run(action, '口座・勘定科目を保存しました。', () => { setEditor(null); resource.reload(); })} /></Overlay>}
        {resource.data && Object.entries(ACCOUNT_TYPES).map(([type, label]) => {
            const rows = accounts.filter((row) => row.account_type === type);
            return <section key={type} className="space-y-2"><h3 className="text-sm font-semibold">{label} <span className="font-normal text-[var(--studio-text-muted)]">{rows.length}件</span></h3>
                <DataTable columns={['名称', '制度区分', '役割', '役割の目標額', '期待年利', '親', '状態']}>
                    {rows.length ? rows.map((row) => <EditableRow key={row.id} disabled={disabled || editor !== null} onEdit={() => setEditor({ account: row })} className={row.is_active ? '' : 'opacity-50'}>
                        <RowTitle name={row.name} disabled={disabled || editor !== null} onEdit={() => setEditor({ account: row })}>{row.name}</RowTitle>
                        <td className="px-5 py-3">{INSTITUTIONS[row.institution ?? 'none']}{row.withdrawable_from_age != null && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">{row.withdrawable_from_age}歳から</span>}</td>
                        <td className="px-5 py-3">{ROLES[row.role]}</td><td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.role_target_amount == null ? '—' : formatCurrency(row.role_target_amount, currency)}</td><td className="px-5 py-3 tabular-nums">{row.expected_return == null ? '試算の年利' : `${row.expected_return}%`}</td><td className="px-5 py-3">{row.parent_id == null ? '—' : resource.data?.find((parent) => parent.id === row.parent_id)?.name ?? `#${row.parent_id}`}</td>
                        <td className="px-5 py-3"><ActiveSwitch name={row.name} active={row.is_active} disabled={disabled || editor !== null} onToggle={() => toggle(row)} /></td>
                    </EditableRow>) : <tr><td colSpan={7} className="px-5 py-4 text-[var(--studio-text-muted)]">登録はありません。</td></tr>}
                </DataTable>
            </section>;
        })}
    </section>;
}

export default function Accounts() {
    const { clientId, currentClient } = useClient();
    return <AccountsForClient key={clientId} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
