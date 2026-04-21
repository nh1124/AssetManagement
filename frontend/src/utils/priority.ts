export const PRIORITY_LABELS: Record<1 | 2 | 3, string> = {
    1: 'High',
    2: 'Medium',
    3: 'Low',
};

export const PRIORITY_COLORS: Record<1 | 2 | 3, string> = {
    1: 'text-rose-400',
    2: 'text-amber-400',
    3: 'text-slate-400',
};

export function priorityLabel(priority: 1 | 2 | 3): string {
    return PRIORITY_LABELS[priority];
}
