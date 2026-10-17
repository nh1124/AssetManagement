import Overlay from '../../components/Overlay';
import { useConfirm } from '../../components/useConfirm';
import { useCallback, useId, useState, type FormEvent } from 'react';
import { applyMilestonesFromSimulation, createMilestone, deleteMilestone, getMilestones, previewMilestonesFromSimulation, updateMilestone } from '../../../api';
import type { Milestone, MilestoneSimulationBasis, MilestoneSimulationInterval, MilestoneSimulationMode, MilestoneSimulationPreview } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { useResource } from '../../useResource';
import { DataTable, EditorActions, Feedback, Field, RowActions } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';
import { useScenario } from './scenarioContext';
import { clientToday, formatDate, useTimezone } from '../../datetime';

function MilestoneEditor({ row, goalId, currency, busy, onSave, onCancel }: {
    row: Milestone | null; goalId: number; currency: string; busy: boolean;
    onSave: (action: () => Promise<unknown>) => void; onCancel: () => void;
}) {
    const formId = useId();
    const timezone = useTimezone();
    const [date, setDate] = useState(row?.date ?? clientToday(timezone));
    const [amount, setAmount] = useState(String(row?.target_amount ?? 0));
    const [note, setNote] = useState(row?.note ?? '');
    const [active, setActive] = useState(row?.is_active_plan !== false);
    const submit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (busy) return;
        const payload = { date, target_amount: Number(amount), note: note.trim(), is_active_plan: active };
        onSave(() => row ? updateMilestone(row.id, payload) : createMilestone({ ...payload, life_event_id: goalId }));
    };
    return <form id={formId} onSubmit={submit} className="rounded-lg border border-[var(--studio-border)] p-5">
        <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
            <Field label="予定日"><input required type="date" value={date} onChange={(event) => setDate(event.target.value)} className={inputClass} /></Field>
            <Field label={`計画額（${currency}）`}><input required type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} className={inputClass} /></Field>
            <Field label="メモ"><input value={note} onChange={(event) => setNote(event.target.value)} className={inputClass} /></Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />進捗計算に採用する</label>
            <EditorActions form={formId} busy={busy} onCancel={onCancel} />
        </fieldset>
    </form>;
}

const INTERVALS: Array<[MilestoneSimulationInterval, string]> = [
    ['annual', '毎年'], ['semiannual', '半年ごと'], ['quarterly', '四半期ごと'], ['target_only', '目標日のみ'],
];
const BASES: Array<[MilestoneSimulationBasis, string]> = [
    ['p50', '中央値（P50）'], ['p10', '慎重（P10）'], ['p90', '楽観（P90）'], ['deterministic', '一定利回り'],
];

function MilestoneAutoCreate({ goalId, currency, existingCount, onClose, onCreated }: {
    goalId: number; currency: string; existingCount: number; onClose: () => void; onCreated: () => void;
}) {
    const { scenario } = useScenario();
    const mutation = useMutation();
    const [interval, setInterval] = useState<MilestoneSimulationInterval>('annual');
    const [basis, setBasis] = useState<MilestoneSimulationBasis>('p50');
    const [mode, setMode] = useState<MilestoneSimulationMode>('replace');
    const [preview, setPreview] = useState<MilestoneSimulationPreview | null>(null);
    // The milestones follow the scenario this event belongs to.
    const request = { interval, basis, mode, n_simulations: 1000, annual_return: scenario.annual_return, inflation: scenario.inflation };
    // Any change of choice discards the preview, so what is applied is what was shown.
    const choose = <T,>(set: (value: T) => void) => (value: T) => { set(value); setPreview(null); };
    const runPreview = () => {
        let result: MilestoneSimulationPreview | null = null;
        void mutation.run(async () => { result = await previewMilestonesFromSimulation(goalId, request); }, '', () => setPreview(result));
    };
    const apply = () => {
        if (!preview) return;
        void mutation.run(() => applyMilestonesFromSimulation(goalId, request), 'マイルストーンを作成しました。', () => { onCreated(); onClose(); });
    };
    const radio = <T extends string>(name: string, value: T, options: Array<[T, string]>, onChange: (value: T) => void) => <fieldset className="space-y-2">
        <legend className="text-sm text-[var(--studio-text-muted)]">{name}</legend>
        <div className="flex flex-wrap gap-3">{options.map(([key, label]) => <label key={`${name}-${key}`} className="flex items-center gap-2 text-sm">
            <input type="radio" name={name} checked={value === key} onChange={() => onChange(key)} />{label}
        </label>)}</div>
    </fieldset>;
    return <Overlay title="マイルストーンを自動で作成" onClose={() => { if (!mutation.busy) onClose(); }}
        footer={<>
            <button type="button" disabled={mutation.busy} onClick={runPreview} className={buttonClass}>プレビュー</button>
            <button type="button" disabled={mutation.busy || !preview} onClick={apply} className={primaryClass}>作成する</button>
        </>}>
        <div className="space-y-4">
            <Feedback error={mutation.error} />
            <fieldset disabled={mutation.busy} className="space-y-4">
                {radio('粒度', interval, INTERVALS, choose(setInterval))}
                {radio('基準', basis, BASES, choose(setBasis))}
                {radio(`既存のマイルストーン（${existingCount}件）`, mode, [['replace', '置き換える'], ['add', '追加する']], choose(setMode))}
            </fieldset>
            {preview && <DataTable columns={['予定日', '計画額']}>
                {preview.items.length ? preview.items.map((item, index) => <tr key={`preview-${index}-${item.date}`}>
                    <th scope="row" className="whitespace-nowrap px-5 py-3 font-normal">{formatDate(item.date)}</th>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(item.target_amount, currency)}</td>
                </tr>) : <tr><td colSpan={2} className="px-5 py-4 text-[var(--studio-text-muted)]">作成されるマイルストーンはありません。</td></tr>}
            </DataTable>}
        </div>
    </Overlay>;
}

