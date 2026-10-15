import { useConfirm } from '../../components/useConfirm';
import Overlay, { OverlayFooter } from '../../components/Overlay';
import { useCallback, useId, useState, type FormEvent } from 'react';
import { applyPeriodReportAction, getPeriodReport, getPeriodReview, getProfitLoss, savePeriodReview } from '../../../api';
import { useClient } from '../../../context/ClientContext';
import type { PeriodReview } from '../../../types';
import { useResource } from '../../useResource';
import { Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';
import { currentMonth, monthRange } from '../ledger/periods';
import { ReportContext, ReportFigures, ReportProposals, type ProfitLoss } from './ReportReading';

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
        <fieldset disabled={disabled || mutation.busy || !clientName} className="space-y-5">
            <Field label="振り返り"><textarea rows={9} value={reflection} onChange={(event) => updateReflection(event.target.value)} className={inputClass} placeholder="この期間のお金の使い方や変化で、何が印象に残りましたか？" /></Field>
            <Field label="次の行動"><textarea rows={7} value={nextActions} onChange={(event) => updateNextActions(event.target.value)} className={inputClass} placeholder="続けたいこと、見直したいこと、次に試すこと" /></Field>
            <div className="flex flex-wrap items-center gap-3"><OverlayFooter><button type="submit" form={formId} disabled={disabled || mutation.busy || !clientName || !dirty} className={primaryClass}>{mutation.busy ? '保存中…' : '振り返りを保存'}</button></OverlayFooter><span className="text-xs text-[var(--studio-text-muted)]">{dirty ? '未保存の変更があります' : saved.id === 0 ? 'まだ記入されていません' : '保存済みの内容です'}</span></div>
        </fieldset>
        <Feedback error={mutation.error} message={mutation.message} />
    </form>;
}

function PeriodReading({ period, currency, clientName, onBusy, onDirty }: {
    period: Period; currency: string; clientName?: string; onBusy: (busy: boolean) => void; onDirty: (dirty: boolean) => void;
}) {
    const { startDate, endDate } = period;
    const loadReview = useCallback(() => getPeriodReview(startDate, endDate), [startDate, endDate]);
    const loadReport = useCallback(() => getPeriodReport(startDate, endDate), [startDate, endDate]);
    const loadProfitLoss = useCallback((): Promise<ProfitLoss> => getProfitLoss(undefined, undefined, false, startDate, endDate), [startDate, endDate]);
    const review = useResource(loadReview);
    const report = useResource(loadReport);
    const profitLoss = useResource(loadProfitLoss);
    const [busy, setBusy] = useState(false);
    const [editing, setEditing] = useState(false);
    const lock = (value: boolean) => { setBusy(value); onBusy(value); };
    const refreshReport = () => { report.reload(); profitLoss.reload(); };
    return <div className="space-y-4">
        <div className="grid items-start gap-6 xl:grid-cols-2">
            <section className="min-w-0 space-y-3">
                <Feedback loading={review.loading} error={review.error} />
                {review.error && <button type="button" disabled={review.loading} onClick={review.reload} className={buttonClass}>振り返りを再取得</button>}
                {review.data && <>
                    <div className="space-y-4 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
                        <h2 className="text-lg font-semibold">数字を見ながら振り返る</h2>
                        <dl className="space-y-4 text-sm"><div><dt className="text-[var(--studio-text-muted)]">振り返り</dt><dd className="mt-2 whitespace-pre-wrap">{review.data.reflection || 'まだ記入されていません'}</dd></div><div><dt className="text-[var(--studio-text-muted)]">次の行動</dt><dd className="mt-2 whitespace-pre-wrap">{review.data.next_actions || 'まだ記入されていません'}</dd></div></dl>
                        <button type="button" disabled={busy || review.loading || Boolean(review.error) || !clientName} onClick={() => setEditing(true)} className={buttonClass}>振り返りを編集</button>
                    </div>
                    {editing && <Overlay title="振り返りを編集" onClose={() => { setEditing(false); onDirty(false); }}>
                        <ReviewEditor initial={review.data} clientName={clientName} disabled={busy || review.loading || Boolean(review.error)} onBusy={lock} onDirty={onDirty} onSaved={(saved) => { review.setData(saved); setEditing(false); }} />
                    </Overlay>}
                </>}
            </section>
            <section className="min-w-0 space-y-6">
                <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">この期間の全体像</h2></div>
                <Feedback loading={report.loading} error={report.error} />
                <Feedback loading={profitLoss.loading} error={profitLoss.error} />
                {report.data && <>
                    <ReportFigures report={report.data} profitLoss={profitLoss.data} currency={currency} />
                    <ReportContext report={report.data} currency={currency} />
                    <ReportProposals report={report.data} currency={currency} clientName={clientName} disabled={busy || report.loading || Boolean(report.error)} apply={(id) => applyPeriodReportAction(startDate, endDate, id)} onApplied={refreshReport} onBusy={lock} />
                </>}
            </section>
        </div>
    </div>;
}

