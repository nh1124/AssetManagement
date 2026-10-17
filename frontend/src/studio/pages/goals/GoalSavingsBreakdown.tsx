import { type GoalBudgetOverview, type GoalBudgetStatusEvent } from '../../../api/goalBudget';
import { formatCurrency } from '../../../utils/currency';
import { formatDate } from '../../datetime';
import { DataTable } from '../db/Database';

function kindLabel(row: GoalBudgetStatusEvent, nearYears: number | null): string {
    switch (row.kind) {
        case 'near': return nearYears === null ? '取り置きで積立' : `取り置きで積立（${nearYears}年以内）`;
        case 'far': return '毎月の積立に含む';
        case 'simulation_only': return '試算のみ（予算に入れない）';
        case 'income': return '収入（予算に入れない）';
    }
}

/** One monthly savings total, divided among the goal's events, against this month's budget. */
export default function GoalSavingsBreakdown({ data, currency }: { data: GoalBudgetOverview; currency: string }) {
    return <section className="space-y-3 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-5">
        <div>
            <div>
                <h3 className="font-semibold">積立の内訳</h3>
                {data.reflection && <p className="text-xs text-[var(--studio-text-muted)]">前回の予算反映：{formatDate(data.reflection.applied_at)}（{data.reflection.start_period}〜{data.reflection.end_period}）</p>}
            </div>
        </div>
        {data.goal && data.budget && <>
            <dl className="grid gap-3 sm:grid-cols-3">
                {[
                    ['月の積立（シナリオ）', formatCurrency(data.goal.monthly_savings, currency) + (data.goal.monthly_savings_is_default ? '（全体設定）' : '')],
                    [`予算の積立（${data.period}）`, formatCurrency(data.budget.total, currency)],
                    ['差（予算 − シナリオ）', `${data.budget.difference >= 0 ? '+' : ''}${formatCurrency(data.budget.difference, currency)}`],
                ].map(([label, value]) => <div key={label} className="rounded-lg border border-[var(--studio-border)] p-3">
                    <dt className="text-xs text-[var(--studio-text-muted)]">{label}</dt>
                    <dd className="mt-1 font-semibold tabular-nums">{value}</dd>
                </div>)}
            </dl>
            <DataTable columns={['ライフイベント', '目標日', '扱い', '毎月の積立', '根拠']}>
                {data.events.map((row) => <tr key={`breakdown-${row.event_id}`}>
                    <th scope="row" className="px-5 py-3 font-medium">{row.name}</th>
                    <td className="whitespace-nowrap px-5 py-3">{formatDate(row.target_date)}</td>
                    <td className="px-5 py-3">{kindLabel(row, data.near_years)}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{row.kind === 'income' ? '—' : formatCurrency(row.allocation, currency)}</td>
                    <td className="px-5 py-3 text-xs text-[var(--studio-text-muted)]">{row.source === 'reflection' ? '予算の反映どおり' : row.source === 'rule' ? '計算上の配分' : '—'}</td>
                </tr>)}
                {data.events.length === 0 && <tr><td colSpan={5} className="px-5 py-3 text-[var(--studio-text-muted)]">ライフイベントはありません。</td></tr>}
            </DataTable>
            <p className="text-xs text-[var(--studio-text-muted)]">月の積立は 1 つの総額で、近いライフイベントは不足額 ÷ 残り月数を取り置きに、残りは遠いライフイベントで優先度に応じて分けます（予算への反映と同じ配り方です）。予算の積立は、今月の取り置きと資産口座への配分の合計です。前提条件は予算に反映するときに判定するため、まだ反映していないイベントは条件つきでも配分に含めて表示します（反映後は「予算の反映どおり」の金額になります）。</p>
        </>}
    </section>;
}
