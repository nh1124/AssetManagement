import { useId, useState, type FormEvent } from 'react';
import { createAccount, updateAccount } from '../../../api';
import { EditorActions, Field } from './Database';
import { ACCOUNT_TYPES, inputClass, type DatabaseAccount } from './forms';

const CARD_NUMBERS = [
    ['liability_closing_day', '締日', 1, 31], ['liability_payment_day', '支払日', 1, 31],
    ['liability_payment_month_offset', '支払月（翌月＝1）', 0, 24],
    ['liability_minimum_payment', '最低支払額', 0, undefined], ['liability_fixed_payment_amount', '定額支払額', 0, undefined],
    ['liability_installment_months', '分割回数', 1, 120], ['liability_revolving_rate', 'リボ年利（%）', 0, undefined],
] as const;

export default function AccountEditor({ account, initialType = 'asset', currency, busy, onSave, onCancel }: {
    account: DatabaseAccount | null; initialType?: DatabaseAccount['account_type']; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const formId = useId();
    const [name, setName] = useState(account?.name ?? '');
    const [type, setType] = useState<DatabaseAccount['account_type']>(account?.account_type ?? initialType);
    const [active, setActive] = useState(account?.is_active ?? true);
    const [policy, setPolicy] = useState<NonNullable<DatabaseAccount['liability_payment_policy']>>(account?.liability_payment_policy ?? 'full');
    const [card, setCard] = useState(() => Object.fromEntries(CARD_NUMBERS.map(([key]) => [key, account?.[key] == null ? '' : String(account[key])])));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!name.trim()) return;
        const payload = { name: name.trim(), is_active: active, ...(type === 'liability' ? {
            liability_payment_policy: policy,
            ...Object.fromEntries(CARD_NUMBERS.map(([key]) => [key, card[key] === '' ? (key === 'liability_payment_month_offset' ? 0 : null) : Number(card[key])])),
        } : {}) };
        onSave(() => account ? updateAccount(account.id, payload) : createAccount({ ...payload, account_type: type }));
    };
    return <form id={formId} onSubmit={submit} className="space-y-4">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label="種類"><select disabled={Boolean(account)} value={type} onChange={(event) => setType(event.target.value as DatabaseAccount['account_type'])} className={inputClass}>{Object.entries(ACCOUNT_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            {type === 'liability' && <>
                <Field label="支払方法"><select value={policy} onChange={(event) => setPolicy(event.target.value as typeof policy)} className={inputClass}>{Object.entries({ full: '全額', minimum: '最低額', fixed: '定額', installment: '分割', revolving: 'リボ' }).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
                {CARD_NUMBERS.map(([key, label, min, max]) => <Field key={key} label={`${label}${key === 'liability_minimum_payment' || key === 'liability_fixed_payment_amount' ? `（${currency}）` : ''}`}><input type="number" min={min} max={max} step={key.includes('amount') || key.includes('minimum') || key.includes('rate') ? 'any' : 1} value={card[key]} onChange={(event) => setCard((previous) => ({ ...previous, [key]: event.target.value }))} className={inputClass} /></Field>)}
            </>}
            <Field label="有効"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} /></Field>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}
