import { useId, useState, type FormEvent } from 'react';
import type { AssumptionPeriod, AssumptionPeriodInput } from '../../../api/lifeScenarios';
import { EditorActions, Feedback, Field } from '../db/Database';
import { inputClass } from '../db/forms';

const PERIOD = /^\d{4}-(0[1-9]|1[0-2])$/;

/** One 期間ごとの前提 record: the scenario's default yield and/or inflation from a month, until a month or open. */
export default function AssumptionPeriodEditor({ period, defaultPeriod, defaultRate, defaultInflation, busy, onSave, onCancel, onDelete }: {
    period: AssumptionPeriod | null; defaultPeriod: string; defaultRate: number; defaultInflation: number; busy: boolean;
    onSave: (input: AssumptionPeriodInput) => void; onCancel: () => void; onDelete?: () => void;
}) {
    const form = useId();
    const [start, setStart] = useState(period?.start_period ?? defaultPeriod);
    const [end, setEnd] = useState(period?.end_period ?? '');
    const [rate, setRate] = useState(period?.annual_return == null ? '' : String(period.annual_return));
    const [inflation, setInflation] = useState(period?.inflation == null ? '' : String(period.inflation));
    const [note, setNote] = useState(period?.note ?? '');
    const [error, setError] = useState('');
    const number = (value: string) => value.trim() === '' ? null : Number(value);
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy) return;
        const values = [number(rate), number(inflation)];
        const problems = [
            !PERIOD.test(start) && '開始月を入力してください。',
            end !== '' && !(PERIOD.test(end) && end >= start) && '終了月は開始月以降を入力してください。',
            values.every((value) => value === null) && '年利かインフレのどちらかを入力してください。',
            values.some((value) => value !== null && !Number.isFinite(value)) && '年利・インフレは数値か空欄です。',
        ].filter((message): message is string => Boolean(message));
        if (problems.length) {
            setError(problems[0]);
            return;
        }
        setError('');
        onSave({ start_period: start, end_period: end || null, annual_return: values[0], inflation: values[1], note: note.trim() || null });
    };
    return <form id={form} onSubmit={submit} className="space-y-4">
        <Feedback error={error} />
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <Field label="開始月"><input required type="month" value={start} onChange={(event) => setStart(event.target.value)} className={inputClass} /></Field>
            <Field label="終了月" help="空欄のときは、シミュレーションの期間の終わりまでです。"><input type="month" min={start} value={end} onChange={(event) => setEnd(event.target.value)} className={inputClass} /></Field>
            <Field label="既定の年利（%）" help={`この期間の、積立設定に年利のない口座の利回りです。空欄のときはシナリオの前提（${defaultRate}%）か、重なるほかのレコードの値です。`}>
                <input inputMode="decimal" value={rate} placeholder="変えない" onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>
            <Field label="インフレ（%）" help={`この期間のインフレです。空欄のときはシナリオの前提（${defaultInflation}%）か、重なるほかのレコードの値です。`}>
                <input inputMode="decimal" value={inflation} placeholder="変えない" onChange={(event) => setInflation(event.target.value)} className={inputClass} /></Field>
            <div className="sm:col-span-2"><Field label="メモ"><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field></div>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} onDelete={onDelete} />
    </form>;
}
