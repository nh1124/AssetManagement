import api from './index';

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

