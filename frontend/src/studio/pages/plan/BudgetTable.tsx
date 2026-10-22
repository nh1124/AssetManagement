import type { ReactNode } from 'react';
import { formatCurrency } from '../../../utils/currency';
import { Help } from '../db/Database';
import { KINDS, KIND_LABELS, TYPE_LABELS, type AccountRow, type EarmarkRow } from './budgetRows';
import { tr } from '../../i18n';

interface TableProps {
    accounts: AccountRow[];
    earmarks: EarmarkRow[];
    currency: string;
    /** Rows are narrowed by search or scope: empty groups are left out. */
    narrowed: boolean;
    highlight: number | null;
    disabled: boolean;
    onAccount: (row: AccountRow) => void;
    onEarmark: (earmark: EarmarkRow) => void;
    /** 取り置き is a tab of its own; the 計画と実績 tab leaves it out. */
    showEarmarks?: boolean;
}

const th = 'whitespace-nowrap px-4 py-3 font-medium';
const td = 'whitespace-nowrap px-4 py-2.5 tabular-nums';
const faint = 'text-[var(--studio-text-faint)]';
const muted = 'text-xs text-[var(--studio-text-muted)]';

function Chip({ children, warn = false }: { children: ReactNode; warn?: boolean }) {
    return <span className={`ml-2 whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-normal ${warn ? 'bg-[var(--studio-warning-soft,transparent)] text-[var(--studio-warning)] ring-1 ring-[var(--studio-warning)]' : 'bg-[var(--studio-bg)] text-[var(--studio-text-muted)]'}`}>{children}</span>;
}

function Scheduled({ row }: { row: AccountRow }) {
    const count = row.scheduled.length;
    return count ? <span className={muted}>{tr(`${count}件`, `${count}`)}</span> : <span className={faint}>—</span>;
}

function Marks({ row }: { row: AccountRow }) {
    return <>{row.goal && <Chip>{tr('ゴール', 'Goal')}</Chip>}{row.cells.some((cell) => cell.mismatch) && <Chip warn>{tr('種別を確認', 'Check the kind')}</Chip>}</>;
}

function NameButton({ row, disabled, onOpen }: { row: AccountRow; disabled: boolean; onOpen: () => void }) {
    return <button type="button" disabled={disabled} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); onOpen(); }}
        className="rounded text-left font-medium hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{row.name}</button>;
}

function rowClass(highlight: boolean, disabled: boolean) {
    return `${highlight ? 'bg-[var(--studio-accent-soft)]' : ''} ${disabled ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)]'}`;
}

const Frame = ({ children }: { children: ReactNode }) => <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">{children}</div>;

/** Where the month's budget of an earmark comes from: the reflection (goal or products), a row typed in, or its monthly amount. */
function origin(earmark: EarmarkRow): string {
    const kinds = new Set(earmark.lines.filter((line) => line.id != null).map((line) => line.source_kind));
    if (kinds.has('goal')) return tr('ゴールの反映', 'From a goal');
    if (kinds.has('product_reserve')) return tr('物品の反映', 'From items');
    if (kinds.size) return tr('手入力', 'Entered by hand');
    return tr('取り置きの月額', 'Earmark’s monthly amount');
}

export function EarmarkTable({ earmarks, currency, disabled, onEarmark }: Pick<TableProps, 'earmarks' | 'currency' | 'disabled' | 'onEarmark'>) {
    const money = (amount: number) => formatCurrency(amount, currency);
    return <section className="space-y-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">{tr('取り置き', 'Earmarks')}<Help label={tr('取り置き', 'Earmarks')} text={tr('口座ではありません。資金元の口座の残高から確保します。予算では、同じ口座への振替を超える分だけを配分として数えます（振替と重ねて数えません）。', 'Not accounts: money set aside from the funding accounts’ balances. In the budget, only what exceeds transfers to the same account counts as allocation (never counted twice with the transfer).')} /></h3>
        <Frame><table className="w-full text-left text-sm">
            <thead className={`border-b border-[var(--studio-border)] ${muted}`}><tr>{[tr('取り置き', 'Earmark'), tr('資金元', 'Funded from'), tr('月の予算', 'Monthly budget'), tr('出どころ', 'Source'), tr('確保額', 'Set aside')].map((label) => <th key={label} scope="col" className={th}>{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">
                {earmarks.map((earmark) => <tr key={earmark.key} onClick={() => { if (!disabled) onEarmark(earmark); }} className={rowClass(false, disabled)}>
                    <th scope="row" className="px-4 py-2.5"><button type="button" disabled={disabled} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); onEarmark(earmark); }} className="rounded text-left font-medium hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{earmark.name}</button>{earmark.goal && <Chip>{tr('ゴール', 'Goal')}</Chip>}</th>
                    <td className={`px-4 py-2.5 ${muted}`}>{earmark.sources.join(tr('・', ', ')) || tr('資金元の口座なし', 'No funding account')}</td>
                    <td className={td}>{money(earmark.budget)}</td>
                    <td className={`px-4 py-2.5 ${muted}`}>{origin(earmark)}</td>
                    <td className={td}>{money(earmark.held)}</td>
                </tr>)}
                {!earmarks.length && <tr><td colSpan={5} className={`px-4 py-3 ${muted}`}>{tr('条件に合う取り置きはありません。', 'No earmarks match.')}</td></tr>}
            </tbody>
        </table></Frame>
    </section>;
}

