import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { createMonthlyPlanLines, deleteMonthlyPlanLine, updateMonthlyPlanLines, type MonthlyPlanLinePayload } from '../../../api';
import type { MonthlyPlanLine, ScheduledTransaction } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { Feedback } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';
import { KIND_LABELS, TYPE_LABELS, lineName, lineOrigin, type AccountRow, type EarmarkRow } from './budgetRows';

export interface OverlayContext {
    period: string;
    currency: string;
    clientName?: string;
    planId: number | null;
    accountName: (id: number | null) => string;
    onChanged: () => void;
}

const lineKey = (line: MonthlyPlanLine, index: number) => line.id != null ? `id:${line.id}` : `${line.source}:${line.target_type}:${line.target_id ?? ''}:${line.account_id ?? ''}:${index}`;

/** Saving and deleting one budget row, with the same confirmation the page always asked for. */
function useLineActions({ period, currency, clientName, planId, onChanged }: OverlayContext) {
    const confirm = useConfirm();
    const mutation = useMutation();
    const save = async (line: MonthlyPlanLine, amount: number, done: () => void) => {
        if (mutation.busy || !clientName) return;
        const name = lineName(line);
        const effect = line.target_type === 'capsule' ? '\n取り置きの月額積立計画にも反映されます。' : '';
        const before = line.id == null && line.amount === 0 ? '未設定' : formatCurrency(line.amount, currency);
        if (!(await confirm(`「${clientName}」の${period}「${name}」を ${before} → ${formatCurrency(amount, currency)}（${currency}）に変更しますか？${effect}`, '変更する'))) return;
        // Send only writable fields; summary actuals and synchronization state are server-owned.
        const payload: MonthlyPlanLinePayload = {
            target_period: line.target_period, line_type: line.line_type, target_type: line.target_type,
            target_id: line.target_id, account_id: line.account_id, source_account_id: line.source_account_id,
            name: line.name || name, amount, source: line.source || 'manual', source_kind: line.source_kind || 'manual',
            manual_override: true, cash_treatment: line.cash_treatment || 'auto', is_active: line.is_active ?? true,
            plan_id: planId,
        };
        const id = line.id;
        void mutation.run(() => id == null ? createMonthlyPlanLines([payload]) : updateMonthlyPlanLines([{ ...payload, id }]), '予算を保存しました。', () => { done(); onChanged(); });
    };
    const remove = async (line: MonthlyPlanLine) => {
        if (mutation.busy || line.id == null || !clientName) return;
        const id = line.id;
        const generated = line.source !== 'manual' || Boolean(line.registry_entry_ids?.length);
        if (!(await confirm(`「${clientName}」の${period}「${lineName(line)}」の予算行を削除しますか？\n${generated ? '定義から作られた項目は、削除後も表示される場合があります。' : '削除は取り消せません。'}`, '削除する'))) return;
        void mutation.run(() => deleteMonthlyPlanLine(id), '予算行を削除しました。', onChanged);
    };
    return { mutation, save, remove, disabled: mutation.busy || !clientName };
}

function LineItem({ line, label, currency, editing, disabled, onEdit, onCancel, onSave, onRemove }: {
    line: MonthlyPlanLine; label: string; currency: string; editing: boolean; disabled: boolean;
    onEdit: () => void; onCancel: () => void; onSave: (amount: number) => void; onRemove: () => void;
}) {
    const [amount, setAmount] = useState(String(line.amount));
    const unsaved = line.id == null && line.amount === 0;
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || amount.trim() === '' || !Number.isFinite(Number(amount)) || Number(amount) < 0) return;
        onSave(Number(amount));
    };
    return <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2">
        <span className="min-w-0 flex-1 text-sm">{label}<span className="ml-2 rounded bg-[var(--studio-bg)] px-1.5 py-0.5 text-[11px] text-[var(--studio-text-muted)]">{lineOrigin(line)}</span></span>
        {editing
            ? <form onSubmit={submit} className="flex items-center gap-2">
                <input autoFocus aria-label={`${label}（${currency}）`} type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} className={`${inputClass} w-36`} />
                <button type="submit" disabled={disabled} className={primaryClass}>保存</button>
                <button type="button" onClick={onCancel} className={buttonClass}>取消</button>
            </form>
            : <>
                <span className={`w-28 text-right tabular-nums ${unsaved ? 'text-[var(--studio-text-faint)]' : ''}`}>{unsaved ? '未設定' : formatCurrency(line.amount, currency)}</span>
                <button type="button" disabled={disabled} onClick={onEdit} className={buttonClass}>編集</button>
                {line.id != null && <button type="button" disabled={disabled} onClick={onRemove} className={`${buttonClass} text-[var(--studio-danger)]`}>削除</button>}
            </>}
    </li>;
}

