import { useCallback, useEffect, useRef, useState } from 'react';
import { deleteTransaction, getTransactionsPage } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { Transaction } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { assetErrorMessage, useResource } from '../../useResource';
import MonthPicker from './MonthPicker';
import { currentMonth, monthRange } from './periods';

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

function RecordResults({ month, currency, onDeleted, onBusy }: {
    month: string;
    currency: string;
    onDeleted: () => void;
    onBusy: (busy: boolean) => void;
}) {
    const loadPage = useCallback(() => getTransactionsPage({ ...monthRange(month), limit: PAGE_SIZE, offset: 0 }), [month]);
    const { data: page, setData, loading, error, reload } = useResource(loadPage);
    const [busy, setBusy] = useState(false);
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
        if (!window.confirm(`${transaction.date}「${transaction.description || '内容未入力'}」${amount} の記録を削除しますか？\n削除は取り消せません。`)) return;
        inFlight.current = true;
        setBusy(true);
        onBusy(true);
        setOperationError('');
        setConfirmation('');
        try {
            await deleteTransaction(transaction.id);
            if (!mounted.current) return;
            setData((previous) => previous ? { items: previous.items.filter((row) => row.id !== transaction.id), total: Math.max(0, previous.total - 1) } : null);
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

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between gap-4">
                <h2 className="text-lg font-semibold">すべての記録</h2>
                <button type="button" onClick={reload} disabled={loading || busy} className={buttonClass}>再読み込み</button>
            </div>
            {loading && <p role="status" className="text-sm text-[var(--studio-text-muted)]">記録を読み込んでいます…</p>}
            {error && <p role="alert" className="text-sm text-[var(--studio-danger)]">記録を取得できませんでした。{error}</p>}
            {operationError && <p role="alert" className="text-sm text-[var(--studio-danger)]">{operationError}</p>}
            {confirmation && <p role="status" className="rounded-md bg-[var(--studio-accent-soft)] p-3 text-sm text-[var(--studio-positive)]">{confirmation}</p>}
            {page && (page.items.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
                    <table className="w-full text-left text-sm" aria-busy={loading || busy}>
                        <caption className="sr-only">{month}の記録（新しい順）</caption>
                        <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]">
                            <tr><th scope="col" className="px-5 py-3 font-medium">日付</th><th scope="col" className="px-5 py-3 font-medium">内容</th><th scope="col" className="px-5 py-3 text-right font-medium">金額</th><th scope="col" className="px-5 py-3 font-medium">口座</th><th scope="col" className="px-5 py-3 font-medium">操作</th></tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--studio-border)]">
                            {page.items.map((transaction) => (
                                <tr key={transaction.id}>
                                    <td className="whitespace-nowrap px-5 py-3 text-[var(--studio-text-muted)]"><time dateTime={transaction.date}>{transaction.date}</time></td>
                                    <th scope="row" className="px-5 py-3 font-medium">{transaction.description || '内容未入力'}</th>
                                    <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums">{formatCurrency(transaction.amount, transaction.currency || currency)}<span className="ml-2 text-xs text-[var(--studio-text-muted)]">{transaction.currency || currency}</span></td>
                                    <td className="px-5 py-3 text-[var(--studio-text-muted)]">{accountLabel(transaction)}</td>
                                    <td className="px-5 py-3"><button type="button" onClick={() => void remove(transaction)} disabled={loading || Boolean(error) || busy} aria-label={`${transaction.date} ${transaction.description}を削除`} className="rounded-md border border-[var(--studio-border)] px-3 py-1.5 text-xs text-[var(--studio-danger)] hover:bg-[var(--studio-bg)] disabled:opacity-40">削除</button></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ) : !loading && !error && <p className="rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-6 text-sm text-[var(--studio-text-muted)]">この月の記録はありません。</p>)}
            {page && page.items.length < page.total && <button type="button" onClick={() => void loadMore()} disabled={loading || Boolean(error) || busy} className={buttonClass}>{busy ? '処理中…' : '次を読み込む'}（{page.items.length} / {page.total}件）</button>}
        </div>
    );
}

export default function Records({ onDeleted }: { onDeleted: () => void }) {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const [month, setMonth] = useState(currentMonth);
    const [busy, setBusy] = useState(false);

    return (
        <section className="space-y-4">
            <MonthPicker value={month} onChange={setMonth} disabled={busy} />
            {/* Remounting prevents an old month's request from replacing the new month. */}
            <RecordResults key={month} month={month} currency={currency} onDeleted={onDeleted} onBusy={setBusy} />
        </section>
    );
}
