import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Search, Clock3 } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { approveTransactionProposal, getProfitLoss, getTransactionProposals, getTransactionsPage, rejectTransactionProposal } from '../../api';
import { useClient } from '../../context/ClientContext';
import type { Transaction, TransactionProposal } from '../../types';
import { formatCurrency } from '../../utils/currency';
import { clientToday, useTimezone } from '../../studio/datetime';
import { loadAccounts } from '../../studio/pages/db/forms';
import { monthRange } from '../../studio/pages/ledger/periods';
import { assetErrorMessage, useResource } from '../../studio/useResource';
import { Screen } from '../components/Layout';
import MonthSwitcher from '../components/MonthSwitcher';
import { monthParam } from '../months';
import { useRecording } from '../components/recording';
import { useSnack } from '../components/snack';
import { TransactionRow } from '../components/transactions';
import { direction } from '../direction';
import { Badge, Empty, ErrorNote, fieldClass, focusRing, secondaryButton, Skeleton } from '../components/ui';
import { accountTypes } from '../data';
import { tr } from '../../studio/i18n';

const PAGE = 100;
const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];

function dayLabel(day: string): string {
    const date = new Date(`${day}T00:00:00`);
    return tr(`${date.getMonth() + 1}月${date.getDate()}日（${WEEKDAYS[date.getDay()]}）`, date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }));
}

