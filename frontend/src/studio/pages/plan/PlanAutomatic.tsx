import { Link } from 'react-router-dom';
import type { ScheduledTransaction } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { formatDate } from '../../datetime';
import { DataTable } from '../db/Database';
import { TYPE_LABELS } from './budgetRows';

/** 自動取引: the month's automatic transactions and depreciation, posted or still to come. */
export default function PlanAutomatic({ items, currency, accountName }: {
    items: ScheduledTransaction[]; currency: string; accountName: (id: number | null) => string;
}) {
    const sorted = [...items].sort((a, b) => a.date.localeCompare(b.date) || a.name.localeCompare(b.name, 'ja'));
    return <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-[var(--studio-text-muted)]">この月に記録される自動取引と減価です。変えるときは自動取引の設定で行います。</p>
            <Link to="/db/auto-transactions" className="text-sm text-[var(--studio-accent)] underline">自動取引の設定</Link>
        </div>
        <DataTable columns={['日付', '名前', '区分', '口座・科目', '金額', '状態', '計画']}>
            {sorted.map((item, index) => <tr key={`${item.kind}:${item.entry_id ?? item.product_id}:${item.date}:${index}`}>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatDate(item.date)}</td>
                <th scope="row" className="px-5 py-3 font-medium">{item.name}</th>
                <td className="whitespace-nowrap px-5 py-3">{item.kind === 'depreciation' ? '減価' : item.line_type ? TYPE_LABELS[item.line_type] : '—'}</td>
                <td className="px-5 py-3">{accountName(item.account_id)}{item.counter_account_id != null && <span className="text-xs text-[var(--studio-text-muted)]">（{accountName(item.counter_account_id)}）</span>}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(item.amount, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3">{item.records_transactions === false ? '予算のみ' : item.posted ? '記録済み' : '予定'}</td>
                <td className="whitespace-nowrap px-5 py-3 text-[var(--studio-text-muted)]">{item.in_budget ? '数える' : '数えない'}</td>
            </tr>)}
            {!sorted.length && <tr><td colSpan={7} className="px-5 py-4 text-[var(--studio-text-muted)]">この月の自動取引はありません。</td></tr>}
        </DataTable>
    </section>;
}