function ReviewForClient({ currency, clientName }: { currency: string; clientName?: string }) {
    const confirm = useConfirm();
    const [period, setPeriod] = useState<Period>(() => monthRange(currentMonth()));
    const [draft, setDraft] = useState(period);
    const [busy, setBusy] = useState(false);
    const [dirty, setDirty] = useState(false);
    const valid = /^\d{4}-\d{2}-\d{2}$/.test(draft.startDate) && /^\d{4}-\d{2}-\d{2}$/.test(draft.endDate) && draft.startDate <= draft.endDate;
    const choose = async (next: Period) => {
        if (busy || next.startDate > next.endDate) return;
        if (next.startDate !== period.startDate || next.endDate !== period.endDate) {
            // Changing the period remounts the editor, so warn before discarding an unsaved draft.
            if (dirty && !(await confirm('未保存の振り返りがあります。変更を破棄して、別の期間を表示しますか？', '破棄して表示する'))) return;
            setDirty(false);
            setPeriod(next);
        }
        setDraft(next);
    };
    const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (valid) choose(draft); };
    const year = currentMonth().slice(0, 4);
    return <section className="space-y-6">
        <form onSubmit={submit} className="space-y-3">
            <fieldset disabled={busy} className="flex flex-wrap items-end gap-3">
                <Field label="開始日"><input required type="date" value={draft.startDate} max={draft.endDate || undefined} onChange={(event) => setDraft({ ...draft, startDate: event.target.value })} className={inputClass} /></Field>
                <Field label="終了日"><input required type="date" value={draft.endDate} min={draft.startDate || undefined} onChange={(event) => setDraft({ ...draft, endDate: event.target.value })} className={inputClass} /></Field>
                <button type="submit" disabled={!valid} className={primaryClass}>この期間を表示</button>
                <button type="button" onClick={() => choose(monthRange(currentMonth()))} className={buttonClass}>今月</button>
                <button type="button" onClick={() => choose({ startDate: `${year}-01-01`, endDate: `${year}-12-31` })} className={buttonClass}>今年</button>
            </fieldset>
            {!valid && <p role="alert" className="text-sm text-[var(--studio-danger)]">開始日と終了日を入力し、終了日を開始日以降にしてください。</p>}
        </form>
        <PeriodReading key={`${period.startDate}:${period.endDate}`} period={period} currency={currency} clientName={clientName} onBusy={setBusy} onDirty={setDirty} />
    </section>;
}

export default function Review() {
    const { clientId, currentClient } = useClient();
    const currency = currentClient?.general_settings?.currency || 'JPY';
    // Client changes discard loaded notes and proposals before a write can use the previous identity.
    return <ReviewForClient key={`${clientId}:${currency}`} currency={currency} clientName={currentClient?.id === clientId ? currentClient.name : undefined} />;
}
