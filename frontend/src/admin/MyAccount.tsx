import { useState } from 'react';
import { tr } from '../studio/i18n';
import { useAdmin } from './context';
import { useAction, useQuery } from './hooks';
import { date } from './format';
import { Decision, Empty, Field, Loading, Notice, Page, SaveButton } from './ui';
import type { Session } from './types';

export default function MyAccount() {
    const { api, me, refreshMe } = useAdmin();
    const query = useQuery<Session[]>('/me/sessions');
    const action = useAction();
    const [revoking, setRevoking] = useState<Session | null>(null);
    const [current, setCurrent] = useState('');
    const [password, setPassword] = useState('');
    const [confirmation, setConfirmation] = useState('');
    return <Page title={tr('自分のアカウント', 'My account')}>
        <p>{me.username}</p><Notice error={query.error || action.error} message={action.message} />
        <section className="admin-card"><h2>{tr('サインイン中の端末', 'Sessions')}</h2>
            {query.loading && <Loading />}{query.error && <button onClick={query.reload}>{tr('再読み込み', 'Reload')}</button>}
            {query.data && <div className="admin-table"><table><thead><tr>{[tr('端末', 'Session'), tr('開始', 'Created'), tr('最後の利用', 'Last active'), tr('有効期限', 'Expires'), tr('操作', 'Action')].map(t => <th key={t} scope="col">{t}</th>)}</tr></thead>
                <tbody>{query.data.map((session, index) => <tr key={session.id}><td>{session.id === me.session.id ? <strong>{tr('この端末', 'Current session')}</strong> : `${tr('端末', 'Session')} ${index + 1}`}</td><td>{date(session.created_at)}</td><td>{date(session.last_seen_at)}</td><td>{date(session.expires_at)}</td><td><button disabled={action.busy} onClick={() => setRevoking(session)}>{tr('サインアウト', 'Revoke')}</button></td></tr>)}</tbody></table>{query.data.length === 0 && <Empty />}</div>}
        </section>
        <section className="admin-card"><h2>{tr('パスワードを変更', 'Change password')}</h2>
            <form onSubmit={e => { e.preventDefault(); void action.run(async () => {
                if (password.length < 12) throw new Error(tr('12文字以上にしてください。', 'Use at least 12 characters.'));
                if (password !== confirmation) throw new Error(tr('パスワードが一致しません。', 'Passwords do not match.'));
                await api.post('/me/password', { current_password: current, new_password: password }); setCurrent(''); setPassword(''); setConfirmation(''); query.reload(); await refreshMe();
            }, tr('パスワードを変更し、ほかの端末をサインアウトしました。', 'Password changed. Other sessions were signed out.')); }}><fieldset disabled={action.busy}>
                <Field autoFocus label={tr('現在のパスワード', 'Current password')} type="password" autoComplete="current-password" required value={current} onChange={e => setCurrent(e.target.value)} />
                <Field label={tr('新しいパスワード', 'New password')} type="password" autoComplete="new-password" minLength={12} required value={password} onChange={e => setPassword(e.target.value)} help={tr('12文字以上にします。変更すると、ほかの端末はサインアウトします。', 'Use at least 12 characters. Changing your password signs out other sessions.')} />
                <Field label={tr('もう一度入力', 'Confirm password')} type="password" autoComplete="new-password" minLength={12} required value={confirmation} onChange={e => setConfirmation(e.target.value)} />
                <SaveButton busy={action.busy} label={tr('パスワードを変更', 'Change password')} />
            </fieldset></form>
        </section>
        {revoking && <Decision title={tr('サインアウト', 'Revoke session')} target={revoking.id === me.session.id ? tr('この端末', 'Current session') : `${tr('開始', 'Created')}: ${date(revoking.created_at)}`} onCancel={() => setRevoking(null)} onConfirm={() => {
            const selected = revoking; setRevoking(null); void action.run(async () => {
                await api.delete(`/me/sessions/${encodeURIComponent(selected.id)}`);
                if (selected.id === me.session.id) await refreshMe(); else query.reload();
            }, tr('サインアウトしました。', 'Session revoked.'));
        }} />}
    </Page>;
}
