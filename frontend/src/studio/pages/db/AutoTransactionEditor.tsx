import { useId, useState, type FormEvent } from 'react';
import type { AutoTransaction, AutoTransactionInput, AutoTransactionKind, AutoFrequency } from '../../../types';
import Overlay from '../../components/Overlay';
import { clientToday, useTimezone } from '../../datetime';
import { ActiveSwitch, Choice, EditorActions, Feedback, Field, Help, OptionGroup } from './Database';
import { inputClass, type DatabaseAccount } from './forms';
import { countEndDate } from './automaticSchedule';
import { labels, tr } from '../../i18n';

const KINDS = labels<AutoTransactionKind>({ expense: ['支出', 'Expense'], income: ['収入', 'Income'], debt: ['返済', 'Repayment'], transfer: ['振替', 'Transfer'] });

function accountOptions(accounts: DatabaseAccount[], kind: AutoTransactionKind, source: boolean) {
    const types = source ? kind === 'income' ? ['income'] : ['asset', 'liability']
        : kind === 'expense' ? ['expense'] : kind === 'debt' ? ['liability'] : ['asset', 'liability'];
    return accounts.filter((account) => types.includes(account.account_type));
}

function initialDraft(entry: AutoTransaction | null, kind: AutoTransactionKind, currency: string, start: string, accounts: DatabaseAccount[]): AutoTransactionInput {
    const source = accountOptions(accounts, kind, true).find((a) => a.is_active);
    const destination = accountOptions(accounts, kind, false).find((a) => a.is_active && a.id !== source?.id);
    const base: AutoTransactionInput = {
        name: '', kind, amount: 0, currency, source_account_id: source?.id ?? null, destination_account_id: destination?.id ?? null,
        budget_account_id: null, repeat_mode: 'indefinite', frequency: 'Monthly', frequency_days: null,
        day_of_month: Number(start.slice(8, 10)), month_of_year: null, start_date: start, end_date: null, repeat_count: null,
        budget_active: true, is_active: true, records_transactions: true, note: null,
    };
    if (!entry) return base;
    // Send the write contract only; names and the next cursor belong to the response.
    return Object.fromEntries(Object.keys(base).map((key) => [key, entry[key as keyof AutoTransactionInput]])) as unknown as AutoTransactionInput;
}

