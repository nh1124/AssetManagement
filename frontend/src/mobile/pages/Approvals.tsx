import { useCallback, useRef, useState } from 'react';
import { Bot } from 'lucide-react';
import { applyAiChangeRequest, approveAiChangeRequest, getAiChangeRequests, getMfaStatus, reauth, refreshAiChangeRequestPreview, rejectAiChangeRequest } from '../../api';
import { useClient } from '../../context/ClientContext';
import type { AiChangeRequest } from '../../types';
import { formatDateTime, useTimezone } from '../../studio/datetime';
import { diffRows } from '../../studio/pages/automation/diffValues';
import { failureReason, rebuildHelp, RISK_LABELS, STATUS_LABELS } from '../../studio/pages/automation/labels';
import { assetErrorMessage, useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import { useSnack } from '../components/snack';
import { Badge, Empty, ErrorNote, fieldClass, primaryButton, secondaryButton, Segmented, Skeleton } from '../components/ui';
import { labels, tr } from '../../studio/i18n';

type Status = 'pending' | 'approved' | 'failed' | 'applied' | 'rejected';
type Action = 'approve' | 'apply' | 'reject' | 'rebuild';
const ACTION_LABELS = labels<Action>({ approve: ['承認', 'Approve'], apply: ['適用', 'Apply'], reject: ['却下', 'Reject'], rebuild: ['作り直す', 'Rebuild'] });
const BUSY_LABELS = labels<Action>({ approve: ['承認中…', 'Approving…'], apply: ['適用中…', 'Applying…'], reject: ['却下中…', 'Rejecting…'], rebuild: ['作り直し中…', 'Rebuilding…'] });
const DONE_LABELS = labels<Action>({ approve: ['承認しました', 'approved'], apply: ['適用しました', 'applied'], reject: ['却下しました', 'rejected'], rebuild: ['作り直しました（承認待ちへ）', 'rebuilt (back to pending)'] });
const REJECTABLE = ['pending', 'approved', 'failed'];

/** The step-up factor the backend accepts: an authenticator code or a recovery code. */
const stepUpFactor = (value: string) => /^\d{6}$/.test(value) ? { code: value } : { recovery_code: value };

/** What a change request changes, field by field, stacked for a narrow screen. */
function Changes({ request, currency }: { request: AiChangeRequest; currency: string }) {
    const rows = diffRows(request, currency);
    if (!rows.length) return <p className="text-xs text-[var(--studio-text-muted)]">{tr('項目の変更はありません。', 'No fields change.')}</p>;
    return <dl className="space-y-2">{rows.map((row, index) => <div key={`${row.field}:${index}`} className="rounded-xl bg-[var(--studio-bg)] px-3 py-2 text-xs">
        <dt className="font-semibold">{row.field}</dt>
        <dd className="mt-1 grid gap-1">
            <span className="whitespace-pre-wrap break-words text-[var(--studio-text-muted)]">{tr('変更前：', 'Before: ')}{row.before}</span>
            <span className="whitespace-pre-wrap break-words">{tr('変更後：', 'After: ')}{row.after}</span>
        </dd>
    </div>)}</dl>;
}

/** One status's requests. Mounted per status, so nothing typed or loaded for another status carries over. */
function RequestList({ status, currency, mfaEnabled }: { status: Status; currency: string; mfaEnabled: boolean | null }) {
    const timezone = useTimezone();
    const snack = useSnack();
    const load = useCallback(() => getAiChangeRequests({ status }), [status]);
    const { data, setData, loading, error, reload } = useResource(load);
    const [busy, setBusy] = useState<{ id: number; action: Action } | null>(null);
    const [factors, setFactors] = useState<Record<number, string>>({});
    const inFlight = useRef(false);
    const run = async (request: AiChangeRequest, action: Action) => {
        if (inFlight.current || loading || error) return;
        // Critical requests need step-up too; never approve them without a token.
        const needsMfa = request.requires_mfa || request.risk === 'critical';
        const factor = (factors[request.id] ?? '').trim();
        if (action === 'approve' && (request.status !== 'pending' || (needsMfa && (!factor || mfaEnabled !== true)))) return;
        if (action === 'apply' && request.status !== 'approved') return;
        if (action === 'reject' && !REJECTABLE.includes(request.status)) return;
        if (action === 'rebuild' && request.status !== 'failed') return;
        inFlight.current = true;
        setBusy({ id: request.id, action });
        try {
            let token: string | undefined;
            if (action === 'approve' && needsMfa) {
                try {
                    token = (await reauth(stepUpFactor(factor))).step_up_token;
                } catch {
                    snack(tr('認証コードが正しくありません。', 'The authentication code is not correct.'), 'error');
                    return;
                }
            }
            const updated = action === 'approve' ? await approveAiChangeRequest(request.id, token ? { step_up_token: token } : undefined)
                : action === 'apply' ? await applyAiChangeRequest(request.id)
                : action === 'rebuild' ? await refreshAiChangeRequestPreview(request.id) : await rejectAiChangeRequest(request.id);
            // A decided request leaves this list at once, even if refreshing it fails.
            setData((previous) => previous?.map((row) => row.id === updated.id ? updated : row).filter((row) => row.status === status) ?? null);
            snack(tr(`#${request.id} を${DONE_LABELS[action]}`, `#${request.id} ${DONE_LABELS[action]}`));
            reload();
        } catch (failure) {
            snack(tr(`#${request.id} の${ACTION_LABELS[action]}ができませんでした。${assetErrorMessage(failure)}`, `Could not ${ACTION_LABELS[action].toLowerCase()} #${request.id}. ${assetErrorMessage(failure)}`), 'error');
        } finally {
            // A one-time code is spent or no longer needed either way; never keep a secret in state.
            setFactors((previous) => ({ ...previous, [request.id]: '' }));
            inFlight.current = false;
            setBusy(null);
        }
    };
    if (error) return <ErrorNote message={error} onRetry={reload} />;
    if (!data) return <Skeleton lines={2} />;
    if (!data.length) return <Empty icon={<Bot size={28} aria-hidden />} title={tr(`${STATUS_LABELS[status]}の変更はありません`, `No ${STATUS_LABELS[status].toLowerCase()} changes`)} />;
    return <>{data.map((request) => {
        const needsMfa = request.requires_mfa || request.risk === 'critical';
        const stepUp = needsMfa && request.status === 'pending' && mfaEnabled === true;
        const mfaMissing = needsMfa && request.status === 'pending' && mfaEnabled === false;
        const disabled = loading || busy !== null || (needsMfa && mfaEnabled === null);
        const label = (action: Action) => busy?.id === request.id && busy.action === action ? BUSY_LABELS[action] : ACTION_LABELS[action];
        return <article key={request.id} aria-busy={busy?.id === request.id} className="space-y-3 rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0"><h2 className="truncate text-sm font-semibold">{request.resource}{tr('・', ' · ')}{request.action}</h2>
                    <p className="text-xs text-[var(--studio-text-muted)]">#{request.id}{tr('・', ' · ')}{formatDateTime(request.created_at, timezone)}{request.tool_name ? `${tr('・', ' · ')}${request.tool_name}` : ''}</p></div>
                <Badge tone={request.risk === 'high' || request.risk === 'critical' ? 'danger' : 'muted'}>{tr('リスク', 'Risk')} {RISK_LABELS[request.risk]}</Badge>
            </div>
            {Object.keys(request.target_ref).length > 0 && <p className="break-all text-xs text-[var(--studio-text-muted)]">{tr('対象：', 'Target: ')}{Object.entries(request.target_ref)
                .map(([key, value]) => `${key} ${value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)}`).join(tr('・', ' · '))}</p>}
            {request.status === 'failed' && <p className="text-xs text-[var(--studio-danger)]">{tr('失敗の理由：', 'Why it failed: ')}{failureReason(request.result ?? {})}</p>}
            <Changes request={request} currency={currency} />
            {request.status === 'failed' && <p className="text-xs text-[var(--studio-text-muted)]">{rebuildHelp()}</p>}
            {mfaMissing && <p className="text-xs text-[var(--studio-warning)]">{tr('この承認には MFA が必要です。PC版の設定で MFA を有効にしてください。', 'This approval needs MFA. Turn on MFA in the desktop settings.')}</p>}
            {stepUp && <label className="block space-y-1 text-xs"><span className="text-[var(--studio-warning)]">{tr('認証コード（認証アプリの 6 桁、またはリカバリーコード）', 'Authentication code (6 digits from your authenticator app, or a recovery code)')}</span>
                <input inputMode="numeric" autoComplete="one-time-code" value={factors[request.id] ?? ''} disabled={disabled} aria-label={tr('認証コード', 'Authentication code')}
                    onChange={(event) => setFactors((previous) => ({ ...previous, [request.id]: event.target.value }))} className={fieldClass} /></label>}
            {request.status === 'failed' ? <div className="grid grid-cols-2 gap-2">
                <button type="button" disabled={disabled} onClick={() => void run(request, 'rebuild')} className={primaryButton}>{label('rebuild')}</button>
                <button type="button" disabled={disabled} onClick={() => void run(request, 'reject')} className={secondaryButton}>{label('reject')}</button>
            </div> : <div className="grid grid-cols-3 gap-2">
                <button type="button" disabled={disabled || request.status !== 'pending' || mfaMissing || (stepUp && !(factors[request.id] ?? '').trim())} onClick={() => void run(request, 'approve')} className={primaryButton}>{label('approve')}</button>
                <button type="button" disabled={disabled || request.status !== 'approved'} onClick={() => void run(request, 'apply')} className={secondaryButton}>{label('apply')}</button>
                <button type="button" disabled={disabled || !REJECTABLE.includes(request.status)} onClick={() => void run(request, 'reject')} className={secondaryButton}>{label('reject')}</button>
            </div>}
        </article>;
    })}</>;
}

/** Changes the AI asked to make: read what changes, then approve (with MFA when required), apply or reject. */
export default function Approvals() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const [status, setStatus] = useState<Status>('pending');
    const mfa = useResource(getMfaStatus);
    return <Screen title={tr('AI からの変更', 'Changes from AI')} back={-1}>
        <Segmented label={tr('状態', 'Status')} value={status} onChange={setStatus} options={(['pending', 'approved', 'failed', 'applied', 'rejected'] as Status[]).map((value) => ({ value, label: STATUS_LABELS[value] }))} />
        {mfa.error && <ErrorNote message={tr('MFA の設定を取得できませんでした。MFA が必要な承認は再読み込みの後で行えます。', 'Could not load the MFA setting. Approvals that need MFA can be done after a reload.')} onRetry={mfa.reload} />}
        <RequestList key={`${clientId}:${status}`} status={status} currency={currency} mfaEnabled={mfa.data?.enabled ?? null} />
    </Screen>;
}
