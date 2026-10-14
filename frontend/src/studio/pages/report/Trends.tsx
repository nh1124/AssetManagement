import { useReloadAction } from '../../components/useReloadAction';
import Overlay from '../../components/Overlay';
import { useCallback, useState } from 'react';
import { getAccountFlows, getAccountFlowTransactions, getNetWorthHistory } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { AccountFlowGrain, AccountFlowRow } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { ACCOUNT_TYPES, buttonClass, inputClass } from '../db/forms';
import { currentMonth, monthRange } from '../ledger/periods';
import { MoneyLineChart } from './Charts';

const GRAINS: Record<AccountFlowGrain, string> = { day: '日別', week: '週別', month: '月別', quarter: '四半期別' };
const PAGE_SIZE = 50;

function EntryPage({ accountId, startDate, endDate, currency, offset, onOffset }: {
    accountId: number; startDate: string; endDate: string; currency: string; offset: number; onOffset: (offset: number) => void;
}) {
    const load = useCallback(() => getAccountFlowTransactions({ accountId, startDate, endDate, limit: PAGE_SIZE, offset }), [accountId, startDate, endDate, offset]);
    const resource = useResource(load);
    useReloadAction(resource.reload, Boolean(resource.loading));
    return <div className="space-y-3">
        <div className="flex items-center justify-between gap-3"><p className="text-xs text-[var(--studio-text-muted)]">{startDate} 〜 {endDate}</p></div>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <>
            <DataTable columns={['日付・記録', '内容・相手先', `借方（${currency}）`, `貸方（${currency}）`, '元の通貨の借方 / 貸方']}>
                {resource.data.items.length ? resource.data.items.map((entry) => <tr key={entry.entry_id}>
                    <td className="whitespace-nowrap px-5 py-3"><time dateTime={entry.date}>{entry.date}</time><span className="mt-1 block text-xs text-[var(--studio-text-muted)]">取引 #{entry.transaction_id} ／ 仕訳 #{entry.entry_id}</span></td>
                    <td className="px-5 py-3">{entry.description || '内容未設定'}<span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{entry.counterpart_accounts.map((row) => row.account_name || `口座 #${row.account_id}`).join('、') || '相手先なし'}</span></td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(entry.debit, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(entry.credit, currency)}</td>
                    {/* Raw sides belong to the entry's currency; they must never be summed with converted sides. */}
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(entry.raw_debit, entry.currency)} / {formatCurrency(entry.raw_credit, entry.currency)}<span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{entry.currency}</span></td>
                </tr>) : <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">この期間の記録はありません。</td></tr>}
            </DataTable>
            <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-[var(--studio-text-muted)]"><p>{resource.data.total ? `${offset + 1} 〜 ${offset + resource.data.items.length} / ${resource.data.total} 件` : '0 件'}</p><div className="flex gap-2">
                <button type="button" disabled={resource.loading || offset === 0} onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))} className={buttonClass}>前の記録</button>
                <button type="button" disabled={resource.loading || offset + PAGE_SIZE >= resource.data.total} onClick={() => onOffset(offset + PAGE_SIZE)} className={buttonClass}>次の記録</button>
            </div></div>
        </>}
    </div>;
}

function Entries({ accountId, startDate, endDate, currency }: { accountId: number; startDate: string; endDate: string; currency: string }) {
    const [offset, setOffset] = useState(0);
    // Remounting each page prevents a previous page's rows appearing under a new page number.
    return <EntryPage key={offset} accountId={accountId} startDate={startDate} endDate={endDate} currency={currency} offset={offset} onOffset={setOffset} />;
}

function AccountDetail({ account, startDate, endDate, currency, grain, buckets }: {
    account: AccountFlowRow; startDate: string; endDate: string; currency: string; grain: AccountFlowGrain;
    buckets: Array<{ key: string; label: string; start_date?: string; end_date?: string }>;
}) {
    const [bucketKey, setBucketKey] = useState('');
    const bucket = buckets.find((row) => row.key === bucketKey);
    const entryStart = bucket?.start_date ?? startDate;
    const entryEnd = bucket?.end_date ?? endDate;
    return <section className="space-y-4">
        <MoneyLineChart rows={account.buckets.map((row) => ({ label: row.label, amount: row.normal_balance_delta }))} currency={currency} label="口座・科目の増減" axisLabel={GRAINS[grain]} />
        <Field label="記録の期間"><select value={bucketKey} onChange={(event) => setBucketKey(event.target.value)} className={inputClass}>
            <option value="">選択した期間すべて</option>
            {buckets.map((row) => <option key={row.key} value={row.key}>{row.label}（{row.start_date} 〜 {row.end_date}）</option>)}
        </select></Field>
        <h4 className="text-sm font-semibold">この動きの元になった記録</h4>
        <Entries key={`${entryStart}:${entryEnd}`} accountId={account.account_id} startDate={entryStart} endDate={entryEnd} currency={currency} />
    </section>;
}

