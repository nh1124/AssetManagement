import { Link, useNavigate } from 'react-router-dom';
import { type GoalBudgetOverview, type GoalBudgetStatusEvent } from '../../../api/goalBudget';
import type { ProjectedLifeScenario } from '../../../api/lifeScenarios';
import { formatCurrency } from '../../../utils/currency';
import { formatDate } from '../../datetime';
import { DataTable } from '../db/Database';
import { goalPercent } from './presentation';

const linkClass = 'rounded text-[var(--studio-accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--studio-accent)]';
const summaryClass = 'cursor-pointer text-sm text-[var(--studio-text-muted)]';

function kindLabel(row: GoalBudgetStatusEvent, nearYears: number | null): string {
    switch (row.kind) {
        case 'near': return nearYears === null ? '取り置きで積立' : `取り置きで積立（${nearYears}年以内）`;
        case 'far': return '毎月の積立に含む';
        case 'simulation_only': return '試算のみ（予算に入れない）';
        case 'income': return '収入（予算に入れない）';
        case 'product': return `消耗品・固定資産の積立（${row.products ?? 0}件）`;
    }
}

/** Each event's need, what is set aside for it, and its share of the monthly savings, in one table. */
export default function GoalSavingsBreakdown({ scenario, funded, budget, currency }: {
    scenario: ProjectedLifeScenario;
    /** Amount set aside per event id; missing progress counts as zero. */
    funded: Map<number, number>;
    /** The savings breakdown; null while it loads or when it failed. */
    budget: GoalBudgetOverview | null;
    currency: string;
}) {
    const navigate = useNavigate();
    const breakdown = new Map((budget?.events ?? []).filter((row) => row.event_id !== null).map((row) => [row.event_id, row]));
    const products = (budget?.events ?? []).filter((row) => row.event_id === null);
    const events = [...scenario.events].sort((a, b) => (a.resolved_date ?? '￿').localeCompare(b.resolved_date ?? '￿') || a.id - b.id);
    const monthly = (row: GoalBudgetStatusEvent | undefined) => !row || row.kind === 'income' ? '—'
        : `${formatCurrency(row.allocation, currency)}${row.source === 'rule' ? '（計算上）' : ''}`;
    return <section className="space-y-3">
        <h3 className="font-semibold">ライフイベント</h3>
        <DataTable columns={['名称', '目標日', '必要額', '確保額', '毎月の積立', '扱い']}>
            {events.map((item) => {
                const income = item.direction === 'income';
                const claimed = funded.get(item.id) ?? 0;
                const row = breakdown.get(item.id);
                const to = `/goals/scenarios/${scenario.id}/events/${item.id}`;
                return <tr key={item.id} className="cursor-pointer hover:bg-[var(--studio-accent-soft)]" onClick={() => navigate(to)}>
                    <th scope="row" className="px-5 py-3 font-medium"><Link to={to} onClick={(event) => event.stopPropagation()} className={linkClass}>{item.name}</Link></th>
                    <td className="whitespace-nowrap px-5 py-3">{item.resolved_date ? formatDate(item.resolved_date) : '未設定'}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{income ? `収入 ${formatCurrency(item.target_amount, currency)}` : formatCurrency(item.target_amount, currency)}</td>
                    {/* A zero target has no percentage to report; 0% would read as no progress. */}
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{income ? '—' : `${formatCurrency(claimed, currency)}（${goalPercent(item.target_amount > 0 ? claimed / item.target_amount * 100 : undefined)}）`}</td>
                    <td className="whitespace-nowrap px-5 py-3 tabular-nums">{monthly(row)}</td>
                    <td className="px-5 py-3 text-xs text-[var(--studio-text-muted)]">{row ? kindLabel(row, budget?.near_years ?? null) : income ? '収入' : '—'}</td>
                </tr>;
            })}
            {products.map((row) => <tr key={`capsule-${row.capsule_id}`}>
                <th scope="row" className="px-5 py-3 font-medium">{row.name}</th>
                <td className="whitespace-nowrap px-5 py-3">{row.target_date ? formatDate(row.target_date) : '—'}</td>
                <td className="px-5 py-3">—</td>
                <td className="px-5 py-3">—</td>
                <td className="whitespace-nowrap px-5 py-3 tabular-nums">{monthly(row)}</td>
                <td className="px-5 py-3 text-xs text-[var(--studio-text-muted)]">{kindLabel(row, budget?.near_years ?? null)}</td>
            </tr>)}
            {events.length + products.length === 0 && <tr><td colSpan={6} className="px-5 py-3 text-[var(--studio-text-muted)]">ライフイベントはありません。</td></tr>}
        </DataTable>
        {/* U5: the rule cannot judge preconditions (they read the allocation itself). */}
        {budget?.events.some((row) => row.source === 'rule' && row.kind !== 'product') && <p className="text-xs text-[var(--studio-text-muted)]">「（計算上）」の月額は前提条件を判定していません。前提条件は予算に反映するときに判定します。</p>}
        {budget?.goal && <details>
            <summary className={summaryClass}>積立の根拠</summary>
            <div className="mt-2 space-y-2 text-xs text-[var(--studio-text-muted)]">
                {budget.reflection && <p>前回の予算反映：{formatDate(budget.reflection.applied_at)}（{budget.reflection.start_period}〜{budget.reflection.end_period}）。反映した月は予算の反映どおりの金額、「（計算上）」はまだ反映していない計算上の配分です。</p>}
                <p>月の積立は 1 つの総額で、近いライフイベントは不足額 ÷ 残り月数を取り置きに、残りは遠いライフイベントで優先度に応じて分けます（予算への反映と同じ配り方で、足りないときは前回の反映の優先順位で後ろのものから削ります）。予算の積立は、今月の取り置きと資産口座への配分の合計です。まだ反映していないイベントは、条件つきでも配分に含めて表示します。</p>
            </div>
        </details>}
    </section>;
}
