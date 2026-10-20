import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { getCapsules, getAutoTransactions } from '../../../api';
import type { MonthlyAction, ReviewActionCreate, ReviewActionKind } from '../../../types';
import { useResource } from '../../useResource';
import { Choice, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, loadAccounts, primaryClass } from '../db/forms';
import { OverlayFooter } from '../../components/Overlay';

const KINDS: Record<ReviewActionKind, string> = {
    set_budget: '支出予算を設定', add_auto_transaction: '自動取引を追加', stop_auto_transaction: '自動取引を停止',
    change_capsule_contribution: '取り置きの月額積立を変更',
};

async function loadActionLookups() {
    // The editor needs reference identities, never journal attribution columns.
    const [accounts, recurring, capsules] = await Promise.all([
        loadAccounts(), getAutoTransactions(), getCapsules() as Promise<Array<{ id: number; name: string }>>,
    ]);
    return { accounts, recurring, capsules };
}

type ActionEditorProps = {
    sourcePeriod: string; currency: string; busy: boolean;
    action?: MonthlyAction;
    onSave?: (payload: ReviewActionCreate) => void;
    onCancel: () => void;
    footerActions?: ReactNode;
};

function isActionKind(value: string): value is ReviewActionKind {
    return Object.hasOwn(KINDS, value);
}

