import type { ConditionMetric } from '../../../api/lifeEventConditions';
import type { ProjectedCondition, ScenarioConditions } from '../../../api/lifeScenarios';
import { formatCurrency } from '../../../utils/currency';
import { formatDate } from '../../datetime';
import { labels, tr } from '../../i18n';

const METRICS = labels<ConditionMetric>({ net_worth: ['純資産', 'Net worth'], free_cash: ['自由資金', 'Free cash'], account_balance: ['口座残高', 'Account balance'], capsule_claim: ['取り置きの確保額', 'Set aside in an earmark'], goal_progress: ['ライフイベントの進捗', 'Life event progress'], member_age: ['年齢', 'Age'], date_reached: ['日付', 'Date'] });
const COMPARISONS = labels({ gte: ['以上', 'or more'], lte: ['以下', 'or less'], eq: ['と等しい', 'exactly'] });

function threshold(condition: ProjectedCondition, currency: string) {
    if (condition.threshold === null) return tr('未設定', 'not set');
    if (condition.metric === 'date_reached') return formatDate(String(condition.threshold));
    if (condition.metric === 'member_age') return tr(`${condition.threshold}歳`, `age ${condition.threshold}`);
    if (condition.metric === 'goal_progress') return `${condition.threshold}%`;
    return formatCurrency(Number(condition.threshold), currency);
}

export default function ScenarioPreconditions({ events, currency }: { events: ScenarioConditions[]; currency: string }) {
    const rows = events.filter((event) => event.conditions.length > 0);
    return <section className="space-y-3">
        <h3 className="font-semibold">{tr('前提条件', 'Preconditions')}</h3>
        {rows.length === 0 && <p className="text-sm text-[var(--studio-text-muted)]">{tr('前提条件はありません。', 'No preconditions.')}</p>}
        {rows.map((event) => <div key={`preconditions-${event.event_id}`} className="space-y-2 rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface)] p-4">
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm"><h4 className="font-medium">{event.event_name}</h4><span>{tr('判定日：', 'Judged on: ')}{event.judged_at ? formatDate(event.judged_at) : tr('未設定', 'not set')}</span><span className="tabular-nums">{event.probability === null ? tr('判定できません', 'Cannot be judged') : tr(`満たす確率 ${Math.round(event.probability * 100)}%`, `${Math.round(event.probability * 100)}% chance it holds`)}</span></div>
            <p className="text-xs text-[var(--studio-text-muted)]">{event.mode === 'all' ? tr('すべて満たす', 'All must hold') : tr('いずれかを満たす', 'Any must hold')}</p>
            <ul className="space-y-1 text-sm">{event.conditions.map((condition) => <li key={`condition-${condition.id}`}>
                {METRICS[condition.metric]}{condition.reference_name ? tr(`（${condition.reference_name}）`, ` (${condition.reference_name})`) : condition.reference_id !== null ? tr(`（#${condition.reference_id}）`, ` (#${condition.reference_id})`) : ''}{tr('：', ': ')}{threshold(condition, currency)} {COMPARISONS[condition.comparator]}
                {condition.basis === 'current' && <span className="ml-2 text-xs text-[var(--studio-text-muted)]">{tr('現在の値で判定', 'Judged on the current value')}</span>}
                {condition.note && <span className="ml-2 text-[var(--studio-text-muted)]">{condition.note}</span>}
            </li>)}</ul>
        </div>)}
    </section>;
}
