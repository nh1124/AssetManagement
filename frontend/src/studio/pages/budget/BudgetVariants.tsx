import { useState, type ReactNode } from 'react';
import Overlay from '../../components/Overlay';
import type { MonthlyPlanLineType } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { KINDS, KIND_LABELS, TYPES, isTransaction, type AccountRow, type Cell, type EarmarkRow } from './budgetRows';

export interface ViewProps {
    accounts: AccountRow[];
    earmarks: EarmarkRow[];
    currency: string;
    /** Rows are narrowed by search or scope: empty groups are left out. */
    narrowed: boolean;
    shortfall: number;
    need: Map<string, number>;
    highlight: number | null;
    disabled: boolean;
    onAccount: (row: AccountRow) => void;
    onEarmark: (earmark: EarmarkRow) => void;
}

const th = 'whitespace-nowrap px-4 py-3 font-medium';
const td = 'whitespace-nowrap px-4 py-2.5 tabular-nums';
const faint = 'text-[var(--studio-text-faint)]';
const muted = 'text-xs text-[var(--studio-text-muted)]';

function Chip({ children, warn = false }: { children: ReactNode; warn?: boolean }) {
    return <span className={`ml-2 whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-normal ${warn ? 'bg-[var(--studio-warning-soft,transparent)] text-[var(--studio-warning)] ring-1 ring-[var(--studio-warning)]' : 'bg-[var(--studio-bg)] text-[var(--studio-text-muted)]'}`}>{children}</span>;
}

function BudgetAmount({ cell, currency }: { cell: Cell; currency: string }) {
    if (cell.set) return <>{formatCurrency(cell.budget, currency)}</>;
    return <><span className={faint}>未設定</span>{cell.defined > 0 && <span className={`ml-2 ${muted}`}>定義 {formatCurrency(cell.defined, currency)}</span>}</>;
}

function Scheduled({ row }: { row: AccountRow }) {
    const count = row.scheduled.filter(isTransaction).length;
    return count ? <span className={muted}>{count}件</span> : <span className={faint}>—</span>;
}

function Marks({ cells }: { cells: Cell[] }) {
    return <>{cells.some((cell) => cell.goal) && <Chip>ゴール</Chip>}{cells.some((cell) => cell.mismatch) && <Chip warn>種別を確認</Chip>}</>;
}

function NameButton({ row, disabled, onOpen }: { row: AccountRow; disabled: boolean; onOpen: () => void }) {
    return <button type="button" disabled={disabled} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); onOpen(); }}
        className="rounded text-left font-medium hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{row.name}</button>;
}

function rowClass(highlight: boolean, disabled: boolean) {
    return `${highlight ? 'bg-[var(--studio-accent-soft)]' : ''} ${disabled ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)]'}`;
}

function NeedMark({ earmark, need, currency }: { earmark: EarmarkRow; need: Map<string, number>; currency: string }) {
    const amount = need.get(earmark.name);
    if (amount == null || amount <= earmark.budget) return null;
    return <Chip warn>必要 {formatCurrency(amount, currency)}</Chip>;
}

function ShortMark({ shortfall, currency }: { shortfall: number; currency: string }) {
    return shortfall > 0 ? <Chip warn>積立 {formatCurrency(shortfall, currency)} 不足</Chip> : null;
}

const Frame = ({ children }: { children: ReactNode }) => <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">{children}</div>;
const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);

