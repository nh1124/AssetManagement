import { useCallback } from 'react';
import { getAccountEarmarks } from '../../../api';
import type { CapsuleFundingSource } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback } from '../db/Database';
import { tr } from '../../i18n';

export default function EarmarkAccounts({ capsuleId, sources }: { capsuleId: number; sources: CapsuleFundingSource[] }) {
    const load = useCallback(async () => Promise.all(sources.map(async (source) => {
        const earmarks = await getAccountEarmarks(source.account_id);
        return { source, earmark: earmarks.find((earmark) => earmark.capsule_id === capsuleId) };
    })), [capsuleId, sources]);
    const claims = useResource(load);
    return <div className="space-y-3">
        <Feedback loading={claims.loading} error={claims.error} />
        <DataTable columns={[tr('口座', 'Account'), tr('確保額（現在）', 'Set aside (now)')]}>
            {sources.length ? sources.map((source) => {
                // Failed or stale reads must not invent a zero claim for an account.
                const earmark = !claims.loading && !claims.error ? claims.data?.find((row) => row.source.account_id === source.account_id)?.earmark : undefined;
                return <tr key={source.id}>
                    <th scope="row" className="px-5 py-3 font-normal">{source.account_name ?? tr(`口座 #${source.account_id}`, `Account #${source.account_id}`)}</th>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{earmark ? formatCurrency(earmark.claimed, earmark.currency) : claims.loading ? tr('読み込み中…', 'Loading…') : tr('確認できません', 'Unknown')}</td>
                </tr>;
            }) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('紐づいている口座はありません。', 'No accounts linked.')}</td></tr>}
        </DataTable>
    </div>;
}
