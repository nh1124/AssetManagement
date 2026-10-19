import { useId, useState, type FormEvent } from 'react';
import type { ContributionPlan, ContributionPlanInput } from '../../../api/lifeScenarios';
import type { LifeEvent } from '../../../types';
import { Choice, EditorActions, Feedback, Field, OptionGroup } from '../db/Database';
import { inputClass, type DatabaseAccount } from '../db/forms';

type Direction = 'save' | 'withdraw' | 'event';

/** One 積立設定 record: from its start month, what the account receives (or gives up) each month, and its yield;
 * or, once, what the account gives toward a life event (ライフイベントへの取り崩し). */
export default function ContributionPlanEditor({ plan, accounts, events, defaultPeriod, currency, defaultRate, busy, onSave, onCancel, onDelete }: {
    plan: ContributionPlan | null; accounts: DatabaseAccount[]; events: LifeEvent[]; defaultPeriod: string; currency: string; defaultRate: number; busy: boolean;
    onSave: (input: ContributionPlanInput) => void; onCancel: () => void; onDelete?: () => void;
}) {
    const form = useId();
    const [accountId, setAccountId] = useState<number | null>(plan?.account_id ?? null);
    const [period, setPeriod] = useState(plan?.start_period ?? defaultPeriod);
    const [direction, setDirection] = useState<Direction>(plan?.life_event_id ? 'event' : plan && plan.monthly_amount < 0 ? 'withdraw' : 'save');
    const [eventId, setEventId] = useState<number | null>(plan?.life_event_id ?? null);
    const [amount, setAmount] = useState(plan ? String(Math.abs(plan.monthly_amount)) : '');
    const [rate, setRate] = useState(plan?.annual_return == null ? '' : String(plan.annual_return));
    const [note, setNote] = useState(plan?.note ?? '');
    const [error, setError] = useState('');
    const choices = accounts.filter((row) => row.account_type === 'asset' && (row.is_active || row.id === accountId));
    const expenses = events.filter((row) => row.direction === 'expense');
    const forEvent = direction === 'event';
    const chooseEvent = (id: number | null) => {
        setEventId(id);
        // A new withdrawal falls in the event's month unless a month was already chosen.
        const chosen = expenses.find((row) => row.id === id);
        if (chosen && !plan && period === defaultPeriod) setPeriod(chosen.target_date.slice(0, 7));
    };
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy) return;
        const monthly = Number(amount || 0);
        if (forEvent && (accountId === null || eventId === null || !/^\d{4}-(0[1-9]|1[0-2])$/.test(period) || !(monthly > 0))) {
            setError('口座・月・ライフイベントと、0より大きい金額を入力してください。');
            return;
        }
        if (!forEvent && (accountId === null || !/^\d{4}-(0[1-9]|1[0-2])$/.test(period) || !Number.isFinite(monthly) || monthly < 0 || (rate.trim() !== '' && !Number.isFinite(Number(rate))))) {
            setError('口座・開始月と0以上の月額を入力してください。年利は数値か空欄です。');
            return;
        }
        setError('');
        onSave(forEvent
            ? { account_id: accountId as number, start_period: period, monthly_amount: -monthly, annual_return: null, note: note.trim() || null, life_event_id: eventId }
            : { account_id: accountId as number, start_period: period, monthly_amount: direction === 'withdraw' ? -monthly : monthly,
                annual_return: rate.trim() === '' ? null : Number(rate), note: note.trim() || null, life_event_id: null });
    };
    return <form id={form} onSubmit={submit} className="space-y-4">
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2"><OptionGroup label="レコードの種類" value={direction} onChange={setDirection} options={[
                { value: 'save', label: '毎月の積立', description: '毎月この口座に入れます。計画の作成では配分の行になります。' },
                { value: 'withdraw', label: '毎月の取り崩し', description: '毎月この口座から引き出します（老後の生活費など）。計画の作成では取り崩しの行になります。' },
                { value: 'event', label: 'ライフイベントへの取り崩し', description: 'その月に一度だけ、この口座から引き出してライフイベントに充てます。計画の作成では、その月まで口座ごとにゴールの取り置きとして積み立てます。' },
            ]} /></div>
            <Choice label="口座" help="積立設定にレコードがある口座が、このシナリオの使用口座です。" value={accountId} options={choices} required onChange={setAccountId} />
            {forEvent
                ? <Field label="取り崩す月" help="ライフイベントの月が既定です。前もって引き出すこともできます（純資産は支払いの時点で減ります）。"><input required type="month" value={period} onChange={(event) => setPeriod(event.target.value)} className={inputClass} /></Field>
                : <Field label="開始月" help="この月から、次のレコードの開始月の前月まで使います。"><input required type="month" value={period} onChange={(event) => setPeriod(event.target.value)} className={inputClass} /></Field>}
            {forEvent && <Choice label="ライフイベント" help="このシナリオの支出のライフイベントです。足りない分は残りの純資産から払います。" value={eventId} options={expenses} required onChange={chooseEvent} />}
            <Field label={forEvent ? `取り崩す金額（${currency}）` : `月額（${currency}）`}><input type="number" min="0" step="any" value={amount} placeholder="0" onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            {!forEvent && <Field label="年利（%）" help={`空欄のときは、この口座の直前のレコードの年利（なければシナリオの既定 ${defaultRate}%）を引き継ぎます。`}><input inputMode="decimal" value={rate} placeholder="引き継ぐ" onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>}
            <div className="sm:col-span-2"><Field label="メモ"><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field></div>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} onDelete={onDelete} />
    </form>;
}
