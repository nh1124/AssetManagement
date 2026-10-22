import type { MonthlyPlanLine, MonthlyPlanLineType, ScheduledTransaction } from '../../../types';
import type { DatabaseAccount } from '../db/forms';
import type { PlanRecord, PlanSection } from '../../../api/plan';
import { tr, labels } from '../../i18n';

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
export const TYPE_LABELS = labels<MonthlyPlanLineType>({
    income: ['収入', 'Income'], expense: ['支出', 'Expense'], allocation: ['配分', 'Allocation'],
    debt_payment: ['返済', 'Repayment'], borrowing: ['借入', 'Borrowing'], drawdown: ['取り崩し', 'Drawdown'],
});
export const TYPES: Array<{ type: MonthlyPlanLineType; readonly label: string; kind: AccountKind }> = ([
    ['income', 'income'], ['expense', 'expense'], ['allocation', 'asset'],
    ['debt_payment', 'liability'], ['borrowing', 'liability'], ['drawdown', 'asset'],
] as const).map(([type, kind]) => ({ type, kind, get label() { return TYPE_LABELS[type]; } }));
// 収益 rather than the database screen's 収入, so the kind never reads as the movement.
export const KIND_LABELS = labels<AccountKind>({ income: ['収益', 'Revenue'], expense: ['費用', 'Expenses'], asset: ['資産', 'Assets'], liability: ['負債', 'Liabilities'] });
export const KINDS: AccountKind[] = ['income', 'expense', 'asset', 'liability'];

// The server sends Japanese labels for plan records; their keys say the same in either language.
export const ORIGIN_LABELS = labels<PlanRecord['origin']>({
    goal: ['ゴールによる設定', 'Set by a goal'], registry: ['自動取引による設定', 'Set by an automatic transaction'],
    card: ['カード請求の見込み', 'Card bill estimate'], manual: ['ユーザーによる追加', 'Added by you'],
});

/** A section is the account's 予算 unless it is one of the other movements (or does not fit the account). */
export function sectionLabel(section: PlanSection): string {
    const key = section.key as keyof typeof TYPE_LABELS;
    if (!section.mismatch && (key === 'allocation' || key === 'expense' || key === 'income')) return tr('予算', 'Budget');
    return TYPE_LABELS[key] ?? section.label;
}

export const lineName = (line: MonthlyPlanLine) => line.target_name || line.name || line.account_name || tr('名称未設定', 'Untitled');

const isGoalLine = (line: MonthlyPlanLine) => line.source_kind === 'goal' || line.source === 'goal';

/** Where a budget row came from, as the overlay names it. */
export function lineOrigin(line: MonthlyPlanLine): string {
    if (isGoalLine(line)) return tr('ゴール', 'Goal');
    if (line.target_type === 'capsule') return tr('取り置き', 'Earmark');
    if (line.source === 'registry' || line.registry_entry_ids?.length) return tr('自動取引', 'Automatic transaction');
    if (line.source === 'credit_settlement' || line.source_kind === 'credit_settlement') return tr('カード請求', 'Card bill');
    return tr('手入力', 'Entered by hand');
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
    /** The goal's plan sets part of its budget, or it funds an earmark made for a goal event. */
    goal: boolean;
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
    /** Made for a goal event when the goal's plan was made; named after the event. */
    goal: boolean;
}

export interface BudgetModel { accounts: AccountRow[]; earmarks: EarmarkRow[] }

const isEarmark = (line: MonthlyPlanLine) => line.target_type === 'capsule';

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
                kind: account?.account_type ?? null, cells: [], goal: false,
                scheduled: id == null ? [] : scheduled.filter((item) => item.account_id === id || item.counter_account_id === id),
            };
            rows.set(key, row);
        }
        return row;
    };
    const cellFor = (row: AccountRow, type: MonthlyPlanLineType) => {
        let cell = row.cells.find((item) => item.type === type);
        if (!cell) {
            cell = { type, lines: [], unset: null, budget: 0, actual: 0, set: false, mismatch: false };
            row.cells.push(cell);
        }
        return cell;
    };
    const goalFunding = new Set<number>();
    for (const line of summary.plan_lines) {
        if (isEarmark(line)) {
            const key = `earmark:${line.target_id ?? lineName(line)}`;
            const earmark = earmarks.get(key) ?? { key, capsuleId: line.target_id ?? null, name: lineName(line), lines: [], budget: 0, held: 0, sources: [], goal: false };
            earmark.lines.push(line);
            if (line.goal_earmark) {
                earmark.goal = true;
                if (line.account_id != null) goalFunding.add(line.account_id);
            }
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
            cell.mismatch = row.kind != null && !fits(row.kind, cell.type);
        }
        row.goal = row.cells.some((cell) => cell.lines.some(isGoalLine))
            || (row.accountId != null && goalFunding.has(row.accountId));
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

export type Scope = 'all' | 'budget' | 'scheduled' | 'goal';
const SCOPE_LABELS = labels<Scope>({ all: ['すべて', 'All'], budget: ['予算あり', 'With a budget'], scheduled: ['取引予定あり', 'With scheduled transactions'], goal: ['ゴール関係', 'Goal-related'] });
export const SCOPES: Array<{ value: Scope; readonly label: string }> = (['all', 'budget', 'scheduled', 'goal'] as const)
    .map((value) => ({ value, get label() { return SCOPE_LABELS[value]; } }));

export function rowMatches(row: AccountRow, query: string, scope: Scope) {
    const needle = query.trim().toLowerCase();
    if (needle && !row.name.toLowerCase().includes(needle)) return false;
    if (scope === 'budget') return row.cells.some((cell) => cell.budget !== 0);
    if (scope === 'scheduled') return row.scheduled.length > 0;
    if (scope === 'goal') return row.goal;
    return true;
}

/** Earmarks hold no automatic transactions, so 取引予定あり leaves them out. */
export function earmarkMatches(earmark: EarmarkRow, query: string, scope: Scope) {
    const needle = query.trim().toLowerCase();
    if (needle && !earmark.name.toLowerCase().includes(needle)) return false;
    if (scope === 'budget') return earmark.budget !== 0;
    if (scope === 'goal') return earmark.goal;
    return scope !== 'scheduled';
}
