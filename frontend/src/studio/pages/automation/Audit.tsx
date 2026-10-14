import { useReloadAction } from '../../components/useReloadAction';
import { formatDateTime, useTimezone } from '../../datetime';
import { useRef, useState } from 'react';
import { getAiAuditLogs } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { AiAuditLog } from '../../../types';
import { assetErrorMessage, useResource } from '../../useResource';
import { buttonClass, DECISION_LABELS, SOURCE_LABELS } from './labels';

const PAGE_SIZE = 50;
const newestFirst = (rows: AiAuditLog[]) => [...rows].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
async function loadFirstPage() {
    const items = await getAiAuditLogs({ limit: PAGE_SIZE, offset: 0 });
    return { items: newestFirst(items), offset: items.length, hasMore: items.length === PAGE_SIZE };
}

function AuditForClient() {
    const timezone = useTimezone();
    const { data, setData, loading, error, reload } = useResource(loadFirstPage);
    const [loadingMore, setLoadingMore] = useState(false);
    const [operationError, setOperationError] = useState('');
    const inFlight = useRef(false);
    const loadMore = async () => {
        if (inFlight.current || loading || error || !data?.hasMore) return;
        inFlight.current = true;
        setLoadingMore(true);
        setOperationError('');
        try {
            const next = await getAiAuditLogs({ limit: PAGE_SIZE, offset: data.offset });
            // New audit events can shift offsets; deduplicate without changing the consumed offset.
            const byId = new Map([...data.items, ...next].map((row) => [row.id, row]));
            setData({ items: newestFirst([...byId.values()]), offset: data.offset + next.length, hasMore: next.length === PAGE_SIZE });
        } catch (failure: unknown) {
            setOperationError(`次の監査ログを取得できませんでした。${assetErrorMessage(failure)}`);
        } finally {
            inFlight.current = false;
            setLoadingMore(false);
        }
    };

    useReloadAction(() => { setOperationError(''); reload(); }, Boolean(loading || loadingMore));
    return (
        <section className="space-y-4">
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">監査ログを読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">監査ログを取得できませんでした。{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {data && (data.items.length ? <>
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="w-full text-left text-sm" aria-busy={loading || loadingMore}>
                        <caption className="sr-only">監査ログ（新しい順）</caption>
                        <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]"><tr>{['日時', '操作', '実行元', '結果'].map((label) => <th scope="col" key={label} className="px-5 py-3 font-medium">{label}</th>)}</tr></thead>
                        <tbody className="divide-y divide-[var(--studio-border)]">
                            {data.items.map((row) => <tr key={row.id}>
                                <td className="whitespace-nowrap px-5 py-3 text-xs"><time dateTime={row.created_at}>{formatDateTime(row.created_at, timezone)}</time></td>
                                <th scope="row" className="px-5 py-3 font-medium">{row.resource}・{row.action}</th>
                                <td className="px-5 py-3">{SOURCE_LABELS[row.source]}{row.tool_name && <span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{row.tool_name}</span>}</td>
                                <td className={`whitespace-nowrap px-5 py-3 ${row.decision === 'failed' || row.decision === 'denied' ? 'text-[var(--studio-danger)]' : ''}`}>{DECISION_LABELS[row.decision]}</td>
                            </tr>)}
                        </tbody>
                    </table>
                </div>
                <div className="flex items-center gap-3"><span className="text-xs text-[var(--studio-text-muted)]">{data.items.length}件を表示（新しい順）</span>{data.hasMore ? <button type="button" onClick={() => void loadMore()} disabled={loading || loadingMore || Boolean(error)} className={buttonClass}>{loadingMore ? '読み込み中…' : 'もっと読む'}</button> : <span className="text-xs text-[var(--studio-text-muted)]">すべて読み込みました。</span>}</div>
            </> : <p className="text-sm text-[var(--studio-text-muted)]">監査ログはありません。</p>)}
        </section>
    );
}

export default function Audit() {
    const { clientId } = useClient();
    return <AuditForClient key={clientId} />;
}
