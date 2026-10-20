export function addMonths(period: string, months: number): string {
    const index = Number(period.slice(0, 4)) * 12 + Number(period.slice(5, 7)) - 1 + months;
    return `${Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, '0')}`;
}

export const monthLabel = (period: string) => `${Number(period.slice(0, 4))}年${Number(period.slice(5, 7))}月`;

/** The month a screen shows: ?month=YYYY-MM, else this month. */
export const monthParam = (value: string | null, current: string) => (value && /^\d{4}-(0[1-9]|1[0-2])$/.test(value) ? value : current);
