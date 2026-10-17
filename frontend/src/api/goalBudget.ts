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
    /** Or a monthly allocation definition whose amount carries the rest of the savings. */
    savings_definition_id: number | null;
    /** Keys of existing savings the user does not count as saving. */
    uncounted: string[];
    create_capsules: number[];
    /** Confirmed handovers: claim this much of an account for a near event's capsule. */
    handovers: GoalBudgetHandoverChoice[];
}

export interface GoalBudgetHandoverChoice {
    event_id: number;
    account_id: number;
    amount: number;
}

/** An earlier reflection's planned savings for an event that is now near, offered for its capsule. */
export interface GoalBudgetHandoverSuggestion {
    event_id: number;
    name: string;
    account_id: number | null;
    planned: number;
    suggested: number;
}

/** A chosen handover and what it changes. */
export interface GoalBudgetHandover {
    event_id: number;
    name: string;
    capsule_id: number | null;
    account_id: number;
    account_name: string;
    adds_funding_source: boolean;
    amount: number;
    claimed: number;
    available_before: number;
    available_after: number;
    funded_before: number;
    funded_after: number;
    monthly_before: number;
    monthly_after: number;
}

/** Savings the budget already plans: a definition, a hand-entered row, or a capsule's monthly amount. */
export interface GoalBudgetExisting {
    key: string;
    kind: 'definition' | 'manual' | 'capsule';
    id: number | null;
    name: string;
    account_id: number | null;
    updatable: boolean;
    counted: boolean;
    destination: boolean;
    amount: number;
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
    /** What this event receives each month: its capsule amount, or its share of the rest saved. */
    allocation: number;
    capsule_id: number | null;
    capsule_name: string | null;
    create_capsule?: boolean;
    conditions_total: number;
    conditions_met: number;
}

export interface GoalBudgetChange {
    period: string;
    kind: 'capsule' | 'savings' | 'retire' | 'definition' | 'definition_row' | 'claim';
    definition_id?: number;
    /** For savings: the part that is the account's definitions, kept in the one budget row. */
    includes_definitions?: number;
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
        existing_amount: number;
        capsule_amount: number;
        account_amount: number;
        shortfall: number;
        account_required: boolean;
        suggested_account_id: number | null;
    };
    events: GoalBudgetEvent[];
    existing: GoalBudgetExisting[];
    handover_suggestions: GoalBudgetHandoverSuggestion[];
    handovers: GoalBudgetHandover[];
    changes: GoalBudgetChange[];
    fingerprint: string;
}

export interface GoalBudgetResult {
    applied: number;
    baseline_updated: boolean;
    handovers: number;
    created_capsules: Array<{ event_id: number; capsule_id: number; name: string }>;
    periods: string[];
}

/** What reflecting the goal would write; the server saves nothing. */
export async function previewGoalBudget(options: GoalBudgetOptions): Promise<GoalBudgetPreview> {
    return (await api.post<GoalBudgetPreview>('/goal-budget/preview', options)).data;
}

/** Writes exactly the confirmed preview, or fails with 409 when anything changed since. */
export async function applyGoalBudget(options: GoalBudgetOptions, fingerprint: string, updateBaseline = false): Promise<GoalBudgetResult> {
    return (await api.post<GoalBudgetResult>('/goal-budget/apply', { ...options, fingerprint, update_baseline: updateBaseline })).data;
}

export interface GoalBudgetReminder {
    code: 'never' | 'goal_changed' | 'coverage_ended' | 'coverage_ending' | 'savings_changed' | 'event_near' | 'events_changed' | 'budget_drift';
    message: string;
    event_id?: number;
    /** For event_near: what earlier reflections planned into the savings for this event. */
    handover_amount?: number;
}

export interface GoalBudgetStatusEvent {
    event_id: number;
    name: string;
    direction: 'expense' | 'income';
    kind: 'near' | 'far' | 'simulation_only' | 'income';
    reflection?: BudgetReflection;
    allocation: number;
    source: 'reflection' | 'rule' | null;
    target_date: string;
}

export interface GoalBudgetOverview {
    goal: { id: number; name: string; monthly_savings: number; monthly_savings_is_default: boolean } | null;
    period: string;
    near_years: number | null;
    events: GoalBudgetStatusEvent[];
    allocated_total: number;
    budget: { total: number; difference: number; lines: Array<{ name: string; account_name: string | null; amount: number; actual: number; source_kind: string }> } | null;
    reflection: { applied_at: string; start_period: string; end_period: string; scenario_id: number | null } | null;
    reminders: GoalBudgetReminder[];
}

/** The savings breakdown for a month and the reasons to reflect again; read-only. */
export async function getGoalBudgetStatus(period: string): Promise<GoalBudgetOverview> {
    return (await api.get<GoalBudgetOverview>('/goal-budget/status', { params: { period } })).data;
}

/** Create, refresh or set aside this month's confirmation-required "update from the goal" action. */
export async function syncGoalReflectionAction(period: string): Promise<{ action_id: number | null; reminders: number }> {
    return (await api.post<{ action_id: number | null; reminders: number }>('/goal-budget/sync-action', null, { params: { period } })).data;
}
