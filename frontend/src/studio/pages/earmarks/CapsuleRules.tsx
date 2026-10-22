import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { createCapsuleRule, deleteCapsuleRule, getCapsuleRules, updateCapsuleRule } from '../../../api';
import type { Capsule, CapsuleRule, CapsuleTriggerKind } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { ActiveSwitch, Choice, DataTable, EditableRow, EditorActions, Feedback, Field, RowTitle } from '../db/Database';
import { buttonClass, inputClass, loadAccounts, useMutation } from '../db/forms';
import { labels, tr } from '../../i18n';

const TRIGGERS = labels<CapsuleTriggerKind>({ Income: ['収入', 'Income'], Expense: ['支出', 'Expense'], CreditExpense: ['カード・負債での支出', 'Spending on a card or liability'], Transfer: ['振替', 'Transfer'] });
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
    const destinations = (capsule.funding_sources ?? []).map((row) => ({ id: row.account_id, name: row.account_name || accounts.find((account) => account.id === row.account_id)?.name || tr(`口座 #${row.account_id}`, `Account #${row.account_id}`) }));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || (sourceMode === 'fixed_account' && source === null)) return;
        onSave({ capsule_id: capsule.id, trigger_type: trigger, trigger_account_id: triggerAccount, trigger_category: category.trim() || null, trigger_description: description.trim() || null, source_mode: sourceMode, source_account_id: sourceMode === 'fixed_account' ? source : null, destination_account_id: destination, amount_type: amountType, amount_value: Number(amount), is_active: active });
    };
    return <Overlay title={rule ? tr(`「${capsule.name}」の規則を編集`, `Edit a rule of “${capsule.name}”`) : tr(`「${capsule.name}」の新しい規則`, `New rule for “${capsule.name}”`)} busy={busy} onClose={onCancel}
        headerAction={<div className="flex items-center gap-2 text-sm"><ActiveSwitch name={tr('規則の有効', 'Rule')} active={active} disabled={busy} onToggle={() => setActive(!active)} /></div>}>
        <Feedback error={error} />
        <form id={formId} onSubmit={submit} className="space-y-4">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label={tr('発火する取引', 'Triggered by')}><select value={trigger} onChange={(event) => setTrigger(event.target.value as CapsuleTriggerKind)} className={inputClass}>{Object.entries(TRIGGERS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Choice label={tr('口座・科目（任意）', 'Account (optional)')} value={triggerAccount} options={accounts} onChange={setTriggerAccount} />
            <Field label={tr('分類の条件（任意）', 'Category condition (optional)')}><input value={category} onChange={(event) => setCategory(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('摘要の条件（任意）', 'Description condition (optional)')}><input value={description} onChange={(event) => setDescription(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('資金元', 'Funded from')}><select value={sourceMode} onChange={(event) => setSourceMode(event.target.value as CapsuleRule['source_mode'])} className={inputClass}><option value="transaction_account">{tr('発火した取引の口座', 'The triggering transaction’s account')}</option><option value="fixed_account">{tr('指定した口座', 'A chosen account')}</option></select></Field>
            <Choice label={tr('資金元の口座', 'Funding account')} value={sourceMode === 'fixed_account' ? source : null} options={accounts.filter((row) => row.is_active !== false)} onChange={setSource} required={sourceMode === 'fixed_account'} disabled={sourceMode !== 'fixed_account'} />
            <Choice label={tr('入金先（未設定なら資金計画に配分）', 'Deposit to (funding plan when not set)')} value={destination} options={destinations} onChange={setDestination} />
            <Field label={tr('金額の指定', 'Amount')}><select value={amountType} onChange={(event) => setAmountType(event.target.value as CapsuleRule['amount_type'])} className={inputClass}><option value="fixed">{tr('固定額', 'Fixed amount')}</option><option value="percentage">{tr('取引額の割合', 'Share of the transaction')}</option></select></Field>
            <Field label={amountType === 'fixed' ? tr(`金額（${currency}）`, `Amount (${currency})`) : tr('割合（%）', 'Share (%)')}><input required type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
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
    const name = (id: number | null | undefined, fallback?: string | null) => accounts.data?.find((row) => row.id === id)?.name || fallback || (id == null ? tr('未設定', 'Not set') : tr(`口座 #${id}`, `Account #${id}`));
    return <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2"><button type="button" disabled={locked || editor !== null} onClick={() => setEditor({ rule: null })} className={buttonClass}>{tr('新しい規則', 'New rule')}</button></div></div>
        <Feedback loading={rules.loading || accounts.loading} error={rules.error || accounts.error} />
        <Feedback error={mutation.error} message={mutation.message} />
        {editor && accounts.data && <RuleEditor key={editor.rule?.id ?? 'new'} rule={editor.rule} capsule={capsule} currency={currency} accounts={accounts.data} busy={locked} error={mutation.error}
            onCancel={() => setEditor(null)} onSave={(payload) => run(() => editor.rule ? updateCapsuleRule(editor.rule.id, payload) : createCapsuleRule(payload), tr('規則を保存しました。', 'Rule saved.'), true)}
            onDelete={editor.rule ? async () => {
                if (await confirm(tr(`「${capsule.name}」の規則を削除しますか？既存の取引・残高はそのまま残ります。`, `Delete this rule of “${capsule.name}”? Existing transactions and balances stay as they are.`), tr('削除する', 'Delete'))) {
                    run(() => deleteCapsuleRule(editor.rule!.id), tr('規則を削除しました。', 'Rule deleted.'), true);
                }
            } : undefined} />}
        {rows && <DataTable columns={[tr('発火条件', 'Trigger'), tr('資金元', 'Funded from'), tr('金額', 'Amount'), tr('入金先', 'Deposit to'), tr('状態', 'Status')]}>
            {rows.length ? rows.map((row) => <EditableRow key={row.id} disabled={locked || editor !== null} onEdit={() => setEditor({ rule: row })}>
                <RowTitle name={tr(`${TRIGGERS[row.trigger_type]}の規則`, `${TRIGGERS[row.trigger_type]} rule`)} disabled={locked || editor !== null} onEdit={() => setEditor({ rule: row })}>{TRIGGERS[row.trigger_type]}{row.trigger_account_id != null && <p className="text-xs">{tr('口座・科目：', 'Account: ')}{name(row.trigger_account_id)}</p>}{row.trigger_category && <p className="text-xs">{tr('分類：', 'Category: ')}{row.trigger_category}</p>}{row.trigger_description && <p className="text-xs">{tr('摘要：', 'Description: ')}{row.trigger_description}</p>}</RowTitle>
                <td className="px-5 py-3">{row.source_mode === 'transaction_account' ? tr('発火した取引の口座', 'The triggering transaction’s account') : name(row.source_account_id, row.source_account_name)}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.amount_type === 'percentage' ? `${row.amount_value}%` : formatCurrency(row.amount_value, currency)}</td>
                <td className="px-5 py-3">{row.destination_account_id == null ? tr('資金計画に配分', 'By the funding plan') : name(row.destination_account_id)}</td>
                <td className="px-5 py-3">{row.is_active ? tr('有効', 'Active') : tr('無効', 'Inactive')}</td>
            </EditableRow>) : <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('規則はありません。', 'No rules.')}</td></tr>}
        </DataTable>}
    </section>;
}
