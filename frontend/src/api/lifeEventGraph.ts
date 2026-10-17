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
    direction: 'expense' | 'income';
    account_id: number | null;
    incoming_link_id: number | null;
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
