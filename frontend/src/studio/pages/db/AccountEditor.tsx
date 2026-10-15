import { useId, useState, type FormEvent } from 'react';
import { createAccount, updateAccount } from '../../../api';
import type { AccountInstitution, AccountRole } from '../../../types';
import { Choice, EditorActions, Field } from './Database';
import { ACCOUNT_TYPES, INSTITUTIONS, ROLES, inputClass, type DatabaseAccount } from './forms';

export default function AccountEditor({ account, accounts, currency, busy, onSave, onCancel }: {
    account: DatabaseAccount | null; accounts: DatabaseAccount[]; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const formId = useId();
    const [name, setName] = useState(account?.name ?? '');
    const [type, setType] = useState<DatabaseAccount['account_type']>(account?.account_type ?? 'asset');
    const [role, setRole] = useState<AccountRole>(account?.role ?? 'unassigned');
    const [target, setTarget] = useState(account?.role_target_amount == null ? '' : String(account.role_target_amount));
    const [expectedReturn, setExpectedReturn] = useState(account?.expected_return == null ? '' : String(account.expected_return));
    const [institution, setInstitution] = useState<AccountInstitution>(account?.institution ?? 'none');
    const [withdrawableAge, setWithdrawableAge] = useState(account?.withdrawable_from_age == null ? '' : String(account.withdrawable_from_age));
    const offersAge = institution === 'ideco' || institution === 'dc_corporate';
    const [parent, setParent] = useState<number | null>(account?.parent_id ?? null);
    const excluded = new Set<number>(account ? [account.id] : []);
    // Exclude descendants as well as self so the parent picker cannot create a cycle.
    let previousSize = -1;
    while (previousSize !== excluded.size) {
        previousSize = excluded.size;
        for (const row of accounts) if (row.parent_id != null && excluded.has(row.parent_id)) excluded.add(row.id);
    }
    const parents = accounts.filter((row) => row.account_type === type && !excluded.has(row.id));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!name.trim() || !Number.isFinite(Number(expectedReturn))) return;
        // Balances are journal-owned; only these editable attributes are sent.
        const payload = { name: name.trim(), role, expected_return: expectedReturn === '' ? null : Number(expectedReturn), parent_id: parent,
            institution, withdrawable_from_age: offersAge ? (withdrawableAge === '' ? null : Number(withdrawableAge)) : (account?.withdrawable_from_age ?? null) };
        onSave(() => account
            ? updateAccount(account.id, { ...payload, role_target_amount: target === '' ? null : Number(target) })
            : createAccount({ ...payload, account_type: type }));
    };
    return <form id={formId} onSubmit={submit} className="space-y-4">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
            <Field label="種別"><select disabled={Boolean(account)} value={type} onChange={(event) => { setType(event.target.value as DatabaseAccount['account_type']); setParent(null); }} className={inputClass}>{Object.entries(ACCOUNT_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Field label="役割"><select value={role} onChange={(event) => setRole(event.target.value as AccountRole)} className={inputClass}>{Object.entries(ROLES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Field label="期待年利（%）"><input type="number" step="any" placeholder="試算の年利" value={expectedReturn} onChange={(event) => setExpectedReturn(event.target.value)} className={inputClass} /></Field>
            <Field label="制度区分"><select value={institution} onChange={(event) => setInstitution(event.target.value as AccountInstitution)} className={inputClass}>{Object.entries(INSTITUTIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            {offersAge && <Field label="引き出し可能年齢"><input type="number" min="0" step="1" placeholder="60" value={withdrawableAge} onChange={(event) => setWithdrawableAge(event.target.value)} className={inputClass} /></Field>}
            {account && <Field label={`役割の目標額（${currency}）`}><input type="number" min="0" step="any" value={target} onChange={(event) => setTarget(event.target.value)} className={inputClass} /></Field>}
            <Choice label="親の口座・勘定科目" value={parent} options={parents} onChange={setParent} />
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}

