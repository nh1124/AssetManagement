import { Link } from 'react-router-dom';
import { tr } from '../studio/i18n';
import { useQuery } from './hooks';
import { AuditTable, Empty, Loading, Notice, Page } from './ui';
import type { OverviewData } from './types';

export default function Overview() {
    const query = useQuery<OverviewData>('/overview');
    const data = query.data;
    return <Page title={tr('概要', 'Overview')} help={tr('件数はこの仕組み全体の状況です。データの確認は有効なアカウントを最大200件まで調べます。', 'Counts cover this installation. Data checks inspect up to 200 active accounts.')}>
        <Notice error={query.error} />{query.error && <button onClick={query.reload}>{tr('再読み込み', 'Reload')}</button>}{query.loading && <Loading />}
        {data && <>
            <div className="admin-counts">{[
                [tr('有効', 'Active'), data.clients.active], [tr('停止中', 'Suspended'), data.clients.suspended],
                [tr('承認待ち', 'Pending approval'), data.clients.pending_approval], [tr('ロック中', 'Locked'), data.clients.locked],
                [tr('TOTP 未設定', 'TOTP not set'), data.clients.without_totp], [tr('管理者', 'Administrators'), data.admins],
            ].map(([label, value]) => <article key={label} className="admin-card"><h2>{label}</h2><strong>{value}</strong></article>)}</div>
            {data.health && <section className="admin-card"><h2>{tr('データの確認', 'Data health')}</h2>
                <p>{tr('確認済み', 'Checked')}: {data.health.checked_clients} / {data.clients.active}</p>
                {data.health.truncated && <p role="status" className="admin-warning">{tr('最初の200件を表示しています。残りは各アカウントで確認してください。', 'Showing the first 200 accounts. Check the remaining accounts individually.')}</p>}
                <div className="admin-table"><table><thead><tr><th scope="col">{tr('アカウント', 'Account')}</th><th scope="col">{tr('利用者が直す', 'User issues')}</th><th scope="col">{tr('仕組み側', 'System issues')}</th></tr></thead>
                    <tbody>{data.health.clients.map(row => <tr key={row.client_id}><td><Link to={`/accounts/${row.client_id}`}>#{row.client_id}</Link></td><td>{row.user}</td><td>{row.admin}</td></tr>)}</tbody></table>{!data.health.clients.length && <Empty />}</div>
            </section>}
            {data.recent_audit && <section className="admin-card"><h2>{tr('最近の監査ログ', 'Recent audit')}</h2><AuditTable rows={data.recent_audit} /></section>}
        </>}
    </Page>;
}
