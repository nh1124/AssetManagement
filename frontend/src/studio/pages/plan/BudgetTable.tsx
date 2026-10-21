import type { ReactNode } from 'react';
import { formatCurrency } from '../../../utils/currency';
import { Help } from '../db/Database';
import { KINDS, KIND_LABELS, TYPE_LABELS, type AccountRow, type EarmarkRow } from './budgetRows';

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
    return count ? <span className={muted}>{count}件</span> : <span className={faint}>—</span>;
}

function Marks({ row }: { row: AccountRow }) {
    return <>{row.goal && <Chip>ゴール</Chip>}{row.cells.some((cell) => cell.mismatch) && <Chip warn>種別を確認</Chip>}</>;
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
    if (kinds.has('goal')) return 'ゴールの反映';
    if (kinds.has('product_reserve')) return '物品の反映';
    if (kinds.size) return '手入力';
    return '取り置きの月額';
}

export function EarmarkTable({ earmarks, currency, disabled, onEarmark }: Pick<TableProps, 'earmarks' | 'currency' | 'disabled' | 'onEarmark'>) {
    const money = (amount: number) => formatCurrency(amount, currency);
    return <section className="space-y-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">取り置き<Help label="取り置き" text="口座ではありません。資金元の口座の残高から確保します。予算では、同じ口座への振替を超える分だけを配分として数えます（振替と重ねて数えません）。" /></h3>
        <Frame><table className="w-full text-left text-sm">
            <thead className={`border-b border-[var(--studio-border)] ${muted}`}><tr>{['取り置き', '資金元', '月の予算', '出どころ', '確保額'].map((label) => <th key={label} scope="col" className={th}>{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">
                {earmarks.map((earmark) => <tr key={earmark.key} onClick={() => { if (!disabled) onEarmark(earmark); }} className={rowClass(false, disabled)}>
                    <th scope="row" className="px-4 py-2.5"><button type="button" disabled={disabled} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); onEarmark(earmark); }} className="rounded text-left font-medium hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{earmark.name}</button>{earmark.goal && <Chip>ゴール</Chip>}</th>
                    <td className={`px-4 py-2.5 ${muted}`}>{earmark.sources.join('・') || '資金元の口座なし'}</td>
                    <td className={td}>{money(earmark.budget)}</td>
                    <td className={`px-4 py-2.5 ${muted}`}>{origin(earmark)}</td>
                    <td className={td}>{money(earmark.held)}</td>
                </tr>)}
                {!earmarks.length && <tr><td colSpan={5} className={`px-4 py-3 ${muted}`}>条件に合う取り置きはありません。</td></tr>}
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
        if (!cells.length) return actual ? money(0) : <span className={faint}>未設定</span>;
        return <div className="space-y-1">{cells.map((cell) => <div key={cell.type}>
            {cells.length > 1 && <span className={`mr-2 ${muted}`}>{TYPE_LABELS[cell.type]}</span>}
            {actual ? money(cell.actual) : cell.set ? money(cell.budget) : <span className={faint}>未設定</span>}
        </div>)}</div>;
    };
    return <div className="space-y-6">
        <Frame><table className="w-full text-left text-sm">
            <thead className={`border-b border-[var(--studio-border)] ${muted}`}><tr>{['口座・科目', '予算', '実績', '取引予定'].map((label) => <th key={label} scope="col" className={th}>{label}</th>)}</tr></thead>
            {groups.map((group) => <tbody key={group.kind ?? 'none'} className="divide-y divide-[var(--studio-border)] border-b border-[var(--studio-border)] last:border-b-0">
                <tr className="bg-[var(--studio-bg)]"><th scope="rowgroup" colSpan={4} className="px-4 py-2 text-sm font-semibold">{group.kind ? KIND_LABELS[group.kind] : '口座未指定'}<span className={`ml-2 font-normal ${muted}`}>{group.rows.length}件</span></th></tr>
                {group.rows.map((row) => <tr key={row.key} onClick={() => { if (!disabled) onAccount(row); }} className={`align-top ${rowClass(row.accountId === highlight, disabled)}`}>
                    <th scope="row" className="px-4 py-2.5"><NameButton row={row} disabled={disabled} onOpen={() => onAccount(row)} /><Marks row={row} /></th>
                    <td className={td}>{stack(row)}</td>
                    <td className={td}>{stack(row, true)}</td>
                    <td className={td}><Scheduled row={row} /></td>
                </tr>)}
                {!group.rows.length && <tr><td colSpan={4} className={`px-4 py-3 ${muted}`}>この種類の口座・科目はありません。</td></tr>}
            </tbody>)}
            {!groups.length && <tbody><tr><td colSpan={4} className="px-4 py-4 text-[var(--studio-text-muted)]">条件に合う口座・科目はありません。</td></tr></tbody>}
        </table></Frame>
        {showEarmarks && (earmarks.length > 0 || !narrowed) && <EarmarkTable earmarks={earmarks} currency={currency} disabled={disabled} onEarmark={onEarmark} />}
    </div>;
}

