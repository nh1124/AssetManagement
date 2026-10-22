import { useState } from 'react';
import { tr } from '../studio/i18n';
import { queryString } from './api';
import { useQuery } from './hooks';
import { date } from './format';
import { AuditTable, Field, Loading, Notice, Page, Pager } from './ui';
import type { AuditRow } from './types';

function csvCell(value: unknown): string {
    let text = String(value ?? '');
    // Administrator/usernames and actions are data; do not execute spreadsheet formulas.
    if (/^\s*[=+\-@]|^[\t\r\n]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
}
function downloadCsv(rows: AuditRow[]) {
    const header = [tr('日時', 'Time'), tr('実行者', 'Actor'), tr('操作', 'Action'), tr('対象のアカウント ID', 'Target account ID'), tr('対象の管理者 ID', 'Target administrator ID'), tr('結果', 'Result')];
    const content = [header, ...rows.map(row => [date(row.at), row.actor, row.action, row.target_client_id, row.target_admin_id,
        row.result === 'ok' ? tr('成功', 'Succeeded') : row.result === 'refused' ? tr('拒否', 'Refused') : row.result === 'failed' ? tr('失敗', 'Failed') : row.result])]
        .map(row => row.map(csvCell).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob(['\uFEFF', content, '\r\n'], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = 'admin-audit.csv'; document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export default function Audit() {
    const empty = { action: '', target_client_id: '', since: '', until: '' };
    const [draft, setDraft] = useState(empty);
    const [filters, setFilters] = useState(empty);
    const [offset, setOffset] = useState(0);
    const [validation, setValidation] = useState('');
    const query = useQuery<AuditRow[]>(`/audit${queryString({ ...filters, limit: 25, offset })}`);
    return <Page title={tr('監査ログ', 'Audit log')} help={tr('操作名は前方一致です。期間はこの端末の時刻で指定します。CSV は今表示している行だけを書き出します。', 'Action matches a prefix. Dates use this device’s timezone. CSV exports only the rows currently shown.')}>
        <form className="admin-filters" onSubmit={e => {
            e.preventDefault();
            if (draft.since && draft.until && draft.since > draft.until) { setValidation(tr('終了は開始より後にしてください。', 'The end must follow the start.')); return; }
            setValidation('');
            setFilters({ ...draft, since: draft.since ? new Date(draft.since).toISOString().replace(/Z$/, '') : '', until: draft.until ? new Date(draft.until).toISOString().replace(/Z$/, '') : '' }); setOffset(0);
        }}>
            <Field label={tr('操作の種類', 'Action type')} value={draft.action} onChange={e => setDraft(value => ({ ...value, action: e.target.value }))} />
            <Field label={tr('対象のアカウント ID', 'Target account ID')} type="number" min={1} step={1} value={draft.target_client_id} onChange={e => setDraft(value => ({ ...value, target_client_id: e.target.value }))} />
            <Field label={tr('開始', 'From')} type="datetime-local" value={draft.since} onChange={e => setDraft(value => ({ ...value, since: e.target.value }))} />
            <Field label={tr('終了', 'Until')} type="datetime-local" value={draft.until} onChange={e => setDraft(value => ({ ...value, until: e.target.value }))} />
            <button type="submit">{tr('絞り込む', 'Apply filters')}</button><button type="button" onClick={() => { setDraft(empty); setFilters(empty); setOffset(0); setValidation(''); }}>{tr('クリア', 'Clear')}</button>
        </form><Notice error={validation || query.error} />{query.error && <button onClick={query.reload}>{tr('再読み込み', 'Reload')}</button>}{query.loading && <Loading />}
        {query.data && <><button disabled={!query.data.length} onClick={() => downloadCsv(query.data!)}>{tr('表示中の行を CSV で保存', 'Download shown rows as CSV')}</button><AuditTable rows={query.data} /><Pager offset={offset} size={25} count={query.data.length} onChange={setOffset} /></>}
    </Page>;
}