export default function AutoTransactionEditor({ entry, kind, currency, accounts, busy, error, onSave, onDelete, onClose }: {
    entry: AutoTransaction | null; kind: AutoTransactionKind; currency: string; accounts: DatabaseAccount[]; busy: boolean; error: string;
    onSave: (form: AutoTransactionInput) => void; onDelete?: () => void; onClose: () => void;
}) {
    const timezone = useTimezone();
    const [form, setForm] = useState(() => initialDraft(entry, kind, currency, clientToday(timezone), accounts));
    const id = useId();
    const set = <K extends keyof AutoTransactionInput>(key: K, value: AutoTransactionInput[K]) => setForm((old) => ({ ...old, [key]: value }));
    const submit = (event: FormEvent) => {
        event.preventDefault();
        if (busy) return;
        const once = form.repeat_mode === 'once';
        onSave({ ...form, name: form.name.trim(), frequency: once ? null : form.frequency,
            frequency_days: !once && form.frequency === 'EveryNDays' ? form.frequency_days : null,
            day_of_month: !once && form.frequency !== 'EveryNDays' ? form.day_of_month : null,
            month_of_year: !once && form.frequency === 'Yearly' ? form.month_of_year : null,
            repeat_count: form.repeat_mode === 'count' ? form.repeat_count : null,
            end_date: once ? null : form.repeat_mode === 'count' ? countEndDate(form) : form.end_date });
    };
    const changeKind = (next: AutoTransactionKind) => {
        const sources = accountOptions(accounts, next, true);
        const destinations = accountOptions(accounts, next, false);
        setForm((old) => {
            const source = sources.some((a) => a.id === old.source_account_id) ? old.source_account_id : sources.find((a) => a.is_active)?.id ?? null;
            const eligible = destinations.filter((a) => a.id !== source);
            const destination = eligible.some((a) => a.id === old.destination_account_id) ? old.destination_account_id : eligible.find((a) => a.is_active)?.id ?? null;
            return { ...old, kind: next, source_account_id: source, destination_account_id: destination };
        });
    };
    const once = form.repeat_mode === 'once';
    return <Overlay title={entry ? tr(`${entry.name}を編集`, `Edit ${entry.name}`) : tr('自動取引の新規作成', 'New automatic transaction')} busy={busy} onClose={onClose}
        headerAction={<ActiveSwitch name={tr('自動取引', 'Automatic transaction')} active={form.is_active} disabled={busy} onToggle={() => set('is_active', !form.is_active)} />}>
        <Feedback error={error} />
        <form id={id} onSubmit={submit} className="space-y-5">
            <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
                <Field label={tr('名称', 'Name')}><input required value={form.name} onChange={(e) => set('name', e.target.value)} className={inputClass} /></Field>
                <Field label={tr('取引の種類', 'Kind')}><select value={form.kind} onChange={(e) => changeKind(e.target.value as AutoTransactionKind)} className={inputClass}>{Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
                <Field label={tr('金額', 'Amount')}><input required type="number" min="0" step="any" value={form.amount} onChange={(e) => set('amount', Number(e.target.value))} className={inputClass} /></Field>
                <Field label={tr('通貨', 'Currency')}><input required minLength={3} maxLength={3} value={form.currency} onChange={(e) => set('currency', e.target.value.toUpperCase())} className={inputClass} /></Field>
                <Choice label={tr('出金元・収入科目', 'From (account or income)')} required value={form.source_account_id} options={accountOptions(accounts, form.kind, true)} onChange={(value) => set('source_account_id', value)} />
                <Choice label={tr('入金先・支出科目・返済先', 'To (account, expense or liability)')} required value={form.destination_account_id} options={accountOptions(accounts, form.kind, false)} onChange={(value) => set('destination_account_id', value)} />
                <Choice label={tr('予算口座', 'Budget account')} value={form.budget_account_id} options={accounts} onChange={(value) => set('budget_account_id', value)} />
            </fieldset>
            <fieldset disabled={busy} className="space-y-4 rounded-lg border border-[var(--studio-border)] p-4">
                <OptionGroup label={tr('繰り返し', 'Repeats')} value={form.repeat_mode} onChange={(mode) => setForm((old) => ({ ...old, repeat_mode: mode, frequency: old.frequency ?? 'Monthly', repeat_count: mode === 'count' ? old.repeat_count ?? 1 : null, end_date: null }))}
                    options={[{ value: 'once', label: tr('一回限り', 'Once'), description: tr('指定日に一度だけ記帳します。', 'Posts once on the date.') }, { value: 'count', label: tr('回数指定', 'A number of times'), description: tr('指定した回数で終了します。', 'Ends after the given number of times.') }, { value: 'indefinite', label: tr('指定なし', 'Until stopped'), description: tr('終了日・無効化・削除まで続きます。', 'Continues until the end date, deactivation or deletion.') }]} />
                <div className="grid min-h-60 content-start gap-4 md:grid-cols-2">
                    <div className={once ? 'invisible' : ''}><Field label={tr('周期', 'Interval')}><select disabled={once} value={form.frequency ?? 'Monthly'} onChange={(e) => setForm((old) => ({ ...old, frequency: e.target.value as AutoFrequency, frequency_days: old.frequency_days ?? 30, month_of_year: old.month_of_year ?? Number(old.start_date.slice(5, 7)) }))} className={inputClass}><option value="Monthly">{tr('毎月', 'Monthly')}</option><option value="Yearly">{tr('毎年', 'Yearly')}</option><option value="EveryNDays">{tr('日数ごと', 'Every N days')}</option></select></Field></div>
                    <div className={once ? 'invisible' : ''}>{form.frequency === 'EveryNDays'
                        ? <Field label={tr('日数', 'Days')}><input disabled={once} required={!once} type="number" min="1" step="1" value={form.frequency_days ?? ''} onChange={(e) => set('frequency_days', Number(e.target.value))} className={inputClass} /></Field>
                        : <div className="flex gap-3">{form.frequency === 'Yearly' && <Field label={tr('月', 'Month')}><input disabled={once} required={!once} type="number" min="1" max="12" value={form.month_of_year ?? Number(form.start_date.slice(5, 7))} onChange={(e) => set('month_of_year', Number(e.target.value))} className={inputClass} /></Field>}<Field label={tr('日', 'Day')}><input disabled={once} required={!once} type="number" min="1" max="31" value={form.day_of_month ?? Number(form.start_date.slice(8, 10))} onChange={(e) => set('day_of_month', Number(e.target.value))} className={inputClass} /></Field></div>}</div>
                    <Field label={once ? tr('日付', 'Date') : tr('開始日', 'Start date')}><input required type="date" value={form.start_date} onChange={(e) => set('start_date', e.target.value)} className={inputClass} /></Field>
                    <div className={form.repeat_mode !== 'count' ? 'invisible' : ''}><Field label={tr('回数', 'Times')}><input disabled={form.repeat_mode !== 'count'} required={form.repeat_mode === 'count'} type="number" min="1" max="100000" step="1" value={form.repeat_count ?? ''} onChange={(e) => set('repeat_count', Number(e.target.value))} className={inputClass} /></Field></div>
                    <div className={once ? 'invisible' : ''}><Field label={form.repeat_mode === 'count' ? tr('終了日（自動）', 'End date (automatic)') : tr('終了日（任意）', 'End date (optional)')}><input disabled={once} readOnly={form.repeat_mode === 'count'} type="date" min={form.start_date} value={form.repeat_mode === 'count' ? countEndDate(form) ?? '' : form.end_date ?? ''} onChange={(e) => set('end_date', e.target.value || null)} className={inputClass} /></Field></div>
                </div>
            </fieldset>
            <details className="rounded-lg border border-[var(--studio-border)] p-4">
                <summary className="cursor-pointer text-sm">{tr('詳細設定', 'Advanced')}</summary>
                <fieldset disabled={busy} className="mt-4 space-y-4">
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.budget_active} onChange={(e) => set('budget_active', e.target.checked)} />{tr('予算に反映する', 'Include in the budget')}</label>
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.records_transactions} onChange={(e) => set('records_transactions', e.target.checked)} />{tr('取引も記録する', 'Also record transactions')}<Help label={tr('取引も記録する', 'Also record transactions')} text={tr('オンなら期日に家計簿へ取引を記録します。オフなら毎月の予算として繰り返すだけで、取引は記録しません（計画で自動扱いにしたレコードなど）。', 'On, the transaction is recorded in the ledger on its day. Off, it only repeats as a monthly budget and records nothing (like records made automatic in the plan).')} /></label>
                    <Field label={tr('メモ', 'Note')}><textarea value={form.note ?? ''} onChange={(e) => set('note', e.target.value || null)} className={inputClass} /></Field>
                </fieldset>
            </details>
            <EditorActions form={id} busy={busy} onCancel={onClose} onDelete={onDelete} />
        </form>
    </Overlay>;
}
