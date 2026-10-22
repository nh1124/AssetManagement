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
import { tr } from '../../i18n';

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
        }, tr('振り返りを保存しました。', 'Review saved.'), () => {
            setSaved(savedReview);
            onDirty(false);
            onSaved(savedReview);
        }).finally(() => onBusy(false));
    };
    return <form id={formId} onSubmit={submit} className="space-y-5 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <div className="text-sm text-[var(--studio-text-muted)]">{tr(`${initial.start_date} 〜 ${initial.end_date}`, `${initial.start_date} to ${initial.end_date}`)}</div>
        <fieldset disabled={disabled || mutation.busy || !clientName} className="space-y-5">
            <Field label={tr('振り返り', 'Review')}><textarea rows={9} value={reflection} onChange={(event) => updateReflection(event.target.value)} className={inputClass} placeholder={tr('この期間のお金の使い方や変化で、何が印象に残りましたか？', 'What stood out about how you used money in this period?')} /></Field>
            <Field label={tr('次の行動', 'Next steps')}><textarea rows={7} value={nextActions} onChange={(event) => updateNextActions(event.target.value)} className={inputClass} placeholder={tr('続けたいこと、見直したいこと、次に試すこと', 'What to keep, what to change, what to try next')} /></Field>
            <div className="flex flex-wrap items-center gap-3"><OverlayFooter><button type="submit" form={formId} disabled={disabled || mutation.busy || !clientName || !dirty} className={primaryClass}>{mutation.busy ? tr('保存中…', 'Saving…') : tr('振り返りを保存', 'Save review')}</button></OverlayFooter><span className="text-xs text-[var(--studio-text-muted)]">{dirty ? tr('未保存の変更があります', 'Unsaved changes') : saved.id === 0 ? tr('まだ記入されていません', 'Nothing written yet') : tr('保存済みの内容です', 'Saved')}</span></div>
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
        if (dirty && !(await confirm(tr('未保存の振り返りがあります。変更を破棄して閉じますか？', 'Your review has unsaved changes. Discard them and close?'), tr('破棄して閉じる', 'Discard and close')))) return;
        setEditing(false);
        markDirty(false);
    };
    return <section className="min-w-0 space-y-3">
        <h2 className="text-lg font-semibold">{tr(`${startDate} 〜 ${endDate}`, `${startDate} to ${endDate}`)}</h2>
        <Feedback loading={review.loading} error={review.error} />
        {review.error && <button type="button" disabled={review.loading} onClick={review.reload} className={buttonClass}>{tr('振り返りを再取得', 'Reload the review')}</button>}
        {review.data && <>
            <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                <dl className="space-y-4 text-sm"><div><dt className="text-[var(--studio-text-muted)]">{tr('振り返り', 'Review')}</dt><dd className="mt-2 whitespace-pre-wrap">{review.data.reflection || tr('まだ記入されていません', 'Nothing written yet')}</dd></div><div><dt className="text-[var(--studio-text-muted)]">{tr('次の行動', 'Next steps')}</dt><dd className="mt-2 whitespace-pre-wrap">{review.data.next_actions || tr('まだ記入されていません', 'Nothing written yet')}</dd></div></dl>
                <div className="flex justify-end"><button type="button" disabled={busy || review.loading || Boolean(review.error) || !clientName} onClick={() => setEditing(true)} className={buttonClass}>{tr('振り返りを編集', 'Edit the review')}</button></div>
            </div>
            {editing && <Overlay title={tr('振り返りを編集', 'Edit the review')} busy={busy} onClose={() => { void closeEditor(); }}>
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
            if (dirty && !(await confirm(tr('未保存の振り返りがあります。変更を破棄して、別の期間を表示しますか？', 'Your review has unsaved changes. Discard them and show another period?'), tr('破棄して表示する', 'Discard and show')))) return;
            setDirty(false);
            setPeriod(next);
        }
        if (selectedMonths !== undefined) setMonths(selectedMonths);
    };
    return <section className="space-y-6">
        <PeriodSelector months={months} onChange={(value) => { void choose(lastMonthsRange(value), value); }} disabled={busy} />
        <PeriodReading key={`review:${period.startDate}:${period.endDate}`} period={period} clientName={clientName} onBusy={setBusy} onDirty={setDirty} onSaved={reviews.reload} />
        <section className="space-y-3">
            <h2 className="text-lg font-semibold">{tr('過去の振り返り', 'Past reviews')}</h2>
            <Feedback loading={reviews.loading} error={reviews.error} />
            {reviews.error && <button type="button" disabled={reviews.loading} onClick={reviews.reload} className={buttonClass}>{tr('過去の振り返りを再取得', 'Reload past reviews')}</button>}
            {reviews.data && <DataTable columns={[tr('期間', 'Period'), tr('振り返り', 'Review')]}>
                {reviews.data.length ? reviews.data.map((row) => <tr key={row.id} onClick={() => { void choose({ startDate: row.start_date, endDate: row.end_date }); }} className={busy ? '' : 'cursor-pointer hover:bg-[var(--studio-accent-soft)] focus-within:bg-[var(--studio-accent-soft)]'}>
                    <th scope="row" className="whitespace-nowrap px-5 py-3 font-medium">
                        <button type="button" disabled={busy} onClick={(event) => { event.stopPropagation(); void choose({ startDate: row.start_date, endDate: row.end_date }); }} className="rounded text-left hover:text-[var(--studio-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)] disabled:opacity-40">{row.label}</button>
                    </th>
                    <td className="px-5 py-3"><div className="max-w-lg truncate">{row.reflection.split(/\r?\n/, 1)[0] || '—'}</div></td>
                </tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">{tr('保存された振り返りはありません。', 'No saved reviews.')}</td></tr>}
            </DataTable>}
        </section>
    </section>;
}

export default function Review() {
    const { clientId, currentClient } = useClient();
    // Client changes discard loaded notes before a write can use the previous identity.
    return <ReviewForClient key={clientId} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