const RECORDING = { auto: '自動記帳', manual: '記帳待ち', none: '予算のみ' };

function ScheduledTable({ items, accountId, context }: { items: ScheduledTransaction[]; accountId: number | null; context: OverlayContext }) {
    const money = (amount: number) => formatCurrency(amount, context.currency);
    if (!items.length) return <p className="text-sm text-[var(--studio-text-muted)]">この月の自動取引はありません。</p>;
    return <div className="overflow-x-auto"><table className="w-full text-left text-sm">
        <thead className="text-xs text-[var(--studio-text-muted)]"><tr>{['予定日', '定義', '種別', '相手', '金額', '記帳'].map((label) => <th key={label} scope="col" className="whitespace-nowrap py-1 pr-4 font-medium">{label}</th>)}</tr></thead>
        <tbody className="divide-y divide-[var(--studio-border)]">
            {items.map((item, index) => {
                const other = item.account_id === accountId ? item.counter_account_id : item.account_id;
                return <tr key={`${item.kind}:${item.entry_id ?? item.product_id}:${index}`}>
                    <td className="whitespace-nowrap py-2 pr-4 tabular-nums">{item.date ? item.date.slice(5).replace('-', '/') : '日付なし'}</td>
                    <th scope="row" className="py-2 pr-4 font-normal">{item.name}</th>
                    <td className="whitespace-nowrap py-2 pr-4">{item.kind === 'depreciation' ? '減価' : item.line_type ? TYPE_LABELS[item.line_type] : '—'}</td>
                    <td className="py-2 pr-4 text-[var(--studio-text-muted)]">{context.accountName(other)}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-right tabular-nums">{money(item.amount)}</td>
                    <td className="whitespace-nowrap py-2 text-xs">{RECORDING[item.recording]}{item.posted ? '・記帳済み' : ''}{item.kind === 'definition' && !item.in_budget ? '（予算外）' : ''}</td>
                </tr>;
            })}
        </tbody>
    </table></div>;
}

