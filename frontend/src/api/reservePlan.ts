import api from './index';

/** 基準: the earmark's saved monthly amount, or what reaches its target by the replacement month. */
export type ReserveBase = 'saved' | 'remaining';
/** How the amount the earmark already holds comes off: the nearest months first, or the same every month. */
export type ReserveHeld = 'recent' | 'even';

/** One earmark row 物品の取り置きから計画を作成 would write, keep or retire. */
export interface ReservePlanChange {
    period: string;
    capsule_id: number;
    capsule_name: string;
    account_id: number | null;
    account_name: string | null;
    line_id: number | null;
    /** The row's amount now, or the saved monthly share the plan shows without a row. */
    current: number;
    new: number;
    changed: boolean;
    retire: boolean;
}

export interface ReservePlanPreview {
    periods: string[];
    currency: string;
    base: ReserveBase;
    held: ReserveHeld;
    earmarks: Array<{ capsule_id: number; name: string; base: number; held: number; replacement: string | null }>;
    changes: ReservePlanChange[];
    warnings: string[];
    fingerprint: string;
}

export async function previewReservePlan(start_period: string, end_period: string, base: ReserveBase, held: ReserveHeld): Promise<ReservePlanPreview> {
    return (await api.post<ReservePlanPreview>('/budget-plans/product-reserves/preview', { start_period, end_period, base, held })).data;
}

export async function applyReservePlan(start_period: string, end_period: string, base: ReserveBase, held: ReserveHeld, fingerprint: string) {
    return (await api.post<{ applied: number; periods: string[] }>('/budget-plans/product-reserves/apply', { start_period, end_period, base, held, fingerprint })).data;
}