/** A: the six movements as headings, the accounts in each, earmarks as their own part of 配分. */
export function TypeBlocks({ accounts, earmarks, currency, narrowed, shortfall, need, highlight, disabled, onAccount, onEarmark }: ViewProps) {
    const money = (amount: number) => formatCurrency(amount, currency);
    const blocks = TYPES.map((block) => ({
        ...block,
        rows: accounts.flatMap((row) => row.cells.filter((cell) => cell.type === block.type).map((cell) => ({ row, cell }))),
        earmarks: block.type === 'allocation' ? earmarks : [],
    })).filter((block) => !narrowed || block.rows.length || block.earmarks.length);
    return <Frame><table className="w-full text-left text-sm">
        <thead className={`border-b border-[var(--studio-border)] ${muted}`}><tr>{['口座・科目', '予算', '実績', '差額', '取引予定'].map((label) => <th key={label} scope="col" className={th}>{label}</th>)}</tr></thead>
        {blocks.map((block) => <tbody key={block.type} className="divide-y divide-[var(--studio-border)] border-b border-[var(--studio-border)] last:border-b-0">
            <tr className="bg-[var(--studio-bg)]">
                <th scope="rowgroup" className="px-4 py-2 text-sm font-semibold">{block.label}<span className={`ml-2 font-normal ${muted}`}>{KIND_LABELS[block.kind]}の{block.kind === 'income' || block.kind === 'expense' ? '科目' : '口座'}</span>{block.type === 'allocation' && <ShortMark shortfall={shortfall} currency={currency} />}</th>
                <td className={`${td} ${muted}`}>計 {money(sum([...block.rows.map(({ cell }) => cell.budget), ...block.earmarks.map((earmark) => earmark.budget)]))}</td>
                <td colSpan={3} />
            </tr>
            {block.rows.map(({ row, cell }) => <tr key={row.key} onClick={() => { if (!disabled) onAccount(row); }} className={rowClass(row.accountId === highlight, disabled)}>
                <th scope="row" className="px-4 py-2.5"><NameButton row={row} disabled={disabled} onOpen={() => onAccount(row)} /><Marks cells={[cell]} /></th>
                <td className={td}><BudgetAmount cell={cell} currency={currency} /></td>
                <td className={td}>{money(cell.actual)}</td>
                <td className={td}>{cell.set ? money(cell.budget - cell.actual) : <span className={faint}>—</span>}</td>
                <td className={td}><Scheduled row={row} /></td>
            </tr>)}
            {!block.rows.length && !block.earmarks.length && <tr><td colSpan={5} className={`px-4 py-3 ${muted}`}>この種別の口座・科目はありません。</td></tr>}
            {block.earmarks.length > 0 && <>
                <tr><th scope="rowgroup" colSpan={5} className={`px-4 pb-1 pt-3 font-medium ${muted}`}>取り置き（口座ではありません。資金元の口座の残高から確保します）</th></tr>
                {block.earmarks.map((earmark) => <tr key={earmark.key} onClick={() => { if (!disabled) onEarmark(earmark); }} className={rowClass(false, disabled)}>
                    <th scope="row" className="px-4 py-2.5 pl-8"><button type="button" disabled={disabled} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); onEarmark(earmark); }} className="rounded text-left font-medium hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{earmark.name}</button>
                        <NeedMark earmark={earmark} need={need} currency={currency} />
                        {earmark.sources.length > 0 && <span className={`block font-normal ${muted}`}>{earmark.sources.join('・')} から</span>}</th>
                    <td className={td}>{money(earmark.budget)}</td>
                    <td className={td}><span className={muted}>確保 </span>{money(earmark.held)}</td>
                    <td className={td}><span className={faint}>—</span></td>
                    <td className={td}><span className={faint}>—</span></td>
                </tr>)}
            </>}
        </tbody>)}
        {!blocks.length && <tbody><tr><td colSpan={5} className="px-4 py-4 text-[var(--studio-text-muted)]">条件に合う項目はありません。</td></tr></tbody>}
    </table></Frame>;
}

