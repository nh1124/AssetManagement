import type { SavingsCheck } from '../../../api/goalBudget';
import type { MonthlyPlanLine, MonthlyPlanLineType, ScheduledTransaction } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import type { DatabaseAccount } from '../db/forms';

// budget_plan_service returns plan_lines and plan_id, not the legacy budget model.
export interface BudgetSummary {
    period: string;
    plan_id: number | null;
    feasibility_status: 'ok' | 'warning' | 'shortfall';
    plan_lines: MonthlyPlanLine[];
    /** Active accounts no plan line covers: unsaved zero rows with their actuals. */
    unset_lines: MonthlyPlanLine[];
}

export type AccountKind = DatabaseAccount['account_type'];

/** The six movements and the kind of account each one normally lands on. */
export const TYPES: Array<{ type: MonthlyPlanLineType; label: string; kind: AccountKind }> = [
    { type: 'income', label: '収入', kind: 'income' }, { type: 'expense', label: '支出', kind: 'expense' },
    { type: 'allocation', label: '配分', kind: 'asset' }, { type: 'debt_payment', label: '返済', kind: 'liability' },
    { type: 'borrowing', label: '借入', kind: 'liability' }, { type: 'drawdown', label: '取り崩し', kind: 'asset' },
];
export const TYPE_LABELS = Object.fromEntries(TYPES.map((item) => [item.type, item.label])) as Record<MonthlyPlanLineType, string>;
// 収益 rather than the database screen's 収入, so the kind never reads as the movement.
export const KIND_LABELS: Record<AccountKind, string> = { income: '収益', expense: '費用', asset: '資産', liability: '負債' };
export const KINDS: AccountKind[] = ['income', 'expense', 'asset', 'liability'];

export const lineName = (line: MonthlyPlanLine) => line.target_name || line.name || line.account_name || '名称未設定';

/** Where a budget row came from, as the overlay names it. */
export function lineOrigin(line: MonthlyPlanLine): string {
    if (line.source_kind === 'goal' || line.source === 'goal') return 'ゴール';
    if (line.target_type === 'capsule' || line.target_type === 'life_event') return '取り置き';
    if (line.source === 'registry' || line.registry_entry_ids?.length) return '自動取引';
    if (line.source === 'credit_settlement' || line.source_kind === 'credit_settlement') return 'カード請求';
    return '手入力';
}

/** One account or subject in one of the six movements. */
export interface Cell {
    type: MonthlyPlanLineType;
    /** Saved rows and the definitions' unsaved rows. */
    lines: MonthlyPlanLine[];
    /** The zero row the summary sends when no line covers the account. */
    unset: MonthlyPlanLine | null;
    budget: number;
    actual: number;
    /** False while nothing is saved and every amount is zero: shown as 未設定. */
    set: boolean;
    goal: boolean;
    /** The account's kind is not the one this movement normally lands on. */
    mismatch: boolean;
}

export interface AccountRow {
    key: string;
    accountId: number | null;
    name: string;
    kind: AccountKind | null;
    cells: Cell[];
    /** The month's automatic transactions on either side of this account. */
    scheduled: ScheduledTransaction[];
}

/** An earmark is not an account: its rows set part of a funding account's balance aside. */
export interface EarmarkRow {
    key: string;
    capsuleId: number | null;
    name: string;
    lines: MonthlyPlanLine[];
    budget: number;
    /** What the earmark holds now (its claim on the funding accounts), not the month's movement. */
    held: number;
    sources: string[];
}

export interface BudgetModel { accounts: AccountRow[]; earmarks: EarmarkRow[] }

const isEarmark = (line: MonthlyPlanLine) => line.target_type === 'capsule' || line.target_type === 'life_event';

function fits(kind: AccountKind, type: MonthlyPlanLineType) {
    const expected = TYPES.find((item) => item.type === type)?.kind;
    return kind === expected;
}

// A line without a source account claims the account's whole side of the month;
// lines with one split it, so they add up instead.
function cellActual(lines: MonthlyPlanLine[]) {
    const whole = lines.find((line) => !line.source_account_id);
    return whole ? whole.actual ?? 0 : lines.reduce((total, line) => total + (line.actual ?? 0), 0);
}

