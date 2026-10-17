import api from './index';
import type { ConditionMode, ConditionResult } from './lifeEventConditions';
import type { ScenarioEvent } from './lifeEventGraph';

export interface LifeScenarioAccountReturn {
    account_id: number;
    annual_return: number;
}

export interface LifeScenarioUpdate {
    name?: string;
    annual_return?: number;
    inflation?: number;
    horizon_years?: number;
}

export interface LifeScenario {
    id: number;
    client_id: number;
    name: string;
    annual_return: number;
    inflation: number;
    horizon_years: number;
    is_goal: boolean;
    created_at: string | null;
    updated_at: string | null;
    account_returns: LifeScenarioAccountReturn[];
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

export interface ProjectedLifeScenario extends LifeScenario {
    projection: ScenarioProjectionRow[];
    conditions: ScenarioConditions[];
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

export async function setAccountReturns(id: number, returns: LifeScenarioAccountReturn[]): Promise<LifeScenario> {
    return (await api.put<LifeScenario>(`/life-scenarios/${id}/account-returns`, { returns })).data;
}

export async function makeGoal(id: number, confirm_detach = false): Promise<LifeScenario> {
    return (await api.post<LifeScenario>(`/life-scenarios/${id}/goal`, { confirm_detach })).data;
}

export async function remove(id: number): Promise<void> {
    await api.delete(`/life-scenarios/${id}`);
}

export async function compare(ids: number[]): Promise<LifeScenarioComparison> {
    return (await api.get<LifeScenarioComparison>('/life-scenarios/compare', { params: { ids: ids.join(',') } })).data;
}
