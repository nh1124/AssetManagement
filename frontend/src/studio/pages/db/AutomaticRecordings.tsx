import { Link } from 'react-router-dom';
import { processRecurringTransaction } from '../../../api';
import type { AutomaticDepreciationRecording, AutomaticRecordings as Recordings, AutomaticRecurringRecording, RegistryEntry } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useConfirm } from '../../components/useConfirm';
import { toggleAutoDepreciation } from './autoDepreciation';
import { ActiveSwitch, DataTable } from './Database';
import { buttonClass, useMutation } from './forms';

type Mutation = ReturnType<typeof useMutation>;

const METHODS: Record<AutomaticDepreciationRecording['method'], string> = { none: 'なし', straight_line: '定額法', declining_balance: '定率法' };

function schedule(row: AutomaticRecurringRecording) {
    return row.frequency === 'Yearly' ? `毎年 ${row.month_of_year ?? 1}月${row.day_of_month}日` : `毎月 ${row.day_of_month}日`;
}

/** Everything that records on its own (U4): set here, run daily and at sign-in. */
export default function AutomaticRecordings({ data, entries, currency, disabled, mutation, onEdit, onChanged }: {
    data: Recordings; entries: RegistryEntry[]; currency: string; disabled: boolean;
    mutation: Mutation; onEdit: (entry: RegistryEntry) => void; onChanged: () => void;
}) {
    const confirm = useConfirm();
    const byId = new Map(entries.map((entry) => [entry.id, entry]));
    const post = async (row: AutomaticRecurringRecording) => {
        if (disabled || row.recurring_transaction_id == null || !row.next_due_date) return;
        if (!(await confirm(`「${row.name}」の${row.next_due_date}分として${formatCurrency(row.amount, row.currency || currency)}を記帳しますか？`, '記帳する'))) return;
        void mutation.run(() => processRecurringTransaction(row.recurring_transaction_id as number), `「${row.name}」を記帳しました。`, onChanged);
    };
    return <div className="space-y-6">
        <p className="text-xs text-[var(--studio-text-muted)]">自動で取引を記帳する設定の一覧です。毎日と、サインインしたときに期日の来た分を記帳します。
            取り置きの規則（取引に連動して確保する仕組み）は対象外で、<Link to="/db/earmarks" className="text-[var(--studio-accent)] hover:underline">取り置き</Link>で設定します。</p>

        <section className="space-y-2">
            <h2 className="text-sm font-medium">定義からの定期記帳</h2>
            <DataTable columns={['名称', '周期・次回', '金額', '口座', '記帳のしかた', '操作']}>
                {data.recurring.length ? data.recurring.map((row) => {
                    const entry = byId.get(row.entry_id);
                    return <tr key={row.entry_id}>
                        <th scope="row" className="px-5 py-3 font-medium">{row.name}{!row.is_active && <span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">定義は無効</span>}</th>
                        <td className="whitespace-nowrap px-5 py-3">{schedule(row)}<span className="mt-1 block text-xs text-[var(--studio-text-muted)]">次回 {row.next_due_date ?? '—'}{row.is_due && !row.auto_post && '（期日到来）'}</span></td>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.amount, row.currency || currency)}</td>
                        <td className="px-5 py-3">{row.source_account_name ?? '—'} → {row.destination_account_name ?? '—'}</td>
                        <td className="whitespace-nowrap px-5 py-3">{row.auto_post ? '期日に自動で記帳' : '記帳待ち（手動）'}</td>
                        <td className="whitespace-nowrap px-5 py-3"><div className="flex gap-2">
                            <button type="button" disabled={disabled || !entry} onClick={() => entry && onEdit(entry)} aria-label={`${row.name}を編集`} className={buttonClass}>編集</button>
                            {!row.auto_post && row.is_due && <button type="button" disabled={disabled} onClick={() => void post(row)} className={buttonClass}>記帳する</button>}
                        </div></td>
                    </tr>;
                }) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">自動記帳する定義はありません。定義の編集で「定義から自動記帳する」を選ぶとここに出ます。</td></tr>}
            </DataTable>
        </section>

        <section className="space-y-2">
            <h2 className="text-sm font-medium">固定資産の減価記帳</h2>
            <p className="text-xs text-[var(--studio-text-muted)]">減価の方法・勘定科目は<Link to="/db/fixed-assets" className="text-[var(--studio-accent)] hover:underline">固定資産</Link>で設定します。ここでは自動で記帳するかを切り替えます（期の末日付で記帳）。</p>
            <DataTable columns={['物品', '方法', '次回の記帳', '未記帳', '帳簿価額', '自動で記帳']}>
                {data.depreciation.length ? data.depreciation.map((row) => <tr key={row.product_id}>
                    <th scope="row" className="px-5 py-3 font-medium">{row.name}{!row.is_active && <span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">定義は無効（記帳しません）</span>}</th>
                    <td className="whitespace-nowrap px-5 py-3">{METHODS[row.method]}・{row.interval === 'yearly' ? '毎年' : '毎月'}</td>
                    <td className="whitespace-nowrap px-5 py-3">{row.blocked_reason
                        ? <span className="text-xs text-[var(--studio-text-muted)]">{row.blocked_reason}</span>
                        : row.next_period ? <>{row.next_period}<span className="ml-2 tabular-nums">{formatCurrency(row.next_amount, row.currency)}</span></> : '—'}</td>
                    <td className="whitespace-nowrap px-5 py-3">{row.pending_periods ? `${row.pending_periods}期` : '—'}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.book_value, row.currency)}</td>
                    <td className="px-5 py-3"><ActiveSwitch name={`${row.name}の減価の自動記帳`} active={row.auto_depreciation}
                        disabled={disabled || (!row.auto_depreciation && Boolean(row.blocked_reason))}
                        onToggle={() => void toggleAutoDepreciation(confirm, mutation, row, onChanged)} /></td>
                </tr>) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">減価の方法を設定した固定資産はありません。</td></tr>}
            </DataTable>
        </section>
    </div>;
}
