import { useId, useState, type FormEvent } from 'react';
import type { PlanAutomatic, PlanRecordSection } from '../../../api/plan';
import Overlay from '../../components/Overlay';
import { Choice, EditorActions, Feedback, Field, OptionGroup } from '../db/Database';
import { inputClass, type DatabaseAccount } from '../db/forms';

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
/** Sections a record can be made automatic in, and what its other account is called there. */
const COUNTERS: Partial<Record<PlanRecordSection, { label: string; types: string[] }>> = {
    expense: { label: '支払元の口座', types: ['asset', 'liability'] },
    income: { label: '入金先の口座', types: ['asset'] },
    allocation: { label: '振替元の口座', types: ['asset'] },
    debt_payment: { label: '支払元の口座', types: ['asset'] },
};

export interface RecordInput {
    name: string;
    amount: number;
    automatic?: PlanAutomatic;
}

/** ＋ レコードを追加: a record with its reason, once for the month, or 自動扱い as an automatic transaction (WP27). */
export default function RecordOptions({ section, sectionLabel, accountId, accountName, period, currency, accounts, busy, error, onSave, onClose }: {
    section: PlanRecordSection; sectionLabel: string; accountId: number; accountName: string; period: string; currency: string;
    accounts: DatabaseAccount[]; busy: boolean; error: string; onSave: (input: RecordInput) => void; onClose: () => void;
}) {
    const form = useId();
    const counter = COUNTERS[section];
    const [name, setName] = useState('');
    const [amount, setAmount] = useState('');
    const [automatic, setAutomatic] = useState(false);
    const [frequency, setFrequency] = useState<'Monthly' | 'Yearly'>('Monthly');
    const [day, setDay] = useState('1');
    const [start, setStart] = useState(period);
    const [end, setEnd] = useState('');
    const [counterId, setCounterId] = useState<number | null>(null);
    const [records, setRecords] = useState(false);
    const [problem, setProblem] = useState('');
    const choices = accounts.filter((account) => counter?.types.includes(account.account_type) && account.id !== accountId && (account.is_active || account.id === counterId));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy) return;
        const value = Number(amount);
        const problems = [
            (amount.trim() === '' || !Number.isFinite(value) || value < 0) && '金額は0以上で入力してください。',
            automatic && !MONTH.test(start) && '開始月を入力してください。',
            automatic && end !== '' && !(MONTH.test(end) && end >= start) && '終了月は開始月以降を入力してください。',
            automatic && counterId === null && `${counter?.label ?? '相手の口座'}を選んでください。`,
            automatic && !(Number.isInteger(Number(day)) && Number(day) >= 1 && Number(day) <= 31) && '日は1〜31で入力してください。',
        ].filter((message): message is string => Boolean(message));
        if (problems.length) {
            setProblem(problems[0]);
            return;
        }
        setProblem('');
        onSave({
            name: name.trim(), amount: value,
            automatic: automatic ? { frequency, day_of_month: Number(day), start_period: start, end_period: end || null, counter_account_id: counterId, records_transactions: records } : undefined,
        });
    };
    return <Overlay title={`${accountName}の${sectionLabel}にレコードを追加`} busy={busy} onClose={onClose}>
        <form id={form} onSubmit={submit} className="space-y-4">
            <Feedback error={problem || error} />
            <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
                <Field label="名前（理由）" help="同じ区分に複数のレコードを置けます。何のための予算かが分かる名前にしてください（同じ名前は1件）。">
                    <input value={name} placeholder={accountName} onChange={(event) => setName(event.target.value)} className={inputClass} /></Field>
                <Field label={`金額（${currency}）`}><input autoFocus type="number" min="0" step="any" required value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
                {counter && <label className="flex items-start gap-3 rounded-md border border-[var(--studio-border)] p-3 text-sm has-checked:border-[var(--studio-accent)] has-checked:bg-[var(--studio-accent-soft)] sm:col-span-2">
                    <input type="checkbox" checked={automatic} onChange={(event) => setAutomatic(event.target.checked)} className="mt-1 accent-[var(--studio-accent)]" />
                    <span><span className="font-medium">自動扱い</span><span className="mt-1 block text-xs text-[var(--studio-text-muted)]">毎月（毎年）の自動取引にします。計画では「自動取引による設定」になり、変更は自動取引の画面で行います。</span></span>
                </label>}
                {automatic && counter && <>
                    <div className="sm:col-span-2"><OptionGroup label="頻度" value={frequency} onChange={setFrequency} options={[
                        { value: 'Monthly', label: '毎月', description: '開始月から毎月です。' },
                        { value: 'Yearly', label: '毎年', description: '開始月から毎年同じ月です。' },
                    ]} /></div>
                    <Field label="日"><input type="number" min="1" max="31" step="1" value={day} onChange={(event) => setDay(event.target.value)} className={inputClass} /></Field>
                    <Choice label={counter.label} value={counterId} options={choices} required onChange={setCounterId} />
                    <Field label="開始月"><input type="month" required value={start} onChange={(event) => setStart(event.target.value)} className={inputClass} /></Field>
                    <Field label="終了月" help="空欄のときは終わりを決めません。"><input type="month" min={start} value={end} onChange={(event) => setEnd(event.target.value)} className={inputClass} /></Field>
                    <label className="flex items-start gap-2 text-sm sm:col-span-2">
                        <input type="checkbox" checked={records} onChange={(event) => setRecords(event.target.checked)} className="mt-1 accent-[var(--studio-accent)]" />
                        <span>取引も記録する<span className="block text-xs text-[var(--studio-text-muted)]">家賃のように、期日に家計簿へ取引を記録します。オフなら毎月の予算として繰り返すだけです（食費など）。</span></span>
                    </label>
                </>}
            </fieldset>
            <EditorActions form={form} busy={busy} onCancel={onClose} />
        </form>
    </Overlay>;
}
