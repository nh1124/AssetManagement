import { useConfirm } from '../../components/useConfirm';
import { clientToday, formatDate, useTimezone } from '../../datetime';
import { useCallback, useEffect, useRef, useState } from 'react';
import { deleteTransaction, getTransaction, getTransactionsPage } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { Transaction } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';
import { Link, useSearchParams } from 'react-router-dom';
import Overlay from '../../components/Overlay';
import RecordForm from '../RecordForm';
import { Feedback } from '../db/Database';
import MonthlyClose from './MonthlyClose';
import MonthPicker from './MonthPicker';
import { monthRange } from './periods';

const PAGE_SIZE = 50;
const buttonClass = 'rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-text-muted)] hover:bg-[var(--studio-accent-soft)] disabled:opacity-40';

function accountLabel(transaction: Transaction): string {
    if ((transaction.legs?.length ?? 0) > 2) return '複数';
    const name = (side: 'credit' | 'debit') => {
        const leg = transaction.legs?.find((entry) => (entry[side] ?? 0) > 0);
        return leg && 'account_name' in leg && typeof leg.account_name === 'string' ? leg.account_name : '—';
    };
    return `${transaction.from_account_name || name('credit')} → ${transaction.to_account_name || name('debit')}`;
}

function RecordEditor({ transactionId, busy, error, onClose, onSaved, onDelete }: {
    transactionId: number;
    busy: boolean;
    error: string;
    onClose: () => void;
    onSaved: () => void;
    onDelete: (transaction: Transaction) => void;
}) {
    // List rows omit journal legs, so editing must start from the full transaction.
    const load = useCallback(() => getTransaction(transactionId), [transactionId]);
    const resource = useResource(load);
    const transaction = resource.data;
    return <Overlay title={transaction ? `「${transaction.description || '内容未入力'}」を編集` : `取引 #${transactionId}を編集`} onClose={onClose}>
        <Feedback loading={resource.loading} error={resource.error || error} />
        {transaction && !resource.loading && !resource.error && <RecordForm existing={transaction} onSaved={onSaved} onCancel={onClose} onDelete={() => onDelete(transaction)} deleting={busy} />}
    </Overlay>;
}

