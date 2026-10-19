import api from './index';
import type { ConditionMode, ConditionResult } from './lifeEventConditions';
import type { ScenarioEvent } from './lifeEventGraph';

export interface LifeScenarioUpdate {
    name?: string;
    annual_return?: number;
    inflation?: number;
    horizon_years?: number;
}

/** A 積立設定 record: from start_period on, this account receives monthly_amount and yields annual_return. */
export interface ContributionPlan {
    id: number;
    scenario_id: number;
    account_id: number;
    account_name: string | null;
    start_period: string;
    monthly_amount: number;
    /** null carries the previous record's yield, else the scenario's default. */
    annual_return: number | null;
    note: string | null;
    /** ライフイベントへの取り崩し: -monthly_amount leaves the account once, in start_period, for this expense. */
    life_event_id: number | null;
    life_event_name: string | null;
}
// monthly_amount below zero withdraws from the account every month (取り崩し).

export type ContributionPlanInput = Partial<Pick<ContributionPlan, 'account_id' | 'start_period' | 'monthly_amount' | 'annual_return' | 'note' | 'life_event_id'>>;

export interface LifeScenario {
    id: number;
    client_id: number;
    name: string;
    /** The yield of accounts whose 積立設定 names none. */
    annual_return: number;
    inflation: number;
    horizon_years: number;
    is_goal: boolean;
    created_at: string | null;
    updated_at: string | null;
    contribution_plans: ContributionPlan[];
    events: ScenarioEvent[];
}

export interface ScenarioProjectionRow {
    year: number;
    p10: number;
    p50: number;
    p90: number;
    cumulative_target: number;
    cumulative_income: number;
}

export interface ProjectedCondition extends Omit<ConditionResult, 'threshold'> {
    threshold: number | string | null;
    threshold_minor: number | null;
    threshold_number: number | null;
    threshold_date: string | null;
    basis: 'projected' | 'current';
    probability: number | null;
}

export interface ScenarioConditions {
    event_id: number;
    event_name: string;
    judged_at: string | null;
    mode: ConditionMode;
    probability: number | null;
    conditions: ProjectedCondition[];
}

export interface ProjectedEvent extends ScenarioEvent {
    /** Share of paths on which the event happens: its preceding event (and, for a repayment, its borrowing) happened and its preconditions held. */
    executed_probability: number | null;
    /** Expenses only: share of paths on which it happens and net worth stays non-negative after it. */
    funded_probability: number | null;
    /** Happens on at least half of the paths. */
    on_likely_path: boolean;
}

export interface ProjectedLifeScenario extends Omit<LifeScenario, 'events'> {
    events: ProjectedEvent[];
    projection: ScenarioProjectionRow[];
    conditions: ScenarioConditions[];
    likely_path: { event_ids: number[]; link_ids: number[] };
    accounts: Array<{ account_id: number; name: string; p50: number[] }>;
    monthly_contribution: number;
}

export interface LifeScenarioComparison {
    scenarios: ProjectedLifeScenario[];
}

export async function list(): Promise<LifeScenario[]> {
    return (await api.get<LifeScenario[]>('/life-scenarios')).data;
}

export async function create(name: string): Promise<LifeScenario> {
    return (await api.post<LifeScenario>('/life-scenarios', { name })).data;
}

export async function duplicate(id: number, name: string): Promise<LifeScenario> {
    return (await api.post<LifeScenario>(`/life-scenarios/${id}/duplicate`, { name })).data;
}

export async function update(id: number, input: LifeScenarioUpdate): Promise<LifeScenario> {
    return (await api.put<LifeScenario>(`/life-scenarios/${id}`, input)).data;
}

/** What happens to the old goal's earmarks when another scenario becomes the goal (R11). */
export type GoalEarmarkChoice = 'keep' | 'replace' | 'carry';

export interface GoalChangePreview {
    scenario: { id: number; name: string };
    current_goal: { id: number; name: string } | null;
    capsules: Array<{ capsule_id: number; capsule_name: string; event_name: string; claim: number; carry_to: string | null }>;
    create: Array<{ event_id: number; name: string; account_name: string | null }>;
}

export async function goalPreview(id: number): Promise<GoalChangePreview> {
    return (await api.get<GoalChangePreview>(`/life-scenarios/${id}/goal-preview`)).data;
}

export async function makeGoal(id: number, earmarks: GoalEarmarkChoice = 'keep'): Promise<LifeScenario> {
    return (await api.post<LifeScenario>(`/life-scenarios/${id}/goal`, { earmarks })).data;
}

export async function remove(id: number): Promise<void> {
    await api.delete(`/life-scenarios/${id}`);
}

export async function compare(ids: number[]): Promise<LifeScenarioComparison> {
    return (await api.get<LifeScenarioComparison>('/life-scenarios/compare', { params: { ids: ids.join(',') } })).data;
}

export async function createContributionPlan(scenarioId: number, input: ContributionPlanInput): Promise<ContributionPlan> {
    return (await api.post<ContributionPlan>(`/life-scenarios/${scenarioId}/contribution-plans`, input)).data;
}

export async function updateContributionPlan(id: number, input: ContributionPlanInput): Promise<ContributionPlan> {
    return (await api.put<ContributionPlan>(`/life-scenarios/contribution-plans/${id}`, input)).data;
}

export async function deleteContributionPlan(id: number): Promise<void> {
    await api.delete(`/life-scenarios/contribution-plans/${id}`);
}
