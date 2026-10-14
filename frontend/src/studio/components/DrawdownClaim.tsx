import { useReloadAction } from './useReloadAction';
import { useCallback } from 'react';
import { getAccountEarmarks } from '../../api';
import { formatCurrency } from '../../utils/currency';
import { useResource } from '../useResource';

// Callers remount for a new client, capsule, account or successful recording so
// an earlier selection's claim never appears as the current release ceiling.
export default function DrawdownClaim({ accountId, accountName, capsuleId, currency }: {
    accountId: number; accountName: string; capsuleId: number; currency: string;
}) {
    const load = useCallback(() => getAccountEarmarks(accountId), [accountId]);
    const claims = useResource(load);
    const claim = claims.data?.find((row) => row.capsule_id === capsuleId && row.currency === currency);
    // Only the server knows the claim; failed or missing reads cannot imply zero.
    useReloadAction(claims.reload, false, Boolean(claims.error));
    return <div className="mt-2 space-y-1 text-xs text-[var(--studio-text-muted)]">
        {claims.loading ? <p role="status">この口座の確保額を読み込んでいます…</p>
            : claims.error ? <>
                <p role="alert">この口座の確保額を取得できませんでした。{claims.error}</p>
            </> : <p role="status">{accountName}の確保額（取り崩し上限）：{claim ? `${formatCurrency(claim.claimed, claim.currency)}（${claim.currency}）` : '確認できません'}</p>}
    </div>;
}