export function buildModel(summary: BudgetSummary, accounts: DatabaseAccount[], scheduled: ScheduledTransaction[]): BudgetModel {
    const byId = new Map(accounts.map((account) => [account.id, account]));
    const rows = new Map<string, AccountRow>();
    const earmarks = new Map<string, EarmarkRow>();
    const rowFor = (line: MonthlyPlanLine) => {
        const id = line.account_id ?? null;
        const key = id == null ? `none:${lineName(line)}` : `account:${id}`;
        let row = rows.get(key);
        if (!row) {
            const account = id == null ? undefined : byId.get(id);
            row = {
                key, accountId: id, name: account?.name ?? (id == null ? lineName(line) : line.account_name || lineName(line)),
                kind: account?.account_type ?? null, cells: [],
                scheduled: id == null ? [] : scheduled.filter((item) => item.account_id === id || item.counter_account_id === id),
            };
            rows.set(key, row);
        }
        return row;
    };
    const cellFor = (row: AccountRow, type: MonthlyPlanLineType) => {
        let cell = row.cells.find((item) => item.type === type);
        if (!cell) {
            cell = { type, lines: [], unset: null, budget: 0, actual: 0, set: false, goal: false, mismatch: false };
            row.cells.push(cell);
        }
        return cell;
    };
    for (const line of summary.plan_lines) {
        if (isEarmark(line)) {
            const key = `earmark:${line.target_id ?? lineName(line)}`;
            const earmark = earmarks.get(key) ?? { key, capsuleId: line.target_id ?? null, name: lineName(line), lines: [], budget: 0, held: 0, sources: [] };
            earmark.lines.push(line);
            earmarks.set(key, earmark);
            continue;
        }
        cellFor(rowFor(line), line.line_type).lines.push(line);
    }
    for (const line of summary.unset_lines) cellFor(rowFor(line), line.line_type).unset = line;

    for (const row of rows.values()) {
        for (const cell of row.cells) {
            cell.budget = cell.lines.reduce((total, line) => total + (line.budget_amount ?? 0), 0);
            cell.actual = cell.lines.length ? cellActual(cell.lines) : cell.unset?.actual ?? 0;
            cell.set = cell.lines.some((line) => line.id != null || (line.budget_amount ?? 0) !== 0);
            cell.goal = cell.lines.some((line) => lineOrigin(line) === 'ゴール');
            cell.mismatch = row.kind != null && !fits(row.kind, cell.type);
        }
        row.cells.sort((a, b) => TYPES.findIndex((item) => item.type === a.type) - TYPES.findIndex((item) => item.type === b.type));
    }
    for (const earmark of earmarks.values()) {
        earmark.budget = earmark.lines.reduce((total, line) => total + (line.budget_amount ?? 0), 0);
        earmark.held = earmark.lines.reduce((total, line) => total + (line.actual ?? 0), 0);
        earmark.sources = [...new Set(earmark.lines.map((line) => line.account_name).filter((name): name is string => Boolean(name)))];
    }
    const byName = <T extends { name: string }>(a: T, b: T) => a.name.localeCompare(b.name, 'ja');
    return { accounts: [...rows.values()].sort(byName), earmarks: [...earmarks.values()].sort(byName) };
}

export type Scope = 'all' | 'budget' | 'scheduled';
export const SCOPES: Array<{ value: Scope; label: string }> = [
    { value: 'all', label: 'すべて' }, { value: 'budget', label: '予算あり' }, { value: 'scheduled', label: '取引予定あり' },
];

export function rowMatches(row: AccountRow, query: string, scope: Scope) {
    const needle = query.trim().toLowerCase();
    if (needle && !row.name.toLowerCase().includes(needle)) return false;
    if (scope === 'budget') return row.cells.some((cell) => cell.budget !== 0);
    if (scope === 'scheduled') return row.scheduled.length > 0;
    return true;
}

/** Earmarks hold no automatic transactions, so 取引予定あり leaves them out. */
export function earmarkMatches(earmark: EarmarkRow, query: string, scope: Scope) {
    const needle = query.trim().toLowerCase();
    if (needle && !earmark.name.toLowerCase().includes(needle)) return false;
    if (scope === 'budget') return earmark.budget !== 0;
    return scope !== 'scheduled';
}

/** U9 in one sentence: the month's budgeted savings against the whole monthly need. */
export function savingsHeadline(check: SavingsCheck, currency: string) {
    const money = (amount: number) => formatCurrency(amount, currency);
    const over = check.budgeted - check.need;
    if (check.shortfall > 0) return `積立が必要額より ${money(check.shortfall)} 少なくなっています`;
    return over >= 1 ? `積立は必要額を ${money(over)} 上回っています` : '積立は必要額と一致しています';
}

/** The need per earmark name, for the mark beside an earmark's row (products and near events). */
export function needByName(check: SavingsCheck | null | undefined) {
    const need = new Map<string, number>();
    for (const group of check?.groups ?? []) {
        if (group.key !== 'products' && group.key !== 'near') continue;
        for (const item of group.items) need.set(item.name, (need.get(item.name) ?? 0) + item.amount);
    }
    return need;
}
