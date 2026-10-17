import type { ReactNode } from 'react';
import type { GoalBudgetReminder } from '../../../api/goalBudget';

/** Reasons the budget may no longer follow the goal; reflecting again is always the user's step. */
export default function GoalReminders({ reminders, action }: { reminders: GoalBudgetReminder[]; action?: ReactNode }) {
    if (!reminders.length) return <p className="text-xs text-[var(--studio-text-muted)]">予算はゴールの最新の反映に沿っています。</p>;
    return <div role="status" className="space-y-2 rounded-lg border border-[var(--studio-warning)] p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-[var(--studio-warning)]">ゴールから予算を更新する時期です</p>
            {action}
        </div>
        <ul className="list-disc space-y-1 pl-5 text-sm">
            {reminders.map((row, index) => <li key={`${row.code}-${row.event_id ?? index}`}>{row.message}</li>)}
        </ul>
    </div>;
}
