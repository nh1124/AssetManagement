import { useState } from 'react';
import { applyReservePlan, previewReservePlan, type ReserveBase, type ReserveHeld, type ReservePlanPreview } from '../../../api/reservePlan';
import Overlay from '../../components/Overlay';
import { clientToday, useTimezone } from '../../datetime';
import { formatCurrency } from '../../../utils/currency';
import { DataTable, Feedback, Field, OptionGroup } from '../db/Database';
import { buttonClass, inputClass, primaryClass, useMutation } from '../db/forms';

function addMonths(period: string, months: number): string {
    const index = Number(period.slice(0, 4)) * 12 + Number(period.slice(5, 7)) - 1 + months;
    return `${Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, '0')}`;
}

const HELP = '商品（物品）にひもづく取り置きの、月ごとの行を作ります。基準の月額から、すでに確保されている額を差し引きます。口座が複数あるときは、資金元の口座の目標の割合で分けます。買い替えの月より後の月は作りません。作った月は、ほかの方法で入れた行も置き換えます。';

/** 物品の取り置きから計画を作成 (§8-4): preview the earmark rows over a range, then write them. */
export default function ReservePlanDialog({ onClose }: { onClose: (applied: boolean) => void }) {
    const timezone = useTimezone();
    const current = clientToday(timezone).slice(0, 7);
    const [start, setStart] = useState(current);
    const [end, setEnd] = useState(addMonths(current, 11));
    const [base, setBase] = useState<ReserveBase>('remaining');
    const [held, setHeld] = useState<ReserveHeld>('even');
    const [preview, setPreview] = useState<ReservePlanPreview | null>(null);
    const mutation = useMutation();
    const changes = preview?.changes.filter((change) => change.changed) ?? [];
    const reset = <T,>(set: (value: T) => void) => (value: T) => { set(value); setPreview(null); };
    const check = () => {
        let loaded: ReservePlanPreview | null = null;
        void mutation.run(async () => { loaded = await previewReservePlan(start, end, base, held); }, '', () => setPreview(loaded));
    };
    const apply = () => {
        if (!preview) return;
        void mutation.run(() => applyReservePlan(start, end, base, held, preview.fingerprint), '', () => onClose(true));
    };
    return <Overlay title="物品の取り置きから計画を作成" help={HELP} busy={mutation.busy} onClose={() => onClose(false)} footer={<>
        <button type="button" disabled={mutation.busy || !preview || changes.length === 0} onClick={apply} className={primaryClass}>{mutation.busy ? '処理中…' : '計画に反映'}</button>
        <button type="button" disabled={mutation.busy} onClick={() => onClose(false)} className={buttonClass}>閉じる</button>
    </>}>
        <div className="space-y-4">
            <fieldset disabled={mutation.busy} className="space-y-4">
                <div className="grid items-end gap-4 sm:grid-cols-2">
                    <Field label="開始月"><input type="month" required value={start} onChange={(event) => reset(setStart)(event.target.value)} className={inputClass} /></Field>
                    <Field label="終了月"><input type="month" required min={start} value={end} onChange={(event) => reset(setEnd)(event.target.value)} className={inputClass} /></Field>
                </div>
                <OptionGroup label="基準の月額" value={base} onChange={reset(setBase)} options={[
                    { value: 'remaining', label: '残り期間に合わせる', description: '開始月から買い替えの月までに目標に届く月額です（消耗品は月あたりの費用）。' },
                    { value: 'saved', label: '取り置きの月額', description: '取り置きに設定されている月額をそのまま使います。' },
                ]} />
                <OptionGroup label="確保済みの額の引き方" value={held} onChange={reset(setHeld)} options={[
                    { value: 'even', label: '均一に引く', description: '確保済みの額を買い替えの月までの月数で割り、毎月同じ額を引きます（買い替えのない消耗品は期間の月数で割ります）。' },
                    { value: 'recent', label: '直近の月から引く', description: '確保済みの額を使い切るまで、開始月に近い月から引きます。' },
                ]} />
                <div><button type="button" disabled={!start || !end || end < start} onClick={check} className={buttonClass}>内容を確認</button></div>
            </fieldset>
            <Feedback error={mutation.error} />
            {preview && <>
                {preview.warnings.length > 0 && <ul role="alert" className="list-disc space-y-1 pl-5 text-sm text-[var(--studio-warning)]">{preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
                {preview.earmarks.length === 0 ? <p className="text-sm text-[var(--studio-text-muted)]">商品にひもづく取り置きはありません。</p>
                    : <DataTable columns={['取り置き', '基準の月額', '確保済み', '買い替えの月']}>
                        {preview.earmarks.map((earmark) => <tr key={earmark.capsule_id}>
                            <th scope="row" className="px-5 py-3 font-medium">{earmark.name}</th>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(earmark.base, preview.currency)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(earmark.held, preview.currency)}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{earmark.replacement ?? '—'}</td>
                        </tr>)}
                    </DataTable>}
                {preview.earmarks.length > 0 && (changes.length === 0 ? <p className="text-sm text-[var(--studio-text-muted)]">計画は最新です。変更はありません。</p>
                    : <DataTable columns={['月', '取り置き（口座）', '現在', '変更後']}>
                        {changes.map((change) => <tr key={`${change.period}:${change.capsule_id}:${change.account_id ?? 0}:${change.line_id ?? 0}`}>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{change.period}</td>
                            <th scope="row" className="px-5 py-3 font-normal">{change.capsule_name}（{change.account_name ?? '口座なし'}）</th>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(change.current, preview.currency)}{change.line_id === null && <span className="ml-1 text-xs text-[var(--studio-text-muted)]">（月額）</span>}</td>
                            <td className="whitespace-nowrap px-5 py-3 tabular-nums">{change.retire ? '削除' : formatCurrency(change.new, preview.currency)}</td>
                        </tr>)}
                    </DataTable>)}
            </>}
        </div>
    </Overlay>;
}
