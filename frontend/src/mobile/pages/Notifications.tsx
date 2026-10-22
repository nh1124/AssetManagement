import { BellOff } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { AppNotification } from '../../api/notifications';
import { formatDateTime, useTimezone } from '../../studio/datetime';
import { useNotifications } from '../../studio/notificationContext';
import { Screen } from '../components/Layout';
import { Empty, focusRing } from '../components/ui';
import { tr } from '../../studio/i18n';

// Notification links are studio paths. These open here; the rest (closing a month, making the plan from
// the goal, data health, actions) need the studio's screens.
const MOBILE_PATHS: Record<string, string> = { '/automation/approvals': '/approvals', '/ledger/auto': '/ledger' };

function target(notification: AppNotification): { href: string; inApp: boolean } | null {
    if (!notification.link) return null;
    const [path, query] = notification.link.split('?');
    const mobile = MOBILE_PATHS[path];
    return mobile ? { href: `${mobile}${query ? `?${query}` : ''}`, inApp: true } : { href: `/studio${notification.link}`, inApp: false };
}

/** What waits for the user, with 開く, 後で and 見送り. */
export default function Notifications() {
    const { items, hiddenCount, snooze, dismiss } = useNotifications();
    const timezone = useTimezone();
    const navigate = useNavigate();
    const action = `min-h-11 rounded-lg px-3 text-xs font-medium ${focusRing}`;
    return <Screen title={tr('通知', 'Notifications')} back={-1}>
        {items.length === 0 && <Empty icon={<BellOff size={28} aria-hidden />} title={tr('通知はありません', 'No notifications')} body={hiddenCount ? tr(`後で確認にした通知が ${hiddenCount}件あります。`, `${hiddenCount} snoozed notification(s).`) : undefined} />}
        {items.map((notification) => {
            const link = target(notification);
            return <article key={notification.id} className="space-y-2 rounded-2xl bg-[var(--studio-surface)] p-4 shadow-[var(--mobile-shadow)]">
                <div>
                    <h2 className="text-sm font-semibold">{notification.title}</h2>
                    <p className="mt-1 text-sm text-[var(--studio-text-muted)]">{notification.body}</p>
                    {notification.created_at && <p className="mt-1 text-[11px] text-[var(--studio-text-faint)]">{formatDateTime(notification.created_at, timezone)}</p>}
                </div>
                <div className="flex flex-wrap justify-end gap-1.5">
                    <button type="button" onClick={() => dismiss(notification.id)} className={`${action} text-[var(--studio-text-muted)] active:bg-[var(--studio-bg)]`}>{tr('見送り', 'Dismiss')}</button>
                    <button type="button" onClick={() => snooze(notification.id, 1)} className={`${action} text-[var(--studio-text-muted)] active:bg-[var(--studio-bg)]`}>{tr('明日また', 'Tomorrow')}</button>
                    <button type="button" onClick={() => snooze(notification.id, 7)} className={`${action} text-[var(--studio-text-muted)] active:bg-[var(--studio-bg)]`}>{tr('1週間後', 'In a week')}</button>
                    {link && <button type="button" onClick={() => { if (link.inApp) navigate(link.href); else window.location.href = link.href; }}
                        className={`${action} bg-[var(--studio-accent)] text-white active:opacity-80`}>{link.inApp ? tr('開く', 'Open') : tr('PC版で開く', 'Open on desktop')}</button>}
                </div>
            </article>;
        })}
        {items.length > 0 && hiddenCount > 0 && <p className="px-1 text-xs text-[var(--studio-text-muted)]">{tr(`後で確認にした通知が ほかに ${hiddenCount}件あります。`, `${hiddenCount} more snoozed notification(s).`)}</p>}
    </Screen>;
}
