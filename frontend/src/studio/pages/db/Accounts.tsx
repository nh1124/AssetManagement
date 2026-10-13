import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useState, type FormEvent } from 'react';
import { createAccount, deleteAccount, updateAccount } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { AccountRole } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { Choice, DataTable, EditorActions, Feedback, Field, RowActions } from './Database';
import { ACCOUNT_TYPES, ROLES, buttonClass, inputClass, loadAccounts, useMutation, type DatabaseAccount } from './forms';

function AccountEditor({ account, accounts, currency, busy, onSave, onCancel }: {
    account: DatabaseAccount | null; accounts: DatabaseAccount[]; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const [name, setName] = useState(account?.name ?? '');
    const [type, setType] = useState<DatabaseAccount['account_type']>(account?.account_type ?? 'asset');
    const [role, setRole] = useState<AccountRole>(account?.role ?? 'unassigned');
    const [target, setTarget] = useState(account?.role_target_amount == null ? '' : String(account.role_target_amount));
    const [expectedReturn, setExpectedReturn] = useState(String(account?.expected_return ?? 0));
    const [parent, setParent] = useState<number | null>(account?.parent_id ?? null);
    const excluded = new Set<number>(account ? [account.id] : []);
    // Exclude descendants as well as self so the parent picker cannot create a cycle.
    let previousSize = -1;
    while (previousSize !== excluded.size) {
        previousSize = excluded.size;
        for (const row of accounts) if (row.parent_id != null && excluded.has(row.parent_id)) excluded.add(row.id);
    }
    const parents = accounts.filter((row) => row.account_type === type && !excluded.has(row.id));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!name.trim() || !Number.isFinite(Number(expectedReturn))) return;
        // Balances are journal-owned; only these editable attributes are sent.
        const payload = { name: name.trim(), role, expected_return: Number(expectedReturn), parent_id: parent };
        onSave(() => account
            ? updateAccount(account.id, { ...payload, role_target_amount: target === '' ? null : Number(target) })
            : createAccount({ ...payload, account_type: type }));
    };
    return <form onSubmit={submit} className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label="種別"><select disabled={Boolean(account)} value={type} onChange={(event) => { setType(event.target.value as DatabaseAccount['account_type']); setParent(null); }} className={inputClass}>{Object.entries(ACCOUNT_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Field label="役割"><select value={role} onChange={(event) => setRole(event.target.value as AccountRole)} className={inputClass}>{Object.entries(ROLES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Field label="期待年利（%）"><input required type="number" step="any" value={expectedReturn} onChange={(event) => setExpectedReturn(event.target.value)} className={inputClass} /></Field>
            {account && <Field label={`役割の目標額（${currency}）`}><input type="number" min="0" step="any" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>}
            <Choice label="親の口座・勘定科目" value={parent} options={parents} onChange={setParent} />
            <EditorActions busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}

function AccountsForClient({ currency }: { currency: string }) {
    const confirm = useConfirm();
    const resource = useResource(loadAccounts);
    const mutation = useMutation();
    const [editor, setEditor] = useState<{ account: DatabaseAccount | null } | null>(null);
    const accounts = resource.data ?? [];
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy;
    const remove = async (account: DatabaseAccount) => {
        // The server archives rather than erases: an account named by a journal
        // entry cannot disappear. Restoring it is the toggle on 資産 > 口座.
        if (disabled || !(await confirm(`「${account.name}」を無効にしますか？\n`
            + '記録は残り、あとから資産 > 口座で戻せます。', '無効にする'))) return;
        void mutation.run(() => deleteAccount(account.id), `「${account.name}」を無効にしました。`, () => {
            resource.setData((previous) => previous?.filter((row) => row.id !== account.id) ?? null);
            resource.reload();
        });
    };
    return <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">口座・勘定科目</h2><p className="mt-1 text-xs text-[var(--studio-text-muted)]">表示通貨：{currency}。無効の口座も含みます。</p></div><div className="flex gap-2"><button type="button" disabled={disabled || editor !== null} onClick={() => setEditor({ account: null })} className={buttonClass}>新規作成</button><button type="button" disabled={resource.loading || mutation.busy || editor !== null} onClick={resource.reload} className={buttonClass}>再読み込み</button></div></div>
        <Feedback loading={resource.loading} error={mutation.error || resource.error} message={mutation.message} />
        {editor && resource.data && <Overlay title={editor.account ? `${editor.account.name}を編集` : '口座・勘定科目の新規作成'} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><AccountEditor key={editor.account?.id ?? 'new'} account={editor.account} accounts={resource.data} currency={currency} busy={disabled} onCancel={() => setEditor(null)} onSave={(action) => void mutation.run(action, '口座・勘定科目を保存しました。', () => { setEditor(null); resource.reload(); })} /></Overlay>}
        {resource.data && Object.entries(ACCOUNT_TYPES).map(([type, label]) => {
            const rows = accounts.filter((row) => row.account_type === type);
            return <section key={type} className="space-y-2"><h3 className="text-sm font-semibold">{label} <span className="font-normal text-[var(--studio-text-muted)]">{rows.length}件</span></h3>
                <DataTable columns={['名称', '役割', '役割の目標額', '期待年利', '親', '操作']}>
                    {rows.length ? rows.map((row) => <tr key={row.id}>
                        <th scope="row" className="px-5 py-3 font-medium">{row.name}{!row.is_active && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">無効</span>}</th>
                        <td className="px-5 py-3">{ROLES[row.role]}</td><td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.role_target_amount == null ? '—' : formatCurrency(row.role_target_amount, currency)}</td><td className="px-5 py-3 tabular-nums">{row.expected_return}%</td><td className="px-5 py-3">{row.parent_id == null ? '—' : resource.data?.find((parent) => parent.id === row.parent_id)?.name ?? `#${row.parent_id}`}</td>
                        <RowActions name={row.name} disabled={disabled || editor !== null} onEdit={() => setEditor({ account: row })} onDelete={() => remove(row)} deleteLabel="無効にする" />
                    </tr>) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">登録はありません。</td></tr>}
                </DataTable>
            </section>;
        })}
    </section>;
}

export default function Accounts() {
    const { clientId, currentClient } = useClient();
    return <AccountsForClient key={clientId} currency={currentClient?.general_settings?.currency || 'JPY'} />;
}
