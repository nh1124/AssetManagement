import type { ReactNode } from 'react';
import { buttonClass } from '../db/forms';
import { GOAL_REFLECTION, useNotifications } from '../../notificationContext';

/** The goal-reflection notification beside a reflect button, with 後で確認 and 見送り. */
export default function GoalReflectionNotice({ action }: { action?: ReactNode }) {
    const { items, snooze, dismiss } = useNotifications();
    const note = items.find((item) => item.kind === GOAL_REFLECTION);
    if (!note) return null;
    return <div role="status" className="space-y-2 rounded-lg border border-[var(--studio-warning)] p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-[var(--studio-warning)]">{note.title}</p>
            <div className="flex flex-wrap gap-2">
                {action}
                <button type="button" onClick={() => snooze(note.id, 1)} className={buttonClass}>明日また確認</button>
                <button type="button" onClick={() => snooze(note.id, 7)} className={buttonClass}>1週間後に確認</button>
                <button type="button" onClick={() => dismiss(note.id)} className={buttonClass}>見送り</button>
            </div>
        </div>
        <ul className="list-disc space-y-1 pl-5 text-sm">
            {note.body.split('\n').filter(Boolean).map((line, index) => <li key={index}>{line}</li>)}
        </ul>
    </div>;
}
