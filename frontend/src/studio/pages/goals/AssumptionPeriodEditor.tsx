import { useId, useState, type FormEvent } from 'react';
import type { AssumptionPeriod, AssumptionPeriodInput } from '../../../api/lifeScenarios';
import { EditorActions, Feedback, Field } from '../db/Database';
import { inputClass } from '../db/forms';
import { tr } from '../../i18n';

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
            !PERIOD.test(start) && tr('開始月を入力してください。', 'Enter the start month.'),
            end !== '' && !(PERIOD.test(end) && end >= start) && tr('終了月は開始月以降を入力してください。', 'The end month must be on or after the start month.'),
            values.every((value) => value === null) && tr('年利かインフレのどちらかを入力してください。', 'Enter a return or an inflation rate.'),
            values.some((value) => value !== null && !Number.isFinite(value)) && tr('年利・インフレは数値か空欄です。', 'The return and inflation must be numbers or empty.'),
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
            <Field label={tr('開始月', 'Start month')}><input required type="month" value={start} onChange={(event) => setStart(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('終了月', 'End month')} help={tr('空欄のときは、シミュレーションの期間の終わりまでです。', 'When empty, it runs to the end of the simulation.')}><input type="month" min={start} value={end} onChange={(event) => setEnd(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('既定の年利（%）', 'Default return (%)')} help={tr(`この期間の、積立設定に年利のない口座の利回りです。空欄のときはシナリオの前提（${defaultRate}%）か、重なるほかのレコードの値です。`, `The return in this period for accounts without one in the contribution settings. When empty, the scenario’s assumption (${defaultRate}%) or an overlapping record applies.`)}>
                <input inputMode="decimal" value={rate} placeholder={tr('変えない', 'Unchanged')} onChange={(event) => setRate(event.target.value)} className={inputClass} /></Field>
            <Field label={tr('インフレ（%）', 'Inflation (%)')} help={tr(`この期間のインフレです。空欄のときはシナリオの前提（${defaultInflation}%）か、重なるほかのレコードの値です。`, `Inflation in this period. When empty, the scenario’s assumption (${defaultInflation}%) or an overlapping record applies.`)}>
                <input inputMode="decimal" value={inflation} placeholder={tr('変えない', 'Unchanged')} onChange={(event) => setInflation(event.target.value)} className={inputClass} /></Field>
            <div className="sm:col-span-2"><Field label={tr('メモ', 'Note')}><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field></div>
        </fieldset>
        <EditorActions form={form} busy={busy} onCancel={onCancel} onDelete={onDelete} />
    </form>;
}
