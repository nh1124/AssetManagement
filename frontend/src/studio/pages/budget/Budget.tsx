import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { clientToday, useTimezone } from '../../datetime';
import { useCallback, useId, useState, type FormEvent } from 'react';
import { createMonthlyPlanLines, deleteMonthlyPlanLine, getBudgetSummary, updateMonthlyPlanLines, type MonthlyPlanLinePayload } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { MonthlyPlanLine, MonthlyPlanLineType } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { EditorActions, Feedback, Field } from '../db/Database';
import AccountEditor from '../db/AccountEditor';
import { buttonClass, inputClass, loadAccounts, useMutation, type DatabaseAccount } from '../db/forms';
import MonthCopy from './MonthCopy';
import SavingsCheck from './SavingsCheck';
import { getSavingsCheck } from '../../../api/goalBudget';
import GoalBudgetReflection from '../goals/GoalBudgetReflection';
import GoalReflectionNotice from '../goals/GoalReflectionNotice';
import { useNotifications } from '../../notificationContext';
import MonthPicker from '../ledger/MonthPicker';

// budget_plan_service returns plan_lines and plan_id, not the legacy budget model.
export interface BudgetSummary {
    period: string;
    plan_id: number | null;
    feasibility_status: 'ok' | 'warning' | 'shortfall';
    plan_lines: MonthlyPlanLine[];
    /** Active accounts no plan line covers: unsaved zero rows with their actuals. */
    unset_lines: MonthlyPlanLine[];
}

// accountType is what 項目を追加 starts with while the block is selected.
const BLOCKS: Array<{ type: MonthlyPlanLineType; label: string; accountType: DatabaseAccount['account_type'] }> = [
    { type: 'income', label: '収入', accountType: 'income' }, { type: 'expense', label: '支出', accountType: 'expense' },
    { type: 'allocation', label: '配分', accountType: 'asset' }, { type: 'debt_payment', label: '返済', accountType: 'liability' },
    { type: 'borrowing', label: '借入', accountType: 'liability' }, { type: 'drawdown', label: '取り崩し', accountType: 'asset' },
];
const STATES = { synced: '定義と一致', missing: '月の計画は未保存', diff: '定義との差あり' };
const lineName = (line: MonthlyPlanLine) => line.target_name || line.name || line.account_name || '名称未設定';

type Scope = 'all' | 'budget' | 'actual';
const SCOPES: Array<{ value: Scope; label: string }> = [{ value: 'all', label: 'すべて' }, { value: 'budget', label: '予算あり' }, { value: 'actual', label: '実績あり' }];
interface Filters { query: string; block: MonthlyPlanLineType | 'all'; scope: Scope }
const FILTERS_KEY = 'studio.budget.filters';

function storedFilters(): Filters {
    try {
        const stored = JSON.parse(localStorage.getItem(FILTERS_KEY) ?? '{}') as Partial<Filters>;
        return {
            query: '',
            block: BLOCKS.some((block) => block.type === stored.block) ? stored.block as MonthlyPlanLineType : 'all',
            scope: SCOPES.some((scope) => scope.value === stored.scope) ? stored.scope as Scope : 'all',
        };
    } catch {
        return { query: '', block: 'all', scope: 'all' };
    }
}

/** A row of the list; unset rows are accounts no plan line covers yet. */
interface Row { line: MonthlyPlanLine; unset: boolean }

function AmountEditor({ line, currency, busy, onSave, onCancel }: {
    line: MonthlyPlanLine; currency: string; busy: boolean;
    onSave: (amount: number) => void; onCancel: () => void;
}) {
    const formId = useId();
    const [amount, setAmount] = useState(String(line.amount));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || amount.trim() === '' || !Number.isFinite(Number(amount)) || Number(amount) < 0) return;
        onSave(Number(amount));
    };
    return <form id={formId} onSubmit={submit} className="space-y-4">
        {line.target_type === 'capsule' && <p className="text-xs text-[var(--studio-warning)]">取り置きの月額積立計画にも反映されます。</p>}
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label={`予算（${currency}）`}><input required type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}