function EarmarkTable({ earmarks, currency, shortfall, need, disabled, onEarmark }: Pick<ViewProps, 'earmarks' | 'currency' | 'shortfall' | 'need' | 'disabled' | 'onEarmark'>) {
    const money = (amount: number) => formatCurrency(amount, currency);
    return <section className="space-y-2">
        <h3 className="text-sm font-semibold">取り置き<span className={`ml-2 font-normal ${muted}`}>口座ではありません。資金元の口座の残高から確保し、予算では配分として数えます。</span><ShortMark shortfall={shortfall} currency={currency} /></h3>
        <Frame><table className="w-full text-left text-sm">
            <thead className={`border-b border-[var(--studio-border)] ${muted}`}><tr>{['取り置き', '資金元', '月の予算', '確保額'].map((label) => <th key={label} scope="col" className={th}>{label}</th>)}</tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">
                {earmarks.map((earmark) => <tr key={earmark.key} onClick={() => { if (!disabled) onEarmark(earmark); }} className={rowClass(false, disabled)}>
                    <th scope="row" className="px-4 py-2.5"><button type="button" disabled={disabled} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); onEarmark(earmark); }} className="rounded text-left font-medium hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{earmark.name}</button><NeedMark earmark={earmark} need={need} currency={currency} /></th>
                    <td className={`px-4 py-2.5 ${muted}`}>{earmark.sources.join('・') || '資金元の口座なし'}</td>
                    <td className={td}>{money(earmark.budget)}</td>
                    <td className={td}>{money(earmark.held)}</td>
                </tr>)}
                {!earmarks.length && <tr><td colSpan={4} className={`px-4 py-3 ${muted}`}>条件に合う取り置きはありません。</td></tr>}
            </tbody>
        </table></Frame>
    </section>;
}

/** B: each account once, under its kind; its movements stack inside the row; earmarks below. */
export function ByAccount({ accounts, earmarks, currency, narrowed, shortfall, need, highlight, disabled, onAccount, onEarmark }: ViewProps) {
    const money = (amount: number) => formatCurrency(amount, currency);
    const groups = [...KINDS, null].map((kind) => ({ kind, rows: accounts.filter((row) => row.kind === kind) }))
        .filter((group) => group.rows.length || (!narrowed && group.kind && group.kind !== 'item'));
    const stack = (row: AccountRow, render: (cell: Cell) => ReactNode) => <div className="space-y-1">{row.cells.map((cell) => <div key={cell.type}>{render(cell)}</div>)}</div>;
    return <div className="space-y-6">
        <Frame><table className="w-full text-left text-sm">
            <thead className={`border-b border-[var(--studio-border)] ${muted}`}><tr>{['口座・科目', '動き', '予算', '実績', '取引予定'].map((label) => <th key={label} scope="col" className={th}>{label}</th>)}</tr></thead>
            {groups.map((group) => <tbody key={group.kind ?? 'none'} className="divide-y divide-[var(--studio-border)] border-b border-[var(--studio-border)] last:border-b-0">
                <tr className="bg-[var(--studio-bg)]"><th scope="rowgroup" colSpan={5} className="px-4 py-2 text-sm font-semibold">{group.kind ? KIND_LABELS[group.kind] : '口座未指定'}<span className={`ml-2 font-normal ${muted}`}>{group.rows.length}件</span></th></tr>
                {group.rows.map((row) => <tr key={row.key} onClick={() => { if (!disabled) onAccount(row); }} className={`align-top ${rowClass(row.accountId === highlight, disabled)}`}>
                    <th scope="row" className="px-4 py-2.5"><NameButton row={row} disabled={disabled} onOpen={() => onAccount(row)} /><Marks cells={row.cells} /></th>
                    <td className="whitespace-nowrap px-4 py-2.5">{stack(row, (cell) => <span className={cell.mismatch ? 'text-[var(--studio-warning)]' : ''}>{TYPES.find((item) => item.type === cell.type)?.label}</span>)}</td>
                    <td className={td}>{stack(row, (cell) => <BudgetAmount cell={cell} currency={currency} />)}</td>
                    <td className={td}>{stack(row, (cell) => money(cell.actual))}</td>
                    <td className={td}><Scheduled row={row} /></td>
                </tr>)}
                {!group.rows.length && <tr><td colSpan={5} className={`px-4 py-3 ${muted}`}>この種類の口座・科目はありません。</td></tr>}
            </tbody>)}
            {!groups.length && <tbody><tr><td colSpan={5} className="px-4 py-4 text-[var(--studio-text-muted)]">条件に合う口座・科目はありません。</td></tr></tbody>}
        </table></Frame>
        {(earmarks.length > 0 || !narrowed) && <EarmarkTable earmarks={earmarks} currency={currency} shortfall={shortfall} need={need} disabled={disabled} onEarmark={onEarmark} />}
    </div>;
}

