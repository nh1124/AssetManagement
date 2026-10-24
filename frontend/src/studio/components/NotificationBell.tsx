import { useState } from 'react';
import { Bell } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { AppNotification } from '../../api/notifications';
import ReflectionOverlay from '../pages/plan/ReflectionOverlay';
import { useClient } from '../../context/ClientContext';
import { buttonClass, primaryClass } from '../pages/db/forms';
import { formatDateTime, useTimezone } from '../datetime';
import { tr } from '../i18n';
import { GOAL_REFLECTION, useNotifications } from '../notificationContext';
import Overlay from './Overlay';

/** Inbox groups, in this order; a kind not listed here follows under its own name. */
const kindLabels = (): Record<string, string> => ({
    [GOAL_REFLECTION]: tr('計画への反映', 'Plan reflection'),
    plan_reflected: tr('計画の自動更新', 'Automatic plan updates'),
    approval_pending: tr('承認待ち', 'Awaiting approval'),
    unmatched: tr('自動取引', 'Automatic transactions'),
    data_health: tr('データの確認', 'Data check'),
});
const KIND_ORDER = Object.keys(kindLabels());

const badgeClass = 'min-w-4 rounded-full bg-[var(--studio-warning)] px-1 text-center text-[10px] font-semibold leading-4 text-white';

/** How many things a notification is about (requests, rows, issues), as its generator counted them. */
function reasonCount(item: AppNotification): number {
    return typeof item.payload.count === 'number' ? item.payload.count : 1;
}

function groupByKind(items: AppNotification[]): [string, AppNotification[]][] {
    const groups = new Map<string, AppNotification[]>();
    for (const item of items) groups.set(item.kind, [...(groups.get(item.kind) ?? []), item]);
    const rank = (kind: string) => (KIND_ORDER.includes(kind) ? KIND_ORDER.indexOf(kind) : KIND_ORDER.length);
    return [...groups].sort(([a], [b]) => rank(a) - rank(b));
}

/** The inbox: notifications grouped by kind; each opens its screen, waits, or is set aside.
 * buttonClass styles the bell for where it sits (the rail, or the header while the rail is shut). */
export default function NotificationBell({ buttonClass: bellClass }: { buttonClass: string }) {
    const { items, hiddenCount, snooze, dismiss, refresh } = useNotifications();
    const navigate = useNavigate();
    const timezone = useTimezone();
    const [open, setOpen] = useState(false);
    const [planning, setPlanning] = useState(false);
    const { clientId, currentClient } = useClient();
    const labels = kindLabels();
    return <>
        <button type="button" onClick={() => setOpen(true)} aria-label={tr(`通知 ${items.length}件`, `Notifications: ${items.length}`)} title={tr('通知', 'Notifications')}
            className={bellClass}>
            <Bell size={16} strokeWidth={1.75} />
            {items.length > 0 && <span className={`absolute -right-1 -top-1 ${badgeClass}`}>{items.length}</span>}
        </button>
        {open && <Overlay title={tr('通知', 'Notifications')} onClose={() => setOpen(false)}>
            <div className="space-y-5">
                {items.length === 0 && <p className="text-sm text-[var(--studio-text-muted)]">{tr('確認が必要な通知はありません。', 'Nothing needs your attention.')}</p>}
                {groupByKind(items).map(([kind, group]) => <section key={kind} className="space-y-2">
                    <h3 className="flex items-center gap-2 text-xs font-semibold text-[var(--studio-text-muted)]">
                        {labels[kind] ?? kind}
                        <span className={badgeClass}>{group.reduce((total, item) => total + reasonCount(item), 0)}</span>
                    </h3>
                    {group.map((item) => <article key={item.id} className="space-y-2 rounded-lg border border-[var(--studio-border)] p-4">
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <h4 className="text-sm font-semibold">{item.title}</h4>
                            {item.updated_at && <span className="text-xs text-[var(--studio-text-muted)]">{formatDateTime(`${item.updated_at}Z`, timezone)}</span>}
                        </div>
                        <ul className="list-disc space-y-1 pl-5 text-sm">
                            {item.body.split('\n').filter(Boolean).map((line, index) => <li key={index}>{line}</li>)}
                        </ul>
                        <div className="flex flex-wrap gap-2">
                            {item.kind === GOAL_REFLECTION
                                ? <button type="button" onClick={() => { setOpen(false); setPlanning(true); }} className={primaryClass}>{tr('反映の設定を開く', 'Open reflection settings')}</button>
                                : item.link && <button type="button" onClick={() => { setOpen(false); navigate(item.link as string); }} className={primaryClass}>{tr('開く', 'Open')}</button>}
                            <button type="button" onClick={() => snooze(item.id, 1)} className={buttonClass}>{tr('明日また確認', 'Remind me tomorrow')}</button>
                            <button type="button" onClick={() => snooze(item.id, 7)} className={buttonClass}>{tr('1週間後に確認', 'Remind me in a week')}</button>
                            <button type="button" onClick={() => dismiss(item.id)} className={buttonClass}>{tr('見送り', 'Dismiss')}</button>
                        </div>
                    </article>)}
                </section>)}
                {hiddenCount > 0 && <p className="text-xs text-[var(--studio-text-muted)]">{tr(`後で確認にした通知が${hiddenCount}件あります（時期が来ると表示されます）。`, `${hiddenCount} snoozed notification(s) will come back when they are due.`)}</p>}
            </div>
        </Overlay>}
        {planning && <ReflectionOverlay clientName={currentClient?.id === clientId ? currentClient.name : undefined}
            currency={currentClient?.general_settings?.currency || 'JPY'} onClose={() => { setPlanning(false); refresh(); }} />}
    </>;
}
