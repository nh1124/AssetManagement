import { useConfirm } from '../../components/useConfirm';
import Overlay, { OverlayFooter } from '../../components/Overlay';
import { useCallback, useId, useState, type FormEvent } from 'react';
import { getPeriodReview, listPeriodReviews, savePeriodReview } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { PeriodReview } from '../../../types';
import { useResource } from '../../useResource';
import { DataTable, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';
import { lastMonthsRange } from '../ledger/periods';
import PeriodSelector from './PeriodSelector';

interface Period { startDate: string; endDate: string }

function ReviewEditor({ initial, clientName, disabled, onBusy, onDirty, onSaved }: {
    initial: PeriodReview; clientName?: string; disabled: boolean;
    onBusy: (busy: boolean) => void; onDirty: (dirty: boolean) => void;
    onSaved: (review: PeriodReview) => void;
}) {
    const formId = useId();
    const [reflection, setReflection] = useState(initial.reflection);
    const [nextActions, setNextActions] = useState(initial.next_actions);
    const [saved, setSaved] = useState(initial);
    const mutation = useMutation();
    const dirty = reflection !== saved.reflection || nextActions !== saved.next_actions;
    const updateReflection = (value: string) => { setReflection(value); onDirty(value !== saved.reflection || nextActions !== saved.next_actions); };
    const updateNextActions = (value: string) => { setNextActions(value); onDirty(reflection !== saved.reflection || value !== saved.next_actions); };
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (disabled || mutation.busy || !clientName || !dirty) return;
        const payload = { start_date: initial.start_date, end_date: initial.end_date, label: initial.label, reflection, next_actions: nextActions };
        let savedReview = saved;
        onBusy(true);
        void mutation.run(async () => {
            savedReview = await savePeriodReview(payload);
        }, '振り返りを保存しました。', () => {
            setSaved(savedReview);
            onDirty(false);
            onSaved(savedReview);
        }).finally(() => onBusy(false));
    };
    return <form id={formId} onSubmit={submit} className="space-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <div className="text-sm text-[var(--studio-text-muted)]">{initial.start_date} 〜 {initial.end_date}</div>
        <fieldset disabled={disabled || mutation.busy || !clientName} className="space-y-5">
            <Field label="振り返り"><textarea rows={9} value={reflection} onChange={(event) => updateReflection(event.target.value)} className={inputClass} placeholder="この期間のお金の使い方や変化で、何が印象に残りましたか？" /></Field>
            <Field label="次の行動"><textarea rows={7} value={nextActions} onChange={(event) => updateNextActions(event.target.value)} className={inputClass} placeholder="続けたいこと、見直したいこと、次に試すこと" /></Field>
            <div className="flex flex-wrap items-center gap-3"><OverlayFooter><button type="submit" form={formId} disabled={disabled || mutation.busy || !clientName || !dirty} className={primaryClass}>{mutation.busy ? '保存中…' : '振り返りを保存'}</button></OverlayFooter><span className="text-xs text-[var(--studio-text-muted)]">{dirty ? '未保存の変更があります' : saved.id === 0 ? 'まだ記入されていません' : '保存済みの内容です'}</span></div>
        </fieldset>
        <Feedback error={mutation.error} message={mutation.message} />
    </form>;
}

