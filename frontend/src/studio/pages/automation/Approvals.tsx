import { useCallback, useRef, useState } from 'react';
import { applyAiChangeRequest, approveAiChangeRequest, getAiChangeRequests, reauth, refreshAiChangeRequestPreview, rejectAiChangeRequest } from '../../../api';
import { Help } from '../../components/Help';
import { useClient } from '../../../context/ClientContext';
import type { AiChangeRequest } from '../../../types';
import { assetErrorMessage, useResource } from '../../useResource';
import DiffRows from './DiffRows';
import { buttonClass, failureReason, inputClass, rebuildHelp, RISK_LABELS, STATUS_LABELS } from './labels';
import { labels, tr } from '../../i18n';

type StatusFilter = 'pending' | 'approved' | 'failed' | 'applied' | 'rejected';
type RequestAction = 'approve' | 'apply' | 'reject' | 'rebuild';
const FILTERS: StatusFilter[] = ['pending', 'approved', 'failed', 'applied', 'rejected'];
const ACTION_LABELS = labels<RequestAction>({ approve: ['承認', 'approve'], apply: ['適用', 'apply'], reject: ['却下', 'reject'], rebuild: ['作り直し', 'rebuild'] });
const ACTION_DONE = labels<RequestAction>({ approve: ['承認', 'approved'], apply: ['適用', 'applied'], reject: ['却下', 'rejected'], rebuild: ['作り直し', 'rebuilt'] });

/** The step-up factor the backend accepts: an authenticator code or a recovery code (MFA only). */
function stepUpFactor(value: string) {
    return /^\d{6}$/.test(value) ? { code: value } : { recovery_code: value };
}

