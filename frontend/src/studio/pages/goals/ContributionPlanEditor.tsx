import { useId, useState, type FormEvent } from 'react';
import type { ContributionPlan, ContributionPlanInput } from '../../../api/lifeScenarios';
import { Choice, EditorActions, Feedback, Field, OptionGroup } from '../db/Database';
import { inputClass, type DatabaseAccount } from '../db/forms';

type Direction = 'save' | 'withdraw';

/** One 積立設定 record: from its start month, what the account receives (or gives up) each month, and its yield. */
export default function ContributionPlanEditor({ plan, accounts, defaultPeriod, currency, defaultRate, busy, onSave, onCancel, onDelete }: {
    plan: ContributionPlan | null; accounts: DatabaseAccount[]; defaultPeriod: string; currency: string; defaultRate: number; busy: boolean;
    onSave: (input: ContributionPlanInput) => void; onCancel: () => void; onDelete?: () => void;
}) {
    const form = useId();
    const [accountId, setAccountId] = useState<number | null>(plan?.account_id ?? null);
    const [period, setPeriod] = useState(plan?.start_period ?? defaultPeriod);
    const [direction, setDirection] = useState<Direction>(plan && plan.monthly_amount < 0 ? 'withdraw' : 'save');
    const [amount, setAmount] = useState(plan ? String(Math.abs(plan.monthly_amount)) : '');
    const [rate, setRate] = useState(plan?.annual_return == null ? '' : String(plan.annual_return));
    const [note, setNote] = useState(plan?.note ?? '');
    const [error, setError] = useState('');
    const choices = accounts.filter((row) => row.account_type === 'asset' && (row.is_active || row.id === accountId));
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy) return;
        const monthly = Number(amount || 0);
        if (accountId === null || !/^\d{4}-(0[1-9]|1[0-2])$/.test(period) || !Number.isFinite(monthly) || monthly < 0 || (rate.trim() !== '' && !Number.isFinite(Number(rate)))) {
            setError('口座・開始月と0以上の月額を入力してください。年利は数値か空欄です。');
            return;
        }
        setError('');
        onSave({ account_id: accountId, start_period: period, monthly_amount: direction === 'withdraw' ? -monthly : monthly,
            annual_return: rate.trim() === '' ? null : Number(rate), note: note.trim() || null });
    };
    return <form id={form} onSubmit={submit} className="space-y-4">
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <Choice label="口座" help="積立設定にレコードがある口座が、このシナリオの使用口座です。" value={accountId} options={choices} required onChange={setAccountId} />
            <Field label="開始月" help="この月から、次のレコードの開始月の前月まで使います。"><input required type="month" value={period} onChange={(event) => setPeriod(event.target.value)} className={inputClass} /></Field>
            <div className="sm:col-span-2"><OptionGroup label="毎月の動き" value={direction} onChange={setDirection} options={[
                { value: 'save', label: '積立', description: '毎月この口座に入れます。計画の作成では配分の行になります。' },
                { value: 'withdraw', label: '取り崩し', description: '毎月この口座から引き出します（老後の生活費など）。計画の作成では取り崩しの行になります。' },
            ]} /></div>
            <Field label={`月額（${currency}）`}><input type="number" min="0" step="any" value={amount} placeholder="0" onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <Field label="年利（%）" help={`空欄のときは、この口座の直前のレコードの年利（なければシナリオの既定 ${defaultRate}%）を引き継ぎます。`}><input inputMode="decimal" value={rate} placeholder="引き継ぐ" onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>
            <div className="sm:col-span-2"><Field label="メモ"><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field></div>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} onDelete={onDelete} />
    </form>;
}
