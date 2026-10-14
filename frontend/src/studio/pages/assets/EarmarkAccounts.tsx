import { useReloadAction } from '../../components/useReloadAction';
import { useCallback } from 'react';
import { getAccountEarmarks } from '../../../api';
import type { CapsuleFundingSource } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { Feedback } from '../db/Database';
import { shareLabel } from './accountEarmarkFunding';

export default function EarmarkAccounts({ capsuleId, sources }: { capsuleId: number; sources: CapsuleFundingSource[] }) {
    const load = useCallback(async () => Promise.all(sources.map(async (source) => {
        const earmarks = await getAccountEarmarks(source.account_id);
        return { source, earmark: earmarks.find((earmark) => earmark.capsule_id === capsuleId) };
    })), [capsuleId, sources]);
    const claims = useResource(load);
    useReloadAction(claims.reload, false, Boolean(claims.error));
    return <div className="space-y-3">
        <p className="text-xs text-[var(--studio-text-muted)]">取り置きの紐づけは「資産 &gt; 口座」から行います。</p>
        <Feedback loading={claims.loading} error={claims.error} />
        {sources.length ? <table className="w-full text-left text-xs">
            <caption className="sr-only">取り置きの紐づいている口座と確保額</caption>
            <thead className="text-[var(--studio-text-muted)]"><tr><th scope="col" className="pb-2 font-medium">口座</th><th scope="col" className="pb-2 text-right font-medium">確保額</th><th scope="col" className="pb-2 text-right font-medium">上限</th></tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">{sources.map((source) => {
                // Failed or stale reads must not invent a zero claim for an account.
                const earmark = !claims.loading && !claims.error ? claims.data?.find((row) => row.source.account_id === source.account_id)?.earmark : undefined;
                return <tr key={source.id}>
                    <th scope="row" className="py-2 font-normal">{source.account_name ?? `口座 #${source.account_id}`}</th>
                    <td className="whitespace-nowrap py-2 text-right tabular-nums">{earmark ? formatCurrency(earmark.claimed, earmark.currency) : claims.loading ? '読み込み中…' : '確認できません'}</td>
                    <td className="whitespace-nowrap py-2 text-right tabular-nums">{shareLabel(earmark ? earmark.max_share_bp : source.max_share_bp)}</td>
                </tr>;
            })}</tbody>
        </table> : <p className="text-sm text-[var(--studio-text-muted)]">紐づいている口座はありません。</p>}
    </div>;
}