function RequestList({ status, currency }: { status: StatusFilter; currency: string }) {
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
        if (action === 'approve' && (request.status !== 'pending' || (needsMfa && !factor))) return;
        if (action === 'apply' && request.status !== 'approved') return;
        if (action === 'reject' && !['pending', 'approved', 'failed'].includes(request.status)) return;
        if (action === 'rebuild' && request.status !== 'failed') return;
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
                    setOperationError(tr('認証コードが正しくありません。', 'The authentication code is not correct.'));
                    return;
                } finally {
                    // A one-time code is spent either way; never keep a secret in state.
                    setFactors((previous) => ({ ...previous, [request.id]: '' }));
                }
            }
            const updated = action === 'approve' ? await approveAiChangeRequest(request.id, stepUpToken ? { step_up_token: stepUpToken } : undefined)
                : action === 'apply' ? await applyAiChangeRequest(request.id)
                : action === 'rebuild' ? await refreshAiChangeRequestPreview(request.id) : await rejectAiChangeRequest(request.id);
            // Remove a decided request immediately, even if refreshing the status list fails.
            setData((previous) => previous?.map((row) => row.id === updated.id ? updated : row).filter((row) => row.status === status) ?? null);
            setConfirmation(action === 'rebuild' ? tr(`リクエスト #${request.id} を作り直しました。「承認待ち」で確認してください。`, `Request #${request.id} rebuilt. Review it under “Pending”.`)
                : tr(`リクエスト #${request.id} を${ACTION_DONE[action]}しました。`, `Request #${request.id} ${ACTION_DONE[action]}.`));
            reload();
        } catch (failure: unknown) {
            setOperationError(tr(`リクエスト #${request.id} を${ACTION_LABELS[action]}できませんでした。${assetErrorMessage(failure)}`, `Could not ${ACTION_LABELS[action]} request #${request.id}. ${assetErrorMessage(failure)}`));
        } finally {
            inFlight.current = false;
            setBusy(null);
        }
    };

    return (
        <div className="space-y-4">
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('承認リクエストを読み込んでいます…', 'Loading approval requests…')}</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('承認リクエストを取得できませんでした。', 'Could not load approval requests. ')}{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {data && (data.length ? data.map((request) => {
                const needsMfa = request.requires_mfa || request.risk === 'critical';
                const disabled = loading || Boolean(error) || busy !== null;
                const stepUp = needsMfa && request.status === 'pending';
                return (
                    <article key={request.id} className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5" aria-busy={busy?.id === request.id}>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div><h3 className="text-sm font-semibold">{request.resource}{tr('・', ' · ')}{request.action}</h3><p className="mt-1 text-xs text-[var(--studio-text-muted)]">{tr(`リクエスト #${request.id}`, `Request #${request.id}`)}</p></div>
                            <div className="flex gap-3 text-xs"><span>{tr('リスク：', 'Risk: ')}{RISK_LABELS[request.risk]}</span><span>{tr('状態：', 'Status: ')}{STATUS_LABELS[request.status]}</span></div>
                        </div>
                        {Object.keys(request.target_ref).length > 0 && <dl className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
                            {Object.entries(request.target_ref).map(([key, value]) => <div key={key} className="flex gap-2"><dt className="text-[var(--studio-text-muted)]">{key}</dt><dd className="break-all">{value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}
                        </dl>}
                        {request.status === 'failed' && <p className="text-xs text-[var(--studio-danger)]">{tr('失敗の理由：', 'Why it failed: ')}{failureReason(request.result ?? {})}</p>}
                        <DiffRows change={request} currency={currency} />
                        {stepUp && <label className="block space-y-1 text-xs">
                            <span id={`mfa-${request.id}`} className="text-[var(--studio-warning)]">{tr('承認には認証コードが必要です（認証アプリの 6 桁、またはリカバリーコード）。', 'Approval needs an authentication code (6 digits from your authenticator app, or a recovery code).')}</span>
                            <input type="text" inputMode="numeric" autoComplete="one-time-code" value={factors[request.id] ?? ''} disabled={disabled}
                                onChange={(event) => setFactors((previous) => ({ ...previous, [request.id]: event.target.value }))}
                                onKeyDown={(event) => { if (event.key === 'Enter') void runAction(request, 'approve'); }}
                                aria-label={tr('認証コード', 'Authentication code')} className={`block w-56 ${inputClass}`} />
                        </label>}
                        <div className="flex flex-wrap gap-2">
                            <button type="button" onClick={() => void runAction(request, 'approve')} disabled={disabled || request.status !== 'pending' || (stepUp && !(factors[request.id] ?? '').trim())} aria-describedby={stepUp ? `mfa-${request.id}` : undefined} className={buttonClass}>{busy?.id === request.id && busy.action === 'approve' ? tr('承認中…', 'Approving…') : tr('承認', 'Approve')}</button>
                            <button type="button" onClick={() => void runAction(request, 'apply')} disabled={disabled || request.status !== 'approved'} className={buttonClass}>{busy?.id === request.id && busy.action === 'apply' ? tr('適用中…', 'Applying…') : tr('適用', 'Apply')}</button>
                            <button type="button" onClick={() => void runAction(request, 'reject')} disabled={disabled || !['pending', 'approved', 'failed'].includes(request.status)} className={buttonClass}>{busy?.id === request.id && busy.action === 'reject' ? tr('却下中…', 'Rejecting…') : tr('却下', 'Reject')}</button>
                            {request.status === 'failed' && <span className="inline-flex items-center gap-1">
                                <button type="button" onClick={() => void runAction(request, 'rebuild')} disabled={disabled} className={buttonClass}>{busy?.id === request.id && busy.action === 'rebuild' ? tr('作り直し中…', 'Rebuilding…') : tr('作り直す', 'Rebuild')}</button>
                                <Help label={tr('作り直す', 'Rebuild')} text={rebuildHelp()} />
                            </span>}
                        </div>
                    </article>
                );
            }) : <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">{tr('該当する承認リクエストはありません。', 'No matching approval requests.')}</p>)}
        </div>
    );
}

export default function Approvals() {
    const { clientId, currentClient } = useClient();
    const [status, setStatus] = useState<StatusFilter>('pending');
    return (
        <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <label className="flex items-center gap-2 text-xs text-[var(--studio-text-muted)]">{tr('状態', 'Status')}
                    <select value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)} className={inputClass}>{FILTERS.map((value) => <option key={value} value={value}>{STATUS_LABELS[value]}</option>)}</select>
                </label>
            </div>
            {/* Remounting prevents an earlier filter or client response from entering this list. */}
            <RequestList key={`${clientId}:${status}`} status={status} currency={currentClient?.general_settings?.currency || 'JPY'} />
        </section>
    );
}
