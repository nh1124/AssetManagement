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

const PAGE = 100;
const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];

function dayLabel(day: string): string {
    const date = new Date(`${day}T00:00:00`);
    return `${date.getMonth() + 1}月${date.getDate()}日（${WEEKDAYS[date.getDay()]}）`;
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
            snack(approve ? '記帳しました' : '却下しました');
            onDecided();
        } catch (failure) {
            snack(assetErrorMessage(failure), 'error');
            setBusy(null);
        }
    };
    return <section aria-label="未反映の自動取引" className="space-y-2">
        <h2 className="flex items-center gap-1.5 px-1 text-xs font-semibold text-[var(--studio-warning)]"><Clock3 size={14} aria-hidden />未反映の自動取引 {proposals.length}件</h2>
        <div className="divide-y divide-[var(--studio-border)] overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">
            {proposals.map((proposal) => <div key={proposal.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{proposal.description || '内容なし'}</p>
                    <p className="text-xs text-[var(--studio-text-muted)]">{proposal.date}・{formatCurrency(proposal.amount, proposal.currency || currency)}</p>
                </div>
                <button type="button" disabled={busy !== null} onClick={() => void decide(proposal, false)} className={`min-h-11 rounded-lg px-3 text-xs font-medium text-[var(--studio-text-muted)] active:bg-[var(--studio-bg)] ${focusRing}`}>却下</button>
                <button type="button" disabled={busy !== null} onClick={() => void decide(proposal, true)} className={`min-h-11 rounded-lg bg-[var(--studio-accent)] px-4 text-xs font-semibold text-white active:opacity-80 ${focusRing}`}>{busy === proposal.id ? '記帳中…' : '記帳'}</button>
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
    const shownMonth = useRef(month);
    useEffect(() => { shownMonth.current = month; }, [month]);
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
        setLoadingMore(true);
        try {
            const next = await getTransactionsPage({ ...monthRange(asked), limit: PAGE, offset: items.length });
            // A page for a month the user has left is dropped.
            if (shownMonth.current === asked) setExtra((loaded) => ({ month: asked, rows: [...(loaded.month === asked ? loaded.rows : []), ...next.items] }));
        } catch (failure) {
            snack(`続きを読み込めませんでした。${assetErrorMessage(failure)}`, 'error');
        } finally {
            setLoadingMore(false);
        }
    };
    const setParam = (key: 'month' | 'q', value: string) => {
        const next = new URLSearchParams(params);
        if (value && !(key === 'month' && value === current)) next.set(key, value); else next.delete(key);
        setParams(next, { replace: true });
    };
    return <Screen title="家計簿" top>
        <MonthSwitcher period={month} current={current} onChange={(next) => setParam('month', next)} />
        <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl bg-[var(--studio-surface)] p-3 shadow-[var(--mobile-shadow)]"><p className="text-xs text-[var(--studio-text-muted)]">支出{needle ? '（見つかった分）' : ''}</p><p className="text-lg font-bold tabular-nums">{formatCurrency(spent, currency)}</p></div>
            <div className="rounded-2xl bg-[var(--studio-surface)] p-3 shadow-[var(--mobile-shadow)]"><p className="text-xs text-[var(--studio-text-muted)]">収入{needle ? '（見つかった分）' : ''}</p><p className="text-lg font-bold tabular-nums text-[var(--studio-positive)]">{formatCurrency(earned, currency)}</p></div>
        </div>
        <label className="relative block">
            <span className="sr-only">記録を探す</span>
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--studio-text-faint)]" aria-hidden />
            <input type="search" value={query} onChange={(event) => setParam('q', event.target.value)} placeholder="内容・口座で探す" className={`${fieldClass} pl-9`} />
        </label>
        {resource.error && <ErrorNote message={resource.error} onRetry={resource.reload} />}
        {!data && !resource.error && <Skeleton lines={4} />}
        {data && data.proposals.length > 0 && <Pending proposals={data.proposals} currency={currency} onDecided={changed} />}
        {data && (days.length ? days.map(([day, rows]) => <section key={day} aria-label={dayLabel(day)}>
            <h2 className="mb-1.5 flex items-center justify-between px-1 text-xs font-semibold text-[var(--studio-text-muted)]"><span>{dayLabel(day)}</span>
                {rows.length > 1 && <Badge>{rows.length}件</Badge>}</h2>
            <div className="divide-y divide-[var(--studio-border)] overflow-hidden rounded-2xl bg-[var(--studio-surface)] shadow-[var(--mobile-shadow)]">
                {rows.map((transaction) => <TransactionRow key={transaction.id} transaction={transaction} types={types} currency={currency} onOpen={open} showDate={false} />)}
            </div>
        </section>) : <Empty title={needle ? '見つかりません' : 'この月の記録はありません'} body={needle ? '別のことばで探してください。' : '＋ から記録できます。'} />)}
        {data && items.length < total && <button type="button" disabled={loadingMore} onClick={() => void more()} className={`${secondaryButton} w-full`}>{loadingMore ? '読み込んでいます…' : `もっと見る（残り ${total - items.length}件）`}</button>}
    </Screen>;
}
