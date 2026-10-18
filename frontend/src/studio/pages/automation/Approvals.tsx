import { useCallback, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { applyAiChangeRequest, approveAiChangeRequest, getAiChangeRequests, getMfaStatus, reauth, rejectAiChangeRequest } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { AiChangeRequest } from '../../../types';
import { assetErrorMessage, useResource } from '../../useResource';
import DiffRows from './DiffRows';
import { buttonClass, inputClass, RISK_LABELS, STATUS_LABELS } from './labels';

type StatusFilter = 'pending' | 'approved' | 'applied' | 'rejected';
type RequestAction = 'approve' | 'apply' | 'reject';
const FILTERS: StatusFilter[] = ['pending', 'approved', 'applied', 'rejected'];
const ACTION_LABELS: Record<RequestAction, string> = { approve: '承認', apply: '適用', reject: '却下' };

/** The step-up factor the backend accepts: an authenticator code or a recovery code (MFA only). */
function stepUpFactor(value: string) {
    return /^\d{6}$/.test(value) ? { code: value } : { recovery_code: value };
}

function RequestList({ status, currency, mfaEnabled }: { status: StatusFilter; currency: string; mfaEnabled: boolean | null }) {
    const load = useCallback(() => getAiChangeRequests({ status }), [status]);
    const { data, setData, loading, error, reload } = useResource(load);
    const [busy, setBusy] = useState<{ id: number; action: RequestAction } | null>(null);
    const [factors, setFactors] = useState<Record<number, string>>({});
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const inFlight = useRef(false);

    const runAction = async (request: AiChangeRequest, action: RequestAction) => {
        if (inFlight.current || loading || error) return;
        // Critical requests need step-up too; never approve them without a token.
        const needsMfa = request.requires_mfa || request.risk === 'critical';
        const factor = (factors[request.id] ?? '').trim();
        if (action === 'approve' && (request.status !== 'pending' || (needsMfa && (!factor || mfaEnabled !== true)))) return;
        if (action === 'apply' && request.status !== 'approved') return;
        if (action === 'reject' && request.status !== 'pending' && request.status !== 'approved') return;
        inFlight.current = true;
        setBusy({ id: request.id, action });
        setOperationError('');
        setConfirmation('');
        try {
            let stepUpToken: string | undefined;
            if (action === 'approve' && needsMfa) {
                try {
                    stepUpToken = (await reauth(stepUpFactor(factor))).step_up_token;
                } catch {
                    setOperationError('認証コードが正しくありません。');
                    return;
                } finally {
                    // A one-time code is spent either way; never keep a secret in state.
                    setFactors((previous) => ({ ...previous, [request.id]: '' }));
                }
            }
            const updated = action === 'approve' ? await approveAiChangeRequest(request.id, stepUpToken ? { step_up_token: stepUpToken } : undefined)
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
                const disabled = loading || Boolean(error) || busy !== null || (needsMfa && mfaEnabled === null);
                const stepUp = needsMfa && request.status === 'pending' && mfaEnabled === true;
                const mfaMissing = needsMfa && request.status === 'pending' && mfaEnabled === false;
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
                        {mfaMissing && <p id={`mfa-${request.id}`} className="text-xs text-[var(--studio-warning)]">この承認には MFA が必要です。<Link to="/settings#mfa" className="underline">設定 › MFA</Link> で設定してください。</p>}
                        {stepUp && <label className="block space-y-1 text-xs">
                            <span id={`mfa-${request.id}`} className="text-[var(--studio-warning)]">承認には認証コードが必要です（認証アプリの 6 桁、またはリカバリーコード）。</span>
                            <input type="text" inputMode="numeric" autoComplete="one-time-code" value={factors[request.id] ?? ''} disabled={disabled}
                                onChange={(event) => setFactors((previous) => ({ ...previous, [request.id]: event.target.value }))}
                                onKeyDown={(event) => { if (event.key === 'Enter') void runAction(request, 'approve'); }}
                                aria-label="認証コード" className={`block w-56 ${inputClass}`} />
                        </label>}
                        <div className="flex flex-wrap gap-2">
                            <button type="button" onClick={() => void runAction(request, 'approve')} disabled={disabled || mfaMissing || request.status !== 'pending' || (stepUp && !(factors[request.id] ?? '').trim())} aria-describedby={stepUp || mfaMissing ? `mfa-${request.id}` : undefined} className={buttonClass}>{busy?.id === request.id && busy.action === 'approve' ? '承認中…' : '承認'}</button>
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
    const mfa = useResource(getMfaStatus);
    return (
        <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <label className="flex items-center gap-2 text-xs text-[var(--studio-text-muted)]">状態
                    <select value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)} className={inputClass}>{FILTERS.map((value) => <option key={value} value={value}>{STATUS_LABELS[value]}</option>)}</select>
                </label>
            </div>
            {/* Remounting prevents an earlier filter or client response from entering this list. */}
            {mfa.error && <p role="alert" className="text-sm text-[var(--studio-danger)]">MFA の設定を取得できませんでした。MFA が必要な承認は再読み込み後に行えます。</p>}
            <RequestList key={`${clientId}:${status}`} status={status} currency={currentClient?.general_settings?.currency || 'JPY'} mfaEnabled={mfa.data?.enabled ?? null} />
        </section>
    );
}