export default function Milestones({ goalId, currency, disabled, onChanged, onBusy }: {
    goalId: number; currency: string; disabled: boolean; onChanged: () => void; onBusy: (busy: boolean) => void;
}) {
    const confirm = useConfirm();
    const load = useCallback(() => getMilestones(goalId), [goalId]);
    const resource = useResource(load);
    const mutation = useMutation();
    const [editor, setEditor] = useState<{ row: Milestone | null } | null>(null);
    const [autoCreating, setAutoCreating] = useState(false);
    const locked = disabled || resource.loading || Boolean(resource.error) || mutation.busy;
    const run = (action: () => Promise<unknown>, message: string, close = false) => {
        if (locked) return;
        onBusy(true);
        void mutation.run(action, message, () => { if (close) setEditor(null); resource.reload(); onChanged(); }).finally(() => onBusy(false));
    };
    return <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2">
            <button type="button" disabled={locked || editor !== null} onClick={() => setEditor({ row: null })} className={buttonClass}>新しいマイルストーン</button>
            <button type="button" disabled={locked || editor !== null || autoCreating} onClick={() => setAutoCreating(true)} className={buttonClass}>自動で作成</button>
        </div></div>
        <Feedback loading={resource.loading} error={resource.error} />
        <Feedback error={mutation.error} message={mutation.message} />
        {autoCreating && <MilestoneAutoCreate goalId={goalId} currency={currency} existingCount={resource.data?.length ?? 0} onClose={() => setAutoCreating(false)} onCreated={() => { resource.reload(); onChanged(); }} />}
        {editor && <Overlay title={editor.row ? 'マイルストーンを編集' : '新しいマイルストーン'} onClose={() => setEditor(null)}><Feedback error={mutation.error} /><MilestoneEditor key={editor.row?.id ?? 'new'} row={editor.row} goalId={goalId} currency={currency} busy={locked} onCancel={() => setEditor(null)} onSave={(action) => run(action, 'マイルストーンを保存しました。', true)} /></Overlay>}
        {resource.data && <DataTable columns={['予定日', '計画額', 'メモ', '進捗計算に採用', '操作']}>
            {resource.data.length ? resource.data.map((row) => <tr key={row.id}>
                <th scope="row" className="whitespace-nowrap px-5 py-3 font-normal">{formatDate(row.date)}</th>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.target_amount, currency)}</td>
                <td className="px-5 py-3">{row.note || '—'}</td>
                <td className="px-5 py-3"><label className="flex items-center gap-2"><input type="checkbox" checked={row.is_active_plan !== false} disabled={locked || editor !== null} aria-label={`${row.date}のマイルストーンを進捗計算に採用`} onChange={(event) => run(() => updateMilestone(row.id, { is_active_plan: event.target.checked }), '採用状態を変更しました。')} />{row.is_active_plan === false ? '参考' : '採用中'}</label></td>
                <RowActions name={`${row.date}のマイルストーン`} disabled={locked || editor !== null} onEdit={() => setEditor({ row })} onDelete={async () => { if ((await confirm(`${row.date}のマイルストーン（${formatCurrency(row.target_amount, currency)}）を削除しますか？`, '削除する'))) run(() => deleteMilestone(row.id), 'マイルストーンを削除しました。'); }} />
            </tr>) : <tr><td colSpan={5} className="px-5 py-4 text-[var(--studio-text-muted)]">マイルストーンはありません。</td></tr>}
        </DataTable>}
    </section>;
}
