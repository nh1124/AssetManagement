import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { tr } from '../studio/i18n';
import Overlay from '../studio/components/Overlay';
import { Help } from '../studio/components/Help';
import { useAdmin } from './context';
import { queryString } from './api';
import { useAction, useQuery } from './hooks';
import { clientStatuses, date, onOff } from './format';
import { Decision, Empty, Field, Loading, Notice, Page, Pager, SaveButton, TemporaryPassword } from './ui';
import type { Client, Health, TemporaryPassword as PasswordResult } from './types';

function CreateAccount({ onClose, onCreated }: { onClose: () => void; onCreated: (result: PasswordResult) => void }) {
    const { api } = useAdmin();
    const [username, setUsername] = useState('');
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const action = useAction();
    return <Overlay title={tr('アカウントを作成', 'Create account')} onClose={onClose} busy={action.busy}>
        <form onSubmit={e => { e.preventDefault(); void action.run(async () => onCreated(await api.post<PasswordResult>('/clients', { username, name, email: email || null })), ''); }}>
            <fieldset disabled={action.busy}>
                <Field autoFocus label={tr('ユーザー名', 'Username')} autoComplete="off" required value={username} onChange={e => setUsername(e.target.value)} />
                <Field label={tr('表示名', 'Display name')} required value={name} onChange={e => setName(e.target.value)} />
                <Field label={tr('メール', 'Email')} type="email" value={email} onChange={e => setEmail(e.target.value)} />
                <Notice {...action} /><SaveButton busy={action.busy} label={tr('作成', 'Create')} />
            </fieldset>
        </form>
    </Overlay>;
}

export default function Accounts() {
    const { can } = useAdmin();
    const [filters, setFilters] = useState({ status: '', query: '', offset: 0 });
    const [draftQuery, setDraftQuery] = useState('');
    const [creating, setCreating] = useState(false);
    const [secret, setSecret] = useState<PasswordResult | null>(null);
    const query = useQuery<Client[]>(`/clients${queryString({ ...filters, limit: 25 })}`);
    return <Page title={tr('アカウント', 'Accounts')}>
        <form className="admin-filters" onSubmit={e => { e.preventDefault(); setFilters(value => ({ ...value, query: draftQuery, offset: 0 })); }}>
            <div className="admin-field"><label htmlFor="account-status">{tr('状態', 'Status')}</label><select id="account-status" value={filters.status} onChange={e => setFilters(value => ({ ...value, status: e.target.value, offset: 0 }))}>
                <option value="">{tr('すべて', 'All')}</option><option value="active">{tr('有効', 'Active')}</option><option value="suspended">{tr('停止中', 'Suspended')}</option><option value="pending">{tr('承認待ち', 'Pending approval')}</option><option value="locked">{tr('ロック中', 'Locked')}</option>
            </select></div>
            <Field label={tr('ユーザー名・表示名・メール', 'Username, name or email')} type="search" value={draftQuery} onChange={e => setDraftQuery(e.target.value)} />
            <button type="submit">{tr('検索', 'Search')}</button>
            {can('accounts.manage') && <button type="button" onClick={() => setCreating(true)}>{tr('アカウントを作成', 'Create account')}</button>}
        </form>
        <Notice error={query.error} />{query.error && <button onClick={query.reload}>{tr('再読み込み', 'Reload')}</button>}{query.loading && <Loading />}
        {query.data && <><div className="admin-table"><table><thead><tr>{[tr('ユーザー名', 'Username'), tr('表示名', 'Display name'), tr('状態', 'Status'), tr('TOTP', 'TOTP'), tr('作成日', 'Created'), tr('取引件数', 'Transactions'), tr('最後の記録', 'Last record')].map(t => <th scope="col" key={t}>{t}</th>)}</tr></thead>
            <tbody>{query.data.map(row => <tr key={row.id}><td><Link to={`/accounts/${row.id}`}>{row.username}</Link></td><td>{row.name}</td><td>{clientStatuses(row)}</td><td>{onOff(row.mfa_enabled)}</td><td>{date(row.created_at)}</td><td>{row.transaction_count}</td><td>{date(row.last_transaction_date, true)}</td></tr>)}</tbody></table>{query.data.length === 0 && <Empty />}</div>
            <Pager offset={filters.offset} size={25} count={query.data.length} onChange={offset => setFilters(value => ({ ...value, offset }))} /></>}
        {creating && <CreateAccount onClose={() => setCreating(false)} onCreated={result => { setCreating(false); setSecret(result); query.reload(); }} />}
        {secret && <TemporaryPassword password={secret.temporary_password} target={`${secret.username} (#${secret.id})`} onClose={() => setSecret(null)} />}
    </Page>;
}

