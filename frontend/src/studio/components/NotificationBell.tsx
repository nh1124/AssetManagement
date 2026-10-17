import { useState } from 'react';
import { Bell } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import GoalBudgetReflection from '../pages/goals/GoalBudgetReflection';
import { buttonClass, primaryClass } from '../pages/db/forms';
import { formatDateTime, useTimezone } from '../datetime';
import { GOAL_REFLECTION, useNotifications } from '../notificationContext';
import Overlay from './Overlay';

/** The header's notification count and list; each one opens its action, waits, or is set aside. */
export default function NotificationBell() {
    const { items, hiddenCount, snooze, dismiss, refresh } = useNotifications();
    const navigate = useNavigate();
    const timezone = useTimezone();
    const [open, setOpen] = useState(false);
    const [reflecting, setReflecting] = useState(false);
    return <>
        <button type="button" onClick={() => setOpen(true)} aria-label={`通知 ${items.length}件`} title="通知"
            className="relative rounded p-2 text-[var(--studio-text-muted)] transition-colors hover:bg-[var(--studio-accent-soft)] hover:text-[var(--studio-text)]">
            <Bell size={16} />
            {items.length > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-[var(--studio-warning)] px-1 text-center text-[10px] font-semibold leading-4 text-white">{items.length}</span>}
        </button>
        {open && <Overlay title="通知" onClose={() => setOpen(false)}>
            <div className="space-y-3">
                {items.length === 0 && <p className="text-sm text-[var(--studio-text-muted)]">確認が必要な通知はありません。</p>}
                {items.map((item) => <section key={item.id} className="space-y-2 rounded-lg border border-[var(--studio-border)] p-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <h3 className="text-sm font-semibold">{item.title}</h3>
                        {item.updated_at && <span className="text-xs text-[var(--studio-text-muted)]">{formatDateTime(`${item.updated_at}Z`, timezone)}</span>}
                    </div>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                        {item.body.split('\n').filter(Boolean).map((line, index) => <li key={index}>{line}</li>)}
                    </ul>
                    <div className="flex flex-wrap gap-2">
                        {item.kind === GOAL_REFLECTION
                            ? <button type="button" onClick={() => { setOpen(false); setReflecting(true); }} className={primaryClass}>予算に反映</button>
                            : item.link && <button type="button" onClick={() => { setOpen(false); navigate(item.link as string); }} className={primaryClass}>開く</button>}
                        <button type="button" onClick={() => snooze(item.id, 1)} className={buttonClass}>明日また確認</button>
                        <button type="button" onClick={() => snooze(item.id, 7)} className={buttonClass}>1週間後に確認</button>
                        <button type="button" onClick={() => dismiss(item.id)} className={buttonClass}>見送り</button>
                    </div>
                </section>)}
                {hiddenCount > 0 && <p className="text-xs text-[var(--studio-text-muted)]">後で確認にした通知が{hiddenCount}件あります（時期が来ると表示されます）。</p>}
            </div>
        </Overlay>}
        {reflecting && <GoalBudgetReflection onClose={() => { setReflecting(false); refresh(); }} />}
    </>;
}
