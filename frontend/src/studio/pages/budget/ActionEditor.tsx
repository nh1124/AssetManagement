import { useId, useState, type FormEvent } from 'react';
import { getCapsules, getLifeEvents, getRecurringTransactions } from '../../../api';
import type { LifeEvent, MonthlyAction, ReviewActionCreate, ReviewActionKind } from '../../../types';
import { useResource } from '../../useResource';
import { Choice, EditorActions, Feedback, Field } from '../db/Database';
import { inputClass, loadAccounts } from '../db/forms';

const KINDS: Record<ReviewActionKind, string> = {
    set_budget: '支出予算を設定', add_recurring: '定常収支を追加', pause_recurring: '定常収支を停止',
    boost_allocation: 'ライフイベントへの確保額を変更', change_capsule_contribution: '取り置きの月額積立を変更',
};

async function loadActionLookups() {
    // The editor needs reference identities, never journal attribution columns.
    const [accounts, recurring, goals, capsules] = await Promise.all([
        loadAccounts(), getRecurringTransactions(), getLifeEvents() as Promise<LifeEvent[]>,
        getCapsules() as Promise<Array<{ id: number; name: string }>>,
    ]);
    return { accounts, recurring, goals, capsules };
}

type ActionEditorProps = {
    sourcePeriod: string; currency: string; busy: boolean;
} & ({ action: MonthlyAction; onSave?: never; onCancel?: never } | {
    action?: undefined;
    onSave: (payload: ReviewActionCreate) => void; onCancel: () => void;
});

function isActionKind(value: string): value is ReviewActionKind {
    return Object.hasOwn(KINDS, value);
}

