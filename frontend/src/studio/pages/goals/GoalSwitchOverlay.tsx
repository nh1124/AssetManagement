import type { GoalPreview } from '../../../api/lifeScenarios';
import { formatCurrency } from '../../../utils/currency';
import Overlay from '../../components/Overlay';
import { DataTable } from '../db/Database';
import { primaryClass } from '../db/forms';

export type PendingGoal = { preview: GoalPreview; create: Set<number> };

/** Everything that happens to capsules when this scenario becomes the goal. */
export default function GoalSwitchOverlay({ pending, busy, currency, onToggle, onConfirm, onClose }: {
    pending: PendingGoal; busy: boolean; currency: string;
    onToggle: (eventId: number, create: boolean) => void; onConfirm: () => void; onClose: () => void;
}) {
    const { preview, create } = pending;
    const nothing = !preview.moves.length && !preview.detach.length && !preview.missing.length;
    return <Overlay title={`「${preview.scenario_name}」をゴールにする`} busy={busy} onClose={onClose}
        footer={<button type="button" disabled={busy} onClick={onConfirm} className={primaryClass}>{busy ? '処理中…' : 'ゴールにする'}</button>}>
        <div className="space-y-5">
            {nothing && <p className="text-sm text-[var(--studio-text-muted)]">取り置きの変更はありません。</p>}
            {preview.moves.length > 0 && <section className="space-y-2">
                <h3 className="text-sm font-semibold">付け替える取り置き</h3>
                <DataTable columns={['取り置き', '付け替え先']}>
                    {preview.moves.map((row) => <tr key={`move-${row.capsule_id}`}><th scope="row" className="px-5 py-3 font-medium">{row.capsule_name}</th><td className="px-5 py-3">{row.to_event_name}</td></tr>)}
                </DataTable>
            </section>}
            {preview.detach.length > 0 && <section className="space-y-2">
                <h3 className="text-sm font-semibold text-[var(--studio-warning)]">紐づけが外れる取り置き（確保済みのお金は口座に残ります）</h3>
                <DataTable columns={['取り置き', '今のライフイベント']}>
                    {preview.detach.map((row) => <tr key={`detach-${row.capsule_id}`}><th scope="row" className="px-5 py-3 font-medium">{row.capsule_name}</th><td className="px-5 py-3">{row.event_name}</td></tr>)}
                </DataTable>
            </section>}
            {preview.missing.length > 0 && <section className="space-y-2">
                <h3 className="text-sm font-semibold">取り置きが無いライフイベント</h3>
                <DataTable columns={['作成する', 'ライフイベント', '目標額']}>
                    {preview.missing.map((row) => <tr key={`missing-${row.event_id}`}>
                        <td className="px-5 py-3"><input type="checkbox" aria-label={`${row.event_name}の取り置きを作成する`} disabled={busy} checked={create.has(row.event_id)} onChange={(event) => onToggle(row.event_id, event.target.checked)} /></td>
                        <th scope="row" className="px-5 py-3 font-medium">{row.event_name}</th>
                        <td className="whitespace-nowrap px-5 py-3 tabular-nums">{formatCurrency(row.target_amount, currency)}</td>
                    </tr>)}
                </DataTable>
            </section>}
        </div>
    </Overlay>;
}
