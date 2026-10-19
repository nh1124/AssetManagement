import { useCallback, useState, type FormEvent, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { createMonthlyPlanLines, deleteMonthlyPlanLine, updateMonthlyPlanLines, type MonthlyPlanLinePayload } from '../../../api';
import { addPlanRecord, amendPlanRecord, deletePlanRecord, getAccountMonth, type AccountMonth, type PlanRecord, type PlanSection } from '../../../api/plan';
import type { MonthlyPlanLine, ScheduledTransaction } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
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

const muted = 'text-xs text-[var(--studio-text-muted)]';
const Tag = ({ children }: { children: ReactNode }) => <span className="ml-2 whitespace-nowrap rounded bg-[var(--studio-bg)] px-1.5 py-0.5 text-[11px] text-[var(--studio-text-muted)]">{children}</span>;
const lineKey = (line: MonthlyPlanLine, index: number) => line.id != null ? `id:${line.id}` : `${line.source}:${line.target_type}:${line.target_id ?? ''}:${line.account_id ?? ''}:${index}`;
const validAmount = (text: string) => text.trim() !== '' && Number.isFinite(Number(text)) && Number(text) >= 0;

function ScheduledTable({ items, accountId, context }: { items: ScheduledTransaction[]; accountId: number | null; context: OverlayContext }) {
    const money = (amount: number) => formatCurrency(amount, context.currency);
    if (!items.length) return <p className="text-sm text-[var(--studio-text-muted)]">この月の自動取引はありません。</p>;
    return <div className="overflow-x-auto"><table className="w-full text-left text-sm">
        <thead className={muted}><tr>{['予定日', '自動取引', '種別', '相手', '金額', '記帳'].map((label) => <th key={label} scope="col" className="whitespace-nowrap py-1 pr-4 font-medium">{label}</th>)}</tr></thead>
        <tbody className="divide-y divide-[var(--studio-border)]">
            {items.map((item, index) => {
                const other = item.account_id === accountId ? item.counter_account_id : item.account_id;
                return <tr key={`${item.kind}:${item.entry_id ?? item.product_id}:${index}`}>
                    <td className="whitespace-nowrap py-2 pr-4 tabular-nums">{item.date.slice(5).replace('-', '/')}</td>
                    <th scope="row" className="py-2 pr-4 font-normal">{item.name}</th>
                    <td className="whitespace-nowrap py-2 pr-4">{item.kind === 'depreciation' ? '減価' : item.line_type ? TYPE_LABELS[item.line_type] : '—'}</td>
                    <td className="py-2 pr-4 text-[var(--studio-text-muted)]">{context.accountName(other)}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-right tabular-nums">{money(item.amount)}</td>
                    <td className="whitespace-nowrap py-2 text-xs">自動{item.posted ? '・記帳済み' : ''}{item.kind === 'automatic_transaction' && !item.in_budget ? '（予算外）' : ''}</td>
                </tr>;
            })}
        </tbody>
    </table></div>;
}

/** Where a record that is not the user's is changed. */
function ChangedAt({ origin }: { origin: PlanRecord['origin'] }) {
    if (origin === 'goal') return <Link to="/goals" className="text-xs text-[var(--studio-accent)] hover:underline">ゴールで変更</Link>;
    if (origin === 'registry') return <Link to="/db/auto-transactions" className="text-xs text-[var(--studio-accent)] hover:underline">自動取引で変更</Link>;
    return <span className={muted}>レコードを追加すると、見込みの代わりにその額を使います</span>;
}

function RecordForm({ label, name, amount, placeholder, currency, disabled, onSubmit, onCancel }: {
    label: string; name: string; amount: string; placeholder: string; currency: string; disabled: boolean;
    onSubmit: (amount: number, name: string) => void; onCancel: () => void;
}) {
    const [values, setValues] = useState({ name, amount });
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!disabled && validAmount(values.amount)) onSubmit(Number(values.amount), values.name.trim());
    };
    return <form onSubmit={submit} className="flex flex-wrap items-center gap-2 py-2">
        <div className="min-w-0 flex-1"><input aria-label="レコードの名前" placeholder={placeholder} value={values.name} onChange={(event) => setValues({ ...values, name: event.target.value })} className={inputClass} /></div>
        <div className="w-36"><input autoFocus aria-label={`${label}（${currency}）`} type="number" min="0" step="0.01" value={values.amount} onChange={(event) => setValues({ ...values, amount: event.target.value })} className={inputClass} /></div>
        <button type="submit" disabled={disabled || !validAmount(values.amount)} className={primaryClass}>保存</button>
        <button type="button" onClick={onCancel} className={buttonClass}>取消</button>
    </form>;
}

