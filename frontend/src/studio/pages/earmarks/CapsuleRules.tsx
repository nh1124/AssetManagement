import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { createCapsuleRule, deleteCapsuleRule, getCapsuleRules, updateCapsuleRule } from '../../../api';
import type { Capsule, CapsuleRule, CapsuleTriggerKind } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { ActiveSwitch, Choice, DataTable, EditableRow, EditorActions, Feedback, Field, RowTitle } from '../db/Database';
import { buttonClass, inputClass, loadAccounts, useMutation } from '../db/forms';

const TRIGGERS: Record<CapsuleTriggerKind, string> = { Income: '収入', Expense: '支出', CreditExpense: 'カード・負債での支出', Transfer: '振替' };
const loadRules = () => getCapsuleRules();
type RuleInput = Parameters<typeof createCapsuleRule>[0];

function RuleEditor({ rule, capsule, currency, accounts, busy, onSave, onCancel, onDelete, error }: {
    rule: CapsuleRule | null; onDelete?: () => void; error: string;
    capsule: Capsule; currency: string; accounts: Array<{ id: number; name: string; is_active?: boolean }>;
    busy: boolean; onSave: (payload: RuleInput) => void; onCancel: () => void;
}) {
    const formId = useId();
    const [trigger, setTrigger] = useState<CapsuleTriggerKind>(rule?.trigger_type ?? 'Income');
    const [category, setCategory] = useState(rule?.trigger_category ?? '');
    const [description, setDescription] = useState(rule?.trigger_description ?? '');
    const [triggerAccount, setTriggerAccount] = useState<number | null>(rule?.trigger_account_id ?? null);
    const [sourceMode, setSourceMode] = useState<CapsuleRule['source_mode']>(rule?.source_mode ?? 'transaction_account');
    const [source, setSource] = useState<number | null>(rule?.source_account_id ?? null);
    const [destination, setDestination] = useState<number | null>(rule?.destination_account_id ?? null);
    const [amountType, setAmountType] = useState<CapsuleRule['amount_type']>(rule?.amount_type ?? 'fixed');
    const [amount, setAmount] = useState(String(rule?.amount_value ?? 0));
    const [active, setActive] = useState(rule?.is_active ?? true);
    const destinations = (capsule.funding_sources ?? []).map((row) => ({ id: row.account_id, name: row.account_name || accounts.find((account) => account.id === row.account_id)?.name || `口座 #${row.account_id}` }));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || (sourceMode === 'fixed_account' && source === null)) return;
        onSave({ capsule_id: capsule.id, trigger_type: trigger, trigger_account_id: triggerAccount, trigger_category: category.trim() || null, trigger_description: description.trim() || null, source_mode: sourceMode, source_account_id: sourceMode === 'fixed_account' ? source : null, destination_account_id: destination, amount_type: amountType, amount_value: Number(amount), is_active: active });
    };
    return <Overlay title={rule ? `「${capsule.name}」の規則を編集` : `「${capsule.name}」の新しい規則`} busy={busy} onClose={onCancel}
        headerAction={<div className="flex items-center gap-2 text-sm"><ActiveSwitch name="規則の有効" active={active} disabled={busy} onToggle={() => setActive(!active)} /></div>}>
        <Feedback error={error} />
        <form id={formId} onSubmit={submit} className="space-y-4">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="発火する取引"><select value={trigger} onChange={(event) => setTrigger(event.target.value as CapsuleTriggerKind)} className={inputClass}>{Object.entries(TRIGGERS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Choice label="口座・科目（任意）" value={triggerAccount} options={accounts} onChange={setTriggerAccount} />
            <Field label="分類の条件（任意）"><input value={category} onChange={(event) => setCategory(event.target.value)} className={inputClass} /></Field>
            <Field label="摘要の条件（任意）"><input value={description} onChange={(event) => setDescription(event.target.value)} className={inputClass} /></Field>
            <Field label="資金元"><select value={sourceMode} onChange={(event) => setSourceMode(event.target.value as CapsuleRule['source_mode'])} className={inputClass}><option value="transaction_account">発火した取引の口座</option><option value="fixed_account">指定した口座</option></select></Field>
            <Choice label="資金元の口座" value={sourceMode === 'fixed_account' ? source : null} options={accounts.filter((row) => row.is_active !== false)} onChange={setSource} required={sourceMode === 'fixed_account'} disabled={sourceMode !== 'fixed_account'} />
            <Choice label="入金先（未設定なら資金計画に配分）" value={destination} options={destinations} onChange={setDestination} />
            <Field label="金額の指定"><select value={amountType} onChange={(event) => setAmountType(event.target.value as CapsuleRule['amount_type'])} className={inputClass}><option value="fixed">固定額</option><option value="percentage">取引額の割合</option></select></Field>
            <Field label={amountType === 'fixed' ? `金額（${currency}）` : '割合（%）'}><input required type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} onDelete={onDelete} />
        </fieldset>
    </form></Overlay>;
}

