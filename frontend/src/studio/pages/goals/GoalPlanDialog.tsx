import { useState } from 'react';
import { applyGoalPlan, previewGoalPlan, type GoalPlanChange, type GoalPlanPreview } from '../../../api/goalPlan';
import Overlay from '../../components/Overlay';
import { clientToday, useTimezone } from '../../datetime';
import { formatCurrency } from '../../../utils/currency';
import { DataTable, Feedback, Field } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';

function addMonths(period: string, months: number): string {
    const index = Number(period.slice(0, 4)) * 12 + Number(period.slice(5, 7)) - 1 + months;
    return `${Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, '0')}`;
}

function rowLabel(change: GoalPlanChange): string {
    const account = change.account_name ?? `#${change.account_id}`;
    if (change.kind === 'drawdown') return `口座「${account}」からの取り崩し`;
    if (change.kind === 'account') return `口座「${account}」への積立`;
    const name = change.capsule_name ?? `#${change.capsule_id}`;
    return change.new_capsule ? `新しい取り置き「${name}」（${account}に作ります）` : `取り置き「${name}」（${account}から）`;
}

/** ゴールから計画を作成: preview the plan rows the goal's 積立設定 and its events' earmarks ask for, then write them. */
export default function GoalPlanDialog({ title = 'ゴールから計画を作成', intro, onClose }: { title?: string; intro?: string; onClose: (applied: boolean) => void }) {
    const timezone = useTimezone();
    const current = clientToday(timezone).slice(0, 7);
    const [start, setStart] = useState(current);
    const [end, setEnd] = useState(addMonths(current, 11));
    const [preview, setPreview] = useState<GoalPlanPreview | null>(null);
    const mutation = useMutation();
    const changes = preview?.changes.filter((change) => change.changed) ?? [];
    const check = () => {
        let loaded: GoalPlanPreview | null = null;
        void mutation.run(async () => { loaded = await previewGoalPlan(start, end); }, '', () => setPreview(loaded));
    };
    const apply = () => {
        if (!preview) return;
        void mutation.run(() => applyGoalPlan(start, end, preview.fingerprint), '', () => onClose(true));
    };
    return <Overlay title={title} help="口座ごとの積立（積立設定の月額）から、その口座の取り置きの月額と既存の配分（自動取引など）を引いた額を配分の行に、毎月の取り崩しは取り崩しの行にします。取り置きは、ライフイベントへの取り崩しのレコードがある支出イベントごとに同じ名前で作り（ゴール）、口座ごとに取り崩す額を、取り崩す月まで均等に積み立てます。取り崩す月には、その口座の取り崩しの行を作ります。「取り置きと既存の配分が積立設定の月額を超えています」は、その月その口座で、ゴールの取り置きと既存の配分の合計が積立設定の月額より多いという意味です（その口座の配分の行は 0 になります）。" busy={mutation.busy} onClose={() => onClose(false)} footer={<>
        <button type="button" disabled={mutation.busy || !preview || changes.length === 0} onClick={apply} className={primaryClass}>{mutation.busy ? '処理中…' : '計画に反映'}</button>
        <button type="button" disabled={mutation.busy} onClick={() => onClose(false)} className={buttonClass}>閉じる</button>
    </>}>
        <div className="space-y-4">
            {intro && <p className="text-sm">{intro}</p>}
            <div className="grid items-end gap-4 sm:grid-cols-3">
                <Field label="開始月"><input type="month" required value={start} disabled={mutation.busy} onChange={(event) => { setStart(event.target.value); setPreview(null); }} className={inputClass} /></Field>
                <Field label="終了月"><input type="month" required min={start} value={end} disabled={mutation.busy} onChange={(event) => { setEnd(event.target.value); setPreview(null); }} className={inputClass} /></Field>
                <div><button type="button" disabled={mutation.busy || !start || !end || end < start} onClick={check} className={buttonClass}>内容を確認</button></div>
            </div>
            <Feedback error={mutation.error} />
            {preview && <>
                <p className="text-sm">ゴール「{preview.scenario.name}」から {preview.periods[0]}〜{preview.periods.at(-1)} の計画を作成します。</p>
                {preview.warnings.length > 0 && <ul role="alert" className="list-disc space-y-1 pl-5 text-sm text-[var(--studio-warning)]">{preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
                {changes.length === 0 ? <p className="text-sm text-[var(--studio-text-muted)]">計画は最新です。変更はありません。</p>
                    : <DataTable columns={['月', '計画の行', '現在', '変更後']}>
                        {changes.map((change) => <tr key={`${change.period}:${change.kind}:${change.capsule_id ?? 0}:${change.account_id ?? 0}`}>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{change.period}</td>
                            <th scope="row" className="px-5 py-3 font-normal">{rowLabel(change)}</th>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{change.line_id === null ? '—' : formatCurrency(change.current, preview.currency)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{change.retire ? '削除' : formatCurrency(change.new, preview.currency)}</td>
                        </tr>)}
                    </DataTable>}
            </>}
        </div>
    </Overlay>;
}