/**
 * An account's month as records: each section lists what makes its budget -- the goal, automatic
 * transactions, a card estimate, the user -- and the user adds or changes their own. The server
 * decides which records exist and which are the user's.
 */
function AccountRecords({ accountId, title, context, onClose }: { accountId: number; title: string; context: OverlayContext; onClose: () => void }) {
    const load = useCallback(() => getAccountMonth(context.period, accountId), [context.period, accountId]);
    const resource = useResource(load);
    const [latest, setLatest] = useState<AccountMonth | null>(null);
    const [editing, setEditing] = useState<string | null>(null);
    const confirm = useConfirm();
    const mutation = useMutation();
    const view = latest ?? resource.data;
    const money = (amount: number) => formatCurrency(amount, context.currency);
    const disabled = mutation.busy || !context.clientName;
    const where = `「${context.clientName}」の${context.period}「${title}」`;
    const write = async (question: string, verb: string, action: () => Promise<AccountMonth>, done: string) => {
        if (disabled || !(await confirm(question, verb))) return;
        void mutation.run(async () => { setLatest(await action()); }, done, () => { setEditing(null); context.onChanged(); });
    };
    const add = (section: PlanSection, amount: number, name: string) => write(
        `${where}の${section.label}に ${money(amount)}（${context.currency}）のレコードを追加しますか？`, '追加する',
        () => addPlanRecord({ period: context.period, account_id: accountId, section: section.key, amount, name: name || undefined }), 'レコードを追加しました。');
    const amend = (section: PlanSection, record: PlanRecord, amount: number, name: string) => write(
        `${where}の${section.label}「${record.name}」を ${money(record.amount)} → ${money(amount)}（${context.currency}）に変更しますか？`, '変更する',
        () => amendPlanRecord(record.id as number, { amount, name: name || undefined }), 'レコードを変更しました。');
    const remove = (section: PlanSection, record: PlanRecord) => write(
        `${where}の${section.label}「${record.name}」を削除しますか？\n削除は取り消せません。`, '削除する',
        () => deletePlanRecord(record.id as number), 'レコードを削除しました。');
    const kind = view?.account.kind;
    const noun = kind === 'income' || kind === 'expense' ? '科目' : '口座';
    return <Overlay title={title} busy={mutation.busy} onClose={onClose}>
        <div className="space-y-6">
            <p className={muted}>{kind ? `${KIND_LABELS[kind]}の${noun} ・ ` : ''}{context.period}</p>
            <Feedback loading={resource.loading} error={mutation.error || resource.error} message={mutation.message} />
            {view?.sections.map((section) => {
                const adding = editing === `add:${section.key}`;
                return <section key={section.key} className="space-y-2">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <h3 className="text-sm font-semibold">{section.label}</h3>
                        <span className={`${muted} tabular-nums`}>予算 {money(section.total)} ／ 実績 {money(section.actual)}</span>
                    </div>
                    {section.mismatch && kind && <p className="text-xs text-[var(--studio-warning)]">{KIND_LABELS[kind]}の{noun}に{section.label}の予算があります。自動取引の種別か口座を確認してください。</p>}
                    <ul className="divide-y divide-[var(--studio-border)] rounded-md border border-[var(--studio-border)] px-4">
                        {section.records.map((record, index) => {
                            const key = `record:${record.id ?? `${record.origin}:${index}`}`;
                            return <li key={key}>{editing === key
                                ? <RecordForm label={section.label} name={record.name} amount={String(record.amount)} placeholder={title} currency={context.currency} disabled={disabled}
                                    onSubmit={(amount, name) => void amend(section, record, amount, name)} onCancel={() => setEditing(null)} />
                                : <div className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                                    <span className="min-w-0 flex-1 text-sm">{record.name}<Tag>{record.origin_label}</Tag></span>
                                    <span className="w-28 text-right tabular-nums">{money(record.amount)}</span>
                                    {record.editable
                                        ? <>
                                            <button type="button" disabled={disabled} onClick={() => setEditing(key)} className={buttonClass}>編集</button>
                                            <button type="button" disabled={disabled} onClick={() => void remove(section, record)} className={`${buttonClass} text-[var(--studio-danger)]`}>削除</button>
                                        </>
                                        : <ChangedAt origin={record.origin} />}
                                    {record.card_estimate != null && <p className={`basis-full ${muted}`}>カード請求の見込み {money(record.card_estimate)} の代わりにこの額を使います。</p>}
                                </div>}</li>;
                        })}
                        {!section.records.length && !adding && <li className={`py-2 ${muted}`}>レコードはありません。</li>}
                        {adding && <li><RecordForm label={section.label} name="" amount="" placeholder={title} currency={context.currency} disabled={disabled}
                            onSubmit={(amount, name) => void add(section, amount, name)} onCancel={() => setEditing(null)} /></li>}
                    </ul>
                    {section.can_add && !adding && <button type="button" disabled={disabled} onClick={() => setEditing(`add:${section.key}`)} className={buttonClass}>＋ レコードを追加</button>}
                </section>;
            })}
            {view && view.earmarks.length > 0 && <section className="space-y-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-sm font-semibold">この口座の取り置き<span className={`ml-2 font-normal ${muted}`}>予算は取り置きの行で決めます</span></h3>
                    <Link to="/db/earmarks" className="text-xs text-[var(--studio-accent)] hover:underline">取り置きで変更</Link>
                </div>
                <ul className="divide-y divide-[var(--studio-border)] rounded-md border border-[var(--studio-border)] px-4">
                    {view.earmarks.map((earmark) => <li key={earmark.capsule_id ?? earmark.name} className="flex items-center gap-3 py-2">
                        <span className="min-w-0 flex-1 text-sm">{earmark.name}{earmark.goal && <Tag>ゴール</Tag>}</span>
                        <span className="w-28 text-right tabular-nums">{money(earmark.amount)}</span>
                    </li>)}
                </ul>
            </section>}
            {view && <section className="space-y-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-sm font-semibold">この月の自動取引</h3>
                    <Link to="/db/auto-transactions" className="text-xs text-[var(--studio-accent)] hover:underline">自動取引で変更</Link>
                </div>
                <ScheduledTable items={view.scheduled} accountId={accountId} context={context} />
            </section>}
        </div>
    </Overlay>;
}

