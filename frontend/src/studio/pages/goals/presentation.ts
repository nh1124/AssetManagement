import type { GoalCapsule, LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';

const PLAN_STATES: Record<string, string> = { Ahead: '計画より先行', 'On Track': '計画どおり', Watch: '要注意', Behind: '計画より遅れ', 'No Plan': '計画なし' };

export const goalPlanStatus = (goal: LifeEvent) => goal.plan_status ? PLAN_STATES[goal.plan_status] || goal.plan_status : '—';
export const goalPercent = (value?: number) => value == null ? '—' : `${new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 }).format(value)}%`;
export const capsuleClaims = (capsule: GoalCapsule) => capsule.claims.length ? capsule.claims.map((claim) => `${formatCurrency(claim.amount, claim.currency)}（${claim.currency}）`).join(' ／ ') : '確保額なし';

export function claimTotals(capsules: GoalCapsule[]): string {
    const totals = new Map<string, number>();
    for (const capsule of capsules) for (const claim of capsule.claims) {
        if (claim.amount > 0) totals.set(claim.currency, (totals.get(claim.currency) ?? 0) + claim.amount);
    }
    return totals.size ? [...totals].map(([currency, amount]) => `${formatCurrency(amount, currency)}（${currency}）`).join(' ／ ') : '返金対象額なし';
}