function PeriodReading({ period, clientName, onBusy, onDirty, onSaved }: {
    period: Period; clientName?: string; onBusy: (busy: boolean) => void; onDirty: (dirty: boolean) => void;
    onSaved: () => void;
}) {
    const confirm = useConfirm();
    const { startDate, endDate } = period;
    const loadReview = useCallback(() => getPeriodReview(startDate, endDate), [startDate, endDate]);
    const review = useResource(loadReview);
    const [busy, setBusy] = useState(false);
    const [editing, setEditing] = useState(false);
    const [dirty, setDirty] = useState(false);
    const lock = (value: boolean) => { setBusy(value); onBusy(value); };
    // Keep the period-change warning in sync with the draft's close warning.
    const markDirty = (value: boolean) => { setDirty(value); onDirty(value); };
    const closeEditor = async () => {
        if (dirty && !(await confirm('未保存の振り返りがあります。変更を破棄して閉じますか？', '破棄して閉じる'))) return;
        setEditing(false);
        markDirty(false);
    };
    return <section className="min-w-0 space-y-3">
        <h2 className="text-lg font-semibold">{startDate} 〜 {endDate}</h2>
        <Feedback loading={review.loading} error={review.error} />
        {review.error && <button type="button" disabled={review.loading} onClick={review.reload} className={buttonClass}>振り返りを再取得</button>}
        {review.data && <>
            <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                <dl className="space-y-4 text-sm"><div><dt className="text-[var(--studio-text-muted)]">振り返り</dt><dd className="mt-2 whitespace-pre-wrap">{review.data.reflection || 'まだ記入されていません'}</dd></div><div><dt className="text-[var(--studio-text-muted)]">次の行動</dt><dd className="mt-2 whitespace-pre-wrap">{review.data.next_actions || 'まだ記入されていません'}</dd></div></dl>
                <div className="flex justify-end"><button type="button" disabled={busy || review.loading || Boolean(review.error) || !clientName} onClick={() => setEditing(true)} className={buttonClass}>振り返りを編集</button></div>
            </div>
            {editing && <Overlay title="振り返りを編集" busy={busy} onClose={() => { void closeEditor(); }}>
                <ReviewEditor initial={review.data} clientName={clientName} disabled={busy || review.loading || Boolean(review.error)} onBusy={lock} onDirty={markDirty} onSaved={(saved) => { review.setData(saved); setEditing(false); onSaved(); }} />
            </Overlay>}
        </>}
    </section>;
}

function ReviewForClient({ clientName }: { clientName?: string }) {
    const confirm = useConfirm();
    const [months, setMonths] = useState(12);
    // Relative selectors move each calendar month; saved ranges must stay reachable through history.
    const [period, setPeriod] = useState<Period>(() => lastMonthsRange(12));
    const [busy, setBusy] = useState(false);
    const [dirty, setDirty] = useState(false);
    const reviews = useResource(listPeriodReviews);
    const choose = async (next: Period, selectedMonths?: number) => {
        if (busy || next.startDate > next.endDate) return;
        if (next.startDate !== period.startDate || next.endDate !== period.endDate) {
            // Changing the period remounts the editor, so warn before discarding an unsaved draft.
            if (dirty && !(await confirm('未保存の振り返りがあります。変更を破棄して、別の期間を表示しますか？', '破棄して表示する'))) return;
            setDirty(false);
            setPeriod(next);
        }
        if (selectedMonths !== undefined) setMonths(selectedMonths);
    };
    return <section className="space-y-6">
        <PeriodSelector months={months} onChange={(value) => { void choose(lastMonthsRange(value), value); }} disabled={busy} />
        <PeriodReading key={`review:${period.startDate}:${period.endDate}`} period={period} clientName={clientName} onBusy={setBusy} onDirty={setDirty} onSaved={reviews.reload} />
        <section className="space-y-3">
            <h2 className="text-lg font-semibold">過去の振り返り</h2>
            <Feedback loading={reviews.loading} error={reviews.error} />
            {reviews.error && <button type="button" disabled={reviews.loading} onClick={reviews.reload} className={buttonClass}>過去の振り返りを再取得</button>}
            {reviews.data && <DataTable columns={['期間', '振り返り']}>
                {reviews.data.length ? reviews.data.map((row) => <tr key={row.id} onClick={() => { void choose({ startDate: row.start_date, endDate: row.end_date }); }} className={busy ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]'}>
                    <th scope="row" className="whitespace-nowrap px-5 py-3 font-medium">
                        <button type="button" disabled={busy} onClick={(event) => { event.stopPropagation(); void choose({ startDate: row.start_date, endDate: row.end_date }); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{row.label}</button>
                    </th>
                    <td className="px-5 py-3"><div className="max-w-lg truncate">{row.reflection.split(/\r?\n/, 1)[0] || '—'}</div></td>
                </tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">保存された振り返りはありません。</td></tr>}
            </DataTable>}
        </section>
    </section>;
}

export default function Review() {
    const { clientId, currentClient } = useClient();
    // Client changes discard loaded notes before a write can use the previous identity.
    return <ReviewForClient key={clientId} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
