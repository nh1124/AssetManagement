import { useReloadAction } from '../../components/useReloadAction';
import { useEffect, useRef, useState } from 'react';
import { approveTransactionProposal, getAccounts, rejectTransactionProposal } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { Account, TransactionProposal } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';

async function loadAccountNames(): Promise<Map<number, string>> {
    // Pending proposals can still refer to an account that has been archived.
    const [active, inactive]: [Account[], Account[]] = await Promise.all([
        getAccounts(undefined, true), getAccounts(undefined, false),
    ]);
    return new Map([...inactive, ...active].map((account) => [account.id, account.name]));
}

export default function Unmatched({ proposals, loading, error, reload, onDecided }: {
    proposals: TransactionProposal[] | null;
    loading: boolean;
    error: string;
    reload: () => void;
    onDecided: (id: number) => void;
}) {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const { data: names, loading: namesLoading, error: namesError, reload: reloadNames } = useResource(loadAccountNames);
    const [decidingId, setDecidingId] = useState<number | null>(null);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const inFlight = useRef(false);
    const mounted = useRef(false);

    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    const decide = async (proposal: TransactionProposal, approve: boolean) => {
        if (inFlight.current || loading || error || namesLoading || namesError) return;
        inFlight.current = true;
        setDecidingId(proposal.id);
        setOperationError('');
        setConfirmation('');
        try {
            if (approve) await approveTransactionProposal(proposal.id);
            else await rejectTransactionProposal(proposal.id);
            if (!mounted.current) return;
            setConfirmation(approve ? `「${proposal.description || '内容未入力'}」を承認し、取引を記帳しました。` : `「${proposal.description || '内容未入力'}」を却下しました。`);
            onDecided(proposal.id);
        } catch (failure: unknown) {
            if (mounted.current) setOperationError(`提案を${approve ? '承認' : '却下'}できませんでした。${assetErrorMessage(failure)}`);
        } finally {
            inFlight.current = false;
            if (mounted.current) setDecidingId(null);
        }
    };

    const refresh = () => { reload(); reloadNames(); };
    const disabled = loading || Boolean(error) || namesLoading || Boolean(namesError) || decidingId !== null;

    useReloadAction(refresh, Boolean(loading || namesLoading || decidingId !== null));
    return (
        <section className="space-y-4">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <p className="mt-1 text-xs text-[var(--studio-text-muted)]">システムが提案した記録です。承認すると実際の取引として記帳されます。</p>
                </div>
            </div>
            {(loading || namesLoading) && <p role="status" className="text-sm text-[var(--studio-text-muted)]">提案と口座名を読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">提案を取得できませんでした。{error}</p>}
            {namesError && <p role="alert" className="text-sm text-[var(--studio-danger)]">口座名を取得できませんでした。{namesError}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="rounded-md bg-[var(--studio-accent-soft)] p-3 text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {proposals && (proposals.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="w-full text-left text-sm" aria-busy={loading || namesLoading || decidingId !== null}>
                        <caption className="sr-only">判断を待っている取引の提案</caption>
                        <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                            <tr><th scope="col" className="px-5 py-3 font-medium">日付</th><th scope="col" className="px-5 py-3 font-medium">内容</th><th scope="col" className="px-5 py-3 text-right font-medium">金額</th><th scope="col" className="px-5 py-3 font-medium">内訳（口座・借方／貸方）</th><th scope="col" className="px-5 py-3 font-medium">操作</th></tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--studio-border)]">
                            {proposals.map((proposal) => {
                                const entryCurrency = proposal.currency || currency;
                                return (
                                    <tr key={proposal.id}>
                                        <td className="whitespace-nowrap px-5 py-3 align-top text-[var(--studio-text-muted)]"><time dateTime={proposal.date}>{proposal.date}</time></td>
                                        <th scope="row" className="px-5 py-3 align-top font-medium">{proposal.description || '内容未入力'}</th>
                                        <td className="whitespace-nowrap px-5 py-3 text-right align-top tabular-nums">{formatCurrency(proposal.amount, entryCurrency)}<span className="ml-2 text-xs text-[var(--studio-text-muted)]">{entryCurrency}</span></td>
                                        <td className="px-5 py-3 align-top">
                                            <ul className="space-y-2 text-xs text-[var(--studio-text-muted)]">
                                                {proposal.legs.map((leg, index) => (
                                                    <li key={`${leg.account_id}-${index}`}>
                                                        <span className="font-medium text-[var(--studio-text)]">{names?.get(leg.account_id) ?? `口座 #${leg.account_id}`}</span>
                                                        {(leg.debit ?? 0) > 0 && <span className="ml-2 whitespace-nowrap">借方 {formatCurrency(leg.debit, entryCurrency)}</span>}
                                                        {(leg.credit ?? 0) > 0 && <span className="ml-2 whitespace-nowrap">貸方 {formatCurrency(leg.credit, entryCurrency)}</span>}
                                                    </li>
                                                ))}
                                            </ul>
                                        </td>
                                        <td className="px-5 py-3 align-top">
                                            <div className="flex flex-wrap gap-2">
                                                <button type="button" onClick={() => void decide(proposal, true)} disabled={disabled} aria-label={`${proposal.description}を承認して記帳`} className="whitespace-nowrap rounded-md bg-[var(--studio-accent)] px-3 py-1.5 text-xs text-[var(--studio-accent-text)] hover:opacity-90 disabled:opacity-40">承認して記帳</button>
                                                <button type="button" onClick={() => void decide(proposal, false)} disabled={disabled} aria-label={`${proposal.description}を却下`} className="rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-danger)] hover:bg-[var(--studio-bg)] disabled:opacity-40">却下</button>
                                                {decidingId === proposal.id && <span role="status" className="text-xs text-[var(--studio-text-muted)]">処理中…</span>}
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            ) : !loading && !error && <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">判断を待っている記録はありません。</p>)}
        </section>
    );
}
