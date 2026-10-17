import type { ConditionMetric } from '../../../api/lifeEventConditions';
import type { ProjectedCondition, ScenarioConditions } from '../../../api/lifeScenarios';
import { formatCurrency } from '../../../utils/currency';
import { formatDate } from '../../datetime';

const labels: Record<ConditionMetric, string> = { net_worth: '純資産', free_cash: '自由資金', account_balance: '口座残高', capsule_claim: '取り置きの確保額', goal_progress: 'ライフイベントの進捗', member_age: '年齢', date_reached: '日付' };
const comparisons = { gte: '以上', lte: '以下', eq: 'と等しい' };

function threshold(condition: ProjectedCondition, currency: string) {
    if (condition.threshold === null) return '未設定';
    if (condition.metric === 'date_reached') return formatDate(String(condition.threshold));
    if (condition.metric === 'member_age') return `${condition.threshold}歳`;
    if (condition.metric === 'goal_progress') return `${condition.threshold}%`;
    return formatCurrency(Number(condition.threshold), currency);
}

export default function ScenarioPreconditions({ events, currency }: { events: ScenarioConditions[]; currency: string }) {
    const rows = events.filter((event) => event.conditions.length > 0);
    return <section className="space-y-3">
        <h3 className="font-semibold">前提条件</h3>
        {rows.length === 0 && <p className="text-sm text-[var(--studio-text-muted)]">前提条件はありません。</p>}
        {rows.map((event) => <div key={`preconditions-${event.event_id}`} className="space-y-2 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm"><h4 className="font-medium">{event.event_name}</h4><span>判定日：{event.judged_at ? formatDate(event.judged_at) : '未設定'}</span><span className="tabular-nums">{event.probability === null ? '判定できません' : `満たす確率 ${Math.round(event.probability * 100)}%`}</span></div>
            <p className="text-xs text-[var(--studio-text-muted)]">{event.mode === 'all' ? 'すべて満たす' : 'いずれかを満たす'}</p>
            <ul className="space-y-1 text-sm">{event.conditions.map((condition) => <li key={`condition-${condition.id}`}>
                {labels[condition.metric]}{condition.reference_name ? `（${condition.reference_name}）` : condition.reference_id !== null ? `（#${condition.reference_id}）` : ''}：{threshold(condition, currency)} {comparisons[condition.comparator]}
                {condition.basis === 'current' && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">現在の値で判定</span>}
                {condition.note && <span className="ml-2 text-[var(--studio-text-muted)]">{condition.note}</span>}
            </li>)}</ul>
        </div>)}
    </section>;
}