/** Saving and deleting one budget row of an earmark or of a row without an account. */
function useLineActions({ period, currency, clientName, planId, onChanged }: OverlayContext) {
    const confirm = useConfirm();
    const mutation = useMutation();
    const save = async (line: MonthlyPlanLine, amount: number, done: () => void) => {
        if (mutation.busy || !clientName) return;
        const name = lineName(line);
        const effect = line.target_type === 'capsule' ? '\n取り置きの月額積立計画にも反映されます。' : '';
        const before = line.id == null && !line.budget_amount ? '未設定' : formatCurrency(line.budget_amount ?? 0, currency);
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
        if (!(await confirm(`「${clientName}」の${period}「${lineName(line)}」の予算行を削除しますか？\n削除は取り消せません。`, '削除する'))) return;
        void mutation.run(() => deleteMonthlyPlanLine(id), '予算行を削除しました。', onChanged);
    };
    return { mutation, save, remove, disabled: mutation.busy || !clientName };
}

function LineItem({ line, label, currency, editing, disabled, onEdit, onCancel, onSave, onRemove }: {
    line: MonthlyPlanLine; label: string; currency: string; editing: boolean; disabled: boolean;
    onEdit: () => void; onCancel: () => void; onSave: (amount: number) => void; onRemove: () => void;
}) {
    const [amount, setAmount] = useState(String(line.budget_amount ?? 0));
    const unsaved = line.id == null && !line.budget_amount;
    // A goal earmark's rows come from the goal's plan; they change there.
    const fromGoal = line.source === 'goal' || line.source_kind === 'goal';
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!disabled && validAmount(amount)) onSave(Number(amount));
    };
    return <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2">
        <span className="min-w-0 flex-1 text-sm">{label}<Tag>{lineOrigin(line)}</Tag></span>
        {editing
            ? <form onSubmit={submit} className="flex items-center gap-2">
                <input autoFocus aria-label={`${label}（${currency}）`} type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} className={`${inputClass} w-36`} />
                <button type="submit" disabled={disabled} className={primaryClass}>保存</button>
                <button type="button" onClick={onCancel} className={buttonClass}>取消</button>
            </form>
            : <>
                <span className={`w-28 text-right tabular-nums ${unsaved ? 'text-[var(--studio-text-faint)]' : ''}`}>{unsaved ? '未設定' : formatCurrency(line.budget_amount ?? 0, currency)}</span>
                {fromGoal
                    ? <Link to="/goals" className="text-xs text-[var(--studio-accent)] hover:underline">ゴールで変更</Link>
                    : <>
                        <button type="button" disabled={disabled} onClick={onEdit} className={buttonClass}>編集</button>
                        {line.id != null && <button type="button" disabled={disabled} onClick={onRemove} className={`${buttonClass} text-[var(--studio-danger)]`}>削除</button>}
                    </>}
            </>}
    </li>;
}

