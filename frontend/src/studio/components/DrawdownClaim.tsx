import { useCallback } from 'react';
import { getAccountEarmarks } from '../../api';
import { formatCurrency } from '../../utils/currency';
import { useResource } from '../useResource';
import { tr } from '../i18n';

// Callers remount for a new client, capsule, account or successful recording so
// an earlier selection's claim never appears as the current release ceiling.
export default function DrawdownClaim({ accountId, accountName, capsuleId, currency }: {
    accountId: number; accountName: string; capsuleId: number; currency: string;
}) {
    const load = useCallback(() => getAccountEarmarks(accountId), [accountId]);
    const claims = useResource(load);
    const claim = claims.data?.find((row) => row.capsule_id === capsuleId && row.currency === currency);
    // Only the server knows the claim; failed or missing reads cannot imply zero.
    return <div className="mt-2 space-y-1 text-xs text-[var(--studio-text-muted)]">
        {claims.loading ? <p role="status">{tr('この口座の確保額を読み込んでいます…', 'Loading the amount set aside in this account…')}</p>
            : claims.error ? <>
                <p role="alert">{tr('この口座の確保額を取得できませんでした。', 'Could not load the amount set aside in this account. ')}{claims.error}</p>
            </> : <p role="status">{tr(`${accountName}の確保額（取り崩し上限）：`, `Set aside in ${accountName} (drawdown limit): `)}{claim ? `${formatCurrency(claim.claimed, claim.currency)} (${claim.currency})` : tr('確認できません', 'unknown')}</p>}
    </div>;
}
