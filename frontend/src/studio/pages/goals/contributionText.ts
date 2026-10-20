import type { ContributionKind, ContributionPlan, ShortageMode } from '../../../api/lifeScenarios';
import { formatCurrency } from '../../../utils/currency';

export const KIND_TEXT: Record<ContributionKind, string> = { contribution: '積立', transfer: '口座振替', withdrawal: 'ライフイベントへの取り崩し' };
export const SHORTAGE_TEXT: Record<ShortageMode, string> = { skip: '取引を発生させない', partial: 'ある分だけで取引する' };

/** 毎月 / 毎年 / 3か月ごと / 2年ごと; null when the record happens once. */
export function frequencyText(interval: number | null): string | null {
    if (interval === null) return null;
    if (interval === 1) return '毎月';
    if (interval === 12) return '毎年';
    return interval % 12 === 0 ? `${interval / 12}年ごと` : `${interval}か月ごと`;
}

/** When a record moves money: "2028-10（1回）", "2026-10から毎月", "2051-01から毎月・360回", "2026-12から毎年・2030-12まで". */
export function scheduleText(plan: Pick<ContributionPlan, 'start_period' | 'interval_months' | 'repeat_count' | 'end_period'>): string {
    const frequency = frequencyText(plan.interval_months);
    if (frequency === null) return `${plan.start_period}（1回）`;
    const ends = [plan.repeat_count !== null ? `${plan.repeat_count}回` : null, plan.end_period ? `${plan.end_period}まで` : null].filter(Boolean);
    return `${plan.start_period}から${frequency}${ends.length ? `・${ends.join('・')}` : ''}`;
}

/** What a record moves, in the table's words. */
export function recordText(plan: ContributionPlan, currency: string): string {
    const amount = formatCurrency(plan.amount, currency);
    if (plan.kind === 'transfer') return `振替 ${amount} → ${plan.to_account_name ?? `#${plan.to_account_id}`}`;
    if (plan.kind === 'withdrawal') return `取り崩し ${amount} → ${plan.life_event_name ?? `#${plan.life_event_id}`}`;
    return `積立 ${amount}`;
}
