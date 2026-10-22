import Overlay from '../../components/Overlay';
import { useCallback, useState } from 'react';
import { getAccountFlowTransactions } from '../../../api';
import type { AccountFlowAnalysis, AccountFlowGrain, AccountFlowRow } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { ACCOUNT_TYPES, buttonClass, inputClass } from '../db/forms';
import { MoneyLineChart } from './Charts';
import { labels, tr } from '../../i18n';

const GRAINS = labels<AccountFlowGrain>({ day: ['日別', 'By day'], week: ['週別', 'By week'], month: ['月別', 'By month'], quarter: ['四半期別', 'By quarter'] });
const PAGE_SIZE = 50;

function EntryPage({ accountId, startDate, endDate, currency, offset, onOffset }: {
    accountId: number; startDate: string; endDate: string; currency: string; offset: number; onOffset: (offset: number) => void;
}) {
    const load = useCallback(() => getAccountFlowTransactions({ accountId, startDate, endDate, limit: PAGE_SIZE, offset }), [accountId, startDate, endDate, offset]);
    const resource = useResource(load);
    return <div className="space-y-3">
        <div className="flex items-center justify-between gap-3"><p className="text-xs text-[var(--studio-text-muted)]">{tr(`${startDate} 〜 ${endDate}`, `${startDate} to ${endDate}`)}</p></div>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <>
            <DataTable columns={[tr('日付・記録', 'Date / record'), tr('内容・相手先', 'Description / counterpart'), tr(`借方（${currency}）`, `Debit (${currency})`), tr(`貸方（${currency}）`, `Credit (${currency})`), tr('元の通貨の借方 / 貸方', 'Debit / credit in the original currency')]}>
                {resource.data.items.length ? resource.data.items.map((entry) => <tr key={entry.entry_id}>
                    <td className="whitespace-nowrap px-5 py-3"><time dateTime={entry.date}>{entry.date}</time><span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{tr(`取引 #${entry.transaction_id} ／ 仕訳 #${entry.entry_id}`, `Transaction #${entry.transaction_id} / entry #${entry.entry_id}`)}</span></td>
                    <td className="px-5 py-3">{entry.description || tr('内容未設定', 'Untitled')}<span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{entry.counterpart_accounts.map((row) => row.account_name || tr(`口座 #${row.account_id}`, `Account #${row.account_id}`)).join(tr('、', ', ')) || tr('相手先なし', 'No counterpart')}</span></td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(entry.debit, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(entry.credit, currency)}</td>
                    {/* Raw sides belong to the entry's currency; they must never be summed with converted sides. */}
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(entry.raw_debit, entry.currency)} / {formatCurrency(entry.raw_credit, entry.currency)}<span className="mt-1 block text-xs text-[var(--studio-text-muted)]">{entry.currency}</span></td>
                </tr>) : <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('この期間の記録はありません。', 'No records in this period.')}</td></tr>}
            </DataTable>
            <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-[var(--studio-text-muted)]"><p>{resource.data.total ? tr(`${offset + 1} 〜 ${offset + resource.data.items.length} / ${resource.data.total} 件`, `${offset + 1}–${offset + resource.data.items.length} of ${resource.data.total}`) : tr('0 件', 'None')}</p><div className="flex gap-2">
                <button type="button" disabled={resource.loading || offset === 0} onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))} className={buttonClass}>{tr('前の記録', 'Previous')}</button>
                <button type="button" disabled={resource.loading || offset + PAGE_SIZE >= resource.data.total} onClick={() => onOffset(offset + PAGE_SIZE)} className={buttonClass}>{tr('次の記録', 'Next')}</button>
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
        <MoneyLineChart rows={account.buckets.map((row) => ({ label: row.label, amount: row.normal_balance_delta }))} currency={currency} label={tr('口座・科目の増減', 'Account change')} axisLabel={GRAINS[grain]} />
        <Field label={tr('記録の期間', 'Records for')}><select value={bucketKey} onChange={(event) => setBucketKey(event.target.value)} className={inputClass}>
            <option value="">{tr('選択した期間すべて', 'The whole period')}</option>
            {buckets.map((row) => <option key={row.key} value={row.key}>{tr(`${row.label}（${row.start_date} 〜 ${row.end_date}）`, `${row.label} (${row.start_date} to ${row.end_date})`)}</option>)}
        </select></Field>
        <h4 className="text-sm font-semibold">{tr('この動きの元になった記録', 'Records behind this movement')}</h4>
        <Entries key={`${entryStart}:${entryEnd}`} accountId={account.account_id} startDate={entryStart} endDate={entryEnd} currency={currency} />
    </section>;
}

export function AccountFlowsReading({ resource, startDate, endDate, currency, heading, className, readOnly = false }: {
    resource: { data: AccountFlowAnalysis | null; loading: boolean; error: string };
    startDate: string; endDate: string; currency: string; heading: string; className: string; readOnly?: boolean;
}) {
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const selected = resource.data?.accounts.find((row) => row.account_id === selectedId);
    return <section className={className}>
        <h2 className="text-lg font-semibold">{heading}</h2>
        <Feedback loading={resource.loading} error={resource.error} />
        {resource.data && <>
            <DataTable columns={[tr('口座・科目', 'Account'), tr('種別', 'Type'), tr('借方', 'Debit'), tr('貸方', 'Credit'), tr('増減', 'Change'), tr('仕訳数', 'Entries')]}>
                {resource.data.accounts.length ? resource.data.accounts.map((row) => <tr key={row.account_id} onClick={readOnly ? undefined : () => setSelectedId(row.account_id)} className={`${readOnly ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)]'} ${selectedId === row.account_id ? 'bg-[var(--studio-accent-soft)]' : ''}`}>
                    <th scope="row" className="px-5 py-3 font-medium">{readOnly ? row.account_name : <button type="button" aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); setSelectedId(row.account_id); }} className="rounded text-left text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]">{row.account_name}</button>}</th>
                    <td className="px-5 py-3">{ACCOUNT_TYPES[row.account_type]}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.total_debit, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.total_credit, currency)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.normal_balance_delta, currency)}</td>
                    <td className="px-5 py-3 tabular-nums">{row.transaction_count}</td>
                </tr>) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('この期間の口座の動きはありません。', 'No account movements in this period.')}</td></tr>}
            </DataTable>
            {selected && <Overlay title={selected.account_name} onClose={() => setSelectedId(null)}><AccountDetail key={selected.account_id} account={selected} startDate={startDate} endDate={endDate} currency={currency} grain={resource.data.grain} buckets={resource.data.buckets} /></Overlay>}
        </>}
    </section>;
}