/** Automatic transactions waiting to be posted: post or reject each. */
function Pending({ proposals, currency, onDecided }: { proposals: TransactionProposal[]; currency: string; onDecided: () => void }) {
    const snack = useSnack();
    const [busy, setBusy] = useState<number | null>(null);
    const decide = async (proposal: TransactionProposal, approve: boolean) => {
        setBusy(proposal.id);
        try {
            if (approve) await approveTransactionProposal(proposal.id);
            else await rejectTransactionProposal(proposal.id);
            snack(approve ? tr('記帳しました', 'Recorded') : tr('却下しました', 'Rejected'));
            onDecided();
        } catch (failure) {
            snack(assetErrorMessage(failure), 'error');
            setBusy(null);
        }
    };
    return <section aria-label={tr('未反映の自動取引', 'Automatic transactions not yet recorded')} className="space-y-2">
        <h2 className="flex items-center gap-1.5 px-1 text-xs font-semibold text-[var(--studio-warning)]"><Clock3 size={14} aria-hidden />{tr(`未反映の自動取引 ${proposals.length}件`, `Not yet recorded: ${proposals.length}`)}</h2>
        <div className="divide-y divide-[var(--studio-border)] overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">
            {proposals.map((proposal) => <div key={proposal.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{proposal.description || tr('内容なし', 'Untitled')}</p>
                    <p className="text-xs text-[var(--studio-text-muted)]">{proposal.date}{tr('・', ' · ')}{formatCurrency(proposal.amount, proposal.currency || currency)}</p>
                </div>
                <button type="button" disabled={busy !== null} onClick={() => void decide(proposal, false)} className={`min-h-11 rounded-lg px-3 text-xs font-medium text-[var(--studio-text-muted)] active:bg-[var(--studio-bg)] ${focusRing}`}>{tr('却下', 'Reject')}</button>
                <button type="button" disabled={busy !== null} onClick={() => void decide(proposal, true)} className={`min-h-11 rounded-lg bg-[var(--studio-accent)] px-4 text-xs font-semibold text-white active:opacity-80 ${focusRing}`}>{busy === proposal.id ? tr('記帳中…', 'Recording…') : tr('記帳', 'Record')}</button>
            </div>)}
        </div>
    </section>;
}

/** The month's records by day, newest first, with the ones waiting to be posted on top. */
export default function Ledger() {
    const { currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const timezone = useTimezone();
    const current = clientToday(timezone).slice(0, 7);
    const [params, setParams] = useSearchParams();
    const month = monthParam(params.get('month'), current);
    const { open, changed } = useRecording();
    const snack = useSnack();
    // The search lives in the URL with the month, so it survives the reload after a save.
    const query = params.get('q') ?? '';
    // Rows loaded with もっと見る belong to the month they were loaded for.
    const [extra, setExtra] = useState<{ month: string; rows: Transaction[] }>({ month, rows: [] });
    const [loadingMore, setLoadingMore] = useState(false);
    // Every month change starts the pages again; a page asked for before it is dropped, even back on the same month.
    const visit = useRef(0);
    useEffect(() => {
        visit.current += 1;
    }, [month]);
    const load = useCallback(async () => {
        const range = monthRange(month);
        const [page, accounts, proposals, profit] = await Promise.all([
            getTransactionsPage({ ...range, limit: PAGE, offset: 0 }), loadAccounts(), getTransactionProposals({ status: 'pending' }),
            getProfitLoss(undefined, undefined, range.startDate, range.endDate) as Promise<{ total_income: number; total_expenses: number }>]);
        return { month, page, types: accountTypes(accounts), proposals, profit };
    }, [month]);
    const resource = useResource(load);
    // A month still loading never shows the previous month's records.
    const data = resource.data?.month === month ? resource.data : null;
    const [seen, setSeen] = useState(month);
    if (seen !== month) {
        // Leaving a month forgets its extra pages, so coming back starts from the first page.
        setSeen(month);
        setExtra({ month, rows: [] });
    }
    const items = useMemo(() => [...(data?.page.items ?? []), ...(extra.month === month ? extra.rows : [])], [data, extra, month]);
    const needle = query.trim().toLowerCase();
    const shown = needle ? items.filter((item) => [item.description, item.from_account_name, item.to_account_name].some((text) => text?.toLowerCase().includes(needle))) : items;
    const days = useMemo(() => {
        const groups = new Map<string, Transaction[]>();
        for (const item of shown) groups.set(item.date, [...(groups.get(item.date) ?? []), item]);
        return [...groups].sort(([a], [b]) => b.localeCompare(a));
    }, [shown]);
    const types = data?.types ?? new Map();
    // The month's totals come from the ledger; a search totals what it found in the client's currency.
    const found = (kind: 'expense' | 'income') => shown.reduce((sum, item) => sum + ((item.currency || currency) === currency && direction(item, types) === kind ? item.amount : 0), 0);
    const spent = needle ? found('expense') : data?.profit.total_expenses ?? 0;
    const earned = needle ? found('income') : data?.profit.total_income ?? 0;
    const total = data?.page.total ?? 0;
    const more = async () => {
        const asked = month;
        const ticket = visit.current;
        setLoadingMore(true);
        try {
            const next = await getTransactionsPage({ ...monthRange(asked), limit: PAGE, offset: items.length });
            if (visit.current === ticket) setExtra((loaded) => ({ month: asked, rows: [...(loaded.month === asked ? loaded.rows : []), ...next.items] }));
        } catch (failure) {
            snack(tr(`続きを読み込めませんでした。${assetErrorMessage(failure)}`, `Could not load more. ${assetErrorMessage(failure)}`), 'error');
        } finally {
            setLoadingMore(false);
        }
    };
    const setParam = (key: 'month' | 'q', value: string) => {
        const next = new URLSearchParams(params);
        if (value && !(key === 'month' && value === current)) next.set(key, value); else next.delete(key);
        setParams(next, { replace: true });
    };
    return <Screen title={tr('家計簿', 'Ledger')} top>
        <MonthSwitcher period={month} current={current} onChange={(next) => setParam('month', next)} />
        <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl bg-[var(--studio-surface)] p-3 shadow-[var(--mobile-shadow)]"><p className="text-xs text-[var(--studio-text-muted)]">{tr('支出', 'Spending')}{needle ? tr('（見つかった分）', ' (found)') : ''}</p><p className="text-lg font-bold tabular-nums">{formatCurrency(spent, currency)}</p></div>
            <div className="rounded-2xl bg-[var(--studio-surface)] p-3 shadow-[var(--mobile-shadow)]"><p className="text-xs text-[var(--studio-text-muted)]">{tr('収入', 'Income')}{needle ? tr('（見つかった分）', ' (found)') : ''}</p><p className="text-lg font-bold tabular-nums text-[var(--studio-positive)]">{formatCurrency(earned, currency)}</p></div>
        </div>
        {needle && <p className="-mt-2 px-1 text-xs text-[var(--studio-text-muted)]">{tr(`検索中の合計は、見つかった記録のうち${currency}の 2 行の記録（支出・収入）だけです。`, `While searching, totals count only the two-line ${currency} records (spending and income) that were found.`)}</p>}
        <label className="relative block">
            <span className="sr-only">{tr('記録を探す', 'Search records')}</span>
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--studio-text-faint)]" aria-hidden />
            <input type="search" value={query} onChange={(event) => setParam('q', event.target.value)} placeholder={tr('内容・口座で探す', 'Search by description or account')} className={`${fieldClass} pl-9`} />
        </label>
        {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
        {!data && !resource.error && <Skeleton lines={4} />}
        {data && data.proposals.length > 0 && <Pending proposals={data.proposals} currency={currency} onDecided={changed} />}
        {data && (days.length ? days.map(([day, rows]) => <section key={day} aria-label={dayLabel(day)}>
            <h2 className="mb-1.5 flex items-center justify-between px-1 text-xs font-semibold text-[var(--studio-text-muted)]"><span>{dayLabel(day)}</span>
                {rows.length > 1 && <Badge>{tr(`${rows.length}件`, `${rows.length}`)}</Badge>}</h2>
            <div className="divide-y divide-[var(--studio-border)] overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">
                {rows.map((transaction) => <TransactionRow key={transaction.id} transaction={transaction} types={types} currency={currency} onOpen={open} showDate={false} />)}
            </div>
        </section>) : <Empty title={needle ? tr('見つかりません', 'Nothing found') : tr('この月の記録はありません', 'No records this month')} body={needle ? tr('別のことばで探してください。', 'Try other words.') : tr('＋ から記録できます。', 'Record with +.')} />)}
        {data && items.length < total && <button type="button" disabled={loadingMore} onClick={() => void more()} className={`${secondaryButton} w-full`}>{loadingMore ? tr('読み込んでいます…', 'Loading…') : tr(`もっと見る（残り ${total - items.length}件）`, `Show more (${total - items.length} left)`)}</button>}
    </Screen>;
}
