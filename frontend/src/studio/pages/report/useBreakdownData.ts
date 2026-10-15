import { useCallback } from 'react';
import { getAccountFlows, getPeriodReport, getProfitLoss, getVarianceAnalysis } from '../../../api';
import type { AccountFlowGrain } from '../../../types';
import { useResource } from '../../useResource';
import type { ProfitLoss } from './ReportReading';

// Saved expense plans include zero-valued categories and unplanned actuals.
export interface VarianceAnalysis {
    plan_id: number | null;
    items: Array<{ category: string; budget: number; actual: number; variance: number; percentage: number }>;
    total_budget: number;
    total_actual: number;
    total_variance: number;
}

export function useBreakdownData(startDate: string, endDate: string) {
    const months = (Number(endDate.slice(0, 4)) - Number(startDate.slice(0, 4))) * 12
        + Number(endDate.slice(5, 7)) - Number(startDate.slice(5, 7)) + 1;
    // Daily detail fits one month; longer periods need monthly or quarterly buckets.
    const grain: AccountFlowGrain = months === 1 ? 'day' : months === 12 ? 'month' : 'quarter';
    const loadReport = useCallback(() => getPeriodReport(startDate, endDate), [startDate, endDate]);
    // Report summaries expose the balance only; P/L supplies income and expense.
    const loadProfitLoss = useCallback((): Promise<ProfitLoss> => getProfitLoss(undefined, undefined, false, startDate, endDate), [startDate, endDate]);
    const loadVariance = useCallback((): Promise<VarianceAnalysis> => getVarianceAnalysis(undefined, undefined, startDate, endDate), [startDate, endDate]);
    const loadFlows = useCallback(() => getAccountFlows({ startDate, endDate, grain }), [startDate, endDate, grain]);
    const report = useResource(loadReport);
    const profitLoss = useResource(loadProfitLoss);
    const variance = useResource(loadVariance);
    const flows = useResource(loadFlows);
    const resources = [report, profitLoss, variance, flows];
    const loading = resources.some((resource) => resource.loading);
    const failed = resources.some((resource) => Boolean(resource.error));
    const ready = !loading && !failed && resources.every((resource) => resource.data !== null);
    const refresh = () => resources.forEach((resource) => resource.reload());
    return { report, profitLoss, variance, flows, loading, failed, ready, refresh };
}

export type BreakdownResource = ReturnType<typeof useBreakdownData>;
