import { createContext, useContext } from 'react';
import type { AppNotification } from '../api/notifications';

/** The notification kind for updating the budget from the goal. */
export const GOAL_REFLECTION = 'goal_reflection';

export interface NotificationState {
    items: AppNotification[];
    hiddenCount: number;
    /** Recompute now (after something that may answer a notification). */
    refresh: () => void;
    /** 後で確認 for a number of days, or 見送り. */
    snooze: (id: number, days: number) => void;
    dismiss: (id: number) => void;
}

export const NotificationContext = createContext<NotificationState>({
    items: [], hiddenCount: 0, refresh: () => {}, snooze: () => {}, dismiss: () => {},
});

export function useNotifications(): NotificationState {
    return useContext(NotificationContext);
}
