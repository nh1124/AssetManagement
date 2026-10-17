import api from './index';

export type BaselineReason = 'adopted' | 'reflection' | 'manual';

export interface GoalBaseline {
    id: number;
    scenario_id: number | null;
    scenario_name: string;
    reason: BaselineReason;
    anchor_date: string;
    is_current: boolean;
    assumptions: { annual_return: number; inflation: number; horizon_years: number; monthly_savings: number };
    events: Array<{ name: string; direction: 'expense' | 'income'; target_amount: number; date: string | null }>;
    created_at: string | null;
}

export interface BaselineRow {
    period: string;
    date: string;
    p10: number;
    p50: number;
    p90: number;
    /** Month-end net worth of active accounts; null for months still ahead. */
    actual: number | null;
    /** Closed in 月次の締め: final rather than provisional. */
    closed: boolean;
}

export interface BaselineComparison {
    baseline: GoalBaseline | null;
    rows: BaselineRow[];
    latest: { period: string; date: string; actual: number; p50: number; difference: number; below_p10: boolean; closed: boolean } | null;
}

export async function getBaselineComparison(): Promise<BaselineComparison> {
    return (await api.get<BaselineComparison>('/goal-baselines/current')).data;
}

/** Freeze today's goal projection as the new baseline; earlier ones stay as history. */
export async function captureBaseline(): Promise<BaselineComparison> {
    return (await api.post<BaselineComparison>('/goal-baselines')).data;
}
