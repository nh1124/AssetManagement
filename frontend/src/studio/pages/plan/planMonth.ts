import { useState } from 'react';
import { clientToday, useTimezone } from '../../datetime';

const KEY = 'studio.plan.month';
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

/** The plan's month, shared by its tabs (計画と実績・取り置き・自動取引) for the visit; this month by default. */
export function usePlanMonth(): [string, (month: string) => void] {
    const timezone = useTimezone();
    const [stored, setStored] = useState<string | null>(() => {
        try { return sessionStorage.getItem(KEY); } catch { return null; }
    });
    const month = stored && MONTH.test(stored) ? stored : clientToday(timezone).slice(0, 7);
    const change = (next: string) => {
        setStored(next);
        try { sessionStorage.setItem(KEY, next); } catch { /* storage unavailable: the month lasts for this tab only */ }
    };
    return [month, change];
}
