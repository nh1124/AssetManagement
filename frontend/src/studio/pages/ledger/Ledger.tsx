import { getTransactionProposals } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { TransactionProposal } from '../../../types';
import { useResource } from '../../useResource';
import Records from './Records';
import AutoTransactions from './AutoTransactions';

const loadPending = (): Promise<TransactionProposal[]> => getTransactionProposals({ status: 'pending' });

function LedgerForClient({ automatic }: { automatic: boolean }) {
    const { data: proposals, setData, loading, error, reload } = useResource(loadPending);

    return (
        <>
            {/* Keep the pending count beside the route tabs on both ledger views. */}
            <div className="-mt-2 mb-4 flex items-center gap-3 text-xs text-[var(--studio-text-muted)]" aria-live="polite">
                <span>未反映：{loading ? '確認中…' : error ? '件数を取得できませんでした' : `${proposals?.length ?? 0}件`}</span>
            </div>
            {automatic ? (
                <AutoTransactions proposals={proposals} loading={loading} error={error} onDecided={(id) => {
                    // Remove a decided proposal immediately, even if the refresh fails.
                    setData((rows) => rows?.filter((row) => row.id !== id) ?? null);
                    reload();
                }} />
            ) : <Records onDeleted={reload} />}
        </>
    );
}

export default function Ledger({ automatic = false }: { automatic?: boolean }) {
    const { clientId } = useClient();
    // A client change discards old rows and outstanding responses together.
    return <LedgerForClient key={clientId} automatic={automatic} />;
}
