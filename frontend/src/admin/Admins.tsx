import { useState } from 'react';
import Overlay from '../studio/components/Overlay';
import { tr } from '../studio/i18n';
import { useAdmin } from './context';
import { useAction, useQuery } from './hooks';
import { date, onOff } from './format';
import { permissionLabel, permissions, presets } from './permissions';
import { Decision, Empty, Field, Loading, Notice, Page, SaveButton, TemporaryPassword } from './ui';
import type { Admin, TemporaryPassword as PasswordResult } from './types';

function Editor({ admin, onClose, onSaved }: { admin: Admin | null; onClose: () => void; onSaved: (result?: PasswordResult) => Promise<void> }) {
    const { api } = useAdmin();
    const [username, setUsername] = useState(admin?.username ?? '');
    const [selected, setSelected] = useState<string[]>(admin?.permissions ?? []);
    const action = useAction();
    return <Overlay title={admin ? tr('権限を変更', 'Edit permissions') : tr('管理者を作成', 'Create administrator')} busy={action.busy} onClose={onClose}>
        <form onSubmit={e => { e.preventDefault(); void action.run(async () => {
            if (admin) { await api.patch(`/admins/${admin.id}`, { permissions: selected }); await onSaved(); }
            else await onSaved(await api.post<PasswordResult>('/admins', { username, permissions: selected }));
        }, ''); }}><fieldset disabled={action.busy}>
            <Field autoFocus label={tr('ユーザー名', 'Username')} required readOnly={!!admin} autoComplete="off" value={username} onChange={e => setUsername(e.target.value)} />
            <fieldset><legend>{tr('権限', 'Permissions')}</legend>
                <div className="admin-actions">{[
                    ['owner', tr('すべて', 'Owner')], ['support', tr('サポート', 'Support')], ['viewer', tr('閲覧のみ', 'Viewer')],
                ].map(([key, label]) => <button type="button" key={key} onClick={() => setSelected([...presets[key]])}>{label}</button>)}</div>
                <div className="admin-permissions">{permissions.map(p => <div key={p}><input id={`permission-${p}`} type="checkbox" checked={selected.includes(p)} onChange={e => setSelected(value => e.target.checked ? [...value, p] : value.filter(item => item !== p))} /><label htmlFor={`permission-${p}`}>{permissionLabel(p)} <code>{p}</code></label></div>)}</div>
            </fieldset><Notice error={action.error} /><SaveButton busy={action.busy} label={admin ? tr('保存', 'Save') : tr('作成', 'Create')} />
        </fieldset></form>
    </Overlay>;
}

export default function Admins() {
    const { api, me, refreshMe } = useAdmin();
    const query = useQuery<Admin[]>('/admins');
    const action = useAction();
    const [message, setMessage] = useState('');
    const [editor, setEditor] = useState<{ admin: Admin | null } | null>(null);
    const [decision, setDecision] = useState<{ admin: Admin; reset: boolean } | null>(null);
    const [secret, setSecret] = useState<{ password: string; target: string; self: boolean } | null>(null);
    return <Page title={tr('管理者', 'Administrators')} help={tr('権限は必要なものだけ選びます。管理者を管理できる人を最後の1人にしたまま、停止や権限削除はできません。', 'Grant only the permissions needed. The last active administrator who can manage administrators cannot be disabled or lose that permission.')}>
        <button onClick={() => setEditor({ admin: null })}>{tr('管理者を作成', 'Create administrator')}</button>
        <Notice error={query.error || action.error} message={action.message || message} />{query.error && <button onClick={query.reload}>{tr('再読み込み', 'Reload')}</button>}{query.loading && <Loading />}
        {query.data && <div className="admin-table"><table><thead><tr>{[tr('ユーザー名', 'Username'), tr('状態', 'Status'), tr('TOTP', 'TOTP'), tr('権限', 'Permissions'), tr('最後のサインイン', 'Last sign in'), tr('操作', 'Actions')].map(t => <th key={t} scope="col">{t}</th>)}</tr></thead>
            <tbody>{query.data.map(admin => <tr key={admin.id}><td>{admin.username}</td><td>{admin.is_active ? tr('有効', 'Active') : tr('停止中', 'Disabled')}</td><td>{onOff(admin.mfa_enabled)}</td>
                <td><div className="admin-chips">{admin.permissions.map(p => <span key={p} className="admin-chip" title={p}>{permissionLabel(p)}</span>)}</div></td><td>{date(admin.last_login_at)}</td><td><div className="admin-actions">
                    <button disabled={action.busy} onClick={() => setEditor({ admin })}>{tr('権限を変更', 'Edit permissions')}</button>
                    <button disabled={action.busy} onClick={() => setDecision({ admin, reset: false })}>{admin.is_active ? tr('停止', 'Disable') : tr('有効にする', 'Enable')}</button>
                    <button disabled={action.busy} onClick={() => setDecision({ admin, reset: true })}>{tr('MFA リセット', 'Reset MFA')}</button>
                </div></td></tr>)}</tbody></table>{!query.data.length && <Empty />}</div>}
        {editor && <Editor admin={editor.admin} onClose={() => setEditor(null)} onSaved={async result => {
            setEditor(null); setMessage(tr('保存しました。', 'Saved.'));
            if (result) setSecret({ password: result.temporary_password, target: result.username ?? '', self: false });
            query.reload();
            if (editor.admin?.username === me.username) await refreshMe();
        }} />}
        {decision && <Decision title={decision.reset ? tr('MFA リセット', 'Reset MFA') : decision.admin.is_active ? tr('停止', 'Disable') : tr('有効にする', 'Enable')} target={`${decision.admin.username} (#${decision.admin.id})`} onCancel={() => setDecision(null)} onConfirm={() => {
            const selected = decision; setDecision(null);
            void action.run(async () => {
                if (selected.reset) {
                    const result = await api.post<PasswordResult>(`/admins/${selected.admin.id}/mfa-reset`);
                    setSecret({ password: result.temporary_password, target: selected.admin.username, self: selected.admin.username === me.username });
                    // A self reset revokes this session. Keep the one-time password visible until dismissed.
                    if (selected.admin.username !== me.username) query.reload();
                } else {
                    await api.patch(`/admins/${selected.admin.id}`, { is_active: !selected.admin.is_active });
                    query.reload();
                    if (selected.admin.username === me.username) await refreshMe();
                }
            });
        }} />}
        {secret && <TemporaryPassword password={secret.password} target={secret.target} onClose={() => { const self = secret.self; setSecret(null); if (self) void refreshMe().catch(() => {}); else query.reload(); }} />}
    </Page>;
}
