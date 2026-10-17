import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { decideNotification, listNotifications, syncNotifications, type NotificationListing } from '../../api/notifications';
import { clientToday, useTimezone } from '../datetime';
import { NotificationContext, type NotificationState } from '../notificationContext';

// Recomputing reads the goal and the budget; moving between screens should not
// redo it more often than this.
const SYNC_INTERVAL_MS = 30_000;

/** Keeps the client's notifications current while the studio is open. Mount once per client. */
export default function NotificationsProvider({ children }: { children: ReactNode }) {
    const timezone = useTimezone();
    const { pathname } = useLocation();
    const [listing, setListing] = useState<NotificationListing>({ items: [], hidden_count: 0 });
    const lastSync = useRef(0);
    const sync = useCallback((force: boolean) => {
        if (!force && Date.now() - lastSync.current < SYNC_INTERVAL_MS) return;
        lastSync.current = Date.now();
        // A failed sync leaves the last list in place; notifications never block a screen.
        void syncNotifications(clientToday(timezone).slice(0, 7)).then(setListing).catch(() => undefined);
    }, [timezone]);
    useEffect(() => { sync(false); }, [pathname, sync]);
    const decide = useCallback((id: number, action: 'snooze' | 'dismiss', until?: Date) => {
        void decideNotification(id, action, until).then(listNotifications).then(setListing).catch(() => undefined);
    }, []);
    const value = useMemo<NotificationState>(() => ({
        items: listing.items,
        hiddenCount: listing.hidden_count,
        refresh: () => sync(true),
        snooze: (id, days) => {
            const until = new Date();
            until.setDate(until.getDate() + days);
            decide(id, 'snooze', until);
        },
        dismiss: (id) => decide(id, 'dismiss'),
    }), [listing, sync, decide]);
    return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>;
}