/** Budget rows that name no account: kept from before accounts were required, edited one by one. */
function UnassignedLines({ row, context, onClose }: { row: AccountRow; context: OverlayContext; onClose: () => void }) {
    const actions = useLineActions(context);
    const [editing, setEditing] = useState<string | null>(null);
    return <Overlay title={row.name} busy={actions.mutation.busy} onClose={onClose}>
        <div className="space-y-4">
            <p className={muted}>口座未指定の予算行 ・ {context.period}</p>
            <Feedback error={actions.mutation.error} message={actions.mutation.message} />
            <ul className="divide-y divide-[var(--studio-border)] rounded-md border border-[var(--studio-border)] px-4">
                {row.cells.flatMap((cell) => cell.lines.map((line, index) => {
                    const key = `${cell.type}:${lineKey(line, index)}`;
                    return <LineItem key={key} line={line} label={`${TYPE_LABELS[cell.type]}「${lineName(line)}」`} currency={context.currency} editing={editing === key} disabled={actions.disabled}
                        onEdit={() => setEditing(key)} onCancel={() => setEditing(null)} onRemove={() => actions.remove(line)}
                        onSave={(amount) => actions.save(line, amount, () => setEditing(null))} />;
                }))}
            </ul>
        </div>
    </Overlay>;
}

/** An account's or subject's month: its records by section and its automatic transactions. */
export function AccountOverlay({ row, context, onClose }: { row: AccountRow; context: OverlayContext; onClose: () => void }) {
    return row.accountId == null
        ? <UnassignedLines row={row} context={context} onClose={onClose} />
        : <AccountRecords accountId={row.accountId} title={row.name} context={context} onClose={onClose} />;
}

/** An earmark's monthly saving from each funding account; it is not an account itself. */
export function EarmarkOverlay({ earmark, context, onClose }: { earmark: EarmarkRow; context: OverlayContext; onClose: () => void }) {
    const actions = useLineActions(context);
    const [editing, setEditing] = useState<string | null>(null);
    const money = (amount: number) => formatCurrency(amount, context.currency);
    return <Overlay title={`取り置き「${earmark.name}」`} busy={actions.mutation.busy} onClose={onClose}>
        <div className="space-y-4">
            <p className={muted}>取り置きは口座ではありません。資金元の口座の残高のうち、この用途に確保する額です。予算では配分として数えます。保存すると取り置きの月額積立計画にも反映されます。</p>
            {earmark.goal && <p className={muted}><Tag>ゴール</Tag> ゴールのライフイベントのために作った取り置きです。月額はゴールから計画を作成すると決まり、ゴールを変更するときに削除できます。</p>}
            <Feedback error={actions.mutation.error} message={actions.mutation.message} />
            <p className="text-sm tabular-nums">月の予算 {money(earmark.budget)} ／ 確保額 {money(earmark.held)}</p>
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