/** 項目を追加: a new account or subject, made with the database screen's editor. */
function AddItem({ initialType, currency, busy, error, onSave, onClose }: {
    initialType: DatabaseAccount['account_type']; currency: string; busy: boolean; error: string;
    onSave: (action: () => Promise<unknown>) => void; onClose: () => void;
}) {
    const accounts = useResource(loadAccounts);
    return <Overlay title="項目を追加（口座・勘定科目）" onClose={onClose}>
        <p className="mb-4 text-xs text-[var(--studio-text-muted)]">作成すると種別に合うブロックに予算「未設定」で並びます。役割が運用の口座は予算の項目に出ません。</p>
        <Feedback loading={accounts.loading} error={error || accounts.error} />
        {accounts.data && <AccountEditor account={null} accounts={accounts.data} initialType={initialType} currency={currency} busy={busy} onSave={onSave} onCancel={onClose} />}
    </Overlay>;
}

function FilterBar({ filters, onChange }: { filters: Filters; onChange: (filters: Filters) => void }) {
    return <div className="flex flex-wrap items-center gap-2">
        <div className="w-56"><input type="search" aria-label="名前で検索" placeholder="名前で検索" value={filters.query} onChange={(event) => onChange({ ...filters, query: event.target.value })} className={inputClass} /></div>
        <div className="w-40"><select aria-label="種別" value={filters.block} onChange={(event) => onChange({ ...filters, block: event.target.value as Filters['block'] })} className={inputClass}>
            <option value="all">すべての種別</option>
            {BLOCKS.map((block) => <option key={block.type} value={block.type}>{block.label}</option>)}
        </select></div>
        <div role="group" aria-label="表示する項目" className="inline-flex overflow-hidden rounded-md border border-[var(--studio-border)]">
            {SCOPES.map((scope) => <button key={scope.value} type="button" aria-pressed={filters.scope === scope.value} onClick={() => onChange({ ...filters, scope: scope.value })} className={`${buttonClass} rounded-none border-0 aria-pressed:bg-[var(--studio-accent-soft)] aria-pressed:text-[var(--studio-accent)]`}>{scope.label}</button>)}
        </div>
    </div>;
}

