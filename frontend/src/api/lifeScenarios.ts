import api from './index';
import type { ConditionMode, ConditionResult } from './lifeEventConditions';
import type { ScenarioEvent } from './lifeEventGraph';

export interface LifeScenarioUpdate {
    name?: string;
    annual_return?: number;
    inflation?: number;
    horizon_years?: number;
}

/** 積立 into account_id, 口座振替 from account_id to to_account_id, or ライフイベントへの取り崩し from account_id toward life_event_id. */
export type ContributionKind = 'contribution' | 'transfer' | 'withdrawal';
/** When the account holds less: skip (取引を発生させない) or partial (ある分だけで取引する). */
export type ShortageMode = 'skip' | 'partial';

/** A 積立設定 record (WP23). Records add up. amount moves each time: once when interval_months is null,
 * else every interval_months months from start_period, repeat_count times or until end_period. */
export interface ContributionPlan {
    id: number;
    scenario_id: number;
    kind: ContributionKind;
    account_id: number;
    account_name: string | null;
    to_account_id: number | null;
    to_account_name: string | null;
    start_period: string;
    amount: number;
    interval_months: number | null;
    repeat_count: number | null;
    end_period: string | null;
    on_shortage: ShortageMode | null;
    /** 積立 only: the account's yield from start_period; null carries the previous record's, else the scenario's default. */
    annual_return: number | null;
    note: string | null;
    life_event_id: number | null;
    life_event_name: string | null;
}

export type ContributionPlanInput = Partial<Omit<ContributionPlan, 'id' | 'scenario_id' | 'account_name' | 'to_account_name' | 'life_event_name'>>;

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
