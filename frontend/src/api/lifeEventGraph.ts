import api from './index';

export interface LifeEventLinkInput {
    from_event_id: number;
    to_event_id: number;
    kind: 'after' | 'alternative';
    offset_months: number;
    note?: string | null;
}

export interface LifeEventLink extends LifeEventLinkInput {
    id: number;
    client_id: number;
    created_at: string | null;
}

export interface ScenarioEvent {
    id: number;
    name: string;
    resolved_date: string | null;
    target_amount: number;
    currency: string;
    incoming_link_id: number | null;
}

export interface LifeEventScenario {
    id: string;
    label: string;
    chosen_link_ids: number[];
    events: ScenarioEvent[];
    projection: Array<{ year: number; p10: number; p50: number; p90: number; cumulative_target: number }>;
}

export interface ScenarioComparison {
    scenarios: LifeEventScenario[];
    truncated: boolean;
    fork_count: number;
}

export interface ScenarioParameters {
    years: number;
    annual_return: number;
    inflation: number;
}

export async function getLifeEventLinks(): Promise<LifeEventLink[]> {
    return (await api.get<LifeEventLink[]>('/life-events/links')).data;
}

export async function createLifeEventLink(input: LifeEventLinkInput): Promise<LifeEventLink> {
    return (await api.post<LifeEventLink>('/life-events/links', input)).data;
}

export async function deleteLifeEventLink(id: number): Promise<void> {
    await api.delete(`/life-events/links/${id}`);
}

export async function getLifeEventScenarios(params: ScenarioParameters): Promise<ScenarioComparison> {
    return (await api.get<ScenarioComparison>('/life-events/scenarios', { params })).data;
}
