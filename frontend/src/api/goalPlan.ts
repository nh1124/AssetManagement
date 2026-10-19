import api from './index';

/** One plan row the goal would write, keep or retire. */
export interface GoalPlanChange {
    period: string;
    kind: 'account' | 'drawdown' | 'capsule';
    account_id: number | null;
    account_name: string | null;
    capsule_id: number | null;
    capsule_name: string | null;
    /** The event an earmark row is for; with new_capsule, applying makes the earmark named after it. */
    event_id: number | null;
    new_capsule: boolean;
    line_id: number | null;
    current: number;
    new: number;
    changed: boolean;
    retire: boolean;
}

export interface GoalPlanPreview {
    scenario: { id: number; name: string };
    periods: string[];
    currency: string;
    months: Array<{ period: string; contribution: number; earmarks: number }>;
    changes: GoalPlanChange[];
    warnings: string[];
    fingerprint: string;
}

/** The goal's 積立設定 for a month beside what the plan sets aside, per account. */
export interface GoalPlanCheck {
    period: string;
    goal: { id: number; name: string } | null;
    accounts: Array<{ account_id: number; name: string; contribution: number; planned: number; difference: number }>;
    contribution: number;
    planned: number;
    difference: number;
    reflected?: boolean;
}

export async function planCheck(period: string): Promise<GoalPlanCheck> {
    return (await api.get<GoalPlanCheck>('/goal-budget/plan-check', { params: { period } })).data;
}

export async function previewGoalPlan(start_period: string, end_period: string): Promise<GoalPlanPreview> {
    return (await api.post<GoalPlanPreview>('/goal-budget/preview', { start_period, end_period })).data;
}

export async function applyGoalPlan(start_period: string, end_period: string, fingerprint: string): Promise<{ applied: number; periods: string[] }> {
    return (await api.post<{ applied: number; periods: string[] }>('/goal-budget/apply', { start_period, end_period, fingerprint })).data;
}
