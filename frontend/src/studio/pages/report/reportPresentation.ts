import type { ActionProposal, MonthlyReport } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import type { ProfitLoss } from './ReportReading';
import type { VarianceAnalysis } from './useBreakdownData';

export const KINDS: Record<ActionProposal['kind'], string> = {
    allocate_to_goal: '余剰をライフイベントへ配分', transfer_to_capsule: '取り置きへ移動',
    increase_savings: '積立額を増やす', review_budget: '予算を見直す', extend_target_date: '目標日を延ばす',
};
export const STATES = { pending: '未適用', applied: '適用済み', skipped: '見送り', failed: '適用に失敗' };

export function varianceRows(variance: VarianceAnalysis) {
    // Zero-valued items still belong to the budget and must remain in every output.
    return variance.items.slice().sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance));
}

export function reportWarnings(report: MonthlyReport, currency: string) {
    return report.anomalies.map((row: Record<string, unknown>) => ({
        title: typeof row.category === 'string' ? row.category : '分類未設定',
        description: `計画 ${typeof row.budget === 'number' ? formatCurrency(row.budget, currency) : '—'} に対して、実績 ${typeof row.actual === 'number' ? formatCurrency(row.actual, currency) : '—'}。`,
    }));
}

export function reportGoals(report: MonthlyReport) {
    return report.goal_progress.map((row) => ({
        title: typeof row.name === 'string' ? row.name : 'ライフイベント',
        description: `見込み進捗 ${typeof row.probability_current === 'number' ? `${row.probability_current}%` : '—'} ／ 期間中の変化 ${typeof row.delta === 'number' ? `${row.delta > 0 ? '+' : ''}${row.delta}ポイント` : '—'}`,
    }));
}

export function reportFigures(report: MonthlyReport, profitLoss: ProfitLoss | null | undefined, currency: string) {
    const summary = report.summary;
    return [
        { label: '収入', value: profitLoss ? formatCurrency(profitLoss.total_income, currency) : '—' },
        { label: '支出', value: profitLoss ? formatCurrency(profitLoss.total_expenses, currency) : '—' },
        { label: '収支（収入 − 支出）', value: formatCurrency(summary.period_pl ?? summary.monthly_pl, currency) },
        { label: '期末の純資産', value: formatCurrency(summary.net_worth, currency) },
        { label: '期間中の純資産の増減', value: summary.net_worth_change == null ? '—' : formatCurrency(summary.net_worth_change, currency) },
        { label: '収入に対する収支の割合', value: profitLoss?.total_income === 0 ? '—' : `${summary.savings_rate.toLocaleString('ja-JP', { maximumFractionDigits: 1 })}%` },
    ];
}

export function proposalEffect(proposal: ActionProposal, report: MonthlyReport, currency: string) {
    const targetId = proposal.target_life_event_id ?? proposal.target_id;
    const goal = report.goal_progress.find((row) => row.id === targetId);
    const target = typeof goal?.name === 'string' ? goal.name : `ライフイベント #${targetId}`;
    // This action creates today's journal transfer and assigns the savings leg to the goal's capsule.
    if (proposal.kind === 'allocate_to_goal') return `本日付で「cash」から「savings」へ ${formatCurrency(proposal.amount, currency)}（${currency}）を移し、「${target}」の取り置きへ配分します。必要な口座・取り置きがない場合は作成します。`;
    if (proposal.kind === 'review_budget') {
        // Backend descriptions hard-code JPY, so rebuild the reading from its numeric amount and category.
        const anomaly = report.anomalies.find((row: Record<string, unknown>) => typeof row.category === 'string' && proposal.description.startsWith(`${row.category} spending `));
        const category: unknown = anomaly?.category;
        return `${typeof category === 'string' ? `「${category}」の` : ''}次の期間の予算と支出を見直す提案です。見直し額：${formatCurrency(proposal.amount, currency)}（${currency}）。`;
    }
    return proposal.description;
}
