import { Link } from 'react-router-dom';
import type { ScheduledTransaction } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { formatDate } from '../../datetime';
import { DataTable } from '../db/Database';
import { TYPE_LABELS } from './budgetRows';
import { tr } from '../../i18n';

/** 自動取引: the month's automatic transactions and depreciation, posted or still to come. */
export default function PlanAutomatic({ items, currency, accountName }: {
    items: ScheduledTransaction[]; currency: string; accountName: (id: number | null) => string;
}) {
    const sorted = [...items].sort((a, b) => a.date.localeCompare(b.date) || a.name.localeCompare(b.name, 'ja'));
    return <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-[var(--studio-text-muted)]">{tr('この月に記録される自動取引と減価です。変えるときは自動取引の設定で行います。', 'Automatic transactions and depreciation recorded this month. Change them in the automatic transaction settings.')}</p>
            <Link to="/db/auto-transactions" className="text-sm text-[var(--studio-accent)] underline">{tr('自動取引の設定', 'Automatic transaction settings')}</Link>
        </div>
        <DataTable columns={[tr('日付', 'Date'), tr('名前', 'Name'), tr('区分', 'Kind'), tr('口座・科目', 'Account'), tr('金額', 'Amount'), tr('状態', 'Status'), tr('計画', 'Plan')]}>
            {sorted.map((item, index) => <tr key={`${item.kind}:${item.entry_id ?? item.product_id}:${item.date}:${index}`}>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatDate(item.date)}</td>
                <th scope="row" className="px-5 py-3 font-medium">{item.name}</th>
                <td className="whitespace-nowrap px-5 py-3">{item.kind === 'depreciation' ? tr('減価', 'Depreciation') : item.line_type ? TYPE_LABELS[item.line_type] : '—'}</td>
                <td className="px-5 py-3">{accountName(item.account_id)}{item.counter_account_id != null && <span className="text-xs text-[var(--studio-text-muted)]">{tr(`（${accountName(item.counter_account_id)}）`, ` (${accountName(item.counter_account_id)})`)}</span>}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(item.amount, currency)}</td>
                <td className="whitespace-nowrap px-5 py-3">{item.records_transactions === false ? tr('予算のみ', 'Budget only') : item.posted ? tr('記録済み', 'Recorded') : tr('予定', 'Scheduled')}</td>
                <td className="whitespace-nowrap px-5 py-3 text-[var(--studio-text-muted)]">{item.in_budget ? tr('数える', 'Counted') : tr('数えない', 'Not counted')}</td>
            </tr>)}
            {!sorted.length && <tr><td colSpan={7} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('この月の自動取引はありません。', 'No automatic transactions this month.')}</td></tr>}
        </DataTable>
    </section>;
}