function AccountFlows({ startDate, endDate, currency, grain }: { startDate: string; endDate: string; currency: string; grain: AccountFlowGrain }) {
    const load = useCallback(() => getAccountFlows({ startDate, endDate, grain }), [startDate, endDate, grain]);
    const resource = useResource(load);
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const selected = resource.data?.accounts.find((row) => row.account_id === selectedId);
    useReloadAction(resource.reload, Boolean(resource.loading));
    return <section className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <h2 className="text-lg font-semibold">資金移動</h2>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <>
            <DataTable columns={['口座・科目', '種別', '借方', '貸方', '増減', '仕訳数']}>
                {resource.data.accounts.length ? resource.data.accounts.map((row) => <tr key={row.account_id} onClick={() => setSelectedId(row.account_id)} className={`cursor-pointer hover:bg-[var(--studio-accent-soft)] ${selectedId === row.account_id ? 'bg-[var(--studio-accent-soft)]' : ''}`}>
                    <th scope="row" className="px-5 py-3 font-medium"><button type="button" aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); setSelectedId(row.account_id); }} className="rounded text-left text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{row.account_name}</button></th>
                    <td className="px-5 py-3">{ACCOUNT_TYPES[row.account_type]}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.total_debit, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.total_credit, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.normal_balance_delta, currency)}</td>
                    <td className="px-5 py-3 tabular-nums">{row.transaction_count}</td>
                </tr>) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">この期間の口座の動きはありません。</td></tr>}
            </DataTable>
            {selected && <Overlay title={selected.account_name} onClose={() => setSelectedId(null)}><AccountDetail key={selected.account_id} account={selected} startDate={startDate} endDate={endDate} currency={currency} grain={resource.data.grain} buckets={resource.data.buckets} /></Overlay>}
        </>}
    </section>;
}

function NetWorth({ months, currency }: { months: number; currency: string }) {
    const load = useCallback(() => getNetWorthHistory(months), [months]);
    const resource = useResource(load);
    const first = resource.data?.[0];
    const latest = resource.data?.at(-1);
    useReloadAction(resource.reload, Boolean(resource.loading));
    return <section className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <h2 className="text-lg font-semibold">純資産の推移</h2>
        <p className="text-sm text-[var(--studio-text-muted)]">今月は、登録されている記録までの値です。</p>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && (first && latest ? <>
            <dl className="flex flex-wrap gap-x-10 gap-y-4"><div><dt className="text-xs text-[var(--studio-text-muted)]">{latest.period} の純資産</dt><dd className="mt-2 text-2xl font-semibold tabular-nums">{formatCurrency(latest.net_worth, currency)}</dd></div><div><dt className="text-xs text-[var(--studio-text-muted)]">{first.period} からの増減</dt><dd className="mt-2 text-xl tabular-nums">{formatCurrency(latest.net_worth - first.net_worth, currency)}</dd></div></dl>
            <MoneyLineChart rows={resource.data.map((row) => ({ label: row.period, amount: row.net_worth }))} currency={currency} label="純資産" axisLabel="月末" />
        </> : <p className="text-sm text-[var(--studio-text-muted)]">純資産の履歴はありません。</p>)}
    </section>;
}

function TrendsForClient({ currency }: { currency: string }) {
    const [months, setMonths] = useState(12);
    const [grain, setGrain] = useState<AccountFlowGrain>('month');
    const [year, month] = currentMonth().split('-').map(Number);
    const first = new Date(year, month - months, 1);
    const startDate = `${first.getFullYear()}-${String(first.getMonth() + 1).padStart(2, '0')}-01`;
    const endDate = monthRange(currentMonth()).endDate;
    return <section className="space-y-8">
        <div className="flex flex-wrap items-end gap-4">
            <Field label="表示期間"><select value={months} onChange={(event) => setMonths(Number(event.target.value))} className={inputClass}>{[12, 36, 60].map((value) => <option key={value} value={value}>{value}か月</option>)}</select></Field>
            <Field label="口座の集計単位"><select value={grain} onChange={(event) => { const value = event.target.value; if (value === 'day' || value === 'week' || value === 'month' || value === 'quarter') setGrain(value); }} className={inputClass}>{Object.entries(GRAINS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        </div>
        <NetWorth key={months} months={months} currency={currency} />
        <AccountFlows key={`${months}:${grain}`} startDate={startDate} endDate={endDate} currency={currency} grain={grain} />
    </section>;
}

export default function Trends() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <TrendsForClient key={`${clientId}:${currency}`} currency={currency} />;
}