export default function ActionEditor({ sourcePeriod, currency, busy, action, onSave, onCancel }: ActionEditorProps) {
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
    const [accountId, setAccountId] = useState(numberValue(kind === 'add_recurring' ? payload.from_account_id : payload.account_id));
    const [destinationId, setDestinationId] = useState(numberValue(payload.to_account_id));
    const [referenceId, setReferenceId] = useState(numberValue(kind === 'pause_recurring' ? payload.recurring_id ?? action?.target_id
        : kind === 'boost_allocation' ? payload.life_event_id : payload.capsule_id ?? action?.target_id));
    const [amount, setAmount] = useState(() => {
        const value = kind === 'boost_allocation' ? payload.delta_percent ?? payload.percent : payload.amount ?? payload.monthly_contribution ?? action?.amount;
        return typeof value === 'number' ? String(value) : '';
    });
    const [name, setName] = useState(typeof payload.name === 'string' ? payload.name : '');
    const [day, setDay] = useState(String(numberValue(payload.day_of_month) ?? 1));
    const [entryCurrency, setEntryCurrency] = useState(typeof payload.currency === 'string' ? payload.currency : currency);
    // Existing actions are read-only because the API has no update endpoint.
    const disabled = Boolean(action) || busy || lookups.loading || Boolean(lookups.error) || !lookups.data;
    const accounts = lookups.data?.accounts.filter((row) => action || row.is_active) ?? [];
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || !onSave || !isActionKind(kind) || !description.trim() || !targetPeriod) return;
        const numeric = Number(amount);
        if (kind !== 'pause_recurring' && (amount.trim() === '' || !Number.isFinite(numeric))) return;
        let payload: Record<string, unknown>;
        switch (kind) {
            case 'set_budget':
                if (!accountId || numeric < 0) return;
                payload = { account_id: accountId, amount: numeric };
                break;
            case 'add_recurring':
                if (!accountId || !destinationId || accountId === destinationId || !name.trim() || numeric <= 0) return;
                payload = { name: name.trim(), amount: numeric, currency: entryCurrency, from_account_id: accountId, to_account_id: destinationId, frequency: 'Monthly', day_of_month: Number(day) };
                break;
            case 'pause_recurring':
                if (!referenceId) return;
                payload = { recurring_id: referenceId };
                break;
            case 'boost_allocation':
                if (!referenceId || !accountId || numeric < -100 || numeric > 100) return;
                payload = { life_event_id: referenceId, account_id: accountId, delta_percent: numeric };
                break;
            case 'change_capsule_contribution':
                if (!referenceId || numeric < 0) return;
                payload = { capsule_id: referenceId, monthly_contribution: numeric };
                break;
        }
        onSave({ source_period: sourcePeriod, target_period: targetPeriod, kind, description: description.trim(), payload });
    };
    return <form id={formId} onSubmit={submit} className="space-y-4">
        {!action && <p className="text-xs text-[var(--studio-text-muted)]">行動を未実行として記録します。実行するか、予定月になって期限到来の処理をすると反映されます。</p>}
        <Feedback loading={lookups.loading} error={lookups.error} />
        <fieldset disabled={disabled} className="grid gap-4 md:grid-cols-2">
            <Field label="行動"><input required value={description} onChange={(event) => setDescription(event.target.value)} className={inputClass} /></Field>
            <Field label="種類"><select value={kind} onChange={(event) => { setKind(event.target.value); setAccountId(null); setDestinationId(null); setReferenceId(null); setAmount(''); }} className={inputClass}>{!isActionKind(kind) && <option value={kind}>未対応の種類（{kind}）</option>}{Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
            <Field label="予定月"><input required type="month" value={targetPeriod} onChange={(event) => setTargetPeriod(event.target.value)} className={inputClass} /></Field>
            {kind === 'set_budget' && <Choice label="支出の勘定科目" value={accountId} required options={accounts.filter((row) => row.account_type === 'expense')} onChange={setAccountId} />}
            {kind === 'add_recurring' && <>
                <Field label="定常収支の名称"><input required value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
                <Choice label="出金元・収入科目" value={accountId} required options={accounts} onChange={setAccountId} />
                <Choice label="入金先・支出科目・返済先" value={destinationId} required options={accounts.filter((row) => row.id !== accountId)} onChange={setDestinationId} />
                <Field label="通貨"><input required pattern="[A-Z]{3}" maxLength={3} value={entryCurrency} onChange={(event) => setEntryCurrency(event.target.value.toUpperCase())} className={inputClass} /></Field>
                <Field label="毎月の予定日"><input required type="number" min="1" max="31" step="1" value={day} onChange={(event) => setDay(event.target.value)} className={inputClass} /></Field>
            </>}
            {kind === 'pause_recurring' && <>
                <Choice label="停止する定常収支" value={referenceId} required options={lookups.data?.recurring.filter((row) => action || row.is_active) ?? []} onChange={setReferenceId} />
                <p className="text-xs text-[var(--studio-warning)] md:col-span-2">実行すると定義を無効にし、自動記帳と予算への反映を停止します。自動で再開する予定は設定されません。</p>
            </>}
            {kind === 'boost_allocation' && <>
                <Choice label="ライフイベント" value={referenceId} required options={lookups.data?.goals ?? []} onChange={setReferenceId} />
                <Choice label="資金を確保する口座" value={accountId} required options={accounts.filter((row) => row.account_type === 'asset')} onChange={setAccountId} />
                <p className="text-xs text-[var(--studio-text-muted)] md:col-span-2">指定口座の残高に対する割合でライフイベントの確保額を変更します。負の割合は確保額を減らします。</p>
            </>}
            {kind === 'change_capsule_contribution' && <Choice label="取り置き" value={referenceId} required options={lookups.data?.capsules ?? []} onChange={setReferenceId} />}
            {kind !== 'pause_recurring' && <Field label={kind === 'boost_allocation' ? '確保額の変更割合（%）' : `金額（${kind === 'add_recurring' ? entryCurrency : currency}）`}>
                <input required type="number" min={kind === 'boost_allocation' ? '-100' : kind === 'add_recurring' ? '0.01' : '0'} max={kind === 'boost_allocation' ? '100' : undefined} step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} />
            </Field>}
            {!action && <EditorActions form={formId} busy={disabled} onCancel={onCancel} />}
        </fieldset>
    </form>;
}
