import { useId, useState, type FormEvent } from 'react';
import type { ContributionKind, ContributionPlan, ContributionPlanInput, ShortageMode } from '../../../api/lifeScenarios';
import type { LifeEvent } from '../../../types';
import { Choice, EditorActions, Feedback, Field, OptionGroup } from '../db/Database';
import { inputClass, type DatabaseAccount } from '../db/forms';
import { SHORTAGE_TEXT } from './contributionText';

type Frequency = 'once' | 'monthly' | 'yearly' | 'custom';
type Ending = 'none' | 'count' | 'until';
const PERIOD = /^\d{4}-(0[1-9]|1[0-2])$/;

function frequencyOf(interval: number | null | undefined): Frequency {
    if (interval === null) return 'once';
    if (interval === undefined || interval === 1) return 'monthly';
    return interval === 12 ? 'yearly' : 'custom';
}

/** One 積立設定 record: a 積立 into an account, a 口座振替 between accounts, or a withdrawal toward a life event,
 * once or every month / year / N months, N times or until a month. */
export default function ContributionPlanEditor({ plan, accounts, events, defaultPeriod, currency, defaultRate, busy, onSave, onCancel, onDelete }: {
    plan: ContributionPlan | null; accounts: DatabaseAccount[]; events: LifeEvent[]; defaultPeriod: string; currency: string; defaultRate: number; busy: boolean;
    onSave: (input: ContributionPlanInput) => void; onCancel: () => void; onDelete?: () => void;
}) {
    const form = useId();
    const [kind, setKind] = useState<ContributionKind>(plan?.kind ?? 'contribution');
    const [accountId, setAccountId] = useState<number | null>(plan?.account_id ?? null);
    const [toAccountId, setToAccountId] = useState<number | null>(plan?.to_account_id ?? null);
    const [eventId, setEventId] = useState<number | null>(plan?.life_event_id ?? null);
    const [period, setPeriod] = useState(plan?.start_period ?? defaultPeriod);
    const [amount, setAmount] = useState(plan ? String(plan.amount) : '');
    const [frequency, setFrequency] = useState<Frequency>(frequencyOf(plan ? plan.interval_months : undefined));
    const initialInterval = plan?.interval_months ?? 3;
    const [every, setEvery] = useState(String(initialInterval % 12 === 0 ? initialInterval / 12 : initialInterval));
    const [unit, setUnit] = useState<'months' | 'years'>(initialInterval % 12 === 0 ? 'years' : 'months');
    const [ending, setEnding] = useState<Ending>(plan?.repeat_count ? 'count' : plan?.end_period ? 'until' : 'none');
    const [count, setCount] = useState(plan?.repeat_count ? String(plan.repeat_count) : '');
    const [until, setUntil] = useState(plan?.end_period ?? '');
    const [shortage, setShortage] = useState<ShortageMode>(plan?.on_shortage ?? (plan?.kind === 'transfer' ? 'skip' : 'partial'));
    const [rate, setRate] = useState(plan?.annual_return == null ? '' : String(plan.annual_return));
    const [note, setNote] = useState(plan?.note ?? '');
    const [error, setError] = useState('');
    const assets = accounts.filter((row) => row.account_type === 'asset');
    const choices = assets.filter((row) => row.is_active || row.id === accountId);
    const destinations = assets.filter((row) => (row.is_active || row.id === toAccountId) && row.id !== accountId);
    const expenses = events.filter((row) => row.direction === 'expense');
    const repeated = frequency !== 'once';
    const chooseKind = (next: ContributionKind) => {
        setKind(next);
        // A new record follows the usual shape of its kind: a withdrawal once, the others every month.
        if (!plan) {
            setFrequency(next === 'withdrawal' ? 'once' : 'monthly');
            setShortage(next === 'transfer' ? 'skip' : 'partial');
        }
    };
    const chooseEvent = (id: number | null) => {
        setEventId(id);
        // A new withdrawal falls in the event's month unless a month was already chosen.
        const chosen = expenses.find((row) => row.id === id);
        if (chosen && !plan && period === defaultPeriod) setPeriod(chosen.target_date.slice(0, 7));
    };
    const interval = (): number | null => {
        if (frequency === 'once') return null;
        if (frequency === 'monthly') return 1;
        if (frequency === 'yearly') return 12;
        return Number(every) * (unit === 'years' ? 12 : 1);
    };
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy) return;
        const value = Number(amount || 0);
        const months = interval();
        const problems = [
            accountId === null && '口座を選んでください。',
            kind === 'transfer' && (toAccountId === null || toAccountId === accountId) && '振替元と別の振替先を選んでください。',
            kind === 'withdrawal' && eventId === null && 'ライフイベントを選んでください。',
            !PERIOD.test(period) && '開始月を入力してください。',
            (!Number.isFinite(value) || value < 0 || (kind !== 'contribution' && value <= 0)) && (kind === 'contribution' ? '金額は0以上で入力してください。' : '金額は0より大きく入力してください。'),
            months !== null && (!Number.isInteger(months) || months < 1 || months > 120) && '間隔は1〜120か月（10年）で入力してください。',
            repeated && ending === 'count' && !(Number.isInteger(Number(count)) && Number(count) >= 1 && Number(count) <= 1200) && '回数は1〜1200で入力してください。',
            repeated && ending === 'until' && !(PERIOD.test(until) && until >= period) && '終了月は開始月以降を入力してください。',
            kind === 'contribution' && rate.trim() !== '' && !Number.isFinite(Number(rate)) && '年利は数値か空欄です。',
        ].filter((message): message is string => Boolean(message));
        if (problems.length) {
            setError(problems[0]);
            return;
        }
        setError('');
        onSave({
            kind, account_id: accountId as number, to_account_id: kind === 'transfer' ? toAccountId : null, start_period: period, amount: value,
            interval_months: months, repeat_count: repeated && ending === 'count' ? Number(count) : null, end_period: repeated && ending === 'until' ? until : null,
            on_shortage: kind === 'contribution' ? null : shortage, annual_return: kind === 'contribution' && rate.trim() !== '' ? Number(rate) : null,
            note: note.trim() || null, life_event_id: kind === 'withdrawal' ? eventId : null,
        });
    };
    return <form id={form} onSubmit={submit} className="space-y-4">
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2"><OptionGroup label="レコードの種類" value={kind} onChange={chooseKind} options={[
                { value: 'contribution', label: '積立', description: 'この口座に入れます（給与からの積立など）。計画の作成では配分の行になります。' },
                { value: 'transfer', label: '口座振替', description: 'この口座からほかの口座へ移します。純資産は変わりません。計画の作成では、振替元を資金元とする振替先への配分の行になります。' },
                { value: 'withdrawal', label: 'ライフイベントへの取り崩し', description: 'この口座から引き出してライフイベントに充てます。イベントの月より前は確保、イベントの月からは支払い（老後の生活費のように毎月払うことも）です。計画の作成では、最初に取り崩す月まで口座ごとにゴールの取り置きとして積み立てます。' },
            ]} /></div>
            <Choice label={kind === 'transfer' ? '振替元の口座' : '口座'} help="積立設定のレコードにある口座が、このシナリオの使用口座です。" value={accountId} options={choices} required onChange={setAccountId} />
            {kind === 'transfer' && <Choice label="振替先の口座" value={toAccountId} options={destinations} required onChange={setToAccountId} />}
            {kind === 'withdrawal' && <Choice label="ライフイベント" help="このシナリオの支出のライフイベントです。口座から払えない分は残りの純資産から払います。" value={eventId} options={expenses} required onChange={chooseEvent} />}
            <Field label={`金額（1回あたり・${currency}）`}><input type="number" min="0" step="any" value={amount} placeholder="0" onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <Field label={repeated ? '開始月' : '月'} help={kind === 'withdrawal' ? 'ライフイベントの月が既定です。前もって引き出すこともできます（純資産は支払いの時点で減ります）。' : undefined}>
                <input required type="month" value={period} onChange={(event) => setPeriod(event.target.value)} className={inputClass} /></Field>
            <div className="sm:col-span-2"><OptionGroup label="頻度" value={frequency} onChange={setFrequency} options={[
                { value: 'once', label: '1回', description: 'その月に一度だけ行います。' },
                { value: 'monthly', label: '毎月', description: '開始月から毎月行います。' },
                { value: 'yearly', label: '毎年', description: '開始月から毎年同じ月に行います。' },
                { value: 'custom', label: '間隔を指定', description: '開始月から、指定した月数・年数ごとに行います。' },
            ]} /></div>
            {frequency === 'custom' && <Field label="間隔"><div className="flex gap-2">
                <input type="number" min="1" step="1" value={every} onChange={(event) => setEvery(event.target.value)} className={inputClass} />
                <select value={unit} onChange={(event) => setUnit(event.target.value as 'months' | 'years')} className={inputClass}><option value="months">か月ごと</option><option value="years">年ごと</option></select>
            </div></Field>}
            {repeated && <div className="sm:col-span-2"><OptionGroup label="終わり" help="終わりを決めないときは、シミュレーションの期間の終わりまで続けます。" value={ending} onChange={setEnding} options={[
                { value: 'none', label: '決めない', description: 'シミュレーションの期間の終わりまで続けます。' },
                { value: 'count', label: '回数', description: '指定した回数で終えます。' },
                { value: 'until', label: '終了月', description: '指定した月（その月を含む）まで行います。' },
            ]} /></div>}
            {repeated && ending === 'count' && <Field label="回数"><input type="number" min="1" max="1200" step="1" value={count} onChange={(event) => setCount(event.target.value)} className={inputClass} /></Field>}
            {repeated && ending === 'until' && <Field label="終了月"><input type="month" min={period} value={until} onChange={(event) => setUntil(event.target.value)} className={inputClass} /></Field>}
            {kind !== 'contribution' && <div className="sm:col-span-2"><OptionGroup label="口座の残高が足りないとき" help="足りない分をほかの口座から回すことはしません。取り崩しで払えない分は、ライフイベントの支払いとして残りの純資産から払います。" value={shortage} onChange={setShortage} options={[
                { value: 'skip', label: SHORTAGE_TEXT.skip, description: '残高が金額に満たない回は行いません。' },
                { value: 'partial', label: SHORTAGE_TEXT.partial, description: '残高の分だけ行います。' },
            ]} /></div>}
            {kind === 'contribution' && <Field label="年利（%）" help={`この口座の、開始月からの利回りです。空欄のときは、この口座の直前のレコードの年利（なければシナリオの既定 ${defaultRate}%）を引き継ぎます。`}><input inputMode="decimal" value={rate} placeholder="引き継ぐ" onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>}
            <div className="sm:col-span-2"><Field label="メモ"><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field></div>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} onDelete={onDelete} />
    </form>;
}