export default function ActionEditor({ sourcePeriod, currency, busy, action, onSave, onCancel, footerActions }: ActionEditorProps) {
    const formId = useId();
    const lookups = useResource(loadActionLookups);
    const payload = action?.payload ?? {};
    const numberValue = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null;
    const [kind, setKind] = useState(action?.kind ?? 'set_budget');
    const [description, setDescription] = useState(action?.description ?? '');
    const [targetPeriod, setTargetPeriod] = useState(() => {
        if (action) return action.target_period ?? '';
        const [year, month] = sourcePeriod.split('-').map(Number);
        return `${month === 12 ? year + 1 : year}-${String(month === 12 ? 1 : month + 1).padStart(2, '0')}`;
    });
    const [accountId, setAccountId] = useState(numberValue(kind === 'add_auto_transaction' ? payload.source_account_id : payload.account_id));
    const [destinationId, setDestinationId] = useState(numberValue(payload.destination_account_id));
    const [referenceId, setReferenceId] = useState(numberValue(kind === 'stop_auto_transaction' ? payload.registry_entry_id ?? action?.target_id
        : payload.capsule_id ?? action?.target_id));
    const [amount, setAmount] = useState(() => {
        const value = payload.amount ?? payload.monthly_contribution ?? action?.amount;
        return typeof value === 'number' ? String(value) : '';
    });
    const [name, setName] = useState(typeof payload.name === 'string' ? payload.name : '');
    const [day, setDay] = useState(String(numberValue(payload.day_of_month) ?? 1));
    const [entryCurrency, setEntryCurrency] = useState(typeof payload.currency === 'string' ? payload.currency : currency);
    const readOnly = action !== undefined && action.status !== 'pending';
    const disabled = readOnly || busy || lookups.loading || Boolean(lookups.error) || !lookups.data;
    const accounts = lookups.data?.accounts.filter((row) => action || row.is_active) ?? [];
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || !onSave || !isActionKind(kind) || !description.trim() || !targetPeriod) return;
        const numeric = Number(amount);
        if (kind !== 'stop_auto_transaction' && (amount.trim() === '' || !Number.isFinite(numeric))) return;
        let payload: Record<string, unknown>;
        switch (kind) {
            case 'set_budget':
                if (!accountId || numeric < 0) return;
                payload = { account_id: accountId, amount: numeric };
                break;
            case 'add_auto_transaction':
                if (!accountId || !destinationId || accountId === destinationId || !name.trim() || numeric <= 0) return;
                payload = { name: name.trim(), amount: numeric, currency: entryCurrency, kind: accounts.find((a) => a.id === accountId)?.account_type === 'income' ? 'income' : accounts.find((a) => a.id === destinationId)?.account_type === 'expense' ? 'expense' : accounts.find((a) => a.id === destinationId)?.account_type === 'liability' ? 'debt' : 'transfer', source_account_id: accountId, destination_account_id: destinationId, start_date: `${targetPeriod}-01`, repeat_mode: 'indefinite', frequency: action?.kind === kind ? action.payload.frequency ?? 'Monthly' : 'Monthly', day_of_month: Number(day) };
                break;
            case 'stop_auto_transaction':
                if (!referenceId) return;
                payload = { registry_entry_id: referenceId };
                break;
            case 'change_capsule_contribution':
                if (!referenceId || numeric < 0) return;
                payload = { capsule_id: referenceId, monthly_contribution: numeric };
                break;
        }
        // Keep fields outside this form, such as plan_id, when correcting the same action kind.
        const savedPayload = action?.kind === kind ? { ...action.payload, ...payload } : payload;
        onSave({ source_period: action?.source_period ?? sourcePeriod, target_period: targetPeriod, kind, description: description.trim(), payload: savedPayload });
    };
    return <form id={formId} onSubmit={submit} className="space-y-4">
        <Feedback loading={lookups.loading} error={lookups.error} />
        <fieldset disabled={disabled} className="grid gap-4 md:grid-cols-2">
            <Field label="行動"><input required value={description} onChange={(event) => setDescription(event.target.value)} className={inputClass} /></Field>
            <Field label="種類"><select value={kind} onChange={(event) => { setKind(event.target.value); setAccountId(null); setDestinationId(null); setReferenceId(null); setAmount(''); }} className={inputClass}>{!isActionKind(kind) && <option value={kind}>未対応の種類（{kind}）</option>}{Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Field label="予定月"><input required type="month" value={targetPeriod} onChange={(event) => setTargetPeriod(event.target.value)} className={inputClass} /></Field>
            {kind === 'set_budget' && <Choice label="支出の勘定科目" value={accountId} required options={accounts.filter((row) => row.account_type === 'expense')} onChange={setAccountId} />}
            {kind === 'add_auto_transaction' && <>
                <Field label="自動取引の名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
                <Choice label="出金元・収入科目" value={accountId} required options={accounts} onChange={setAccountId} />
                <Choice label="入金先・支出科目・返済先" value={destinationId} required options={accounts.filter((row) => row.id !== accountId)} onChange={setDestinationId} />
                <Field label="通貨"><input required pattern="[A-Z]{3}" maxLength={3} value={entryCurrency} onChange={(event) => setEntryCurrency(event.target.value.toUpperCase())} className={inputClass} /></Field>
                <Field label="毎月の予定日"><input required type="number" min="1" max="31" step="1" value={day} onChange={(event) => setDay(event.target.value)} className={inputClass} /></Field>
            </>}
            {kind === 'stop_auto_transaction' && <>
                <Choice label="停止する自動取引" value={referenceId} required options={lookups.data?.recurring.filter((row) => action || row.is_active) ?? []} onChange={setReferenceId} />
                <p className="text-xs text-[var(--studio-warning)] md:col-span-2">実行すると自動取引を無効にし、自動記帳と予算への反映を停止します。自動で再開する予定は設定されません。</p>
            </>}
            {kind === 'change_capsule_contribution' && <Choice label="取り置き" value={referenceId} required options={lookups.data?.capsules ?? []} onChange={setReferenceId} />}
            {kind !== 'stop_auto_transaction' && <Field label={`金額（${kind === 'add_auto_transaction' ? entryCurrency : currency}）`}>
                <input required type="number" min={kind === 'add_auto_transaction' ? '0.01' : '0'} step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} />
            </Field>}
        </fieldset>
        {!readOnly && onSave && <OverlayFooter fallback={<div className="flex justify-end gap-2">
            <button type="submit" form={formId} disabled={disabled} className={primaryClass}>保存</button>
            <button type="button" disabled={busy} onClick={onCancel} className={buttonClass}>キャンセル</button>
        </div>}>
            {footerActions}
            <button type="submit" form={formId} disabled={disabled} className={primaryClass}>保存</button>
        </OverlayFooter>}
    </form>;
}