function MonthlyBudget({ period, currency, clientName, filters, onFilters, onBusy }: {
    period: string; currency: string; clientName?: string; filters: Filters;
    onFilters: (filters: Filters) => void; onBusy: (busy: boolean) => void;
}) {
    const confirm = useConfirm();
    const load = useCallback((): Promise<BudgetSummary> => getBudgetSummary(period, { include_unset: true }), [period]);
    const resource = useResource(load);
    const loadCheck = useCallback(() => getSavingsCheck(period), [period]);
    const check = useResource(loadCheck);
    const refresh = () => { resource.reload(); check.reload(); };
    const mutation = useMutation();
    const [copyBusy, setCopyBusy] = useState(false);
    const [editing, setEditing] = useState<Row | null>(null);
    const [reflecting, setReflecting] = useState(false);
    const [adding, setAdding] = useState(false);
    const [created, setCreated] = useState<number | null>(null);
    const [unfolded, setUnfolded] = useState<MonthlyPlanLineType[]>([]);
    const notifications = useNotifications();
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy || copyBusy || !clientName;
    const locked = disabled || editing !== null || adding;
    const lines = resource.data?.plan_lines ?? [];
    const save = async (amount: number) => {
        if (disabled || !editing || !resource.data) return;
        const { line, unset } = editing;
        const name = lineName(line);
        const effect = line.target_type === 'capsule' ? '\n取り置きの月額積立計画にも反映されます。' : '';
        const before = unset ? '未設定' : formatCurrency(line.amount, currency);
        if (!(await confirm(`「${clientName}」の${period}「${name}」を ${before} → ${formatCurrency(amount, currency)}（${currency}）に変更しますか？${effect}`, '変更する'))) return;
        // Send only writable fields; summary actuals and synchronization state are server-owned.
        const payload: MonthlyPlanLinePayload = {
            target_period: line.target_period, line_type: line.line_type, target_type: line.target_type,
            target_id: line.target_id, account_id: line.account_id, source_account_id: line.source_account_id,
            name: line.name || name, amount, source: line.source || 'manual', source_kind: line.source_kind || 'manual',
            manual_override: true, cash_treatment: line.cash_treatment || 'auto', is_active: line.is_active ?? true,
            plan_id: resource.data.plan_id,
        };
        const id = line.id;
        void mutation.run(() => id == null ? createMonthlyPlanLines([payload]) : updateMonthlyPlanLines([{ ...payload, id }]), '計画額を保存しました。', () => {
            setEditing(null);
            refresh();
        });
    };
    const remove = async (line: MonthlyPlanLine) => {
        if (disabled || line.id == null) return;
        const id = line.id;
        const generated = line.source !== 'manual' || Boolean(line.registry_entry_ids?.length);
        if (!(await confirm(`「${clientName}」の${period}「${lineName(line)}」の予算行を削除しますか？\n${generated ? '定義から作られた項目は、削除後も表示される場合があります。' : '削除は取り消せません。'}`, '削除する'))) return;
        void mutation.run(() => deleteMonthlyPlanLine(id), '予算行を削除しました。', () => {
            setEditing(null);
            resource.setData((previous) => previous ? { ...previous, plan_lines: previous.plan_lines.filter((row) => row.id !== id) } : null);
            refresh();
        });
    };
    const add = (action: () => Promise<unknown>) => void mutation.run(async () => {
        const account = await action() as { id: number };
        setCreated(account.id);
    }, '項目を追加しました。一覧で色付きで表示しています。', () => {
        setAdding(false);
        resource.reload();
    });

    const rows: Row[] = [...lines.map((line) => ({ line, unset: false })), ...(resource.data?.unset_lines ?? []).map((line) => ({ line, unset: true }))];
    const needle = filters.query.trim().toLowerCase();
    const narrowed = Boolean(needle) || filters.scope !== 'all';
    const isNew = (row: Row) => row.unset && row.line.account_id === created;
    const matches = (row: Row) => (!needle || `${lineName(row.line)} ${row.line.account_name ?? ''}`.toLowerCase().includes(needle))
        && (filters.scope === 'all' || (filters.scope === 'budget' ? row.line.amount !== 0 : Boolean(row.line.actual)));
    // Most accounts have no budget and no actual in a month; they fold under one line per block.
    const quiet = (row: Row) => !narrowed && row.line.amount === 0 && !row.line.actual && !isNew(row);
    const blocks = BLOCKS.filter((block) => filters.block === 'all' || filters.block === block.type).map((block) => {
        const all = rows.filter((row) => row.line.line_type === block.type);
        const matching = all.filter(matches);
        const folded = matching.filter(quiet).length;
        const open = unfolded.includes(block.type);
        return { ...block, all, folded, open, shown: open ? matching : matching.filter((row) => !quiet(row)), empty: matching.length === 0 };
    }).filter((block) => !narrowed || !block.empty);

    return <div className="space-y-4">
        <Feedback loading={resource.loading} error={resource.error} />
        <Feedback error={mutation.error && !adding ? mutation.error : undefined} message={mutation.message} />
        <div className="flex flex-wrap items-start gap-2">
            <MonthCopy period={period} disabled={locked} clientName={clientName} onBusy={(busy) => { setCopyBusy(busy); onBusy(busy); }} onCopied={refresh} />
            <button type="button" disabled={locked} onClick={() => setReflecting(true)} className={buttonClass}>ゴールから更新</button>
            <button type="button" disabled={locked} onClick={() => setAdding(true)} className={buttonClass}>項目を追加</button>
        </div>
        {reflecting && <GoalBudgetReflection title="ゴールから予算を更新" initialPeriod={period} onClose={() => { setReflecting(false); notifications.refresh(); }} onApplied={refresh} />}
        {adding && <AddItem initialType={BLOCKS.find((block) => block.type === filters.block)?.accountType ?? 'expense'} currency={currency} busy={disabled} error={mutation.error} onSave={add} onClose={() => setAdding(false)} />}
        <GoalReflectionNotice />
        {check.error ? <Feedback error={`積立と必要額の比較を取得できませんでした。${check.error}`} /> : check.data && <SavingsCheck check={check.data} currency={currency} />}
        {editing && <Overlay title={`「${lineName(editing.line)}」の金額を編集`} onClose={() => setEditing(null)} footer={editing.line.id != null
            ? <button type="button" disabled={disabled} onClick={() => remove(editing.line)} className={`${buttonClass} mr-auto text-[var(--studio-danger)]`}>削除</button>
            : <span className="mr-auto text-xs text-[var(--studio-text-muted)]">未保存のため削除不可</span>}><Feedback error={mutation.error} /><AmountEditor key={editing.line.id ?? lineName(editing.line)} line={editing.line} currency={currency} busy={disabled} onSave={save} onCancel={() => setEditing(null)} /></Overlay>}
        <FilterBar filters={filters} onChange={onFilters} />
        {resource.data && <div className="overflow-x-auto rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)]">
            <table className="w-full text-left text-sm">
                <thead className="border-b border-[var(--studio-border)] text-xs text-[var(--studio-text-muted)]"><tr>{['項目', '予算', '実績', '差額', '状態'].map((label) => <th key={label} scope="col" className="whitespace-nowrap px-5 py-3 font-medium">{label}</th>)}</tr></thead>
                {blocks.map((block) => <tbody key={block.type} className="divide-y divide-[var(--studio-border)] border-b border-[var(--studio-border)] last:border-b-0">
                    <tr className="bg-[var(--studio-bg)]">
                        <th scope="rowgroup" className="px-5 py-2 text-sm font-semibold">{block.label} <span className="ml-1 text-xs font-normal text-[var(--studio-text-muted)]">{block.all.length}件</span></th>
                        <td className="whitespace-nowrap px-5 py-2 text-xs tabular-nums text-[var(--studio-text-muted)]">計 {formatCurrency(block.all.reduce((total, row) => total + row.line.amount, 0), currency)}</td>
                        <td colSpan={3} />
                    </tr>
                    {block.shown.map((row, index) => <BudgetRow key={row.line.id ?? `${row.unset ? 'unset' : row.line.target_type}:${row.line.target_id ?? ''}:${row.line.account_id ?? ''}:${index}`} row={row} currency={currency} highlight={isNew(row)} disabled={locked} onEdit={() => setEditing(row)} />)}
                    {block.empty && <tr><td colSpan={5} className="px-5 py-3 text-xs text-[var(--studio-text-muted)]">この種別の項目はありません。</td></tr>}
                    {block.folded > 0 && <tr><td colSpan={5} className="px-5 py-2">
                        <button type="button" aria-expanded={block.open} onClick={() => setUnfolded((previous) => block.open ? previous.filter((type) => type !== block.type) : [...previous, block.type])} className="text-xs text-[var(--studio-accent)] hover:underline">
                            {block.open ? `予算・実績のない ${block.folded}件を閉じる` : `予算・実績のない ${block.folded}件を表示`}
                        </button>
                    </td></tr>}
                </tbody>)}
                {!blocks.length && <tbody><tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">条件に合う項目はありません。</td></tr></tbody>}
            </table>
        </div>}
    </div>;
}

function BudgetRow({ row, currency, highlight, disabled, onEdit }: {
    row: Row; currency: string; highlight: boolean; disabled: boolean; onEdit: () => void;
}) {
    const { line, unset } = row;
    const status = unset ? '未設定' : line.sync_status ? STATES[line.sync_status] : line.suggested_status ? STATES[line.suggested_status] : '—';
    return <tr onClick={() => { if (!disabled) onEdit(); }} className={`${highlight ? 'bg-[var(--studio-accent-soft)]' : ''} ${disabled ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]'}`}>
        <th scope="row" className="px-5 py-3 font-medium"><button type="button" disabled={disabled} aria-label={`${lineName(line)}の金額を編集`} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); onEdit(); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{lineName(line)}</button>{line.account_name && line.account_name !== lineName(line) && <span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{line.account_name}</span>}</th>
        <td className={`whitespace-nowrap px-5 py-3 tabular-nums ${unset ? 'text-[var(--studio-text-faint)]' : ''}`}>{unset ? '未設定' : formatCurrency(line.amount, currency)}</td>
        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{line.actual == null ? '—' : formatCurrency(line.actual, currency)}</td>
        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{line.variance == null ? '—' : formatCurrency(line.variance, currency)}</td>
        <td className="px-5 py-3 text-xs text-[var(--studio-text-muted)]">{status}</td>
    </tr>;
}

export default function Budget() {
    const { clientId, currentClient } = useClient();
    const timezone = useTimezone();
    const [busy, setBusy] = useState(false);
    const [periodEdit, setPeriod] = useState<string | null>(null);
    const [filters, setFilters] = useState(storedFilters);
    const period = periodEdit ?? clientToday(timezone).slice(0, 7);
    const currency = currentClient?.general_settings?.currency || 'JPY';
    const changeFilters = (next: Filters) => {
        setFilters(next);
        // The search is per visit; the block and scope stay for the next one.
        try { localStorage.setItem(FILTERS_KEY, JSON.stringify({ block: next.block, scope: next.scope })); } catch { /* storage unavailable */ }
    };
    return <section className="space-y-4">
        <MonthPicker value={period} onChange={setPeriod} disabled={busy} />
        <MonthlyBudget key={`${clientId}:${period}:${currency}`} period={period} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} filters={filters} onFilters={changeFilters} onBusy={setBusy} />
    </section>;
}
