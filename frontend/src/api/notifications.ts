import api from './index';

export type NotificationStatus = 'open' | 'snoozed' | 'dismissed' | 'done';

export interface AppNotification {
    id: number;
    kind: string;
    title: string;
    body: string;
    payload: Record<string, unknown>;
    /** A studio path the notification is about. */
    link: string | null;
    status: NotificationStatus;
    snoozed_until: string | null;
    created_at: string | null;
    updated_at: string | null;
}

export interface NotificationListing {
    items: AppNotification[];
    /** Snoozed notifications still waiting for their time. */
    hidden_count: number;
}

export async function listNotifications(): Promise<NotificationListing> {
    return (await api.get<NotificationListing>('/notifications')).data;
}

/** Recompute every notification kind for the month, then list. */
export async function syncNotifications(period: string): Promise<NotificationListing> {
    return (await api.post<NotificationListing>('/notifications/sync', null, { params: { period } })).data;
}

/** 後で確認 (snooze until), 見送り (dismiss) or reopen. */
export async function decideNotification(id: number, action: 'snooze' | 'dismiss' | 'reopen', until?: Date): Promise<AppNotification> {
    return (await api.post<AppNotification>(`/notifications/${id}/decision`, { action, until: until?.toISOString() })).data;
}
