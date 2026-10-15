import { useCallback, useRef, useState } from 'react';
import { applyAiChangeRequest, approveAiChangeRequest, getAiChangeRequests, rejectAiChangeRequest } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { AiChangeRequest } from '../../../types';
import { assetErrorMessage, useResource } from '../../useResource';
import DiffRows from './DiffRows';
import { buttonClass, inputClass, RISK_LABELS, STATUS_LABELS } from './labels';

type StatusFilter = 'pending' | 'approved' | 'applied' | 'rejected';
type RequestAction = 'approve' | 'apply' | 'reject';
const FILTERS: StatusFilter[] = ['pending', 'approved', 'applied', 'rejected'];
const ACTION_LABELS: Record<RequestAction, string> = { approve: '承認', apply: '適用', reject: '却下' };

function RequestList({ status, currency }: { status: StatusFilter; currency: string }) {
    const load = useCallback(() => getAiChangeRequests({ status }), [status]);
    const { data, setData, loading, error, reload } = useResource(load);
    const [busy, setBusy] = useState<{ id: number; action: RequestAction } | null>(null);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const inFlight = useRef(false);

    const runAction = async (request: AiChangeRequest, action: RequestAction) => {
        if (inFlight.current || loading || error) return;
        // Critical requests also need step-up in the legacy flow; never approve them without a token.
        if (action === 'approve' && (request.status !== 'pending' || request.requires_mfa || request.risk === 'critical')) return;
        if (action === 'apply' && request.status !== 'approved') return;
        if (action === 'reject' && request.status !== 'pending' && request.status !== 'approved') return;
        inFlight.current = true;
        setBusy({ id: request.id, action });
        setOperationError('');
        setConfirmation('');
        try {
            const updated = action === 'approve' ? await approveAiChangeRequest(request.id)
                : action === 'apply' ? await applyAiChangeRequest(request.id) : await rejectAiChangeRequest(request.id);
            // Remove a decided request immediately, even if refreshing the status list fails.
            setData((previous) => previous?.map((row) => row.id === updated.id ? updated : row).filter((row) => row.status === status) ?? null);
            setConfirmation(`リクエスト #${request.id} を${ACTION_LABELS[action]}しました。`);
            reload();
        } catch (failure: unknown) {
            setOperationError(`リクエスト #${request.id} を${ACTION_LABELS[action]}できませんでした。${assetErrorMessage(failure)}`);
        } finally {
            inFlight.current = false;
            setBusy(null);
        }
    };

    return (
        <div className="space-y-4">
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">承認リクエストを読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">承認リクエストを取得できませんでした。{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {data && (data.length ? data.map((request) => {
                const needsMfa = request.requires_mfa || request.risk === 'critical';
                const disabled = loading || Boolean(error) || busy !== null;
                return (
                    <article key={request.id} className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5" aria-busy={busy?.id === request.id}>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div><h3 className="text-sm font-semibold">{request.resource}・{request.action}</h3><p className="mt-1 text-xs text-[var(--studio-text-muted)]">リクエスト #{request.id}</p></div>
                            <div className="flex gap-3 text-xs"><span>リスク：{RISK_LABELS[request.risk]}</span><span>状態：{STATUS_LABELS[request.status]}</span></div>
                        </div>
                        {Object.keys(request.target_ref).length > 0 && <dl className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
                            {Object.entries(request.target_ref).map(([key, value]) => <div key={key} className="flex gap-2"><dt className="text-[var(--studio-text-muted)]">{key}</dt><dd className="break-all">{value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}
                        </dl>}
                        <DiffRows change={request} currency={currency} />
                        {needsMfa && request.status === 'pending' && <p id={`mfa-${request.id}`} className="text-xs text-[var(--studio-warning)]">MFAが必要です。MFAを入力できる承認画面で承認してください。</p>}
                        <div className="flex flex-wrap gap-2">
                            <button type="button" onClick={() => void runAction(request, 'approve')} disabled={disabled || request.status !== 'pending' || needsMfa} aria-describedby={needsMfa && request.status === 'pending' ? `mfa-${request.id}` : undefined} className={buttonClass}>{busy?.id === request.id && busy.action === 'approve' ? '承認中…' : '承認'}</button>
                            <button type="button" onClick={() => void runAction(request, 'apply')} disabled={disabled || request.status !== 'approved'} className={buttonClass}>{busy?.id === request.id && busy.action === 'apply' ? '適用中…' : '適用'}</button>
                            <button type="button" onClick={() => void runAction(request, 'reject')} disabled={disabled || (request.status !== 'pending' && request.status !== 'approved')} className={buttonClass}>{busy?.id === request.id && busy.action === 'reject' ? '却下中…' : '却下'}</button>
                        </div>
                    </article>
                );
            }) : <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">該当する承認リクエストはありません。</p>)}
        </div>
    );
}

export default function Approvals() {
    const { clientId, currentClient } = useClient();
    const [status, setStatus] = useState<StatusFilter>('pending');
    return (
        <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <label className="flex items-center gap-2 text-xs text-[var(--studio-text-muted)]">状態
                    <select value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)} className={inputClass}>{FILTERS.map((value) => <option key={value} value={value}>{STATUS_LABELS[value]}</option>)}</select>
                </label>
            </div>
            {/* Remounting prevents an earlier filter or client response from entering this list. */}
            <RequestList key={`${clientId}:${status}`} status={status} currency={currentClient?.general_settings?.currency || 'JPY'} />
        </section>
    );
}
