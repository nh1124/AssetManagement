import { useId, useState, type InputHTMLAttributes, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { tr } from '../studio/i18n';
import Overlay from '../studio/components/Overlay';
import Confirm from '../studio/components/Confirm';
import { Help } from '../studio/components/Help';
import { inputClass, primaryClass } from '../studio/components/controlStyles';
import { useAction } from './hooks';
import { date } from './format';
import { useAdmin } from './context';
import type { AuditRow } from './types';

export function Field({ label, help, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; help?: string }) {
    const generated = useId();
    const id = props.id ?? generated;
    return <div className="admin-field"><label htmlFor={id}>{label}</label>{help && <Help label={label} text={help} />}<input {...props} id={id} className={inputClass} /></div>;
}
export function Notice({ error, message }: { error?: string; message?: string }) {
    return <>{error && <p className="admin-error" role="alert">{error}</p>}{message && <p className="admin-success" role="status">{message}</p>}</>;
}
export function Loading() { return <p role="status">{tr('読み込み中…', 'Loading…')}</p>; }
export function Empty() { return <p>{tr('該当する記録はありません。', 'No matching records.')}</p>; }
export function Pager({ offset, size, count, onChange, busy }: { offset: number; size: number; count: number; onChange: (offset: number) => void; busy?: boolean }) {
    return <nav className="admin-actions" aria-label={tr('ページ', 'Pagination')}>
        <button disabled={busy || offset === 0} onClick={() => onChange(Math.max(0, offset - size))}>{tr('前へ', 'Previous')}</button>
        <span>{tr('ページ', 'Page')} {offset / size + 1}</span>
        <button disabled={busy || count < size} onClick={() => onChange(offset + size)}>{tr('次へ', 'Next')}</button>
    </nav>;
}
export function Decision({ title, target, needsReason = false, onConfirm, onCancel }: {
    title: string; target: string; needsReason?: boolean; onConfirm: (reason: string) => void; onCancel: () => void;
}) {
    const [reason, setReason] = useState('');
    const [error, setError] = useState('');
    return <Confirm title={title} confirmLabel={title} onCancel={onCancel} onConfirm={() => {
        if (needsReason && !reason.trim()) { setError(tr('理由を入力してください。', 'Enter a reason.')); return; }
        onConfirm(reason.trim());
    }}><p>{target}</p>{needsReason && <Field autoFocus required label={tr('停止する理由', 'Reason for suspension')} value={reason} onChange={e => setReason(e.target.value)} />}<Notice error={error} /></Confirm>;
}
export function TemporaryPassword({ password, target, onClose }: { password: string; target: string; onClose: () => void }) {
    const action = useAction();
    return <Overlay title={tr('一時パスワード', 'Temporary password')} onClose={onClose}>
        <p>{target}</p><p role="alert" className="admin-warning">{tr('この画面を閉じると再表示できません。安全な方法で本人に伝えてください。', 'You cannot view this again after closing this screen. Give it to the person through a secure channel.')}</p>
        <code className="admin-secret">{password}</code><button autoFocus disabled={action.busy} onClick={() => void action.run(() => navigator.clipboard.writeText(password), tr('コピーしました。', 'Copied.'))}>{tr('コピー', 'Copy')}</button>
        <Notice {...action} />
    </Overlay>;
}
export function Page({ title, help, children }: { title: string; help?: string; children: ReactNode }) {
    return <section className="admin-page"><div className="admin-heading"><h1>{title}</h1>{help && <Help label={title} text={help} below wide />}</div>{children}</section>;
}
export function SaveButton({ busy, label }: { busy: boolean; label?: string }) {
    return <button type="submit" className={primaryClass} disabled={busy}>{busy ? tr('処理中…', 'Working…') : label ?? tr('保存', 'Save')}</button>;
}
export function AuditTable({ rows }: { rows: AuditRow[] }) {
    const { can } = useAdmin();
    return <div className="admin-table"><table><thead><tr>{[tr('日時', 'Time'), tr('実行者', 'Actor'), tr('操作', 'Action'), tr('対象', 'Target'), tr('結果', 'Result')].map(t => <th key={t} scope="col">{t}</th>)}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.id}><td>{date(row.at)}</td><td>{row.actor}</td><td><code>{row.action}</code></td><td>{row.target_client_id !== null ? can('accounts.read') ? <Link to={`/accounts/${row.target_client_id}`}>{tr('アカウント', 'Account')} #{row.target_client_id}</Link> : `${tr('アカウント', 'Account')} #${row.target_client_id}` : row.target_admin_id !== null ? `${tr('管理者', 'Administrator')} #${row.target_admin_id}` : tr('—', '—')}</td><td>{row.result === 'ok' ? tr('成功', 'Succeeded') : row.result === 'refused' ? tr('拒否', 'Refused') : row.result === 'failed' ? tr('失敗', 'Failed') : row.result}</td></tr>)}</tbody></table>{rows.length === 0 && <Empty />}</div>;
}
