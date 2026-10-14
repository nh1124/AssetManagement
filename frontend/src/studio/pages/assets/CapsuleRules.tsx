import { useReloadAction } from '../../components/useReloadAction';
import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useId, useState, type FormEvent } from 'react';
import { createCapsuleRule, deleteCapsuleRule, getCapsuleRules } from '../../../api';
import type { Capsule, CapsuleRule, CapsuleTriggerKind } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { Choice, DataTable, EditorActions, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, loadAccounts, useMutation } from '../db/forms';

const TRIGGERS: Record<CapsuleTriggerKind, string> = { Income: '収入', Expense: '支出', CreditExpense: 'カード・負債での支出', Transfer: '振替' };
const loadRules = () => getCapsuleRules();
type RuleInput = Parameters<typeof createCapsuleRule>[0];

function RuleEditor({ capsule, currency, accounts, busy, onSave, onCancel }: {
    capsule: Capsule; currency: string; accounts: Array<{ id: number; name: string; is_active?: boolean }>;
    busy: boolean; onSave: (payload: RuleInput) => void; onCancel: () => void;
}) {
    const formId = useId();
    const [trigger, setTrigger] = useState<CapsuleTriggerKind>('Income');
    const [category, setCategory] = useState('');
    const [description, setDescription] = useState('');
    const [sourceMode, setSourceMode] = useState<CapsuleRule['source_mode']>('transaction_account');
    const [source, setSource] = useState<number | null>(null);
    const [destination, setDestination] = useState<number | null>(null);
    const [amountType, setAmountType] = useState<CapsuleRule['amount_type']>('fixed');
    const [amount, setAmount] = useState('0');
    const [active, setActive] = useState(true);
    const destinations = (capsule.funding_sources ?? []).map((row) => ({ id: row.account_id, name: row.account_name || accounts.find((account) => account.id === row.account_id)?.name || `口座 #${row.account_id}` }));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy || (sourceMode === 'fixed_account' && source === null)) return;
        onSave({ capsule_id: capsule.id, trigger_type: trigger, trigger_category: category.trim() || null, trigger_description: description.trim() || null, source_mode: sourceMode, source_account_id: sourceMode === 'fixed_account' ? source : null, destination_account_id: destination, amount_type: amountType, amount_value: Number(amount), is_active: active });
    };
    return <form id={formId} onSubmit={submit} className="rounded-lg border border-[var(--studio-border)] p-5">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="発火する取引"><select value={trigger} onChange={(event) => setTrigger(event.target.value as CapsuleTriggerKind)} className={inputClass}>{Object.entries(TRIGGERS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Field label="分類の条件（任意）"><input value={category} onChange={(event) => setCategory(event.target.value)} className={inputClass} /></Field>
            <Field label="摘要の条件（任意）"><input value={description} onChange={(event) => setDescription(event.target.value)} className={inputClass} /></Field>
            <Field label="資金元"><select value={sourceMode} onChange={(event) => setSourceMode(event.target.value as CapsuleRule['source_mode'])} className={inputClass}><option value="transaction_account">発火した取引の口座</option><option value="fixed_account">指定した口座</option></select></Field>
            {sourceMode === 'fixed_account' && <Choice label="資金元の口座" value={source} options={accounts.filter((row) => row.is_active !== false)} onChange={setSource} required />}
            <Choice label="入金先（未設定なら資金計画に配分）" value={destination} options={destinations} onChange={setDestination} />
            <Field label="金額の指定"><select value={amountType} onChange={(event) => setAmountType(event.target.value as CapsuleRule['amount_type'])} className={inputClass}><option value="fixed">固定額</option><option value="percentage">取引額の割合</option></select></Field>
            <Field label={amountType === 'fixed' ? `金額（${currency}）` : '割合（%）'}><input required type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />有効</label>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}

export default function CapsuleRules({ capsule, currency, disabled, onBusy }: { capsule: Capsule; currency: string; disabled: boolean; onBusy: (busy: boolean) => void }) {
    const confirm = useConfirm();
    const rules = useResource(loadRules);
    const accounts = useResource(loadAccounts);
    const mutation = useMutation();
    const [editing, setEditing] = useState(false);
    const locked = disabled || mutation.busy || rules.loading || accounts.loading || Boolean(rules.error) || Boolean(accounts.error);
    const run = (action: () => Promise<unknown>, message: string, close = false) => {
        if (locked) return;
        // Keep deletion and funding edits locked while a rule write is in flight.
        onBusy(true);
        void mutation.run(action, message, () => { if (close) setEditing(false); rules.reload(); }).finally(() => onBusy(false));
    };
    const rows = rules.data?.filter((row) => row.capsule_id === capsule.id);
    const name = (id: number | null | undefined, fallback?: string | null) => accounts.data?.find((row) => row.id === id)?.name || fallback || (id == null ? '未設定' : `口座 #${id}`);
    useReloadAction(() => { rules.reload(); accounts.reload(); }, Boolean(disabled || mutation.busy || rules.loading));
    return <section className="mt-6 space-y-3 border-t border-[var(--studio-border)] pt-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2"><button type="button" disabled={locked || editing} onClick={() => setEditing(true)} className={buttonClass}>新しい規則</button></div></div>
        <p className="text-xs text-[var(--studio-text-muted)]">入金先を未設定にすると、資金計画の口座へ配分します。資金計画がない場合は先に設定してください。</p>
        <Feedback loading={rules.loading || accounts.loading} error={rules.error || accounts.error} />
        <Feedback error={mutation.error} message={mutation.message} />
        {editing && accounts.data && <Overlay title={`「${capsule.name}」の新しい規則`} onClose={() => setEditing(false)}><Feedback error={mutation.error} /><RuleEditor capsule={capsule} currency={currency} accounts={accounts.data} busy={locked} onCancel={() => setEditing(false)} onSave={(payload) => run(() => createCapsuleRule(payload), '規則を作成しました。', true)} /></Overlay>}
        {rows && <DataTable columns={['発火条件', '資金元', '金額', '入金先', '状態', '操作']}>
            {rows.length ? rows.map((row) => <tr key={row.id}>
                <th scope="row" className="px-5 py-3 font-normal">{TRIGGERS[row.trigger_type]}{row.trigger_category && <p className="text-xs">分類：{row.trigger_category}</p>}{row.trigger_description && <p className="text-xs">摘要：{row.trigger_description}</p>}</th>
                <td className="px-5 py-3">{row.source_mode === 'transaction_account' ? '発火した取引の口座' : name(row.source_account_id, row.source_account_name)}</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.amount_type === 'percentage' ? `${row.amount_value}%` : formatCurrency(row.amount_value, currency)}</td>
                <td className="px-5 py-3">{row.destination_account_id == null ? '資金計画に配分' : name(row.destination_account_id)}</td>
                <td className="px-5 py-3">{row.is_active ? '有効' : '無効'}</td>
                <td className="px-5 py-3"><button type="button" disabled={locked || editing} className={`${buttonClass} text-[var(--studio-danger)]`} onClick={async () => { if ((await confirm(`「${capsule.name}」の${TRIGGERS[row.trigger_type]}の規則を削除しますか？既存の取引・残高はそのまま残ります。`, '削除する'))) run(() => deleteCapsuleRule(row.id), '規則を削除しました。'); }}>削除</button></td>
            </tr>) : <tr><td colSpan={6} className="px-5 py-4 text-[var(--studio-text-muted)]">規則はありません。</td></tr>}
        </DataTable>}
    </section>;
}