/** An account's budget in each movement and the month's automatic transactions on it. */
export function AccountOverlay({ row, context, onClose }: { row: AccountRow; context: OverlayContext; onClose: () => void }) {
    const actions = useLineActions(context);
    const [editing, setEditing] = useState<string | null>(null);
    const money = (amount: number) => formatCurrency(amount, context.currency);
    const noun = row.kind === 'income' || row.kind === 'expense' ? '科目' : '口座';
    return <Overlay title={row.name} busy={actions.mutation.busy} onClose={onClose}>
        <div className="space-y-6">
            <p className="text-xs text-[var(--studio-text-muted)]">{row.kind ? `${KIND_LABELS[row.kind]}の${noun}` : '口座未指定の予算行'} ・ {context.period}</p>
            <Feedback error={actions.mutation.error} message={actions.mutation.message} />
            <section className="space-y-3">
                <h3 className="text-sm font-semibold">予算</h3>
                {row.cells.map((cell) => {
                    const lines = cell.lines.length ? cell.lines : cell.unset ? [cell.unset] : [];
                    return <div key={cell.type} className="rounded-md border border-[var(--studio-border)] px-4 py-2">
                        <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                            <span className="font-medium">{TYPE_LABELS[cell.type]}</span>
                            <span className="text-xs tabular-nums text-[var(--studio-text-muted)]">予算 {cell.set ? money(cell.budget) : '未設定'} ／ 実績 {money(cell.actual)}</span>
                        </div>
                        {cell.mismatch && row.kind && <p className="mt-1 text-xs text-[var(--studio-warning)]">{KIND_LABELS[row.kind]}の{noun}に{TYPE_LABELS[cell.type]}の予算があります。定義の種別か口座を確認してください。</p>}
                        {cell.defined > 0 && !cell.set && <p className="mt-1 text-xs text-[var(--studio-text-muted)]">定義の予定額 {money(cell.defined)}。予算は未設定です。</p>}
                        <ul className="divide-y divide-[var(--studio-border)]">
                            {lines.map((line, index) => {
                                const key = `${cell.type}:${lineKey(line, index)}`;
                                const label = lines.length > 1 || lineName(line) !== row.name ? lineName(line) : 'この月の予算';
                                return <LineItem key={key} line={line} label={label} currency={context.currency} editing={editing === key} disabled={actions.disabled}
                                    onEdit={() => setEditing(key)} onCancel={() => setEditing(null)} onRemove={() => actions.remove(line)}
                                    onSave={(amount) => actions.save(line, amount, () => setEditing(null))} />;
                            })}
                        </ul>
                    </div>;
                })}
            </section>
            <section className="space-y-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-sm font-semibold">この月の自動取引</h3>
                    <Link to="/db/definitions" className="text-xs text-[var(--studio-accent)] hover:underline">収支・配分の定義で変更</Link>
                </div>
                <ScheduledTable items={row.scheduled} accountId={row.accountId} context={context} />
            </section>
        </div>
    </Overlay>;
}

/** An earmark's monthly saving from each funding account; it is not an account itself. */
export function EarmarkOverlay({ earmark, need, context, onClose }: { earmark: EarmarkRow; need?: number; context: OverlayContext; onClose: () => void }) {
    const actions = useLineActions(context);
    const [editing, setEditing] = useState<string | null>(null);
    const money = (amount: number) => formatCurrency(amount, context.currency);
    return <Overlay title={`取り置き「${earmark.name}」`} busy={actions.mutation.busy} onClose={onClose}>
        <div className="space-y-4">
            <p className="text-xs text-[var(--studio-text-muted)]">取り置きは口座ではありません。資金元の口座の残高のうち、この用途に確保する額です。予算では配分として数えます。保存すると取り置きの月額積立計画にも反映されます。</p>
            <Feedback error={actions.mutation.error} message={actions.mutation.message} />
            <p className="text-sm tabular-nums">月の予算 {money(earmark.budget)} ／ 確保額 {money(earmark.held)}{need != null && <span className={need > earmark.budget ? 'ml-2 text-[var(--studio-warning)]' : 'ml-2 text-[var(--studio-text-muted)]'}>必要額 {money(need)}</span>}</p>
            <ul className="divide-y divide-[var(--studio-border)] rounded-md border border-[var(--studio-border)] px-4">
                {earmark.lines.map((line, index) => {
                    const key = lineKey(line, index);
                    return <LineItem key={key} line={line} label={line.account_name ? `${line.account_name} から` : '資金元の口座なし'} currency={context.currency} editing={editing === key} disabled={actions.disabled}
                        onEdit={() => setEditing(key)} onCancel={() => setEditing(null)} onRemove={() => actions.remove(line)}
                        onSave={(amount) => actions.save(line, amount, () => setEditing(null))} />;
                })}
            </ul>
            <Link to="/db/earmarks" className="text-xs text-[var(--studio-accent)] hover:underline">取り置きの画面で開く</Link>
        </div>
    </Overlay>;
}
