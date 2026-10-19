import api from './index';

export interface LifeEventLinkInput {
    from_event_id: number;
    to_event_id: number;
    // Branches were abolished: a different story is a different scenario.
    kind: 'after';
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
    direction: 'expense' | 'income' | 'borrowing' | 'repayment';
    /** 資金の割り当て: each account's share in percent; the rest is the residual net worth's. */
    fundings: Array<{ account_id: number; share: number }>;
    incoming_link_id: number | null;
    interest_rate: number | null;
    borrowing_event_id: number | null;
    repeat_count: number | null;
}

export async function getLifeEventLinks(scenarioId?: number): Promise<LifeEventLink[]> {
    return (await api.get<LifeEventLink[]>('/life-events/links', { params: { scenario_id: scenarioId } })).data;
}

export async function createLifeEventLink(input: LifeEventLinkInput): Promise<LifeEventLink> {
    return (await api.post<LifeEventLink>('/life-events/links', input)).data;
}

export async function deleteLifeEventLink(id: number): Promise<void> {
    await api.delete(`/life-events/links/${id}`);
}
