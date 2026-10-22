import type { ContributionKind, ContributionPlan, ShortageMode } from '../../../api/lifeScenarios';
import { formatCurrency } from '../../../utils/currency';
import { labels, tr } from '../../i18n';

export const KIND_TEXT = labels<ContributionKind>({ contribution: ['積立', 'Contribution'], transfer: ['口座振替', 'Transfer'], withdrawal: ['ライフイベントへの取り崩し', 'Drawdown for a life event'] });
export const SHORTAGE_TEXT = labels<ShortageMode>({ skip: ['取引を発生させない', 'Skip the transaction'], partial: ['ある分だけで取引する', 'Move what is there'] });

/** 毎月 / 毎年 / 3か月ごと / 2年ごと; null when the record happens once. */
export function frequencyText(interval: number | null): string | null {
    if (interval === null) return null;
    if (interval === 1) return tr('毎月', 'monthly');
    if (interval === 12) return tr('毎年', 'yearly');
    return interval % 12 === 0 ? tr(`${interval / 12}年ごと`, `every ${interval / 12} years`) : tr(`${interval}か月ごと`, `every ${interval} months`);
}

/** When a record moves money: "2028-10（1回）", "2026-10から毎月", "2051-01から毎月・360回", "2026-12から毎年・2030-12まで". */
export function scheduleText(plan: Pick<ContributionPlan, 'start_period' | 'interval_months' | 'repeat_count' | 'end_period'>): string {
    const frequency = frequencyText(plan.interval_months);
    if (frequency === null) return tr(`${plan.start_period}（1回）`, `${plan.start_period} (once)`);
    const ends = [plan.repeat_count !== null ? tr(`${plan.repeat_count}回`, `${plan.repeat_count} times`) : null, plan.end_period ? tr(`${plan.end_period}まで`, `until ${plan.end_period}`) : null].filter(Boolean);
    return tr(`${plan.start_period}から${frequency}${ends.length ? `・${ends.join('・')}` : ''}`, `${frequency} from ${plan.start_period}${ends.length ? `, ${ends.join(', ')}` : ''}`);
}

/** What a record moves, in the table's words. */
export function recordText(plan: ContributionPlan, currency: string): string {
    const amount = formatCurrency(plan.amount, currency);
    if (plan.kind === 'transfer') return `${tr('振替', 'Transfer')} ${amount} → ${plan.to_account_name ?? `#${plan.to_account_id}`}`;
    if (plan.kind === 'withdrawal') return `${tr('取り崩し', 'Drawdown')} ${amount} → ${plan.life_event_name ?? `#${plan.life_event_id}`}`;
    return `${tr('積立', 'Contribution')} ${amount}`;
}