/** One row per account; name movements only when several have content. */
export default function BudgetTable({ accounts, earmarks, currency, narrowed, highlight, disabled, onAccount, onEarmark, showEarmarks = true }: TableProps) {
    const money = (amount: number) => formatCurrency(amount, currency);
    const groups = [...KINDS, null].map((kind) => ({ kind, rows: accounts.filter((row) => row.kind === kind) }))
        .filter((group) => group.rows.length || (!narrowed && group.kind));
    const stack = (row: AccountRow, actual = false) => {
        const cells = row.cells.filter((cell) => cell.set || cell.budget !== 0 || cell.actual !== 0);
        if (!cells.length) return actual ? money(0) : <span className={faint}>{tr('未設定', 'Not set')}</span>;
        return <div className="space-y-1">{cells.map((cell) => <div key={cell.type}>
            {cells.length > 1 && <span className={`mr-2 ${muted}`}>{TYPE_LABELS[cell.type]}</span>}
            {actual ? money(cell.actual) : cell.set ? money(cell.budget) : <span className={faint}>{tr('未設定', 'Not set')}</span>}
        </div>)}</div>;
    };
    return <div className="space-y-6">
        <Frame><table className="w-full text-left text-sm">
            <thead className={`border-b border-[var(--studio-border)] ${muted}`}><tr>{[tr('口座・科目', 'Account'), tr('予算', 'Budget'), tr('実績', 'Actual'), tr('取引予定', 'Scheduled')].map((label) => <th key={label} scope="col" className={th}>{label}</th>)}</tr></thead>
            {groups.map((group) => <tbody key={group.kind ?? 'none'} className="divide-y divide-[var(--studio-border)] border-b border-[var(--studio-border)] last:border-b-0">
                <tr className="bg-[var(--studio-bg)]"><th scope="rowgroup" colSpan={4} className="px-4 py-2 text-sm font-semibold">{group.kind ? KIND_LABELS[group.kind] : tr('口座未指定', 'No account')}<span className={`ml-2 font-normal ${muted}`}>{tr(`${group.rows.length}件`, `${group.rows.length}`)}</span></th></tr>
                {group.rows.map((row) => <tr key={row.key} onClick={() => { if (!disabled) onAccount(row); }} className={`align-top ${rowClass(row.accountId === highlight, disabled)}`}>
                    <th scope="row" className="px-4 py-2.5"><NameButton row={row} disabled={disabled} onOpen={() => onAccount(row)} /><Marks row={row} /></th>
                    <td className={td}>{stack(row)}</td>
                    <td className={td}>{stack(row, true)}</td>
                    <td className={td}><Scheduled row={row} /></td>
                </tr>)}
                {!group.rows.length && <tr><td colSpan={4} className={`px-4 py-3 ${muted}`}>{tr('この種類の口座・科目はありません。', 'No accounts of this kind.')}</td></tr>}
            </tbody>)}
            {!groups.length && <tbody><tr><td colSpan={4} className="px-4 py-4 text-[var(--studio-text-muted)]">{tr('条件に合う口座・科目はありません。', 'No accounts match.')}</td></tr></tbody>}
        </table></Frame>
        {showEarmarks && (earmarks.length > 0 || !narrowed) && <EarmarkTable earmarks={earmarks} currency={currency} disabled={disabled} onEarmark={onEarmark} />}
    </div>;
}

