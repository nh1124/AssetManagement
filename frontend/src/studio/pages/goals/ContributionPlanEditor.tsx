import { useId, useState, type FormEvent } from 'react';
import type { ContributionKind, ContributionPlan, ContributionPlanInput, ShortageMode } from '../../../api/lifeScenarios';
import type { LifeEvent } from '../../../types';
import { Choice, EditorActions, Feedback, Field, OptionGroup } from '../db/Database';
import { inputClass, type DatabaseAccount } from '../db/forms';
import { SHORTAGE_TEXT } from './contributionText';
import { tr } from '../../i18n';

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
            accountId === null && tr('口座を選んでください。', 'Choose an account.'),
            kind === 'transfer' && (toAccountId === null || toAccountId === accountId) && tr('振替元と別の振替先を選んでください。', 'Choose a different account to transfer to.'),
            kind === 'withdrawal' && eventId === null && tr('ライフイベントを選んでください。', 'Choose a life event.'),
            !PERIOD.test(period) && tr('開始月を入力してください。', 'Enter the start month.'),
            (!Number.isFinite(value) || value < 0 || (kind !== 'contribution' && value <= 0)) && (kind === 'contribution' ? tr('金額は0以上で入力してください。', 'Enter an amount of 0 or more.') : tr('金額は0より大きく入力してください。', 'Enter an amount above 0.')),
            months !== null && (!Number.isInteger(months) || months < 1 || months > 120) && tr('間隔は1〜120か月（10年）で入力してください。', 'Enter an interval from 1 to 120 months (10 years).'),
            repeated && ending === 'count' && !(Number.isInteger(Number(count)) && Number(count) >= 1 && Number(count) <= 1200) && tr('回数は1〜1200で入力してください。', 'Enter a count from 1 to 1200.'),
            repeated && ending === 'until' && !(PERIOD.test(until) && until >= period) && tr('終了月は開始月以降を入力してください。', 'The end month must be on or after the start month.'),
            kind === 'contribution' && rate.trim() !== '' && !Number.isFinite(Number(rate)) && tr('年利は数値か空欄です。', 'The return must be a number or empty.'),
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
            <div className="sm:col-span-2"><OptionGroup label={tr('レコードの種類', 'Kind of record')} value={kind} onChange={chooseKind} options={[
                { value: 'contribution', label: tr('積立', 'Contribution'), description: tr('この口座に入れます（給与からの積立など）。計画の作成では配分の行になります。', 'Puts money into this account (such as saving from pay). It becomes an allocation row when the plan is made.') },
                { value: 'transfer', label: tr('口座振替', 'Transfer'), description: tr('この口座からほかの口座へ移します。純資産は変わりません。計画の作成では、振替元を資金元とする振替先への配分の行になります。', 'Moves money from this account to another; net worth does not change. It becomes an allocation row to the destination, funded from this account, when the plan is made.') },
                { value: 'withdrawal', label: tr('ライフイベントへの取り崩し', 'Drawdown for a life event'), description: tr('この口座から引き出してライフイベントに充てます。イベントの月より前は確保、イベントの月からは支払い（老後の生活費のように毎月払うことも）です。計画の作成では、最初に取り崩す月まで口座ごとにゴールの取り置きとして積み立てます。', 'Takes money from this account for a life event: set aside before the event’s month and paid from it (monthly payments, like retirement living costs, are possible). When the plan is made, it is saved up as the goal’s earmark, account by account, until the first drawdown.') },
            ]} /></div>
            <Choice label={kind === 'transfer' ? tr('振替元の口座', 'Transfer from') : tr('口座', 'Account')} help={tr('積立設定のレコードにある口座が、このシナリオの使用口座です。', 'The accounts in the contribution settings are the accounts this scenario uses.')} value={accountId} options={choices} required onChange={setAccountId} />
            {kind === 'transfer' && <Choice label={tr('振替先の口座', 'Transfer to')} value={toAccountId} options={destinations} required onChange={setToAccountId} />}
            {kind === 'withdrawal' && <Choice label={tr('ライフイベント', 'Life event')} help={tr('このシナリオの支出のライフイベントです。口座から払えない分は残りの純資産から払います。', 'A spending life event in this scenario. Whatever the account cannot pay comes from the rest of net worth.')} value={eventId} options={expenses} required onChange={chooseEvent} />}
            <Field label={tr(`金額（1回あたり・${currency}）`, `Amount each time (${currency})`)}><input type="number" min="0" step="any" value={amount} placeholder="0" onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <Field label={repeated ? tr('開始月', 'Start month') : tr('月', 'Month')} help={kind === 'withdrawal' ? tr('ライフイベントの月が既定です。前もって引き出すこともできます（純資産は支払いの時点で減ります）。', 'The life event’s month by default. You can take it out earlier (net worth falls when it is paid).') : undefined}>
                <input required type="month" value={period} onChange={(event) => setPeriod(event.target.value)} className={inputClass} /></Field>
            <div className="sm:col-span-2"><OptionGroup label={tr('頻度', 'Frequency')} value={frequency} onChange={setFrequency} options={[
                { value: 'once', label: tr('1回', 'Once'), description: tr('その月に一度だけ行います。', 'Only once, in that month.') },
                { value: 'monthly', label: tr('毎月', 'Monthly'), description: tr('開始月から毎月行います。', 'Every month from the start month.') },
                { value: 'yearly', label: tr('毎年', 'Yearly'), description: tr('開始月から毎年同じ月に行います。', 'The same month every year from the start month.') },
                { value: 'custom', label: tr('間隔を指定', 'Custom interval'), description: tr('開始月から、指定した月数・年数ごとに行います。', 'Every given number of months or years from the start month.') },
            ]} /></div>
            {frequency === 'custom' && <Field label={tr('間隔', 'Interval')}><div className="flex gap-2">
                <input type="number" min="1" step="1" value={every} onChange={(event) => setEvery(event.target.value)} className={inputClass} />
                <select value={unit} onChange={(event) => setUnit(event.target.value as 'months' | 'years')} className={inputClass}><option value="months">{tr('か月ごと', 'months')}</option><option value="years">{tr('年ごと', 'years')}</option></select>
            </div></Field>}
            {repeated && <div className="sm:col-span-2"><OptionGroup label={tr('終わり', 'Ends')} help={tr('終わりを決めないときは、シミュレーションの期間の終わりまで続けます。', 'Without an end, it continues to the end of the simulation.')} value={ending} onChange={setEnding} options={[
                { value: 'none', label: tr('決めない', 'Never'), description: tr('シミュレーションの期間の終わりまで続けます。', 'Continues to the end of the simulation.') },
                { value: 'count', label: tr('回数', 'After a count'), description: tr('指定した回数で終えます。', 'Ends after the given number of times.') },
                { value: 'until', label: tr('終了月', 'In a month'), description: tr('指定した月（その月を含む）まで行います。', 'Runs until the given month (inclusive).') },
            ]} /></div>}
            {repeated && ending === 'count' && <Field label={tr('回数', 'Count')}><input type="number" min="1" max="1200" step="1" value={count} onChange={(event) => setCount(event.target.value)} className={inputClass} /></Field>}
            {repeated && ending === 'until' && <Field label={tr('終了月', 'End month')}><input type="month" min={period} value={until} onChange={(event) => setUntil(event.target.value)} className={inputClass} /></Field>}
            {kind !== 'contribution' && <div className="sm:col-span-2"><OptionGroup label={tr('口座の残高が足りないとき', 'When the balance is short')} help={tr('足りない分をほかの口座から回すことはしません。取り崩しで払えない分は、ライフイベントの支払いとして残りの純資産から払います。', 'The shortfall is never taken from other accounts. Whatever a drawdown cannot pay is paid for the life event from the rest of net worth.')} value={shortage} onChange={setShortage} options={[
                { value: 'skip', label: SHORTAGE_TEXT.skip, description: tr('残高が金額に満たない回は行いません。', 'Skips any time the balance is below the amount.') },
                { value: 'partial', label: SHORTAGE_TEXT.partial, description: tr('残高の分だけ行います。', 'Moves only what the balance holds.') },
            ]} /></div>}
            {kind === 'contribution' && <Field label={tr('年利（%）', 'Annual return (%)')} help={tr(`この口座の、開始月からの利回りです。空欄のときは、この口座の直前のレコードの年利（なければシナリオの既定 ${defaultRate}%）を引き継ぎます。`, `This account’s return from the start month. When empty, it carries over the return of the account’s previous record (or the scenario default, ${defaultRate}%).`)}><input inputMode="decimal" value={rate} placeholder={tr('引き継ぐ', 'Carry over')} onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>}
            <div className="sm:col-span-2"><Field label={tr('メモ', 'Note')}><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field></div>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} onDelete={onDelete} />
    </form>;
}
