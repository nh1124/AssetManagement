import { useClient } from '../context/ClientContext';

export function normalizeTimezone(value: unknown): string {
    if (typeof value !== 'string' || !value) return 'UTC';
    try {
        new Intl.DateTimeFormat('en', { timeZone: value });
        return value;
    } catch {
        return 'UTC';
    }
}

export function useTimezone(): string {
    const { clientId, currentClient } = useClient();
    return normalizeTimezone(currentClient?.id === clientId ? currentClient.general_settings?.timezone : undefined);
}

type DateValue = string | number | Date;

function instant(value: DateValue): Date {
    // The API's timestamps without an offset are UTC, not browser-local time.
    if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value) && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) {
        return new Date(`${value.replace(' ', 'T')}Z`);
    }
    return new Date(value);
}

function parts(value: Date, timezone: string, time = false): Record<string, string> {
    return Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
        timeZone: normalizeTimezone(timezone), year: 'numeric', month: '2-digit', day: '2-digit',
        ...(time ? { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' } as const : {}),
    }).formatToParts(value).map((part) => [part.type, part.value]));
}

export function clientToday(timezone = 'UTC'): string {
    return formatDate(new Date(), timezone);
}

export function formatDate(value: DateValue, timezone = 'UTC'): string {
    // A calendar date is not an instant. Never shift a recorded transaction date.
    if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    const date = instant(value);
    if (Number.isNaN(date.getTime())) return '—';
    const p = parts(date, timezone);
    return `${p.year}-${p.month}-${p.day}`;
}

export function formatDateTime(value: DateValue, timezone = 'UTC'): string {
    if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    const date = instant(value);
    if (Number.isNaN(date.getTime())) return '—';
    const p = parts(date, timezone, true);
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}
