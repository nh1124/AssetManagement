import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { clientToday, useTimezone } from '../../datetime';
import { useCallback, useId, useState, type FormEvent } from 'react';
import { createMonthlyPlanLines, deleteMonthlyPlanLine, getBudgetSummary, updateMonthlyPlanLines, type MonthlyPlanLinePayload } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { MonthlyPlanLine, MonthlyPlanLineType } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, EditorActions, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, useMutation } from '../db/forms';
import MonthCopy from './MonthCopy';
import MonthPicker from '../ledger/MonthPicker';

// budget_plan_service returns plan_lines and plan_id, not the legacy budget model.
export interface BudgetSummary {
    period: string;
    plan_id: number | null;
    feasibility_status: 'ok' | 'warning' | 'shortfall';
    plan_lines: MonthlyPlanLine[];
}

const BLOCKS: Array<{ type: MonthlyPlanLineType; label: string }> = [
    { type: 'income', label: '収入' }, { type: 'expense', label: '支出' },
    { type: 'allocation', label: '配分' }, { type: 'debt_payment', label: '返済' },
    { type: 'borrowing', label: '借入' }, { type: 'drawdown', label: '取り崩し' },
];
const STATES = { synced: '定義と一致', missing: '月の計画は未保存', diff: '定義との差あり' };
const lineName = (line: MonthlyPlanLine) => line.target_name || line.name || line.account_name || '名称未設定';

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
    return <form id={formId} onSubmit={submit} className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        {line.target_type === 'capsule' && <p className="text-xs text-[var(--studio-warning)]">取り置きの月額積立計画にも反映されます。</p>}
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label={`月末計画（${currency}）`}><input required type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}

function MonthlyBudget({ period, currency, clientName, onBusy }: { period: string; currency: string; clientName?: string; onBusy: (busy: boolean) => void }) {
    const confirm = useConfirm();
    const load = useCallback((): Promise<BudgetSummary> => getBudgetSummary(period), [period]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [copyBusy, setCopyBusy] = useState(false);
    const [editing, setEditing] = useState<MonthlyPlanLine | null>(null);
    const disabled = resource.loading || Boolean(resource.error) || mutation.busy || copyBusy || !clientName;
    const save = async (amount: number) => {
        if (disabled || !editing || !resource.data) return;
        const name = lineName(editing);
        const effect = editing.target_type === 'capsule' ? '\n取り置きの月額積立計画にも反映されます。' : '';
        if (!(await confirm(`「${clientName}」の${period}「${name}」を ${formatCurrency(editing.amount, currency)} → ${formatCurrency(amount, currency)}（${currency}）に変更しますか？${effect}`, '変更する'))) return;
        // Send only writable fields; summary actuals and synchronization state are server-owned.
        const payload: MonthlyPlanLinePayload = {
            target_period: editing.target_period, line_type: editing.line_type, target_type: editing.target_type,
            target_id: editing.target_id, account_id: editing.account_id, source_account_id: editing.source_account_id,
            name: editing.name || name, amount, source: editing.source || 'manual', source_kind: editing.source_kind || 'manual',
            manual_override: true, cash_treatment: editing.cash_treatment || 'auto', is_active: editing.is_active ?? true,
            plan_id: resource.data.plan_id,
        };
        const id = editing.id;
        void mutation.run(() => id == null ? createMonthlyPlanLines([payload]) : updateMonthlyPlanLines([{ ...payload, id }]), '計画額を保存しました。', () => {
            setEditing(null);
            resource.reload();
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
            resource.reload();
        });
    };
    return <div className="space-y-4">
        <Feedback loading={resource.loading} error={resource.error} />
        <Feedback error={mutation.error} message={mutation.message} />
        <MonthCopy period={period} disabled={disabled || editing !== null} clientName={clientName} onBusy={(busy) => { setCopyBusy(busy); onBusy(busy); }} onCopied={resource.reload} />
        {editing && <Overlay title={`「${lineName(editing)}」の金額を編集`} onClose={() => setEditing(null)} footer={editing.id != null
            ? <button type="button" disabled={disabled} onClick={() => remove(editing)} className={`${buttonClass} mr-auto text-[var(--studio-danger)]`}>削除</button>
            : <span className="mr-auto text-xs text-[var(--studio-text-muted)]">未保存のため削除不可</span>}><Feedback error={mutation.error} /><AmountEditor key={editing.id ?? lineName(editing)} line={editing} currency={currency} busy={disabled} onSave={save} onCancel={() => setEditing(null)} /></Overlay>}
        {resource.data && <>
            <DataTable columns={['計画項目', '種別', '月末計画', '照合済み実績', '月末計画との差', '状態']}>
                {resource.data.plan_lines.length ? BLOCKS.map((block) => {
                    const lines = resource.data?.plan_lines.filter((line) => line.line_type === block.type) ?? [];
                    return lines.map((line, index) => <tr key={line.id ?? `${block.type}:${index}`} onClick={() => { if (!disabled && editing === null) setEditing(line); }} className={disabled || editing !== null ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]'}>
                        <th scope="row" className="px-5 py-3 font-medium"><button type="button" disabled={disabled || editing !== null} aria-label={`${lineName(line)}の金額を編集`} aria-haspopup="dialog" onClick={(event) => { event.stopPropagation(); setEditing(line); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{lineName(line)}</button>{line.account_name && <span className="mt-1 block text-xs font-normal text-[var(--studio-text-muted)]">{line.account_name}</span>}</th>
                        <td className="whitespace-nowrap px-5 py-3">{block.label}</td>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(line.amount, currency)}</td>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{line.actual == null ? '—' : formatCurrency(line.actual, currency)}</td>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{line.variance == null ? '—' : formatCurrency(line.variance, currency)}</td>
                        <td className="px-5 py-3 text-xs text-[var(--studio-text-muted)]">{line.sync_status ? STATES[line.sync_status] : line.suggested_status ? STATES[line.suggested_status] : '—'}</td>
                    </tr>);
                }) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">この月の予算行はありません。</td></tr>}
            </DataTable>
        </>}
    </div>;
}

export default function Budget() {
    const { clientId, currentClient } = useClient();
    const timezone = useTimezone();
    const [busy, setBusy] = useState(false);
    const [periodEdit, setPeriod] = useState<string | null>(null);
    const period = periodEdit ?? clientToday(timezone).slice(0, 7);
    const currency = currentClient?.general_settings?.currency || 'JPY';
    return <section className="space-y-4">
        <MonthPicker value={period} onChange={setPeriod} disabled={busy} />
        <MonthlyBudget key={`${clientId}:${period}:${currency}`} period={period} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} onBusy={setBusy} />
    </section>;
}