/** C: each account once, the six movements as columns; earmarks fold into one row under 配分. */
export function Matrix({ accounts, earmarks, currency, narrowed, shortfall, need, highlight, disabled, onAccount, onEarmark }: ViewProps) {
    const money = (amount: number) => formatCurrency(amount, currency);
    const [listing, setListing] = useState(false);
    const cellOf = (row: AccountRow, type: MonthlyPlanLineType) => row.cells.find((cell) => cell.type === type);
    const rows = [...accounts].sort((a, b) => KINDS.indexOf(a.kind ?? 'item') - KINDS.indexOf(b.kind ?? 'item'));
    const earmarkBudget = sum(earmarks.map((earmark) => earmark.budget));
    const showEarmarks = earmarks.length > 0 || !narrowed;
    return <>
        <Frame><table className="w-full text-left text-sm">
            <thead className={`border-b border-[var(--studio-border)] ${muted}`}><tr>
                <th scope="col" className={th}>口座・科目</th>
                {TYPES.map((type) => <th key={type.type} scope="col" className={`${th} text-right`}>{type.label}<span className="block text-[10px] font-normal">{KIND_LABELS[type.kind]}</span></th>)}
                <th scope="col" className={th}>取引予定</th>
            </tr></thead>
            <tbody className="divide-y divide-[var(--studio-border)]">
                {rows.map((row) => <tr key={row.key} onClick={() => { if (!disabled) onAccount(row); }} className={rowClass(row.accountId === highlight, disabled)}>
                    <th scope="row" className="px-4 py-2.5"><NameButton row={row} disabled={disabled} onOpen={() => onAccount(row)} />{row.kind && <span className={`ml-2 font-normal ${muted}`}>{KIND_LABELS[row.kind]}</span>}<Marks cells={row.cells} /></th>
                    {TYPES.map((type) => {
                        const cell = cellOf(row, type.type);
                        return <td key={type.type} className={`${td} text-right ${cell?.mismatch ? 'text-[var(--studio-warning)]' : ''}`}>{cell ? (cell.set ? money(cell.budget) : <span className={faint}>未設定</span>) : <span className={faint}>·</span>}</td>;
                    })}
                    <td className={td}><Scheduled row={row} /></td>
                </tr>)}
                {showEarmarks && <tr onClick={() => { if (!disabled) setListing(true); }} className={rowClass(false, disabled)}>
                    <th scope="row" className="px-4 py-2.5"><button type="button" disabled={disabled} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); setListing(true); }} className="rounded text-left font-medium hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">取り置き {earmarks.length}件</button><span className={`ml-2 font-normal ${muted}`}>口座ではありません</span><ShortMark shortfall={shortfall} currency={currency} /></th>
                    {TYPES.map((type) => <td key={type.type} className={`${td} text-right`}>{type.type === 'allocation' ? money(earmarkBudget) : <span className={faint}>·</span>}</td>)}
                    <td className={td}><span className={faint}>—</span></td>
                </tr>}
                {!rows.length && !showEarmarks && <tr><td colSpan={8} className="px-4 py-4 text-[var(--studio-text-muted)]">条件に合う口座・科目はありません。</td></tr>}
            </tbody>
            <tfoot className="border-t border-[var(--studio-border)] bg-[var(--studio-bg)] text-xs"><tr>
                <th scope="row" className="px-4 py-2 font-medium">計</th>
                {TYPES.map((type) => <td key={type.type} className={`${td} text-right`}>{money(sum([...rows.map((row) => cellOf(row, type.type)?.budget ?? 0), type.type === 'allocation' ? earmarkBudget : 0]))}</td>)}
                <td />
            </tr></tfoot>
        </table></Frame>
        {listing && <Overlay title="取り置き" onClose={() => setListing(false)}>
            <p className={`mb-3 ${muted}`}>取り置きは口座ではありません。資金元の口座の残高から確保し、予算では配分として数えます。開くと月の予算を編集できます。</p>
            <EarmarkTable earmarks={earmarks} currency={currency} shortfall={shortfall} need={need} disabled={disabled} onEarmark={(earmark) => { setListing(false); onEarmark(earmark); }} />
        </Overlay>}
    </>;
}
