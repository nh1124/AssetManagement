import type { BudgetReflection, GoalCapsule, LifeEvent } from '../../../types';
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

/** How an event reaches the budget; the same words everywhere the choice appears. */
export const REFLECTIONS: Record<BudgetReflection, string> = { firm: '確定', conditional: '条件つき', simulation_only: '試算のみ' };
export const REFLECTION_HINTS: Record<BudgetReflection, string> = {
    firm: '予算に反映するときに、常に含めます。',
    conditional: '予算に反映する時点で前提条件を満たしていれば含め、満たさなければ見込みとして表示します。',
    simulation_only: '予算には含めず、シミュレーションだけで使います。',
};