export default function CapsuleRules({ capsule, currency, disabled, onBusy }: { capsule: Capsule; currency: string; disabled: boolean; onBusy: (busy: boolean) => void }) {
    const confirm = useConfirm();
    const rules = useResource(loadRules);
    const accounts = useResource(loadAccounts);
    const mutation = useMutation();
    const [editor, setEditor] = useState<{ rule: CapsuleRule | null } | null>(null);
    const locked = disabled || mutation.busy || rules.loading || accounts.loading || Boolean(rules.error) || Boolean(accounts.error);
    const run = (action: () => Promise<unknown>, message: string, close = false) => {
        if (locked) return;
        // Keep deletion and funding edits locked while a rule write is in flight.
        onBusy(true);
        void mutation.run(action, message, () => { if (close) setEditor(null); rules.reload(); }).finally(() => onBusy(false));
    };
    const rows = rules.data?.filter((row) => row.capsule_id === capsule.id);
    const name = (id: number | null | undefined, fallback?: string | null) => accounts.data?.find((row) => row.id === id)?.name || fallback || (id == null ? '未設定' : `口座 #${id}`);
    return <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2"><button type="button" disabled={locked || editor !== null} onClick={() => setEditor({ rule: null })} className={buttonClass}>新しい規則</button></div></div>
        <Feedback loading={rules.loading || accounts.loading} error={rules.error || accounts.error} />
        <Feedback error={mutation.error} message={mutation.message} />
        {editor && accounts.data && <RuleEditor key={editor.rule?.id ?? 'new'} rule={editor.rule} capsule={capsule} currency={currency} accounts={accounts.data} busy={locked} error={mutation.error}
            onCancel={() => setEditor(null)} onSave={(payload) => run(() => editor.rule ? updateCapsuleRule(editor.rule.id, payload) : createCapsuleRule(payload), '規則を保存しました。', true)}
            onDelete={editor.rule ? async () => {
                if (await confirm(`「${capsule.name}」の規則を削除しますか？既存の取引・残高はそのまま残ります。`, '削除する')) {
                    run(() => deleteCapsuleRule(editor.rule!.id), '規則を削除しました。', true);
                }
            } : undefined} />}
        {rows && <DataTable columns={['発火条件', '資金元', '金額', '入金先', '状態']}>
            {rows.length ? rows.map((row) => <EditableRow key={row.id} disabled={locked || editor !== null} onEdit={() => setEditor({ rule: row })}>
                <RowTitle name={`${TRIGGERS[row.trigger_type]}の規則`} disabled={locked || editor !== null} onEdit={() => setEditor({ rule: row })}>{TRIGGERS[row.trigger_type]}{row.trigger_account_id != null && <p className="text-xs">口座・科目：{name(row.trigger_account_id)}</p>}{row.trigger_category && <p className="text-xs">分類：{row.trigger_category}</p>}{row.trigger_description && <p className="text-xs">摘要：{row.trigger_description}</p>}</RowTitle>
                <td className="px-5 py-3">{row.source_mode === 'transaction_account' ? '発火した取引の口座' : name(row.source_account_id, row.source_account_name)}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.amount_type === 'percentage' ? `${row.amount_value}%` : formatCurrency(row.amount_value, currency)}</td>
                <td className="px-5 py-3">{row.destination_account_id == null ? '資金計画に配分' : name(row.destination_account_id)}</td>
                <td className="px-5 py-3">{row.is_active ? '有効' : '無効'}</td>
            </EditableRow>) : <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">規則はありません。</td></tr>}
        </DataTable>}
    </section>;
}