function HealthPanel({ client }: { client: Client }) {
    const { can, api } = useAdmin();
    const query = useQuery<Health>(can('health.read') ? `/clients/${client.id}/health` : null);
    const action = useAction();
    const [repairing, setRepairing] = useState(false);
    if (!can('health.read') && !can('health.repair')) return null;
    return <section className="admin-card"><div className="admin-heading"><h2>{tr('データの確認', 'Data health')}</h2><Help label={tr('データの確認', 'Data health')} text={tr('利用者が直すものと仕組み側の問題を分けます。修復は、このアカウントの自動で直せる部分だけに行います。', 'Issues are grouped by who can fix them. Repair applies automatic fixes only to this account.')} below wide /></div>
        <Notice error={query.error || action.error} message={action.message} />{query.loading && <Loading />}
        <div className="admin-actions">{can('health.read') && <button disabled={action.busy || query.loading} onClick={query.reload}>{tr('再確認', 'Check again')}</button>}
            {can('health.repair') && <button disabled={action.busy || query.loading || query.data?.repairable_groups === 0} onClick={() => setRepairing(true)}>{tr('修復する', 'Repair')}</button>}</div>
        {query.data && <>
            <p role="status">{query.data.total_issues === 0 ? tr('問題は見つかりませんでした。', 'No issues found.') : `${tr('問題の件数', 'Issue count')}: ${query.data.total_issues}`}</p>
            {(['user', 'admin'] as const).map(audience => <section key={audience}><h3>{audience === 'user' ? tr('利用者が直す', 'User issues') : tr('仕組み側', 'System issues')}</h3>
                {query.data!.issues.filter(i => i.audience === audience && i.count > 0).map(issue => <article key={issue.code} className="admin-issue"><h4>{issue.title} ({issue.count})</h4><code>{issue.code}</code>
                    {issue.repairable && <span className="admin-chip">{tr('自動修復あり', 'Automatic repair available')}</span>}
                    {issue.items.slice(0, 5).map((item, index) => <pre key={index}>{JSON.stringify(item, null, 2)}</pre>)}
                    {issue.items.length > 5 && <p>{tr('先頭の5件を表示しています。', 'Showing the first 5 items.')}</p>}
                </article>)}
                {!query.data!.issues.some(i => i.audience === audience && i.count > 0) && <Empty />}
            </section>)}
        </>}
        {repairing && <Decision title={tr('修復する', 'Repair')} target={`${client.username} (#${client.id})`} onCancel={() => setRepairing(false)} onConfirm={() => {
            setRepairing(false); void action.run(async () => { await api.post(`/clients/${client.id}/health/repair`); query.reload(); }, tr('修復しました。再確認中です。', 'Repair completed. Checking again.'));
        }} />}
    </section>;
}

export function AccountDetail() {
    const { id } = useParams();
    const { api, can } = useAdmin();
    const query = useQuery<Client>(`/clients/${encodeURIComponent(id ?? '')}`);
    const action = useAction();
    const [decision, setDecision] = useState<{ path: string; title: string } | null>(null);
    const [secret, setSecret] = useState<string | null>(null);
    const client = query.data;
    const actions = [
        { path: 'suspend', title: tr('停止', 'Suspend'), permission: 'accounts.manage', show: client?.is_active },
        { path: 'reactivate', title: tr('再開', 'Reactivate'), permission: 'accounts.manage', show: client && !client.is_active },
        { path: 'approve', title: tr('承認', 'Approve'), permission: 'accounts.manage', show: client?.approval_pending },
        { path: 'unlock', title: tr('ロック解除', 'Unlock'), permission: 'accounts.manage', show: client?.locked_until },
        { path: 'sign-out', title: tr('全端末からサインアウト', 'Sign out all devices'), permission: 'accounts.manage', show: true },
        { path: 'password-reset', title: tr('パスワード再設定', 'Reset password'), permission: 'accounts.credentials', show: true },
        { path: 'mfa-reset', title: tr('MFA リセット', 'Reset MFA'), permission: 'accounts.credentials', show: true },
    ];
    return <Page title={client ? `${tr('アカウント', 'Account')}: ${client.username}` : tr('アカウント', 'Account')}>
        <Link to="/accounts">{tr('一覧へ戻る', 'Back to accounts')}</Link><Notice error={query.error || action.error} message={action.message} />{query.error && <button onClick={query.reload}>{tr('再読み込み', 'Reload')}</button>}{query.loading && <Loading />}
        {client && <><section className="admin-card"><dl className="admin-attributes">{[
            [tr('ID', 'ID'), client.id], [tr('表示名', 'Display name'), client.name], [tr('メール', 'Email'), client.email || tr('—', '—')],
            [tr('状態', 'Status'), clientStatuses(client)], [tr('TOTP', 'TOTP'), onOff(client.mfa_enabled)], [tr('作成日', 'Created'), date(client.created_at)],
            [tr('取引件数', 'Transactions'), client.transaction_count], [tr('最後の記録', 'Last record'), date(client.last_transaction_date, true)],
            [tr('停止理由', 'Suspension reason'), client.suspended_reason || tr('—', '—')], [tr('ロック期限', 'Locked until'), date(client.locked_until)],
            [tr('パスワード変更', 'Password change'), client.must_change_password ? tr('必要', 'Required') : tr('不要', 'Not required')],
        ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
            <div className="admin-actions">{actions.filter(item => item.show && can(item.permission)).map(item => <button key={item.path} disabled={action.busy} onClick={() => setDecision(item)}>{item.title}</button>)}</div>
        </section><HealthPanel key={client.id} client={client} /></>}
        {decision && client && <Decision title={decision.title} target={`${client.username} (#${client.id})`} needsReason={decision.path === 'suspend'} onCancel={() => setDecision(null)} onConfirm={reason => {
            const selected = decision; setDecision(null);
            void action.run(async () => {
                const result = await api.post<Partial<PasswordResult>>(`/clients/${client.id}/${selected.path}`, selected.path === 'suspend' ? { reason } : undefined);
                if (result.temporary_password) setSecret(result.temporary_password);
                query.reload();
            });
        }} />}
        {secret && <TemporaryPassword password={secret} target={`${tr('アカウント', 'Account')} #${id}`} onClose={() => setSecret(null)} />}
    </Page>;
}
