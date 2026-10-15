import api from './index';

export type ConditionMetric = 'net_worth' | 'free_cash' | 'account_balance' | 'capsule_claim' | 'goal_progress' | 'member_age' | 'date_reached';
export type ConditionMode = 'all' | 'any';
export interface ConditionInput {
    metric: ConditionMetric;
    comparator: 'gte' | 'lte' | 'eq';
    threshold_minor?: number;
    threshold_number?: number;
    threshold_date?: string;
    reference_id?: number;
    note?: string | null;
}
export interface ConditionResult {
    id: number;
    metric: ConditionMetric;
    comparator: ConditionInput['comparator'];
    threshold: number | string;
    reference_id: number | null;
    reference_name: string | null;
    actual: number | string | null;
    satisfied: boolean | null;
    reason: string | null;
    note: string | null;
}
export interface ConditionEvaluation {
    mode: ConditionMode;
    satisfied: boolean | null;
    conditions: ConditionResult[];
}
export interface MemberInput {
    name: string;
    relation: string | null;
    birth_date: string;
}
export interface HouseholdMember extends MemberInput {
    id: number;
    client_id: number;
    created_at: string | null;
}
export async function getGoalConditions(id: number): Promise<ConditionEvaluation> {
    return (await api.get<ConditionEvaluation>(`/life-events/${id}/conditions`)).data;
}
export async function getAllConditions(): Promise<Record<number, ConditionEvaluation>> {
    return (await api.get<Record<number, ConditionEvaluation>>('/life-events/conditions')).data;
}
export async function addGoalCondition(id: number, input: ConditionInput): Promise<void> {
    await api.post(`/life-events/${id}/conditions`, input);
}
export async function deleteGoalCondition(id: number, conditionId: number): Promise<void> {
    await api.delete(`/life-events/${id}/conditions/${conditionId}`);
}
export async function getHouseholdMembers(): Promise<HouseholdMember[]> {
    return (await api.get<HouseholdMember[]>('/household-members')).data;
}
export async function saveHouseholdMember(input: MemberInput, id?: number): Promise<void> {
    if (id === undefined) await api.post('/household-members', input);
    else await api.put(`/household-members/${id}`, input);
}
export async function deleteHouseholdMember(id: number): Promise<void> {
    await api.delete(`/household-members/${id}`);
}
