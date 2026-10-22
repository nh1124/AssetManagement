import { useCallback, useEffect, useRef, useState } from 'react';
import { approveTransactionProposal, deleteTransaction, getAccounts, getGeneratedTransactions, rejectTransactionProposal } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { Account, TransactionProposal } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';
import { useSearchParams } from 'react-router-dom';
import { clientToday, useTimezone } from '../../datetime';
import { useConfirm } from '../../components/useConfirm';
import { DataTable, EditableRow, Feedback, RowTitle } from '../db/Database';
import { RecordEditor } from './Records';
import MonthPicker from './MonthPicker';
import { tr } from '../../i18n';


async function loadAccountNames(): Promise<Map<number, string>> {
    // Pending proposals can still refer to an account that has been archived.
    const [active, inactive]: [Account[], Account[]] = await Promise.all([
        getAccounts(undefined, true), getAccounts(undefined, false),
    ]);
    return new Map([...inactive, ...active].map((account) => [account.id, account.name]));
}

function PendingProposals({ proposals, loading, error, onDecided }: {
    proposals: TransactionProposal[] | null;
    loading: boolean;
    error: string;
    onDecided: (id: number) => void;
}) {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const { data: names, loading: namesLoading, error: namesError } = useResource(loadAccountNames);
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
            setConfirmation(approve
                ? tr(`「${proposal.description || '内容未入力'}」を承認し、取引を記帳しました。`, `Approved “${proposal.description || 'Untitled'}” and recorded the transaction.`)
                : tr(`「${proposal.description || '内容未入力'}」を却下しました。`, `Rejected “${proposal.description || 'Untitled'}”.`));
            onDecided(proposal.id);
        } catch (failure: unknown) {
            if (mounted.current) setOperationError(tr(`提案を${approve ? '承認' : '却下'}できませんでした。${assetErrorMessage(failure)}`, `Could not ${approve ? 'approve' : 'reject'} the proposal. ${assetErrorMessage(failure)}`));
        } finally {
            inFlight.current = false;
            if (mounted.current) setDecidingId(null);
        }
    };

    const disabled = loading || Boolean(error) || namesLoading || Boolean(namesError) || decidingId !== null;

    return (
        <section className="space-y-4">
            {(loading || namesLoading) && <p role="status" className="text-sm text-[var(--studio-text-muted)]">{tr('提案と口座名を読み込んでいます…', 'Loading proposals and account names…')}</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('提案を取得できませんでした。', 'Could not load proposals. ')}{error}</p>}
            {namesError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{tr('口座名を取得できませんでした。', 'Could not load account names. ')}{namesError}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="rounded-md bg-[var(--studio-accent-soft)] p-3 text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {proposals && (proposals.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="w-full text-left text-sm" aria-busy={loading || namesLoading || decidingId !== null}>
                        <caption className="sr-only">{tr('判断を待っている取引の提案', 'Transaction proposals awaiting a decision')}</caption>
                        <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                            <tr><th scope="col" className="px-5 py-3 font-medium">{tr('日付', 'Date')}</th><th scope="col" className="px-5 py-3 font-medium">{tr('内容', 'Description')}</th><th scope="col" className="px-5 py-3 text-right font-medium">{tr('金額', 'Amount')}</th><th scope="col" className="px-5 py-3 font-medium">{tr('内訳（口座・借方／貸方）', 'Lines (account, debit / credit)')}</th><th scope="col" className="px-5 py-3 font-medium">{tr('操作', 'Actions')}</th></tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--studio-border)]">
                            {proposals.map((proposal) => {
                                const entryCurrency = proposal.currency || currency;
                                return (
                                    <tr key={proposal.id}>
                                        <td className="whitespace-nowrap px-5 py-3 align-top text-[var(--studio-text-muted)]"><time dateTime={proposal.date}>{proposal.date}</time></td>
                                        <th scope="row" className="px-5 py-3 align-top font-medium">{proposal.description || tr('内容未入力', 'Untitled')}</th>
                                        <td className="whitespace-nowrap px-5 py-3 text-right align-top tabular-nums">{formatCurrency(proposal.amount, entryCurrency)}<span className="ml-2 text-xs text-[var(--studio-text-muted)]">{entryCurrency}</span></td>
                                        <td className="px-5 py-3 align-top">
                                            <ul className="space-y-2 text-xs text-[var(--studio-text-muted)]">
                                                {proposal.legs.map((leg, index) => (
                                                    <li key={`${leg.account_id}-${index}`}>
                                                        <span className="font-medium text-[var(--studio-text)]">{names?.get(leg.account_id) ?? tr(`口座 #${leg.account_id}`, `Account #${leg.account_id}`)}</span>
                                                        {(leg.debit ?? 0) > 0 && <span className="ml-2 whitespace-nowrap">{tr('借方', 'Debit')} {formatCurrency(leg.debit, entryCurrency)}</span>}
                                                        {(leg.credit ?? 0) > 0 && <span className="ml-2 whitespace-nowrap">{tr('貸方', 'Credit')} {formatCurrency(leg.credit, entryCurrency)}</span>}
                                                    </li>
                                                ))}
                                            </ul>
                                        </td>
                                        <td className="px-5 py-3 align-top">
                                            <div className="flex flex-wrap gap-2">
                                                <button type="button" onClick={() => void decide(proposal, true)} disabled={disabled} aria-label={tr(`${proposal.description}を承認して記帳`, `Approve and record ${proposal.description}`)} className="whitespace-nowrap rounded-md bg-[var(--studio-accent)] px-3 py-1.5 text-xs text-[var(--studio-accent-text)] hover:opacity-90 disabled:opacity-40">{tr('記帳', 'Record')}</button>
                                                <button type="button" onClick={() => void decide(proposal, false)} disabled={disabled} aria-label={tr(`${proposal.description}を却下`, `Reject ${proposal.description}`)} className="rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-danger)] hover:bg-[var(--studio-bg)] disabled:opacity-40">{tr('却下', 'Reject')}</button>
                                                {decidingId === proposal.id && <span role="status" className="text-xs text-[var(--studio-text-muted)]">{tr('処理中…', 'Working…')}</span>}
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            ) : !loading && !error && <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">{tr('未反映の候補はありません。', 'No candidates waiting.')}</p>)}
        </section>
    );
}

export default function AutoTransactions(props: Parameters<typeof PendingProposals>[0]) {
    const timezone = useTimezone();
    const [params, setParams] = useSearchParams();
    const requested = params.get('month') ?? '';
    const month = /^\d{4}-(0[1-9]|1[0-2])$/.test(requested) ? requested : clientToday(timezone).slice(0, 7);
    const load = useCallback(() => getGeneratedTransactions(month), [month]);
    const resource = useResource(load);
    const confirm = useConfirm();
    const [editing, setEditing] = useState<number | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    return <div className="space-y-6">
        <MonthPicker value={month} onChange={(value) => setParams({ month: value })} disabled={busy} />
        <section className="space-y-3"><h2 className="text-sm font-semibold">{tr('未反映', 'Not yet recorded')}</h2><PendingProposals {...props} onDecided={(id) => { props.onDecided(id); resource.reload(); }} /></section>
        <section className="space-y-3"><h2 className="text-sm font-semibold">{tr('発生した自動取引', 'Automatic transactions recorded')}</h2>
            <Feedback loading={resource.loading} error={error || resource.error} />
            <DataTable columns={[tr('日付', 'Date'), tr('摘要', 'Description'), tr('金額', 'Amount'), tr('生成元', 'Source')]}>
                {resource.data?.map((row) => <EditableRow key={row.id} disabled={busy} onEdit={() => setEditing(row.id)}>
                    <td className="px-5 py-3">{row.date}</td><RowTitle name={row.description} disabled={busy} onEdit={() => setEditing(row.id)}>{row.description}</RowTitle>
                    <td className="px-5 py-3 tabular-nums">{formatCurrency(row.amount, row.currency)}</td><td className="px-5 py-3">{row.source}</td>
                </EditableRow>)}
                {!resource.loading && !resource.data?.length && <tr><td colSpan={4} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('この月の自動取引はありません。', 'No automatic transactions this month.')}</td></tr>}
            </DataTable>
        </section>
        {editing !== null && <RecordEditor key={editing} transactionId={editing} busy={busy} error={error} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); resource.reload(); }} onDelete={async (transaction) => {
            if (busy || !(await confirm(tr(`「${transaction.description}」を削除しますか？`, `Delete “${transaction.description}”?`), tr('削除する', 'Delete')))) return;
            setBusy(true); setError('');
            try { await deleteTransaction(transaction.id); setEditing(null); resource.reload(); } catch (failure) { setError(assetErrorMessage(failure)); } finally { setBusy(false); }
        }} />}
    </div>;
}
