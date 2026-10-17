import api from './index';
import type { BudgetReflection } from '../types';

export interface GoalBudgetOptions {
    /** Q1: the scenario's monthly savings, or what the reflected events require. */
    savings_source: 'scenario' | 'required';
    /** Q2: events within this many years are funded through their own capsules; null = all. */
    near_years: number | null;
    start_period: string;
    months: number;
    savings_account_id: number | null;
    create_capsules: number[];
}

export type GoalBudgetStatus = 'reflected' | 'condition_unmet' | 'condition_unknown' | 'simulation_only' | 'income' | 'past_due' | 'no_capsule';

export interface GoalBudgetEvent {
    event_id: number;
    name: string;
    direction: 'expense' | 'income';
    target_date: string;
    target_amount: number;
    funded: number;
    reflection: BudgetReflection;
    reflection_chosen: boolean;
    status: GoalBudgetStatus;
    near: boolean;
    months: number;
    monthly_required: number;
    capsule_id: number | null;
    capsule_name: string | null;
    create_capsule?: boolean;
    conditions_total: number;
    conditions_met: number;
}

export interface GoalBudgetChange {
    period: string;
    kind: 'capsule' | 'savings' | 'retire';
    event_id: number | null;
    capsule_id: number | null;
    name: string;
    account_id: number | null;
    line_id: number | null;
    current_amount: number | null;
    new_amount: number;
    changed: boolean;
}

export interface GoalBudgetPreview {
    scenario: { id: number; name: string; monthly_savings: number; monthly_savings_is_default: boolean; annual_return: number; after_tax_return: number };
    options: GoalBudgetOptions;
    periods: string[];
    savings: {
        scenario_amount: number;
        required_amount: number;
        chosen_amount: number;
        capsule_amount: number;
        account_amount: number;
        shortfall: number;
        account_required: boolean;
        suggested_account_id: number | null;
    };
    events: GoalBudgetEvent[];
    changes: GoalBudgetChange[];
    fingerprint: string;
}

export interface GoalBudgetResult {
    applied: number;
    created_capsules: Array<{ event_id: number; capsule_id: number; name: string }>;
    periods: string[];
}

/** What reflecting the goal would write; the server saves nothing. */
export async function previewGoalBudget(options: GoalBudgetOptions): Promise<GoalBudgetPreview> {
    return (await api.post<GoalBudgetPreview>('/goal-budget/preview', options)).data;
}

/** Writes exactly the confirmed preview, or fails with 409 when anything changed since. */
export async function applyGoalBudget(options: GoalBudgetOptions, fingerprint: string): Promise<GoalBudgetResult> {
    return (await api.post<GoalBudgetResult>('/goal-budget/apply', { ...options, fingerprint })).data;
}