function RecordResults({ month, currency, onDeleted, onBusy }: {
    month: string;
    currency: string;
    onDeleted: () => void;
    onBusy: (busy: boolean) => void;
}) {
    const confirm = useConfirm();
    const timezone = useTimezone();
    const loadPage = useCallback(() => getTransactionsPage({ ...monthRange(month), limit: PAGE_SIZE, offset: 0 }), [month]);
    const { data: page, setData, loading, error, reload } = useResource(loadPage);
    const [busy, setBusy] = useState(false);
    const [editingId, setEditingId] = useState<number | null>(null);
    const [operationError, setOperationError] = useState('');
    const [confirmation, setConfirmation] = useState('');
    const inFlight = useRef(false);
    const mounted = useRef(false);

    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    const loadMore = async () => {
        if (!page || inFlight.current || loading || error) return;
        inFlight.current = true;
        setBusy(true);
        onBusy(true);
        setOperationError('');
        try {
            const next = await getTransactionsPage({ ...monthRange(month), limit: PAGE_SIZE, offset: page.items.length });
            if (mounted.current) setData({ items: [...page.items, ...next.items], total: next.total });
        } catch (failure: unknown) {
            if (mounted.current) setOperationError(`次の記録を取得できませんでした。${assetErrorMessage(failure)}`);
        } finally {
            inFlight.current = false;
            if (mounted.current) { setBusy(false); onBusy(false); }
        }
    };

    const remove = async (transaction: Transaction) => {
        if (inFlight.current || loading || error) return;
        const amount = `${formatCurrency(transaction.amount, transaction.currency || currency)} (${transaction.currency || currency})`;
        if (!(await confirm(`${transaction.date}「${transaction.description || '内容未入力'}」${amount} の記録を削除しますか？\n削除は取り消せません。`, '削除する'))) return;
        inFlight.current = true;
        setBusy(true);
        onBusy(true);
        setOperationError('');
        setConfirmation('');
        try {
            await deleteTransaction(transaction.id);
            if (!mounted.current) return;
            setData((previous) => previous ? { items: previous.items.filter((row) => row.id !== transaction.id), total: Math.max(0, previous.total - 1) } : null);
            setEditingId(null);
            setConfirmation(`${transaction.date}「${transaction.description || '内容未入力'}」を削除しました。`);
            // Reload from offset zero because deleting changes every later offset.
            reload();
            onDeleted();
        } catch (failure: unknown) {
            if (mounted.current) setOperationError(`記録を削除できませんでした。${assetErrorMessage(failure)}`);
        } finally {
            inFlight.current = false;
            if (mounted.current) { setBusy(false); onBusy(false); }
        }
    };

    const openEditor = (id: number) => {
        if (loading || error || busy || editingId !== null) return;
        setOperationError('');
        setConfirmation('');
        setEditingId(id);
    };

    return (
        <div className="space-y-4">
            {editingId !== null && <RecordEditor key={editingId} transactionId={editingId} busy={busy} error={operationError} onClose={() => setEditingId(null)} onSaved={() => {
                setEditingId(null);
                reload();
                onDeleted();
            }} onDelete={(transaction) => void remove(transaction)} />}
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">記録を読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">記録を取得できませんでした。{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="rounded-md bg-[var(--studio-accent-soft)] p-3 text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {page && (page.items.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="w-full text-left text-sm" aria-busy={loading || busy}>
                        <caption className="sr-only">{month}の記録（新しい順）</caption>
                        <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                            <tr><th scope="col" className="px-5 py-3 font-medium">日付</th><th scope="col" className="px-5 py-3 font-medium">内容</th><th scope="col" className="px-5 py-3 text-right font-medium">金額</th><th scope="col" className="px-5 py-3 font-medium">口座</th></tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--studio-border)]">
                            {page.items.map((transaction) => (
                                <tr key={transaction.id} onClick={() => openEditor(transaction.id)} className={loading || error || busy || editingId !== null ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]'}>
                                    <td className="whitespace-nowrap px-5 py-3 text-[var(--studio-text-muted)]"><time dateTime={transaction.date}>{formatDate(transaction.date, timezone)}</time></td>
                                    <th scope="row" className="px-5 py-3 font-medium"><button type="button" disabled={loading || Boolean(error) || busy || editingId !== null} aria-label={`${transaction.date} ${transaction.description || '内容未入力'}を編集`} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); openEditor(transaction.id); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{transaction.description || '内容未入力'}</button></th>
                                    <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums">{formatCurrency(transaction.amount, transaction.currency || currency)}<span className="ml-2 text-xs text-[var(--studio-text-muted)]">{transaction.currency || currency}</span></td>
                                    <td className="px-5 py-3 text-[var(--studio-text-muted)]">{accountLabel(transaction)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ) : !loading && !error && <div className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]"><p>この月の記録はありません。</p><Link to="/record" className={`inline-block ${buttonClass}`}>取引を記録</Link></div>)}
            {page && page.items.length < page.total && <button type="button" onClick={() => void loadMore()} disabled={loading || Boolean(error) || busy} className={buttonClass}>{busy ? '処理中…' : '次を読み込む'}（{page.items.length} / {page.total}件）</button>}
        </div>
    );
}

export default function Records({ onDeleted }: { onDeleted: () => void }) {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const timezone = useTimezone();
    const [search, setSearch] = useSearchParams();
    const monthEdit = search.get('month');
    const today = clientToday(timezone).slice(0, 7);
    const month = monthEdit && /^\d{4}-(0[1-9]|1[0-2])$/.test(monthEdit) ? monthEdit : today;
    const setMonth = (value: string) => setSearch((previous) => {
        const next = new URLSearchParams(previous);
        next.set('month', value);
        return next;
    }, { replace: true });
    const [busy, setBusy] = useState(false);

    return (
        <section className="space-y-4">
            <MonthPicker value={month} onChange={setMonth} disabled={busy} />
            <MonthlyClose key={month} period={month} currentPeriod={today} disabled={busy} onBusy={setBusy} onSelect={setMonth} />
            {/* Remounting prevents an old month's request from replacing the new month. */}
            <RecordResults key={month} month={month} currency={currency} onDeleted={onDeleted} onBusy={setBusy} />
        </section>
    );
}
