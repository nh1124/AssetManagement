import type { AutoTransactionInput } from '../../../types';

export function countEndDate(form: AutoTransactionInput): string | null {
    if (!form.start_date || !form.repeat_count || form.repeat_count < 1) return null;
    const [year, month, day] = form.start_date.split('-').map(Number);
    const clamp = (y: number, m: number, d: number) => new Date(Date.UTC(y, m - 1, Math.min(d, new Date(Date.UTC(y, m, 0)).getUTCDate())));
    const start = new Date(`${form.start_date}T00:00:00Z`);
    let end: Date;
    if (form.frequency === 'EveryNDays') {
        if (!form.frequency_days) return null;
        end = new Date(start.getTime() + (form.repeat_count - 1) * form.frequency_days * 86400000);
    } else if (form.frequency === 'Yearly') {
        const m = form.month_of_year || month;
        const d = form.day_of_month || day;
        const firstYear = year + Number(clamp(year, m, d) < start);
        end = clamp(firstYear + form.repeat_count - 1, m, d);
    } else {
        const d = form.day_of_month || day;
        const base = year * 12 + month - 1 + Number(clamp(year, month, d) < start) + form.repeat_count - 1;
        end = clamp(Math.floor(base / 12), base % 12 + 1, d);
    }
    return Number.isNaN(end.getTime()) ? null : end.toISOString().slice(0, 10);
}

export function scheduleLabel(entry: AutoTransactionInput): string {
    if (entry.repeat_mode === 'once') return `一回限り ${entry.start_date}`;
    const cycle = entry.frequency === 'Monthly' ? `毎月 ${entry.day_of_month}日`
        : entry.frequency === 'Yearly' ? `毎年 ${entry.month_of_year}月${entry.day_of_month}日` : `${entry.frequency_days}日ごと`;
    return cycle + (entry.repeat_mode === 'count' ? `・${entry.repeat_count}回` : '');
}
